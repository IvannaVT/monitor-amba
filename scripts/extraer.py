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

# --------------------------------------------------------------------------
# Campos del portal -> columna de 04, tipo y sinónimos de etiqueta.
# La coincidencia es por igualdad de la etiqueta normalizada (sin tildes), no
# por subcadena, para no confundir p. ej. "transparencia" con "transparencia asap".
# --------------------------------------------------------------------------
CAMPOS_PORTAL: dict[str, dict] = {
    "indice_global": dict(tipo="num", sin=["indice municipal general", "indice general", "indice municipal", "indice global", "puntaje general"]),
    "ranking_provincial": dict(tipo="int", sin=["ranking provincial", "posicion provincial", "ranking en la provincia"]),
    "ranking_pares": dict(tipo="int", sin=["ranking por grupo", "ranking grupo comparable", "ranking en el grupo", "ranking pares"]),
    "grupo_comparacion": dict(tipo="txt", sin=["grupo de comparacion", "grupo comparable", "grupo de pares"]),
    "transparencia_puntaje": dict(tipo="num", sin=["transparencia", "pilar transparencia", "puntaje transparencia"]),
    "transparencia_relevamiento_propio": dict(tipo="num", sin=["relevamiento propio", "transparencia activa", "relevamiento propio de transparencia activa"]),
    "transparencia_asap": dict(tipo="num", sin=["indice de transparencia fiscal asap", "transparencia fiscal asap", "asap", "itf asap"]),
    "transparencia_semaforo": dict(tipo="semaforo", sin=["semaforo de transparencia", "semaforo", "transparencia semaforo"]),
    "presupuesto_publicado": dict(tipo="bool", sin=["presupuesto publicado", "publica presupuesto", "publicacion del presupuesto"]),
    "ejecucion_publicada": dict(tipo="bool", sin=["ejecucion publicada", "ejecucion presupuestaria publicada", "publicacion de ejecucion presupuestaria"]),
    "servicios_seguridad_puntaje": dict(tipo="num", sin=["servicios y seguridad", "pilar servicios y seguridad"]),
    "seguridad_puntaje": dict(tipo="num", sin=["seguridad", "puntaje seguridad", "puntaje de seguridad", "seguridad puntaje"]),
    "homicidios_tasa_100k": dict(tipo="num", sin=["tasa de homicidios dolosos", "tasa de homicidios", "homicidios por 100 000 habitantes", "homicidios cada 100 000 habitantes"]),
    "homicidios_periodo": dict(tipo="txt", sin=["periodo de la tasa de homicidios", "periodo homicidios"]),
    "victimas_homicidio_ultimo_anio": dict(tipo="int", sin=["victimas de homicidio", "victimas homicidios", "victimas ultimo anio"]),
    "victimas_homicidio_anio": dict(tipo="int", sin=["anio de las victimas", "anio victimas homicidio"]),
    "cobertura_agua_pct": dict(tipo="num", sin=["cobertura de agua de red", "agua de red", "cobertura de agua"]),
    "cobertura_cloacas_pct": dict(tipo="num", sin=["cobertura de cloacas", "cloacas"]),
    "cobertura_gas_pct": dict(tipo="num", sin=["cobertura de gas de red", "gas de red", "cobertura de gas"]),
    "control_puntaje": dict(tipo="num", sin=["control externo y judicial", "control", "pilar control", "puntaje control"]),
    "ultimo_fallo_htc": dict(tipo="txt", sin=["ultimo fallo del htc", "ultimo fallo htc", "ultimo fallo del tribunal de cuentas"]),
    "ejercicio_fallo_htc": dict(tipo="txt", sin=["ejercicio del ultimo fallo", "ejercicio fallo htc", "ultimo ejercicio auditado"]),
    "señales_control": dict(tipo="int", sin=["senales de control", "senales"]),
    "cargos_htc_monto": dict(tipo="num", sin=["cargos htc", "cargos patrimoniales", "monto de cargos"]),
    "multas_htc_monto": dict(tipo="num", sin=["multas htc", "multas", "monto de multas"]),
    "presupuesto_total": dict(tipo="num", sin=["presupuesto total", "presupuesto municipal total"]),
    "presupuesto_anio": dict(tipo="txt", sin=["anio del presupuesto", "ejercicio del presupuesto", "anio fiscal"]),
    "gasto_por_habitante": dict(tipo="num", sin=["gasto por habitante"]),
    "gasto_periodo": dict(tipo="txt", sin=["periodo del gasto"]),
    "empleados_municipales": dict(tipo="int", sin=["empleados municipales", "empleados ocupados", "personal ocupado"]),
    "tipo_dato_empleo": dict(tipo="txt", sin=["tipo de dato de empleo"]),
    "empleo_periodo": dict(tipo="txt", sin=["periodo del empleo", "periodo de empleo"]),
}
CAMPO_FECHA_PORTAL = ("fecha_actualizacion_portal", ["fecha de actualizacion", "actualizado", "ultima actualizacion"])

# Campos de 04 que se replican en 01 (misma columna).
CAMPOS_EN_01 = [
    "indice_global", "ranking_provincial", "transparencia_puntaje", "transparencia_semaforo",
    "servicios_seguridad_puntaje", "seguridad_puntaje", "control_puntaje",
]

_INDICE_ETIQUETAS: dict[str, str] = {}
for _campo, _d in CAMPOS_PORTAL.items():
    for _s in _d["sin"]:
        _INDICE_ETIQUETAS.setdefault(C.normalizar_texto(_s), _campo)


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


def _aplanar_json(o, clave: str = "") -> list[tuple[str, str]]:
    """Pares (clave de hoja, valor escalar) de un JSON; camelCase/snake_case -> palabras."""
    res: list[tuple[str, str]] = []
    if isinstance(o, dict):
        for k, v in o.items():
            res += _aplanar_json(v, str(k))
    elif isinstance(o, list):
        for v in o[:200]:
            res += _aplanar_json(v, clave)
    elif isinstance(o, (str, int, float, bool)) and clave and not isinstance(o, bool):
        res.append((re.sub(r"([a-z])([A-Z])", r"\1 \2", clave).replace("_", " "), str(o)))
    return res


def etiquetas_no_reconocidas(html: str, maximo: int = 15) -> list[str]:
    """Etiquetas de la ficha que no coinciden con ningún sinónimo (ayuda a ajustar CAMPOS_PORTAL)."""
    vistas: list[str] = []
    for et, _ in extraer_pares(html):
        n = C.normalizar_texto(et)
        if n and n not in _INDICE_ETIQUETAS and n not in {C.normalizar_texto(x) for x in CAMPO_FECHA_PORTAL[1]} \
                and et[:40] not in vistas and len(et) <= 60:
            vistas.append(et[:40])
    return vistas[:maximo]


def extraer_pares(html: str) -> list[tuple[str, str]]:
    """Pares (etiqueta, valor) desde tablas, listas de definición y 'Etiqueta: valor'."""
    soup = BeautifulSoup(html, "lxml")
    pares: list[tuple[str, str]] = []
    for sc in soup.find_all("script"):  # datos estructurados embebidos (solo se parsean como JSON)
        if (sc.get("type") or "").lower() in ("application/json", "application/ld+json") or sc.get("id") == "__NEXT_DATA__":
            try:
                pares += _aplanar_json(json.loads(sc.string or ""))
            except (ValueError, TypeError):
                pass
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    for tr in soup.find_all("tr"):
        celdas = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(celdas) >= 2 and celdas[0] and celdas[1]:
            pares.append((celdas[0], celdas[1]))
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            pares.append((dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)))
    for el in soup.find_all(["li", "p", "div", "span"]):
        if el.find(["li", "p", "div", "table"]):
            continue  # solo elementos hoja
        txt = el.get_text(" ", strip=True)
        if ":" in txt and len(txt) < 200:
            k, _, v = txt.partition(":")
            if k.strip() and v.strip():
                pares.append((k.strip(), v.strip()))
    return pares


def _semaforo(v: str) -> str | None:
    n = C.normalizar_texto(v)
    for k, out in (("verde", "VERDE"), ("amarillo", "AMARILLO"), ("rojo", "ROJO")):
        if re.search(rf"\b{k}\b", n):
            return out
    return None


def _bool(v: str) -> str | None:
    n = C.normalizar_texto(v)
    if n in ("si", "publicado", "publica", "true"):
        return "SI"
    if n in ("no", "no publicado", "no publica", "false"):
        return "NO"
    return None


_MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}


def parse_fecha(v: str) -> str | None:
    v = v.strip()
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", v):
        return m.group(0)
    if m := re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    n = C.normalizar_texto(v)
    if m := re.search(r"(\d{1,2}) de (\w+) de (\d{4})", n):
        if m.group(2) in _MESES:
            return f"{m.group(3)}-{_MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def convertir(tipo: str, valor: str):
    """Valor de texto -> valor normalizado, o None si no es interpretable."""
    if tipo == "num":
        return C.parse_num(re.sub(r"[^\d,.\-+]", "", valor.split("/")[0])) if re.search(r"\d", valor) else None
    if tipo == "int":
        m = re.search(r"\d[\d.]*", valor)
        n = C.parse_num(m.group(0)) if m else None
        return int(n) if n is not None else None
    if tipo == "semaforo":
        return _semaforo(valor)
    if tipo == "bool":
        return _bool(valor)
    return valor.strip() or None


def interpretar_pagina(html: str) -> tuple[dict[str, dict], list[dict]]:
    """Devuelve ({campo: {valor, original, etiqueta}}, contradicciones)."""
    hallados: dict[str, dict] = {}
    contradicciones: list[dict] = []
    fecha_et = {C.normalizar_texto(s) for s in CAMPO_FECHA_PORTAL[1]}
    for etiqueta, valor in extraer_pares(html):
        n = C.normalizar_texto(etiqueta)
        if n in fecha_et:
            campo, val = CAMPO_FECHA_PORTAL[0], parse_fecha(valor)
        else:
            campo = _INDICE_ETIQUETAS.get(n)
            val = convertir(CAMPOS_PORTAL[campo]["tipo"], valor) if campo else None
        if not campo or val is None:
            continue
        if campo in hallados:
            if hallados[campo]["valor"] != val:
                contradicciones.append({"campo": campo, "a": hallados[campo]["original"], "b": valor})
            continue
        hallados[campo] = {"valor": val, "original": valor.strip(), "etiqueta": etiqueta.strip()}
    return hallados, contradicciones


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


def procesar_municipio(cli: Cliente, cfg: dict, desc: Descubridor, fecha: str, snap: str) -> dict:
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

    hallados, contradicciones = interpretar_pagina(r.texto)
    fila04 = {"municipio_id": mid, "snapshot_id": snap, "fecha_extraccion": fecha, "url_fuente": url}
    for campo, d in hallados.items():
        fila04[campo] = d["valor"]
        out["fuentes"].append(_fuente(
            mid, "indicador_portal", campo, d["original"], url, fecha, snap, "html_etiqueta_valor", "MEDIO",
            obs=f"etiqueta='{d['etiqueta']}'; html_sha256={r.sha256[:16]}"))
    for c in contradicciones:
        out["incidencias"].append(_incidencia(
            mid, c["campo"], "CONTRADICCION_INTERNA",
            f"Valores distintos en la misma página: '{c['a']}' vs '{c['b']}'. Se conservó el primero.",
            url, fecha, snap, "MEDIO", "Revisar manualmente la página.", c["a"], c["b"]))
    for campo in CAMPOS_EN_01:
        if campo in fila04:
            fila01[campo] = fila04[campo]
    faltan = [c for c in CAMPOS_PORTAL if c not in hallados]
    n_hallados = len([c for c in hallados if c != "fecha_actualizacion_portal"])
    out["campos"] = n_hallados
    if faltan:
        out["incidencias"].append(_incidencia(
            mid, ";".join(faltan), "DATOS_NO_ENCONTRADOS",
            f"{len(faltan)} de {len(CAMPOS_PORTAL)} campos del portal no figuran en la página (quedan en blanco). "
            f"Faltantes: {', '.join(faltan)}. Etiquetas no reconocidas en la ficha: "
            f"{'; '.join(etiquetas_no_reconocidas(r.texto)) or 'ninguna'}.",
            url, fecha, snap, "BAJO" if n_hallados else "ALTO",
            "Verificar si el portal los publica con otra etiqueta; ajustar sinónimos en CAMPOS_PORTAL.", url))
    if n_hallados:
        out["indicadores"] = fila04
        out["estado"] = "PARCIAL" if faltan else "COMPLETO"
    return out


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
             dir_actual: Path | None = None, dir_historico: Path | None = None, cfg_path: Path | None = None) -> dict:
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
    resultados = [procesar_municipio(cli, c, desc, fecha, snap) for c in sel]
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
    ap.add_argument("--registrar-bloqueo", metavar="DETALLE", default=None,
                    help="no consulta la red: registra incidencias de acceso bloqueado con este detalle")
    a = ap.parse_args(argv)
    cli = ClienteBloqueado(a.registrar_bloqueo) if a.registrar_bloqueo else None
    res = ejecutar(a.municipios, a.fecha, a.pausa, cliente=cli)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if a.informe_ejecucion:
        a.informe_ejecucion.write_text(informe_ejecucion(res), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
