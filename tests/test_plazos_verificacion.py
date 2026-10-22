"""Plazos de la verificación de sitios: ningún servidor lento, silencioso o con Crawl-delay enorme puede bloquear la ejecución.

Sesiones SINTÉTICAS (dominios -prueba): no se usa la red ni se espera tiempo real significativo.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import descubrir_sitios as D  # noqa: E402
from test_pipeline import R  # noqa: E402
from test_sitios_redirecciones import SesionPorHost  # noqa: E402

CFG = {m["municipio_id"]: m for m in C.cargar_municipios_cfg()}
HOME = "<html><head><title>Municipalidad de {n}</title></head><body><h1>Municipalidad de {n}</h1><p>Provincia de Buenos Aires</p></body></html>"


class SesionColgada(SesionPorHost):
    """Un host no devuelve nunca (como un servidor que gotea bytes): el GET queda bloqueado hasta que se libera."""

    def __init__(self, paginas, colgados=(), **kw):
        super().__init__(paginas, **kw)
        self.colgados, self.libre = set(colgados), threading.Event()

    def get(self, url, timeout=None, allow_redirects=True):
        from urllib.parse import urlparse
        if urlparse(url).hostname in self.colgados:
            self.pedidos.append(url)
            self.libre.wait(30)
        return super().get(url, timeout, allow_redirects)


def mid_cand(n=3):
    """Municipios CANDIDATO_A_VERIFICAR reales de la config (solo se usan sus ids; los sitios se sustituyen por dominios -prueba)."""
    return [c for c in C.cargar_municipios_cfg()][:n]


def sitios_prueba(cfgs, hosts):
    return {c["municipio_id"]: {"municipio_id": c["municipio_id"], "estado": "CANDIDATO_A_VERIFICAR", "sitio_oficial": f"https://{h}/"}
            for c, h in zip(cfgs, hosts)}


def test_solicitud_colgada_vence_por_tiempo_total_y_no_bloquea():
    ses = SesionColgada({}, colgados={"colgado-prueba.gob.ar"})
    cli = K.ClienteContactos(pausa=0, session=ses, plazo_solicitud=0.3)
    t = time.monotonic()
    r = cli.get("https://colgado-prueba.gob.ar/")
    ses.libre.set()
    assert time.monotonic() - t < 3 and not r.ok and r.tipo_error == "ROBOTS_NO_VERIFICABLE" and "TIMEOUT" in r.detalle


def test_pagina_colgada_tras_robots_ok_es_timeout():
    class S(SesionColgada):
        def get(self, url, timeout=None, allow_redirects=True):
            if url.endswith("/robots.txt"):
                return R(404)
            return super().get(url, timeout, allow_redirects)
    ses = S({}, colgados={"lento-prueba.gob.ar"})
    cli = K.ClienteContactos(pausa=0, session=ses, plazo_solicitud=0.3)
    r = cli.get("https://lento-prueba.gob.ar/")
    ses.libre.set()
    assert r.tipo_error == "TIMEOUT"


def test_crawl_delay_enorme_se_respeta_sin_dormir():
    cli = K.ClienteContactos(pausa=0, session=SesionPorHost({"https://delay-prueba.gob.ar/": R(text="<p>x</p>")},
                                                            robots_por_host={"delay-prueba.gob.ar": "User-agent: *\nCrawl-delay: 86400\n"}))
    t = time.monotonic()
    r = cli.get("https://delay-prueba.gob.ar/")
    assert time.monotonic() - t < 2 and r.tipo_error == "CRAWL_DELAY_EXCESIVO" and "86400" in r.detalle
    assert "https://delay-prueba.gob.ar/" not in cli.s.pedidos      # respetar robots: no se consulta la página


def test_limite_de_paginas_por_dominio():
    pag = {f"https://dom-prueba.gob.ar/p{i}": R(text="<p>x</p>") for i in range(10)}
    cli = K.ClienteContactos(pausa=0, session=SesionPorHost(pag), max_paginas_dominio=3)
    tipos = [cli.get(f"https://dom-prueba.gob.ar/p{i}").tipo_error for i in range(5)]
    assert tipos == ["", "", "", "LIMITE_PAGINAS_DOMINIO", "LIMITE_PAGINAS_DOMINIO"]
    assert sum(1 for u in cli.s.pedidos if "/p" in u) == 3
    cli.iniciar_municipio()                                          # el contador se reinicia por municipio
    assert cli.get("https://dom-prueba.gob.ar/p9").ok


def test_presupuesto_por_municipio_y_total():
    cli = K.ClienteContactos(pausa=0, session=SesionPorHost({"https://a-prueba.gob.ar/": R(text="<p>x</p>")}))
    cli.iniciar_municipio(max_solicitudes=1)                         # el robots.txt ya consume la única solicitud
    assert cli.get("https://a-prueba.gob.ar/").ok                    # (robots + página se cuentan al empezar: 0 < 1)
    assert cli.get("https://a-prueba.gob.ar/").tipo_error == "LIMITE_SOLICITUDES_MUNICIPIO"
    cli.iniciar_municipio(plazo=0.0001)
    time.sleep(0.01)
    assert cli.get("https://a-prueba.gob.ar/").tipo_error == "TIMEOUT_MUNICIPIO"
    cli.fin_global = time.monotonic() - 1
    assert cli.get("https://a-prueba.gob.ar/").tipo_error == "PLAZO_TOTAL_AGOTADO"


def test_un_municipio_colgado_no_frena_a_los_demas_y_hay_logs(capsys):
    cfgs = mid_cand(3)
    hosts = ["colgado-prueba.gob.ar", "ok1-prueba.gob.ar", "ok2-prueba.gob.ar"]
    pag = {f"https://{h}/": R(text=HOME.format(n=c["municipio"])) for c, h in zip(cfgs, hosts)}
    ses = SesionColgada(pag, colgados={hosts[0]})
    cli = K.ClienteContactos(pausa=0, session=ses, plazo_solicitud=0.3)
    res, avance = [], []
    D.descubrir(cli, cfgs, sitios_prueba(cfgs, hosts), cfgs, res, plazo_municipio=5, plazo_total=60, max_solicitudes=10,
                al_terminar=lambda r: avance.append(len(r)))
    ses.libre.set()
    assert [r["estado"] for r in res][0] != D.ESTADO_OK
    assert [r["estado"] for r in res][1:] == [D.ESTADO_OK, D.ESTADO_OK]
    assert avance == [1, 2, 3]                                        # resultado parcial disponible tras cada municipio
    out = capsys.readouterr().out
    for c in cfgs:
        assert f"{c['municipio']}: inicio" in out and f"{c['municipio']}: " in out and "solicitudes" in out


def test_plazo_total_agotado_marca_el_resto_sin_tocar_la_red():
    cfgs = mid_cand(4)
    hosts = [f"m{i}-prueba.gob.ar" for i in range(4)]
    ses = SesionPorHost({f"https://{h}/": R(text=HOME.format(n=c["municipio"])) for c, h in zip(cfgs, hosts)})
    cli = K.ClienteContactos(pausa=0, session=ses)
    res = D.descubrir(cli, cfgs, sitios_prueba(cfgs, hosts), cfgs, plazo_total=0.0001, log=lambda *a, **k: None)
    assert len(res) == 4 and [r["estado"] for r in res[1:]] == ["NO_PROCESADO_PLAZO_TOTAL"] * 3   # el 1.º pudo empezar antes de vencer
    assert not any(h in u for u in ses.pedidos for h in hosts[1:])


def test_error_inesperado_en_un_municipio_no_detiene_la_ejecucion():
    cfgs = mid_cand(2)
    hosts = ["roto-prueba.gob.ar", "ok-prueba.gob.ar"]
    ses = SesionPorHost({f"https://{hosts[1]}/": R(text=HOME.format(n=cfgs[1]["municipio"]))}, errores={hosts[0]: RuntimeError("fallo raro")})
    cli = K.ClienteContactos(pausa=0, session=ses)
    res = D.descubrir(cli, cfgs, sitios_prueba(cfgs, hosts), cfgs, log=lambda *a, **k: None)
    assert res[0]["estado"] != D.ESTADO_OK and res[1]["estado"] == D.ESTADO_OK


def test_interrupcion_conserva_parciales_e_incidencias(tmp_path, monkeypatch):
    cfgs = mid_cand(3)
    # se prueba la lógica de main con un descubrir que cancela a la mitad
    guardado = {}

    def falso_descubrir(cli, cfg_all, sitios, seleccion, res, *a, al_terminar=None, **k):
        res.append(D._fila(seleccion[0], estado=D.ESTADO_OK, sitio="https://ok-prueba.gob.ar/"))
        al_terminar(res)
        raise KeyboardInterrupt("señal 15")
    monkeypatch.setattr(D, "descubrir", falso_descubrir)
    monkeypatch.setattr(K, "seleccionar", lambda cfg_all, sel: cfgs)
    monkeypatch.setattr(D, "registrar_incidencias", lambda res: guardado.setdefault("inc", [r["estado"] for r in res]))
    monkeypatch.setattr(D, "aplicar_config", lambda *a, **k: 0)
    assert D.main(["--municipios", "todos", "--salida", str(tmp_path)]) == 0
    assert guardado["inc"] == [D.ESTADO_OK, "NO_PROCESADO_INTERRUMPIDO", "NO_PROCESADO_INTERRUMPIDO"]
    assert "NO_PROCESADO_INTERRUMPIDO" in (tmp_path / "cobertura_sitios.md").read_text(encoding="utf-8")


def test_workflow_tiene_limites_razonables():
    import yaml
    wf = yaml.safe_load((AQUI.parent / ".github/workflows/relevar_contactos.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["contactos"]
    assert job["timeout-minutes"] <= 90
    paso = next(p for p in job["steps"] if "descubrir_sitios.py" in p.get("run", ""))
    assert paso["timeout-minutes"] <= 25 and "--plazo-total" in paso["run"]


def test_las_40_url_configuradas_siguen_presentes():
    assert len([s for s in C.leer_csv(C.ARCHIVO_SITIOS) if s["sitio_oficial"]]) == 40
