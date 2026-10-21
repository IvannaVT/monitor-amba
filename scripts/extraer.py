#!/usr/bin/env python3
"""Extractor MONITOR AMBA (Fase 1): municipiosargentinos.net -> 8 CSV.

Principios (spec sec. 15 y 25):
- Respeta robots.txt (si no se puede verificar, NO se consulta: falla cerrada).
- Límite de solicitudes; ante 403/429/bloqueos no se reintenta ni se elude.
- No deduce rutas por patrón: se usa `url_portal_municipio` (config) y, como respaldo, los
  enlaces de la portada.
- Nunca inventa datos: lo que no se encuentra queda en blanco + incidencia.
- Todo valor extraído genera una fila de trazabilidad en 05_amba_fuentes.csv.
- No ejecuta nada de lo que contengan las páginas (solo se lee texto).

Uso:
    python scripts/extraer.py --municipios avellaneda,vicente_lopez,tres_de_febrero
    python scripts/extraer.py --municipios todos
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

BASE_URL = "https://municipiosargentinos.net/"
URL_METODOLOGIA = BASE_URL + "metodologia/"
USER_AGENT = (
    "MonitorAMBA/0.1 (+https://github.com/IvannaVT/monitor-amba; "
    "relevamiento de datos publicos; sin evasion de restricciones)"
)

from parser_ficha import (  # noqa: E402  (parser de fichas: campos, reglas y análisis)
    CAMPOS_EN_01, CAMPOS_FICHA_01, CAMPOS_PORTAL, CAMPO_FECHA_PORTAL, analizar_ficha, estructura_texto,
    etiquetas_no_reconocidas, interpretar_pagina, parse_fecha,
)

# ------------------------------------------------------------------ cliente
def url_segura(url: str) -> str:
    """URL sin credenciales, query ni fragmento (para registrar sin datos sensibles)."""
    p = urlparse(url or "")
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    return urlunparse((p.scheme, host, p.path, "", "", ""))


@dataclass
class Respuesta:
    url: str
    ok: bool
    status: int | None = None
    texto: str = ""
    tipo_error: str = ""
    detalle: str = ""
    url_final: str = ""
    redirecciones: tuple = ()  # ((codigo, url_destino), ...) ya saneadas

    @property
    def pagina_ausente(self) -> bool:
        return self.status in (404, 410)

    def diagnostico(self) -> str:
        """Resumen registrable: código HTTP, URL final, redirecciones y causa."""
        red = " -> ".join(f"{c} {u}" for c, u in self.redirecciones) or "sin redirecciones"
        return (f"HTTP {self.status if self.status is not None else 'sin respuesta'}; "
                f"url_final={url_segura(self.url_final or self.url)}; redirecciones: {red}; "
                f"causa: {self.detalle or self.tipo_error or 'n/a'}")

    @property
    def sha256(self) -> str:
        return C.sha256_texto(self.texto) if self.texto else ""


class Cliente:
    """HTTP cortés: robots.txt obligatorio, pausa entre solicitudes, sin evasión."""

    def __init__(self, pausa: float = 2.0, timeout: float = 30.0, session=None, user_agent: str = USER_AGENT):
        self.pausa = pausa
        self.timeout = timeout
        self.s = session or requests.Session()
        self.ua = user_agent
        self.s.headers.update({"User-Agent": user_agent, "Accept-Language": "es-AR,es;q=0.9"})
        self._robots: dict[str, tuple[robotparser.RobotFileParser | None, str]] = {}
        self._ultimo = 0.0
        self.n_solicitudes = 0
        self.eventos: list[dict] = []

    def _esperar(self, extra: float = 0.0) -> None:
        espera = max(self.pausa, extra) - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo = time.monotonic()

    @staticmethod
    def _clasificar(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, requests.exceptions.ProxyError):
            return "ACCESO_BLOQUEADO_RED", f"Proxy/red del entorno rechazó la conexión: {str(exc)[:200]}"
        if isinstance(exc, requests.exceptions.SSLError):
            return "ERROR_TLS", str(exc)[:200]
        if isinstance(exc, requests.exceptions.Timeout):
            return "TIMEOUT", str(exc)[:200]
        return "ERROR_CONEXION", str(exc)[:200]

    def _robots_de(self, url: str):
        p = urlparse(url)
        origen = f"{p.scheme}://{p.netloc}"
        if origen in self._robots:
            return self._robots[origen]
        ru = origen + "/robots.txt"
        rp: robotparser.RobotFileParser | None = None
        motivo = ""
        try:
            self._esperar()
            self.n_solicitudes += 1
            r = self.s.get(ru, timeout=self.timeout)
            if r.status_code == 200:
                rp = robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
            elif r.status_code in (404, 410):
                rp = robotparser.RobotFileParser()
                rp.parse([])  # sin robots.txt: sin restricciones declaradas
            else:
                motivo = f"robots.txt respondió HTTP {r.status_code}; no verificable"
        except requests.exceptions.RequestException as exc:
            tipo, det = self._clasificar(exc)
            motivo = f"robots.txt inaccesible ({tipo}): {det}"
        self._robots[origen] = (rp, motivo)
        return self._robots[origen]

    def get(self, url: str) -> Respuesta:
        r = self._get(url)
        self.eventos.append({"url": url_segura(url), "status": r.status, "ok": r.ok, "tipo_error": r.tipo_error})
        return r

    def _get(self, url: str) -> Respuesta:
        rp, motivo = self._robots_de(url)
        if rp is None:
            return Respuesta(url, False, tipo_error="ROBOTS_NO_VERIFICABLE", detalle=motivo)
        if not rp.can_fetch(self.ua, url):
            return Respuesta(url, False, tipo_error="PROHIBIDO_POR_ROBOTS", detalle="robots.txt no permite esta ruta")
        delay = rp.crawl_delay(self.ua) or rp.crawl_delay("*") or 0
        try:
            self._esperar(float(delay))
            self.n_solicitudes += 1
            r = self.s.get(url, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            tipo, det = self._clasificar(exc)
            return Respuesta(url, False, tipo_error=tipo, detalle=det)
        final = url_segura(getattr(r, "url", "") or url)
        saltos = tuple((h.status_code, url_segura(getattr(h, "headers", {}).get("Location", "") or h.url))
                       for h in (getattr(r, "history", None) or ()))
        base = dict(url_final=final, redirecciones=saltos)
        if urlparse(final).netloc != urlparse(url).netloc:
            return Respuesta(url, False, r.status_code, tipo_error="REDIRECCION_EXTERNA",
                             detalle="redirige a otro dominio; no se sigue", **base)
        if final != url_segura(url) and not rp.can_fetch(self.ua, final):
            return Respuesta(url, False, r.status_code, tipo_error="PROHIBIDO_POR_ROBOTS",
                             detalle="la URL final tras redirección no está permitida por robots.txt", **base)
        if r.status_code == 429:
            return Respuesta(url, False, 429, tipo_error="LIMITE_SOLICITUDES_429",
                             detalle="HTTP 429; no se reintenta ni se eluden límites", **base)
        if r.status_code in (401, 403):
            return Respuesta(url, False, r.status_code, tipo_error="ACCESO_DENEGADO_HTTP",
                             detalle=f"HTTP {r.status_code}; no se eluden restricciones", **base)
        if r.status_code in (404, 410):
            return Respuesta(url, False, r.status_code, tipo_error="PAGINA_AUSENTE",
                             detalle=f"HTTP {r.status_code}: la página no existe", **base)
        if r.status_code >= 400:
            return Respuesta(url, False, r.status_code, tipo_error="ERROR_HTTP",
                             detalle=f"HTTP {r.status_code}", **base)
        r.encoding = r.encoding or r.apparent_encoding or "utf-8"
        if not (r.text or "").strip():
            return Respuesta(url, False, r.status_code, tipo_error="RESPUESTA_VACIA",
                             detalle="HTTP 200 sin contenido", **base)
        return Respuesta(url, True, r.status_code, texto=r.text, **base)


class ClienteBloqueado:
    """Registra un bloqueo ya comprobado SIN realizar ninguna solicitud de red."""

    n_solicitudes = 0

    def __init__(self, detalle: str):
        self.detalle = detalle
        self.eventos: list[dict] = []

    def get(self, url: str) -> Respuesta:
        self.eventos.append({"url": url_segura(url), "status": None, "ok": False, "tipo_error": "ACCESO_BLOQUEADO_RED"})
        return Respuesta(url, False, tipo_error="ACCESO_BLOQUEADO_RED", detalle=self.detalle)


# ------------------------------------------------------------------ parsers
def descubrir_enlaces(html: str, base: str) -> list[tuple[str, str]]:
    """Enlaces (texto, url absoluta) de una página, solo del mismo host."""
    soup = BeautifulSoup(html, "lxml")
    host = urlparse(base).netloc
    vistos, res = set(), []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if urlparse(url).netloc != host or url in vistos:
            continue
        vistos.add(url)
        res.append((a.get_text(" ", strip=True), url))
    # Rutas de ficha /m/<slug>/ que aparezcan en el HTML/JSON crudo (listados generados por script).
    # Solo se leen como texto; nunca se ejecuta nada.
    for m in re.finditer(r'(?:https?://[^"\'\s<>]*?)?(/m/[a-z0-9][a-z0-9\-]*/?)(?=["\'\s<>?#\\])', html):
        url = urljoin(base, m.group(1))
        if urlparse(url).netloc == host and url not in vistos:
            vistos.add(url)
            res.append(("", url))
    return res


def encontrar_pagina_municipio(enlaces: list[tuple[str, str]], nombre: str) -> tuple[str | None, str]:
    """Busca el enlace del municipio por igualdad exacta (texto o último tramo de la ruta)."""
    objetivo = C.normalizar_texto(nombre)
    candidatos: dict[str, None] = {}
    for texto, url in enlaces:
        ultimo = urlparse(url).path.rstrip("/").split("/")[-1]
        if C.normalizar_texto(texto) == objetivo or C.normalizar_texto(ultimo) == objetivo:
            candidatos[url] = None
    if len(candidatos) == 1:
        return next(iter(candidatos)), ""
    if not candidatos:
        return None, "sin enlace con nombre exacto en el portal"
    return None, "enlaces ambiguos: " + " | ".join(candidatos)


def verificar_metodologia(html: str) -> dict:
    """Busca en el texto publicado las ponderaciones y el tope esperados (spec sec. 6)."""
    t = C.normalizar_texto(BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    ponderaciones = {
        "transparencia_50": bool(re.search(r"transparencia[^.]{0,80}\b50\b", t)),
        "servicios_seguridad_35": bool(re.search(r"servicios[^.]{0,40}seguridad[^.]{0,80}\b35\b", t)),
        "control_15": bool(re.search(r"control[^.]{0,80}\b15\b", t)),
        "tope_40_puntos": bool(re.search(r"\b40\b[^.]{0,20}puntos|puntos[^.]{0,60}\b40\b", t)),
    }
    return {"hash": C.sha256_texto(t), "ponderaciones": ponderaciones}


# --------------------------------------------------------- armado de filas
def _fuente(mid, entidad, campo, valor, url, fecha, snap, metodo, confianza, obs="", periodo="", titulo="", fecha_doc=""):
    return {
        "fuente_id": C.id_estable(mid, entidad, campo, valor, url),
        "municipio_id": mid, "entidad": entidad, "campo_verificado": campo,
        "valor_obtenido": valor, "fuente_tipo": "PORTAL_AGREGADOR_TERCERO",
        "organismo": "Municipios Argentinos", "documento_titulo": titulo,
        "documento_url": url, "fecha_documento": fecha_doc, "periodo_referencia": periodo,
        "fecha_consulta": fecha, "metodo_extraccion": metodo, "nivel_confianza": confianza,
        "observaciones": obs, "snapshot_id": snap,
    }


def _incidencia(mid, campo, tipo, desc, url, fecha, snap, impacto="MEDIO", accion="", f1="", f2=""):
    return {
        "incidencia_id": C.id_estable(mid, campo, tipo, url),
        "municipio_id": mid, "campo": campo, "tipo_incidencia": tipo, "descripcion": desc,
        "url_afectada": url, "fuente_1": f1, "fuente_2": f2, "impacto": impacto,
        "accion_recomendada": accion, "estado_resolucion": "ABIERTA",
        "fecha_deteccion": fecha, "fecha_ultima_revision": fecha, "snapshot_id": snap,
    }


ACCION_POR_TIPO = {
    "ACCESO_BLOQUEADO_RED": "Habilitar el dominio en la política de red del entorno o ejecutar desde GitHub Actions.",
    "ROBOTS_NO_VERIFICABLE": "Reintentar cuando robots.txt sea accesible; no se consulta sin verificarlo.",
    "PROHIBIDO_POR_ROBOTS": "No consultar la ruta; buscar fuente alternativa permitida.",
    "ACCESO_DENEGADO_HTTP": "No eludir; buscar fuente alternativa o solicitar autorización al titular del portal.",
    "LIMITE_SOLICITUDES_429": "Aumentar la pausa entre solicitudes y reintentar en otra ejecución.",
}


class Descubridor:
    """Descubre enlaces de la portada solo si hace falta (una única consulta por ejecución)."""

    def __init__(self, cli):
        self.cli, self._hecho, self.enlaces, self.error = cli, False, [], None

    def resolver(self, nombre: str) -> tuple[str | None, Respuesta | None, str]:
        if not self._hecho:
            self._hecho = True
            rp = self.cli.get(BASE_URL)
            if rp.ok:
                self.enlaces = descubrir_enlaces(rp.texto, BASE_URL)
            else:
                self.error = rp
        if self.error is not None:
            return None, self.error, ""
        url, motivo = encontrar_pagina_municipio(self.enlaces, nombre)
        return url, None, motivo


def _inc_respuesta(mid, r: Respuesta, fecha, snap, campo="pagina_municipio"):
    """Incidencia fiel a la causa real; PAGINA_NO_ENCONTRADA solo para 404/410."""
    tipo = "PAGINA_AUSENTE" if r.pagina_ausente else r.tipo_error
    impacto = "ALTO"
    return _incidencia(mid, campo, tipo, r.diagnostico(), url_segura(r.url), fecha, snap, impacto,
                       ACCION_POR_TIPO.get(tipo, "Revisar la URL configurada o reintentar en otra ejecución."),
                       url_segura(r.url), url_segura(r.url_final or ""))


def procesar_municipio(cli: Cliente, cfg: dict, desc: Descubridor, fecha: str, snap: str, dir_diag: Path | None = None) -> dict:
    """Prioridad: URL configurada. El descubrimiento por portada es respaldo (si no hay URL o da 404/410)."""
    mid, nombre = cfg["municipio_id"], cfg["municipio"]
    out = {"indicadores": None, "municipio": None, "fuentes": [], "incidencias": [], "estado": "SIN_DATOS",
           "campos": 0, "url_origen": "", "http": None}
    fila01 = {"municipio_id": mid, "municipio": nombre, "seccion_electoral": cfg.get("seccion_electoral", ""),
              "fecha_verificacion": fecha, "snapshot_id": snap}
    out["municipio"] = fila01

    r, url = None, (cfg.get("url_portal_municipio") or "").strip()
    fallida = ""
    if url:
        out["url_origen"] = "configurada"
        r = cli.get(url)
        if not r.ok and not r.pagina_ausente:  # 403/429/red/robots: no se busca otra ruta
            out["http"] = r.status
            out["incidencias"].append(_inc_respuesta(mid, r, fecha, snap))
            return out
        if not r.ok:  # página ausente: se intenta el respaldo
            out["incidencias"].append(_inc_respuesta(mid, r, fecha, snap))
            fallida, url, r = url_segura(url), "", None
    if not url:
        out["url_origen"] = "descubierta"
        url, err, motivo = desc.resolver(nombre)
        if err is not None:
            out["incidencias"].append(_inc_respuesta(mid, err, fecha, snap, "portada"))
            return out
        if not url:
            out["incidencias"].append(_incidencia(
                mid, "pagina_municipio", "PAGINA_NO_ENCONTRADA",
                f"La portada respondió correctamente pero {motivo}.", BASE_URL, fecha, snap, "ALTO",
                "Completar url_portal_municipio en config/municipios_amba.csv tras revisión manual.", BASE_URL))
            return out
        if fallida and url_segura(url) == fallida:  # el respaldo apunta a la misma URL ya ausente
            return out
        r = cli.get(url)
    out["http"] = r.status
    if not r.ok:
        out["incidencias"].append(_inc_respuesta(mid, r, fecha, snap))
        return out
    url = url_segura(r.url_final or url)

    if dir_diag is not None:
        volcar_diagnostico(dir_diag, mid, r.texto)
    an = analizar_ficha(r.texto)
    hallados, contradicciones = an["hallados"], an["contradicciones"]
    fila04 = {"municipio_id": mid, "snapshot_id": snap, "fecha_extraccion": fecha, "url_fuente": url}
    for campo, d in hallados.items():
        en_01 = campo in CAMPOS_FICHA_01
        if en_01:
            if campo != "seccion_electoral" or not fila01.get("seccion_electoral"):
                fila01[campo] = d["valor"]
        else:
            fila04[campo] = d["valor"]
        obs = f"etiqueta='{d['etiqueta']}'; seccion='{d['seccion']}'; html_sha256={r.sha256[:16]}"
        if en_01 and campo != "poblacion_2022" and campo != "seccion_electoral":
            obs += "; dato político tomado del portal, pendiente de verificación en fuente oficial"
        if d.get("obs"):
            obs += "; " + d["obs"]
        out["fuentes"].append(_fuente(
            mid, "municipio_portal" if en_01 else "indicador_portal", campo, d["original"], url, fecha, snap,
            "html_secciones_etiqueta_valor", d.get("confianza", "MEDIO"), obs=obs))
    for c in contradicciones:
        out["incidencias"].append(_incidencia(
            mid, c["campo"], "CONTRADICCION_INTERNA",
            f"Valores distintos en la misma página: '{c['a']}' ({c['seccion_a']}) vs '{c['b']}' ({c['seccion_b']}). "
            "Se conservó el primero.", url, fecha, snap, "MEDIO", "Revisar manualmente la página.", c["a"], c["b"]))
    for campo in CAMPOS_EN_01:
        if campo in fila04:
            fila01[campo] = fila04[campo]
    faltan = [c for c in CAMPOS_PORTAL if c not in hallados]
    faltan_01 = [c for c in CAMPOS_FICHA_01 if c not in hallados and c != "coalicion_actual"]
    n_hallados = len([c for c in hallados if c != "fecha_actualizacion_portal"])
    out["campos"] = n_hallados
    if faltan or faltan_01:
        def lista(xs, m):
            return "; ".join(xs[:m]) + (f"; ... (+{len(xs) - m})" if len(xs) > m else "") or "ninguna"
        out["incidencias"].append(_incidencia(
            mid, ";".join(faltan + faltan_01), "DATOS_NO_ENCONTRADOS",
            f"Indicadores sin dato: {len(faltan)} de {len(CAMPOS_PORTAL)} ({', '.join(faltan)}). "
            f"Ficha (01) sin dato: {', '.join(faltan_01) or 'ninguno'}. "
            f"Secciones vistas: {lista(an['secciones'], 12)}. "
            f"Etiquetas no reconocidas [sección > etiqueta = valor]: {lista(an['no_reconocidas'], 25)}. "
            f"Valores rechazados: {lista(an['rechazados'], 15)}.",
            url, fecha, snap, "BAJO" if n_hallados else "ALTO",
            "Ajustar reglas en scripts/parser_ficha.py usando la captura diagnostico/ de la ejecución.", url))
    if any(c in fila04 for c in CAMPOS_PORTAL) or "fecha_actualizacion_portal" in fila04:
        out["indicadores"] = fila04
    if n_hallados:
        out["estado"] = "PARCIAL" if (faltan or faltan_01) else "COMPLETO"
    return out


def volcar_diagnostico(dir_diag: Path, mid: str, html: str) -> None:
    """Captura para depurar el parser: HTML público (acotado) y su estructura por secciones."""
    dir_diag.mkdir(parents=True, exist_ok=True)
    (dir_diag / f"{mid}.html").write_text(html[:1_500_000], encoding="utf-8")
    (dir_diag / f"{mid}_estructura.txt").write_text(estructura_texto(html), encoding="utf-8")


def seleccionar(cfg_all: list[dict], pedido: str) -> list[dict]:
    if pedido.strip().lower() == "todos":
        return cfg_all
    quiero = [x.strip() for x in pedido.split(",") if x.strip()]
    res = []
    for q in quiero:
        qn = C.slug(q).removeprefix("ba_")
        m = [c for c in cfg_all if c["municipio_id"] == f"ba_{qn}"]
        if not m:
            raise SystemExit(f"Municipio no reconocido: '{q}'")
        res.append(m[0])
    return res


def ejecutar(municipios: str, fecha: str | None = None, pausa: float = 2.0, cliente: Cliente | None = None,
             dir_actual: Path | None = None, dir_historico: Path | None = None, cfg_path: Path | None = None,
             dir_diagnostico: Path | None = None) -> dict:
    import normalizar as N
    ahora = C.ahora_utc()
    fecha = fecha or ahora.strftime("%Y-%m-%d")
    snap = C.snapshot_desde(ahora)
    cfg_all = C.cargar_municipios_cfg(cfg_path or C.ARCHIVO_MUNICIPIOS_CFG)
    sel = seleccionar(cfg_all, municipios)
    cli = cliente or Cliente(pausa=pausa)

    desc = Descubridor(cli)

    # 2) Metodología (una vez por ejecución).
    fuentes_extra, incid_extra = [], []
    rm = cli.get(URL_METODOLOGIA)
    if rm.ok:
        met = verificar_metodologia(rm.texto)
        fuentes_extra.append(_fuente("GLOBAL", "metodologia", "metodologia_hash", met["hash"], URL_METODOLOGIA,
                                     fecha, snap, "hash_texto_normalizado", "MEDIO",
                                     obs="Huella del texto de la metodología (detecta cambios metodológicos)."))
        for k, ok in met["ponderaciones"].items():
            fuentes_extra.append(_fuente("GLOBAL", "metodologia", k, "CONFIRMADO" if ok else "NO_CONFIRMADO",
                                         URL_METODOLOGIA, fecha, snap, "regex_texto", "BAJO",
                                         obs="Verificación textual heurística; confirmar a mano."))
            if not ok:
                incid_extra.append(_incidencia(
                    "GLOBAL", k, "METODOLOGIA_NO_CONFIRMADA",
                    f"No se halló en la página de metodología el texto esperado para '{k}'.",
                    URL_METODOLOGIA, fecha, snap, "MEDIO", "Revisar manualmente la metodología publicada.", URL_METODOLOGIA))
    else:
        incid_extra.append(_inc_respuesta("GLOBAL", rm, fecha, snap, "metodologia"))

    # 3) Municipios.
    resultados = [procesar_municipio(cli, c, desc, fecha, snap, dir_diagnostico) for c in sel]
    resumen = N.aplicar(resultados, fuentes_extra, incid_extra, fecha, snap,
                        ids_procesados=[c["municipio_id"] for c in sel],
                        dir_actual=dir_actual or C.DIR_ACTUAL, dir_historico=dir_historico or C.DIR_HISTORICO)
    ev = getattr(cli, "eventos", [])
    bloqueos = {"ACCESO_DENEGADO_HTTP", "LIMITE_SOLICITUDES_429", "PROHIBIDO_POR_ROBOTS", "ROBOTS_NO_VERIFICABLE",
                "ACCESO_BLOQUEADO_RED", "REDIRECCION_EXTERNA"}
    resumen.update({
        "snapshot_id": snap, "fecha": fecha, "solicitudes_http": cli.n_solicitudes,
        "solicitudes_exitosas": sum(1 for e in ev if e["ok"]),
        "respuestas_bloqueadas": sum(1 for e in ev if e["tipo_error"] in bloqueos),
        "paginas_ausentes": sum(1 for e in ev if e["tipo_error"] == "PAGINA_AUSENTE"),
        "otros_errores": sum(1 for e in ev if not e["ok"] and e["tipo_error"] not in bloqueos | {"PAGINA_AUSENTE"}),
        "municipios_con_datos": sum(1 for r in resultados if r["campos"] > 0),
        "detalle_solicitudes": ev,
        "municipios": {r["municipio"]["municipio"]: {
            "estado": r["estado"], "campos_extraidos": r["campos"], "http": r["http"], "url_origen": r["url_origen"],
            "incidencias": sorted({i["tipo_incidencia"] for i in r["incidencias"]})} for r in resultados},
    })
    return resumen


def informe_ejecucion(res: dict) -> str:
    """Informe Markdown de la ejecución (separa éxito, bloqueo, ausencia y datos extraídos)."""
    l = [f"# Informe de ejecución {res['fecha']} (`{res['snapshot_id']}`)\n",
         "| Concepto | Cantidad |", "|---|---|",
         f"| Solicitudes a páginas con éxito | {res['solicitudes_exitosas']} |",
         f"| Respuestas bloqueadas o restringidas (403/429/robots/red) | {res['respuestas_bloqueadas']} |",
         f"| Páginas ausentes (404/410) | {res['paginas_ausentes']} |",
         f"| Otros errores | {res['otros_errores']} |",
         f"| Municipios con datos efectivamente extraídos | {res['municipios_con_datos']} de {len(res['municipios'])} |",
         f"| Solicitudes HTTP totales (incluye robots.txt) | {res['solicitudes_http']} |", "",
         "## Por municipio\n", "| Municipio | Estado | Campos | HTTP | Origen URL | Incidencias |", "|---|---|---|---|---|---|"]
    for n, m in res["municipios"].items():
        l.append(f"| {n} | {m['estado']} | {m['campos_extraidos']} | {m['http'] or ''} | {m['url_origen']} | "
                 f"{', '.join(m['incidencias']) or '-'} |")
    return "\n".join(l) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--municipios", default="avellaneda,vicente_lopez,tres_de_febrero",
                    help="ids/nombres separados por coma, o 'todos'")
    ap.add_argument("--fecha", default=None, help="AAAA-MM-DD (por defecto, hoy UTC)")
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos mínimos entre solicitudes")
    ap.add_argument("--informe-ejecucion", type=Path, default=None, help="escribe el informe de la ejecución en Markdown")
    ap.add_argument("--diagnostico", type=Path, default=None, help="carpeta donde guardar el HTML y la estructura de cada ficha leída")
    ap.add_argument("--registrar-bloqueo", metavar="DETALLE", default=None,
                    help="no consulta la red: registra incidencias de acceso bloqueado con este detalle")
    a = ap.parse_args(argv)
    cli = ClienteBloqueado(a.registrar_bloqueo) if a.registrar_bloqueo else None
    res = ejecutar(a.municipios, a.fecha, a.pausa, cliente=cli, dir_diagnostico=a.diagnostico)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.informe_ejecucion:
        a.informe_ejecucion.write_text(informe_ejecucion(res), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
