"""Fusión incremental y escritura de los 8 CSV (spec sec. 18 y 21).

Reglas:
- Nunca se sobrescribe un valor válido con uno vacío (fallas temporales).
- 01: upsert por municipio_id. 04: se agrega una captura solo si cambia algún dato.
- 05: se agregan fuentes nuevas (id determinístico). 06: incidencias con id estable.
- Antes de modificar un archivo, la versión previa se copia a data/historico/AAAA-MM-DD/.
- Sin cambios reales en los datos => no se reescribe ningún archivo (evita commits vacíos).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

# Columnas que cambian en cada ejecución aunque los datos no cambien.
VOLATILES = {"snapshot_id", "fecha_extraccion", "fecha_verificacion", "fecha_consulta",
             "fecha_ultima_revision", "fecha_deteccion"}


def _vacio(v) -> bool:
    return v is None or str(v).strip() == ""


def _s(v) -> str:
    return C.formatear(v)


def fusionar_municipios(existentes: list[dict], nuevas: list[dict]) -> list[dict]:
    por_id = {r["municipio_id"]: dict(r) for r in existentes}
    for n in nuevas:
        actual = por_id.setdefault(n["municipio_id"], {})
        cambio = False
        for k, v in n.items():
            if k in VOLATILES or _vacio(v):
                continue
            if _s(actual.get(k)) != _s(v):
                actual[k] = _s(v)
                cambio = True
        if cambio or not actual.get("snapshot_id"):
            actual["fecha_verificacion"] = n.get("fecha_verificacion", "")
            actual["snapshot_id"] = n.get("snapshot_id", "")
        actual["municipio_id"] = n["municipio_id"]
    return sorted(por_id.values(), key=lambda r: r["municipio_id"])


def fusionar_indicadores(existentes: list[dict], nuevas: list[dict]) -> list[dict]:
    res = [dict(r) for r in existentes]
    for n in nuevas:
        datos = {k: _s(v) for k, v in n.items() if k not in VOLATILES and k != "url_fuente" and not _vacio(v)}
        datos.pop("municipio_id", None)
        if not datos:
            continue  # captura vacía (falla temporal): no se agrega
        base: dict[str, str] = {}  # último valor no vacío conocido por campo (las ausencias no cuentan como cambio)
        for r in res:
            if r["municipio_id"] == n["municipio_id"]:
                base.update({k: v for k, v in r.items() if k not in VOLATILES and k != "url_fuente" and not _vacio(v)})
        base.pop("municipio_id", None)
        if base and all(base.get(k) == v for k, v in datos.items()):
            continue  # nada nuevo respecto de lo ya conocido
        res.append({k: _s(v) for k, v in n.items()})
    return res


def fusionar_fuentes(existentes: list[dict], nuevas: list[dict]) -> list[dict]:
    ids = {r["fuente_id"] for r in existentes}
    res = [dict(r) for r in existentes]
    for n in nuevas:
        if n["fuente_id"] not in ids:
            ids.add(n["fuente_id"])
            res.append({k: _s(v) for k, v in n.items()})
    return res


def fusionar_incidencias(existentes: list[dict], nuevas: list[dict], ids_procesados: set[str], fecha: str) -> list[dict]:
    res = [dict(r) for r in existentes]
    ids_nuevos = {n["incidencia_id"] for n in nuevas}
    por_id = {r["incidencia_id"]: r for r in res}
    for r in res:  # lo que ya no ocurre en municipios reprocesados se marca resuelto
        if (r["municipio_id"] in ids_procesados and r["estado_resolucion"] == "ABIERTA"
                and r["incidencia_id"] not in ids_nuevos):
            r["estado_resolucion"] = "RESUELTA"
            r["fecha_ultima_revision"] = fecha
    for n in nuevas:
        if n["incidencia_id"] in por_id:
            if por_id[n["incidencia_id"]]["estado_resolucion"] == "RESUELTA":
                por_id[n["incidencia_id"]].update({"estado_resolucion": "ABIERTA", "fecha_ultima_revision": fecha})
            continue
        res.append({k: _s(v) for k, v in n.items()})
    return res


def _contenido_significativo(filas: list[dict]) -> list[tuple]:
    return [tuple(sorted((k, v) for k, v in r.items() if k not in VOLATILES)) for r in filas]


def escribir_con_historial(nombre: str, filas: list[dict], dir_actual: Path, dir_hist: Path, fecha: str) -> bool:
    """Escribe solo si hay cambios reales. Devuelve True si escribió."""
    ruta = dir_actual / nombre
    previas = C.leer_csv(ruta)
    if _contenido_significativo(previas) == _contenido_significativo([{k: _s(v) for k, v in r.items()} for r in filas]) \
            and ruta.exists():
        return False
    if previas:
        destino = dir_hist / fecha / nombre
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta, destino)
    C.escribir_csv(ruta, filas, C.ESQUEMAS[nombre])
    return True


def aplicar(resultados: list[dict], fuentes_extra: list[dict], incid_extra: list[dict], fecha: str, snap: str,
            ids_procesados: list[str], dir_actual: Path, dir_historico: Path) -> dict:
    import detectar_cambios as D
    dir_actual.mkdir(parents=True, exist_ok=True)
    antes = {n: C.leer_csv(dir_actual / n) for n in C.ESQUEMAS}

    nuevos_01 = [r["municipio"] for r in resultados]
    nuevos_04 = [r["indicadores"] for r in resultados if r["indicadores"]]
    nuevas_05 = [f for r in resultados for f in r["fuentes"]] + fuentes_extra
    nuevas_06 = [i for r in resultados for i in r["incidencias"]] + incid_extra

    despues = {
        C.F_MUNICIPIOS: fusionar_municipios(antes[C.F_MUNICIPIOS], nuevos_01),
        C.F_INDICADORES: fusionar_indicadores(antes[C.F_INDICADORES], nuevos_04),
        C.F_FUENTES: fusionar_fuentes(antes[C.F_FUENTES], nuevas_05),
        C.F_INCIDENCIAS: fusionar_incidencias(antes[C.F_INCIDENCIAS], nuevas_06, set(ids_procesados) | {"GLOBAL"}, fecha),
    }
    # Alertas: solo con registros comparables; la primera ejecución es línea de base.
    alertas = D.generar_alertas(antes, despues, fecha, snap)
    despues[C.F_ALERTAS] = D.fusionar_alertas(antes[C.F_ALERTAS], alertas)
    for n in (C.F_BLOQUES, C.F_CONTACTOS, C.F_CABA):  # Fase 1: solo esquema, sin datos inventados
        despues[n] = antes[n]

    escritos = [n for n in C.ESQUEMAS if escribir_con_historial(n, despues[n], dir_actual, dir_historico, fecha)]
    return {
        "archivos_escritos": escritos,
        "linea_base": not antes[C.F_INDICADORES],
        "alertas_nuevas": len(alertas),
        "incidencias_nuevas": len(nuevas_06),
        "fuentes_nuevas": len(despues[C.F_FUENTES]) - len(antes[C.F_FUENTES]),
    }
