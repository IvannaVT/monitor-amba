"""Calidad de atribución (ejecución intermedia 39699076649): HCD vs Municipalidad, URL exacta por contacto, vigencia, discrepancias, responsables.

El HTML real capturado por Actions NO estuvo disponible para estas pruebas (el artefacto no se pudo descargar). Las páginas de abajo son
REPRODUCCIONES SINTÉTICAS de los casos descritos (dominios ficticios -prueba); no son capturas reales.
"""
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import contactos_parser as CP  # noqa: E402
import validar as V  # noqa: E402
from test_contactos import completar_archivos, dirs  # noqa: E402,F401
from test_contactos_generales import MARCA, filas, portada_tdf, relevar_real  # noqa: E402
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

MUNI, HCD = "https://www.quilmes-prueba.gov.ar/", "https://www.hcdquilmes-prueba.gob.ar/"
ORG_HCD = "Honorable Concejo Deliberante de Quilmes"


def home_q(extra=""):
    return f"""{MARCA}<html><head><title>Municipalidad de Quilmes</title></head><body>
<nav><a href="{HCD}">Honorable Concejo Deliberante</a> <a href="/contacto/">Contacto</a></nav><main><h1>Quilmes</h1>{extra}</main>
<footer>Tel: 4000-0000 | <a href="mailto:info@quilmes-prueba.gov.ar">info@quilmes-prueba.gov.ar</a></footer></body></html>"""


HCD_HOME = f"""{MARCA}<html><head><title>Honorable Concejo Deliberante de Quilmes</title></head><body><main>
<h3>Presidencia del Honorable Concejo Deliberante</h3>
<ul><li>Presidencia: <a href="mailto:presidencia@hcdquilmes-prueba.gob.ar">presidencia@hcdquilmes-prueba.gob.ar</a></li>
<li>Prensa: <a href="mailto:prensa@hcdquilmes-prueba.gob.ar">prensa@hcdquilmes-prueba.gob.ar</a></li>
<li>Contacto: <a href="mailto:contacto@hcdquilmes-prueba.gob.ar">contacto@hcdquilmes-prueba.gob.ar</a></li></ul>
</main></body></html>"""


def relevar_q(dirs, pag, estado="CONFIRMADO", extra=None):
    ses = SesionPorHost(pag)
    cli = K.ClienteContactos(pausa=0, session=ses)
    s = dict({"sitio_oficial": MUNI, "estado": estado}, **(extra or {}))
    res = K.relevar_municipio(cli, {"municipio_id": "ba_quilmes", "municipio": "Quilmes"}, s, "2026-10-21", "S1")
    K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1], verificados={})
    return res, ses


def fuentes(dirs):
    return C.leer_csv(dirs[0] / C.F_FUENTES)


# ------------------------------------------------------------------ 1-2. Quilmes: HCD ≠ Municipalidad, una dependencia por canal
def test_hcd_presidencia_prensa_y_contacto_son_filas_distintas_y_no_van_a_la_municipalidad(dirs):
    relevar_q(dirs, {MUNI: R(text=home_q()), HCD: R(text=HCD_HOME)})
    f = filas(dirs)
    pres, pren, cont = (f["Presidencia del Concejo Deliberante"], f["Prensa y Comunicación del Concejo Deliberante"],
                        f["Contacto institucional general del Concejo Deliberante"])
    assert pres["email_institucional"] == "presidencia@hcdquilmes-prueba.gob.ar" and pres["organismo"] == ORG_HCD and pres["tipo_contacto"] == "CONCEJO"
    assert pren["email_institucional"] == "prensa@hcdquilmes-prueba.gob.ar" and pren["tipo_contacto"] == "CONTACTO_ALTERNATIVO"
    assert cont["email_institucional"] == "contacto@hcdquilmes-prueba.gob.ar" and cont["organismo"] == ORG_HCD
    g = f["Contacto institucional general"]
    assert g["email_institucional"] == "info@quilmes-prueba.gov.ar" and g["telefono_institucional"] == "4000-0000" and g["organismo"] == "Municipalidad de Quilmes"
    for r in f.values():                                                         # ningún correo del HCD en filas municipales y viceversa
        assert ("hcdquilmes" in r["email_institucional"]) == (r["organismo"] == ORG_HCD) or not r["email_institucional"]
        assert r["email_institucional"].count("@") <= 1                          # nunca varios correos agrupados en una dependencia
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_cada_contacto_registra_la_url_exacta_de_su_pagina(dirs):
    relevar_q(dirs, {MUNI: R(text=home_q()), HCD: R(text=HCD_HOME)})
    f = filas(dirs)
    esperado = {"presidencia@hcdquilmes-prueba.gob.ar": HCD, "prensa@hcdquilmes-prueba.gob.ar": HCD, "contacto@hcdquilmes-prueba.gob.ar": HCD,
                "info@quilmes-prueba.gov.ar": MUNI, "4000-0000": MUNI}
    obtenido = {x["valor_obtenido"]: x["documento_url"] for x in fuentes(dirs) if x["campo_verificado"] in ("email_institucional", "telefono_institucional")}
    assert obtenido == esperado
    assert f["Presidencia del Concejo Deliberante"]["url_fuente"] == HCD and f["Contacto institucional general"]["url_fuente"] == MUNI
    assert all(x["fecha_consulta"] == "2026-10-21" and "evidencia=" in x["observaciones"] for x in fuentes(dirs) if x["entidad"].startswith("contacto:"))


def test_correo_del_hcd_en_el_pie_de_la_portada_municipal_no_va_al_contacto_general(dirs):
    pie = '<footer>Tel: 4000-0000 | <a href="mailto:info@quilmes-prueba.gov.ar">info@quilmes-prueba.gov.ar</a><p>Concejo Deliberante: <a href="mailto:hcd@quilmes-prueba.gov.ar">hcd@quilmes-prueba.gov.ar</a></p></footer>'
    pag = {MUNI: R(text=f"<html><head><title>Municipalidad de Quilmes</title></head><body>{pie}</body></html>")}
    relevar_q(dirs, pag)
    f = filas(dirs)
    assert f["Contacto institucional general"]["email_institucional"] == "info@quilmes-prueba.gov.ar"
    assert f["Contacto institucional general del Concejo Deliberante"]["email_institucional"] == "hcd@quilmes-prueba.gov.ar"


def test_un_canal_con_datos_en_dos_paginas_registra_cada_url():
    a1 = CP.analizar_pagina("<body><section><h3>Ceremonial y Protocolo</h3><p>protocolo@quilmes-prueba.gov.ar</p></section></body>", MUNI + "a/", {"quilmes-prueba.gov.ar"})
    a2 = CP.analizar_pagina("<body><section><h3>Ceremonial y Protocolo</h3><p>Tel: 4000-0001</p></section></body>", MUNI + "b/", {"quilmes-prueba.gov.ar"})
    res = {"municipio_id": "ba_quilmes", "municipio": "Quilmes", "sitio_ok": True, "incidencias": [], "paginas": [MUNI], "general": [],
           "hallazgos": [dict(h, titulo="", fecha_actualizacion="") for a in (a1, a2) for h in a["hallazgos"]]}
    filas_, fu, _ = K.construir_filas(res, "2026-10-21", "S1")
    por_valor = {x["valor_obtenido"]: x["documento_url"] for x in fu if x["campo_verificado"] in ("email_institucional", "telefono_institucional")}
    assert por_valor == {"protocolo@quilmes-prueba.gov.ar": MUNI + "a/", "4000-0001": MUNI + "b/"}
    cer = next(f for f in filas_ if f["dependencia"] == "Ceremonial y Protocolo")
    assert cer["url_fuente"] == MUNI + "a/" and MUNI + "b/" in cer["evidencia"]


# ------------------------------------------------------------------ 3. publicado ≠ vigencia confirmada
def test_http_200_y_la_corroboracion_no_prueban_vigencia(dirs):
    pag = {MUNI: R(text=home_q()), MUNI + "contacto/": R(text="<html><title>Contacto</title><body><footer>Tel: 4000-0000 info@quilmes-prueba.gov.ar</footer></body></html>")}
    relevar_q(dirs, pag)
    estados = {r["dependencia"]: r["estado_contacto"] for r in C.leer_csv(dirs[0] / C.F_CONTACTOS)}
    assert estados["Contacto institucional general"] == "PUBLICADO_CORROBORADO"
    assert "VIGENTE_CONFIRMADO" not in estados.values() and all(r["fecha_verificacion"] == "" for r in C.leer_csv(dirs[0] / C.F_CONTACTOS))
    assert all(x["nivel_confianza"] != "ALTO" for x in fuentes(dirs))


def test_solo_una_verificacion_humana_confirma_la_vigencia(dirs, tmp_path):
    reg = tmp_path / "v.csv"
    reg.write_text("﻿municipio_id;dependencia;canal;fecha_verificacion;metodo;verificado_por\n"
                   "ba_quilmes;Contacto institucional general;INFO@quilmes-prueba.gov.ar;2026-10-22;respuesta a correo de prueba;persona\n"
                   "ba_quilmes;Contacto institucional general;sin_metodo@x.gob.ar;2026-10-22;;\n", encoding="utf-8")
    ver = K.cargar_verificados(reg)
    assert ver == {("ba_quilmes", "Contacto institucional general"): {"info@quilmes-prueba.gov.ar": "2026-10-22"}}   # la fila sin método no cuenta
    ses = SesionPorHost({MUNI: R(text=home_q())})
    res = K.relevar_municipio(K.ClienteContactos(pausa=0, session=ses), {"municipio_id": "ba_quilmes", "municipio": "Quilmes"},
                              {"sitio_oficial": MUNI, "estado": "CONFIRMADO"}, "2026-10-21", "S1")
    K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1], verificados=ver)
    g = filas(dirs)["Contacto institucional general"]
    assert g["estado_contacto"] == "VIGENTE_CONFIRMADO" and g["fecha_verificacion"] == "2026-10-22"
    assert any(x["nivel_confianza"] == "ALTO" for x in fuentes(dirs) if x["entidad"] == "contacto:contacto_general")
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == []


def test_validador_rechaza_fecha_de_verificacion_sin_vigencia_confirmada_y_registros_incompletos(dirs, tmp_path, monkeypatch):
    relevar_q(dirs, {MUNI: R(text=home_q())})
    completar_archivos(dirs)
    p = dirs[0] / C.F_CONTACTOS
    rows = C.leer_csv(p)
    rows[0]["fecha_verificacion"] = "2026-10-21"
    C.escribir_csv(p, rows, C.ESQUEMAS[C.F_CONTACTOS])
    reg = tmp_path / "v.csv"
    reg.write_text("﻿municipio_id;dependencia;canal;fecha_verificacion;metodo;verificado_por\nba_quilmes;x;a@b.gob.ar;21/10/2026;llamado;\n", encoding="utf-8")
    monkeypatch.setattr(C, "ARCHIVO_VERIFICADOS", reg)
    e = "\n".join(V.validar(dirs[0], "prueba")[0])
    assert "fecha_verificacion solo corresponde a VIGENTE_CONFIRMADO" in e and "contactos_verificados.csv: fila incompleta o con fecha inválida" in e


# ------------------------------------------------------------------ 4. Tres de Febrero: la discrepancia queda como incidencia, el número técnico no
def test_el_numero_tecnico_del_enlace_nunca_figura_como_confirmado(dirs):
    extra = '<p>Atención al vecino: <a href="tel:+5411 4000-9999">147</a></p>'
    for _ in range(2):                                                         # la incidencia se conserva entre corridas
        relevar_real(dirs, "ba_tres_de_febrero", {"": portada_tdf(extra)})
    texto = "".join((dirs[0] / n).read_text(encoding="utf-8-sig") for n in (C.F_CONTACTOS, C.F_FUENTES))
    assert "4000-9999" not in texto and "541140009999" not in texto
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["tipo_incidencia"] == "TELEFONO_DISCREPANCIA"]
    assert len(inc) == 1 and inc[0]["estado_resolucion"] == "ABIERTA" and "'147' vs tel:+5411 4000-9999" in inc[0]["descripcion"]
    g = filas(dirs)["Contacto institucional general"]
    assert g["telefono_institucional"] == "147" and g["estado_contacto"] != "VIGENTE_CONFIRMADO"


# ------------------------------------------------------------------ 5. Vicente López: responsable inequívoco, variantes de organigrama
def resp(html):
    out = {}
    for h in CP.analizar_pagina(html, "https://www.vicentelopez-prueba.gov.ar/o", set())["hallazgos"]:
        if h["clave"] not in out or (h["responsable"] and not out[h["clave"]][0]):
            out[h["clave"]] = (h["responsable"], h["cargo"])
    return out


@pytest.mark.parametrize("html", [
    "<main><ul><li>Facundo Carrillo – Jefe de Gabinete</li></ul></main>",
    "<main><p>Jefe de Gabinete: Facundo Carrillo</p></main>",
    "<main><p>Jefatura de Gabinete: Facundo Carrillo</p></main>",
    "<main><div><h3>Jefatura de Gabinete</h3><h4>Facundo Carrillo</h4></div></main>",
    "<main><table><tr><td>Jefe de Gabinete</td><td>Facundo Carrillo</td></tr></table></main>",
    "<main><div><h3>Jefatura de Gabinete</h3><p><strong>Facundo Carrillo</strong></p></div></main>",
    "<main><p>Jefe de Gabinete, Facundo Carrillo</p></main>",
])
def test_responsable_de_jefatura_de_gabinete_en_las_estructuras_habituales(html):
    assert resp(html)["despacho"][0] == "Facundo Carrillo", html


@pytest.mark.parametrize("html", [
    "<main><h3>Jefatura de Gabinete</h3><h3>Obras Públicas</h3></main>",                       # encabezado del mismo nivel: otra oficina
    "<main><h3>Jefatura de Gabinete</h3><h4>Ver más información</h4></main>",
    "<main><p>Jefatura de Gabinete – Tel. 4000-1234</p></main>",
    "<main><li>Jefatura de Gabinete</li><li>Tesorería Municipal</li></main>",
])
def test_sin_asociacion_inequivoca_no_hay_responsable(html):
    assert resp(html).get("despacho", ("", ""))[0] == ""


def test_el_nombre_de_la_dependencia_no_se_usa_como_responsable():
    assert resp("<main><p>Jefatura de Gabinete – Secretaría Privada</p></main>").get("despacho", ("", ""))[0] == ""


# ------------------------------------------------------------------ 7. verificación de candidatos y pendientes
def test_presets_candidatos_y_pendientes_y_workflow():
    cfg = C.cargar_municipios_cfg()
    est = {m: s["estado"] for m, s in K.cargar_sitios().items()}
    cand, pend = K.seleccionar(cfg, "candidatos"), K.seleccionar(cfg, "pendientes")
    assert {c["municipio_id"] for c in cand} == {m for m, e in est.items() if e == "CANDIDATO_A_VERIFICAR"} and len(cand) == 28
    assert {c["municipio_id"] for c in pend} == {m for m, e in est.items() if e == "SIN_CONFIGURAR"} and len(pend) == 0
    assert len(K.seleccionar(cfg, "documentados")) == 9
    wf = (AQUI.parent / ".github" / "workflows" / "relevar_contactos.yml").read_text(encoding="utf-8")
    assert "options: [prueba, intermedia, completo, candidatos, pendientes, documentados, discrepancias]" in wf and "solo_sitios" in wf
    assert "github.ref_name != 'main'" in wf and "\n  schedule:" not in wf and "scripts/extraer.py" not in wf
