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
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import contactos_parser as CP  # noqa: E402
import detectar_cambios as D  # noqa: E402
import extraer as E  # noqa: E402
import normalizar as N  # noqa: E402

SITIOS = C.ARCHIVO_SITIOS
# Muestra intermedia (8): los 3 del piloto + 5 grandes del conurbano. El resto se amplía con `completo`.
MUESTRA_INTERMEDIA = ["ba_avellaneda", "ba_vicente_lopez", "ba_tres_de_febrero", "ba_lanus", "ba_lomas_de_zamora", "ba_quilmes",
                      "ba_moron", "ba_san_isidro"]


def seleccionar(cfg_all: list[dict], pedido: str) -> list[dict]:
    """'intermedia' = muestra de 8; 'todos' = los 40; o una lista de ids/nombres separados por coma."""
    if pedido.strip().lower() == "intermedia":
        return [c for c in cfg_all if c["municipio_id"] in MUESTRA_INTERMEDIA]
    if pedido.strip().lower() in ("candidatos", "pendientes", "documentados"):       # solo verificación/identificación de sitios
        estado = {"candidatos": "CANDIDATO_A_VERIFICAR", "pendientes": "SIN_CONFIGURAR", "documentados": "OFICIAL_DOCUMENTADO"}[pedido.strip().lower()]
        ids = {m for m, s in cargar_sitios().items() if s.get("estado") == estado}
        return [c for c in cfg_all if c["municipio_id"] in ids]
    return E.seleccionar(cfg_all, pedido)
MAX_PAGINAS, MAX_PAGINAS_HCD = 12, 6
CAMPOS_CANAL = ["responsable_nombre", "responsable_apellido", "responsable_nombre_completo", "cargo", "email_institucional",
                "telefono_institucional", "interno", "direccion", "horario_atencion", "sitio_web", "url_fuente", "evidencia"]


REDIRECCIONES = (301, 302, 303, 307, 308)
MAX_SALTOS = 5
# Plazos por defecto (segundos). Ninguna operación de red puede superar PLAZO_SOLICITUD, haya o no respuesta parcial.
PLAZO_CONEXION, PLAZO_LECTURA, PLAZO_SOLICITUD = 8.0, 15.0, 30.0
MAX_ESPERA_CRAWL = 10.0        # un Crawl-delay mayor se respeta NO consultando el dominio (no se duerme horas)
MAX_PAGINAS_DOMINIO = 6        # páginas (sin contar robots.txt) por dominio y por municipio


def _mismo_dominio(a: str, b: str) -> bool:
    """www/apex/subdominio del mismo dominio (no cambia de titular)."""
    a, b = CP.dominio_base(a or ""), CP.dominio_base(b or "")
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


class ClienteContactos(E.Cliente):
    """Cliente que sigue las redirecciones a mano.

    - robots.txt y el certificado TLS se verifican en CADA salto (nunca se solicita un destino sin comprobarlo antes).
    - Una redirección no es un error por sí misma: se acepta si el destino es del mismo dominio (www/apex/subdominio,
      http->https) o de un dominio verificado como oficial para ese municipio (`hosts_ok`, salido de la configuración).
    - Cualquier otro destino (p. ej. el mismo nombre en otra provincia) se rechaza con REDIRECCION_EXTERNA sin solicitarlo.
    """

    def __init__(self, *a, plazo_solicitud: float = PLAZO_SOLICITUD, max_espera_crawl: float = MAX_ESPERA_CRAWL,
                 max_paginas_dominio: int = MAX_PAGINAS_DOMINIO, **kw):
        super().__init__(*a, **kw)
        self.plazo_solicitud, self.max_espera_crawl, self.max_paginas_dominio = plazo_solicitud, max_espera_crawl, max_paginas_dominio
        self.timeout = (min(PLAZO_CONEXION, plazo_solicitud), min(PLAZO_LECTURA, plazo_solicitud))
        self.fin_global: float | None = None          # instante (time.monotonic) tope de toda la ejecución
        self.fin_municipio: float | None = None
        self.max_solicitudes_municipio: int | None = None
        self._n0, self._paginas = 0, {}

    def iniciar_municipio(self, plazo: float | None = None, max_solicitudes: int | None = None) -> None:
        self.fin_municipio = time.monotonic() + plazo if plazo else None
        self.max_solicitudes_municipio, self._n0, self._paginas = max_solicitudes, self.n_solicitudes, {}

    def presupuesto_agotado(self) -> str:
        """Devuelve '' si se puede seguir, o el tipo de error que corresponde."""
        ahora = time.monotonic()
        if self.fin_global is not None and ahora >= self.fin_global:
            return "PLAZO_TOTAL_AGOTADO"
        if self.fin_municipio is not None and ahora >= self.fin_municipio:
            return "TIMEOUT_MUNICIPIO"
        if self.max_solicitudes_municipio is not None and self.n_solicitudes - self._n0 >= self.max_solicitudes_municipio:
            return "LIMITE_SOLICITUDES_MUNICIPIO"
        return ""

    def _plazo_efectivo(self) -> float:
        topes = [self.plazo_solicitud] + [f - time.monotonic() for f in (self.fin_global, self.fin_municipio) if f is not None]
        return max(0.1, min(topes))

    def _pedir(self, url: str, allow_redirects: bool):
        """GET con tope de tiempo TOTAL (conexión + cabeceras + cuerpo), no solo por lectura: corre en un hilo daemon y se abandona al vencer."""
        caja: dict = {}

        def trabajo():
            try:
                caja["r"] = self.s.get(url, timeout=self.timeout, allow_redirects=allow_redirects)   # TLS se verifica
            except BaseException as exc:  # noqa: BLE001 - se reenvía al hilo principal
                caja["exc"] = exc
        h = threading.Thread(target=trabajo, daemon=True)
        h.start()
        h.join(self._plazo_efectivo())
        if h.is_alive():
            raise requests.exceptions.Timeout(f"sin respuesta completa en {self._plazo_efectivo():.0f} s (tope total por solicitud)")
        if "exc" in caja:
            raise caja["exc"]
        return caja["r"]

    def _robots_de(self, url: str):
        p = urlparse(url)
        origen = f"{p.scheme}://{p.netloc}"
        if origen in self._robots:
            return self._robots[origen]
        rp, motivo = None, ""
        try:
            self._esperar()
            self.n_solicitudes += 1
            r = self._pedir(origen + "/robots.txt", True)
            if r.status_code == 200:
                rp = E.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
            elif r.status_code in (404, 410):
                rp = E.robotparser.RobotFileParser()
                rp.parse([])
            else:
                motivo = f"robots.txt respondió HTTP {r.status_code}; no verificable"
        except requests.exceptions.RequestException as exc:
            tipo, det = self._clasificar(exc)
            motivo = f"robots.txt inaccesible ({tipo}): {det}"
        self._robots[origen] = (rp, motivo)
        return self._robots[origen]

    def get(self, url: str, hosts_ok=frozenset()) -> E.Respuesta:
        r = self._get_con_saltos(url, {CP.dominio_base(h) for h in hosts_ok})
        self.eventos.append({"url": E.url_segura(url), "status": r.status, "ok": r.ok, "tipo_error": r.tipo_error})
        return r

    def _get_con_saltos(self, url: str, ok: set[str]) -> E.Respuesta:
        saltos, actual = [], url
        for _ in range(MAX_SALTOS + 1):
            ctx = dict(url_final=E.url_segura(actual), redirecciones=tuple(saltos))
            agotado = self.presupuesto_agotado()
            if agotado:
                return E.Respuesta(url, False, tipo_error=agotado, detalle="presupuesto de tiempo/solicitudes agotado; no se consulta", **ctx)
            rp, motivo = self._robots_de(actual)
            if rp is None:
                return E.Respuesta(url, False, tipo_error="ROBOTS_NO_VERIFICABLE", detalle=motivo, **ctx)
            if not rp.can_fetch(self.ua, actual):
                return E.Respuesta(url, False, tipo_error="PROHIBIDO_POR_ROBOTS", detalle="robots.txt no permite esta ruta", **ctx)
            delay = float(rp.crawl_delay(self.ua) or rp.crawl_delay("*") or 0)
            base = CP.dominio_base(urlparse(actual).hostname or "")
            if delay > self.max_espera_crawl:
                return E.Respuesta(url, False, tipo_error="CRAWL_DELAY_EXCESIVO",
                                   detalle=f"robots.txt pide Crawl-delay de {delay:g} s (> {self.max_espera_crawl:g} s admitidos); se respeta y no se consulta", **ctx)
            if self._paginas.get(base, 0) >= self.max_paginas_dominio:
                return E.Respuesta(url, False, tipo_error="LIMITE_PAGINAS_DOMINIO",
                                   detalle=f"se alcanzó el máximo de {self.max_paginas_dominio} páginas por dominio", **ctx)
            try:
                self._esperar(delay)
                self.n_solicitudes += 1
                self._paginas[base] = self._paginas.get(base, 0) + 1
                r = self._pedir(actual, False)
            except requests.exceptions.RequestException as exc:
                tipo, det = self._clasificar(exc)
                return E.Respuesta(url, False, tipo_error=tipo, detalle=det, **ctx)
            loc = (getattr(r, "headers", None) or {}).get("Location")
            if r.status_code not in REDIRECCIONES or not loc:
                break
            destino = urljoin(actual, loc)
            saltos.append((r.status_code, E.url_segura(destino)))
            ctx = dict(url_final=E.url_segura(destino), redirecciones=tuple(saltos))
            po, pd = urlparse(actual), urlparse(destino)
            if pd.scheme not in ("http", "https") or (po.scheme == "https" and pd.scheme != "https"):
                return E.Respuesta(url, False, r.status_code, tipo_error="REDIRECCION_NO_SEGURA",
                                   detalle="la redirección degrada https o cambia de esquema; no se sigue", **ctx)
            if not (_mismo_dominio(po.hostname, pd.hostname) or CP.dominio_base(pd.hostname or "") in ok):
                return E.Respuesta(url, False, r.status_code, tipo_error="REDIRECCION_EXTERNA",
                                   detalle=f"redirige a {pd.hostname}, que no está verificado como oficial para este municipio; no se sigue", **ctx)
            actual = destino
        else:
            return E.Respuesta(url, False, r.status_code, tipo_error="REDIRECCION_EXCESIVA",
                               detalle=f"más de {MAX_SALTOS} redirecciones", url_final=E.url_segura(actual), redirecciones=tuple(saltos))
        ctx = dict(url_final=E.url_segura(actual), redirecciones=tuple(saltos))
        if r.status_code == 429:
            return E.Respuesta(url, False, 429, tipo_error="LIMITE_SOLICITUDES_429", detalle="HTTP 429; no se reintenta ni se eluden límites", **ctx)
        if r.status_code in (401, 403):
            return E.Respuesta(url, False, r.status_code, tipo_error="ACCESO_DENEGADO_HTTP", detalle=f"HTTP {r.status_code}; no se eluden restricciones", **ctx)
        if r.status_code in (404, 410):
            return E.Respuesta(url, False, r.status_code, tipo_error="PAGINA_AUSENTE", detalle=f"HTTP {r.status_code}: la página no existe", **ctx)
        if r.status_code >= 400:
            return E.Respuesta(url, False, r.status_code, tipo_error="ERROR_HTTP", detalle=f"HTTP {r.status_code}", **ctx)
        r.encoding = r.encoding or getattr(r, "apparent_encoding", None) or "utf-8"
        if not (r.text or "").strip():
            return E.Respuesta(url, False, r.status_code, tipo_error="RESPUESTA_VACIA", detalle="HTTP 200 sin contenido", **ctx)
        return E.Respuesta(url, True, r.status_code, texto=r.text, **ctx)


def _get(cli, url: str, permitidos: set[str]):
    return cli.get(url, hosts_ok=permitidos) if isinstance(cli, ClienteContactos) else cli.get(url)


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
def _relevar_sitio(cli, cfg: dict, sitio: dict, fecha: str, snap: str, max_paginas: int = MAX_PAGINAS, dir_diag: Path | None = None) -> dict:
    mid, nombre = cfg["municipio_id"], cfg["municipio"]
    out = dict(municipio_id=mid, municipio=nombre, sitio_ok=False, hallazgos=[], general=[], paginas=[], incidencias=[], fuentes_extra=[])
    url0 = (sitio or {}).get("sitio_oficial", "").strip()
    if not url0:
        out["incidencias"].append(_inc(mid, "sitio_oficial", "SITIO_OFICIAL_NO_CONFIGURADO", "No hay sitio oficial en config/sitios_oficiales.csv.",
                                       E.BASE_URL, fecha, snap, "ALTO", "Cargar y verificar el sitio oficial del municipio."))
        return out
    hcd_cfg = (sitio.get("sitio_hcd") or "").strip()
    # Destinos que una redirección puede alcanzar además del mismo dominio: solo los verificados en la configuración.
    permitidos = {urlparse(u).hostname or "" for u in (url0, hcd_cfg) if u} | \
                 {d.strip() for d in (sitio.get("dominios_verificados") or "").split(";") if d.strip()}
    permitidos = {h for h in permitidos if not CP.dominio_homonimo(h)}   # un homónimo de otra provincia nunca es destino válido
    r = _get(cli, url0, permitidos)
    if not r.ok:
        out["incidencias"].append(E._inc_respuesta(mid, r, fecha, snap, "contacto:sitio_oficial"))
        return out
    cab = CP.BeautifulSoup(r.texto, "lxml")
    for t in cab(["script", "style", "noscript"]):
        t.decompose()
    texto_id = " ".join([cab.title.get_text(" ") if cab.title else ""] + [h.get_text(" ") for h in cab.find_all(["h1", "h2"])[:6]] +
                        [m.get("content", "") for m in cab.find_all("meta", attrs={"property": "og:site_name"})])
    host0 = urlparse(r.url_final or url0).hostname or ""
    # El dominio debe corresponder al municipio del AMBA: ni el dominio de un homónimo conocido ni una página que se declare de otra provincia.
    homonimo = CP.dominio_homonimo(host0)
    ajena = "" if homonimo else CP.provincia_ajena(texto_id + " " + cab.get_text(" ", strip=True)[:4000])
    if homonimo or ajena:
        out["incidencias"].append(_inc(mid, "sitio_oficial", "SITIO_HOMONIMO",
                                       f"{r.diagnostico()}; el sitio parece de otro municipio homónimo "
                                       f"({homonimo or 'Provincia de ' + ajena.title()}), no de {nombre} (Buenos Aires).", url0, fecha, snap, "ALTO",
                                       "Corregir config/sitios_oficiales.csv con el dominio oficial del municipio bonaerense."))
        return out
    # CONFIRMADO = una persona verificó que es el sitio oficial de este municipio (p. ej. su título no nombra al municipio).
    documentado = sitio.get("estado") in ("CONFIRMADO", "OFICIAL_DOCUMENTADO")   # una persona / una fuente oficial lo identificó
    en_ba = CP.evidencia_bonaerense(texto_id + " " + cab.get_text(" ", strip=True)[:6000], cab)
    verificado = documentado or (CP.nombre_en_texto(nombre, texto_id) and _oficial(host0) and en_ba)
    if not verificado:
        out["incidencias"].append(_inc(mid, "sitio_oficial", "SITIO_NO_VERIFICADO",
                                       f"{r.diagnostico()}; no se pudo verificar que sea el sitio oficial de {nombre} "
                                       f"(título/encabezados sin el nombre, dominio fuera de gob.ar/gov.ar o sin evidencia de pertenecer a la provincia de Buenos Aires).", url0, fecha, snap, "ALTO",
                                       "Revisar el dominio; marcar estado=CONFIRMADO en config solo tras verificación manual."))
        return out
    out["sitio_ok"] = True
    bases = {CP.dominio_base(host0)} | ({CP.dominio_base(urlparse(hcd_cfg).hostname or "")} if hcd_cfg else set())
    final0 = r.url_final or url0   # los enlaces relativos se resuelven contra el destino final, no contra la URL anterior a la redirección
    cola, vistas, expandidas = [(final0, r.texto)], {E.url_segura(url0), E.url_segura(final0)}, set()
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
            rr = _get(cli, url, permitidos)
            if not rr.ok:
                if not rr.pagina_ausente:
                    out["incidencias"].append(E._inc_respuesta(mid, rr, fecha, snap, "contacto:pagina"))
                continue
            html, url = rr.texto, (rr.url_final or url)
        host = CP.dominio_base(urlparse(url).hostname or "")
        es_hcd_pag = host != CP.dominio_base(host0)       # otro sitio oficial enlazado desde la portada = el del Concejo
        if _oficial(host) or host in bases:
            bases.add(host)
        if dir_diag is not None:
            dir_diag.mkdir(parents=True, exist_ok=True)
            (dir_diag / f"contactos_{mid}_{C.id_estable(url)}.html").write_text(html[:1_000_000], encoding="utf-8")
        a = CP.analizar_pagina(html, url, bases, hcd=es_hcd_pag)
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


def relevar_municipio(cli, cfg: dict, sitio: dict, fecha: str, snap: str, max_paginas: int = MAX_PAGINAS, dir_diag: Path | None = None) -> dict:
    """Relevamiento del sitio principal; si no se puede (TLS, robots, bloqueo, sitio no verificado), solo entonces se prueban las
    `fuentes_alternativas` OFICIALES cargadas en la config (otro dominio del municipio, HCD...). Sin eludir TLS, robots ni accesos:
    cada alternativa pasa las mismas verificaciones y la incidencia del sitio principal se conserva."""
    out = _relevar_sitio(cli, cfg, sitio, fecha, snap, max_paginas, dir_diag)
    alts = [u.strip() for u in (sitio or {}).get("fuentes_alternativas", "").split(";") if u.strip()]
    if out["sitio_ok"] or not alts:
        return out
    for alt in alts:
        if not alt.startswith("https://") or CP.dominio_homonimo(urlparse(alt).hostname or ""):
            continue
        o2 = _relevar_sitio(cli, cfg, {**sitio, "sitio_oficial": alt, "estado": "CONFIRMADO", "fuentes_alternativas": ""}, fecha, snap, max_paginas, dir_diag)
        out["incidencias"] += o2["incidencias"]
        if o2["sitio_ok"]:
            for k in ("hallazgos", "general", "paginas"):
                out[k] += o2[k]
            out["sitio_ok"], out["fuente_alternativa"] = True, alt
            break
    return out


# ------------------------------------------------------------------ agregación y filas
def _agregar(hallazgos: list[dict]) -> dict:
    ag: dict[str, dict] = {}
    for h in hallazgos:
        a = ag.setdefault(h["clave"], dict(emails=[], telefonos=[], internos=[], direccion="", horario="", formulario="", responsable="",
                                           cargo="", responsable_original="", urls=[], canales_por_url={}, fechas={}, hs=[], omitidos=0,
                                           discrepancias=[], resp_h=None, origen={}))
        a["hs"].append(h)
        a["fallback"] = h.get("fallback", False) and a.get("fallback", True)   # solo si TODA la evidencia general es de respaldo
        if h.get("responsable") and not a["responsable"]:      # la persona publicada se conserva aunque no haya canal
            a["responsable"], a["cargo"], a["responsable_original"], a["resp_h"] = h["responsable"], h.get("cargo", ""), h.get("responsable_original", ""), h
        a["discrepancias"] += [d for d in h.get("discrepancias", []) if d not in a["discrepancias"]]
        if not h["con_canal"]:
            continue
        for v in h["emails"] + h["telefonos"]:
            a["origen"].setdefault(v, h)                          # página EXACTA donde aparece cada contacto
        for k_src, k_dst in (("emails", "emails"), ("telefonos", "telefonos"), ("internos", "internos")):
            a[k_dst] += [x for x in h[k_src] if x not in a[k_dst]]
        for k in ("direccion", "horario", "formulario", "responsable", "cargo", "responsable_original"):
            a[k] = a[k] or h.get(k, "")
        a["urls"].append(h["url"])
        a["canales_por_url"].setdefault(h["url"], set()).update(h["emails"] + [re.sub(r"\D", "", t) for t in h["telefonos"]])
        a["fechas"][h["url"]] = h.get("fecha_actualizacion", "")
        a["omitidos"] += sum(h.get("omitidos", {}).values())
    return ag


def cargar_verificados(ruta: Path | None = None) -> dict[tuple[str, str], dict[str, str]]:
    """Canales cuya vigencia confirmó una PERSONA (llamado, respuesta a un correo...): {(municipio, dependencia): {valor: fecha}}.
    Un HTTP 200 o que el dato aparezca en el sitio no demuestra que el correo o teléfono funcione."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    for r in C.leer_csv(ruta or C.ARCHIVO_VERIFICADOS):
        if not all((r.get(k) or "").strip() for k in ("municipio_id", "dependencia", "canal", "fecha_verificacion", "metodo")):
            continue
        v = r["canal"].strip().lower()
        out.setdefault((r["municipio_id"], r["dependencia"]), {})[v if "@" in v else re.sub(r"\D", "", v)] = r["fecha_verificacion"]
    return out


def _estado(a: dict | None, hoy: str, verif: dict[str, str] | None = None) -> str:
    """NO_ENCONTRADO | DEPENDENCIA_SIN_CANAL | PUBLICADO_SIN_VIGENCIA_CONFIRMADA (un solo origen) | PUBLICADO_CORROBORADO (2+ páginas
    oficiales o fecha de actualización reciente; sigue sin probar que funcione) | VIGENTE_CONFIRMADO (solo si una persona lo verificó)."""
    if a is None:
        return "NO_ENCONTRADO"
    if not (a["emails"] or a["telefonos"]):
        return "DEPENDENCIA_SIN_CANAL"
    if verif and any(v in verif for v in [e.lower() for e in a["emails"]] + [re.sub(r"\D", "", t) for t in a["telefonos"]]):
        return "VIGENTE_CONFIRMADO"
    conteo: dict[str, int] = {}
    for canales in a["canales_por_url"].values():
        for c in canales:
            conteo[c] = conteo.get(c, 0) + 1
    if any(n >= 2 for n in conteo.values()) or any(f and CP.fecha_reciente(f, hoy) for f in a["fechas"].values()):
        return "PUBLICADO_CORROBORADO"
    return "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"


def construir_filas(res: dict, fecha: str, snap: str, verificados: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """(filas 03, fuentes 05, incidencias 06) de un municipio ya relevado."""
    mid, nombre = res["municipio_id"], res["municipio"]
    if not res["sitio_ok"]:
        return [], [], res["incidencias"]
    ag = _agregar(res["hallazgos"] + [dict(g, omitidos=g.get("omitidos", {})) for g in res["general"]])
    filas, fuentes, incs = [], [], list(res["incidencias"])
    titulos = {h["url"]: h.get("titulo", "") for h in res["hallazgos"] + res["general"]}
    verificados = verificados or {}
    for d in [*CP.DEPENDENCIAS, *CP.ALTERNATIVOS]:
        clave, a = d["clave"], ag.get(d["clave"])
        if a is None and clave in ("prensa", "hcd_prensa", "hcd_contacto"):
            continue                        # canales alternativos: solo si se hallaron (sin filas vacías)
        verif = verificados.get((mid, d["dependencia"]), {})
        estado = _estado(a, fecha, verif)
        if clave == "contacto_general" and estado in ("NO_ENCONTRADO", "DEPENDENCIA_SIN_CANAL"):
            incs.append(_inc(mid, clave, "CANAL_NO_ENCONTRADO", "No se halló un contacto general institucional publicado.", res["paginas"][0],
                             fecha, snap, "ALTO", "Revisar manualmente la sección de contacto del sitio oficial."))
            # la fila se emite igual: si antes había un canal, la fusión lo conserva SIN vigencia y registra que dejó de verse
        org = f"Honorable Concejo Deliberante de {nombre}" if d["organismo"] == "HCD" else f"Municipalidad de {nombre}"
        nom, ape, met = C.separar_nombre(a["responsable"]) if a and a["responsable"] else ("", "", "")
        con = estado in ("VIGENTE_CONFIRMADO", "PUBLICADO_CORROBORADO", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA")
        primero = (a["emails"] or a["telefonos"] or [None])[0] if a else None
        h_pri = a["origen"].get(primero) if a and primero else None                      # página exacta del primer canal
        fecha_verif = max([verif[v] for v in [e.lower() for e in (a["emails"] if a else [])] + [re.sub(r"\D", "", t) for t in (a["telefonos"] if a else [])]
                           if v in verif] or [""]) if estado == "VIGENTE_CONFIRMADO" else ""
        fuentes_txt = " | ".join(f"{v} @ {E.url_segura(a['origen'][v]['url'])}" for v in (a["emails"] + a["telefonos"]) if v in a["origen"]) if a else ""
        fila = {"municipio_id": mid, "organismo": org, "dependencia": d["dependencia"], "tipo_contacto": d["tipo"],
                "responsable_nombre": nom, "responsable_apellido": ape, "responsable_nombre_completo": a["responsable"] if a else "",
                "cargo": a["cargo"] if a else "", "email_institucional": "; ".join(a["emails"]) if a else "",
                "telefono_institucional": "; ".join(a["telefonos"]) if a else "", "interno": "; ".join(a["internos"]) if a else "",
                "direccion": a["direccion"] if a else "", "horario_atencion": a["horario"] if a else "",
                "sitio_web": (a["formulario"] or (a["urls"][0] if a["urls"] else "")) if a else "",
                "url_fuente": E.url_segura(h_pri["url"]) if h_pri else (E.url_segura(a["hs"][0]["url"]) if a else ""),
                "fecha_verificacion": fecha_verif, "estado_contacto": estado, "snapshot_id": snap, "fecha_consulta": fecha,
                "evidencia": ((fuentes_txt + " || " if fuentes_txt else "") +
                              (next((h["evidencia"] for h in a["hs"] if h["con_canal"] or h.get("responsable")), a["hs"][0]["evidencia"]) if a and a["hs"] else ""))[:240]}
        filas.append(fila)
        if a is None and clave != "contacto_general":
            alt = "; canal alternativo: contacto institucional general / mesa de entradas" if clave in ("ceremonial", "relaciones") else ""
            incs.append(_inc(mid, clave, "OFICINA_NO_ENCONTRADA", f"No se identificó '{d['dependencia']}' en las {len(res['paginas'])} páginas oficiales consultadas{alt}.",
                             res["paginas"][0], fecha, snap, "MEDIO" if clave != "ceremonial" else "ALTO", "Revisar organigrama/decretos o consultar fuente oficial alternativa."))
        elif estado == "DEPENDENCIA_SIN_CANAL":
            incs.append(_inc(mid, clave, "CANAL_NO_ENCONTRADO", f"'{d['dependencia']}' figura en el sitio pero sin correo/teléfono atribuible a su bloque.",
                             a["hs"][0]["url"], fecha, snap, "MEDIO", "Buscar el canal en otra sección oficial o por pedido formal."))
        if a and a["responsable"]:   # persona publicada: trazabilidad con o sin canal; vigencia sin confirmar
            hr = a["resp_h"] or a["hs"][0]
            fuentes.append(_fuente(mid, clave, "responsable_nombre_completo", a["responsable"], hr, fecha, snap, "MEDIO", titulos.get(hr["url"], "")))
            if a["cargo"]:
                fuentes.append(_fuente(mid, clave, "cargo", a["cargo"], hr, fecha, snap, "MEDIO", titulos.get(hr["url"], "")))
        if a and a["discrepancias"]:
            incs.append(_inc(mid, clave, "TELEFONO_DISCREPANCIA",
                             "El texto visible y el enlace tel: no coinciden (se registró el texto publicado): " +
                             "; ".join(f"'{t}' vs tel:{h}" for t, h in a["discrepancias"]), a["urls"][0] if a["urls"] else a["hs"][0]["url"],
                             fecha, snap, "BAJO", "Confirmar cuál es el número vigente en la fuente oficial."))
        if a and a.get("fallback") and clave == "contacto_general":
            incs.append(_inc(mid, clave, "CONTACTO_GENERAL_POR_RESPALDO",
                             "No había una zona de contacto reconocible: el contacto general se tomó de los canales institucionales del cuerpo de la página.",
                             a["hs"][0]["url"], fecha, snap, "BAJO", "Auditar la fuente antes de usarlo."))
        if a and a["omitidos"]:
            incs.append(_inc(mid, clave, "CANAL_NO_INSTITUCIONAL_OMITIDO",
                             f"{a['omitidos']} correo(s) de dominio no institucional o teléfono(s) móvil/WhatsApp publicados no se registraron.",
                             a["urls"][0], fecha, snap, "BAJO", "Ninguna: solo se registran canales institucionales."))
        if con:
            conf = "ALTO" if estado == "VIGENTE_CONFIRMADO" else ("BAJO" if clave == "contacto_general" else "MEDIO")
            h0 = next(h for h in a["hs"] if h["con_canal"])
            for e in a["emails"]:      # cada contacto con la URL EXACTA de la página donde apareció
                he = a["origen"].get(e, h0)
                fuentes.append(_fuente(mid, clave, "email_institucional", e, he, fecha, snap, conf, titulos.get(he["url"], "")))
            for t in a["telefonos"]:
                ht = a["origen"].get(t, h0)
                fuentes.append(_fuente(mid, clave, "telefono_institucional", t, ht, fecha, snap, conf, titulos.get(ht["url"], "")))
            for campo, val in (("direccion", a["direccion"]), ("horario_atencion", a["horario"]), ("sitio_web", a["formulario"])):
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
            for c in CAMPOS_CANAL + ["tipo_contacto", "estado_contacto"]:
                if n.get(c):
                    prev[c] = n[c]
            prev["fecha_verificacion"] = n.get("fecha_verificacion", "")      # solo existe si una persona verificó el canal
            if not prev_canal and prev["municipio_id"] in con_filas:
                eventos.append(dict(tipo="NUEVO", fila=n, prev=dict(prev)))
        elif prev_canal:                      # ya no se ve el canal: se conserva lo anterior sin afirmar vigencia
            eventos.append(dict(tipo="YA_NO_VISIBLE", fila=n, prev=dict(prev)))   # la incidencia tiene id estable: no se duplica
            prev["estado_contacto"] = "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"
        else:
            prev["estado_contacto"] = n["estado_contacto"]
            for c in ("responsable_nombre", "responsable_apellido", "responsable_nombre_completo", "cargo", "evidencia", "url_fuente"):
                if n.get(c):
                    prev[c] = n[c]            # se actualiza la persona publicada; nunca se pisa con vacío
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


def aplicar(resultados: list[dict], fecha: str, snap: str, dir_actual: Path, dir_hist: Path, verificados: dict | None = None) -> dict:
    filas, fuentes, incs, procesados = [], [], [], []
    verificados = cargar_verificados() if verificados is None else verificados
    for res in resultados:
        f, s, i = construir_filas(res, fecha, snap, verificados)
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
    sim = {"VIGENTE_CONFIRMADO": "✔ vigente", "PUBLICADO_CORROBORADO": "✔ corroborado", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA": "✔ publicado", "DEPENDENCIA_SIN_CANAL": "◐ sin canal", "NO_ENCONTRADO": "✘"}
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
    espec = sum(1 for f in filas if f["tipo_contacto"] != "CONTACTO_ALTERNATIVO" and f["estado_contacto"] in ("VIGENTE_CONFIRMADO", "PUBLICADO_CORROBORADO", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"))
    alt = sum(1 for f in filas if f["tipo_contacto"] == "CONTACTO_ALTERNATIVO" and f["estado_contacto"] in ("VIGENTE_CONFIRMADO", "PUBLICADO_CORROBORADO", "PUBLICADO_SIN_VIGENCIA_CONFIRMADA"))
    l += ["", "Estados: " + ", ".join(f"{k}={v}" for k, v in sorted(cuenta.items())),
          f"Canales específicos (protocolo, relaciones, despacho, concejo) con contacto: {espec}; canales generales/alternativos con contacto: {alt}.",
          f"Responsables publicados: {sum(1 for f in filas if f['responsable_nombre_completo'])}.", "", "— = no relevado (sitio no verificado)."]
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
    sel = seleccionar(cfg_all, a.municipios)
    sitios, cli = cargar_sitios(), ClienteContactos(pausa=a.pausa)
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
