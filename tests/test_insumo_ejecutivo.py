"""Insumo preliminar del Ejecutivo: separado de data/actual, con evidencias depuradas, casillas clasificadas y discrepancias.

Los CSV de data/insumos provienen de la base entregada por el usuario (no son capturas propias); estos tests no usan la red.
"""
import csv
import subprocess
import sys
import time
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import importar_insumo as I  # noqa: E402
import verificar_pares_dominio as P  # noqa: E402
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

DIR = AQUI.parent / "data" / "insumos" / "ejecutivo_preliminar"
leer = lambda n: C.leer_csv(DIR / n)  # noqa: E731


def test_insumo_esta_separado_de_data_actual():
    assert DIR.is_dir() and "actual" not in DIR.parts
    assert not any(p.name.startswith(("municipios", "contactos")) and "insumos" in str(p) for p in C.DIR_ACTUAL.glob("*"))
    assert len(leer("municipios.csv")) == 41 and len(leer("contactos.csv")) == 50 and len(leer("fuentes.csv")) == 82


def test_conserva_fuentes_y_estados_originales():
    k = leer("contactos.csv")
    assert all(r["fuente_url"] for r in k)
    assert {r["estado_contacto"] for r in k} >= {"PUBLICADO EN FUENTE OFICIAL; RESPUESTA NO PROBADA", "DOCUMENTO HISTÓRICO; VIGENCIA PENDIENTE"}
    assert not any("VIGENTE" == r["estado_contacto"] for r in k)       # nada pasa a vigente: no se comprobó respuesta
    assert all(r["evidencia_original"] for r in k)


def test_casillas_distinguen_proveedor_de_uso_oficial():
    assert I.tipo_casilla("a@gmail.com", "https://www.muni-prueba.gob.ar/")[0] == "PROVEEDOR_PUBLICO"
    assert I.tipo_casilla("a@muni-prueba.gob.ar", "https://www.muni-prueba.gob.ar/")[0] == "DOMINIO_MUNICIPAL"
    assert I.tipo_casilla("a@muni-prueba.gov.ar", "https://www.muni-prueba.gob.ar/")[0] == "DOMINIO_GOB_DISTINTO"
    k = {r["email_institucional"]: r for r in leer("contactos.csv") if r["email_institucional"]}
    for gm in ("privadaituzaingo@gmail.com", "cypituzaingo@gmail.com", "ceremonialsfm@gmail.com", "prensamunicipalidadensenada@gmail.com"):
        assert k[gm]["tipo_casilla"] == "PROVEEDOR_PUBLICO" and "CONFIRMAR" in k[gm]["uso_oficial"]
    assert k["ventanillaunica@miituzaingo.gob.ar"]["tipo_casilla"] == "DOMINIO_GOB_DISTINTO"     # .gob.ar vs sitio .gov.ar


def test_evidencia_depurada_y_sin_respaldo_marcada():
    ev, est = I.depurar_evidencia("ipal INTENDENTE Mario Secco 0221 460 1771 intendente@ensenada.gov.ar 23/04/2019 Autoridades otras cosas " * 3,
                                  "intendente@ensenada.gov.ar", "")
    assert est == "DEPURADA" and "intendente@ensenada.gov.ar" in ev and not ev.startswith("ipal")
    ev, est = I.depurar_evidencia("Contactanos", "infovecinos@escobar.gob.ar", "")
    assert est == "EL_EMAIL_NO_FIGURA_EN_LA_EVIDENCIA"
    k = {r["municipio"]: r for r in leer("contactos.csv") if r["estado_evidencia"] == "EL_EMAIL_NO_FIGURA_EN_LA_EVIDENCIA"}
    assert set(k) == {"Escobar", "Esteban Echeverría"}
    dis = {(d["municipio"], d["tema"]) for d in leer("discrepancias.csv")}
    assert ("Escobar", "EVIDENCIA_NO_RESPALDA_EL_DATO") in dis and ("Esteban Echeverría", "EVIDENCIA_NO_RESPALDA_EL_DATO") in dis


def test_evidencia_depurada_no_conserva_numeros_de_emergencia():
    ev, _ = I.depurar_evidencia("LUJáN 109 EMERGENCIAS 911 POLICÍA 144 Mail: contacto@lujan.gob.ar", "contacto@lujan.gob.ar", "")
    assert "911" not in ev and "144" not in ev and "contacto@lujan.gob.ar" in ev
    ev, _ = I.depurar_evidencia("SAME 107 Atención general 147 y 0800-333-1055", "", "147")
    assert "107" not in ev and "147" in ev
    assert not any(n in r["evidencia"].split() for r in leer("contactos.csv") for n in ("911", "144", "107"))


def test_seis_pares_de_dominio_detectados():
    pares = {d["municipio"]: (d["valor_repo"], d["valor_insumo"]) for d in leer("discrepancias.csv") if d["tema"] == "DOMINIO_DISCREPANTE"}
    assert set(pares) == {"Berisso", "Cañuelas", "Exaltación de la Cruz", "General Rodríguez", "La Matanza", "Marcos Paz"}
    assert all(d["proceso"] == "ACTIONS" for d in leer("discrepancias.csv") if d["tema"] == "DOMINIO_DISCREPANTE")


def test_autoridades_no_se_sobrescriben_y_quedan_para_contraste_municipal():
    dis = leer("discrepancias.csv")
    manuales = [d for d in dis if d["tema"].startswith(("AUTORIDAD", "MUNICIPAL_VS", "PARTIDO", "ALIANZA"))]
    assert manuales and all(d["proceso"] == "MANUAL" for d in manuales)
    av = [d for d in dis if d["municipio"] == "Avellaneda" and d["tema"] == "MUNICIPAL_VS_DIRECTORIO_PROVINCIAL"]
    assert av and "no sobrescribir" in av[0]["accion"].lower()


def test_importador_no_escribe_en_data_actual(tmp_path):
    antes = {p: p.stat().st_mtime_ns for p in C.DIR_ACTUAL.glob("*.csv")}
    pytest.importorskip("openpyxl")
    assert I.main([str(I.XLSX), "--salida", str(tmp_path)]) == 0
    assert {p: p.stat().st_mtime_ns for p in C.DIR_ACTUAL.glob("*.csv")} == antes
    assert (tmp_path / "discrepancias.csv").read_bytes() == (DIR / "discrepancias.csv").read_bytes()   # reproducible


def test_preset_discrepancias_solo_procesa_los_automatizables():
    sel = {c["municipio"] for c in K.seleccionar(C.cargar_municipios_cfg(), "discrepancias")}
    assert {"Cañuelas", "Escobar", "Ituzaingó", "San Fernando"} <= sel and len(sel) < 20


def test_verificacion_de_pares_informa_cada_lado_sin_tocar_la_config():
    antes = (C.ARCHIVO_SITIOS).read_bytes()
    pag = {"https://www.canuelas.gob.ar/": R(text="<html><head><title>Municipalidad de Cañuelas</title></head><body><h1>Municipalidad de Cañuelas</h1><p>Provincia de Buenos Aires</p></body></html>")}
    cli = K.ClienteContactos(pausa=0, session=SesionPorHost(pag, errores={"canuelas.gov.ar": __import__("requests").exceptions.ConnectTimeout("t")}))
    fila = {"municipio": "Cañuelas", "municipio_id": "ba_canuelas", "valor_repo": "https://www.canuelas.gob.ar/", "valor_insumo": "https://canuelas.gov.ar/"}
    out = P.verificar(cli, [fila], {"ba_canuelas": "Cañuelas"}, log=lambda *a, **k: None)
    assert out[0]["resultado"] == "SOLO_CONFIG" and out[0]["ok_config"] and not out[0]["ok_insumo"] and "TIMEOUT" in out[0]["detalle_insumo"]
    assert "SOLO_CONFIG" in P.informe(out)
    assert C.ARCHIVO_SITIOS.read_bytes() == antes
