"""Dominio correcto por municipio, homónimos de otras provincias y relevamiento exclusivamente institucional.

Páginas SINTÉTICAS; los hosts reales se leen de config/sitios_oficiales.csv. No se consulta la red.
"""
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import contactos_parser as CP  # noqa: E402
import validar as V  # noqa: E402
from test_contactos import completar_archivos, dirs  # noqa: E402,F401
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost, relevar  # noqa: E402

CFG = {r["municipio_id"]: r for r in csv.DictReader(open(K.SITIOS, encoding="utf-8-sig"), delimiter=";")}
# Hosts oficiales esperados (provistos por el usuario). Solo viven en las pruebas.
ESPERADO = {"ba_avellaneda": ("Avellaneda", "mda.gob.ar"), "ba_vicente_lopez": ("Vicente López", "vicentelopez.gov.ar"),
            "ba_tres_de_febrero": ("Tres de Febrero", "tresdefebrero.gov.ar")}


def host(mid):
    return CP.dominio_base(urlparse(CFG[mid]["sitio_oficial"]).hostname)


# ------------------------------------------------------------------ dominio ↔ municipio
@pytest.mark.parametrize("mid", list(ESPERADO))
def test_cada_dominio_corresponde_a_su_municipio(mid):
    assert host(mid) == ESPERADO[mid][1] and CFG[mid]["sitio_oficial"].startswith("https://www.")
    assert not CP.dominio_homonimo(host(mid))
    otros = {host(m) for m in ESPERADO if m != mid}
    assert host(mid) not in otros                                                    # un dominio no se comparte entre municipios


def test_el_dominio_de_avellaneda_santa_fe_esta_identificado_como_homonimo():
    assert CP.dominio_homonimo("www.avellaneda.gob.ar") == "Avellaneda (Santa Fe)" and CP.dominio_homonimo("x.avellaneda.gob.ar")
    assert not CP.dominio_homonimo("mda.gob.ar") and not CP.dominio_homonimo("notavellaneda.gob.ar")


def test_validador_de_la_config_real_sin_errores():
    err = V.validar(Path("/nonexistent"), "prueba")[0]
    assert not [e for e in err if "sitios_oficiales" in e]


def test_validador_detecta_sitios_mal_configurados(dirs, tmp_path, monkeypatch):
    p = tmp_path / "s.csv"
    monkeypatch.setattr(C, "ARCHIVO_SITIOS", p)
    cab = "municipio_id;sitio_oficial;sitio_hcd;estado;fuente;dominios_verificados\n"
    filas = ("ba_avellaneda;https://www.avellaneda.gob.ar/;;CONFIRMADO;x;\n"            # homónimo de Santa Fe
             "ba_lanus;http://www.lanus-prueba.gob.ar/;;CONFIRMADO;x;\n"                 # sin https
             "ba_quilmes;https://www.lanus-prueba.gob.ar/;;CONFIRMADO;;\n"               # dominio repetido y sin fuente
             "ba_merlo;https://www.merlo-prueba.gob.ar/;;CONFIRMADO;x;avellaneda.gob.ar\n")  # alias homónimo
    p.write_text("﻿" + cab + filas, encoding="utf-8")
    e = "\n".join(V.validar(Path("/nonexistent"), "prueba")[0])
    for frag in ("homónimo de otra provincia", "URL https completa", "ya está asignado", "sin fuente de la verificación", "incluye el homónimo"):
        assert frag in e, (frag, e)


# ------------------------------------------------------------------ guardas en el relevamiento
def pagina_con(texto_extra="", titulo="Portal municipal"):
    return f"<html><head><title>{titulo}</title></head><body><h1>{titulo}</h1><p>{texto_extra}</p></body></html>"


def test_dominio_homonimo_se_bloquea_aun_confirmado(dirs):
    url = "https://www.avellaneda.gob.ar/"
    res, _, _ = relevar(dirs, {url: R(text=pagina_con(titulo="Municipalidad de Avellaneda"))}, url, {"estado": "CONFIRMADO"})
    assert not res["sitio_ok"] and C.leer_csv(dirs[0] / C.F_CONTACTOS) == []
    i = [x for x in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if x["tipo_incidencia"] == "SITIO_HOMONIMO"]
    assert len(i) == 1 and "Santa Fe" in i[0]["descripcion"] and i[0]["campo"] == "contacto:sitio_oficial"


def test_pagina_que_se_declara_de_otra_provincia_se_bloquea(dirs):
    url = "https://www.sitio-prueba.gob.ar/"
    res, _, _ = relevar(dirs, {url: R(text=pagina_con("Municipalidad de Tres de Febrero - Provincia de Santa Fe"))}, url, {"estado": "CONFIRMADO"})
    assert not res["sitio_ok"] and "SITIO_HOMONIMO" in {x["tipo_incidencia"] for x in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


def test_una_calle_santa_fe_o_la_provincia_correcta_no_bloquean(dirs):
    url = "https://www.sitio-prueba.gob.ar/"
    for texto in ("Dirección: Av. Santa Fe 1234", "Municipalidad de Tres de Febrero - Provincia de Buenos Aires. Cerca de Provincia de Santa Fe"):
        d = (dirs[0].parent / str(abs(hash(texto))), dirs[1])
        res, _, _ = relevar(d, {url: R(text=pagina_con(texto))}, url, {"estado": "CONFIRMADO"})
        assert res["sitio_ok"], texto


def test_un_alias_homonimo_en_la_config_no_habilita_la_redireccion(dirs):
    pag = {"https://www.mda-prueba.gob.ar/": R(301, location="https://www.avellaneda.gob.ar/"),
           "https://www.avellaneda.gob.ar/": R(text=pagina_con())}
    res, _, ses = relevar(dirs, pag, "https://www.mda-prueba.gob.ar/", {"estado": "CONFIRMADO", "dominios_verificados": "avellaneda.gob.ar"})
    assert not res["sitio_ok"] and "https://www.avellaneda.gob.ar/" not in ses.pedidos
    assert "REDIRECCION_EXTERNA" in {x["tipo_incidencia"] for x in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}


# ------------------------------------------------------------------ solo canales institucionales (con los hosts reales)
@pytest.mark.parametrize("mid", list(ESPERADO))
def test_solo_se_registran_canales_institucionales_en_cada_dominio(mid, dirs):
    nombre, dom = ESPERADO[mid]
    url = CFG[mid]["sitio_oficial"]
    home = '<html><head><title>Inicio</title></head><body><a href="/autoridades/">Autoridades</a></body></html>'
    aut = f"""<html><body><section><h3>Ceremonial y Protocolo</h3><p>Tel: 4000-0001</p><p>Celular: 11 5555-1111</p>
<p>protocolo@{dom}</p><p>coordinador.personal@gmail.com</p><p>protocolo@avellaneda.gob.ar</p><p>WhatsApp 11 4444-2222</p></section></body></html>"""
    ses = SesionPorHost({url: R(text=home), url + "autoridades/": R(text=aut)})
    cli = K.ClienteContactos(pausa=0, session=ses)
    res = K.relevar_municipio(cli, {"municipio_id": mid, "municipio": nombre}, dict(CFG[mid]), "2026-10-21", "S1")
    K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1])
    cer = next(x for x in C.leer_csv(dirs[0] / C.F_CONTACTOS) if x["dependencia"] == "Ceremonial y Protocolo")
    assert cer["email_institucional"] == f"protocolo@{dom}"                       # ni gmail ni el dominio del homónimo
    assert cer["telefono_institucional"] == "4000-0001"                           # ni celular ni WhatsApp
    textos = "".join((dirs[0] / n).read_text(encoding="utf-8-sig") for n in (C.F_CONTACTOS, C.F_FUENTES))
    assert "gmail" not in textos and "5555" not in textos and "4444" not in textos and "avellaneda.gob.ar" not in textos
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == []


def test_evidencia_de_dependencia_sin_canal_tampoco_filtra_datos_omitidos():
    html = "<body><ul><li>Ceremonial y Protocolo: escribir a coord@gmail.com o al celular 11 5555-0000</li><li>Relaciones Institucionales</li></ul></body>"
    a = CP.analizar_pagina(html, "https://www.sitio-prueba.gob.ar/p", {"sitio-prueba.gob.ar"})
    ev = " ".join(h["evidencia"] for h in a["hallazgos"])
    assert "gmail" not in ev and "5555" not in ev
