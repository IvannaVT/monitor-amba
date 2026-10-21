"""Partido vs. frente electoral y separación documentada de nombres.

Los fragmentos de las primeras pruebas son REPRODUCCIONES SINTÉTICAS del fallo informado (partidos cuyo nombre empieza con
"Frente", como Frente Grande o Frente Renovador); no son capturas reales de esas fichas.
"""
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import parser_ficha as P  # noqa: E402
import validar as V  # noqa: E402
from test_pipeline import dirs, correr, paginas, BASE, R, leer  # noqa: E402,F401


def intendente(par: str, etiqueta="Intendente:"):
    toks = [("Intendente", True), (etiqueta, False), ("Persona Ficticia", False),
            (f", en funciones desde el 2023-12-10 ({par}).", False)]
    h = P.analizar_tokens(toks)["hallados"]
    return {c: d["valor"] for c, d in h.items()}, h


@pytest.mark.parametrize("par,partido,frente", [
    ("Frente Renovador", "Frente Renovador", None),
    ("Frente Grande", "Frente Grande", None),
    ("Frente Renovador · frente Unión por la Patria", "Frente Renovador", "Unión por la Patria"),
    ("Frente Grande · frente Fuerza Patria", "Frente Grande", "Fuerza Patria"),
    ("PJ · frente Fuerza Patria", "PJ", "Fuerza Patria"),            # formato ya validado con la ficha real
    ("PRO", "PRO", None),
    ("La Libertad Avanza", "La Libertad Avanza", None),
    ("frente Unión por la Patria", None, "Unión por la Patria"),     # solo conector: no se inventa partido
])
def test_partido_y_frente_no_se_confunden(par, partido, frente):
    v, _ = intendente(par)
    assert v.get("partido_politico") == partido and v.get("frente_electoral") == frente, v
    assert v["fecha_asuncion"] == "2023-12-10" and "coalicion_actual" not in v


def test_elemento_adicional_con_mayuscula_no_se_clasifica_como_alianza():
    v, h = intendente("PJ · Frente Grande")
    assert v["partido_politico"] == "PJ" and "frente_electoral" not in v
    assert "elementos sin clasificar: Frente Grande" in h["partido_politico"]["obs"]


def test_conector_coalicion_en_minuscula():
    v, _ = intendente("PRO · coalición Juntos por el Cambio")
    assert v["partido_politico"] == "PRO" and v["coalicion_actual"] == "Juntos por el Cambio" and "frente_electoral" not in v


def test_fichas_reales_siguen_igual():
    from test_fichas_reales import valores
    a, v, t = valores("avellaneda"), valores("vicente_lopez"), valores("tres_de_febrero")
    assert (a["partido_politico"], a["frente_electoral"]) == ("PJ", "Fuerza Patria")
    assert v["partido_politico"] == "PRO" and "frente_electoral" not in v
    assert t["partido_politico"] == "La Libertad Avanza" and "frente_electoral" not in t


def test_ficha_sin_partido_ni_frente_no_inventa_datos(dirs):
    html = leer("ficha_ref_a.html").replace("<dt>Partido</dt><dd>Partido de Prueba</dd><dt>Frente electoral</dt><dd>Frente de Prueba</dd>", "")
    assert html != leer("ficha_ref_a.html")
    # ficha sintética sin esos datos: no aparecen inventados
    pag = paginas(); pag[BASE + "/m/avellaneda/"] = R(text=html)
    correr(dirs, pag, municipios="avellaneda")
    m = C.leer_csv(dirs[0] / C.F_MUNICIPIOS)[0]
    assert m["partido_politico"] == "" and m["frente_electoral"] == ""


# ---------------------------------------------------------------- nombres documentados
def test_override_sin_fuente_no_se_aplica(tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("﻿nombre_completo;nombre;apellido;fuente_revision\n"
                 "Juan Carlos Pérez;Juan Carlos;Pérez;https://ejemplo.org/doc\n"
                 "Ana Maria Lopez;Ana Maria;Lopez;\n", encoding="utf-8")
    o = C.cargar_nombres_override(p)
    assert o == {"Juan Carlos Pérez": ("Juan Carlos", "Pérez")}
    assert C.separar_nombre("Ana Maria Lopez", o) == ("", "", "no_separado")          # sin fuente: ambiguo, queda vacío
    assert C.separar_nombre("Juan Carlos Pérez", o) == ("Juan Carlos", "Pérez", "override_config")


def test_validador_exige_fuente_y_coherencia_en_los_overrides(dirs, tmp_path, monkeypatch):
    correr(dirs, paginas(), municipios="avellaneda")
    p = tmp_path / "n.csv"
    monkeypatch.setattr(C, "ARCHIVO_NOMBRES", p)
    p.write_text("﻿nombre_completo;nombre;apellido;fuente_revision\nJuan Carlos Pérez;Juan Carlos;Pérez;https://ejemplo.org/doc\n", encoding="utf-8")
    assert V.validar(dirs[0], "prueba")[0] == []
    p.write_text("﻿nombre_completo;nombre;apellido;fuente_revision\nJuan Carlos Pérez;Juan;Pérez;\n", encoding="utf-8")
    e = "\n".join(V.validar(dirs[0], "prueba")[0])
    assert "falta fuente_revision" in e and "no reconstruyen" in e


def test_config_real_de_nombres_es_valida():
    for r in C.leer_csv(C.ARCHIVO_NOMBRES):
        assert r["fuente_revision"].strip() and f"{r['nombre']} {r['apellido']}".split() == r["nombre_completo"].split()
