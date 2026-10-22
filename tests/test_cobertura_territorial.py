"""Cobertura territorial (candidatos vs verificados), fuentes alternativas, responsables en organigramas y conservación del contacto general.

Todo con páginas SINTÉTICAS (dominios -prueba); no son capturas reales y no se consulta la red.
"""
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

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
from test_contactos_generales import MARCA, filas, portada_tdf, relevar_real, todo_el_texto  # noqa: E402
from test_pipeline import R  # noqa: E402
from test_sitios_descubrimiento import FICHA, ficha, home  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

SIT = {r["municipio_id"]: r for r in C.leer_csv(C.ARCHIVO_SITIOS)}
CFG = {m["municipio_id"]: m for m in C.cargar_municipios_cfg()}


# ------------------------------------------------------------------ FASE A: cobertura y estados
def test_cobertura_documentados_candidatos_y_pendientes():
    est = {m: r["estado"] for m, r in SIT.items()}
    cuenta = {e: list(est.values()).count(e) for e in set(est.values())}
    assert cuenta == {"CONFIRMADO": 3, "OFICIAL_DOCUMENTADO": 9, "CANDIDATO_A_VERIFICAR": 28}     # 0 pendientes; 0 verificados técnicamente sin haberse comprobado
    for mid, r in SIT.items():
        if r["estado"] == "CANDIDATO_A_VERIFICAR":
            assert "NO comprobado" in r["fuente"] and r["sitio_oficial"].startswith("https://www."), mid


def test_dominios_unicos_oficiales_y_sin_homonimos():
    hosts = [CP.dominio_base(urlparse(r["sitio_oficial"]).hostname) for r in SIT.values()]
    assert len(hosts) == 40 and len(set(hosts)) == 40 and all(SIT[m]["sitio_oficial"].startswith("https://") for m in SIT)
    assert not [h for h in hosts if CP.dominio_homonimo(h)]
    assert not [e for e in V.validar(Path("/nonexistent"), "prueba")[0] if "sitios_oficiales" in e]


def test_el_documento_de_cobertura_coincide_con_la_config():
    md = (AQUI.parent / "docs" / "cobertura_territorial.md").read_text(encoding="utf-8")
    assert "| CONFIRMADO | verificado por una persona | 3 |" in md and "| CANDIDATO_A_VERIFICAR | candidato NO comprobado | 28 |" in md
    assert "| OFICIAL_DOCUMENTADO | oficial según fuente documental (la verificación HTTP va aparte) | 9 |" in md and "SIN_CONFIGURAR" not in md.split("| Municipio |")[0]


# ------------------------------------------------------------------ verificación de candidatos (Actions)
def sit(estado, url, mid="ba_lanus"):
    return {mid: {"municipio_id": mid, "sitio_oficial": url, "estado": estado, "fuente": ""}}


def correr(paginas, sitios_cfg, ids=("ba_lanus",), errores=None):
    ses = SesionPorHost(paginas, errores=errores)
    return D.descubrir(K.ClienteContactos(pausa=0, session=ses), list(CFG.values()), sitios_cfg, [CFG[i] for i in ids])[0], ses


def test_candidato_correcto_pasa_a_verificado_tecnicamente_sin_acudir_a_la_ficha():
    r, ses = correr({"https://www.lanus-prueba.gob.ar/": R(text=home("Municipio de Lanús"))}, sit("CANDIDATO_A_VERIFICAR", "https://www.lanus-prueba.gob.ar/"))
    assert (r["estado"], r["origen"], r["http"]) == (D.ESTADO_OK, "candidato verificado", 200)
    assert FICHA("ba_lanus") not in ses.pedidos


@pytest.mark.parametrize("pag,detalle", [
    ({"https://www.lanus-prueba.gob.ar/": R(text=home("Otra cosa"))}, "no nombran al municipio"),
    ({"https://www.lanus-prueba.gob.ar/": R(404)}, "HTTP 404"),
    ({"https://www.lanus-prueba.gob.ar/": R(text=home("Municipio de Lanús - Provincia de Mendoza", ba=False))}, "homónimo"),
])
def test_candidato_que_no_se_comprueba_no_se_presenta_como_verificado(pag, detalle):
    r, _ = correr(pag, sit("CANDIDATO_A_VERIFICAR", "https://www.lanus-prueba.gob.ar/"))
    assert r["estado"] == "CANDIDATO_NO_VERIFICADO" and detalle in r["detalle"] and r["sitio"] == ""


def test_candidato_con_error_tls_no_se_eluda():
    r, ses = correr({"https://www.lanus-prueba.gob.ar/": R(text=home("Municipio de Lanús"))}, sit("CANDIDATO_A_VERIFICAR", "https://www.lanus-prueba.gob.ar/"),
                    errores={"www.lanus-prueba.gob.ar": requests.exceptions.SSLError("certificate verify failed")})
    assert r["estado"] == "CANDIDATO_NO_VERIFICADO" and "ERROR_TLS" in r["detalle"]
    assert ses.pedidos.count("https://www.lanus-prueba.gob.ar/") == 0                        # robots no verificable: ni se pide la página


def test_candidato_fallido_se_reemplaza_por_el_descubierto_en_la_ficha():
    pag = {"https://www.lanus-prueba.gob.ar/": R(404), FICHA("ba_lanus"): R(text=ficha('<li>Municipalidad de Lanús - Hacienda: <a href="https://www.lanus-real-prueba.gov.ar/a.pdf">a</a></li>')),
           "https://www.lanus-real-prueba.gov.ar/": R(text=home("Municipalidad de Lanús"))}
    r, _ = correr(pag, sit("CANDIDATO_A_VERIFICAR", "https://www.lanus-prueba.gob.ar/"))
    assert r["estado"] == D.ESTADO_OK and r["sitio"] == "https://www.lanus-real-prueba.gov.ar/" and r["origen"] == "ficha del portal"


def test_aplicar_actualiza_candidatos_y_conserva_confirmados_y_no_comprobados(tmp_path):
    ruta = tmp_path / "s.csv"
    ruta.write_text("﻿municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados;fuentes_alternativas\n"
                    "ba_lanus;https://www.lanus-prueba.gob.ar/;;CANDIDATO_A_VERIFICAR;NO comprobado;;\n"
                    "ba_quilmes;https://www.quilmes-prueba.gov.ar/;;CANDIDATO_A_VERIFICAR;NO comprobado;;\n"
                    "ba_avellaneda;https://www.mda.gob.ar/;;CONFIRMADO;usuario;;\n", encoding="utf-8")
    res = [{"municipio_id": "ba_lanus", "estado": D.ESTADO_OK, "sitio": "https://www.lanus-real-prueba.gov.ar/", "http": 200, "titulo": "Municipalidad de Lanús",
            "enlace_documento": "https://www.lanus-real-prueba.gov.ar/a.pdf", "ficha": FICHA("ba_lanus"), "origen": "ficha del portal"},
           {"municipio_id": "ba_quilmes", "estado": "CANDIDATO_NO_VERIFICADO", "sitio": ""},
           {"municipio_id": "ba_avellaneda", "estado": D.ESTADO_OK, "sitio": "https://otro.gob.ar/", "http": 200, "titulo": "x", "enlace_documento": "x", "ficha": "x"}]
    assert D.aplicar_config(res, ruta) == 1
    f = {r["municipio_id"]: r for r in C.leer_csv(ruta)}
    assert f["ba_lanus"]["estado"] == D.ESTADO_OK and "candidato anterior no comprobado: https://www.lanus-prueba.gob.ar/" in f["ba_lanus"]["fuente"]
    assert f["ba_quilmes"]["estado"] == "CANDIDATO_A_VERIFICAR" and f["ba_avellaneda"]["sitio_oficial"] == "https://www.mda.gob.ar/"


# ------------------------------------------------------------------ nombres con título (General San Martín)
@pytest.mark.parametrize("nombre,texto,esperado", [
    ("General San Martín", "Municipio de San Martín", True), ("General San Martín", "Municipalidad de General San Martín", True),
    ("Almirante Brown", "Municipio de Almirante Brown", True), ("General Rodríguez", "Municipio de Rodríguez", True),
    ("Lanús", "Municipio de Lanús Este", True), ("Morón", "Portal ciudadano", False), ("San Martín", "Municipio de General San Martín", True),
])
def test_nombre_en_texto(nombre, texto, esperado):
    assert CP.nombre_en_texto(nombre, texto) is esperado


# ------------------------------------------------------------------ FASE B: Avellaneda — fuentes alternativas oficiales
def relevar_alt(dirs, paginas, alternativas, errores=None):
    ses = SesionPorHost(paginas, errores=errores)
    cli = K.ClienteContactos(pausa=0, session=ses)
    sitio = {"sitio_oficial": "https://www.mda.gob.ar/", "estado": "CONFIRMADO", "fuentes_alternativas": alternativas}
    res = K.relevar_municipio(cli, {"municipio_id": "ba_avellaneda", "municipio": "Avellaneda"}, sitio, "2026-10-21", "S1")
    K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1])
    return res, ses


ALT_HOME = '<html><head><title>HCD</title></head><body><footer>Tel: 4000-7777 <a href="mailto:hcd@alt-prueba.gob.ar">hcd@alt-prueba.gob.ar</a></footer></body></html>'


def test_con_tls_en_el_principal_se_usa_la_fuente_oficial_alternativa_y_se_conserva_la_incidencia(dirs):
    tls = requests.exceptions.SSLError("certificate verify failed")
    res, ses = relevar_alt(dirs, {"https://www.hcd-alt-prueba.gob.ar/": R(text=ALT_HOME)}, "https://www.hcd-alt-prueba.gob.ar/", {"www.mda.gob.ar": tls})
    assert res["sitio_ok"] and res["fuente_alternativa"] == "https://www.hcd-alt-prueba.gob.ar/"
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["campo"] == "contacto:sitio_oficial"]
    assert any(i["tipo_incidencia"] == "ROBOTS_NO_VERIFICABLE" and "ERROR_TLS" in i["descripcion"] and "mda.gob.ar" in i["url_afectada"] for i in inc)
    g = filas(dirs)["Contacto institucional general del Concejo Deliberante"]    # el sitio alternativo es del HCD: no se atribuye a la Municipalidad
    assert g["email_institucional"] == "hcd@alt-prueba.gob.ar" and g["url_fuente"].startswith("https://www.hcd-alt-prueba.gob.ar/")
    assert filas(dirs)["Contacto institucional general"]["email_institucional"] == ""        # y la Municipalidad no recibe los correos del HCD
    assert ses.pedidos.count("https://www.mda.gob.ar/robots.txt") == 1 and "https://www.mda.gob.ar/" not in ses.pedidos     # el principal no se eluda


def test_no_se_prueban_alternativas_si_el_principal_funciona_ni_homonimos_ni_http(dirs):
    pag = {"https://www.mda.gob.ar/": R(text=home("Municipio de Avellaneda", '<footer>Tel: 4000-0001</footer>'))}
    res, ses = relevar_alt(dirs, pag, "https://www.hcd-alt-prueba.gob.ar/")
    assert res["sitio_ok"] and not any("hcd-alt" in p for p in ses.pedidos)
    d2 = (dirs[0].parent / "a2", dirs[1])
    tls = requests.exceptions.SSLError("x")
    res2, ses2 = relevar_alt(d2, {}, "https://www.avellaneda.gob.ar/;http://www.otra-prueba.gob.ar/", {"www.mda.gob.ar": tls})
    assert not res2["sitio_ok"] and all("avellaneda.gob.ar" not in p and "otra-prueba" not in p for p in ses2.pedidos)


def test_validador_de_fuentes_alternativas(tmp_path, monkeypatch):
    p = tmp_path / "s.csv"
    monkeypatch.setattr(C, "ARCHIVO_SITIOS", p)
    p.write_text("﻿municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados;fuentes_alternativas\n"
                 "ba_avellaneda;https://www.mda.gob.ar/;;CONFIRMADO;x;;https://www.avellaneda.gob.ar/;http://x.gob.ar/\n", encoding="utf-8")
    p.write_text(p.read_text(encoding="utf-8").replace(";https://www.avellaneda.gob.ar/;http://x.gob.ar/", ";https://www.avellaneda.gob.ar/"), encoding="utf-8")
    assert "fuentes_alternativas debe ser https y no un homónimo" in "\n".join(V.validar(Path("/nonexistent"), "prueba")[0])


# ------------------------------------------------------------------ FASE B: Vicente López — responsables ↔ dependencias
def resp(html):
    """Responsable por dependencia tal como se agrega en el relevamiento (el primero publicado)."""
    out = {}
    for h in CP.analizar_pagina(html, "https://www.vicentelopez-prueba.gov.ar/o", set())["hallazgos"]:
        if h["clave"] not in out or (h["responsable"] and not out[h["clave"]][0]):
            out[h["clave"]] = (h["responsable"], h["cargo"])
    return out


def test_organigrama_en_tabla_con_cargo_repetido_y_dependencias_contiguas():
    tabla = "<main><table><tr><td>Jefatura de Gabinete</td><td>Facundo Carrillo</td></tr><tr><td>Secretaría Privada</td><td>Pedro Ejemplo</td></tr></table></main>"
    assert resp(tabla) == {"despacho": ("Facundo Carrillo", ""), "privada": ("Pedro Ejemplo", "")}
    cargo = "<main><div><h3>Jefatura de Gabinete</h3><p>Jefe de Gabinete: Facundo Carrillo</p></div><div><h3>Secretaría Privada</h3><p>Secretario Privado: Pedro Ejemplo</p></div></main>"
    assert resp(cargo) == {"despacho": ("Facundo Carrillo", "Jefe de Gabinete"), "privada": ("Pedro Ejemplo", "Secretario Privado")}


def test_organigrama_jerarquico_no_cruza_responsables_entre_dependencias():
    html = ("<main><ul><li><h3>Jefatura de Gabinete</h3><p>Facundo Carrillo</p>"
            "<ul><li><h3>Secretaría Privada</h3><p>Pedro Ejemplo</p></li><li><h3>Relaciones Institucionales</h3></li></ul></li></ul></main>")
    r = resp(html)
    assert r["despacho"][0] == "Facundo Carrillo" and r["privada"][0] == "Pedro Ejemplo" and r["relaciones"][0] == ""


def test_ninguna_dependencia_recibe_el_nombre_de_otra_oficina_como_responsable():
    html = "<main><div><h4>Ceremonial y Protocolo</h4><p>Relaciones Institucionales</p></div><div><h4>Secretaría Privada</h4><p>Obras Públicas</p></div></main>"
    assert all(not v[0] for v in resp(html).values())


# ------------------------------------------------------------------ FASE B: Tres de Febrero — conservar general y teléfonos
def test_el_contacto_general_y_los_telefonos_publicados_se_conservan_entre_corridas(dirs):
    extra = '<p>Atención al vecino: <a href="tel:+5411 4000-9999">147</a></p><p>Tel: 4000-1111</p>'
    relevar_real(dirs, "ba_tres_de_febrero", {"": portada_tdf(extra)})
    g1 = filas(dirs)["Contacto institucional general"]
    assert g1["email_institucional"] == "atencionalvecino@tresdefebrero.gov.ar" and "147" in g1["telefono_institucional"]
    assert "TELEFONO_DISCREPANCIA" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
    relevar_real(dirs, "ba_tres_de_febrero", {"": "<html><head><title>Municipio de Tres de Febrero</title></head><body><p>Sin contacto</p></body></html>"})
    g2 = filas(dirs)["Contacto institucional general"]
    assert (g2["email_institucional"], g2["telefono_institucional"]) == (g1["email_institucional"], g1["telefono_institucional"])
    assert g2["estado_contacto"] == "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"
    assert "CONTACTO_YA_NO_VISIBLE" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


# ------------------------------------------------------------------ FASE C/D: informe y ejecución
def test_informe_separa_canales_especificos_de_generales(dirs):
    relevar_real(dirs, "ba_tres_de_febrero", {"": portada_tdf()})
    md = K.informe_md(C.leer_csv(dirs[0] / C.F_CONTACTOS), ["ba_tres_de_febrero"], "2026-10-21")
    assert "canales generales/alternativos con contacto: 1" in md and "Canales específicos" in md and "Responsables publicados: 0" in md


def test_workflow_sigue_manual_sin_commits_en_main_ni_cambios_de_config():
    wf = (AQUI.parent / ".github" / "workflows" / "relevar_contactos.yml").read_text(encoding="utf-8")
    assert "options: [prueba, intermedia, completo, candidatos, pendientes, documentados, discrepancias]" in wf and "github.ref_name != 'main'" in wf and "\n  schedule:" not in wf
    assert "scripts/extraer.py" not in wf
