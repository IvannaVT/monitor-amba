"""Capa II (40 municipios): descubrimiento/verificación de URL, INDEC, nombres, cargos y modo completo. Offline."""
import csv
import json
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import descubrir_urls as D  # noqa: E402
import extraer as E  # noqa: E402
import normalizar as N  # noqa: E402
import validar as V  # noqa: E402
from test_pipeline import BASE, FakeSession, R, correr, dirs, leer, paginas  # noqa: E402,F401


def ficha(titulo, indec=None):
    ld = ""
    if indec:
        ld = ('<script type="application/ld+json">' + json.dumps({"@graph": [
            {"@type": "PropertyValue", "propertyID": "INDEC código de partido", "value": indec}]}) + "</script>")
    return f"<html><body><h1>{titulo}</h1><h2>Datos clave</h2><p>x</p>{ld}</body></html>"


def sesion_descubrimiento():
    pag = {
        BASE + "/": R(text='<a href="/m/avellaneda/">Avellaneda</a><a href="/mapa/">Mapa</a>'),
        BASE + "/ranking/": R(text='<a href="/m/vicente-lopez/">Vicente López</a><a href="/m/quilmes/">Quilmes</a>'),
        BASE + "/sitemap.xml": R(text=f"<urlset><url><loc>{BASE}/m/tres-de-febrero/</loc></url></urlset>"),
        BASE + "/m/avellaneda/": R(text=ficha("Avellaneda", "06035")),
        BASE + "/m/vicente-lopez/": R(text=ficha("Vicente López", "06861")),
        BASE + "/m/tres-de-febrero/": R(text=ficha("Tres de Febrero", "06035")),   # INDEC duplicado a propósito
        BASE + "/m/quilmes/": R(text=ficha("Otro Partido", "06658")),              # el título no coincide
    }
    return FakeSession(pag, robots=f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml")


def cfg_tmp(tmp_path, ids):
    todos = C.cargar_municipios_cfg()
    # Se parte de una config SIN URL ni INDEC para probar el descubrimiento de forma aislada del config real (40 verificadas).
    filas = [dict(m, url_portal_municipio="", indec_codigo="", indec_fuente="") for m in todos if m["municipio_id"] in ids]
    ruta = tmp_path / "cfg.csv"
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(todos[0].keys()), delimiter=";", lineterminator="\n")
        w.writeheader(); w.writerows(filas)
    return ruta, filas


def test_descubrimiento_usa_solo_enlaces_reales_y_verifica_titulo(tmp_path):
    ses = sesion_descubrimiento()
    ruta, filas = cfg_tmp(tmp_path, {"ba_avellaneda", "ba_vicente_lopez", "ba_tres_de_febrero", "ba_quilmes", "ba_lanus"})
    res, notas = D.descubrir(E.Cliente(pausa=0, session=ses), filas, filas)
    est = {r["municipio_id"]: r["estado"] for r in res}
    assert est == {"ba_avellaneda": "VERIFICADA", "ba_vicente_lopez": "VERIFICADA", "ba_tres_de_febrero": "VERIFICADA",
                   "ba_quilmes": "TITULO_NO_COINCIDE", "ba_lanus": "URL_NO_ENCONTRADA"}
    assert not any("/m/lanus" in p for p in ses.pedidos)   # no se prueba ninguna ruta deducida
    assert all(not p.endswith(("/m/lanus/", "/m/lanus")) for p in ses.pedidos) and notas == []


def test_aplicar_config_solo_con_verificadas_y_sin_duplicar_indec(tmp_path):
    ses = sesion_descubrimiento()
    ruta, filas = cfg_tmp(tmp_path, {"ba_avellaneda", "ba_vicente_lopez", "ba_tres_de_febrero", "ba_quilmes", "ba_lanus"})
    res, _ = D.descubrir(E.Cliente(pausa=0, session=ses), filas, filas)
    cambios = D.aplicar_config(res, filas, ruta)
    cfg = {r["municipio_id"]: r for r in C.leer_csv(ruta)}
    assert cfg["ba_avellaneda"]["url_portal_municipio"] == BASE + "/m/avellaneda/" and cfg["ba_avellaneda"]["indec_codigo"] == "06035"
    assert "pendiente de verificar" in cfg["ba_avellaneda"]["indec_fuente"]
    assert cfg["ba_vicente_lopez"]["indec_codigo"] == "06861"
    assert cfg["ba_tres_de_febrero"]["url_portal_municipio"] and cfg["ba_tres_de_febrero"]["indec_codigo"] == ""   # 06035 ya usado
    assert cambios["indec_conflictos"] == ["ba_tres_de_febrero"]
    assert cfg["ba_quilmes"]["url_portal_municipio"] == "" and cfg["ba_lanus"]["url_portal_municipio"] == ""
    assert "Descubrimiento" in D.informe_md(res, [], cambios) and "TITULO_NO_COINCIDE" in D.informe_md(res, [], cambios)


def test_aplicar_config_no_pisa_valores_existentes(tmp_path):
    ruta, filas = cfg_tmp(tmp_path, {"ba_avellaneda"})
    filas[0].update(url_portal_municipio=BASE + "/m/otra/", indec_codigo="06999")
    D.aplicar_config([{"municipio_id": "ba_avellaneda", "estado": "VERIFICADA", "url": BASE + "/m/avellaneda/", "indec": "06035"}], filas, ruta)
    r = C.leer_csv(ruta)[0]
    assert r["url_portal_municipio"] == BASE + "/m/otra/" and r["indec_codigo"] == "06999"


def test_descubrimiento_registra_incidencias_sin_resolver_las_ajenas(dirs):
    correr(dirs, paginas(), municipios="avellaneda")                      # crea incidencias propias del extractor
    ajenas = [i["incidencia_id"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["estado_resolucion"] == "ABIERTA"]
    D.registrar_incidencias([{"municipio_id": "ba_lanus", "estado": "URL_NO_ENCONTRADA", "detalle": "sin enlace", "url": ""}],
                            ["https://x/: ACCESO_DENEGADO"], dirs[0], dirs[1])
    inc = C.leer_csv(dirs[0] / C.F_INCIDENCIAS)
    assert {"URL_NO_ENCONTRADA", "ACCESO_LISTADO_NO_LOGRADO"} <= {i["tipo_incidencia"] for i in inc}
    assert all(i["estado_resolucion"] == "ABIERTA" for i in inc if i["incidencia_id"] in ajenas)


# ---------------------------------------------------------------- nombres
@pytest.mark.parametrize("completo,esperado", [
    ("Magdalena Sierra", ("Magdalena", "Sierra", "dos_palabras")),
    ("Soledad Martínez", ("Soledad", "Martínez", "dos_palabras")),
    ("Juan Carlos Pérez", ("", "", "no_separado")),
    ("María de los Ángeles Gómez", ("", "", "no_separado")),
    ("Juan De La Torre", ("", "", "no_separado")),
    ("Ana-María Pérez", ("", "", "no_separado")),
    ("O'Connor Pablo", ("", "", "no_separado")),
    ("Cher", ("", "", "no_separado")),
])
def test_separar_nombre_conservador(completo, esperado):
    assert C.separar_nombre(completo) == esperado


def test_separar_nombre_override_y_nombre_original_intacto(dirs, tmp_path, monkeypatch):
    assert C.separar_nombre("Juan Carlos Pérez", {"Juan Carlos Pérez": ("Juan Carlos", "Pérez")}) == ("Juan Carlos", "Pérez", "override_config")
    over = tmp_path / "n.csv"
    over.write_text("﻿nombre_completo;nombre;apellido;fuente_revision\nAna Ficticia Prueba;Ana;Ficticia Prueba;revisión manual\n", encoding="utf-8")
    monkeypatch.setattr(C, "ARCHIVO_NOMBRES", over)
    monkeypatch.setattr(C, "cargar_nombres_override", lambda ruta=over: {"Ana Ficticia Prueba": ("Ana", "Ficticia Prueba")})
    pag = paginas(); pag[BASE + "/m/avellaneda/"] = R(text=leer("ficha_ref_a.html"))
    correr(dirs, pag, municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert (m["intendente_nombre_completo"], m["intendente_nombre"], m["intendente_apellido"]) == ("Ana Ficticia Prueba", "Ana", "Ficticia Prueba")
    f = {x["campo_verificado"]: x for x in C.leer_csv(dirs[0] / C.F_FUENTES)}
    assert f["intendente_apellido"]["metodo_extraccion"] == "separacion_override_config" and "Ana Ficticia Prueba" in f["intendente_apellido"]["observaciones"]
    assert V.validar(dirs[0], "prueba")[0] == []


def test_nombre_no_separable_queda_vacio_con_incidencia(dirs):
    pag = paginas(); pag[BASE + "/m/avellaneda/"] = R(text=leer("ficha_ref_a.html").replace("Ana Ficticia Prueba", "Juan Carlos Pérez"))
    correr(dirs, pag, municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert m["intendente_nombre_completo"] == "Juan Carlos Pérez" and m["intendente_nombre"] == "" and m["intendente_apellido"] == ""
    assert "NOMBRE_NO_SEPARADO" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


def test_cambio_de_intendente_reemplaza_datos_dependientes_sin_arrastrar_los_anteriores(dirs):
    pag = paginas(); pag[BASE + "/m/avellaneda/"] = R(text=leer("ficha_ref_a.html"))
    correr(dirs, pag, fecha="2026-10-21", municipios="avellaneda")
    antes = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert antes["frente_electoral"] == "Frente de Prueba" and antes["intendente_apellido"] == ""   # 3 palabras: sin separar
    nuevo = leer("ficha_ref_a.html").replace("Ana Ficticia Prueba", "Pedro Nuevo").replace("<dt>Frente electoral</dt><dd>Frente de Prueba</dd>", "")
    pag[BASE + "/m/avellaneda/"] = R(text=nuevo)
    correr(dirs, pag, fecha="2026-10-28", municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert (m["intendente_nombre"], m["intendente_apellido"], m["frente_electoral"]) == ("Pedro", "Nuevo", "")
    assert any(a["categoria_alerta"] == "CAMBIO_INTENDENTE" for a in C.leer_csv(dirs[0] / C.F_ALERTAS))


# ----------------------------------------------- cargos, esquema y modo completo
def test_cargos_presupuestados_tiene_columna_propia_distinta_de_empleados():
    cols = C.ESQUEMAS[C.F_INDICADORES]
    assert "cargos_presupuestados" in cols and "empleados_municipales" in cols and cols.index("cargos_presupuestados") != cols.index("empleados_municipales")


def test_migracion_de_encabezado_conserva_la_version_previa(dirs):
    correr(dirs, paginas(), fecha="2026-10-21", municipios="avellaneda")
    p = dirs[0] / C.F_INDICADORES
    viejo = [c for c in C.ESQUEMAS[C.F_INDICADORES] if c != "cargos_presupuestados"]
    C.escribir_csv(p, [], viejo)                                            # archivo con el esquema anterior
    assert N.escribir_con_historial(C.F_INDICADORES, [], dirs[0], dirs[1], "2026-10-28")
    assert p.read_bytes().decode("utf-8-sig").split("\n", 1)[0].split(";") == C.ESQUEMAS[C.F_INDICADORES]
    assert (dirs[1] / "2026-10-28" / C.F_INDICADORES).exists() is False     # sin filas previas no hay nada que archivar


def cfg_solo_piloto(tmp_path):
    """Config de 40 municipios con URL únicamente en los 3 pilotos (los demás sin URL), derivada del config real."""
    todos = C.cargar_municipios_cfg()
    piloto = {"ba_avellaneda", "ba_vicente_lopez", "ba_tres_de_febrero"}
    filas = [dict(m, url_portal_municipio=m["url_portal_municipio"] if m["municipio_id"] in piloto else "") for m in todos]
    ruta = tmp_path / "cfg_piloto.csv"
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(todos[0].keys()), delimiter=";", lineterminator="\n")
        w.writeheader(); w.writerows(filas)
    return ruta


def test_modo_completo_40_municipios_valida_y_registra_incidencias(dirs, tmp_path):
    pag = paginas()
    for slug in ("avellaneda", "vicente-lopez", "tres-de-febrero"):
        pag[f"{BASE}/m/{slug}/"] = R(text=leer("ficha_ref_a.html"))
    ses = FakeSession(pag)
    res = E.ejecutar("todos", "2026-10-21", cliente=E.Cliente(pausa=0, session=ses), dir_actual=dirs[0], dir_historico=dirs[1],
                     cfg_path=cfg_solo_piloto(tmp_path))
    assert len(res["municipios"]) == 40 and res["municipios_con_datos"] == 3
    assert len(C.leer_csv(dirs[0] / C.F_MUNICIPIOS)) == 40
    assert ses.pedidos.count(BASE + "/") == 1                                # la portada se consulta una sola vez
    sin_url = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["tipo_incidencia"] == "PAGINA_NO_ENCONTRADA"]
    assert len(sin_url) == 37 and not any("/m/almirante" in p for p in ses.pedidos)   # no se prueban rutas deducidas
    err, _, _ = V.validar(dirs[0], "completo")
    assert err == [], err


def test_workflow_manual_sin_programacion_ni_commit_automatico():
    wf = (AQUI.parent / ".github" / "workflows" / "actualizar_amba.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf and "descubrir_urls" in wf and "completo" in wf
    assert "\n  schedule:" not in wf and "# schedule:" in wf
    assert "confirmar_cambios" in wf and "default: false" in wf.split("confirmar_cambios:")[1][:200]


def test_modo_completo_con_las_40_url_verificadas_del_config_real(dirs):
    """Config real (40 URL verificadas): no se consulta la portada, no hay PAGINA_NO_ENCONTRADA y valida en modo completo."""
    cfg = C.cargar_municipios_cfg()
    pag = {BASE + "/metodologia/": R(text=leer("metodologia_prueba.html"))}
    for m in cfg:
        pag[m["url_portal_municipio"]] = R(text=leer("ficha_ref_a.html"))
    ses = FakeSession(pag)
    res = E.ejecutar("todos", "2026-10-21", cliente=E.Cliente(pausa=0, session=ses), dir_actual=dirs[0], dir_historico=dirs[1])
    assert len(res["municipios"]) == 40 and res["municipios_con_datos"] == 40
    assert BASE + "/" not in ses.pedidos                                       # con URL configurada no hace falta la portada
    assert sorted(p for p in ses.pedidos if "/m/" in p) == sorted(m["url_portal_municipio"] for m in cfg)   # una solicitud por ficha
    assert not any(i["tipo_incidencia"] == "PAGINA_NO_ENCONTRADA" for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS))
    assert len(C.leer_csv(dirs[0] / C.F_MUNICIPIOS)) == 40 and len(C.leer_csv(dirs[0] / C.F_INDICADORES)) == 40
    err, _, _ = V.validar(dirs[0], "completo")
    assert err == [], err
