#!/usr/bin/env python3
"""Descubre y verifica el SITIO OFICIAL de cada municipio SIN deducir dominios.

Fuente de candidatos: los enlaces que la ficha del portal (URL ya verificada en config/municipios_amba.csv) publica hacia
documentos de la "Municipalidad de <nombre>" en dominios gob.ar/gov.ar. Cada candidato se confirma con una solicitud
(robots.txt y TLS se respetan): HTTP 200, título/encabezados con el nombre del municipio, sin ser un homónimo de otra provincia.
Resultado: estado `VERIFICADO_TECNICAMENTE` (no equivale a la confirmación humana `CONFIRMADO`).

Uso: python scripts/descubrir_sitios.py --municipios intermedia|todos|ids [--aplicar] [--salida diagnostico]
Sin --aplicar no modifica config/. Nunca hace commits. No pisa sitios ya cargados ni CONFIRMADO.
"""
from __future__ import annotations

import argparse
import csv
import re
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import contactos_parser as CP  # noqa: E402
import extraer as E  # noqa: E402
import normalizar as N  # noqa: E402

ESTADO_OK = "VERIFICADO_TECNICAMENTE"
# Presupuestos por defecto (segundos / solicitudes). Ningún municipio ni la ejecución completa pueden quedar bloqueados.
PLAZO_MUNICIPIO, PLAZO_TOTAL, MAX_SOLICITUDES_MUNICIPIO = 90.0, 1200.0, 14
ERRORES_PRESUPUESTO = ("PLAZO_TOTAL_AGOTADO", "TIMEOUT_MUNICIPIO", "LIMITE_SOLICITUDES_MUNICIPIO")
_CONTENEDORES = ("li", "p", "tr", "dd", "div", "td")


def _contexto(a) -> str:
    """Texto del contenedor más cercano al enlace (la línea 'Municipalidad de X - Secretaría...: documento')."""
    nodo = a
    for _ in range(4):
        nodo = nodo.parent
        if nodo is None:
            break
        t = nodo.get_text(" ", strip=True)
        if nodo.name in _CONTENEDORES and len(t) <= 300:
            return t
    return a.get_text(" ", strip=True)


def candidatos_desde_ficha(html: str, ficha_url: str, nombre: str) -> list[dict]:
    """Hosts gob.ar/gov.ar enlazados en contextos 'Municipalidad de <nombre>' (los de otras entidades no cuentan)."""
    soup = CP.BeautifulSoup(html, "lxml")
    portal, obj = urlparse(ficha_url).hostname, CP.norm(nombre)
    patrones = [rf"\b{pre} {re.escape(obj)}\b" for pre in ("municipalidad de", "municipio de", "municipalidad")]
    res: dict[str, list[str]] = {}
    for a in soup.find_all("a", href=True):
        u = urljoin(ficha_url, a["href"])
        p = urlparse(u)
        host = (p.hostname or "").lower()
        if p.scheme not in ("http", "https") or not host or host == portal or not host.endswith((".gob.ar", ".gov.ar")):
            continue
        if CP.dominio_homonimo(host) or not any(re.search(x, CP.norm(_contexto(a))) for x in patrones):
            continue
        res.setdefault(host, []).append(E.url_segura(u))
    return [{"host": h, "enlaces": v} for h, v in sorted(res.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def raices_candidatas(host: str) -> list[str]:
    """Raíz del propio host del documento y, si es un subdominio, la de su dominio (gob.ar/gov.ar: últimas 3 etiquetas)."""
    base = ".".join(host.split(".")[-3:])
    raices = [f"https://{host}/"]
    for extra in (f"https://{base}/", f"https://www.{base}/"):
        if extra not in raices:
            raices.append(extra)
    return raices


def base_de(host: str) -> str:
    h = (host or "").lower()
    return ".".join(h.split(".")[-3:] if h.endswith((".gob.ar", ".gov.ar")) else h.split(".")[-2:])


def verificar_raiz(cli, raiz: str, nombre: str, exigir_nombre: bool = True, exigir_provincia: bool = True) -> dict:
    base = base_de(urlparse(raiz).hostname)
    r = K._get(cli, raiz, {base})
    res = {"raiz": raiz, "http": r.status, "titulo": "", "ok": False, "detalle": ""}
    if not r.ok:
        res["detalle"] = r.diagnostico()
        return res
    cab = CP.BeautifulSoup(r.texto, "lxml")
    for t in cab(["script", "style", "noscript"]):
        t.decompose()
    ident = " ".join([cab.title.get_text(" ") if cab.title else ""] + [h.get_text(" ") for h in cab.find_all(["h1", "h2"])[:6]] +
                     [m.get("content", "") for m in cab.find_all("meta", attrs={"property": "og:site_name"})])
    res["titulo"] = (cab.title.get_text(" ", strip=True) if cab.title else ident)[:120]
    host_final = urlparse(r.url_final or raiz).hostname or ""
    if CP.dominio_homonimo(host_final) or CP.provincia_ajena(ident + " " + cab.get_text(" ", strip=True)[:4000]):
        res["detalle"] = "posible homónimo de otra provincia"
    elif base_de(host_final) != base:
        res["detalle"] = f"el destino final ({host_final}) no es del dominio verificado"
    elif exigir_nombre and not CP.nombre_en_texto(nombre, ident):
        res["detalle"] = "el título/encabezados no nombran al municipio"
    elif exigir_provincia and not CP.evidencia_bonaerense(ident + " " + cab.get_text(" ", strip=True)[:6000], cab):
        res["detalle"] = "sin evidencia de pertenecer a la provincia de Buenos Aires (podría ser un homónimo de otra provincia)"
    else:
        res["ok"], res["raiz"] = True, E.url_segura(r.url_final or raiz)
    return res


def descubrir(cli, cfg_all: list[dict], sitios: dict[str, dict], seleccion: list[dict], resultados: list[dict] | None = None,
              plazo_municipio: float | None = PLAZO_MUNICIPIO, plazo_total: float | None = PLAZO_TOTAL,
              max_solicitudes: int | None = MAX_SOLICITUDES_MUNICIPIO, al_terminar=None, log=print) -> list[dict]:
    """`resultados` (lista del llamador) se va llenando municipio a municipio: si la ejecución se corta, lo hecho se conserva."""
    resultados = [] if resultados is None else resultados
    if plazo_total and hasattr(cli, "fin_global"):
        cli.fin_global = time.monotonic() + plazo_total
    dueno = {base_de(urlparse(x["sitio_oficial"]).hostname): m for m, x in sitios.items() if x.get("sitio_oficial")}   # dominio -> municipio
    t0, total = time.monotonic(), len(seleccion)
    for i, cfg in enumerate(seleccion, 1):
        n_antes = len(resultados)
        agotado = cli.presupuesto_agotado() if hasattr(cli, "presupuesto_agotado") else ""
        if agotado == "PLAZO_TOTAL_AGOTADO":     # el resto queda registrado como no procesado, sin tocar la red
            for c in seleccion[i - 1:]:
                resultados.append(_fila(c, estado="NO_PROCESADO_PLAZO_TOTAL", detalle=f"plazo total de {plazo_total:g} s agotado antes de procesarlo"))
                if al_terminar:
                    al_terminar(resultados)
            log(f"[{i}/{total}] plazo total agotado: {total - i + 1} municipio(s) sin procesar", flush=True)
            break
        if hasattr(cli, "iniciar_municipio"):
            cli.iniciar_municipio(plazo_municipio, max_solicitudes)
        t1, n1 = time.monotonic(), getattr(cli, "n_solicitudes", 0)
        log(f"[{i}/{total}] {cfg['municipio']}: inicio", flush=True)
        try:
            _descubrir_uno(cli, cfg, sitios, resultados, dueno)
        except Exception as exc:  # noqa: BLE001 - un municipio con error inesperado no frena a los demás
            _cerrar(resultados, cfg, n_antes, "ERROR_INESPERADO", f"{type(exc).__name__}: {str(exc)[:150]}")
        fila = resultados[-1]
        if fila["estado"] in ERRORES_PRESUPUESTO or (fila["estado"] not in (ESTADO_OK, "YA_CONFIGURADO") and any(e in (fila["detalle"] or "") for e in ERRORES_PRESUPUESTO)):
            fila["detalle"] = f"{fila['estado']}; {fila['detalle']}"[:300]
        log(f"[{i}/{total}] {cfg['municipio']}: {fila['estado']} · {getattr(cli, 'n_solicitudes', 0) - n1} solicitudes · "
            f"{time.monotonic() - t1:.1f} s · acumulado {time.monotonic() - t0:.0f} s", flush=True)
        if al_terminar:
            al_terminar(resultados)
    return resultados


def _fila(cfg: dict, **kw) -> dict:
    return {"municipio_id": cfg["municipio_id"], "municipio": cfg["municipio"], "estado": "", "sitio": "", "http": None, "titulo": "",
            "enlace_documento": "", "ficha": cfg.get("url_portal_municipio", ""), "detalle": "", **kw}


def _cerrar(resultados: list[dict], cfg: dict, n_antes: int, estado: str, detalle: str) -> None:
    """Deja exactamente una fila para el municipio, con el estado dado."""
    del resultados[n_antes:]
    resultados.append(_fila(cfg, estado=estado, detalle=detalle))


def _descubrir_uno(cli, cfg: dict, sitios: dict[str, dict], resultados: list[dict], dueno: dict[str, str]) -> None:
    for cfg in (cfg,):
        mid, nombre = cfg["municipio_id"], cfg["municipio"]
        fila = {"municipio_id": mid, "municipio": nombre, "estado": "", "sitio": "", "http": None, "titulo": "", "enlace_documento": "",
                "ficha": cfg.get("url_portal_municipio", ""), "detalle": ""}
        resultados.append(fila)
        s = sitios.get(mid, {})
        if s.get("estado") == "OFICIAL_DOCUMENTADO" and s.get("sitio_oficial"):     # identificado en una fuente oficial: solo se comprueba el acceso HTTP
            v = verificar_raiz(cli, s["sitio_oficial"], nombre, exigir_nombre=False, exigir_provincia=False)
            fila.update(estado="DOCUMENTADO_HTTP_OK" if v["ok"] else "DOCUMENTADO_HTTP_FALLIDO", sitio=s["sitio_oficial"], http=v["http"],
                        titulo=v["titulo"], detalle=v["detalle"])
            continue
        candidato = s.get("sitio_oficial", "") if s.get("estado") == "CANDIDATO_A_VERIFICAR" else ""
        if s.get("estado") in ("CONFIRMADO", ESTADO_OK) or (s.get("sitio_oficial") and not candidato):
            fila.update(estado="YA_CONFIGURADO", sitio=s.get("sitio_oficial", ""))
            continue
        previo = ""
        if candidato:                       # 1) se verifica el candidato cargado; no se toma por bueno sin comprobarlo
            v = verificar_raiz(cli, candidato, nombre)
            if v["ok"] and dueno.get(base_de(urlparse(v["raiz"]).hostname), mid) == mid:
                fila.update(estado=ESTADO_OK, sitio=v["raiz"], http=v["http"], titulo=v["titulo"], origen="candidato verificado")
                continue
            previo = f"candidato {candidato}: {v['detalle'] or 'dominio ya asignado a otro municipio'}"
            fila["detalle"] = previo
        if not fila["ficha"]:
            fila.update(estado="CANDIDATO_NO_VERIFICADO" if candidato else "FICHA_NO_CONFIGURADA", detalle=previo or "sin url_portal_municipio")
            continue
        r = cli.get(fila["ficha"])                    # 2) respaldo: enlaces de la ficha del portal
        if not r.ok:
            fila.update(estado="CANDIDATO_NO_VERIFICADO" if candidato else r.tipo_error, http=r.status, detalle=(previo + " | " if previo else "") + r.diagnostico())
            continue
        cands, fallos = candidatos_desde_ficha(r.texto, fila["ficha"], nombre), []
        if not cands:
            fila.update(estado="CANDIDATO_NO_VERIFICADO" if candidato else "SITIO_NO_DESCUBIERTO",
                        detalle=(previo + " | " if previo else "") + "la ficha no enlaza documentos de la Municipalidad en dominios gob.ar/gov.ar")
            continue
        for cand in cands[:2]:
            for raiz in raices_candidatas(cand["host"]):
                v = verificar_raiz(cli, raiz, nombre)
                if v["ok"]:
                    if dueno.get(base_de(urlparse(v["raiz"]).hostname), mid) != mid:
                        fila.update(estado="DOMINIO_DUPLICADO", sitio=v["raiz"], detalle="ya asignado a otro municipio")
                    else:
                        dueno[base_de(urlparse(v["raiz"]).hostname)] = mid
                        fila.update(estado=ESTADO_OK, sitio=v["raiz"], http=v["http"], titulo=v["titulo"], enlace_documento=cand["enlaces"][0],
                                    origen="ficha del portal")
                    break
                fallos.append(f"{raiz}: {v['detalle']}")
            if fila["estado"]:
                break
        if not fila["estado"]:
            fila.update(estado="CANDIDATO_NO_VERIFICADO" if candidato else "SITIO_NO_VERIFICADO", detalle=" | ".join(([previo] if previo else []) + fallos)[:300])
    return resultados


def aplicar_config(resultados: list[dict], ruta: Path, fecha: str | None = None) -> int:
    """Completa filas SIN_CONFIGURAR o CANDIDATO_A_VERIFICAR con sitios verificados técnicamente; nunca pisa CONFIRMADO ni lo ya verificado."""
    filas = C.leer_csv(ruta)
    cols = list(filas[0].keys())
    fecha = fecha or C.ahora_utc().strftime("%Y-%m-%d")
    if "verificacion_http" not in cols:
        cols.append("verificacion_http")
    http = {r["municipio_id"]: r for r in resultados if r["estado"] in ("DOCUMENTADO_HTTP_OK", "DOCUMENTADO_HTTP_FALLIDO")}
    for f in filas:    # la verificación técnica de un sitio documentado va en su propia columna: no cambia su condición documental
        if f["municipio_id"] in http:
            r_ = http[f["municipio_id"]]
            f["verificacion_http"] = (f"HTTP {r_['http']} verificado el {fecha}; título '{r_['titulo']}'" if r_["estado"] == "DOCUMENTADO_HTTP_OK"
                                      else f"NO verificado el {fecha}: {r_['detalle'][:200]}")
    n = 0
    por_id = {r["municipio_id"]: r for r in resultados if r["estado"] == ESTADO_OK}
    for f in filas:
        v = por_id.get(f["municipio_id"])
        if v and ((not f.get("sitio_oficial") and f.get("estado") == "SIN_CONFIGURAR") or f.get("estado") == "CANDIDATO_A_VERIFICAR"):
            origen = (f"candidato cargado en la config, comprobado: HTTP {v['http']}; título '{v['titulo']}'" if v.get("origen") == "candidato verificado"
                      else f"descubierto en la ficha del portal {v['ficha']} → enlace {v['enlace_documento']}; HTTP {v['http']}; título '{v['titulo']}'")
            anterior = f" (candidato anterior no comprobado: {f['sitio_oficial']})" if f.get("sitio_oficial") and f["sitio_oficial"] != v["sitio"] else ""
            f.update(sitio_oficial=v["sitio"], estado=ESTADO_OK, fuente=f"{origen}{anterior}; pendiente de confirmación humana")
            n += 1
    with open(ruta, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    return n


def informe_cobertura(sitios: list[dict], resultados: list[dict] | None = None) -> str:
    cuenta: dict[str, int] = {}
    for s in sitios:
        cuenta[s["estado"]] = cuenta.get(s["estado"], 0) + 1
    etiqueta = {"CONFIRMADO": "verificado por una persona", "OFICIAL_DOCUMENTADO": "oficial según fuente documental (la verificación HTTP va aparte)", "VERIFICADO_TECNICAMENTE": "verificado técnicamente (falta confirmación humana)",
                "CANDIDATO_A_VERIFICAR": "candidato NO comprobado", "SIN_CONFIGURAR": "pendiente (sin candidato)"}
    l = ["# Cobertura territorial: sitios oficiales\n", "| Estado | Significado | Municipios |", "|---|---|---|"] + \
        [f"| {k} | {etiqueta.get(k, '')} | {v} |" for k, v in sorted(cuenta.items())]
    l += ["", "| Municipio | Estado | Sitio oficial | Verificación HTTP | Fuente |", "|---|---|---|---|---|"]
    for s in sitios:
        l.append(f"| {s['municipio_id']} | {s['estado']} | {s['sitio_oficial']} | {(s.get('verificacion_http') or '—')[:50]} | {(s.get('fuente') or '')[:70]} |")
    if resultados:
        l += ["", "## Resultado del descubrimiento", "", "| Municipio | Resultado | Sitio | HTTP | Detalle |", "|---|---|---|---|---|"]
        l += [f"| {r['municipio']} | {r['estado']} | {r['sitio']} | {r['http'] or ''} | {r['detalle'][:100]} |" for r in resultados]
    return "\n".join(l) + "\n"


def registrar_incidencias(resultados: list[dict], dir_actual: Path | None = None, dir_hist: Path | None = None) -> None:
    ahora = C.ahora_utc()
    fecha, snap = ahora.strftime("%Y-%m-%d"), C.snapshot_desde(ahora)
    dir_actual, dir_hist = dir_actual or C.DIR_ACTUAL, dir_hist or C.DIR_HISTORICO
    nuevas = [E._incidencia(r["municipio_id"], "sitios:descubrimiento", r["estado"], r["detalle"] or r["estado"], r["ficha"] or E.BASE_URL, fecha, snap,
                            "MEDIO", "Confirmar o cargar el sitio oficial a mano en config/sitios_oficiales.csv.", E.BASE_URL)
              for r in resultados if r["estado"] not in (ESTADO_OK, "YA_CONFIGURADO", "DOCUMENTADO_HTTP_OK")]
    todas = C.leer_csv(dir_actual / C.F_INCIDENCIAS)
    propias = [i for i in todas if i["campo"].startswith("sitios:")]
    resto = [i for i in todas if not i["campo"].startswith("sitios:")]
    ids = {r["municipio_id"] for r in resultados}
    N.escribir_con_historial(C.F_INCIDENCIAS, resto + N.fusionar_incidencias(propias, nuevas, ids, fecha), dir_actual, dir_hist, fecha)


def _guardar_parcial(res: list[dict], salida: Path) -> None:
    """Informe y avance escritos tras cada municipio: si el proceso se corta, queda lo ya resuelto."""
    salida.mkdir(parents=True, exist_ok=True)
    tmp = salida / "cobertura_sitios.md.tmp"
    tmp.write_text(informe_cobertura(C.leer_csv(C.ARCHIVO_SITIOS), res), encoding="utf-8")
    tmp.replace(salida / "cobertura_sitios.md")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--municipios", default="intermedia")
    ap.add_argument("--salida", type=Path, default=Path("diagnostico_contactos"))
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--aplicar", action="store_true", help="completa config/sitios_oficiales.csv (solo filas SIN_CONFIGURAR)")
    ap.add_argument("--plazo-solicitud", type=float, default=K.PLAZO_SOLICITUD, help="segundos máximos por solicitud (total)")
    ap.add_argument("--plazo-municipio", type=float, default=PLAZO_MUNICIPIO, help="segundos máximos por municipio")
    ap.add_argument("--plazo-total", type=float, default=PLAZO_TOTAL, help="segundos máximos de toda la ejecución")
    ap.add_argument("--max-solicitudes", type=int, default=MAX_SOLICITUDES_MUNICIPIO, help="solicitudes máximas por municipio (incluye robots.txt)")
    a = ap.parse_args(argv)

    def cortar(signum, _frame):      # cancelación de Actions (SIGTERM/SIGINT): se conserva lo ya hecho
        raise KeyboardInterrupt(f"señal {signum}")
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, cortar)
    cfg_all = C.cargar_municipios_cfg()
    sitios = K.cargar_sitios()
    cli = K.ClienteContactos(pausa=a.pausa, plazo_solicitud=a.plazo_solicitud)
    seleccion = K.seleccionar(cfg_all, a.municipios)
    res: list[dict] = []
    interrumpido = ""
    try:
        descubrir(cli, cfg_all, sitios, seleccion, res, a.plazo_municipio, a.plazo_total, a.max_solicitudes,
                  al_terminar=lambda r: _guardar_parcial(r, a.salida))
    except KeyboardInterrupt as exc:
        interrumpido = str(exc) or "interrumpido"
        hechos = {r["municipio_id"] for r in res}
        res.extend(_fila(c, estado="NO_PROCESADO_INTERRUMPIDO", detalle=f"ejecución interrumpida ({interrumpido})") for c in seleccion if c["municipio_id"] not in hechos)
        print(f"INTERRUMPIDO ({interrumpido}): se conservan {len(hechos)} resultados", flush=True)
    finally:
        if a.aplicar:
            print(f"Config actualizada: {aplicar_config(res, C.ARCHIVO_SITIOS)} sitios", flush=True)
        registrar_incidencias(res)
        _guardar_parcial(res, a.salida)
    print(informe_cobertura(C.leer_csv(C.ARCHIVO_SITIOS), res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
