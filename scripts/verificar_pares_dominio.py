#!/usr/bin/env python3
"""Verifica por HTTP los pares de dominios discrepantes (config vs insumo preliminar). No modifica ninguna configuración.

Cada dominio se solicita con robots.txt y TLS verificados, con los mismos plazos que el descubrimiento de sitios; se informa el
resultado por dominio y del par (ambos válidos / solo uno / ninguno / dominio alternativo redirige al otro). La decisión de cambiar
config/sitios_oficiales.csv queda para una persona.

Uso: python scripts/verificar_pares_dominio.py [--salida diagnostico_contactos] [--plazo-total 600]
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import descubrir_sitios as D  # noqa: E402


def pares() -> list[dict]:
    return [r for r in C.leer_csv(C.ARCHIVO_DISCREPANCIAS) if r["tema"] == "DOMINIO_DISCREPANTE"]


def resultado_par(a: dict, b: dict) -> str:
    if a["ok"] and b["ok"]:
        return "AMBOS_VALIDOS" + (" (mismo destino final)" if D.base_de(urlparse(a["raiz"]).hostname) == D.base_de(urlparse(b["raiz"]).hostname) else " (destinos distintos: revisar)")
    if a["ok"]:
        return "SOLO_CONFIG"
    return "SOLO_INSUMO" if b["ok"] else "NINGUNO_VERIFICADO"


def verificar(cli, filas: list[dict], nombres: dict[str, str], plazo_municipio: float = 90.0, log=print) -> list[dict]:
    out = []
    for i, r in enumerate(filas, 1):
        nombre = nombres.get(r["municipio_id"], r["municipio"])
        cli.iniciar_municipio(plazo_municipio, 12)
        res = {}
        for lado, url in (("config", r["valor_repo"]), ("insumo", r["valor_insumo"])):
            try:
                res[lado] = D.verificar_raiz(cli, url, nombre)
            except Exception as exc:  # noqa: BLE001
                res[lado] = {"raiz": url, "http": None, "titulo": "", "ok": False, "detalle": f"ERROR_INESPERADO {type(exc).__name__}"}
        fila = {"municipio": r["municipio"], "dominio_config": r["valor_repo"], "http_config": res["config"]["http"], "ok_config": res["config"]["ok"],
                "detalle_config": res["config"]["detalle"], "dominio_insumo": r["valor_insumo"], "http_insumo": res["insumo"]["http"],
                "ok_insumo": res["insumo"]["ok"], "detalle_insumo": res["insumo"]["detalle"], "resultado": resultado_par(res["config"], res["insumo"])}
        out.append(fila)
        log(f"[{i}/{len(filas)}] {r['municipio']}: {fila['resultado']}", flush=True)
    return out


def informe(filas: list[dict]) -> str:
    l = ["# Verificación de pares de dominios (config vs insumo)", "", "| Municipio | Dominio config | HTTP | Dominio insumo | HTTP | Resultado |", "|---|---|---|---|---|---|"]
    l += [f"| {f['municipio']} | {f['dominio_config']} | {f['http_config'] or '—'} {'✔' if f['ok_config'] else '✘ ' + f['detalle_config'][:60]} | {f['dominio_insumo']} | "
          f"{f['http_insumo'] or '—'} {'✔' if f['ok_insumo'] else '✘ ' + f['detalle_insumo'][:60]} | {f['resultado']} |" for f in filas]
    return "\n".join(l) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salida", type=Path, default=Path("diagnostico_contactos"))
    ap.add_argument("--pausa", type=float, default=2.0)
    ap.add_argument("--plazo-total", type=float, default=600.0)
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("SIGTERM")))
    cli = K.ClienteContactos(pausa=a.pausa)
    cli.fin_global = time.monotonic() + a.plazo_total
    nombres = {c["municipio_id"]: c["municipio"] for c in C.cargar_municipios_cfg()}
    filas: list[dict] = []
    try:
        filas = verificar(cli, pares(), nombres)
    except KeyboardInterrupt:
        print("INTERRUMPIDO: se conserva lo verificado", flush=True)
    a.salida.mkdir(parents=True, exist_ok=True)
    (a.salida / "pares_dominio.md").write_text(informe(filas), encoding="utf-8")
    print(informe(filas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
