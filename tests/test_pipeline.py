"""Pruebas offline con fixtures SINTETICOS (tests/fixtures). No usan la red."""
import shutil
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
import comun as C  # noqa: E402
import detectar_cambios as D  # noqa: E402
import extraer as E  # noqa: E402
import validar as V  # noqa: E402

FIX = AQUI / "fixtures"
leer = lambda n: (FIX / n).read_text(encoding="utf-8")  # noqa: E731


class R:
    def __init__(self, status=200, text="", exc=None):
        self.status_code, self.text, self.encoding, self.apparent_encoding, self.exc = status, text, "utf-8", "utf-8", exc


class FakeSession:
    """Sesión falsa: sirve fixtures por URL; registra cada solicitud."""

    def __init__(self, paginas, robots=None):
        self.headers, self.paginas, self.robots, self.pedidos = {}, paginas, robots, []

    def get(self, url, timeout=None):
        self.pedidos.append(url)
        if url.endswith("/robots.txt"):
            if self.robots is None:
                return R(404)
            return R(200, self.robots) if isinstance(self.robots, str) else R(self.robots)
        return self.paginas.get(url, R(404))


def paginas(valor_indice="61,5"):
    a = leer("municipio_prueba_a.html").replace("61,5", valor_indice)
    base = "https://municipiosargentinos.net"
    return {
        base + "/": R(text=leer("portada_prueba.html")),
        base + "/metodologia/": R(text=leer("metodologia_prueba.html")),
        base + "/municipio/avellaneda/": R(text=a),
        base + "/municipio/tres-de-febrero/": R(text="<html><p>sin tablas</p></html>"),
        # Vicente López: 403 (restricción de acceso)
        base + "/municipio/vicente-lopez/": R(403),
    }


@pytest.fixture()
def dirs(tmp_path):
    return tmp_path / "actual", tmp_path / "hist"


def correr(dirs, pag, fecha="2026-10-21", robots=None, municipios="avellaneda,tres_de_febrero,vicente_lopez"):
    ses = FakeSession(pag, robots)
    cli = E.Cliente(pausa=0, session=ses)
    res = E.ejecutar(municipios, fecha, cliente=cli, dir_actual=dirs[0], dir_historico=dirs[1])
    return res, ses


# ---------------------------------------------------------------- parsers
def test_parse_numeros_es_ar():
    assert C.parse_num("1.234,5") == 1234.5 and C.parse_num("61,5") == 61.5 and C.parse_num("") is None
    assert C.parse_num("1.234.567") == 1234567 and C.parse_num("abc") is None


def test_interpretar_pagina_sintetica():
    h, contra = E.interpretar_pagina(leer("municipio_prueba_a.html"))
    assert h["indice_global"]["valor"] == 61.5 and h["ranking_provincial"]["valor"] == 12
    assert h["transparencia_semaforo"]["valor"] == "VERDE" and h["presupuesto_publicado"]["valor"] == "SI"
    assert h["homicidios_tasa_100k"]["valor"] == 3.4
    assert h["fecha_actualizacion_portal"]["valor"] == "2026-10-15"
    assert "control_puntaje" in h and not contra
    assert "gas" not in " ".join(h)  # faltantes no se inventan


def test_etiqueta_exacta_no_subcadena():
    h, _ = E.interpretar_pagina("<table><tr><td>Transparencia ASAP</td><td>80</td></tr></table>")
    assert "transparencia_puntaje" not in h


def test_contradiccion_interna():
    _, c = E.interpretar_pagina("<table><tr><td>Ranking provincial</td><td>3</td></tr><tr><td>Posición provincial</td><td>4</td></tr></table>")
    assert c and c[0]["campo"] == "ranking_provincial"


def test_enlaces_exactos_y_ambiguos():
    enl = E.descubrir_enlaces(leer("portada_prueba.html"), E.BASE_URL)
    assert E.encontrar_pagina_municipio(enl, "Vicente López")[0].endswith("/vicente-lopez/")
    assert E.encontrar_pagina_municipio(enl, "Morón")[0] is None
    dup = enl + [("Avellaneda", "https://municipiosargentinos.net/otra/avellaneda/")]
    assert "ambiguos" in E.encontrar_pagina_municipio(dup, "Avellaneda")[1]


def test_metodologia():
    assert all(E.verificar_metodologia(leer("metodologia_prueba.html"))["ponderaciones"].values())


def test_csv_formato_y_formulas():
    s = C.serializar_csv([{"municipio_id": "=HYPERLINK(1)", "snapshot_id": 3.5}], ["municipio_id", "snapshot_id"])
    assert "'=HYPERLINK" in s and "3,5" in s
    assert C.sanear_celda("-3,5") == "-3,5"


# ------------------------------------------------------------- robots / http
def test_robots_prohibe_y_no_se_consulta(dirs):
    res, ses = correr(dirs, paginas(), robots="User-agent: *\nDisallow: /")
    assert all(not p.endswith("/municipio/avellaneda/") for p in ses.pedidos)
    inc = C.leer_csv(dirs[0] / C.F_INCIDENCIAS)
    assert any(i["tipo_incidencia"] == "PROHIBIDO_POR_ROBOTS" for i in inc)


def test_robots_no_verificable_falla_cerrada(dirs):
    res, ses = correr(dirs, paginas(), robots=500)
    assert not any("/municipio/" in p for p in ses.pedidos)
    assert any(i["tipo_incidencia"] == "ROBOTS_NO_VERIFICABLE" for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS))


def test_bloqueo_sin_red(dirs):
    res = E.ejecutar("avellaneda", "2026-10-21", cliente=E.ClienteBloqueado("403 CONNECT"),
                     dir_actual=dirs[0], dir_historico=dirs[1])
    assert res["solicitudes_http"] == 0
    assert {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)} == {"ACCESO_BLOQUEADO_RED"}


# ------------------------------------------------------------------ pipeline
def test_extraccion_completa_trazabilidad_y_validacion(dirs):
    res, _ = correr(dirs, paginas())
    assert res["municipios"]["Avellaneda"]["estado"] == "PARCIAL"
    assert res["municipios"]["Vicente López"]["estado"] == "SIN_DATOS"
    assert res["linea_base"] and res["alertas_nuevas"] == 0
    err, adv, datos = V.validar(dirs[0], "prueba")
    assert err == [], err
    assert len(datos[C.F_INDICADORES]) == 1
    tipos = {i["tipo_incidencia"] for i in datos[C.F_INCIDENCIAS]}
    assert {"ACCESO_DENEGADO_HTTP", "DATOS_NO_ENCONTRADOS"} <= tipos
    assert datos[C.F_ALERTAS] == []
    for n in C.ESQUEMAS:
        assert (dirs[0] / n).read_bytes().startswith(b"\xef\xbb\xbf")


def test_modo_completo_exige_40(dirs):
    correr(dirs, paginas())
    err, _, _ = V.validar(dirs[0], "completo")
    assert any("exactamente 40" in e for e in err)


def test_reejecucion_sin_cambios_no_escribe(dirs):
    correr(dirs, paginas(), fecha="2026-10-21")
    antes = {n: (dirs[0] / n).read_bytes() for n in C.ESQUEMAS}
    res, _ = correr(dirs, paginas(), fecha="2026-10-28")
    assert res["archivos_escritos"] == [] and res["alertas_nuevas"] == 0
    assert antes == {n: (dirs[0] / n).read_bytes() for n in C.ESQUEMAS}


def test_cambio_genera_alerta_e_historial(dirs):
    correr(dirs, paginas("61,5"), fecha="2026-10-21")
    res, _ = correr(dirs, paginas("45"), fecha="2026-10-28")
    al = C.leer_csv(dirs[0] / C.F_ALERTAS)
    assert len(al) == 1 and al[0]["variable"] == "indice_global"
    assert al[0]["variacion_absoluta"] == "-16,5" and al[0]["variacion_relativa_pct"].startswith("-26,8")
    assert al[0]["severidad"] == "MEDIA"
    assert (dirs[1] / "2026-10-28" / C.F_INDICADORES).exists()  # versión previa conservada
    assert V.validar(dirs[0], "prueba")[0] == []


def test_falla_temporal_no_borra_datos_validos(dirs):
    correr(dirs, paginas(), fecha="2026-10-21")
    ant = C.leer_csv(dirs[0] / C.F_INDICADORES)
    pag = paginas(); pag["https://municipiosargentinos.net/municipio/avellaneda/"] = R(500)
    correr(dirs, pag, fecha="2026-10-28")
    assert C.leer_csv(dirs[0] / C.F_INDICADORES) == ant
    assert C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]["indice_global"] == "61,5"


def test_alertas_semaforo_y_umbral():
    r = D.cargar_reglas()
    def f(snap, ind, sem): return {"municipio_id": "ba_x", "snapshot_id": snap, "indice_global": ind, "transparencia_semaforo": sem}
    assert D.alertas_indicadores([f("s1", "50", "VERDE")], r, "d", "s1") == []  # línea de base
    a = D.alertas_indicadores([f("s1", "50", "VERDE"), f("s2", "55", "AMARILLO")], r, "d", "s2")
    assert [x["categoria_alerta"] for x in a] == ["CAMBIO_SEMAFORO"]  # +5 < umbral, pero semáforo sí
    assert D.variaciones(0, 5) == (5, None)


def test_validador_detecta_errores(dirs):
    correr(dirs, paginas())
    p = dirs[0] / C.F_MUNICIPIOS
    filas = C.leer_csv(p); filas[0].update(total_bancas="10", bancas_oficialismo="3", bancas_aliadas="1",
                                           bancas_oposicion="1", bancas_independientes="1", bancas_sin_verificar="1",
                                           indice_global="150", transparencia_semaforo="AZUL")
    C.escribir_csv(p, filas + [dict(filas[0])], C.ESQUEMAS[C.F_MUNICIPIOS])
    txt = "\n".join(V.validar(dirs[0], "prueba")[0])
    assert "bancas suman" in txt and "fuera de 0-100" in txt and "semáforo inválido" in txt and "duplicada" in txt


def test_config_40_municipios_unicos():
    ids = [m["municipio_id"] for m in C.cargar_municipios_cfg()]
    assert len(ids) == len(set(ids)) == 40
