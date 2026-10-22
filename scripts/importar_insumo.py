#!/usr/bin/env python3
"""Incorpora la base preliminar del Ejecutivo (xlsx) como INSUMO separado de data/actual.

Salida (data/insumos/ejecutivo_preliminar/): municipios.csv, contactos.csv, fuentes.csv, discrepancias.csv.
Conserva fuentes y estados originales; no inventa ni completa datos; no toca data/actual ni los indicadores.
Alcance: Ejecutivo municipal, intendente en funciones, partido, alianza y Protocolo/Ceremonial (HCD y otras dimensiones quedan fuera).

Uso: python scripts/importar_insumo.py [xlsx] [--salida DIR]      (requiere openpyxl; solo para importar)
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

DIR = C.RAIZ / "data" / "insumos" / "ejecutivo_preliminar"
XLSX = DIR / "origen" / "Base_Ejecutivo_AMBA_2026-10-22.xlsx"
PROVEEDORES_PUBLICOS = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.ar", "live.com", "icloud.com", "proton.me")
EMERGENCIA = re.compile(r"(?<![\d-])(911|10[0-9]|14[45]|13[67])(?![\d-])")   # 147 (atención general) sí se conserva
EMAIL = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
COL_MUN = ["municipio", "municipio_id", "intendente_en_funciones", "condicion_funcional", "partido_politico", "alianza_reportada",
           "estado_alianza", "situacion_protocolo", "area_contacto", "email_publicado", "telefono_publicado", "interno", "contacto_id",
           "estado_autoridad", "observaciones_politicas", "proximo_paso", "sitio_municipal", "tipo_fuente_autoridad", "fuente_autoridad_url",
           "fuente_partido_url"]
COL_CON = ["municipio", "municipio_id", "contacto_id", "categoria", "dependencia", "responsable_publicado", "email_institucional", "tipo_casilla",
           "uso_oficial", "telefono_publicado", "interno", "direccion", "tipo_via", "estado_contacto", "fecha_consulta", "fuente_url",
           "estado_evidencia", "evidencia", "evidencia_original", "observaciones"]
COL_FUE = ["municipio", "municipio_id", "campo", "valor_registrado", "fuente_url", "tipo_fuente", "estado_evidencia", "consulta", "observaciones"]
COL_DIS = ["discrepancia_id", "municipio", "municipio_id", "tema", "prioridad", "detalle", "valor_repo", "valor_insumo", "proceso", "accion"]


def snake(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def base_host(host: str) -> str:
    h = (host or "").lower().removeprefix("www.")
    return ".".join(h.split(".")[-3:] if h.endswith((".gob.ar", ".gov.ar")) else h.split(".")[-2:])


def tipo_fuente(url: str, sitio: str) -> str:
    h = urlparse(url or "").hostname or ""
    if "wikipedia.org" in h:
        return "SECUNDARIA_WIKIPEDIA"
    if h.endswith("gba.gob.ar"):
        return "PROVINCIAL"
    if sitio and base_host(h) == base_host(urlparse(sitio).hostname or ""):
        return "MUNICIPAL"
    return "OTRA"


def tipo_casilla(email: str, sitio: str) -> tuple[str, str]:
    """Distingue el PROVEEDOR del correo del uso oficial: que figure en el sitio oficial no hace institucional a una casilla pública."""
    if not email:
        return "", ""
    dom = email.split("@")[-1].lower()
    if dom in PROVEEDORES_PUBLICOS:
        return "PROVEEDOR_PUBLICO", "PUBLICADA EN SITIO OFICIAL; CASILLA DE PROVEEDOR PÚBLICO: CONFIRMAR QUE ES DE USO INSTITUCIONAL"
    if base_host(dom) == base_host(urlparse(sitio or "").hostname or ""):
        return "DOMINIO_MUNICIPAL", "DOMINIO DEL SITIO OFICIAL"
    if dom.endswith((".gob.ar", ".gov.ar")):
        return "DOMINIO_GOB_DISTINTO", "DOMINIO GOB/GOV DISTINTO DEL SITIO OFICIAL: VERIFICAR"
    return "OTRO_DOMINIO", "DOMINIO AJENO AL SITIO OFICIAL: VERIFICAR"


def categoria(dep: str, via: str) -> str:
    t = f"{dep} {via}".lower()
    if "ceremonial" in t or "protocolo" in t:
        return "PROTOCOLO_CEREMONIAL"
    if any(p in t for p in ("intendencia", "privada", "gobierno", "relaciones institucionales", "comunicación institucional", "prensa", "gestión pública")):
        return "EJECUTIVO_INSTITUCIONAL"
    return "DERIVACION_GENERAL"


def depurar_evidencia(ev: str, email: str, tel: str) -> tuple[str, str]:
    """Recorta el texto de contexto alrededor del dato publicado (sin agregar nada). Devuelve (evidencia, estado)."""
    ev = re.sub(r"\s+", " ", ev or "").strip()
    if not ev:
        return "", "SIN_EVIDENCIA"
    if email:
        pos, largo = ev.lower().find(email.lower()), len(email)
        if pos < 0:
            return ev[:200], "EL_EMAIL_NO_FIGURA_EN_LA_EVIDENCIA"
    else:
        pos, largo = _buscar_telefono(ev, tel)
        if pos < 0:
            return ev[:200], "DATO_NO_LOCALIZADO_EN_LA_EVIDENCIA"
    a, b = max(0, pos - 90), min(len(ev), pos + largo + 40)
    if a > 0 and ev[a - 1] != " ":
        a = ev.find(" ", a) + 1 or a
    if b < len(ev) and ev[b] != " ":
        corte = ev.rfind(" ", pos + largo, b)
        b = corte if corte > 0 else b
    frag = EMERGENCIA.sub("[número de emergencia omitido]", ev[a:b].strip())
    if a == 0 and frag[:1].islower() and " " in frag:     # el texto original arranca a mitad de palabra: se descarta el fragmento
        frag = frag.split(" ", 1)[1]
    return frag, "DEPURADA" if frag != ev else "SIN_CAMBIOS"


def _buscar_telefono(ev: str, tel: str) -> tuple[int, int]:
    """Posición del primer número de `tel` que figura en el texto (compara dígitos, tolera separadores)."""
    for num in re.findall(r"\d[\d\s\-()]*\d", tel or ""):
        dig = re.sub(r"\D", "", num)
        if len(dig) < 3:
            continue
        for m in re.finditer(r"\d[\d\s\-()]*\d", ev):
            d2 = re.sub(r"\D", "", m.group())
            if d2 == dig or (len(dig) >= 6 and d2.endswith(dig[-6:])):
                return m.start(), len(m.group())
    return -1, 0


def leer_hojas(xlsx: Path) -> tuple[list[dict], list[dict], list[dict]]:
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, data_only=True)

    def hoja(n):
        ws = wb[n]
        h = [snake(str(c.value)) for c in ws[1]]
        return [dict(zip(h, [("" if c.value is None else (c.value.strftime("%Y-%m-%d") if hasattr(c.value, "strftime") else str(c.value))) for c in r]))
                for r in ws.iter_rows(min_row=2) if any(c.value for c in r)]
    alias = {"estado_de_la_alianza": "estado_alianza", "situacion_de_protocolo": "situacion_protocolo", "area_de_contacto": "area_contacto"}
    mun = [{alias.get(k, k): v for k, v in r.items()} for r in hoja("Municipios")]
    return mun, hoja("Contactos Ejecutivo"), hoja("Fuentes")


def construir(mun: list[dict], con: list[dict], fue: list[dict], sitios: dict[str, dict], cfg: list[dict]) -> dict[str, list[dict]]:
    ids = {c["municipio"]: c["municipio_id"] for c in cfg} | {"CABA": "caba"}
    sitio_x = {m["municipio"]: m["sitio_municipal"] for m in mun}
    f_aut = {f["municipio"]: f for f in fue if f["campo"] == "Autoridad ejecutiva"}
    f_par = {f["municipio"]: f for f in fue if f["campo"] == "Partido y alianza"}
    M, K, F, D = [], [], [], []

    def dis(m, tema, prio, detalle, valor_repo="", valor_insumo="", proceso="MANUAL", accion=""):
        D.append({"discrepancia_id": f"D{len(D) + 1:03d}", "municipio": m, "municipio_id": ids.get(m, ""), "tema": tema, "prioridad": prio,
                  "detalle": detalle, "valor_repo": valor_repo, "valor_insumo": valor_insumo, "proceso": proceso, "accion": accion})

    for m in mun:
        n = m["municipio"]
        a, p = f_aut.get(n, {}), f_par.get(n, {})
        M.append({**{k: m.get(k, "") for k in COL_MUN if k not in ("municipio_id", "tipo_fuente_autoridad", "fuente_autoridad_url", "fuente_partido_url", "observaciones_politicas")},
                  "observaciones_politicas": m.get("observaciones_politicas", ""), "municipio_id": ids.get(n, ""),
                  "tipo_fuente_autoridad": tipo_fuente(a.get("fuente_url", ""), m["sitio_municipal"]), "fuente_autoridad_url": a.get("fuente_url", ""),
                  "fuente_partido_url": p.get("fuente_url", "")})
        tf = M[-1]["tipo_fuente_autoridad"]
        if tf != "MUNICIPAL":
            dis(n, "AUTORIDAD_SIN_DOCUMENTO_MUNICIPAL", "ALTA" if m["condicion_funcional"] != "TITULAR SEGÚN FUENTE" else "MEDIA",
                f"intendente '{m['intendente_en_funciones']}' respaldado por fuente {tf}", "", m["intendente_en_funciones"], "MANUAL",
                "Contrastar con documentación municipal reciente (sitio, boletín o decreto). No sobrescribir datos actuales con el directorio provincial sin contraste.")
        if m["condicion_funcional"] not in ("TITULAR SEGÚN FUENTE", "JEFE DE GOBIERNO"):
            dis(n, "AUTORIDAD_INTERINA_O_SUCESION", "ALTA", m["condicion_funcional"], "", m["intendente_en_funciones"], "MANUAL",
                "Confirmar el acto municipal que habilita al interino/sucesor.")
        if "provincial" in (m.get("observaciones_politicas") or "").lower():
            dis(n, "MUNICIPAL_VS_DIRECTORIO_PROVINCIAL", "ALTA", m["observaciones_politicas"], "", m["intendente_en_funciones"], "MANUAL",
                "Se mantiene lo informado por el municipio mientras sea más reciente; registrar la diferencia; no sobrescribir con el directorio provincial.")
        if m["partido_politico"] == "PENDIENTE":
            dis(n, "PARTIDO_PENDIENTE", "MEDIA", "afiliación no determinada", "", "PENDIENTE", "MANUAL", "Buscar fuente municipal o partidaria; no inferir de la coalición.")
        if m["alianza_reportada"] == "PENDIENTE" or "ACTUALIZAR" in m["estado_alianza"] and m["estado_alianza"] != "REFERENCIA DE FUENTE; ACTUALIZAR CORTE 2026":
            dis(n, "ALIANZA_PENDIENTE", "MEDIA", m["estado_alianza"], "", m["alianza_reportada"], "MANUAL", "Definir corte temporal y fuente de la alianza vigente.")
        s_repo = sitios.get(ids.get(n, ""), {}).get("sitio_oficial", "")
        if s_repo and base_host(urlparse(s_repo).hostname) != base_host(urlparse(m["sitio_municipal"]).hostname or ""):
            dis(n, "DOMINIO_DISCREPANTE", "ALTA", f"el insumo y la config usan dominios distintos (config: {sitios[ids[n]]['estado']})", s_repo, m["sitio_municipal"],
                "ACTIONS", "Verificar ambos dominios por HTTP con robots/TLS (scripts/verificar_pares_dominio.py); no cambiar la config sin resultado.")

    for c in con:
        n = c["municipio"]
        sitio = sitio_x.get(n, "")
        tc, uso = tipo_casilla(c["email_institucional"], sitio)
        ev, est = depurar_evidencia(c["evidencia"], c["email_institucional"], c["telefono_publicado"])
        K.append({"municipio": n, "municipio_id": ids.get(n, ""), "contacto_id": c["contacto_id"], "categoria": categoria(c["dependencia"], c["tipo_de_via"]),
                  "dependencia": c["dependencia"], "responsable_publicado": c["responsable_publicado"], "email_institucional": c["email_institucional"],
                  "tipo_casilla": tc, "uso_oficial": uso, "telefono_publicado": c["telefono_publicado"], "interno": c["interno"], "direccion": c["direccion"],
                  "tipo_via": c["tipo_de_via"], "estado_contacto": c["estado_del_contacto"], "fecha_consulta": c["fecha_de_consulta"], "fuente_url": c["fuente_url"],
                  "estado_evidencia": est, "evidencia": ev, "evidencia_original": c["evidencia"], "observaciones": c["observaciones"]})
        cat = K[-1]["categoria"]
        prio = "ALTA" if cat == "PROTOCOLO_CEREMONIAL" else "MEDIA"
        ref = f"{c['contacto_id']} {c['dependencia']}"
        if tc == "PROVEEDOR_PUBLICO":
            dis(n, "CASILLA_PROVEEDOR_PUBLICO", prio, f"{ref}: {c['email_institucional']} figura en el sitio oficial pero es de un proveedor público", "", c["email_institucional"],
                "ACTIONS", "Volver a capturar la página fuente y confirmar si el sitio la publica como canal institucional; luego confirmación humana.")
        elif tc in ("DOMINIO_GOB_DISTINTO", "OTRO_DOMINIO"):
            dis(n, "EMAIL_DOMINIO_DISTINTO", prio, f"{ref}: {c['email_institucional']} no es del dominio del sitio ({sitio})", sitio, c["email_institucional"],
                "ACTIONS", "Recapturar la fuente y comprobar que el dominio del correo coincide con el publicado (posible error de tipeo de la fuente).")
        if est in ("EL_EMAIL_NO_FIGURA_EN_LA_EVIDENCIA", "DATO_NO_LOCALIZADO_EN_LA_EVIDENCIA", "SIN_EVIDENCIA"):
            dis(n, "EVIDENCIA_NO_RESPALDA_EL_DATO", prio, f"{ref}: {est}", "", c["email_institucional"] or c["telefono_publicado"], "ACTIONS",
                "Recapturar la página fuente y registrar el fragmento que contiene el dato; hasta entonces el dato no está respaldado.")
        anios = [int(y) for y in re.findall(r"\b\d{2}/\d{2}/(20\d{2})\b", c["evidencia"] or "")]
        if anios and max(anios) <= 2023:
            dis(n, "EVIDENCIA_CON_FECHA_ANTIGUA", "MEDIA", f"{ref}: la fuente muestra fechas de {max(anios)}", "", c["email_institucional"], "ACTIONS",
                "Recapturar la fuente y verificar si la autoridad/contacto sigue vigente.")
        if "HISTÓRICO" in c["estado_del_contacto"].upper() or "PROTOCOLO HISTÓRICO" in c["tipo_de_via"].upper():
            dis(n, "CONTACTO_HISTORICO", "MEDIA", f"{ref}: {c['estado_del_contacto']}", "", c["telefono_publicado"], "ACTIONS", "Buscar un canal vigente de Ceremonial en el sitio oficial.")
    for f in fue:
        F.append({"municipio": f["municipio"], "municipio_id": ids.get(f["municipio"], ""), "campo": f["campo"], "valor_registrado": f["valor_registrado"],
                  "fuente_url": f["fuente_url"], "tipo_fuente": tipo_fuente(f["fuente_url"], sitio_x.get(f["municipio"], "")),
                  "estado_evidencia": f["estado_de_evidencia"], "consulta": f["consulta"], "observaciones": f["observaciones"]})
    con_directo = {k["municipio"] for k in K if k["categoria"] == "PROTOCOLO_CEREMONIAL" and k["tipo_via"] in ("PROTOCOLO EJECUTIVO",)}
    for m in mun:
        if m["municipio"] not in con_directo:
            dis(m["municipio"], "SIN_PROTOCOLO_DIRECTO", "MEDIA", f"situación: {m['situacion_protocolo']}", "", "", "ACTIONS",
                "Buscar Ceremonial/Protocolo en el sitio oficial (relevamiento de contactos acotado).")
    return {"municipios.csv": (M, COL_MUN), "contactos.csv": (K, COL_CON), "fuentes.csv": (F, COL_FUE), "discrepancias.csv": (D, COL_DIS)}


def escribir(sal: dict, dir_sal: Path) -> None:
    for nombre, (filas, cols) in sal.items():
        C.escribir_csv(dir_sal / nombre, filas, cols)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", nargs="?", type=Path, default=XLSX)
    ap.add_argument("--salida", type=Path, default=DIR)
    a = ap.parse_args(argv)
    mun, con, fue = leer_hojas(a.xlsx)
    import contactos as K
    sal = construir(mun, con, fue, K.cargar_sitios(), C.cargar_municipios_cfg())
    escribir(sal, a.salida)
    print({n: len(f) for n, (f, _) in sal.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
