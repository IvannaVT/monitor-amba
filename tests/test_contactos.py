"""Directorio de vinculación: pruebas OFFLINE con un sitio municipal SINTÉTICO (dominio ficticio .gob.ar; no son datos reales)."""
import csv
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import contactos_parser as CP  # noqa: E402
import extraer as E  # noqa: E402
import validar as V  # noqa: E402
from test_pipeline import FakeSession, R  # noqa: E402

SITIO = "https://www.avellaneda-prueba.gob.ar"
HCD = "https://hcd.avellaneda-prueba.gob.ar"
BASES = {"avellaneda-prueba.gob.ar"}


def home(extra=""):
    return f"""<html><head><title>Municipalidad de Avellaneda (PRUEBA SINTÉTICA)</title></head><body>
<nav><a href="/autoridades/">Autoridades</a> <a href="/contacto/">Contacto</a> <a href="{HCD}/">Honorable Concejo Deliberante</a>
<a href="/cultura/">Cultura</a></nav><h1>Municipalidad de Avellaneda</h1>{extra}
<footer>Tel: 4201-0000 | Mesa general: <a href="mailto:info@avellaneda-prueba.gob.ar">info@avellaneda-prueba.gob.ar</a></footer></body></html>"""


AUTORIDADES = """<html><head><title>Autoridades</title></head><body><main>
<ul>
<li><h3>Ceremonial y Protocolo</h3><p>Director: Lic. Ana Ficticia</p><p>Tel: 4201-0001 int. 123 / 4201-0002</p>
<p><a href="mailto:protocolo@avellaneda-prueba.gob.ar">Escribir</a></p><p>Horario de atención: Lunes a viernes de 8 a 14 hs</p>
<p>Dirección: Calle Falsa 123, Avellaneda</p></li>
<li><h3>Secretaría Privada</h3><p>Secretario Privado: Pedro Ejemplo Prueba</p><p>privada@avellaneda-prueba.gob.ar</p>
<p>Cel: 11 5555-0000</p><p>Contacto: personal@gmail.com</p></li>
<li><h3>Relaciones Institucionales</h3><p>Sin datos de contacto publicados.</p></li>
</ul></main></body></html>"""

CONTACTO = """<html><head><title>Contacto</title></head><body><main>
<section class="contacto"><h2>Contacto institucional</h2><p>Teléfono: 4201-0000</p><p>Correo: info@avellaneda-prueba.gob.ar</p>
<p>Dirección: Av. Mitre 1, Avellaneda</p><form><textarea></textarea></form></section>
<div class="mesa"><h3>Mesa de Entradas</h3><p>Tel: 4201-0003</p><p>Horario: 8 a 13 hs</p></div></main></body></html>"""

HCD_HOME = """<html><head><title>HCD</title></head><body><a href="/autoridades/">Autoridades</a><div>
<h3>Presidencia del Honorable Concejo Deliberante</h3><p>Presidenta: Dra. Lucía Muestra</p><p>presidencia@hcd.avellaneda-prueba.gob.ar</p><p>Tel: 4201-0100</p></div>
<div><h3>Secretaría del Concejo Deliberante</h3><p>Tel: 4201-0101</p></div></body></html>"""


def sitio_ok(**mod):
    p = {SITIO + "/": R(text=home()), SITIO + "/autoridades/": R(text=AUTORIDADES), SITIO + "/contacto/": R(text=CONTACTO),
         SITIO + "/cultura/": R(text="<html><body>no relevante</body></html>"), HCD + "/": R(text=HCD_HOME)}
    p.update(mod)
    return p


@pytest.fixture()
def dirs(tmp_path):
    return tmp_path / "actual", tmp_path / "hist"


def correr(dirs, pag, fecha="2026-10-21", robots=None, estado="CANDIDATO_A_VERIFICAR", sitio=SITIO + "/"):
    ses = FakeSession(pag, robots)
    cli = E.Cliente(pausa=0, session=ses)
    cfg = {"municipio_id": "ba_avellaneda", "municipio": "Avellaneda"}
    res = K.relevar_municipio(cli, cfg, {"sitio_oficial": sitio, "estado": estado}, fecha, "S" + fecha.replace("-", ""))
    out = K.aplicar([res], fecha, "S" + fecha.replace("-", ""), dirs[0], dirs[1])
    return res, out, ses


def completar_archivos(dirs):
    """Los demás CSV (indicadores, etc.) existen en el repo; en la carpeta de prueba se crean vacíos para poder validar."""
    for n, cols in C.ESQUEMAS.items():
        if not (dirs[0] / n).exists():
            C.escribir_csv(dirs[0] / n, [], cols)


def filas(dirs):
    return {f["dependencia"]: f for f in C.leer_csv(dirs[0] / C.F_CONTACTOS)}


# ------------------------------------------------------------- extractores
def test_emails_institucionales_y_omision_de_no_institucionales():
    nodo = CP.BeautifulSoup('<p>a@avellaneda-prueba.gob.ar <a href="mailto:x@gmail.com">x</a> b@otra.gob.ar</p>', "lxml")
    buenos, omit = CP.extraer_emails(nodo, BASES)
    assert buenos == ["a@avellaneda-prueba.gob.ar", "b@otra.gob.ar"] and omit == 1


def test_telefonos_con_etiqueta_sin_moviles_ni_cuit():
    nodo = CP.BeautifulSoup("<div>Tel: 4201-0001 / 4201-0002</div><div>Celular: 11 5555-0000</div><div>CUIT 30-12345678-9</div>"
                            "<div>WhatsApp 11 4444-1111</div><a href='tel:+5411 4201 0009'>llamar</a>", "lxml")
    tels, omit = CP.extraer_telefonos(nodo)
    assert tels == ["4201-0001", "4201-0002", "+5411 4201 0009"] and omit == 2


def test_internos_horario_direccion():
    t = "Tel: 4201-0001 int. 123, 124\nHorario de atención: Lunes a viernes de 8 a 14 hs\nDirección: Calle Falsa 123, Avellaneda"
    assert CP.extraer_internos(t) == ["123", "124"] and CP.extraer_horario(t).startswith("Lunes a viernes")
    assert CP.extraer_direccion(t) == "Calle Falsa 123, Avellaneda" and CP.extraer_direccion("Dirección: Secretaría") == ""


@pytest.mark.parametrize("lineas,esperado", [
    (["Director: Lic. Ana Ficticia"], ("Ana Ficticia", "Director")),
    (["Secretario Privado", "Pedro Ejemplo Prueba"], ("Pedro Ejemplo Prueba", "Secretario Privado")),
    (["Director", "Ceremonial y Protocolo"], ("", "")),                  # título de oficina, no persona
    (["Director", "protocolo@x.gob.ar"], ("", "")),
    (["Directora: Tel 4201-0001"], ("", "")),
    (["Presidente: lucía muestra"], ("", "")),                            # sin mayúsculas: no se acepta
])
def test_responsable_solo_si_es_un_nombre_publicado(lineas, esperado):
    n, c, _ = CP.extraer_responsable(lineas)
    assert (n, c) == esperado


# ------------------------------------------------------------- atribución por bloque
def test_atribucion_solo_dentro_del_bloque_y_ambiguos_sin_canal():
    html = """<body><ul><li><b>Ceremonial y Protocolo</b></li><li><b>Relaciones Institucionales</b></li>
<li>Tel: 4201-9999 correo: x@avellaneda-prueba.gob.ar</li></ul><footer>Tel: 4201-0000</footer></body>"""
    a = CP.analizar_pagina(html, SITIO + "/p", BASES)
    h = {x["clave"]: x for x in a["hallazgos"]}
    assert not h["ceremonial"]["con_canal"] and not h["relaciones"]["con_canal"]   # el contacto está en otro bloque: no se atribuye
    assert a["general"] and a["general"]["telefonos"] == ["4201-0000"]            # el pie solo alimenta el contacto general


def test_pie_de_pagina_no_se_atribuye_a_la_dependencia():
    html = "<body><main><h1>Ceremonial y Protocolo</h1><p>Texto.</p></main><footer>Tel: 4201-0000 info@avellaneda-prueba.gob.ar</footer></body>"
    h = CP.analizar_pagina(html, SITIO + "/protocolo/", BASES)["hallazgos"][0]
    assert h["clave"] == "ceremonial" and not h["con_canal"]


# ------------------------------------------------------------- flujo completo
def test_relevamiento_piloto_sintetico(dirs):
    res, out, ses = correr(dirs, sitio_ok())
    f = filas(dirs)
    cer = f["Ceremonial y Protocolo"]
    assert cer["tipo_contacto"] == "ESPECIFICO_PROTOCOLO" and cer["organismo"] == "Municipalidad de Avellaneda"
    assert cer["responsable_nombre"] == "Ana" and cer["responsable_apellido"] == "Ficticia" and cer["responsable_nombre_completo"] == "Ana Ficticia"
    assert cer["cargo"] == "Director" and cer["email_institucional"] == "protocolo@avellaneda-prueba.gob.ar"
    assert cer["telefono_institucional"] == "4201-0001; 4201-0002" and cer["interno"] == "123"
    assert cer["horario_atencion"].startswith("Lunes a viernes") and cer["direccion"] == "Calle Falsa 123, Avellaneda"
    assert cer["url_fuente"] == SITIO + "/autoridades/" and cer["fecha_consulta"] == "2026-10-21"
    priv = f["Secretaría Privada del Intendente"]
    assert priv["email_institucional"] == "privada@avellaneda-prueba.gob.ar" and priv["telefono_institucional"] == ""   # celular y gmail omitidos
    assert priv["responsable_nombre"] == "" and priv["responsable_nombre_completo"] == "Pedro Ejemplo Prueba"            # 3 palabras: sin dividir
    assert f["Relaciones Institucionales"]["estado_contacto"] == "DEPENDENCIA_SIN_CANAL"
    assert f["Despacho del Intendente / Jefatura de Gabinete"]["estado_contacto"] == "NO_ENCONTRADO"
    assert f["Presidencia del Concejo Deliberante"]["organismo"] == "Honorable Concejo Deliberante de Avellaneda"
    assert f["Presidencia del Concejo Deliberante"]["email_institucional"] == "presidencia@hcd.avellaneda-prueba.gob.ar"
    assert f["Secretaría del Concejo Deliberante"]["telefono_institucional"] == "4201-0101"
    assert f["Mesa de Entradas"]["telefono_institucional"] == "4201-0003"
    assert f["Contacto institucional general"]["tipo_contacto"] == "CONTACTO_ALTERNATIVO" and f["Contacto institucional general"]["sitio_web"]
    assert all(r["tipo_contacto"] in C.TIPOS_CONTACTO and r["estado_contacto"] in C.ESTADOS_CONTACTO for r in f.values())


def test_estados_de_vigencia(dirs):
    correr(dirs, sitio_ok())
    f = filas(dirs)
    assert f["Ceremonial y Protocolo"]["estado_contacto"] == "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"   # una sola página
    assert f["Contacto institucional general"]["estado_contacto"] == "VIGENTE_CONFIRMADO"          # mismo correo/teléfono en 2+ páginas
    assert f["Ceremonial y Protocolo"]["fecha_verificacion"] == "2026-10-21"
    assert f["Despacho del Intendente / Jefatura de Gabinete"]["fecha_verificacion"] == ""
    fechada = AUTORIDADES.replace("</main>", "<p>Actualizado al 2026-09-30</p></main>")
    d2 = (dirs[0].parent / "a2", dirs[0].parent / "h2")
    correr(d2, sitio_ok(**{SITIO + "/autoridades/": R(text=fechada)}))
    assert filas(d2)["Ceremonial y Protocolo"]["estado_contacto"] == "VIGENTE_CONFIRMADO"            # página con fecha reciente visible


def test_trazabilidad_incidencias_y_validacion(dirs):
    correr(dirs, sitio_ok())
    fu = C.leer_csv(dirs[0] / C.F_FUENTES)
    e = [x for x in fu if x["campo_verificado"] == "email_institucional" and x["entidad"] == "contacto:ceremonial"]
    assert len(e) == 1 and e[0]["valor_obtenido"] == "protocolo@avellaneda-prueba.gob.ar" and e[0]["documento_url"] == SITIO + "/autoridades/"
    assert e[0]["fuente_tipo"] == "SITIO_OFICIAL_MUNICIPAL" and e[0]["fecha_consulta"] == "2026-10-21" and "evidencia=" in e[0]["observaciones"]
    tipos = {(i["campo"], i["tipo_incidencia"]) for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
    assert ("contacto:despacho", "OFICINA_NO_ENCONTRADA") in tipos and ("contacto:relaciones", "CANAL_NO_ENCONTRADO") in tipos
    assert ("contacto:privada", "CANAL_NO_INSTITUCIONAL_OMITIDO") in tipos
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_no_se_inventan_correos_ni_telefonos(dirs):
    pag = sitio_ok(**{SITIO + "/autoridades/": R(text="<html><body><h3>Ceremonial y Protocolo</h3><p>Director: Ana Ficticia</p></body></html>")})
    correr(dirs, pag)
    cer = filas(dirs)["Ceremonial y Protocolo"]
    assert cer["estado_contacto"] == "DEPENDENCIA_SIN_CANAL" and cer["email_institucional"] == "" and cer["telefono_institucional"] == ""


# ------------------------------------------------------------- accesos y verificación del sitio
def test_sitio_no_verificado_no_genera_filas(dirs):
    for pag, estado in ((sitio_ok(**{SITIO + "/": R(text="<html><title>Otro lugar</title><h1>Otro</h1></html>")}), "CANDIDATO"),
                        ({"https://www.avellaneda-prueba.com/": R(text=home())}, "CANDIDATO")):
        d = (dirs[0].parent / str(len(pag)), dirs[1])
        sitio = SITIO + "/" if "gob.ar" in next(iter(pag)) else "https://www.avellaneda-prueba.com/"
        correr(d, pag, sitio=sitio)
        assert C.leer_csv(d[0] / C.F_CONTACTOS) == []
        assert "SITIO_NO_VERIFICADO" in {i["tipo_incidencia"] for i in C.leer_csv(d[0] / C.F_INCIDENCIAS)}


def test_sin_sitio_configurado_y_accesos_bloqueados(dirs, tmp_path):
    correr(dirs, {}, sitio="")
    assert "SITIO_OFICIAL_NO_CONFIGURADO" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
    for estado, tipo in ((403, "ACCESO_DENEGADO_HTTP"), (429, "LIMITE_SOLICITUDES_429")):
        d = (tmp_path / f"a{estado}", tmp_path / f"h{estado}")
        res, _, ses = correr(d, sitio_ok(**{SITIO + "/autoridades/": R(estado)}))
        assert ses.pedidos.count(SITIO + "/autoridades/") == 1                       # sin reintento
        assert tipo in {i["tipo_incidencia"] for i in C.leer_csv(d[0] / C.F_INCIDENCIAS)}
        assert filas(d)["Ceremonial y Protocolo"]["estado_contacto"] == "NO_ENCONTRADO"   # no se afirma nada que no se vio


def test_robots_prohibe_y_no_se_consulta(dirs):
    _, _, ses = correr(dirs, sitio_ok(), robots="User-agent: *\nDisallow: /")
    assert ses.pedidos == [SITIO + "/robots.txt"]
    assert "PROHIBIDO_POR_ROBOTS" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


# ------------------------------------------------------------- incremental, historial, alertas
def test_reejecucion_sin_cambios_no_escribe_ni_alerta(dirs):
    correr(dirs, sitio_ok(), fecha="2026-10-21")
    existentes = [n for n in C.ESQUEMAS if (dirs[0] / n).exists()]
    antes = {n: (dirs[0] / n).read_bytes() for n in existentes}
    _, out, _ = correr(dirs, sitio_ok(), fecha="2026-10-28")
    assert out["archivos_escritos"] == [] and out["alertas_nuevas"] == 0
    assert antes == {n: (dirs[0] / n).read_bytes() for n in existentes}


def test_cambio_de_correo_genera_alerta_e_historial(dirs):
    correr(dirs, sitio_ok(), fecha="2026-10-21")                                     # línea de base: sin alertas
    assert C.leer_csv(dirs[0] / C.F_ALERTAS) == []
    nuevo = AUTORIDADES.replace("protocolo@avellaneda-prueba.gob.ar", "ceremonial@avellaneda-prueba.gob.ar")
    correr(dirs, sitio_ok(**{SITIO + "/autoridades/": R(text=nuevo)}), fecha="2026-10-28")
    al = C.leer_csv(dirs[0] / C.F_ALERTAS)
    assert [a["categoria_alerta"] for a in al] == ["CAMBIO_CONTACTO_OFICIAL"] and al[0]["valor_anterior"].startswith("protocolo@")
    assert (dirs[1] / "2026-10-28" / C.F_CONTACTOS).exists()
    assert filas(dirs)["Ceremonial y Protocolo"]["email_institucional"] == "ceremonial@avellaneda-prueba.gob.ar"


def test_canal_que_deja_de_verse_se_conserva_sin_vigencia(dirs):
    correr(dirs, sitio_ok(), fecha="2026-10-21")
    sin = "<html><body><h3>Ceremonial y Protocolo</h3><p>Texto.</p></body></html>"
    correr(dirs, sitio_ok(**{SITIO + "/autoridades/": R(text=sin)}), fecha="2026-10-28")
    cer = filas(dirs)["Ceremonial y Protocolo"]
    assert cer["email_institucional"] == "protocolo@avellaneda-prueba.gob.ar" and cer["estado_contacto"] == "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"
    assert "CONTACTO_YA_NO_VISIBLE" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


def test_nueva_dependencia_en_municipio_con_linea_de_base_genera_alerta_informativa(dirs):
    sin = sitio_ok(**{SITIO + "/autoridades/": R(text="<html><body><p>nada</p></body></html>")})
    correr(dirs, sin, fecha="2026-10-21")
    correr(dirs, sitio_ok(), fecha="2026-10-28")
    cats = {a["categoria_alerta"]: a["severidad"] for a in C.leer_csv(dirs[0] / C.F_ALERTAS)}
    assert cats.get("NUEVO_CONTACTO_OFICIAL") == "INFORMATIVA"


# ------------------------------------------------------------- independencia, validador y workflow
def test_relevamiento_no_toca_indicadores_ni_municipios(dirs):
    dirs[0].mkdir(parents=True)
    for n in (C.F_MUNICIPIOS, C.F_INDICADORES):
        C.escribir_csv(dirs[0] / n, [], C.ESQUEMAS[n])
    antes = {n: (dirs[0] / n).read_bytes() for n in (C.F_MUNICIPIOS, C.F_INDICADORES)}
    correr(dirs, sitio_ok())
    assert antes == {n: (dirs[0] / n).read_bytes() for n in (C.F_MUNICIPIOS, C.F_INDICADORES)}


def test_extraccion_de_indicadores_conserva_los_contactos(dirs):
    correr(dirs, sitio_ok())
    previo = C.leer_csv(dirs[0] / C.F_CONTACTOS)
    from test_pipeline import paginas, correr as correr_ind
    correr_ind(dirs, paginas(), municipios="avellaneda")
    assert C.leer_csv(dirs[0] / C.F_CONTACTOS) == previo


def test_validador_detecta_problemas_en_contactos(dirs):
    correr(dirs, sitio_ok())
    completar_archivos(dirs)
    p = dirs[0] / C.F_CONTACTOS
    rows = C.leer_csv(p)
    rows[0].update(estado_contacto="VIGENTE", tipo_contacto="X", email_institucional="mal-correo; usuario@gmail.com",
                   telefono_institucional="abc", url_fuente="www.sin-esquema.gob.ar")
    rows.append(dict(rows[1]))
    C.escribir_csv(p, rows, C.ESQUEMAS[C.F_CONTACTOS])
    e = "\n".join(V.validar(dirs[0], "prueba")[0])
    for frag in ("estado_contacto inválido", "tipo_contacto inválido", "correo inválido", "no institucional", "teléfono inválido", "URL no completa", "duplicada"):
        assert frag in e, (frag, e)


def test_workflow_de_contactos_separado_manual_y_sin_commit_por_defecto():
    wf = (AQUI.parent / ".github" / "workflows" / "relevar_contactos.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in wf and "\n  schedule:" not in wf and "scripts/contactos.py" in wf and "scripts/extraer.py" not in wf
    assert "default: false" in wf.split("confirmar_cambios:")[1][:200] and "modo" in wf


def test_sitios_oficiales_config():
    cfg = list(csv.DictReader(open(K.SITIOS, encoding="utf-8-sig"), delimiter=";"))
    assert len(cfg) == 40 and {r["municipio_id"] for r in cfg} == {m["municipio_id"] for m in C.cargar_municipios_cfg()}
    assert all(r["estado"] in ("SIN_CONFIGURAR", "CANDIDATO_A_VERIFICAR", "VERIFICADO_TECNICAMENTE", "CONFIRMADO") for r in cfg)
    assert all(r["sitio_oficial"].startswith("https://") for r in cfg if r["sitio_oficial"])
