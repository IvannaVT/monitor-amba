"""Extracción de canales de contacto institucional desde páginas OFICIALES (solo se lee texto; nada se ejecuta).

Principios (spec sec. 5 y 25):
- Un dato solo se registra si está publicado en la página; nunca se deduce (ni correos por patrón ni nombres).
- Los canales se atribuyen a una dependencia solo cuando aparecen en el mismo bloque estructural y el bloque no
  menciona otras dependencias; si no, la dependencia queda "encontrada sin canal".
- Se omiten (y solo se cuenta que existían) correos de dominios no institucionales y teléfonos móviles/WhatsApp.
- Encabezado, navegación y pie no se atribuyen a dependencias: el pie alimenta únicamente el contacto general.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import parser_ficha as P  # noqa: E402

# Dependencias objetivo, en orden de prioridad (spec: ceremonial/protocolo primero).
DEPENDENCIAS = [
    dict(clave="ceremonial", dependencia="Ceremonial y Protocolo", organismo="MUNICIPALIDAD", tipo="ESPECIFICO_PROTOCOLO",
         frases=["ceremonial y protocolo", "ceremonial", "protocolo"]),
    dict(clave="relaciones", dependencia="Relaciones Institucionales", organismo="MUNICIPALIDAD", tipo="RELACIONES_INSTITUCIONALES",
         frases=["relaciones institucionales"]),
    dict(clave="privada", dependencia="Secretaría Privada del Intendente", organismo="MUNICIPALIDAD", tipo="DESPACHO",
         frases=["secretaria privada"]),
    dict(clave="despacho", dependencia="Despacho del Intendente / Jefatura de Gabinete", organismo="MUNICIPALIDAD", tipo="DESPACHO",
         frases=["despacho del intendente", "despacho de la intendenta", "jefatura de gabinete", "jefe de gabinete", "jefa de gabinete"]),
    dict(clave="hcd_presidencia", dependencia="Presidencia del Concejo Deliberante", organismo="HCD", tipo="CONCEJO",
         frases=["presidencia del honorable concejo deliberante", "presidencia del concejo deliberante", "presidencia del hcd", "presidencia hcd"]),
    dict(clave="hcd_secretaria", dependencia="Secretaría del Concejo Deliberante", organismo="HCD", tipo="CONCEJO",
         frases=["secretaria del honorable concejo deliberante", "secretaria del concejo deliberante", "secretaria del hcd",
                 "secretaria legislativa", "secretaria administrativa del concejo"]),
    dict(clave="mesa_entradas", dependencia="Mesa de Entradas", organismo="MUNICIPALIDAD", tipo="CONTACTO_ALTERNATIVO",
         frases=["mesa general de entradas", "mesa de entradas", "mesa de entrada"]),
]
GENERAL = dict(clave="contacto_general", dependencia="Contacto institucional general", organismo="MUNICIPALIDAD",
               tipo="CONTACTO_ALTERNATIVO", frases=[])
POR_CLAVE = {d["clave"]: d for d in [*DEPENDENCIAS, GENERAL]}
_RX_FRASES = {d["clave"]: re.compile(r"\b(?:" + "|".join(re.escape(f) for f in d["frases"]) + r")\b") for d in DEPENDENCIAS}

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
RE_TEL = re.compile(r"(?i)(?:tel(?:[eé]fono)?s?|conmutador|l[ií]nea|fono)\.?\s*[:\-]?\s*((?:\+?54\s*)?[\d\s().\-/]{6,34}\d)")
RE_MOVIL = re.compile(r"(?i)\b(?:cel(?:ular)?|m[oó]vil|whats\s?app|wsp)\b")
RE_INT = re.compile(r"(?i)\b(?:int(?:erno)?s?\.?|anexo)\s*[:.]?\s*(\d{2,5}(?:\s*(?:,|y)\s*\d{2,5})*)")  # "/" separa teléfonos, no internos
RE_DIR = re.compile(r"(?i)(?:direcci[oó]n|domicilio|ubicaci[oó]n)\s*[:\-]\s*([^\n|]{6,140})")
RE_HOR = re.compile(r"(?i)horarios?(?:\s+de\s+atenci[oó]n)?\s*[:\-]\s*([^\n|]{4,140})")
RE_ACTUALIZADO = re.compile(r"(?i)(?:actualizad[oa]|[uú]ltima actualizaci[oó]n)[^\d]{0,25}(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})")
RE_CARGO = re.compile(r"(?i)^(?:(?:sub)?secretari[oa]|(?:sub)?director[a]?|jef[ea]|coordinador[a]?|presidente|presidenta|titular|"
                      r"responsable|encargad[oa])\b[^:]{0,70}")
HONORIFICOS = re.compile(r"^(?:(?:lic|dr|dra|prof|arq|ing|cdor|cdora|cr|abog|sr|sra|mg|mag|esp|tec|don|dna|mtro|mtra)\.?\s+)+", re.I)
_NO_ES_NOMBRE = {"secretaria", "secretario", "direccion", "director", "subsecretaria", "protocolo", "ceremonial", "relaciones",
                 "institucionales", "institucional", "privada", "despacho", "gabinete", "concejo", "deliberante", "honorable",
                 "municipalidad", "municipio", "intendente", "intendenta", "mesa", "entradas", "atencion", "contacto",
                 "telefono", "correo", "mail", "email", "horario", "legislativa", "administrativa", "presidencia", "jefatura"}
_PARTICULAS_OK = {"de", "del", "la", "las", "los", "y", "da", "das", "do", "dos", "di", "van", "von"}
_ZONAS_EXCLUIDAS = {"header", "nav", "footer", "aside"}
EXTENSIONES_NO_HTML = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".mp4", ".webp")


def norm(t: str) -> str:
    return C.normalizar_texto(t)


def deps_en(texto_norm: str) -> set[str]:
    return {k for k, rx in _RX_FRASES.items() if rx.search(texto_norm)}


def dominio_base(host: str) -> str:
    return (host or "").lower().removeprefix("www.")


# Dominios de municipios HOMÓNIMOS de otras provincias (ya identificados): nunca son oficiales para el AMBA.
DOMINIOS_HOMONIMOS = {"avellaneda.gob.ar": "Avellaneda (Santa Fe)"}
_PROVINCIAS_AJENAS = ["santa fe", "cordoba", "mendoza", "tucuman", "salta", "jujuy", "entre rios", "corrientes", "chaco", "misiones",
                      "la pampa", "san juan", "san luis", "rio negro", "neuquen", "chubut", "santa cruz", "tierra del fuego",
                      "catamarca", "la rioja", "santiago del estero", "formosa"]
_RX_PROV_BA = re.compile(r"\b(?:provincia|pcia) de (?:buenos aires|bs as)\b")
_RX_PROV_AJENA = re.compile(r"\b(?:provincia|pcia) de (" + "|".join(_PROVINCIAS_AJENAS) + r")\b")


def dominio_homonimo(host: str) -> str:
    """Nombre del municipio homónimo si el host pertenece a su dominio (o a un subdominio), o ''."""
    h = dominio_base(host)
    return next((v for d, v in DOMINIOS_HOMONIMOS.items() if h == d or h.endswith("." + d)), "")


def provincia_ajena(texto: str) -> str:
    """Otra provincia nombrada como 'Provincia de X' en el texto, si no se nombra también la de Buenos Aires; si no, ''."""
    t = norm(texto)
    if _RX_PROV_BA.search(t):
        return ""
    m = _RX_PROV_AJENA.search(t)
    return m.group(1) if m else ""


def email_institucional(email: str, bases: set[str]) -> bool:
    dom = email.split("@", 1)[1].lower()
    if dominio_homonimo(dom):
        return False
    return dom.endswith((".gob.ar", ".gov.ar")) or any(dom == b or dom.endswith("." + b) for b in bases)


# ------------------------------------------------------------------ extractores de canales
def extraer_emails(nodo, bases: set[str]) -> tuple[list[str], int]:
    """(emails institucionales sin repetir, cantidad de emails omitidos por dominio no institucional)."""
    crudos = [a["href"][7:].split("?")[0] for a in nodo.find_all("a", href=True) if a["href"].lower().startswith("mailto:")]
    crudos += RE_EMAIL.findall(nodo.get_text(" ", strip=True))
    vistos, buenos, omitidos = set(), [], 0
    for e in crudos:
        e = e.strip().strip(".,;:()<>").lower()
        if not RE_EMAIL.fullmatch(e) or e in vistos:
            continue
        vistos.add(e)
        if email_institucional(e, bases):
            buenos.append(e)
        else:
            omitidos += 1
    return buenos, omitidos


def _digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


def extraer_telefonos(nodo) -> tuple[list[str], int]:
    """(teléfonos publicados con etiqueta de teléfono o tel:, cantidad de móviles/WhatsApp omitidos)."""
    lineas = [ln for ln in nodo.get_text("\n", strip=True).split("\n")]
    res, omitidos, vistos = [], 0, set()

    def agregar(t: str) -> None:
        d = _digitos(t)
        if 6 <= len(d) <= 13 and d not in vistos and not re.fullmatch(r"\d{2}-?\d{8}-?\d", t.strip()):
            vistos.add(d)
            res.append(re.sub(r"\s+", " ", t).strip(" -/.,"))
    for ln in lineas:
        if RE_MOVIL.search(ln):
            omitidos += 1
            continue
        for m in RE_TEL.finditer(ln):
            resto = RE_INT.sub(" ", ln[m.start(1):])      # tras la etiqueta: "4201-0001 int. 123 / 4201-0002"
            for parte in re.split(r"\s*[/;|]\s*", resto):
                if not (n := re.match(r"\s*((?:\+?54\s*)?[\d\s().\-]{6,30}\d)", parte)):
                    break                                   # una parte sin número corta la lista
                agregar(n.group(1))
    for a in nodo.find_all("a", href=True):
        if a["href"].lower().startswith("tel:"):
            if RE_MOVIL.search(a.get_text(" ")):
                omitidos += 1
            else:
                agregar(a["href"][4:])
    return res, omitidos


def extraer_internos(texto: str) -> list[str]:
    out = []
    for m in RE_INT.finditer(texto):
        out += [x for x in re.split(r"\s*(?:y|,)\s*", m.group(1)) if x]
    return list(dict.fromkeys(out))


def extraer_direccion(texto: str) -> str:
    for m in RE_DIR.finditer(texto):
        v = m.group(1).strip(" .;")
        if re.search(r"\d|s/n|esq|calle|av", v, re.I):
            return v
    return ""


def extraer_horario(texto: str) -> str:
    m = RE_HOR.search(texto)
    return m.group(1).strip(" .;") if m else ""


def extraer_formulario(nodo, url: str) -> str:
    for a in nodo.find_all("a", href=True):
        h = a["href"]
        if h.lower().startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        if re.search(r"formulario|contact[aá]nos|escrib[ií]nos|consultas?", norm(a.get_text(" ")) + " " + norm(h)):
            return urljoin(url, h).split("#")[0]
    if nodo.find("form") and nodo.find("textarea"):
        return url
    return ""


def _nombre_valido(cand: str) -> str:
    """Nombre de persona o ''. Rechaza títulos de oficinas, correos y números."""
    c = HONORIFICOS.sub("", cand.strip()).strip(" -–,.;")
    if not c or "@" in c or re.search(r"\d", c):
        return ""
    pal = c.split()
    if any(norm(p) in _NO_ES_NOMBRE for p in pal) or deps_en(norm(c)):
        return ""
    if any(not (p[0].isupper() or p.lower() in _PARTICULAS_OK) for p in pal):
        return ""
    v, _ = P.validar_valor("intendente_nombre_completo", c)
    return v or ""


def extraer_responsable(lineas: list[str]) -> tuple[str, str, str]:
    """(nombre sin honorífico, cargo, texto original) para 'Cargo: Nombre' o 'Cargo' + línea siguiente."""
    for i, ln in enumerate(lineas):
        if not RE_CARGO.match(ln):
            continue
        if ":" in ln:
            cargo, _, cand = ln.partition(":")
        else:
            cargo, cand = ln, (lineas[i + 1] if i + 1 < len(lineas) else "")
        if deps_en(norm(cargo)) and ":" not in ln:
            continue  # es el título de la oficina, no un cargo con persona
        nombre = _nombre_valido(cand)
        if nombre:
            return nombre, cargo.strip()[:80], cand.strip()
    return "", "", ""


# ------------------------------------------------------------------ análisis de una página
def _limpiar(soup: BeautifulSoup) -> None:
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()


def _en_zona_excluida(el) -> bool:
    return any(p.name in _ZONAS_EXCLUIDAS for p in el.parents) or el.name in _ZONAS_EXCLUIDAS


def _tiene_contacto(nodo) -> bool:
    if nodo.find("a", href=re.compile(r"^(mailto|tel):", re.I)):
        return True
    t = nodo.get_text(" ", strip=True)
    return bool(RE_EMAIL.search(t) or RE_TEL.search(t))


def _canales(nodo, url: str, bases: set[str]) -> dict:
    texto = nodo.get_text("\n", strip=True)
    emails, om_mail = extraer_emails(nodo, bases)
    tels, om_tel = extraer_telefonos(nodo)
    nombre, cargo, orig = extraer_responsable(texto.split("\n"))
    return dict(emails=emails, telefonos=tels, internos=extraer_internos(texto), direccion=extraer_direccion(texto),
                horario=extraer_horario(texto), formulario=extraer_formulario(nodo, url), responsable=nombre, cargo=cargo,
                responsable_original=orig, omitidos={"email_no_institucional": om_mail, "telefono_movil": om_tel})


def texto_seguro(nodo, bases: set[str], maximo: int = 240) -> str:
    """Texto del bloque para la evidencia SIN datos no institucionales: líneas con móvil/WhatsApp y correos de
    dominios no institucionales se reemplazan por marcas (lo omitido no debe reaparecer en los CSV)."""
    return _texto_seguro_str(nodo.get_text("\n", strip=True), bases, maximo)


def _texto_seguro_str(texto: str, bases: set[str], maximo: int = 240) -> str:
    lineas = []
    for ln in texto.split("\n"):
        if RE_MOVIL.search(ln):
            ln = "[móvil/WhatsApp omitido]"
        ln = RE_EMAIL.sub(lambda m: m.group(0) if email_institucional(m.group(0).lower(), bases) else "[correo no institucional omitido]", ln)
        lineas.append(ln)
    return re.sub(r"\s+", " ", " ".join(lineas))[:maximo]


def _hay_canal(c: dict) -> bool:
    return bool(c["emails"] or c["telefonos"])


def analizar_pagina(html: str, url: str, bases: set[str]) -> dict:
    """Hallazgos por dependencia + contacto general + fecha de actualización visible de la página."""
    soup = BeautifulSoup(html, "lxml")
    titulo = (soup.title.get_text(" ", strip=True) if soup.title else "")[:160]
    _limpiar(soup)
    hallazgos: list[dict] = []
    for el in soup.find_all(True)[:8000]:
        if el.name in ("html", "body", "head") or _en_zona_excluida(el):
            continue
        txt = el.get_text(" ", strip=True)
        if not txt or len(txt) > 220:
            continue
        deps = deps_en(norm(txt))
        for clave in deps:
            if any(deps_en(norm(h.get_text(" ", strip=True))) >= {clave} for h in el.find_all(True, recursive=False)):
                continue  # el hijo ya contiene la frase: se toma el elemento más interno
            nodo, bloque = el, None
            for _ in range(5):
                if nodo is None or nodo.name in ("body", "html") or _en_zona_excluida(nodo):
                    break
                t = nodo.get_text(" ", strip=True)
                if len(t) > 1800:
                    break
                if _tiene_contacto(nodo):
                    if deps_en(norm(t)) == {clave}:
                        bloque = nodo
                    break  # con 2+ dependencias en el bloque la atribución es ambigua: no se atribuye
                nodo = nodo.parent
            h = dict(clave=clave, etiqueta=txt[:120], url=url, con_canal=False, evidencia=_texto_seguro_str(txt, bases, 160))
            if bloque is not None:
                c = _canales(bloque, url, bases)
                if _hay_canal(c):
                    h.update(c, con_canal=True, evidencia=texto_seguro(bloque, bases))
            hallazgos.append(h)
    # Contacto general: pie de página y bloques "contacto"; o toda la página si es una página de contacto.
    zonas = [z for z in soup.find_all(["footer"])] + [
        z for z in soup.find_all(attrs={"class": re.compile(r"contact", re.I)}) + soup.find_all(attrs={"id": re.compile(r"contact", re.I)})
        if not deps_en(norm(z.get_text(" ", strip=True)))]
    if re.search(r"contact", urlparse(url).path, re.I) and soup.body:
        zonas.append(soup.body)
    general = None
    for z in zonas:
        c = _canales(z, url, bases)
        if _hay_canal(c):
            general = dict(c, clave="contacto_general", etiqueta="Contacto general (pie/página de contacto)", url=url,
                           con_canal=True, evidencia=texto_seguro(z, bases))
            break
    fecha = ""
    if m := RE_ACTUALIZADO.search(soup.get_text(" ", strip=True)):
        fecha = P.parse_fecha(m.group(1)) or ""
    return dict(hallazgos=hallazgos, general=general, titulo=titulo, fecha_actualizacion=fecha)


# ------------------------------------------------------------------ enlaces a seguir
PESOS_ENLACE = {"ceremonial": 4, "protocolo": 4, "relaciones institucionales": 4, "secretaria privada": 4, "mesa de entradas": 3,
                "contacto": 3, "contactanos": 3, "autoridades": 3, "funcionarios": 3, "organigrama": 3, "gabinete": 3,
                "despacho": 3, "intendente": 2, "intendenta": 2, "gobierno": 1, "concejo deliberante": 3, "hcd": 3,
                "honorable concejo": 3, "secretaria legislativa": 3, "atencion al vecino": 2}


def puntuar_enlace(texto: str, url: str) -> int:
    base = norm(texto + " " + urlparse(url).path.replace("-", " ").replace("_", " "))
    return sum(p for k, p in PESOS_ENLACE.items() if k in base)


def enlaces_con_puntaje(html: str, base_url: str) -> list[tuple[int, str, str]]:
    """(puntaje, texto, url absoluta) de enlaces HTML con algún indicio de contacto/autoridades, ordenados."""
    soup = BeautifulSoup(html, "lxml")
    vistos, res = set(), []
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if h.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urljoin(base_url, h).split("#")[0]
        if u in vistos or urlparse(u).scheme not in ("http", "https") or urlparse(u).path.lower().endswith(EXTENSIONES_NO_HTML):
            continue
        vistos.add(u)
        t = a.get_text(" ", strip=True)
        if (p := puntuar_enlace(t, u)) >= 2:
            res.append((p, t, u))
    return sorted(res, key=lambda x: (-x[0], x[2]))


def fecha_reciente(fecha_iso: str, hoy: str, dias: int = 365) -> bool:
    try:
        return 0 <= (date.fromisoformat(hoy) - date.fromisoformat(fecha_iso)).days <= dias
    except ValueError:
        return False
