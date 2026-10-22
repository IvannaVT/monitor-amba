"""Descubrimiento y verificación de sitios oficiales (37 pendientes), muestra intermedia y contacto general de respaldo.

Páginas SINTÉTICAS con dominios ficticios (-prueba): no son capturas reales y no se consulta la red.
"""
import csv
import shutil
import sys
from pathlib import Path

import pytest
import requests

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import contactos_parser as CP  # noqa: E402
import descubrir_sitios as D  # noqa: E402
import validar as V  # noqa: E402
from test_contactos import completar_archivos, dirs  # noqa: E402,F401
from test_contactos_generales import MARCA, filas, relevar_real, todo_el_texto  # noqa: E402
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

CFG = {m["municipio_id"]: m for m in C.cargar_municipios_cfg()}
FICHA = lambda mid: CFG[mid]["url_portal_municipio"]  # noqa: E731


def ficha(extra_links: str) -> str:
    return f"""{MARCA}<html><body><h2>Fuentes</h2><ul>
<li>INDEC (Instituto Nacional de Estadística y Censos): <a href="https://www.indec.gob.ar/ftp/cuadros.xls">Cuadro 1.2</a></li>
<li>Honorable Tribunal de Cuentas: <a href="https://www.hcdn-prueba.gob.ar/fallos">Buscador de fallos</a></li>{extra_links}</ul></body></html>"""


def home(titulo, extra="", ba=True):
    prov = "<p>Provincia de Buenos Aires</p>" if ba else ""
    return f"<html><head><title>{titulo}</title></head><body><h1>{titulo}</h1>{prov}{extra}</body></html>"


def sesion():
    P = {
        FICHA("ba_lanus"): R(text=ficha('<li>Municipalidad de Lanús - Secretaría de Hacienda y Administración: '
                                        '<a href="https://www.lanus-prueba.gob.ar/archivos/balance-anual-2023.pdf">(sin título; archivo balance-anual-2023.pdf)</a></li>'
                                        '<li>Municipalidad de Quilmes - Hacienda: <a href="https://www.quilmes-prueba.gov.ar/x.pdf">doc</a></li>'
                                        '<li>Municipalidad de Lanús: <a href="https://www.avellaneda.gob.ar/doc.pdf">doc (homónimo)</a></li>')),
        "https://www.lanus-prueba.gob.ar/": R(text=home("Municipio de Lanús")),
        FICHA("ba_quilmes"): R(text=ficha("")),                                                       # no enlaza documentos municipales
        FICHA("ba_lomas_de_zamora"): R(text=ficha('<li>Municipalidad de Lomas de Zamora - Hacienda: <a href="https://www.lomas-prueba.gob.ar/a.pdf">a</a></li>')),
        "https://www.lomas-prueba.gob.ar/": R(text=home("Portal ciudadano")),                        # el título no nombra al municipio
        FICHA("ba_moron"): R(text=ficha('<li>Municipalidad de Morón - Hacienda: <a href="https://hacienda.moron-prueba.gob.ar/doc.pdf">doc</a></li>')),
        "https://hacienda.moron-prueba.gob.ar/": R(404),
        "https://moron-prueba.gob.ar/": R(text=home("Municipalidad de Morón")),
        FICHA("ba_san_isidro"): R(text=ficha('<li>Municipalidad de San Isidro: <a href="https://www.sanisidro-prueba.gob.ar/a.pdf">a</a></li>')),
        "https://www.sanisidro-prueba.gob.ar/": R(text=home("Municipio de San Isidro - Provincia de Córdoba", ba=False)),   # homónimo declarado
    }
    return SesionPorHost(P)


def sitios(ids):
    return {i: {"municipio_id": i, "sitio_oficial": "", "estado": "SIN_CONFIGURAR", "fuente": ""} for i in ids}


# ------------------------------------------------------------------ candidatos
def test_candidatos_solo_de_la_municipalidad_correcta_y_sin_homonimos():
    c = D.candidatos_desde_ficha(sesion().paginas[FICHA("ba_lanus")].text, FICHA("ba_lanus"), "Lanús")
    assert [x["host"] for x in c] == ["www.lanus-prueba.gob.ar"]                               # ni INDEC, ni HTC, ni Quilmes, ni el homónimo
    assert D.candidatos_desde_ficha(sesion().paginas[FICHA("ba_quilmes")].text, FICHA("ba_quilmes"), "Quilmes") == []


def test_raices_candidatas_solo_a_partir_del_host_enlazado():
    assert D.raices_candidatas("www.lanus-prueba.gob.ar") == ["https://www.lanus-prueba.gob.ar/", "https://lanus-prueba.gob.ar/"]
    assert D.raices_candidatas("hacienda.moron-prueba.gob.ar") == ["https://hacienda.moron-prueba.gob.ar/", "https://moron-prueba.gob.ar/",
                                                                   "https://www.moron-prueba.gob.ar/"]


# ------------------------------------------------------------------ descubrimiento
def test_descubrimiento_verifica_y_clasifica():
    ses = sesion()
    ids = ["ba_lanus", "ba_quilmes", "ba_lomas_de_zamora", "ba_moron", "ba_san_isidro", "ba_avellaneda"]
    sit = sitios(ids)
    sit["ba_avellaneda"].update(sitio_oficial="https://www.mda.gob.ar/", estado="CONFIRMADO")
    res = {r["municipio_id"]: r for r in D.descubrir(K.ClienteContactos(pausa=0, session=ses), list(CFG.values()), sit, [CFG[i] for i in ids])}
    assert {k: v["estado"] for k, v in res.items()} == {
        "ba_lanus": "VERIFICADO_TECNICAMENTE", "ba_quilmes": "SITIO_NO_DESCUBIERTO", "ba_lomas_de_zamora": "SITIO_NO_VERIFICADO",
        "ba_moron": "VERIFICADO_TECNICAMENTE", "ba_san_isidro": "SITIO_NO_VERIFICADO", "ba_avellaneda": "YA_CONFIGURADO"}
    assert res["ba_lanus"]["sitio"] == "https://www.lanus-prueba.gob.ar/" and res["ba_lanus"]["http"] == 200
    assert res["ba_lanus"]["enlace_documento"].endswith("balance-anual-2023.pdf")
    assert res["ba_moron"]["sitio"] == "https://moron-prueba.gob.ar/"                          # la raíz del subdominio 404 → la del dominio
    assert "no nombran al municipio" in res["ba_lomas_de_zamora"]["detalle"] and "homónimo" in res["ba_san_isidro"]["detalle"]
    # nunca se pide un host que no esté enlazado en una ficha (ni se prueba mda.gob.ar, ya configurado)
    permitidos = ("municipiosargentinos.net", "lanus-prueba", "lomas-prueba", "moron-prueba", "sanisidro-prueba")
    assert all(any(p in u for p in permitidos) for u in ses.pedidos), ses.pedidos


def test_dominio_duplicado_y_ficha_inaccesible():
    ses = sesion()
    sit = sitios(["ba_lanus", "ba_quilmes"])
    sit["ba_quilmes"]["sitio_oficial"] = "https://www.lanus-prueba.gob.ar/"            # ya asignado a otro municipio
    ses.paginas[FICHA("ba_lanus")] = R(text=ficha('<li>Municipalidad de Lanús: <a href="https://www.lanus-prueba.gob.ar/a.pdf">a</a></li>'))
    assert D.descubrir(K.ClienteContactos(pausa=0, session=ses), list(CFG.values()), sit, [CFG["ba_lanus"]])[0]["estado"] == "DOMINIO_DUPLICADO"
    ses2 = sesion()
    ses2.paginas[FICHA("ba_lanus")] = R(403)
    r = D.descubrir(K.ClienteContactos(pausa=0, session=ses2), list(CFG.values()), sitios(["ba_lanus"]), [CFG["ba_lanus"]])[0]
    assert r["estado"] == "ACCESO_DENEGADO_HTTP" and "HTTP 403" in r["detalle"]


def test_error_tls_del_candidato_no_se_elude():
    ses = sesion()
    ses.errores["www.lanus-prueba.gob.ar"] = requests.exceptions.SSLError("certificate verify failed")
    r = D.descubrir(K.ClienteContactos(pausa=0, session=ses), list(CFG.values()), sitios(["ba_lanus"]), [CFG["ba_lanus"]])[0]
    assert r["estado"] == "SITIO_NO_VERIFICADO" and "ERROR_TLS" in r["detalle"] and r["sitio"] == ""


# ------------------------------------------------------------------ aplicar a la configuración
def test_aplicar_solo_completa_sin_configurar_y_conserva_lo_confirmado(tmp_path):
    ruta = tmp_path / "s.csv"
    shutil.copy(C.ARCHIVO_SITIOS, ruta)
    original = {r["municipio_id"]: r for r in C.leer_csv(ruta)}
    res = [{"municipio_id": "ba_lanus", "estado": D.ESTADO_OK, "sitio": "https://www.lanus-prueba.gob.ar/", "http": 200, "titulo": "Municipio de Lanús",
            "enlace_documento": "https://www.lanus-prueba.gob.ar/a.pdf", "ficha": FICHA("ba_lanus")},
           {"municipio_id": "ba_avellaneda", "estado": D.ESTADO_OK, "sitio": "https://www.otro.gob.ar/", "http": 200, "titulo": "x",
            "enlace_documento": "x", "ficha": "x"}]
    assert D.aplicar_config(res, ruta) == 1
    nuevo = {r["municipio_id"]: r for r in C.leer_csv(ruta)}
    assert nuevo["ba_lanus"]["estado"] == "VERIFICADO_TECNICAMENTE" and nuevo["ba_lanus"]["sitio_oficial"] == "https://www.lanus-prueba.gob.ar/"
    assert "pendiente de confirmación humana" in nuevo["ba_lanus"]["fuente"] and FICHA("ba_lanus") in nuevo["ba_lanus"]["fuente"]
    assert nuevo["ba_avellaneda"] == original["ba_avellaneda"]                               # CONFIRMADO intacto
    assert all(nuevo[m] == original[m] for m in nuevo if m not in ("ba_lanus",))
    assert list(nuevo["ba_lanus"].keys()) == list(original["ba_lanus"].keys())


def test_el_repositorio_no_incluye_sitios_no_auditados():
    est = {r["municipio_id"]: r["estado"] for r in C.leer_csv(C.ARCHIVO_SITIOS)}
    assert sum(1 for e in est.values() if e == "CONFIRMADO") == 3 and "VERIFICADO_TECNICAMENTE" not in est.values()   # nada sin comprobar figura como verificado
    assert sum(1 for e in est.values() if e == "CANDIDATO_A_VERIFICAR") + sum(1 for e in est.values() if e == "OFICIAL_DOCUMENTADO") == 37


def test_validador_exige_fuente_en_los_verificados_tecnicamente(tmp_path, monkeypatch):
    p = tmp_path / "s.csv"
    monkeypatch.setattr(C, "ARCHIVO_SITIOS", p)
    p.write_text("﻿municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados\nba_lanus;https://www.lanus-prueba.gob.ar/;;VERIFICADO_TECNICAMENTE;;\n", encoding="utf-8")
    assert "VERIFICADO_TECNICAMENTE sin fuente" in "\n".join(V.validar(Path("/nonexistent"), "prueba")[0])


# ------------------------------------------------------------------ muestra intermedia y relevamiento con sitio verificado técnicamente
def test_muestra_intermedia_y_completo():
    cfg = list(CFG.values())
    inter = K.seleccionar(cfg, "intermedia")
    assert 5 <= len(inter) <= 10 and {"ba_avellaneda", "ba_vicente_lopez", "ba_tres_de_febrero"} <= {c["municipio_id"] for c in inter}
    assert len(K.seleccionar(cfg, "todos")) == 40 and len(K.seleccionar(cfg, "lanus,moron")) == 2


def test_sitio_verificado_tecnicamente_se_relevan_con_titulo_y_dominio(dirs):
    pag = {"https://www.lanus-prueba.gob.ar/": R(text=home("Municipio de Lanús", '<footer><a href="mailto:info@lanus-prueba.gob.ar">info@lanus-prueba.gob.ar</a></footer>'))}
    ses = SesionPorHost(pag)
    cli = K.ClienteContactos(pausa=0, session=ses)
    s = {"sitio_oficial": "https://www.lanus-prueba.gob.ar/", "estado": D.ESTADO_OK}
    res = K.relevar_municipio(cli, {"municipio_id": "ba_lanus", "municipio": "Lanús"}, s, "2026-10-21", "S1")
    assert res["sitio_ok"]
    pag["https://www.lanus-prueba.gob.ar/"] = R(text=home("Portal ciudadano"))
    res2 = K.relevar_municipio(K.ClienteContactos(pausa=0, session=SesionPorHost(pag)), {"municipio_id": "ba_lanus", "municipio": "Lanús"}, s, "2026-10-21", "S2")
    assert not res2["sitio_ok"]


# ------------------------------------------------------------------ contacto general de respaldo y prioridades
def test_contacto_general_de_respaldo_cuando_no_hay_zona_ni_dependencias(dirs):
    cuerpo = '<main><p>Escribinos a <a href="mailto:info@tresdefebrero.gov.ar">info@tresdefebrero.gov.ar</a> o llamá al Tel: 4000-0000</p></main>'
    relevar_real(dirs, "ba_tres_de_febrero", {"": f"{MARCA}<html><head><title>Municipio de Tres de Febrero</title></head><body>{cuerpo}</body></html>"})
    g = filas(dirs)["Contacto institucional general"]
    assert g["email_institucional"] == "info@tresdefebrero.gov.ar" and g["telefono_institucional"] == "4000-0000"
    assert g["estado_contacto"] == "PUBLICADO_SIN_VIGENCIA_CONFIRMADA" and g["evidencia"] and g["url_fuente"]
    assert "CONTACTO_GENERAL_POR_RESPALDO" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
    fu = [x for x in C.leer_csv(dirs[0] / C.F_FUENTES) if x["entidad"] == "contacto:contacto_general"]
    assert fu and all(x["nivel_confianza"] == "BAJO" for x in fu)
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == []


def test_el_respaldo_no_se_usa_si_hay_zona_de_contacto_ni_toma_canales_de_una_dependencia(dirs):
    cuerpo = ('<section><h3>Ceremonial y Protocolo</h3><p>Tel: 4000-0001</p><p>protocolo@tresdefebrero.gov.ar</p></section>'
              '<footer>Mesa general: <a href="mailto:info@tresdefebrero.gov.ar">info@tresdefebrero.gov.ar</a></footer>')
    relevar_real(dirs, "ba_tres_de_febrero", {"": f"<html><head><title>Municipio de Tres de Febrero</title></head><body>{cuerpo}</body></html>"})
    f = filas(dirs)
    assert f["Contacto institucional general"]["email_institucional"] == "info@tresdefebrero.gov.ar"
    assert "CONTACTO_GENERAL_POR_RESPALDO" not in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
    sin_zona = '<section><h3>Ceremonial y Protocolo</h3><p>Tel: 4000-0001</p><p>protocolo@tresdefebrero.gov.ar</p></section>'
    d2 = (dirs[0].parent / "a2", dirs[1])
    relevar_real(d2, "ba_tres_de_febrero", {"": f"<html><head><title>Municipio de Tres de Febrero</title></head><body>{sin_zona}</body></html>"})
    g = filas(d2)["Contacto institucional general"]
    assert g["estado_contacto"] == "NO_ENCONTRADO" and g["email_institucional"] == "" and g["telefono_institucional"] == ""   # el canal de Ceremonial no se reutiliza


def test_intendencia_es_despacho_y_el_orden_de_prioridad():
    assert [d["clave"] for d in CP.DEPENDENCIAS][:4] == ["ceremonial", "relaciones", "privada", "despacho"]
    assert [d["clave"] for d in CP.DEPENDENCIAS][4:6] == ["hcd_presidencia", "hcd_secretaria"]
    h = CP.analizar_pagina("<body><main><div><h3>Intendencia</h3><p>Tel: 4000-0003</p><p>intendencia@x-prueba.gob.ar</p></div></main></body>",
                           "https://www.x-prueba.gob.ar/p", {"x-prueba.gob.ar"})["hallazgos"][0]
    assert h["clave"] == "despacho" and h["emails"] == ["intendencia@x-prueba.gob.ar"]


# ------------------------------------------------------------------ workflow: nada sin auditar llega a main
def test_workflow_intermedia_completo_y_sin_escritura_en_main():
    wf = (AQUI.parent / ".github" / "workflows" / "relevar_contactos.yml").read_text(encoding="utf-8")
    assert "options: [prueba, intermedia, completo, candidatos, pendientes, documentados]" in wf and "scripts/descubrir_sitios.py" in wf and "--aplicar" in wf
    assert "github.ref_name != 'main'" in wf and "\n  schedule:" not in wf
    assert "default: false" in wf.split("confirmar_cambios:")[1][:300]
    assert "git add data docs/informe_contactos.md" in wf and "config/" not in wf.split("git add")[1].split("\n")[0]
    assert "scripts/extraer.py" not in wf
