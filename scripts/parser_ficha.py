"""Parser de fichas municipales de municipiosargentinos.net (Fase 1b).

Sin depender de un formato rígido: la página se convierte en una secuencia de
fragmentos de texto con su sección (Datos clave, Cómo se compone su índice, Control,
Intendente...). Las etiquetas se reconocen por reglas (igualdad o palabras contenidas,
con preferencia por la sección) y el valor se busca después de la etiqueta, en la misma
cadena ("Etiqueta: valor") o, si hace falta, justo antes (tarjetas "12,3 / Índice").

Principios: no se inventan valores; un valor con escala distinta (p. ej. "40 / 50"),
porcentaje de peso o fuera de rango se rechaza y se informa; todo lo no reconocido se
devuelve con su etiqueta original para seguir depurando.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

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

# Campos de la ficha que van a 01 (identificación / intendente), con su tipo de valor.
CAMPOS_FICHA_01 = {
    "intendente_nombre_completo": "nombre", "partido_politico": "txt", "frente_electoral": "txt",
    "coalicion_actual": "txt", "intendente_condicion": "txt", "fecha_asuncion": "fecha", "poblacion_2022": "poblacion", "seccion_electoral": "txt",
}
TIPOS: dict[str, str] = {c: d["tipo"] for c, d in CAMPOS_PORTAL.items()}
TIPOS.update(CAMPOS_FICHA_01)
TIPOS[CAMPO_FECHA_PORTAL[0]] = "fecha"
TIPOS["cargos_presupuestados"] = "int"
TIPOS["indec_codigo"] = "indec"  # solo trazabilidad (05) y config; lo publica el portal, no está verificado contra INDEC
PCT = {"cobertura_agua_pct", "cobertura_cloacas_pct", "cobertura_gas_pct"}
PUNTAJES = {"indice_global", "transparencia_puntaje", "transparencia_relevamiento_propio", "transparencia_asap",
            "servicios_seguridad_puntaje", "seguridad_puntaje", "control_puntaje"}
SECCIONES_CONOCIDAS = {"datos clave", "como se compone su indice", "control", "intendente"}

# ---------------------------------------------------------------- reglas de etiquetas
# (campo, etiquetas iguales, [grupos de palabras que deben estar todas], secciones preferidas, solo_en_seccion)
_EXTRA = [
    ("transparencia_relevamiento_propio", [], [("relevamiento propio",), ("transparencia activa",)], (), False),
    ("transparencia_asap", [], [("asap",), ("transparencia fiscal",)], (), False),
    ("servicios_seguridad_puntaje", [], [("servicios", "seguridad")], (), False),
    ("seguridad_puntaje", ["indice de seguridad", "pilar seguridad"], [("seguridad", "puntaje")], (), False),
    ("homicidios_tasa_100k", [], [("homicidios", "tasa"), ("tasa", "homicid"), ("homicidios", "100"), ("homicidios",)], (), False),
    ("victimas_homicidio_ultimo_anio", [], [("victimas",)], (), False),
    ("ranking_pares", [], [("ranking", "grupo"), ("ranking", "pares"), ("posicion", "grupo"), ("puesto", "grupo"),
                           ("posicion", "pares")], (), False),
    ("ranking_provincial", ["ranking", "posicion", "puesto"], [("ranking", "provinc"), ("posicion", "provinc"),
                                                              ("puesto", "provinc"), ("en la provincia",)], ("datos clave",), False),
    ("transparencia_semaforo", [], [("semaforo",)], (), False),
    ("control_puntaje", ["puntaje", "puntos", "pilar", "puntaje del pilar"], [], ("control",), True),
    ("cobertura_agua_pct", ["agua"], [("agua", "red")], (), False),
    ("cobertura_gas_pct", ["gas"], [("gas", "red")], (), False),
    ("fecha_actualizacion_portal", [], [("actualiz",)], (), False),
    ("intendente_nombre_completo", ["intendente", "intendenta", "intendente a", "jefe comunal", "jefe municipal"], [], ("intendente",), False),
    ("intendente_nombre_completo", ["nombre", "nombre completo", "nombre y apellido"], [], ("intendente",), True),
    ("partido_politico", ["partido", "partido politico"], [("partido politico",)], (), False),
    ("frente_electoral", ["frente", "frente electoral", "alianza", "alianza electoral"], [("frente electoral",), ("alianza electoral",)], (), False),
    ("coalicion_actual", ["coalicion", "coalicion actual"], [("coalicion",)], (), False),
    ("fecha_asuncion", ["asumio", "asuncion", "fecha de asuncion", "en el cargo desde", "mandato desde"], [("asumio",), ("asuncion",)], (), False),
    ("fecha_asuncion", ["desde"], [], ("intendente",), True),
    ("poblacion_2022", ["habitantes"], [("poblacion",)], ("datos clave",), False),
    ("seccion_electoral", ["seccion"], [("seccion electoral",)], (), False),
    ("indec_codigo", ["indec codigo de partido", "codigo indec"], [("indec", "codigo")], (), False),
    ("cobertura_cloacas_pct", [], [("cloacas",)], (), False),
    ("gasto_por_habitante", [], [("gasto", "habitante")], (), False),
    ("empleados_municipales", [], [("empleados", "municipales")], (), False),
    ("ultimo_fallo_htc", [], [("ultimo", "fallo")], (), False),
    ("intendente_nombre_completo", [], [("intendente",), ("intendenta",)], (), False),
]
IGNORAR_SECCIONES = ("partidos para comparar", "fuentes")  # datos de otros municipios / citas: no se interpretan
REGLAS: list[dict] = []
for _c, _d in CAMPOS_PORTAL.items():
    REGLAS.append(dict(campo=_c, igual={C.normalizar_texto(x) for x in _d["sin"]}, contiene=[], secciones=(), solo=False))
REGLAS.append(dict(campo=CAMPO_FECHA_PORTAL[0], igual={C.normalizar_texto(x) for x in CAMPO_FECHA_PORTAL[1]},
                   contiene=[], secciones=(), solo=False))
for _c, _ig, _co, _se, _so in _EXTRA:
    REGLAS.append(dict(campo=_c, igual={C.normalizar_texto(x) for x in _ig},
                       contiene=[tuple(C.normalizar_texto(w) for w in g) for g in _co], secciones=_se, solo=_so))


def clasificar(etiqueta: str, seccion_norm: str = "") -> str | None:
    """Campo al que corresponde una etiqueta (la regla más específica; preferencia por sección)."""
    n = C.normalizar_texto(etiqueta)
    if not n or len(n) > 70:
        return None
    mejor, mejor_pt = None, 0
    for r in REGLAS:
        pt = 0
        if n in r["igual"]:
            pt = 1000 + len(n)
        for g in r["contiene"]:
            if all(re.search(rf"\b{re.escape(w)}", n) for w in g):
                pt = max(pt, 100 * len(g) + sum(len(w) for w in g))
        if not pt:
            continue
        en_seccion = any(x in seccion_norm for x in r["secciones"])
        if r["solo"] and not en_seccion:
            continue
        pt += 50 if en_seccion else 0
        if pt > mejor_pt:
            mejor, mejor_pt = r["campo"], pt
    return mejor


# ---------------------------------------------------------------- valores
_RUIDO = re.compile(r"^(?:/|de|sobre|/\s*100|de\s*100|sobre\s*100|puntos?|pts?\.?|-|–|—|•|·|\|)$", re.I)
_NUM = re.compile(r"\$?\s*([+-]?\d[\d.]*(?:,\d+)?)\s*(%|puntos?|pts?\.?)?\s*(?:(?:/|de|sobre)\s*(\d+(?:[.,]\d+)?))?", re.I)
_RANK = re.compile(r"[#nN°º.\s]*(\d{1,4})\s*[°ºª.]*\s*(?:(?:de|/)\s*(\d{1,4}))?(?:\s+[A-Za-zñÑ ]{0,25})?")
_CONTEO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:\s*[A-Za-zñÑ.]{0,15})?")
_NOMBRE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ.'’\- ]{2,59}")
_NO_NOMBRE = {"partido", "frente", "intendente", "intendenta", "municipio", "ver", "mas", "ficha", "datos", "control",
              "indice", "transparencia", "seguridad", "servicios", "ranking", "provincia", "buenos", "aires", "alianza"}
_MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}


_PILAR = re.compile(r"\(\s*(\d+(?:,\d+)?)\s*%\s*del\s+[ií]ndice\s*\)\s*:\s*(\d+(?:[.,]\d+)?)\s*de\s*100\.?")


def _c_homicidios(t: str, et: str):
    m = re.match(r"^([\d.]+(?:,\d+)?)\s+cada\s+100\.?000\s+hab(?:itantes|\.)?(?:\s*\(\s*(\d[\d.]*)\s+v[ií]ctimas?\s+en\s+(\d{4})\s*\))?", t, re.I)
    if not m and (simple := re.fullmatch(r"(\d+(?:,\d+)?)(?:\s*(?:por|cada|/)\s*100\.?000(?:\s*hab(?:itantes|\.)?)?)?", t, re.I)):
        return {"homicidios_tasa_100k": C.parse_num(simple.group(1))}  # solo la tasa, sin víctimas
    if not m or C.parse_num(m.group(1)) is None:
        return None
    d: dict = {"homicidios_tasa_100k": C.parse_num(m.group(1))}
    if p := re.search(r"(\d{4}\s*-\s*\d{4})", et):
        d["homicidios_periodo"] = re.sub(r"\s+", "", p.group(1))
    if m.group(2):
        d["victimas_homicidio_ultimo_anio"] = int(m.group(2).replace(".", ""))
        d["victimas_homicidio_anio"] = int(m.group(3))
    return d


def _c_empleo(t: str, et: str):
    """'4.125 (2026-08; empleados ocupados, ...)' vs '3.720 (2023; cargos presupuestados, ...)': nunca se mezclan."""
    m = re.match(r"^\s*(\d{1,3}(?:\.\d{3})+|\d+)\s*\(\s*(\d{4}(?:-\d{2})?)\s*;\s*([^,;)]*)", t)
    if not m:
        return None
    tipo, n = C.normalizar_texto(m.group(3)), int(m.group(1).replace(".", ""))
    if "ocupad" in tipo:
        return {"empleados_municipales": n, "tipo_dato_empleo": "EMPLEADOS_OCUPADOS", "empleo_periodo": m.group(2)}
    if "presupuest" in tipo:  # no es personal efectivo: no va a empleados_municipales
        return {"cargos_presupuestados": n, "tipo_dato_empleo": "CARGOS_PRESUPUESTADOS", "empleo_periodo": m.group(2)}
    return None


def _c_fallo(t: str, et: str):
    v = t.strip().rstrip(".").strip()
    if not v or len(v) > 120:
        return None
    d = {"ultimo_fallo_htc": v}
    if y := re.search(r"\((\d{4})\)", et):
        d["ejercicio_fallo_htc"] = y.group(1)
    return d


COMPUESTOS = {"homicidios_tasa_100k": _c_homicidios, "empleados_municipales": _c_empleo, "ultimo_fallo_htc": _c_fallo}


# El portal escribe "(PARTIDO · frente X)": "frente"/"coalición" en MINÚSCULA es el conector de la alianza. Con mayúscula inicial
# forma parte del nombre propio de un partido ("Frente Renovador", "Frente Grande") y no es una alianza.
_CONECTOR = re.compile(r"(frente|coalici[oó]n)\s+(.+)")


def _p_intendente(m):
    out = [("fecha_asuncion", m.group(1), "'en funciones desde' del portal")]
    partido, extras = None, []
    for i, p in enumerate(x.strip() for x in re.split(r"\s*[·•|]\s*", m.group(2)) if x.strip()):
        if mk := _CONECTOR.fullmatch(p):
            campo = "frente_electoral" if mk.group(1) == "frente" else "coalicion_actual"
            out.append((campo, mk.group(2).strip(), "tras el conector en minúscula del portal"))
        elif i == 0:
            partido = p  # el nombre se conserva completo aunque empiece con "Frente"
        else:
            extras.append(p)  # no se clasifica sin evidencia
    if partido:
        obs = "primer elemento entre paréntesis del portal (el portal no distingue partido/frente)"
        out.append(("partido_politico", partido, obs + (f"; elementos sin clasificar: {' | '.join(extras)}" if extras else "")))
    return out


def _p_seccion(m):
    out = [("seccion_electoral", m.group(1), "")]
    if m.group(2):
        out.append(("grupo_comparacion", m.group(2).strip(), ""))
    return out


# Oraciones completas del portal que contienen varios datos (regex, función -> [(campo, valor, obs)]).
PATRONES = [
    (re.compile(r"^(\d+)\s+se[ñn]ales?\s+de\s+control", re.I), lambda m: [("señales_control", int(m.group(1)), "")]),
    (re.compile(r"^,?\s*en funciones desde el (\d{4}-\d{2}-\d{2})\s*\((.+?)\)\.?\s*$", re.I), _p_intendente),
    (re.compile(r"\(\s*secci[oó]n electoral\s+(\d+)(?:\s*,\s*grupo\s+([^)]+?))?\s*\)", re.I), _p_seccion),
    (re.compile(r"^Datos actualizados al (\d{4}-\d{2}-\d{2})", re.I), lambda m: [("fecha_actualizacion_portal", m.group(1), "")]),
]


def es_ruido(t: str) -> bool:
    return bool(_RUIDO.match(t.strip()))


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


def parse_fecha(v: str) -> str | None:
    v = v.strip()
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", v):
        return m.group(0)
    if m := re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if m := re.search(r"(\d{1,2}) de (\w+) de (\d{4})", C.normalizar_texto(v)):
        if m.group(2) in _MESES:
            return f"{m.group(3)}-{_MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def validar_valor(campo: str, token: str, etiqueta: str = "") -> tuple[object | None, str]:
    """(valor normalizado, '') o (None, motivo del rechazo)."""
    tipo, t = TIPOS[campo], token.strip()
    if campo in COMPUESTOS:  # un mismo texto aporta varios campos
        d = COMPUESTOS[campo](t, etiqueta)
        return (d, "") if d else (None, "formato compuesto no reconocido")
    if not t or len(t) > 160:
        return None, "vacío o demasiado largo"
    if tipo == "num":
        if (mp := _PILAR.fullmatch(t)) and campo in PUNTAJES:  # "(50 % del índice): 50,0 de 100." -> 50,0 (el peso no es el puntaje)
            num = C.parse_num(mp.group(2))
            return (num, "") if num is not None and 0 <= num <= 100 else (None, "fuera de 0-100")
        m = _NUM.fullmatch(t)
        if not m:
            return None, "formato no numérico"
        num = C.parse_num(m.group(1))
        if num is None:
            return None, "número ilegible"
        if m.group(2) == "%" and campo not in PCT:
            return None, "porcentaje en un campo de puntaje (¿peso del pilar?)"
        if m.group(3) and C.parse_num(m.group(3)) != 100 and campo in PUNTAJES:
            return None, f"puntaje sobre escala {m.group(3)} (no 0-100)"
        if (campo in PUNTAJES or campo in PCT) and not 0 <= num <= 100:
            return None, "fuera de 0-100"
        return num, ""
    if tipo in ("int", "poblacion"):
        if campo.startswith("ranking"):
            m = _RANK.fullmatch(t)
            return (int(m.group(1)), "") if m else (None, "formato de ranking no reconocido")
        m = _CONTEO.fullmatch(t)
        if not m:
            return None, "formato de cantidad no reconocido"
        n = int(m.group(1).replace(".", ""))
        return (n, "") if tipo != "poblacion" or n >= 1000 else (None, "población implausible")
    if tipo == "indec":
        return (t, "") if re.fullmatch(r"06\d{3}", t) else (None, "código de partido INDEC inválido (se esperan 5 dígitos que empiecen con 06)")
    if tipo == "semaforo":
        v = _semaforo(t) if len(t) <= 30 else None
        return (v, "") if v else (None, "no es un color de semáforo")
    if tipo == "bool":
        v = _bool(t)
        return (v, "") if v else (None, "no es sí/no")
    if tipo == "fecha":
        v = parse_fecha(t)
        return (v, "") if v else (None, "fecha incompleta o ilegible")
    if tipo == "nombre":
        pal = t.split()
        if not (2 <= len(pal) <= 6 and _NOMBRE.fullmatch(t)) or any(C.normalizar_texto(p) in _NO_NOMBRE for p in pal):
            return None, "no parece un nombre de persona"
        return t, ""
    return (t, "") if not es_ruido(t) else (None, "ruido")


# ---------------------------------------------------------------- tokenización
_SALTAR = {"script", "style", "noscript", "template", "svg", "head", "title"}
_ENCABEZADOS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _limpiar(t: str) -> str:
    return re.sub(r"\s+", " ", str(t).replace("\xa0", " ")).strip()


def _aplanar_json(o, clave: str = "") -> list[tuple[str, str]]:
    """Pares (clave de hoja, valor escalar) de un JSON; camelCase/snake_case -> palabras."""
    res: list[tuple[str, str]] = []
    if isinstance(o, dict):
        for k, v in o.items():
            res += _aplanar_json(v, str(k))
    elif isinstance(o, list):
        for v in o[:200]:
            res += _aplanar_json(v, clave)
    elif isinstance(o, (str, int, float)) and not isinstance(o, bool) and clave:
        res.append((re.sub(r"([a-z])([A-Z])", r"\1 \2", clave).replace("_", " "), str(o)))
    return res


def tokenizar(html: str) -> list[tuple[str, bool]]:
    """Fragmentos de texto en orden de documento: (texto, es_encabezado). Solo se lee texto."""
    soup = BeautifulSoup(html, "lxml")
    out: list[tuple[str, bool]] = []
    json_pares: list[tuple[str, str]] = []
    for sc in soup.find_all("script"):  # datos embebidos: solo se parsean como JSON
        if (sc.get("type") or "").lower() in ("application/json", "application/ld+json") or sc.get("id") == "__NEXT_DATA__":
            try:
                json_pares += _aplanar_json(json.loads(sc.string or ""))
            except (ValueError, TypeError):
                pass

    def rec(nodo):
        for h in nodo.children:
            if isinstance(h, Comment):
                continue
            if isinstance(h, NavigableString):
                if t := _limpiar(h):
                    out.append((t, False))
            elif h.name in _SALTAR:
                continue
            elif h.name in _ENCABEZADOS or h.get("role") == "heading":
                if t := _limpiar(h.get_text(" ", strip=True)):
                    out.append((t, True))
            else:
                rec(h)
    rec(soup.body or soup)
    if json_pares:
        out.append(("json", True))
        for k, v in json_pares:
            out += [(_limpiar(k), False), (_limpiar(v), False)]
    return out


# ---------------------------------------------------------------- análisis
def _separar(txt: str) -> tuple[str, str | None]:
    """'Etiqueta: valor' -> (etiqueta, valor). Sin dos puntos devuelve (txt, None)."""
    if ":" in txt and len(txt) <= 200:
        k, _, v = txt.partition(":")
        return k.strip(), (v.strip() or None)
    return txt.strip(), None


def analizar_ficha(html: str) -> dict:
    return analizar_tokens(tokenizar(html))


def analizar_tokens(toks: list[tuple[str, bool]]) -> dict:
    n = len(toks)
    sec_ef: list[str] = []   # sección (texto original) vigente en cada fragmento
    sec_n: list[str] = []    # ídem normalizada; incluye títulos de sección sin etiqueta <hN>
    sec, sec_norm = "", ""
    for t, enc in toks:
        nt = C.normalizar_texto(t)
        if enc or nt in SECCIONES_CONOCIDAS:
            sec, sec_norm = t, nt
        sec_ef.append(sec)
        sec_n.append(sec_norm)
    hallados: dict[str, dict] = {}
    contradicciones: list[dict] = []
    rechazados: list[str] = []
    consumido: set[int] = set()

    def ignorada(j: int) -> bool:
        return any(x in sec_n[j] for x in IGNORAR_SECCIONES)

    def es_etiqueta(j: int) -> bool:
        return not toks[j][1] and not ignorada(j) and clasificar(_separar(toks[j][0])[0], sec_n[j]) is not None

    def registrar(campo, valor, original, etiqueta, seccion, obs="", conf="MEDIO"):
        if campo in hallados:
            if hallados[campo]["valor"] != valor:
                contradicciones.append({"campo": campo, "a": hallados[campo]["original"], "b": original,
                                        "seccion_a": hallados[campo]["seccion"], "seccion_b": seccion})
            return
        hallados[campo] = {"valor": valor, "original": str(original).strip(), "etiqueta": str(etiqueta).strip(),
                           "seccion": seccion, "confianza": conf, "obs": obs}

    # ---- pasada 0: oraciones con varios datos (intendente, sección electoral, señales, fecha del portal)
    for i, (txt, enc) in enumerate(toks):
        if enc or "comparar" in sec_n[i]:
            continue
        for rx, fn in PATRONES:
            if m := rx.search(txt):
                for campo, valor, obs in fn(m):
                    registrar(campo, valor, txt[:160], txt[:80], sec_ef[i], obs)
                consumido.add(i)
                break

    # ---- pasada 1: etiquetas reconocidas
    etiquetas: list[dict] = []
    for i, (txt, enc) in enumerate(toks):
        if enc or ignorada(i) or i in consumido:
            continue
        etiqueta, inline = _separar(txt)
        campo = clasificar(etiqueta, sec_n[i])
        if campo is None and inline is None:  # "Índice municipal 12,3" en un solo fragmento
            m = re.match(r"^(.*?[A-Za-zñÑáéíóú])\s+([+-]?\d[\d.,]*\s*(?:%|puntos?|pts?\.?)?(?:\s*(?:/|de|sobre)\s*\d+)?)$", txt)
            if m and (c2 := clasificar(m.group(1), sec_n[i])):
                campo, etiqueta, inline = c2, m.group(1), m.group(2)
        if campo is not None:
            etiquetas.append(dict(i=i, campo=campo, etiqueta=etiqueta, inline=inline, txt=txt))

    # ---- candidatos de valor: después de la etiqueta y (solo numéricos) antes de ella
    def adelante(e: dict):
        i, campo, tipo, vistos, motivo = e["i"], e["campo"], TIPOS[e["campo"]], 0, ""
        for j in range(i + 1, min(n, i + 6)):
            if toks[j][1]:
                break
            if es_ruido(toks[j][0]):
                continue
            if es_etiqueta(j) and tipo in ("txt", "nombre", "fecha", "poblacion"):
                break
            v, mot = validar_valor(campo, toks[j][0], e["etiqueta"])
            if v is not None:
                return j, v, toks[j][0], motivo
            if es_etiqueta(j):
                break
            motivo = mot or motivo
            if re.search(r"\d", toks[j][0]):
                e.setdefault("rech", []).append(f"{sec_ef[i]} > {e['etiqueta']} = {toks[j][0][:30]}: {mot}")
            vistos += 1
            if vistos >= 3:
                break
        return None

    def atras(e: dict):
        i, campo = e["i"], e["campo"]
        if TIPOS[campo] not in ("num", "int", "semaforo", "poblacion"):
            return None
        for j in range(i - 1, max(-1, i - 4), -1):
            if toks[j][1] or es_etiqueta(j):
                break
            if es_ruido(toks[j][0]):
                continue
            v, _ = validar_valor(campo, toks[j][0])
            return (j, v, toks[j][0], "") if v is not None else None
        return None

    for e in etiquetas:
        e["ad"] = None if e["inline"] is not None else adelante(e)
        e["at"] = None if e["inline"] is not None else atras(e)
    votos_ad = sum(1 for e in etiquetas if e["ad"] and not e["at"])
    votos_at = sum(1 for e in etiquetas if e["at"] and not e["ad"])
    orientacion = "atras" if votos_at > votos_ad else "adelante"  # tarjetas "12,3 / Índice" vs "Índice: 12,3"

    # ---- pasada 2: asignación (cada valor se usa una sola vez)
    for e in etiquetas:
        i, campo, etiqueta = e["i"], e["campo"], e["etiqueta"]
        if i in consumido:
            continue
        valor, original, usados, motivo = None, "", [], ""
        if TIPOS[campo] == "fecha" and e["inline"] is None and re.search(r"\d", e["txt"]):
            valor, motivo = validar_valor(campo, e["txt"])  # "Actualizado el 15/10/2026"
            original = e["txt"]
        if valor is None and e["inline"] is not None:
            valor, motivo = validar_valor(campo, e["inline"], etiqueta)
            original = e["inline"]
        if valor is None and e["inline"] is None:
            opciones = [e["ad"], e["at"]] if orientacion == "adelante" else [e["at"], e["ad"]]
            for op in opciones:
                if op and op[0] not in consumido:
                    usados, valor, original = [op[0]], op[1], op[2]
                    break
            if valor is None:
                rechazados += e.get("rech", [])
        if valor is None:
            if sec_n[i] in SECCIONES_CONOCIDAS:  # fuera de las secciones de datos todo es ruido de navegación
                if e["inline"] is None and not e.get("rech"):
                    rechazados.append(f"{sec_ef[i]} > {etiqueta}: etiqueta reconocida ({campo}) sin valor")
                elif e["inline"] is not None:
                    rechazados.append(f"{sec_ef[i]} > {etiqueta} = {e['inline'][:30]}: {motivo}")
            continue
        if campo == "poblacion_2022":  # exige evidencia del censo 2022
            ctx = " ".join(toks[k][0] for k in range(i, min(n, (usados[0] if usados else i) + 3)))
            if "2022" not in ctx and "censo" not in C.normalizar_texto(ctx):
                rechazados.append(f"{sec_ef[i]} > {etiqueta} = {original[:30]}: población sin año 2022 verificable")
                continue
        consumido.update(usados + [i])
        if isinstance(valor, dict):  # un mismo texto aporta varios campos (tasa+víctimas, empleo+tipo+período...)
            for c2, v2 in valor.items():
                registrar(c2, v2, original, etiqueta, sec_ef[i], "campo derivado del mismo texto del portal")
        else:
            mp = _PILAR.fullmatch(original.strip())
            registrar(campo, valor, original, etiqueta, sec_ef[i], f"peso informado: {mp.group(1)} % del índice" if mp else "")

    # Condición del cargo, solo si la etiqueta del portal la dice (interino/suplente/reemplazante).
    if h := hallados.get("intendente_nombre_completo"):
        ne = C.normalizar_texto(h["etiqueta"])
        for pal, cond in (("interin", "INTERINO"), ("suplente", "SUPLENTE"), ("reemplaz", "REEMPLAZANTE")):
            if pal in ne:
                registrar("intendente_condicion", cond, h["etiqueta"], h["etiqueta"], h["seccion"], "deducida de la etiqueta del portal")
                break
    # Nombre del intendente por posición en su sección.
    if "intendente_nombre_completo" not in hallados:
        for i, (t, enc) in enumerate(toks):
            if enc or i in consumido or ignorada(i) or "intendente" not in C.normalizar_texto(sec_ef[i]) or es_etiqueta(i):
                continue
            v, _ = validar_valor("intendente_nombre_completo", t)
            if v:
                hallados["intendente_nombre_completo"] = {
                    "valor": v, "original": t, "etiqueta": "(primer nombre en la sección Intendente)",
                    "seccion": sec_ef[i], "confianza": "BAJO", "obs": "inferido por posición; confirmar con fuente oficial"}
                consumido.add(i)
                break
    # Etiquetas no reconocidas: texto seguido de algo que parece un valor.
    no_rec: list[str] = []
    for i, (t, enc) in enumerate(toks[:-1]):
        if enc or i in consumido or ignorada(i) or len(t) > 60 or not re.search(r"[A-Za-zñáéíóú]", t):
            continue
        et, inline = _separar(t)
        if clasificar(et, sec_n[i]) or es_ruido(t) or C.normalizar_texto(t) in SECCIONES_CONOCIDAS:
            continue
        sig = inline if inline is not None else toks[i + 1][0]
        if inline is None and toks[i + 1][1]:
            continue
        if "://" in t or et.startswith("@") or sig.startswith(("@", "http")):  # metadatos JSON-LD
            continue
        if re.search(r"\d", sig) or _semaforo(sig) or sec_ef[i] == "json":
            item = f"{sec_ef[i] or '(sin sección)'} > {et[:40]} = {sig[:30]}"
            if item not in no_rec:
                no_rec.append(item)
    return {"hallados": hallados, "contradicciones": contradicciones, "no_reconocidas": no_rec,
            "rechazados": rechazados, "secciones": [t for t, e in toks if e], "n_tokens": n, "tokens": toks,
            "seccion_por_token": sec_ef, "orientacion": orientacion}


def interpretar_pagina(html: str) -> tuple[dict[str, dict], list[dict]]:
    a = analizar_ficha(html)
    return a["hallados"], a["contradicciones"]


def etiquetas_no_reconocidas(html: str, maximo: int = 15) -> list[str]:
    return analizar_ficha(html)["no_reconocidas"][:maximo]


def estructura_texto(html: str, maximo: int = 700) -> str:
    """Volcado legible de la estructura para depurar: sección, fragmentos y qué se reconoció."""
    a = analizar_ficha(html)
    l = [f"# Estructura de la ficha: {a['n_tokens']} fragmentos; secciones: {a['secciones']}; orientación valor/etiqueta: {a['orientacion']}", ""]
    for i, ((t, enc), sec) in enumerate(zip(a["tokens"][:maximo], a["seccion_por_token"])):
        l.append(f"{i:4d} {'H ' if enc else '  '}[{sec[:28]}] {t[:140]}")
    l += ["", "# Reconocidos"] + [f"{c} = {d['valor']!r}  <- '{d['etiqueta']}' en '{d['seccion']}' ({d['confianza']})"
                                  for c, d in a["hallados"].items()]
    l += ["", "# Rechazados"] + a["rechazados"] + ["", "# Etiquetas no reconocidas"] + a["no_reconocidas"]
    return "\n".join(l) + "\n"
