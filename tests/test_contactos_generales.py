"""Regresión del piloto de contactos (ejecución 39692247738).

IMPORTANTE: el HTML real capturado por Actions NO estuvo disponible para estas pruebas (el artefacto no se pudo descargar).
Las páginas de abajo son REPRODUCCIONES SINTÉTICAS de las estructuras descritas por el usuario; no son capturas reales.
Los dominios sí son los de config/sitios_oficiales.csv.
"""
import csv
import re
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
import validar as V  # noqa: E402
from test_contactos import completar_archivos, dirs  # noqa: E402,F401
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

CFG = {r["municipio_id"]: r for r in csv.DictReader(open(K.SITIOS, encoding="utf-8-sig"), delimiter=";")}
TDF, VL, AV = "ba_tres_de_febrero", "ba_vicente_lopez", "ba_avellaneda"
NOMBRES = {TDF: "Tres de Febrero", VL: "Vicente López", AV: "Avellaneda"}
MARCA = "<!-- REPRODUCCIÓN SINTÉTICA de la estructura descrita; no es una captura real -->"


def relevar_real(dirs, mid, paginas, errores=None):
    ses = SesionPorHost({CFG[mid]["sitio_oficial"] + k: R(text=v) if isinstance(v, str) else v for k, v in paginas.items()}, errores=errores)
    cli = K.ClienteContactos(pausa=0, session=ses)
    res = K.relevar_municipio(cli, {"municipio_id": mid, "municipio": NOMBRES[mid]}, dict(CFG[mid]), "2026-10-21", "S1")
    K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1])
    return res, ses


def filas(dirs):
    return {f["dependencia"]: f for f in C.leer_csv(dirs[0] / C.F_CONTACTOS)}


def todo_el_texto(dirs):
    return "".join((dirs[0] / n).read_text(encoding="utf-8-sig") for n in (C.F_CONTACTOS, C.F_FUENTES, C.F_INCIDENCIAS))


# ------------------------------------------------------------------ 1. Tres de Febrero: contacto general en la portada
def portada_tdf(extra=""):
    return f"""{MARCA}<html><head><title>Municipio de Tres de Febrero</title></head><body>
<header><nav><a href="/autoridades/">Autoridades</a> <a href="/protocolo/">Ceremonial y Protocolo</a></nav></header>
<main><h1>Tres de Febrero</h1>
<section class="atencion"><h2>Atención al vecino</h2><p>Línea municipal <a href="tel:147">147</a></p>
<p><a href="mailto:atencionalvecino@tresdefebrero.gov.ar">atencionalvecino@tresdefebrero.gov.ar</a></p></section>
<div class="utiles"><p>Emergencias: <a href="tel:911">911</a> | Bomberos 100 | Policía 101 | SAME 107</p><p>Violencia de género: <a href="tel:144">144</a></p></div>
{extra}</main><footer>Municipio de Tres de Febrero</footer></body></html>"""


def test_portada_publica_correo_y_147_como_contacto_general_no_ceremonial(dirs):
    res, _ = relevar_real(dirs, TDF, {"": portada_tdf()})
    f = filas(dirs)
    g = f["Contacto institucional general"]
    assert g["tipo_contacto"] == "CONTACTO_ALTERNATIVO" and g["email_institucional"] == "atencionalvecino@tresdefebrero.gov.ar"
    assert g["telefono_institucional"] == "147" and g["url_fuente"] == "https://www.tresdefebrero.gov.ar/"
    assert g["estado_contacto"] == "PUBLICADO_SIN_VIGENCIA_CONFIRMADA" and g["fecha_consulta"] == "2026-10-21" and g["evidencia"]
    cer = f["Ceremonial y Protocolo"]
    assert cer["email_institucional"] == "" and cer["telefono_institucional"] == "" and cer["estado_contacto"] == "NO_ENCONTRADO"
    texto = todo_el_texto(dirs)
    for emergencia in ("911", "tel:144"):
        assert emergencia not in texto
    assert not re.search(r"\b(?:100|101|107|144)\b", g["telefono_institucional"])
    fu = [x for x in C.leer_csv(dirs[0] / C.F_FUENTES) if x["entidad"] == "contacto:contacto_general"]
    assert {x["valor_obtenido"] for x in fu} == {"atencionalvecino@tresdefebrero.gov.ar", "147"}
    assert all(x["documento_url"].startswith("https://www.tresdefebrero.gov.ar/") and x["fecha_consulta"] == "2026-10-21" for x in fu)
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_numero_corto_solo_como_contacto_general_nunca_dentro_de_una_dependencia():
    html = "<body><section><h3>Ceremonial y Protocolo</h3><p>Línea 147</p><p>Tel: 4000-0001</p><p>protocolo@tresdefebrero.gov.ar</p></section></body>"
    h = CP.analizar_pagina(html, "https://www.tresdefebrero.gov.ar/p", {"tresdefebrero.gov.ar"})["hallazgos"][0]
    assert h["telefonos"] == ["4000-0001"]


@pytest.mark.parametrize("texto", ["Emergencias 911", "Bomberos: 100 | Policía: 101", "Atención de emergencias: tel 4000-9111", "SAME 107"])
def test_las_lineas_de_emergencia_no_se_registran(texto):
    nodo = CP.BeautifulSoup(f"<div>{texto}</div><a href='tel:911'>Llamar</a><a href='tel:107' title='SAME'>Ambulancia</a>", "lxml")
    tels, _ = CP.extraer_telefonos(nodo, general=True)
    assert tels == [] or all(len(t.replace("-", "")) >= 6 for t in tels)   # ningún número corto de emergencia
    assert "911" not in tels and "107" not in tels and "100" not in tels


def test_numero_de_emergencia_con_etiqueta_de_atencion_al_vecino_igual_se_descarta():
    nodo = CP.BeautifulSoup("<p>Atención al vecino: 911</p><p>Línea 107</p>", "lxml")
    assert CP.extraer_telefonos(nodo, general=True)[0] == []


def test_texto_y_enlace_tel_coinciden_o_se_informa_la_discrepancia(dirs):
    equivalente = CP.BeautifulSoup('<p>Tel: <a href="tel:+54114000-1234">4000-1234</a></p><p>Línea municipal <a href="tel:147">147</a></p>', "lxml")
    assert CP.telefonos_discrepantes(equivalente) == []
    assert CP.extraer_telefonos(equivalente, general=True)[0] == ["4000-1234", "147"]
    extra = '<p>Mesa de ayuda: <a href="tel:+5411 4000-9999">147</a></p>'
    res, _ = relevar_real(dirs, TDF, {"": portada_tdf(extra.replace("Mesa de ayuda", "Atención al vecino"))})
    g = filas(dirs)["Contacto institucional general"]
    assert g["telefono_institucional"] == "147"                                 # prevalece el texto publicado
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["tipo_incidencia"] == "TELEFONO_DISCREPANCIA"]
    assert len(inc) == 1 and "'147' vs tel:+5411 4000-9999" in inc[0]["descripcion"] and inc[0]["estado_resolucion"] == "ABIERTA"
    assert "4000-9999" not in g["telefono_institucional"]


# ------------------------------------------------------------------ 2. Vicente López: organigrama h3 / p
ORGANIGRAMA = f"""{MARCA}<html><head><title>Organigrama</title></head><body><main>
<div class="area"><h3>Jefatura de Gabinete</h3><p>Facundo Carrillo</p></div>
<div class="area"><h3>Secretaría Privada</h3><p>Secretario Privado</p><p>Pedro Ejemplo</p></div>
<div class="area"><h3>Relaciones Institucionales</h3><p>Ver más información sobre el área</p></div>
<dl><dt>Ceremonial y Protocolo</dt><dd>Lic. Ana Muestra</dd></dl>
<ul><li><h3>Presidencia del Concejo Deliberante</h3><ul><li>Obras Públicas</li></ul></li></ul>
</main></body></html>"""


def test_organigrama_asocia_encabezado_con_el_nombre_del_parrafo(dirs):
    home = '<html><head><title>Municipio de Vicente López</title></head><body><a href="/organigrama/">Organigrama</a></body></html>'
    relevar_real(dirs, VL, {"": home, "organigrama/": ORGANIGRAMA})
    f = filas(dirs)
    d = f["Despacho del Intendente / Jefatura de Gabinete"]
    assert (d["responsable_nombre_completo"], d["responsable_nombre"], d["responsable_apellido"]) == ("Facundo Carrillo", "Facundo", "Carrillo")
    assert d["estado_contacto"] == "DEPENDENCIA_SIN_CANAL" and d["email_institucional"] == "" and d["url_fuente"].endswith("/organigrama/")
    assert d["cargo"] == "" and d["evidencia"] and d["fecha_consulta"] == "2026-10-21" and d["fecha_verificacion"] == ""   # vigencia sin confirmar
    p = f["Secretaría Privada del Intendente"]
    assert (p["responsable_nombre_completo"], p["cargo"]) == ("Pedro Ejemplo", "Secretario Privado")
    c = f["Ceremonial y Protocolo"]
    assert c["responsable_nombre_completo"] == "Ana Muestra" and c["responsable_nombre"] == "Ana"            # dt/dd, sin honorífico
    assert f["Relaciones Institucionales"]["responsable_nombre_completo"] == ""                               # un texto cualquiera no es un nombre
    assert f["Presidencia del Concejo Deliberante"]["responsable_nombre_completo"] == ""                      # la sub-lista "Obras Públicas" no es una persona
    for fila in f.values():                                                                                   # el nombre de la dependencia nunca va al responsable
        for campo in ("responsable_nombre", "responsable_apellido", "responsable_nombre_completo", "cargo"):
            assert not CP.deps_en(CP.norm(fila[campo])) and "Jefatura" not in fila[campo] and "Gabinete" not in fila[campo]
    fu = [x for x in C.leer_csv(dirs[0] / C.F_FUENTES) if x["campo_verificado"] == "responsable_nombre_completo" and x["entidad"] == "contacto:despacho"]
    assert len(fu) == 1 and fu[0]["valor_obtenido"] == "Facundo Carrillo" and fu[0]["documento_url"].endswith("/organigrama/") and "evidencia=" in fu[0]["observaciones"]
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_un_menu_no_produce_responsables_falsos():
    html = "<body><main><ul><li><a>Ceremonial y Protocolo</a></li><li>Obras Públicas</li><li>Cultura Municipal</li></ul></main></body>"
    assert all(not h["responsable"] for h in CP.analizar_pagina(html, "https://www.vicentelopez.gov.ar/m", set())["hallazgos"])


def test_responsable_en_titulo_en_linea_con_salto_de_linea():
    html = "<body><main><p><strong>Jefatura de Gabinete</strong><br>Facundo Carrillo</p></main></body>"
    h = CP.analizar_pagina(html, "https://www.vicentelopez.gov.ar/m", set())["hallazgos"][0]
    assert h["responsable"] == "Facundo Carrillo"


# ------------------------------------------------------------------ 3. formulario de suscripción informativa
SUSCRIPCION = """<form action="/suscripcion" class="newsletter"><label>Suscribite a las novedades</label>
<input type="email" name="email" placeholder="Tu correo"><button>Suscribirme</button></form>"""


def test_formulario_de_suscripcion_no_se_atribuye_a_ceremonial_ni_despacho(dirs):
    pagina = f"""{MARCA}<html><body><main>
<section><h3>Ceremonial y Protocolo</h3><p>Tel: 4000-0001</p><p>protocolo@vicentelopez.gov.ar</p>{SUSCRIPCION}</section>
<section><h3>Despacho del Intendente</h3><p>Tel: 4000-0002</p><a href="/suscripcion-novedades/">Formulario de contacto</a></section></main></body></html>"""
    home = '<html><head><title>Municipio de Vicente López</title></head><body><a href="/autoridades/">Autoridades</a></body></html>'
    relevar_real(dirs, VL, {"": home, "autoridades/": pagina})
    f = filas(dirs)
    assert f["Ceremonial y Protocolo"]["sitio_web"] == f["Ceremonial y Protocolo"]["url_fuente"]            # solo la página, sin "formulario"
    assert "suscrip" not in todo_el_texto(dirs).lower().replace("suscripción informativa", "")
    nodo = CP.BeautifulSoup(SUSCRIPCION, "lxml")
    assert CP.extraer_formulario(nodo, "https://x/") == ""


def test_un_formulario_de_contacto_real_si_se_registra_como_general():
    nodo = CP.BeautifulSoup('<form><input name="nombre"><textarea name="mensaje"></textarea><button>Enviar consulta</button></form>', "lxml")
    assert CP.extraer_formulario(nodo, "https://www.vicentelopez.gov.ar/contacto/") == "https://www.vicentelopez.gov.ar/contacto/"


# ------------------------------------------------------------------ 4. Avellaneda: TLS en robots.txt
def test_error_tls_en_robots_se_mantiene_como_incidencia_sin_eludirlo(dirs):
    err = requests.exceptions.SSLError("certificate verify failed")
    res, ses = relevar_real(dirs, AV, {"": "<html>x</html>"}, errores={"www.mda.gob.ar": err})
    assert not res["sitio_ok"] and C.leer_csv(dirs[0] / C.F_CONTACTOS) == []
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["campo"] == "contacto:sitio_oficial"]
    assert len(inc) == 1 and inc[0]["tipo_incidencia"] == "ROBOTS_NO_VERIFICABLE" and "ERROR_TLS" in inc[0]["descripcion"]
    assert ses.pedidos == ["https://www.mda.gob.ar/robots.txt"]                                 # sin reintento y sin pedir la página


def test_nunca_se_desactiva_la_verificacion_de_certificados():
    visto = {}

    class Captura(SesionPorHost):
        def get(self, url, timeout=None, allow_redirects=True, **kw):
            visto.update(kw)
            return super().get(url, timeout, allow_redirects)
    K.ClienteContactos(pausa=0, session=Captura({"https://a-prueba.gob.ar/": R(text="<p>x</p>")})).get("https://a-prueba.gob.ar/")
    assert "verify" not in visto
    for ruta in (AQUI.parent / "scripts").glob("*.py"):
        assert not re.search(r"verify\s*=\s*False|disable_warnings|CERT_NONE", ruta.read_text(encoding="utf-8")), ruta


# ------------------------------------------------------------------ privacidad intacta
def test_reglas_de_privacidad_siguen_vigentes(dirs):
    extra = '<p>Atención al vecino por WhatsApp: 11 5555-0000</p><p>Cel: 11 4444-1111</p><p>Escribinos a vecino.personal@gmail.com</p>'
    relevar_real(dirs, TDF, {"": portada_tdf(extra)})
    t = todo_el_texto(dirs)
    assert "5555" not in t and "4444" not in t and "gmail" not in t
    assert filas(dirs)["Contacto institucional general"]["email_institucional"] == "atencionalvecino@tresdefebrero.gov.ar"
