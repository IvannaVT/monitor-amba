"""Pruebas con fichas REALES capturadas por GitHub Actions (tests/fixtures/real/*_estructura.txt).

Cada archivo es el volcado de fragmentos de texto (sección, texto) que produce el tokenizador a partir
del HTML real del portal; aquí se reconstruye ese flujo y se analiza. Los valores esperados viven SOLO
en este archivo de pruebas (nunca en el código de producción).
"""
import re
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import extraer as E  # noqa: E402
import parser_ficha as P  # noqa: E402
import validar as V  # noqa: E402
from test_pipeline import BASE, FakeSession, R, dirs, paginas  # noqa: E402,F401

REAL = AQUI / "fixtures" / "real"
MUNIS = ["avellaneda", "vicente_lopez", "tres_de_febrero"]


def tokens(k: str) -> list[tuple[str, bool]]:
    out = []
    for ln in (REAL / f"ba_{k}_estructura.txt").read_text(encoding="utf-8").splitlines():
        if ln.startswith("# Reconocidos"):
            break
        if m := re.match(r"^\s*(\d+) (H |  )\[([^\]]*)\] ?(.*)$", ln):
            out.append((m.group(4), m.group(2) == "H "))
    return out


def valores(k):
    return {c: d["valor"] for c, d in P.analizar_tokens(tokens(k))["hallados"].items()}


ESPERADO = {
    "avellaneda": dict(
        transparencia_puntaje=50.0, servicios_seguridad_puntaje=60.9, seguridad_puntaje=47.1, control_puntaje=65.8,
        cobertura_cloacas_pct=80.3, homicidios_tasa_100k=4.4, homicidios_periodo="2023-2025",
        victimas_homicidio_ultimo_anio=17, victimas_homicidio_anio=2025, señales_control=5,
        ultimo_fallo_htc="aprobada con observaciones", ejercicio_fallo_htc="2024", transparencia_semaforo="AMARILLO",
        intendente_nombre_completo="Magdalena Sierra", fecha_asuncion="2026-07-03", partido_politico="PJ",
        frente_electoral="Fuerza Patria", poblacion_2022=367554, ranking_provincial=44, ranking_pares=4,
        seccion_electoral="3", fecha_actualizacion_portal="2026-10-15", transparencia_relevamiento_propio=50.0),
    "vicente_lopez": dict(
        transparencia_puntaje=75.0, servicios_seguridad_puntaje=90.8, seguridad_puntaje=93.7, control_puntaje=72.6,
        cobertura_cloacas_pct=98.0, homicidios_tasa_100k=1.1, victimas_homicidio_ultimo_anio=3, señales_control=3,
        intendente_nombre_completo="Soledad Martínez", fecha_asuncion="2023-12-10", partido_politico="PRO",
        poblacion_2022=282280, empleados_municipales=4125, tipo_dato_empleo="EMPLEADOS_OCUPADOS",
        empleo_periodo="2026-08", transparencia_semaforo="AMARILLO", ranking_provincial=3),
    "tres_de_febrero": dict(
        transparencia_puntaje=60.0, servicios_seguridad_puntaje=65.1, seguridad_puntaje=47.4, control_puntaje=76.8,
        cobertura_cloacas_pct=93.6, homicidios_tasa_100k=5.0, victimas_homicidio_ultimo_anio=17, señales_control=3,
        intendente_nombre_completo="Rodrigo Aybar", intendente_condicion="INTERINO", fecha_asuncion="2025-12-09",
        partido_politico="La Libertad Avanza", poblacion_2022=364176, cargos_presupuestados=3720,
        tipo_dato_empleo="CARGOS_PRESUPUESTADOS", empleo_periodo="2023", ranking_provincial=19),
}
INDICE_PUBLICADO = {"avellaneda": 56.2, "vicente_lopez": 80.2, "tres_de_febrero": 64.3}  # capturado el 2026-10-15


@pytest.mark.parametrize("k", MUNIS)
def test_valores_de_la_ficha_real(k):
    v = valores(k)
    for campo, esperado in ESPERADO[k].items():
        assert v.get(campo) == esperado, (k, campo, v.get(campo))
    assert v["indice_global"] == INDICE_PUBLICADO[k]


@pytest.mark.parametrize("k", MUNIS)
def test_sin_contradicciones_y_con_etiqueta_original_y_seccion(k):
    a = P.analizar_tokens(tokens(k))
    assert a["contradicciones"] == []
    for campo, d in a["hallados"].items():
        assert d["etiqueta"] and d["original"] and d["seccion"], campo


def test_los_tres_pilares_no_se_confunden_con_indice_ni_relevamiento():
    v = valores("avellaneda")
    assert v["indice_global"] == 56.2 and v["transparencia_puntaje"] == 50.0      # coinciden numéricamente...
    assert v["transparencia_relevamiento_propio"] == 50.0                          # ...pero son campos distintos
    d = P.analizar_tokens(tokens("avellaneda"))["hallados"]
    assert d["transparencia_puntaje"]["seccion"] == "Cómo se compone su índice" and "peso informado: 50" in d["transparencia_puntaje"]["obs"]
    assert d["transparencia_relevamiento_propio"]["seccion"] == "Datos clave"
    assert d["seguridad_puntaje"]["etiqueta"].startswith("Seguridad, puntaje")
    assert len({v[c] for c in ("servicios_seguridad_puntaje", "seguridad_puntaje", "control_puntaje")}) == 3
    assert 35 not in v.values() and 15 not in v.values()                           # los pesos no son puntajes


def test_semaforo_no_se_infiere_del_color_del_indice():
    for k in ("avellaneda", "tres_de_febrero"):
        assert any(t == f"Índice {'amarillo'}" for t, _ in tokens(k))
    assert any(t == "Índice verde" for t, _ in tokens("vicente_lopez"))
    assert valores("vicente_lopez")["transparencia_semaforo"] == "AMARILLO"        # lo dice el texto, no el color del índice
    assert "transparencia_semaforo" not in valores("tres_de_febrero")             # la ficha no lo publica: queda vacío


def test_empleados_ocupados_no_se_mezclan_con_cargos_presupuestados():
    vl, tf, av = valores("vicente_lopez"), valores("tres_de_febrero"), valores("avellaneda")
    assert vl["empleados_municipales"] == 4125 and "cargos_presupuestados" not in vl
    assert "empleados_municipales" not in tf and tf["cargos_presupuestados"] == 3720
    assert "empleados_municipales" not in av and "tipo_dato_empleo" not in av      # "No declara cuántos empleados tiene"


def test_no_se_inventan_campos_ni_se_mezclan_otros_municipios():
    permitidos = (set(C.ESQUEMAS[C.F_INDICADORES]) | set(P.CAMPOS_FICHA_01) | {"cargos_presupuestados"})
    for k in MUNIS:
        a = P.analizar_tokens(tokens(k))
        assert set(a["hallados"]) <= permitidos, set(a["hallados"]) - permitidos
        assert not {"coalicion_actual", "presidente_hcd", "total_bancas", "email_municipal"} & set(a["hallados"])
        assert "puesto 43" not in " ".join(d["original"] for d in a["hallados"].values())  # sección "Partidos para comparar"
    assert "frente_electoral" not in valores("vicente_lopez") and "frente_electoral" not in valores("tres_de_febrero")
    assert "intendente_condicion" not in valores("avellaneda")                     # "Intendenta" sin "interino": no se declara condición


def test_cantidad_de_campos_por_ficha():
    cuenta = {k: len([c for c in valores(k) if c != "fecha_actualizacion_portal"]) for k in MUNIS}
    assert cuenta == {"avellaneda": 27, "vicente_lopez": 28, "tres_de_febrero": 28}


def test_los_valores_de_referencia_no_estan_en_produccion():
    for ruta in [*(AQUI.parent / "scripts").glob("*.py"), *(AQUI.parent / "config").glob("*")]:
        txt = ruta.read_text(encoding="utf-8-sig")
        for prohibido in ("Magdalena Sierra", "Soledad Martínez", "Rodrigo Aybar", "367554", "282280", "364176",
                          "367.554", "282.280", "364.176", "Fuerza Patria", "60,9", "90,8", "65,1"):
            assert prohibido not in txt, (ruta, prohibido)


def test_pipeline_con_fichas_reales_escribe_01_04_05_y_valida(dirs, monkeypatch):
    mapa = {f"MARCA-{k}": tokens(k) for k in MUNIS}
    monkeypatch.setattr(E, "analizar_ficha", lambda html: P.analizar_tokens(mapa[re.search(r"MARCA-\w+", html).group(0)]))
    pag = paginas()
    for k, slug in zip(MUNIS, ["avellaneda", "vicente-lopez", "tres-de-febrero"]):
        pag[f"{BASE}/m/{slug}/"] = R(text=f"<html>MARCA-{k}</html>")
    ses = FakeSession(pag)
    res = E.ejecutar(",".join(MUNIS), "2026-10-21", cliente=E.Cliente(pausa=0, session=ses),
                     dir_actual=dirs[0], dir_historico=dirs[1])
    assert {n: m["campos_extraidos"] for n, m in res["municipios"].items()} == \
        {"Avellaneda": 27, "Vicente López": 28, "Tres de Febrero": 28}
    m01 = {r["municipio_id"]: r for r in C.leer_csv(dirs[0] / C.F_MUNICIPIOS)}
    i04 = {r["municipio_id"]: r for r in C.leer_csv(dirs[0] / C.F_INDICADORES)}
    f05 = C.leer_csv(dirs[0] / C.F_FUENTES)
    assert m01["ba_avellaneda"]["intendente_nombre_completo"] == "Magdalena Sierra" and m01["ba_avellaneda"]["poblacion_2022"] == "367554"
    assert m01["ba_tres_de_febrero"]["intendente_condicion"] == "INTERINO" and m01["ba_vicente_lopez"]["frente_electoral"] == ""
    assert m01["ba_avellaneda"]["indice_global"] == "56,2" and m01["ba_avellaneda"]["seccion_electoral"] == "3"
    assert i04["ba_tres_de_febrero"]["empleados_municipales"] == "" and i04["ba_tres_de_febrero"]["tipo_dato_empleo"] == "CARGOS_PRESUPUESTADOS"
    assert i04["ba_vicente_lopez"]["empleados_municipales"] == "4125" and i04["ba_vicente_lopez"]["empleo_periodo"] == "2026-08"
    assert i04["ba_avellaneda"]["homicidios_tasa_100k"] == "4,4" and i04["ba_avellaneda"]["cobertura_cloacas_pct"] == "80,3"
    carg = [f for f in f05 if f["campo_verificado"] == "cargos_presupuestados"]
    assert len(carg) == 1 and carg[0]["municipio_id"] == "ba_tres_de_febrero" and carg[0]["valor_obtenido"].startswith("3.720")
    for f in f05:
        if f["entidad"] in ("indicador_portal", "municipio_portal"):
            assert f["documento_url"].startswith(BASE + "/m/") and "etiqueta='" in f["observaciones"] and "seccion='" in f["observaciones"]
    assert all("pendiente de verificación" in f["observaciones"] for f in f05
               if f["campo_verificado"] in ("intendente_nombre_completo", "partido_politico", "frente_electoral", "fecha_asuncion"))
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]
    for n in (C.F_BLOQUES, C.F_CONTACTOS, C.F_CABA):   # sin Concejo, contactos ni CABA inventados
        assert C.leer_csv(dirs[0] / n) == []
