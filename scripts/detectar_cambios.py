"""Detección de cambios y alertas (spec sec. 11-13).

- Compara solo valores comparables (ambos presentes) entre capturas consecutivas.
- Sin captura previa => línea de base, cero alertas.
- Fórmulas: variacion_absoluta = actual - anterior;
  variacion_relativa_pct = (actual - anterior) / abs(anterior) * 100 (no si anterior es 0/ausente).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

IMPACTO = "Prioridad de seguimiento; no implica determinación de responsabilidad legal."


def cargar_reglas(ruta: Path = C.ARCHIVO_REGLAS) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def variaciones(anterior: float, actual: float) -> tuple[float, float | None]:
    abs_ = actual - anterior
    rel = None if anterior == 0 else abs_ / abs(anterior) * 100
    return abs_, rel


def _alerta(mid, snap_ant, snap_act, fecha, capa, cat, var, v_ant, v_act, sev, desc, fecha_evento="", url="", fuente="", abs_=None, rel=None):
    return {
        "alerta_id": C.id_estable(mid, snap_act, var, cat),
        "municipio_id": mid, "snapshot_anterior": snap_ant, "snapshot_actual": snap_act,
        "fecha_deteccion": fecha, "fecha_evento": fecha_evento, "capa_analitica": capa,
        "categoria_alerta": cat, "variable": var, "valor_anterior": v_ant, "valor_actual": v_act,
        "variacion_absoluta": abs_, "variacion_relativa_pct": rel, "severidad": sev,
        "impacto_institucional": IMPACTO, "descripcion": desc,
        "estado_verificacion": "AUTOMATICA_PENDIENTE_REVISION", "fuente_documental": fuente,
        "url_fuente": url, "estado_seguimiento": "ABIERTA",
    }


def _ultimas_dos(filas: list[dict], mid: str) -> tuple[dict | None, dict | None]:
    f = [r for r in filas if r["municipio_id"] == mid]
    return (f[-2], f[-1]) if len(f) >= 2 else (None, f[-1] if f else None)


def _par_comparable(filas: list[dict], var: str, snap: str | None):
    """(anterior, actual) con los dos últimos valores no vacíos de `var`; el actual debe ser de `snap`."""
    con = [r for r in filas if (r.get(var) or "").strip()]
    if len(con) < 2 or (snap and con[-1]["snapshot_id"] != snap):
        return None
    return con[-2], con[-1]


def alertas_indicadores(indicadores: list[dict], reglas: dict, fecha: str, solo_snapshot: str | None = None) -> list[dict]:
    res = []
    umbral = reglas["umbral_variacion_absoluta"]
    for mid in sorted({r["municipio_id"] for r in indicadores}):
        filas = [r for r in indicadores if r["municipio_id"] == mid]
        def args(par): return (mid, par[0]["snapshot_id"], par[1]["snapshot_id"], fecha)  # noqa: E704
        for var, nombre in reglas["variables_numericas_0_100"].items():
            par = _par_comparable(filas, var, solo_snapshot)
            if not par:
                continue
            a, b = C.parse_num(par[0].get(var)), C.parse_num(par[1].get(var))
            if a is None or b is None or a == b:
                continue
            d, rel = variaciones(a, b)
            if abs(d) >= umbral:
                sev = "ALTA" if abs(d) >= umbral * reglas["umbral_alta_multiplo"] else "MEDIA"
                res.append(_alerta(*args(par), "CAPA_II_DESEMPENO", "VARIACION_INDICE", var, a, b, sev,
                                   f"{nombre}: variación de {d:+.1f} puntos (umbral {umbral}).",
                                   par[1].get("fecha_actualizacion_portal", ""), par[1].get("url_fuente", ""),
                                   "municipiosargentinos.net", d, rel))
        for var in reglas["variables_ranking"]:
            par = _par_comparable(filas, var, solo_snapshot)
            if not par:
                continue
            a, b = C.parse_num(par[0].get(var)), C.parse_num(par[1].get(var))
            if a is None or b is None or a == b:
                continue
            d, rel = variaciones(a, b)
            sev = "MEDIA" if abs(d) >= reglas["umbral_ranking_posiciones"] else "INFORMATIVA"
            res.append(_alerta(*args(par), "CAPA_II_DESEMPENO", "VARIACION_RANKING", var, a, b, sev,
                               f"Ranking {var}: cambio de {d:+.0f} posiciones.",
                               par[1].get("fecha_actualizacion_portal", ""), par[1].get("url_fuente", ""),
                               "municipiosargentinos.net", d, rel))
        for var, sev in reglas["variables_semaforo"].items():
            par = _par_comparable(filas, var, solo_snapshot)
            if par and par[0][var].strip() != par[1][var].strip():  # cualquier cambio de semáforo es alerta
                res.append(_alerta(*args(par), "CAPA_II_DESEMPENO", "CAMBIO_SEMAFORO", var, par[0][var], par[1][var], sev,
                                   f"Semáforo de transparencia: {par[0][var]} -> {par[1][var]}.",
                                   par[1].get("fecha_actualizacion_portal", ""), par[1].get("url_fuente", ""),
                                   "municipiosargentinos.net"))
    return res


def alertas_politicas(antes: list[dict], despues: list[dict], reglas: dict, fecha: str, snap: str) -> list[dict]:
    res = []
    prev = {r["municipio_id"]: r for r in antes}
    for r in despues:
        p = prev.get(r["municipio_id"])
        if not p:
            continue
        for var, cfg in reglas["variables_politicas"].items():
            a, b = (p.get(var) or "").strip(), (r.get(var) or "").strip()
            if not a or not b or a == b:
                continue
            cat, desc = cfg["categoria"], f"{var}: '{a}' -> '{b}'."
            if var == "situacion_legislativa":
                mayoria = lambda x: x.startswith("MAYORIA")  # noqa: E731
                if mayoria(a) and b == "MINORIA":
                    cat, desc = "PERDIDA_MAYORIA_LEGISLATIVA", f"Pérdida de mayoría: {a} -> {b}."
                elif a == "MINORIA" and mayoria(b):
                    cat, desc = "OBTENCION_MAYORIA_LEGISLATIVA", f"Obtención de mayoría: {a} -> {b}."
            res.append(_alerta(r["municipio_id"], p.get("snapshot_id", ""), snap, fecha, "CAPA_I_POLITICA",
                               cat, var, a, b, cfg["severidad"], desc))
    return res


def alerta_metodologia(fuentes_antes: list[dict], fuentes_despues: list[dict], reglas: dict, fecha: str, snap: str) -> list[dict]:
    def hashes(filas):
        return [r for r in filas if r["entidad"] == "metodologia" and r["campo_verificado"] == "metodologia_hash"]
    ant, act = hashes(fuentes_antes), hashes(fuentes_despues)
    if not ant or len(act) <= len(ant) or act[-1]["valor_obtenido"] == ant[-1]["valor_obtenido"]:
        return []
    cfg = reglas["metodologia"]
    return [_alerta("GLOBAL", ant[-1]["snapshot_id"], snap, fecha, "CAPA_III_METODOLOGIA", cfg["categoria"],
                    "metodologia_hash", ant[-1]["valor_obtenido"][:16], act[-1]["valor_obtenido"][:16], cfg["severidad"],
                    "El texto de la metodología publicada cambió; revisar comparabilidad de índices.",
                    url=act[-1]["documento_url"], fuente="municipiosargentinos.net/metodologia")]


def generar_alertas(antes: dict[str, list[dict]], despues: dict[str, list[dict]], fecha: str, snap: str) -> list[dict]:
    reglas = cargar_reglas()
    return (alertas_indicadores(despues[C.F_INDICADORES], reglas, fecha, solo_snapshot=snap)
            + alertas_politicas(antes[C.F_MUNICIPIOS], despues[C.F_MUNICIPIOS], reglas, fecha, snap)
            + alerta_metodologia(antes[C.F_FUENTES], despues[C.F_FUENTES], reglas, fecha, snap))


def fusionar_alertas(existentes: list[dict], nuevas: list[dict]) -> list[dict]:
    ids = {r["alerta_id"] for r in existentes}
    res = [dict(r) for r in existentes]
    res += [{k: C.formatear(v) for k, v in n.items()} for n in nuevas if n["alerta_id"] not in ids]
    return res


if __name__ == "__main__":
    print("Las alertas se generan durante extraer.py (normalizar.aplicar). Ver docs/metodologia.md.")
