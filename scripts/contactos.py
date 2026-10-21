#!/usr/bin/env python3
"""Directorio de vinculación institucional AMBA: relevamiento de canales de contacto (independiente de los indicadores).

Lee los sitios OFICIALES configurados en config/sitios_oficiales.csv (no se deducen dominios), sigue solo enlaces de
contacto/autoridades/concejo, respeta robots.txt y límites, y escribe 03_amba_contactos_protocolo.csv (+ trazabilidad en 05,
incidencias en 06 y alertas en 08). No envía mensajes ni realiza gestiones de contacto.

Uso:  python scripts/contactos.py --municipios avellaneda,vicente_lopez,tres_de_febrero [--diagnostico DIR] [--informe MD]
      python scripts/contactos.py --municipios todos
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import contactos_parser as CP  # noqa: E402
import detectar_cambios as D  # noqa: E402
import extraer as E  # noqa: E402
import normalizar as N  # noqa: E402

SITIOS = C.DIR_CONFIG / "sitios_oficiales.csv"
MAX_PAGINAS, MAX_PAGINAS_HCD = 12, 6
CAMPOS_CANAL = ["responsable_nombre", "responsable_apellido", "responsable_nombre_completo", "cargo", "email_institucional",
                "telefono_institucional", "interno", "direccion", "horario_atencion", "sitio_web", "url_fuente", "evidencia"]


def cargar_sitios(ruta: Path = SITIOS) -> dict[str, dict]:
    return {r["municipio_id"]: r for r in C.leer_csv(ruta)}


def _oficial(host: str) -> bool:
    return host.lower().endswith((".gob.ar", ".gov.ar"))


def _inc(mid, clave, tipo, desc, url, fecha, snap, impacto="MEDIO", accion=""):
    return E._incidencia(mid, f"contacto:{clave}", tipo, desc, E.url_segura(url), fecha, snap, impacto, accion, E.url_segura(url))


def _fuente(mid, clave, campo, valor, h, fecha, snap, conf, titulo=""):
    hcd = CP.POR_CLAVE[clave]["organismo"] == "HCD"
    return {"fuente_id": C.id_estable(mid, f"contacto:{clave}", campo, valor, h["url"]), "municipio_id": mid,
            "entidad": f"contacto:{clave}", "campo_verificado": campo, "valor_obtenido": valor,
            "fuente_tipo": "SITIO_OFICIAL_HCD" if hcd else "SITIO_OFICIAL_MUNICIPAL", "organismo": CP.POR_CLAVE[clave]["dependencia"],
            "documento_titulo": titulo, "documento_url": E.url_segura(h["url"]), "fecha_documento": h.get("fecha_actualizacion", ""),
            "periodo_referencia": "", "fecha_consulta": fecha, "metodo_extraccion": "html_bloque_dependencia",
            "nivel_confianza": conf, "observaciones": f"etiqueta publicada='{h['etiqueta'][:80]}'; evidencia='{h['evidencia'][:140]}'",
            "snapshot_id": snap}


# ------------------------------------------------------------------ relevamiento de un municipio
def relevar_municipio(cli, cfg: dict, sitio: dict, fecha: str, snap: str, max_paginas: int = MAX_PAGINAS, dir_diag: Path | None = None) -> dict:
    mid, nombre = cfg["municipio_id"], cfg["municipio"]
    out = dict(municipio_id=mid, municipio=nombre, sitio_ok=False, hallazgos=[], general=[], paginas=[], incidencias=[], fuentes_extra=[])
    url0 = (sitio or {}).get("sitio_oficial", "").strip()
    if not url0:
        out["incidencias"].append(_inc(mid, "sitio_oficial", "SITIO_OFICIAL_NO_CONFIGURADO", "No hay sitio oficial en config/sitios_oficiales.csv.",
                                       E.BASE_URL, fecha, snap, "ALTO", "Cargar y verificar el sitio oficial del municipio."))
        return out
    r = cli.get(url0)
    if not r.ok:
        out["incidencias"].append(E._inc_respuesta(mid, r, fecha, snap, "contacto:sitio_oficial"))
        return out
    cab = CP.BeautifulSoup(r.texto, "lxml")
    texto_id = " ".join([cab.title.get_text(" ") if cab.title else ""] + [h.get_text(" ") for h in cab.find_all(["h1", "h2"])[:6]] +
                        [m.get("content", "") for m in cab.find_all("meta", attrs={"property": "og:site_name"})])
    host0 = urlparse(r.url_final or url0).hostname or ""
    if C.normalizar_texto(nombre) not in C.normalizar_texto(texto_id) or not (_oficial(host0) or sitio.get("estado") == "CONFIRMADO"):
        out["incidencias"].append(_inc(mid, "sitio_oficial", "SITIO_NO_VERIFICADO",
                                       f"{r.diagnostico()}; no se pudo verificar que sea el sitio oficial de {nombre} "
                                       f"(título/encabezados sin el nombre o dominio fuera de gob.ar/gov.ar).", url0, fecha, snap, "ALTO",
                                       "Revisar el dominio; marcar estado=CONFIRMADO en config solo tras verificación manual."))
        return out
    out["sitio_ok"] = True
    hcd_cfg = (sitio.get("sitio_hcd") or "").strip()
    bases = {CP.dominio_base(host0)} | ({CP.dominio_base(urlparse(hcd_cfg).hostname or "")} if hcd_cfg else set())
    cola, vistas, expandidas = [(url0, r.texto)], {E.url_segura(url0)}, set()
    pendientes = [(10, "", hcd_cfg)] if hcd_cfg else []
    n_hcd = 0
    while cola or pendientes:
        if cola:
            url, html = cola.pop(0)
        else:
            _, _, url = pendientes.pop(0)
            if E.url_segura(url) in vistas or len(vistas) >= max_paginas + MAX_PAGINAS_HCD:
                continue
            vistas.add(E.url_segura(url))
            rr = cli.get(url)
            if not rr.ok:
                if not rr.pagina_ausente:
                    out["incidencias"].append(E._inc_respuesta(mid, rr, fecha, snap, "contacto:pagina"))
                continue
            html = rr.texto
        host = CP.dominio_base(urlparse(url).hostname or "")
        if _oficial(host) or host in bases:
            bases.add(host)
        if dir_diag is not None:
            dir_diag.mkdir(parents=True, exist_ok=True)
            (dir_diag / f"contactos_{mid}_{C.id_estable(url)}.html").write_text(html[:1_000_000], encoding="utf-8")
        a = CP.analizar_pagina(html, url, bases)
        out["paginas"].append(E.url_segura(url))
        for h in a["hallazgos"]:
            out["hallazgos"].append(dict(h, titulo=a["titulo"], fecha_actualizacion=a["fecha_actualizacion"]))
        if a["general"]:
            out["general"].append(dict(a["general"], titulo=a["titulo"], fecha_actualizacion=a["fecha_actualizacion"]))
        # enlaces a seguir: mismo sitio; o sitio oficial externo cuyo enlace menciona al Concejo/HCD
        es_hcd = host not in {CP.dominio_base(host0)}
        limite = MAX_PAGINAS_HCD if es_hcd else max_paginas
        if host in expandidas:
            continue
        expandidas.add(host)
        for p, t, u in CP.enlaces_con_puntaje(html, url):
            h2 = CP.dominio_base(urlparse(u).hostname or "")
            mismo = h2 == host
            externo_hcd = _oficial(h2) and re.search(r"concejo|hcd", C.normalizar_texto(t + " " + u))
            if not (mismo or externo_hcd) or E.url_segura(u) in vistas:
                continue
            if sum(1 for x in vistas if CP.dominio_base(urlparse(x).hostname or "") == h2) >= (limite if mismo else 1):
                continue
            pendientes.append((p, t, u))
        pendientes.sort(key=lambda x: (-x[0], x[2]))
        if len(vistas) >= max_paginas + MAX_PAGINAS_HCD:
            pendientes = []
    return out


# ------------------------------------------------------------------ agregación y filas
def _agregar(hallazgos: list[dict]) -> dict:
    ag: dict[str, dict] = {}
    for h in hallazgos:
        a = ag.setdefault(h["clave"], dict(emails=[], telefonos=[], internos=[], direccion="", horario="", formulario="", responsable="",
                                           cargo="", responsable_original="", urls=[], canales_por_url={}, fechas={}, hs=[], omitidos=0))
        a["hs"].append(h)
        if not h["con_canal"]:
            continue
        for k_src, k_dst in (("emails", "emails"), ("telefonos", "telefonos"), ("internos", "internos")):
            a[k_dst] += [x for x in h[k_src] if x not in a[k_dst]]
        for k in ("direccion", "horario", "formulario", "responsable", "cargo", "responsable_original"):
            a[k] = a[k] or h.get(k, "")
        a["urls"].append(h["url"])
        a["canales_por_url"].setdefault(h["url"], set()).update(h["emails"] + [re.sub(r"\D", "", t) for t in h["telefonos"]])
        a["fechas"][h["url"]] = h.get("fecha_actualizacion", "")
        a["omitidos"] += sum(h.get("omitidos", {}).values())
    return ag


def _estado(a: dict | None, hoy: str) -> str:
    if a is None:
        return "NO_ENCONTRADO"
    if not (a["emails"] or a["telefonos"]):
        return "DEPENDENCIA_SIN_CANAL"
    conteo: dict[str, int] = {}
    for canales in a["canales_por_url"].values():
        for c in canales:
            conteo[c] = conteo.get(c, 0) + 1
    if any(n >= 2 for n in conteo.values()) or any(f and CP.fecha_reciente(f, hoy) for f in a["fechas"].values()):
        return "VIGENTE_CONFIRMADO"   # corroborado en 2+ páginas oficiales distintas, o página con actualización reciente visible
    return "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"


def construir_filas(res: dict, fecha: str, snap: str) -> tuple[list[dict], list[dict], list[dict]]:
    """(filas 03, fuentes 05, incidencias 06) de un municipio ya relevado."""
    mid, nombre = res["municipio_id"], res["municipio"]
    if not res["sitio_ok"]:
        return [], [], res["incidencias"]
    ag = _agregar(res["hallazgos"] + [dict(g, clave="contacto_general", omitidos=g.get("omitidos", {})) for g in res["general"]])
    filas, fuentes, incs = [], [], list(res["incidencias"])
    titulos = {h["url"]: h.get("titulo", "") for h in res["hallazgos"] + res["general"]}
    for d in [*CP.DEPENDENCIAS, CP.GENERAL]:
        clave, a = d["clave"], ag.get(d["clave"])
        estado = _estado(a, fecha)
        if clave == "contacto_general" and estado in ("NO_ENCONTRADO", "DEPENDENCIA_SIN_CANAL"):
            incs.append(_inc(mid, clave, "CANAL_NO_ENCONTRADO", "No se halló un contacto general institucional publicado.", res["paginas"][0],
                             fecha, snap, "ALTO", "Revisar manualmente la sección de contacto del sitio oficial."))
            continue
        org = f"Honorable Concejo Deliberante de {nombre}" if d["organismo"] == "HCD" else f"Municipalidad de {nombre}"
        nom, ape, met = C.separar_nombre(a["responsable"]) if a and a["responsable"] else ("", "", "")
        con = estado in ("VIGENTE_CONFIRMADO", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA")
        fila = {"municipio_id": mid, "organismo": org, "dependencia": d["dependencia"], "tipo_contacto": d["tipo"],
                "responsable_nombre": nom, "responsable_apellido": ape, "responsable_nombre_completo": a["responsable"] if a else "",
                "cargo": a["cargo"] if a else "", "email_institucional": "; ".join(a["emails"]) if a else "",
                "telefono_institucional": "; ".join(a["telefonos"]) if a else "", "interno": "; ".join(a["internos"]) if a else "",
                "direccion": a["direccion"] if a else "", "horario_atencion": a["horario"] if a else "",
                "sitio_web": (a["formulario"] or (a["urls"][0] if a["urls"] else "")) if a else "",
                "url_fuente": E.url_segura(a["urls"][0]) if a and a["urls"] else (E.url_segura(a["hs"][0]["url"]) if a else ""),
                "fecha_verificacion": fecha if con else "", "estado_contacto": estado, "snapshot_id": snap, "fecha_consulta": fecha,
                "evidencia": (a["hs"][0]["evidencia"] if a and a["hs"] else "")[:240]}
        filas.append(fila)
        if a is None and clave != "contacto_general":
            alt = "; canal alternativo: contacto institucional general / mesa de entradas" if clave in ("ceremonial", "relaciones") else ""
            incs.append(_inc(mid, clave, "OFICINA_NO_ENCONTRADA", f"No se identificó '{d['dependencia']}' en las {len(res['paginas'])} páginas oficiales consultadas{alt}.",
                             res["paginas"][0], fecha, snap, "MEDIO" if clave != "ceremonial" else "ALTO", "Revisar organigrama/decretos o consultar fuente oficial alternativa."))
        elif estado == "DEPENDENCIA_SIN_CANAL":
            incs.append(_inc(mid, clave, "CANAL_NO_ENCONTRADO", f"'{d['dependencia']}' figura en el sitio pero sin correo/teléfono atribuible a su bloque.",
                             a["hs"][0]["url"], fecha, snap, "MEDIO", "Buscar el canal en otra sección oficial o por pedido formal."))
        if a and a["omitidos"]:
            incs.append(_inc(mid, clave, "CANAL_NO_INSTITUCIONAL_OMITIDO",
                             f"{a['omitidos']} correo(s) de dominio no institucional o teléfono(s) móvil/WhatsApp publicados no se registraron.",
                             a["urls"][0], fecha, snap, "BAJO", "Ninguna: solo se registran canales institucionales."))
        if con:
            conf = "ALTO" if estado == "VIGENTE_CONFIRMADO" and clave != "contacto_general" else ("BAJO" if clave == "contacto_general" else "MEDIO")
            h0 = next(h for h in a["hs"] if h["con_canal"])
            for e in a["emails"]:
                fuentes.append(_fuente(mid, clave, "email_institucional", e, h0, fecha, snap, conf, titulos.get(h0["url"], "")))
            for t in a["telefonos"]:
                fuentes.append(_fuente(mid, clave, "telefono_institucional", t, h0, fecha, snap, conf, titulos.get(h0["url"], "")))
            for campo, val in (("responsable_nombre_completo", a["responsable"]), ("direccion", a["direccion"]),
                               ("horario_atencion", a["horario"]), ("sitio_web", a["formulario"])):
                if val:
                    fuentes.append(_fuente(mid, clave, campo, val, h0, fecha, snap, conf, titulos.get(h0["url"], "")))
            if a["responsable"] and met == "no_separado":
                incs.append(_inc(mid, clave, "NOMBRE_NO_SEPARADO", f"'{a['responsable']}' no se divide automáticamente (ambiguo).",
                                 h0["url"], fecha, snap, "BAJO", "Resolver con fuente documental si hace falta."))
    return filas, fuentes, incs


# ------------------------------------------------------------------ fusión incremental
def fusionar_contactos(existentes: list[dict], nuevas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Conserva registros y no pisa datos válidos con vacíos. Devuelve (filas, eventos de cambio)."""
    clave = lambda r: (r["municipio_id"], r["organismo"], r["dependencia"])  # noqa: E731
    res = {clave(r): dict(r) for r in existentes}
    con_filas = {r["municipio_id"] for r in existentes}
    eventos = []
    for n in nuevas:
        k, prev = clave(n), res.get(clave(n))
        n = {c: ("" if v is None else str(v)) for c, v in n.items()}
        con_canal = bool(n["email_institucional"] or n["telefono_institucional"])
        if prev is None:
            res[k] = n
            if con_canal and n["municipio_id"] in con_filas:
                eventos.append(dict(tipo="NUEVO", fila=n, prev=None))
            continue
        prev_canal = bool(prev.get("email_institucional") or prev.get("telefono_institucional"))
        if con_canal:
            for c in ("email_institucional", "telefono_institucional"):
                if prev.get(c) and set(prev[c].split("; ")) != set(n[c].split("; ")) and n[c]:
                    eventos.append(dict(tipo="CAMBIO", campo=c, fila=n, prev=dict(prev)))
            for c in CAMPOS_CANAL + ["tipo_contacto", "estado_contacto", "fecha_verificacion"]:
                if n.get(c):
                    prev[c] = n[c]
            if not prev_canal and prev["municipio_id"] in con_filas:
                eventos.append(dict(tipo="NUEVO", fila=n, prev=dict(prev)))
        elif prev_canal:                      # ya no se ve el canal: se conserva lo anterior sin afirmar vigencia
            eventos.append(dict(tipo="YA_NO_VISIBLE", fila=n, prev=dict(prev)))   # la incidencia tiene id estable: no se duplica
            prev["estado_contacto"] = "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"
        else:
            prev["estado_contacto"] = n["estado_contacto"]
        prev["snapshot_id"], prev["fecha_consulta"] = n["snapshot_id"], n["fecha_consulta"]
    orden = {d["dependencia"]: i for i, d in enumerate([*CP.DEPENDENCIAS, CP.GENERAL])}
    return sorted(res.values(), key=lambda r: (r["municipio_id"], orden.get(r["dependencia"], 99), r["dependencia"])), eventos


def alertas_de(eventos: list[dict], fecha: str, snap: str) -> list[dict]:
    out = []
    for ev in eventos:
        f, p = ev["fila"], ev["prev"] or {}
        if ev["tipo"] == "CAMBIO":
            out.append(D._alerta(f["municipio_id"], p.get("snapshot_id", ""), snap, fecha, "CAPA_I_INSTITUCIONAL", "CAMBIO_CONTACTO_OFICIAL",
                                 f"{f['dependencia']}.{ev['campo']}", p[ev["campo"]], f[ev["campo"]], "MEDIA",
                                 f"Cambió {ev['campo']} de {f['dependencia']}.", url=f["url_fuente"], fuente="sitio oficial"))
        elif ev["tipo"] == "NUEVO":
            out.append(D._alerta(f["municipio_id"], p.get("snapshot_id", ""), snap, fecha, "CAPA_I_INSTITUCIONAL", "NUEVO_CONTACTO_OFICIAL",
                                 f"{f['dependencia']}.canal", "", f["email_institucional"] or f["telefono_institucional"], "INFORMATIVA",
                                 f"Nuevo canal oficial publicado para {f['dependencia']}.", url=f["url_fuente"], fuente="sitio oficial"))
    return out


def aplicar(resultados: list[dict], fecha: str, snap: str, dir_actual: Path, dir_hist: Path) -> dict:
    filas, fuentes, incs, procesados = [], [], [], []
    for res in resultados:
        f, s, i = construir_filas(res, fecha, snap)
        filas += f; fuentes += s; incs += i
        procesados.append(res["municipio_id"])
    antes = {n: C.leer_csv(dir_actual / n) for n in (C.F_CONTACTOS, C.F_FUENTES, C.F_INCIDENCIAS, C.F_ALERTAS)}
    contactos, eventos = fusionar_contactos(antes[C.F_CONTACTOS], filas)
    propias = [i for i in antes[C.F_INCIDENCIAS] if i["campo"].startswith("contacto:")]
    resto = [i for i in antes[C.F_INCIDENCIAS] if not i["campo"].startswith("contacto:")]
    for ev in eventos:
        if ev["tipo"] == "YA_NO_VISIBLE":
            f = ev["fila"]
            clave = next((d["clave"] for d in CP.POR_CLAVE.values() if d["dependencia"] == f["dependencia"]), "contacto_general")
            incs.append(_inc(f["municipio_id"], clave, "CONTACTO_YA_NO_VISIBLE", "El canal publicado antes ya no aparece; se conserva el dato previo sin vigencia confirmada.",
                             ev["prev"].get("url_fuente") or E.BASE_URL, fecha, snap, "MEDIO", "Verificar manualmente si cambió o se retiró."))
    out = {
        C.F_CONTACTOS: contactos,
        C.F_FUENTES: N.fusionar_fuentes(antes[C.F_FUENTES], fuentes),
        C.F_INCIDENCIAS: resto + N.fusionar_incidencias(propias, incs, set(procesados), fecha),
        C.F_ALERTAS: D.fusionar_alertas(antes[C.F_ALERTAS], alertas_de(eventos, fecha, snap)),
    }
    escritos = [n for n, v in out.items() if N.escribir_con_historial(n, v, dir_actual, dir_hist, fecha)]
    return {"archivos_escritos": escritos, "filas": len(filas), "fuentes_nuevas": len(out[C.F_FUENTES]) - len(antes[C.F_FUENTES]),
            "alertas_nuevas": len(out[C.F_ALERTAS]) - len(antes[C.F_ALERTAS]), "incidencias": len(incs)}


# ------------------------------------------------------------------ informe y CLI
def informe_md(filas: list[dict], municipios: list[str], fecha: str) -> str:
    deps = [d["dependencia"] for d in [*CP.DEPENDENCIAS, CP.GENERAL]]
    sim = {"VIGENTE_CONFIRMADO": "✔ vigente", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA": "✔ publicado", "DEPENDENCIA_SIN_CANAL": "◐ sin canal", "NO_ENCONTRADO": "✘"}
    l = [f"# Directorio de vinculación: cobertura ({fecha})\n", "| Municipio | " + " | ".join(deps) + " |", "|---|" + "---|" * len(deps)]
    for mid in municipios:
        celdas = []
        for d in deps:
            f = next((x for x in filas if x["municipio_id"] == mid and x["dependencia"] == d), None)
            celdas.append(sim.get(f["estado_contacto"], "·") if f else "—")
        l.append(f"| {mid} | " + " | ".join(celdas) + " |")
    cuenta = {}
    for f in filas:
        cuenta[f["estado_contacto"]] = cuenta.get(f["estado_contacto"], 0) + 1
    l += ["", "Estados: " + ", ".join(f"{k}={v}" for k, v in sorted(cuenta.items())), "", "— = no relevado (sitio no verificado)."]
    return "\n".join(l) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--municipios", default="avellaneda,vicente_lopez,tres_de_febrero")
    ap.add_argument("--fecha", default=None)
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--max-paginas", type=int, default=MAX_PAGINAS)
    ap.add_argument("--diagnostico", type=Path, default=None)
    ap.add_argument("--informe", type=Path, default=None)
    a = ap.parse_args(argv)
    ahora = C.ahora_utc()
    fecha, snap = a.fecha or ahora.strftime("%Y-%m-%d"), C.snapshot_desde(ahora)
    cfg_all = C.cargar_municipios_cfg()
    sel = E.seleccionar(cfg_all, a.municipios)
    sitios, cli = cargar_sitios(), E.Cliente(pausa=a.pausa)
    resultados = [relevar_municipio(cli, c, sitios.get(c["municipio_id"], {}), fecha, snap, a.max_paginas, a.diagnostico) for c in sel]
    resumen = aplicar(resultados, fecha, snap, C.DIR_ACTUAL, C.DIR_HISTORICO)
    resumen["solicitudes_http"] = cli.n_solicitudes
    resumen["municipios"] = {r["municipio"]: {"sitio_verificado": r["sitio_ok"], "paginas": len(r["paginas"])} for r in resultados}
    print(__import__("json").dumps(resumen, ensure_ascii=False, indent=2))
    if a.informe:
        a.informe.write_text(informe_md(C.leer_csv(C.DIR_ACTUAL / C.F_CONTACTOS), [c["municipio_id"] for c in sel], fecha), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
