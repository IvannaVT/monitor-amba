#!/usr/bin/env python3
"""Validación automática de los 8 CSV + informe de cobertura (spec sec. 21 y 23.E).

Uso: python scripts/validar.py [--modo prueba|completo] [--dir data/actual] [--informe docs/informe_calidad.md]
Código de salida 1 si hay errores. En modo 'prueba' se admiten menos de 40 municipios.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CAMPOS_FECHA = {"fecha_verificacion", "fecha_extraccion", "fecha_consulta", "fecha_deteccion",
                "fecha_ultima_revision", "fecha_asuncion", "fecha_actualizacion_portal", "fecha_documento",
                "fecha_composicion", "fecha_evento"}
CAMPOS_0_100 = ["indice_global", "transparencia_puntaje", "servicios_seguridad_puntaje", "seguridad_puntaje",
                "control_puntaje", "transparencia_relevamiento_propio", "transparencia_asap",
                "cobertura_agua_pct", "cobertura_cloacas_pct", "cobertura_gas_pct"]
CAMPOS_BANCAS = ["bancas_oficialismo", "bancas_aliadas", "bancas_oposicion", "bancas_independientes", "bancas_sin_verificar"]
INICIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def validar(dir_actual: Path, modo: str = "prueba") -> tuple[list[str], list[str], dict[str, list[dict]]]:
    err, adv = [], []
    datos: dict[str, list[dict]] = {}
    ids_cfg = {m["municipio_id"] for m in C.cargar_municipios_cfg()}
    if len(ids_cfg) != 40:
        err.append(f"config/municipios_amba.csv tiene {len(ids_cfg)} municipios únicos (se esperan 40)")

    for nombre, cols in C.ESQUEMAS.items():
        ruta = dir_actual / nombre
        if not ruta.exists():
            err.append(f"{nombre}: archivo inexistente")
            datos[nombre] = []
            continue
        crudo = ruta.read_bytes()
        if not crudo.startswith(b"\xef\xbb\xbf"):
            err.append(f"{nombre}: falta BOM UTF-8")
        encabezado = crudo.decode("utf-8-sig").split("\n", 1)[0].rstrip("\r")
        if encabezado.split(";") != cols:
            err.append(f"{nombre}: encabezado distinto al esquema de la especificación")
        filas = C.leer_csv(ruta)
        datos[nombre] = filas

        claves = C.CLAVES[nombre]
        dup = [k for k, n in Counter(tuple(f.get(c, "") for c in claves) for f in filas).items() if n > 1]
        if dup:
            err.append(f"{nombre}: {len(dup)} clave(s) duplicada(s) {claves}, p. ej. {dup[0]}")
        for i, f in enumerate(filas, 2):
            for k, v in f.items():
                if v and v[0] in INICIO_FORMULA and not re.fullmatch(r"[+-]?\d+(,\d+)?", v):
                    err.append(f"{nombre}:{i} {k}: posible inyección de fórmula '{v[:20]}'")
                if k in CAMPOS_FECHA and v and not RE_FECHA.match(v):
                    err.append(f"{nombre}:{i} {k}: fecha inválida '{v}'")
                if v and "." in v and re.fullmatch(r"\d+\.\d+", v) and k not in ("documento_url",):
                    err.append(f"{nombre}:{i} {k}: decimal con punto '{v}' (debe usar coma)")
            mid = f.get("municipio_id")
            if mid and mid not in ids_cfg and mid != "GLOBAL":
                err.append(f"{nombre}:{i} municipio_id desconocido '{mid}'")

    # --- reglas por archivo
    m = datos.get(C.F_MUNICIPIOS, [])
    if modo == "completo" and len(m) != 40:
        err.append(f"{C.F_MUNICIPIOS}: {len(m)} municipios; modo completo exige exactamente 40")
    elif modo == "prueba" and len(m) > 40:
        err.append(f"{C.F_MUNICIPIOS}: más de 40 municipios")
    for f in m:
        for c in CAMPOS_BANCAS + ["total_bancas"]:
            if f.get(c) and C.parse_num(f[c]) is None:
                err.append(f"{C.F_MUNICIPIOS} {f['municipio_id']}: {c} no numérico")
        if f.get("total_bancas") and all(f.get(c, "") != "" for c in CAMPOS_BANCAS):
            suma = sum(C.parse_num(f[c]) or 0 for c in CAMPOS_BANCAS)
            if suma != C.parse_num(f["total_bancas"]):
                err.append(f"{C.F_MUNICIPIOS} {f['municipio_id']}: bancas suman {suma:g} != total {f['total_bancas']}")
        if f.get("situacion_legislativa") and f["situacion_legislativa"] not in C.SITUACIONES_LEGISLATIVAS:
            err.append(f"{C.F_MUNICIPIOS} {f['municipio_id']}: situacion_legislativa inválida")
    for nombre in (C.F_MUNICIPIOS, C.F_INDICADORES):
        for f in datos.get(nombre, []):
            for c in CAMPOS_0_100:
                v = C.parse_num(f.get(c))
                if f.get(c) and v is None:
                    err.append(f"{nombre} {f['municipio_id']}: {c} no numérico '{f[c]}'")
                elif v is not None and not 0 <= v <= 100:
                    err.append(f"{nombre} {f['municipio_id']}: {c}={v:g} fuera de 0-100")
            s = f.get("transparencia_semaforo")
            if s and s not in C.SEMAFOROS:
                err.append(f"{nombre} {f['municipio_id']}: semáforo inválido '{s}'")
    ind_por_id = {}
    for f in datos.get(C.F_INDICADORES, []):
        ind_por_id[f["municipio_id"]] = f
    for f in m:  # concordancia 01 vs 04 (misma fuente original)
        i = ind_por_id.get(f["municipio_id"])
        for c in ("indice_global", "transparencia_puntaje", "control_puntaje"):
            if i and f.get(c) and i.get(c) and f[c] != i[c]:
                adv.append(f"{f['municipio_id']}: {c} difiere entre 01 ({f[c]}) y la última captura 04 ({i[c]})")

    for f in datos.get(C.F_FUENTES, []):
        if f["nivel_confianza"] not in C.NIVELES_CONFIANZA:
            err.append(f"{C.F_FUENTES} {f['fuente_id']}: nivel_confianza inválido")
        if not f["documento_url"].startswith(("http://", "https://")):
            err.append(f"{C.F_FUENTES} {f['fuente_id']}: URL no completa")
        if not f["fecha_consulta"]:
            err.append(f"{C.F_FUENTES} {f['fuente_id']}: sin fecha_consulta")
    fuentes_por_campo = {(f["municipio_id"], f["campo_verificado"]) for f in datos.get(C.F_FUENTES, [])}
    for f in datos.get(C.F_INDICADORES, []):  # todo dato debe tener trazabilidad
        for c, v in f.items():
            if v and c not in ("municipio_id", "snapshot_id", "fecha_extraccion", "url_fuente", "fecha_actualizacion_portal") \
                    and (f["municipio_id"], c) not in fuentes_por_campo:
                err.append(f"{C.F_INDICADORES} {f['municipio_id']}: '{c}' sin fila de trazabilidad en 05")
    for f in m:  # datos de la ficha en 01 también requieren trazabilidad
        for c in ("intendente_nombre_completo", "partido_politico", "frente_electoral", "fecha_asuncion", "poblacion_2022"):
            if f.get(c) and (f["municipio_id"], c) not in fuentes_por_campo:
                err.append(f"{C.F_MUNICIPIOS} {f['municipio_id']}: '{c}' sin fila de trazabilidad en 05")
    for f in datos.get(C.F_ALERTAS, []):
        if f["severidad"] not in C.SEVERIDADES:
            err.append(f"{C.F_ALERTAS} {f['alerta_id']}: severidad inválida")
    if not datos.get(C.F_INDICADORES):
        adv.append("04: sin capturas de indicadores (línea de base pendiente)")
    return err, adv, datos


def informe(datos: dict[str, list[dict]], err: list[str], adv: list[str], modo: str) -> str:
    m = datos.get(C.F_MUNICIPIOS, [])
    ind = {f["municipio_id"]: f for f in datos.get(C.F_INDICADORES, [])}
    campos04 = [c for c in C.ESQUEMAS[C.F_INDICADORES] if c not in ("municipio_id", "snapshot_id", "fecha_extraccion", "url_fuente")]
    completos = parciales = sin = 0
    for f in m:
        n = sum(1 for c in campos04 if ind.get(f["municipio_id"], {}).get(c))
        if n == 0:
            sin += 1
        elif n == len(campos04):
            completos += 1
        else:
            parciales += 1
    inc = Counter(i["tipo_incidencia"] for i in datos.get(C.F_INCIDENCIAS, []) if i["estado_resolucion"] == "ABIERTA")
    pol = ["intendente_nombre_completo", "partido_politico", "coalicion_actual", "total_bancas"]
    l = [f"# Informe de calidad y cobertura\n",
         f"Generado por `scripts/validar.py` (modo `{modo}`). Los datos de prueba no se cuentan como reales.\n",
         "## Cobertura\n", "| Indicador | Valor |", "|---|---|",
         f"| Municipios en 01 | {len(m)} de 40 |",
         f"| Con indicadores completos | {completos} |", f"| Con indicadores parciales | {parciales} |",
         f"| Sin datos / sin verificar | {sin} |",
         f"| Intendentes verificados | {sum(1 for f in m if f.get('intendente_nombre_completo'))} |",
         f"| Concejos verificados | {sum(1 for f in m if f.get('total_bancas'))} |",
         f"| Contactos de protocolo | {len(datos.get(C.F_CONTACTOS, []))} |",
         f"| Capturas de indicadores (04) | {len(datos.get(C.F_INDICADORES, []))} |",
         f"| Filas de fuentes (05) | {len(datos.get(C.F_FUENTES, []))} |",
         f"| Incidencias abiertas (06) | {sum(inc.values())} |",
         f"| Alertas (08) | {len(datos.get(C.F_ALERTAS, []))} |",
         f"| Completitud de indicadores (campos con dato / posibles) | "
         f"{(sum(1 for f in ind.values() for c in campos04 if f.get(c)) / (max(len(m), 1) * len(campos04)) * 100):.1f} % |", ""]
    if inc:
        l += ["## Incidencias abiertas por tipo\n"] + [f"- `{k}`: {v}" for k, v in inc.most_common()] + [""]
    l += ["## Validación\n", f"- Errores: {len(err)}", f"- Advertencias: {len(adv)}"]
    l += [f"  - ERROR: {e}" for e in err[:30]] + [f"  - AVISO: {a}" for a in adv[:30]]
    return "\n".join(l) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["prueba", "completo"], default="prueba")
    ap.add_argument("--dir", type=Path, default=C.DIR_ACTUAL)
    ap.add_argument("--informe", type=Path, default=None, help="escribe el informe de cobertura en Markdown")
    a = ap.parse_args(argv)
    err, adv, datos = validar(a.dir, a.modo)
    for e in err:
        print("ERROR:", e)
    for w in adv:
        print("AVISO:", w)
    if a.informe:
        a.informe.write_text(informe(datos, err, adv, a.modo), encoding="utf-8")
    print(f"Validación: {len(err)} errores, {len(adv)} advertencias")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
