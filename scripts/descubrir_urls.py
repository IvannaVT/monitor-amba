#!/usr/bin/env python3
"""Descubre y VERIFICA las URL de las fichas municipales (sin inferir rutas).

Las URL salen únicamente de enlaces/sitemaps reales del portal:
  - portada y /ranking/ (ruta confirmada por el BreadcrumbList de las fichas),
  - sitemaps declarados en robots.txt.
Cada candidata se confirma con una solicitud: HTTP 200 y título (primer encabezado) igual al
nombre del municipio. Si el título no coincide o no hay respuesta correcta, NO se escribe.
Del mismo GET se toma el código de partido INDEC publicado por el portal (no verificado contra
el INDEC): se completa en config solo con el formato 06xxx, sin duplicados y marcado como tal.

Uso: python scripts/descubrir_urls.py [--municipios todos|ids] [--salida diagnostico] [--aplicar]
Sin --aplicar no modifica config/. Nunca hace commits.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import extraer as E  # noqa: E402
import normalizar as N  # noqa: E402
import parser_ficha as P  # noqa: E402

PAGINAS_LISTADO = [E.BASE_URL + "ranking/"]
RE_FICHA = re.compile(r"^/m/[a-z0-9][a-z0-9\-]*/?$")
INDEC_FUENTE = "portal (metadatos de la ficha); pendiente de verificar contra el nomenclador INDEC"


def reunir_fichas(cli) -> tuple[list[tuple[str, str]], list[str]]:
    """(enlaces a /m/<slug>/ encontrados, notas de incidencias de acceso)."""
    host = urlparse(E.BASE_URL).netloc
    rp, _ = cli._robots_de(E.BASE_URL)
    cola = [E.BASE_URL, *PAGINAS_LISTADO, *((rp.site_maps() or [])[:3] if rp else [])]
    vistos, enlaces, notas, n_xml = set(), [], [], 0
    while cola and len(vistos) < 12:
        u = cola.pop(0)
        if u in vistos or urlparse(u).netloc != host:
            continue
        vistos.add(u)
        r = cli.get(u)
        if not r.ok:
            notas.append(f"{u}: {r.diagnostico()}")
            continue
        if u.endswith(".xml"):
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.texto)
            enlaces += [("", x) for x in locs if urlparse(x).netloc == host]
            if n_xml < 5:  # un nivel de sitemap-index
                cola += [x for x in locs if x.endswith(".xml")]
                n_xml += 1
        else:
            enlaces += E.descubrir_enlaces(r.texto, E.BASE_URL)
    unicos = {}
    for t, u in enlaces:
        if RE_FICHA.match(urlparse(u).path):
            unicos.setdefault(u, t)
    return [(t, u) for u, t in unicos.items()], notas


def verificar(cli, cfg: dict, url: str) -> dict:
    """GET único de la ficha: HTTP 200 + título igual al municipio (+ INDEC publicado)."""
    r = cli.get(url)
    res = {"municipio_id": cfg["municipio_id"], "municipio": cfg["municipio"], "url": E.url_segura(url),
           "http": r.status, "titulo": "", "indec": "", "estado": "", "detalle": ""}
    if not r.ok:
        res.update(estado="PAGINA_AUSENTE" if r.pagina_ausente else r.tipo_error, detalle=r.diagnostico())
        return res
    toks = P.tokenizar(r.texto)
    res["titulo"] = next((t for t, enc in toks if enc), "")
    if C.normalizar_texto(res["titulo"]) != C.normalizar_texto(cfg["municipio"]):
        res.update(estado="TITULO_NO_COINCIDE", detalle=f"título '{res['titulo']}' != '{cfg['municipio']}'")
        return res
    res["indec"] = (P.analizar_tokens(toks)["hallados"].get("indec_codigo") or {}).get("valor", "")
    res["estado"] = "VERIFICADA"
    return res


def descubrir(cli, cfg_all: list[dict], seleccion: list[dict]) -> tuple[list[dict], list[str]]:
    fichas, notas = reunir_fichas(cli)
    resultados = []
    for cfg in seleccion:
        url = (cfg.get("url_portal_municipio") or "").strip()
        origen = "config"
        if not url:
            url, motivo = E.encontrar_pagina_municipio(fichas, cfg["municipio"])
            origen = "enlace_del_portal"
            if not url:
                resultados.append({"municipio_id": cfg["municipio_id"], "municipio": cfg["municipio"], "url": "", "http": None,
                                   "titulo": "", "indec": "", "estado": "URL_NO_ENCONTRADA", "detalle": motivo, "origen": ""})
                continue
        v = verificar(cli, cfg, url)
        v["origen"] = origen
        resultados.append(v)
    return resultados, notas


def aplicar_config(resultados: list[dict], cfg_all: list[dict], ruta: Path) -> dict:
    """Completa url_portal_municipio e indec_codigo SOLO con datos verificados; no pisa valores existentes."""
    por_id = {r["municipio_id"]: r for r in resultados if r["estado"] == "VERIFICADA"}
    usados = {c["indec_codigo"] for c in cfg_all if c.get("indec_codigo")}
    cambios = {"urls": 0, "indec": 0, "indec_conflictos": []}
    for c in cfg_all:
        v = por_id.get(c["municipio_id"])
        if not v:
            continue
        if not c.get("url_portal_municipio"):
            c["url_portal_municipio"] = v["url"]
            cambios["urls"] += 1
        if v["indec"] and not c.get("indec_codigo"):
            if re.fullmatch(r"06\d{3}", v["indec"]) and v["indec"] not in usados:
                c["indec_codigo"], c["indec_fuente"] = v["indec"], INDEC_FUENTE
                usados.add(v["indec"])
                cambios["indec"] += 1
            else:
                cambios["indec_conflictos"].append(c["municipio_id"])
    cols = list(cfg_all[0].keys())
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(cfg_all)
    return cambios


def informe_md(resultados: list[dict], notas: list[str], cambios: dict | None) -> str:
    cuenta = {}
    for r in resultados:
        cuenta[r["estado"]] = cuenta.get(r["estado"], 0) + 1
    l = ["# Descubrimiento de URL de fichas\n", "| Estado | Municipios |", "|---|---|"]
    l += [f"| {k} | {v} |" for k, v in sorted(cuenta.items())]
    if cambios is not None:
        l += ["", f"Config actualizada: {cambios['urls']} URL y {cambios['indec']} códigos INDEC (del portal, sin verificar oficialmente)."]
    l += ["", "| Municipio | Estado | HTTP | URL | INDEC (portal) | Detalle |", "|---|---|---|---|---|---|"]
    l += [f"| {r['municipio']} | {r['estado']} | {r['http'] or ''} | {r['url']} | {r['indec']} | {r['detalle'][:90]} |" for r in resultados]
    if notas:
        l += ["", "## Accesos no logrados"] + [f"- {n}" for n in notas]
    return "\n".join(l) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--municipios", default="todos")
    ap.add_argument("--salida", type=Path, default=Path("diagnostico"))
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--aplicar", action="store_true", help="escribe lo verificado en config/municipios_amba.csv")
    a = ap.parse_args(argv)
    cfg_all = C.cargar_municipios_cfg()
    cli = E.Cliente(pausa=a.pausa)
    resultados, notas = descubrir(cli, cfg_all, E.seleccionar(cfg_all, a.municipios))
    cambios = aplicar_config(resultados, cfg_all, C.ARCHIVO_MUNICIPIOS_CFG) if a.aplicar else None
    registrar_incidencias(resultados, notas)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "descubrimiento_urls.md").write_text(informe_md(resultados, notas, cambios), encoding="utf-8")
    print(informe_md(resultados, notas, cambios))
    return 0


def registrar_incidencias(resultados: list[dict], notas: list[str], dir_actual: Path | None = None,
                          dir_hist: Path | None = None) -> None:
    """Las URL no verificadas quedan como incidencias en 06 (con historial)."""
    ahora = C.ahora_utc()
    fecha, snap = ahora.strftime("%Y-%m-%d"), C.snapshot_desde(ahora)
    dir_actual, dir_hist = dir_actual or C.DIR_ACTUAL, dir_hist or C.DIR_HISTORICO
    nuevas = [E._incidencia(r["municipio_id"], "url_portal_municipio", r["estado"], r["detalle"] or r["estado"], r["url"] or E.BASE_URL,
                            fecha, snap, "ALTO", "Revisar manualmente o completar url_portal_municipio en config.", E.BASE_URL)
              for r in resultados if r["estado"] != "VERIFICADA"]
    nuevas += [E._incidencia("GLOBAL", "descubrimiento_urls", "ACCESO_LISTADO_NO_LOGRADO", n, E.BASE_URL, fecha, snap, "MEDIO",
                             "Reintentar o aportar la lista de fichas.", E.BASE_URL) for n in notas]
    ids = {r["municipio_id"] for r in resultados} | {"GLOBAL"}
    todas = C.leer_csv(dir_actual / C.F_INCIDENCIAS)
    propias = [i for i in todas if i["campo"] in ("url_portal_municipio", "descubrimiento_urls")]  # solo estas se resuelven aquí
    resto = [i for i in todas if i not in propias]
    N.escribir_con_historial(C.F_INCIDENCIAS, resto + N.fusionar_incidencias(propias, nuevas, ids, fecha), dir_actual, dir_hist, fecha)


if __name__ == "__main__":
    sys.exit(main())
