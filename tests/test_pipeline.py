"""Pruebas offline con fixtures SINTETICOS (tests/fixtures). No usan la red."""
import re
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
    def __init__(self, status=200, text="", exc=None, url=None, history=(), location=None):
        self.status_code, self.text, self.encoding, self.apparent_encoding, self.exc = status, text, "utf-8", "utf-8", exc
        self.url, self.history, self.headers = url, list(history), ({"Location": location} if location else {})


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
        r = self.paginas.get(url, R(404))
        if r.url is None:
            r.url = url
        return r


def paginas(valor_indice="61,5"):
    a = leer("municipio_prueba_a.html").replace("61,5", valor_indice)
    base = "https://municipiosargentinos.net"
    return {
        base + "/": R(text=leer("portada_prueba.html")),
        base + "/metodologia/": R(text=leer("metodologia_prueba.html")),
        base + "/m/avellaneda/": R(text=a),
        base + "/m/tres-de-febrero/": R(text="<html><p>sin tablas</p></html>"),
        # Vicente López: 403 (restricción de acceso)
        base + "/m/vicente-lopez/": R(403),
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
    assert all(not p.endswith("/m/avellaneda/") for p in ses.pedidos)
    inc = C.leer_csv(dirs[0] / C.F_INCIDENCIAS)
    assert any(i["tipo_incidencia"] == "PROHIBIDO_POR_ROBOTS" for i in inc)


def test_robots_no_verificable_falla_cerrada(dirs):
    res, ses = correr(dirs, paginas(), robots=500)
    assert not any("/m/" in p for p in ses.pedidos)
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
    pag = paginas(); pag["https://municipiosargentinos.net/m/avellaneda/"] = R(500)
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


# ------------------------------------------- resolución de URL, errores, informe
BASE = "https://municipiosargentinos.net"
FICHA = BASE + "/m/avellaneda/"


def inc(dirs):
    return C.leer_csv(dirs[0] / C.F_INCIDENCIAS)


def test_url_configurada_tiene_prioridad_y_no_consulta_portada(dirs):
    res, ses = correr(dirs, paginas(), municipios="avellaneda")
    assert BASE + "/" not in ses.pedidos and FICHA in ses.pedidos
    assert res["municipios"]["Avellaneda"]["url_origen"] == "configurada"
    assert res["municipios"]["Avellaneda"]["campos_extraidos"] >= 6


def test_404_en_configurada_usa_respaldo_de_portada_y_registra_ausencia(dirs):
    pag = paginas()
    pag[FICHA] = R(404)
    pag[BASE + "/otra/avellaneda/"] = R(text=leer("municipio_prueba_a.html"))
    pag[BASE + "/"] = R(text='<a href="/otra/avellaneda/">Avellaneda</a>')
    res, _ = correr(dirs, pag, municipios="avellaneda")
    assert res["municipios"]["Avellaneda"]["url_origen"] == "descubierta" and res["municipios"]["Avellaneda"]["campos_extraidos"] > 0
    assert res["paginas_ausentes"] == 1
    assert "PAGINA_AUSENTE" in {i["tipo_incidencia"] for i in inc(dirs)}


@pytest.mark.parametrize("estado,tipo", [(403, "ACCESO_DENEGADO_HTTP"), (429, "LIMITE_SOLICITUDES_429"),
                                         (500, "ERROR_HTTP"), (401, "ACCESO_DENEGADO_HTTP")])
def test_errores_no_son_pagina_no_encontrada(dirs, estado, tipo):
    pag = paginas()
    pag[FICHA] = R(estado)
    res, ses = correr(dirs, pag, municipios="avellaneda")
    tipos = [i["tipo_incidencia"] for i in inc(dirs) if i["municipio_id"] == "ba_avellaneda"]
    assert tipo in tipos and "PAGINA_NO_ENCONTRADA" not in tipos and "PAGINA_AUSENTE" not in tipos
    assert ses.pedidos.count(FICHA) == 1 and BASE + "/" not in ses.pedidos  # sin reintento ni respaldo
    d = next(i for i in inc(dirs) if i["tipo_incidencia"] == tipo)["descripcion"]
    assert f"HTTP {estado}" in d and "url_final=" in d and "redirecciones" in d
    assert res["respuestas_bloqueadas"] == (1 if estado != 500 else 0) and res["municipios_con_datos"] == 0


def test_redireccion_interna_se_registra_y_se_sanea_la_url(dirs):
    pag = paginas()
    destino = BASE + "/m/avellaneda-2/"
    pag[FICHA] = R(text=leer("municipio_prueba_a.html"), url=destino + "?token=SECRETO#x",
                   history=[R(301, url=FICHA, location=destino + "?token=SECRETO")])
    res, _ = correr(dirs, pag, municipios="avellaneda")
    f = C.leer_csv(dirs[0] / C.F_FUENTES)
    assert f and all(x["documento_url"] == destino for x in f if x["entidad"] == "indicador_portal")
    assert "SECRETO" not in "".join((dirs[0] / n).read_text(encoding="utf-8-sig") for n in C.ESQUEMAS)
    assert any(e["url"] == FICHA for e in res["detalle_solicitudes"])


def test_redireccion_a_otro_dominio_no_se_sigue(dirs):
    pag = paginas()
    pag[FICHA] = R(text="<html>x</html>", url="https://otro.example/x?a=1",
                   history=[R(302, url=FICHA, location="https://otro.example/x?a=1")])
    res, _ = correr(dirs, pag, municipios="avellaneda")
    i = next(i for i in inc(dirs) if i["tipo_incidencia"] == "REDIRECCION_EXTERNA")
    assert "302 https://otro.example/x" in i["descripcion"] and "a=1" not in i["descripcion"]
    assert res["municipios_con_datos"] == 0


def test_pagina_no_encontrada_solo_si_portada_ok_sin_url_y_sin_enlace(dirs, tmp_path):
    cfg = tmp_path / "cfg.csv"
    cfg.write_text("\ufeffmunicipio_id;municipio;indec_codigo;seccion_electoral;url_portal_municipio\n"
                   "ba_moron;Morón;;;\nba_avellaneda;Avellaneda;;;\n", encoding="utf-8")
    pag = paginas()
    ses = FakeSession(pag)
    res = E.ejecutar("moron", "2026-10-21", cliente=E.Cliente(pausa=0, session=ses), dir_actual=dirs[0],
                     dir_historico=dirs[1], cfg_path=cfg)
    assert [i["tipo_incidencia"] for i in inc(dirs) if i["municipio_id"] == "ba_moron"] == ["PAGINA_NO_ENCONTRADA"]
    # si la portada falla, NO es "no encontrada"
    d2 = (dirs[0].parent / "a2", dirs[0].parent / "h2")
    ses2 = FakeSession({BASE + "/": R(503)})
    E.ejecutar("moron", "2026-10-21", cliente=E.Cliente(pausa=0, session=ses2), dir_actual=d2[0], dir_historico=d2[1], cfg_path=cfg)
    assert [i["tipo_incidencia"] for i in C.leer_csv(d2[0] / C.F_INCIDENCIAS) if i["municipio_id"] == "ba_moron"] == ["ERROR_HTTP"]


def test_config_incluye_las_tres_urls_verificadas():
    u = {m["municipio_id"]: m["url_portal_municipio"] for m in C.cargar_municipios_cfg()}
    assert u["ba_avellaneda"] == BASE + "/m/avellaneda/"
    assert u["ba_vicente_lopez"] == BASE + "/m/vicente-lopez/"
    assert u["ba_tres_de_febrero"] == BASE + "/m/tres-de-febrero/"
    # Config actual: 40 municipios, cada uno con su URL de ficha (únicas, bajo /m/) y su INDEC del portal (06xxx, único).
    cfg = C.cargar_municipios_cfg()
    assert len(cfg) == 40 and all(re.fullmatch(re.escape(BASE) + r"/m/[a-z0-9\-]+/", v) for v in u.values())
    assert len(set(u.values())) == 40
    codigos = [m["indec_codigo"] for m in cfg]
    assert all(re.fullmatch(r"06\d{3}", c) for c in codigos) and len(set(codigos)) == 40


def test_parsing_json_embebido_y_etiquetas_no_reconocidas():
    h, _ = E.interpretar_pagina(leer("ficha_json_prueba.html"))
    assert h["indice_global"]["valor"] == 48.5 and h["ranking_provincial"]["valor"] == 30
    assert h["transparencia_semaforo"]["valor"] == "AMARILLO" and h["seguridad_puntaje"]["valor"] == 62.5
    assert any("campo desconocido" in x.lower() for x in E.etiquetas_no_reconocidas(leer("ficha_json_prueba.html")))


def test_descubre_rutas_m_en_html_crudo():
    urls = [u for _, u in E.descubrir_enlaces(leer("ficha_json_prueba.html"), BASE + "/")]
    assert BASE + "/m/merlo/" in urls
    assert E.encontrar_pagina_municipio([("", u) for u in urls], "Merlo")[0] == BASE + "/m/merlo/"


def test_campos_ausentes_no_pisan_valores_historicos(dirs):
    correr(dirs, paginas("61,5"), fecha="2026-10-21", municipios="avellaneda")
    pag = paginas()
    pag[FICHA] = R(text="<table><tr><td>Índice municipal general</td><td>61,5</td></tr></table>")  # ficha parcial
    res, _ = correr(dirs, pag, fecha="2026-10-28", municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert m["transparencia_puntaje"] == "70,25" and m["control_puntaje"] == "40" and m["indice_global"] == "61,5"
    assert len(C.leer_csv(dirs[0] / C.F_INDICADORES)) == 1 and res["alertas_nuevas"] == 0
    # el valor vuelve a cambiar tras una captura parcial: se compara contra el último valor conocido
    pag[FICHA] = R(text=leer("municipio_prueba_a.html").replace("70,25", "50"))
    correr(dirs, pag, fecha="2026-11-04", municipios="avellaneda")
    assert [a["variable"] for a in C.leer_csv(dirs[0] / C.F_ALERTAS)] == ["transparencia_puntaje"]
    assert V.validar(dirs[0], "prueba")[0] == []


def test_informe_ejecucion_diferencia_categorias(dirs):
    pag = paginas()
    pag[BASE + "/m/vicente-lopez/"] = R(403)
    pag[BASE + "/m/tres-de-febrero/"] = R(404)
    res, _ = correr(dirs, pag)
    assert (res["solicitudes_exitosas"], res["respuestas_bloqueadas"], res["municipios_con_datos"]) == (3, 1, 1)
    assert res["paginas_ausentes"] == 1
    md = E.informe_ejecucion(res)
    for t in ("con éxito", "bloqueadas", "ausentes", "efectivamente extraídos", "ACCESO_DENEGADO_HTTP"):
        assert t in md


# ------------------------------------------------ fichas con las secciones reales
REF = {"a": 56.2, "b": 82.2, "c": 65.7}   # índices de comprobación: SOLO en pruebas
ESPERADO = {
    "a": dict(transparencia_puntaje=40, transparencia_relevamiento_propio=35, transparencia_asap=45,
              servicios_seguridad_puntaje=52, seguridad_puntaje=61, control_puntaje=33, ranking_provincial=101,
              ranking_pares=9, transparencia_semaforo="AMARILLO", poblacion_2022=342677, seccion_electoral="Tercera",
              intendente_nombre_completo="Ana Ficticia Prueba", partido_politico="Partido de Prueba",
              frente_electoral="Frente de Prueba", fecha_asuncion="2023-12-10", ejercicio_fallo_htc="2021", señales_control=3),
    "b": dict(transparencia_puntaje=88, transparencia_relevamiento_propio=90, transparencia_asap=75,
              servicios_seguridad_puntaje=80, seguridad_puntaje=84.5, control_puntaje=70, ranking_provincial=3,
              transparencia_semaforo="VERDE", poblacion_2022=269420, intendente_nombre_completo="Luis Ficticio Prueba",
              partido_politico="Partido de Prueba", frente_electoral="Frente de Prueba", ejercicio_fallo_htc="2021"),
    "c": dict(transparencia_puntaje=70, transparencia_relevamiento_propio=66, servicios_seguridad_puntaje=50,
              seguridad_puntaje=58, control_puntaje=62, ranking_provincial=44, poblacion_2022=360000,
              intendente_nombre_completo="Carla Ficticia Prueba", partido_politico="Partido de Prueba"),
}


@pytest.mark.parametrize("k", ["a", "b", "c"])
def test_fichas_de_referencia(k):
    h, contra = E.interpretar_pagina(leer(f"ficha_ref_{k}.html"))
    assert h["indice_global"]["valor"] == REF[k]
    for campo, esperado in ESPERADO[k].items():
        assert h[campo]["valor"] == esperado, (campo, h.get(campo))
    assert contra == []


def test_pilares_no_se_confunden_y_se_rechazan_pesos():
    h, _ = E.interpretar_pagina(leer("ficha_ref_a.html"))
    assert len({h[c]["valor"] for c in ("transparencia_puntaje", "transparencia_relevamiento_propio", "transparencia_asap",
                                        "servicios_seguridad_puntaje", "seguridad_puntaje", "control_puntaje")}) == 6
    assert 50 not in (h["transparencia_puntaje"]["valor"], h["control_puntaje"]["valor"])  # 50 % / 15 % son pesos


def test_valores_trampa_se_rechazan_y_se_informan():
    a = E.analizar_ficha(leer("fichas_trampa.html"))
    assert "transparencia_puntaje" not in a["hallados"] and "seguridad_puntaje" not in a["hallados"]
    assert "poblacion_2022" not in a["hallados"]  # sin año 2022 verificable
    txt = " | ".join(a["rechazados"])
    assert "escala 50" in txt and "fuera de 0-100" in txt and "sin año 2022" in txt


def test_intendente_inferido_por_posicion_queda_con_confianza_baja():
    h, _ = E.interpretar_pagina(leer("ficha_ref_a.html"))
    assert h["intendente_nombre_completo"]["confianza"] == "BAJO" and "posición" in h["intendente_nombre_completo"]["obs"]
    assert E.interpretar_pagina(leer("ficha_ref_b.html"))[0]["intendente_nombre_completo"]["confianza"] == "MEDIO"


def test_valores_de_referencia_no_estan_en_codigo_ni_datos():
    prohibidos = ["56,2", "82,2", "65,7", "56.2", "82.2", "65.7"]
    for ruta in [*(AQUI.parent / "scripts").glob("*.py"), *(AQUI.parent / "config").glob("*"),
                 *(AQUI.parent / "data" / "actual").glob("*.csv")]:
        txt = ruta.read_text(encoding="utf-8-sig")
        assert not any(p in txt for p in prohibidos), ruta


def test_pipeline_con_ficha_real_extrae_a_01_y_04_con_trazabilidad(dirs):
    pag = paginas()
    pag[FICHA] = R(text=leer("ficha_ref_a.html"))
    res, _ = correr(dirs, pag, municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert m["indice_global"] == "56,2" and m["intendente_nombre_completo"] == "Ana Ficticia Prueba"
    assert m["partido_politico"] == "Partido de Prueba" and m["poblacion_2022"] == "342677" and m["fecha_asuncion"] == "2023-12-10"
    assert m["intendente_nombre"] == "" and m["coalicion_actual"] == ""   # no se inventa ni se separa
    i = C.leer_csv(dirs[0] / C.F_INDICADORES)[0]
    assert i["transparencia_relevamiento_propio"] == "35" and i["servicios_seguridad_puntaje"] == "52"
    f = [x for x in C.leer_csv(dirs[0] / C.F_FUENTES) if x["campo_verificado"] == "intendente_nombre_completo"][0]
    assert f["nivel_confianza"] == "BAJO" and "pendiente de verificación" in f["observaciones"] or "inferido" in f["observaciones"]
    d = next(x for x in inc(dirs) if x["tipo_incidencia"] == "DATOS_NO_ENCONTRADOS")["descripcion"]
    assert "Secciones vistas" in d and "Etiquetas no reconocidas" in d
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_diagnostico_guarda_html_y_estructura(dirs, tmp_path):
    pag = paginas()
    pag[FICHA] = R(text=leer("ficha_ref_b.html"))
    ses = FakeSession(pag)
    E.ejecutar("avellaneda", "2026-10-21", cliente=E.Cliente(pausa=0, session=ses), dir_actual=dirs[0],
               dir_historico=dirs[1], dir_diagnostico=tmp_path / "diag")
    est = (tmp_path / "diag" / "ba_avellaneda_estructura.txt").read_text(encoding="utf-8")
    assert "Datos clave" in est and "Cómo se compone su índice" in est and "indice_global = 82.2" in est
    assert (tmp_path / "diag" / "ba_avellaneda.html").exists()


# ------------------------------------------- formato numérico: miles vs. decimales
def _ficha_a_01_05(dirs):
    pag = paginas()
    pag[FICHA] = R(text=leer("ficha_ref_a.html"))
    correr(dirs, pag, municipios="avellaneda")


def test_valor_obtenido_preserva_miles_y_pasa_la_validacion(dirs):
    _ficha_a_01_05(dirs)
    p = dirs[0] / C.F_FUENTES
    filas = C.leer_csv(p)
    pob = next(f for f in filas if f["campo_verificado"] == "poblacion_2022")
    assert pob["valor_obtenido"].startswith("342.677")          # texto original, con separador de miles
    for orig in ("342.677", "367.554", "282.280", "364.176", "56.2", "1.234,5"):
        pob["valor_obtenido"] = orig                              # genérico: se preserva sin reglas decimales
        C.escribir_csv(p, filas, C.ESQUEMAS[C.F_FUENTES])
        assert V.validar(dirs[0], "prueba")[0] == [], orig
    assert C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]["poblacion_2022"] == "342677"


@pytest.mark.parametrize("archivo,col,valor,esperado", [
    (C.F_MUNICIPIOS, "poblacion_2022", "367554", None),
    (C.F_MUNICIPIOS, "poblacion_2022", "367.554", "separador de miles"),
    (C.F_MUNICIPIOS, "indice_global", "56,2", None),
    (C.F_MUNICIPIOS, "indice_global", "56.2", "decimal con punto"),
    (C.F_MUNICIPIOS, "indice_global", "1.056,2", "separador de miles"),
    (C.F_MUNICIPIOS, "ranking_provincial", "12,5", "no numérico"),
    (C.F_MUNICIPIOS, "seguridad_puntaje", "abc", "no numérico"),
])
def test_columnas_tipadas_distinguen_miles_y_decimales(dirs, archivo, col, valor, esperado):
    _ficha_a_01_05(dirs)
    p = dirs[0] / archivo
    filas = C.leer_csv(p)
    filas[0][col] = valor
    C.escribir_csv(p, filas, C.ESQUEMAS[archivo])
    errores = [e for e in V.validar(dirs[0], "prueba")[0] if col in e and ("miles" in e or "decimal" in e or "no numérico" in e)]
    if esperado is None:
        assert errores == []
    else:
        assert errores and esperado in errores[0]


def test_error_numerico_unitario():
    assert V.error_numerico("367554", "int") is None and V.error_numerico("367.554", "int")
    assert V.error_numerico("56,2", "dec") is None and V.error_numerico("0", "dec") is None
    assert "decimal con punto" in V.error_numerico("56.2", "dec")
    assert "miles" in V.error_numerico("1.234.567", "int") and V.error_numerico("-3,5", "dec") is None
