"""Validación territorial: Ituzaingó (Buenos Aires ≠ Corrientes), homónimos de otras provincias, sitios oficiales documentados
(fuente provincial) y su separación de la verificación técnica HTTP. Páginas SINTÉTICAS; no se consulta la red."""
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
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

SIT = {r["municipio_id"]: r for r in C.leer_csv(C.ARCHIVO_SITIOS)}
CFG = {m["municipio_id"]: m for m in C.cargar_municipios_cfg()}
GBA = "https://www.gba.gob.ar/municipios"
DOCUMENTADOS = {
    "ba_berisso": "https://www.berisso.gov.ar/", "ba_brandsen": "https://www.brandsen.gob.ar/", "ba_ensenada": "https://www.ensenada.gov.ar/",
    "ba_exaltacion_de_la_cruz": "https://www.exaltaciondelacruz.gov.ar/", "ba_florencio_varela": "https://www.florenciovarela.gov.ar/",
    "ba_general_las_heras": "https://www.gobiernodelasheras.com/", "ba_general_rodriguez": "https://www.generalrodriguez.gov.ar/",
    "ba_presidente_peron": "https://www.presidenteperon.gov.ar/", "ba_ituzaingo": "https://miituzaingo.gov.ar/"}


def pag(titulo, cuerpo="", enlaces=""):
    return f"<html><head><title>{titulo}</title></head><body><h1>{titulo}</h1>{cuerpo}{enlaces}</body></html>"


def verificar(paginas, raiz, nombre="Ituzaingó", **kw):
    return D.verificar_raiz(K.ClienteContactos(pausa=0, session=SesionPorHost(paginas)), raiz, nombre, **kw)


# ------------------------------------------------------------------ Ituzaingó
def test_ituzaingo_bonaerense_corregido_y_el_dominio_de_corrientes_bloqueado():
    r = SIT["ba_ituzaingo"]
    assert r["sitio_oficial"] == "https://miituzaingo.gov.ar/" and r["estado"] == "OFICIAL_DOCUMENTADO"
    assert GBA in r["fuente"] and "Corrientes" in r["fuente"] and r["verificacion_http"] == ""
    assert CP.dominio_homonimo("www.ituzaingo.gob.ar") == "Ituzaingó (Corrientes)"
    assert not CP.dominio_homonimo("miituzaingo.gov.ar")
    assert all(urlparse(s["sitio_oficial"]).hostname.removeprefix("www.") != "ituzaingo.gob.ar" for s in SIT.values())


# ------------------------------------------------------------------ homónimos: nunca se verifican automáticamente
def test_dominio_homonimo_conocido_no_se_verifica_aunque_el_titulo_y_la_provincia_parezcan_correctos():
    r = verificar({"https://www.ituzaingo.gob.ar/": R(text=pag("Municipalidad de Ituzaingó", "<p>Provincia de Buenos Aires</p>"))}, "https://www.ituzaingo.gob.ar/")
    assert not r["ok"] and "homónimo" in r["detalle"]


def test_pagina_que_se_declara_de_otra_provincia_no_se_verifica():
    r = verificar({"https://www.ituzaingo-prueba.gob.ar/": R(text=pag("Municipio de Ituzaingó", "<p>Ituzaingó, Provincia de Corrientes</p>"))}, "https://www.ituzaingo-prueba.gob.ar/")
    assert not r["ok"] and "homónimo" in r["detalle"]


def test_sin_evidencia_positiva_de_la_provincia_de_buenos_aires_no_se_verifica():
    p = {"https://www.ituzaingo-prueba.gob.ar/": R(text=pag("Municipio de Ituzaingó", "<p>Avenida Buenos Aires 123</p>"))}   # una calle no es evidencia
    r = verificar(p, "https://www.ituzaingo-prueba.gob.ar/")
    assert not r["ok"] and "sin evidencia de pertenecer a la provincia de Buenos Aires" in r["detalle"]


@pytest.mark.parametrize("cuerpo,enlaces", [("<p>Municipio de la Provincia de Buenos Aires</p>", ""),
                                            ("<p>Pcia. de Bs. As.</p>", ""),
                                            ("", '<a href="https://www.gba.gob.ar/">Gobierno de la Provincia</a>')])
def test_con_evidencia_positiva_de_la_provincia_si_se_verifica(cuerpo, enlaces):
    r = verificar({"https://www.ituzaingo-prueba.gob.ar/": R(text=pag("Municipio de Ituzaingó", cuerpo, enlaces))}, "https://www.ituzaingo-prueba.gob.ar/")
    assert r["ok"] and r["http"] == 200


def test_el_descubrimiento_deja_un_candidato_homonimo_sin_verificar():
    sitios = {"ba_ituzaingo": {"municipio_id": "ba_ituzaingo", "sitio_oficial": "https://www.ituzaingo.gob.ar/", "estado": "CANDIDATO_A_VERIFICAR", "fuente": ""}}
    ses = SesionPorHost({"https://www.ituzaingo.gob.ar/": R(text=pag("Municipalidad de Ituzaingó", "<p>Provincia de Buenos Aires</p>"))})
    cfg = dict(CFG["ba_ituzaingo"], url_portal_municipio="")
    res = D.descubrir(K.ClienteContactos(pausa=0, session=ses), [cfg], sitios, [cfg])[0]
    assert res["estado"] == "CANDIDATO_NO_VERIFICADO" and "homónimo" in res["detalle"] and res["sitio"] == ""


@pytest.mark.parametrize("estado", ["CANDIDATO_A_VERIFICAR", "CONFIRMADO", "OFICIAL_DOCUMENTADO"])
def test_el_relevamiento_no_usa_un_dominio_homonimo_en_ningun_estado(dirs, estado):
    ses = SesionPorHost({"https://www.ituzaingo.gob.ar/": R(text=pag("Municipalidad de Ituzaingó", '<footer>Tel: 4000-1234 <a href="mailto:a@ituzaingo.gob.ar">a@ituzaingo.gob.ar</a></footer>'))})
    res = K.relevar_municipio(K.ClienteContactos(pausa=0, session=ses), {"municipio_id": "ba_ituzaingo", "municipio": "Ituzaingó"},
                              {"sitio_oficial": "https://www.ituzaingo.gob.ar/", "estado": estado}, "2026-10-22", "S1")
    assert not res["sitio_ok"] and [i["tipo_incidencia"] for i in res["incidencias"]] == ["SITIO_HOMONIMO"]


def test_el_registro_de_homonimos_se_extiende_por_configuracion(tmp_path, monkeypatch):
    p = tmp_path / "h.csv"
    p.write_text("﻿dominio;municipio;provincia;fuente\nwww.lujan-prueba.gob.ar;Luján;San Luis;prueba\n", encoding="utf-8")
    monkeypatch.setattr(C, "ARCHIVO_HOMONIMOS", p)
    d = CP._cargar_homonimos()
    assert d["lujan-prueba.gob.ar"] == "Luján (San Luis)" and "ituzaingo.gob.ar" in d and "avellaneda.gob.ar" in d     # base fija + config


def test_el_validador_rechaza_un_homonimo_documentado_en_la_config(tmp_path, monkeypatch):
    p = tmp_path / "s.csv"
    monkeypatch.setattr(C, "ARCHIVO_SITIOS", p)
    p.write_text(f"﻿municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados;fuentes_alternativas;verificacion_http\n"
                 f"ba_ituzaingo;https://www.ituzaingo.gob.ar/;;OFICIAL_DOCUMENTADO;{GBA};;;\n", encoding="utf-8")
    assert "homónimo de otra provincia" in "\n".join(V.validar(Path("/nonexistent"), "prueba")[0])


# ------------------------------------------------------------------ los ocho sitios documentados
@pytest.mark.parametrize("mid,url", sorted(DOCUMENTADOS.items()))
def test_sitios_documentados_con_fuente_provincial_y_sin_verificacion_http(mid, url):
    r = SIT[mid]
    assert (r["sitio_oficial"], r["estado"]) == (url, "OFICIAL_DOCUMENTADO")
    assert GBA in r["fuente"] and "DOCUMENTAL" in r["fuente"] and "sin verificación técnica HTTP" in r["fuente"]
    assert r["verificacion_http"] == "" and r["estado"] != "VERIFICADO_TECNICAMENTE"        # condición documental ≠ verificación HTTP


def test_dominio_no_gubernamental_solo_con_referencia_oficial_explicita():
    no_gub = [m for m, r in SIT.items() if not urlparse(r["sitio_oficial"]).hostname.endswith((".gob.ar", ".gov.ar"))]
    assert no_gub == ["ba_general_las_heras"] and "referencia oficial explícita" in SIT["ba_general_las_heras"]["fuente"]
    assert not [e for e in V.validar(Path("/nonexistent"), "prueba")[0] if "sitios_oficiales" in e]


def test_el_validador_exige_la_referencia_para_dominios_no_gubernamentales_y_documentados(tmp_path, monkeypatch):
    p = tmp_path / "s.csv"
    monkeypatch.setattr(C, "ARCHIVO_SITIOS", p)
    cab = "﻿municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados;fuentes_alternativas;verificacion_http\n"
    p.write_text(cab + "ba_a;https://www.a-prueba.com/;;CANDIDATO_A_VERIFICAR;x;;;\n"                      # .com sin referencia
                 "ba_b;https://www.b-prueba.com/;;OFICIAL_DOCUMENTADO;otra fuente;;;\n"                      # documentado sin citar la fuente provincial
                 f"ba_c;https://www.c-prueba.com/;;OFICIAL_DOCUMENTADO;{GBA};;;\n", encoding="utf-8")        # válido
    e = "\n".join(V.validar(Path("/nonexistent"), "prueba")[0])
    assert "ba_a: dominio no gubernamental" in e and "ba_b: OFICIAL_DOCUMENTADO debe citar la fuente provincial" in e and "sitios_oficiales.csv ba_c" not in e


def test_base_de_distingue_dominios_gubernamentales_y_comerciales():
    assert D.base_de("www.berisso.gov.ar") == "berisso.gov.ar" and D.base_de("hacienda.x.gob.ar") == "x.gob.ar"
    assert D.base_de("www.gobiernodelasheras.com") == "gobiernodelasheras.com"


# ------------------------------------------------------------------ verificación HTTP aparte (no cambia la condición documental)
def run_doc(paginas, errores=None, mid="ba_general_las_heras"):
    cfg = CFG[mid]
    sitios = {mid: dict(SIT[mid])}
    cli = K.ClienteContactos(pausa=0, session=SesionPorHost(paginas, errores=errores))
    return D.descubrir(cli, [cfg], sitios, [cfg])[0]


def test_http_ok_se_registra_en_su_columna_sin_cambiar_el_estado_documental(tmp_path):
    u = SIT["ba_general_las_heras"]["sitio_oficial"]
    r = run_doc({u: R(text=pag("Gobierno de Las Heras"))})                       # el título no nombra al municipio y el dominio es .com: no importa
    assert r["estado"] == "DOCUMENTADO_HTTP_OK" and r["http"] == 200
    ruta = tmp_path / "s.csv"
    ruta.write_bytes(C.ARCHIVO_SITIOS.read_bytes())
    assert D.aplicar_config([r], ruta, "2026-10-22") == 0
    f = {x["municipio_id"]: x for x in C.leer_csv(ruta)}["ba_general_las_heras"]
    assert f["estado"] == "OFICIAL_DOCUMENTADO" and f["verificacion_http"].startswith("HTTP 200 verificado el 2026-10-22")
    assert f["sitio_oficial"] == u


@pytest.mark.parametrize("pags,errores,frag", [({}, None, "HTTP 404"),
                                               ({"https://www.gobiernodelasheras.com/": R(text=pag("x"))}, {"www.gobiernodelasheras.com": requests.exceptions.SSLError("certificate verify failed")}, "ERROR_TLS"),
                                               ({"https://www.gobiernodelasheras.com/": R(301, location="https://otro-dominio.com/")}, None, "no está verificado como oficial")])
def test_http_fallido_queda_documentado_sin_eludir_nada(tmp_path, pags, errores, frag):
    r = run_doc(pags, errores)
    assert r["estado"] == "DOCUMENTADO_HTTP_FALLIDO" and frag in r["detalle"]
    ruta = tmp_path / "s.csv"
    ruta.write_bytes(C.ARCHIVO_SITIOS.read_bytes())
    D.aplicar_config([r], ruta, "2026-10-22")
    f = {x["municipio_id"]: x for x in C.leer_csv(ruta)}["ba_general_las_heras"]
    assert f["estado"] == "OFICIAL_DOCUMENTADO" and f["verificacion_http"].startswith("NO verificado el 2026-10-22") and frag in f["verificacion_http"]


def test_los_candidatos_no_verificados_conservan_su_incidencia(dirs):
    cfg = CFG["ba_lanus"]
    sitios = {"ba_lanus": dict(SIT["ba_lanus"])}
    tls = {"www.lanus.gob.ar": requests.exceptions.SSLError("certificate verify failed")}
    for _ in range(2):                                                          # dos ejecuciones: la incidencia se mantiene abierta
        r = D.descubrir(K.ClienteContactos(pausa=0, session=SesionPorHost({}, errores=tls)), [dict(cfg, url_portal_municipio="")], sitios,
                        [dict(cfg, url_portal_municipio="")])[0]
        D.registrar_incidencias([r], dirs[0], dirs[1])
    assert r["estado"] == "CANDIDATO_NO_VERIFICADO" and "ERROR_TLS" in r["detalle"] and r["sitio"] == ""
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["municipio_id"] == "ba_lanus"]
    assert len(inc) == 1 and inc[0]["tipo_incidencia"] == "CANDIDATO_NO_VERIFICADO" and inc[0]["estado_resolucion"] == "ABIERTA"


def test_relevamiento_de_un_sitio_documentado_no_gubernamental_solo_con_canales_institucionales(dirs):
    u = SIT["ba_general_las_heras"]["sitio_oficial"]
    cuerpo = '<footer>Tel: 4000-5555 <a href="mailto:info@gobiernodelasheras.com">info@gobiernodelasheras.com</a> <a href="mailto:personal@gmail.com">p</a></footer>'
    ses = SesionPorHost({u: R(text=pag("Gobierno", cuerpo))})
    res = K.relevar_municipio(K.ClienteContactos(pausa=0, session=ses), {"municipio_id": "ba_general_las_heras", "municipio": "General Las Heras"},
                              dict(SIT["ba_general_las_heras"]), "2026-10-22", "S1")
    assert res["sitio_ok"]
    K.aplicar([res], "2026-10-22", "S1", dirs[0], dirs[1], verificados={})
    g = {r["dependencia"]: r for r in C.leer_csv(dirs[0] / C.F_CONTACTOS)}["Contacto institucional general"]
    assert g["email_institucional"] == "info@gobiernodelasheras.com" and "gmail" not in "".join(
        (dirs[0] / n).read_text(encoding="utf-8-sig") for n in (C.F_CONTACTOS, C.F_FUENTES))
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == []
