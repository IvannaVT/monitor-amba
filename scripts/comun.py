"""Utilidades comunes: esquemas de los 8 CSV, lectura/escritura y formatos.

Formato (spec sec. 21): UTF-8 con BOM, separador ';', decimales con coma,
fechas AAAA-MM-DD, faltantes en blanco, protección contra fórmulas en CSV.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_ACTUAL = RAIZ / "data" / "actual"
DIR_HISTORICO = RAIZ / "data" / "historico"
DIR_CONFIG = RAIZ / "config"
ARCHIVO_MUNICIPIOS_CFG = DIR_CONFIG / "municipios_amba.csv"
ARCHIVO_REGLAS = DIR_CONFIG / "reglas_alertas.json"
ARCHIVO_NOMBRES = DIR_CONFIG / "intendentes_nombres.csv"

F_MUNICIPIOS = "01_amba_municipios.csv"
F_BLOQUES = "02_amba_concejos_bloques.csv"
F_CONTACTOS = "03_amba_contactos_protocolo.csv"
F_INDICADORES = "04_amba_indicadores.csv"
F_FUENTES = "05_amba_fuentes.csv"
F_INCIDENCIAS = "06_amba_incidencias.csv"
F_CABA = "07_caba_institucional.csv"
F_ALERTAS = "08_amba_alertas_cambios.csv"


def _c(texto: str) -> list[str]:
    return [x.strip() for x in texto.replace("\n", " ").split(",") if x.strip()]


# Esquemas literales de la especificación, sec. 16.
ESQUEMAS: dict[str, list[str]] = {
    F_MUNICIPIOS: _c(
        "municipio_id, municipio, seccion_electoral, poblacion_2022, sitio_oficial, "
        "intendente_nombre, intendente_apellido, intendente_nombre_completo, "
        "intendente_condicion, fecha_asuncion, partido_politico, frente_electoral, "
        "coalicion_actual, presidente_hcd, total_bancas, bancas_oficialismo, "
        "bancas_aliadas, bancas_oposicion, bancas_independientes, bancas_sin_verificar, "
        "porcentaje_oficialismo, porcentaje_apoyo_confirmado, situacion_legislativa, "
        "indice_global, ranking_provincial, transparencia_puntaje, transparencia_semaforo, "
        "servicios_seguridad_puntaje, seguridad_puntaje, control_puntaje, email_municipal, "
        "telefono_municipal, sitio_hcd, fecha_verificacion, snapshot_id"
    ),
    F_BLOQUES: _c(
        "municipio_id, bloque_id, bloque_nombre, partido_o_frente, bancas, "
        "presidente_bloque_nombre, presidente_bloque_apellido, posicion_frente_intendente, "
        "tipo_alineamiento, documento_respaldo, url_fuente, fecha_composicion, "
        "fecha_verificacion, snapshot_id"
    ),
    F_CONTACTOS: _c(
        "municipio_id, organismo, dependencia, tipo_contacto, responsable_nombre, "
        "responsable_apellido, cargo, email_institucional, telefono_institucional, interno, "
        "direccion, horario_atencion, sitio_web, url_fuente, fecha_verificacion, "
        "estado_contacto, snapshot_id"
    ),
    F_INDICADORES: _c(
        "municipio_id, snapshot_id, fecha_extraccion, fecha_actualizacion_portal, "
        "indice_global, ranking_provincial, ranking_pares, grupo_comparacion, "
        "transparencia_puntaje, transparencia_relevamiento_propio, transparencia_asap, "
        "transparencia_semaforo, presupuesto_publicado, ejecucion_publicada, "
        "servicios_seguridad_puntaje, seguridad_puntaje, homicidios_tasa_100k, "
        "homicidios_periodo, victimas_homicidio_ultimo_anio, victimas_homicidio_anio, "
        "cobertura_agua_pct, cobertura_cloacas_pct, cobertura_gas_pct, control_puntaje, "
        "ultimo_fallo_htc, ejercicio_fallo_htc, señales_control, cargos_htc_monto, "
        "multas_htc_monto, presupuesto_total, presupuesto_anio, gasto_por_habitante, "
        "gasto_periodo, empleados_municipales, cargos_presupuestados, tipo_dato_empleo, empleo_periodo, url_fuente"
    ),
    F_FUENTES: _c(
        "fuente_id, municipio_id, entidad, campo_verificado, valor_obtenido, fuente_tipo, "
        "organismo, documento_titulo, documento_url, fecha_documento, periodo_referencia, "
        "fecha_consulta, metodo_extraccion, nivel_confianza, observaciones, snapshot_id"
    ),
    F_INCIDENCIAS: _c(
        "incidencia_id, municipio_id, campo, tipo_incidencia, descripcion, url_afectada, "
        "fuente_1, fuente_2, impacto, accion_recomendada, estado_resolucion, "
        "fecha_deteccion, fecha_ultima_revision, snapshot_id"
    ),
    F_CABA: _c(
        "jurisdiccion_id, jurisdiccion, jefe_gobierno_nombre, jefe_gobierno_apellido, cargo, "
        "condicion_funcional, partido_politico, coalicion_actual, fecha_asuncion, "
        "legislatura_total_bancas, legislatura_bancas_oficialismo, legislatura_bancas_aliadas, "
        "legislatura_bancas_oposicion, legislatura_bancas_sin_verificar, presidente_legislatura, "
        "situacion_legislativa, contacto_protocolo, email_institucional, "
        "telefono_institucional, sitio_gobierno, sitio_legislatura, fuentes, "
        "fecha_verificacion, snapshot_id"
    ),
    F_ALERTAS: _c(
        "alerta_id, municipio_id, snapshot_anterior, snapshot_actual, fecha_deteccion, "
        "fecha_evento, capa_analitica, categoria_alerta, variable, valor_anterior, "
        "valor_actual, variacion_absoluta, variacion_relativa_pct, severidad, "
        "impacto_institucional, descripcion, estado_verificacion, fuente_documental, "
        "url_fuente, estado_seguimiento"
    ),
}

# Clave natural de cada archivo (para duplicados y fusión incremental).
CLAVES: dict[str, tuple[str, ...]] = {
    F_MUNICIPIOS: ("municipio_id",),
    F_BLOQUES: ("municipio_id", "bloque_id"),
    F_CONTACTOS: ("municipio_id", "organismo", "dependencia"),
    F_INDICADORES: ("municipio_id", "snapshot_id"),
    F_FUENTES: ("fuente_id",),
    F_INCIDENCIAS: ("incidencia_id",),
    F_CABA: ("jurisdiccion_id",),
    F_ALERTAS: ("alerta_id",),
}

NIVELES_CONFIANZA = {"ALTO", "MEDIO", "BAJO", "SIN_VERIFICAR"}
SEMAFOROS = {"VERDE", "AMARILLO", "ROJO"}
SITUACIONES_LEGISLATIVAS = {
    "MAYORIA_PROPIA", "MAYORIA_CON_ALIADOS", "MINORIA", "EMPATE", "SIN_VERIFICAR",
}
SEVERIDADES = {"CRITICA", "ALTA", "MEDIA", "INFORMATIVA"}


# ---------------------------------------------------------------- texto / ids
def normalizar_texto(s: str) -> str:
    """Minúsculas, sin tildes, solo alfanuméricos separados por un espacio."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def slug(s: str) -> str:
    return normalizar_texto(s).replace(" ", "_")


def id_estable(*partes: object) -> str:
    base = "|".join("" if p is None else str(p) for p in partes)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_desde(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S") + f"{dt.microsecond // 1000:03d}Z"


# ------------------------------------------------------------- números / csv
_NUM_RE = re.compile(r"^[+-]?\d+(?:,\d+)?$")
_FORMULA_INICIO = ("=", "+", "-", "@", "\t", "\r")


def formatear(v: object) -> str:
    """Valor Python -> celda CSV (coma decimal, vacío para None)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "SI" if v else "NO"
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(round(v, 6)).replace(".", ",")
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    return sanear_celda(str(v))


def sanear_celda(s: str) -> str:
    """Neutraliza inyección de fórmulas (=, +, -, @) salvo números válidos."""
    if s and s[0] in _FORMULA_INICIO and not _NUM_RE.match(s):
        return "'" + s
    return s


def parse_num(s: object) -> float | None:
    """Celda CSV o texto es-AR -> float. '1.234,5' y '1234,5' y '12.5' válidos."""
    if s is None:
        return None
    t = str(s).strip().replace("%", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", t):  # 1.234.567 -> miles
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def leer_csv(ruta: Path) -> list[dict[str, str]]:
    if not Path(ruta).exists():
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f, delimiter=";")]


def serializar_csv(filas: list[dict], columnas: list[str]) -> str:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(columnas)
    for fila in filas:
        w.writerow([formatear(fila.get(c)) for c in columnas])
    return buf.getvalue()


def escribir_csv(ruta: Path, filas: list[dict], columnas: list[str]) -> None:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        f.write(serializar_csv(filas, columnas))


_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "da", "das", "do", "dos", "di", "van", "von", "san", "santa", "mc", "mac"}


def cargar_nombres_override(ruta: Path = ARCHIVO_NOMBRES) -> dict[str, tuple[str, str]]:
    """Separaciones revisadas a mano: nombre completo exacto -> (nombre, apellido)."""
    return {r["nombre_completo"].strip(): (r["nombre"].strip(), r["apellido"].strip())
            for r in leer_csv(ruta) if r.get("nombre_completo") and r.get("nombre") and r.get("apellido")}


def separar_nombre(completo: str, overrides: dict[str, tuple[str, str]] | None = None) -> tuple[str, str, str]:
    """(nombre, apellido, método). Conservador: solo separa cuando no hay ambigüedad.

    - 'override_config': figura en config/intendentes_nombres.csv (revisado a mano).
    - 'dos_palabras': exactamente dos palabras sin partículas, guiones, apóstrofos ni puntos.
    - 'no_separado': 3+ palabras, partículas (de, del, la...) u otra ambigüedad -> se deja vacío.
    El nombre completo original nunca se modifica.
    """
    c = " ".join((completo or "").split())
    if overrides and c in overrides:
        return overrides[c][0], overrides[c][1], "override_config"
    p = c.split(" ")
    if len(p) == 2 and not any(x.lower().strip(".") in _PARTICULAS or re.search(r"[-'’.]", x) for x in p):
        return p[0], p[1], "dos_palabras"
    return "", "", "no_separado"


def cargar_municipios_cfg(ruta: Path = ARCHIVO_MUNICIPIOS_CFG) -> list[dict[str, str]]:
    return leer_csv(ruta)
