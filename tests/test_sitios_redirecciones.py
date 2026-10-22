"""Sitios oficiales del piloto y redirecciones: una 301 legítima se sigue; un destino no verificado se rechaza SIN solicitarlo.

Todo con sesiones simuladas y dominios ficticios (no se consulta la red).
"""
import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))
sys.path.insert(0, str(AQUI))
import comun as C  # noqa: E402
import contactos as K  # noqa: E402
import extraer as E  # noqa: E402
from test_contactos import AUTORIDADES, HCD_HOME, completar_archivos, dirs  # noqa: E402,F401
from test_pipeline import FakeSession, R  # noqa: E402
import validar as V  # noqa: E402

CFG = {r["municipio_id"]: r for r in csv.DictReader(open(K.SITIOS, encoding="utf-8-sig"), delimiter=";")}


# ------------------------------------------------------------------ configuración
def test_sitios_confirmados_del_piloto():
    esperado = {"ba_avellaneda": "https://www.mda.gob.ar/", "ba_vicente_lopez": "https://www.vicentelopez.gov.ar/",
                "ba_tres_de_febrero": "https://www.tresdefebrero.gov.ar/"}
    for mid, url in esperado.items():
        assert CFG[mid]["sitio_oficial"] == url and CFG[mid]["estado"] == "CONFIRMADO", mid
        assert urlparse(url).hostname.endswith((".gob.ar", ".gov.ar")) and CFG[mid]["fuente"]
    assert urlparse(CFG["ba_avellaneda"]["sitio_oficial"]).hostname != "avellaneda.gob.ar"      # ese dominio es de Avellaneda (Santa Fe)
    assert "dominios_verificados" in CFG["ba_avellaneda"]
    resto = [r for mid, r in CFG.items() if mid not in esperado]
    assert len(CFG) == 40 and len(resto) == 37
    assert all(r["estado"] in ("CANDIDATO_A_VERIFICAR", "OFICIAL_DOCUMENTADO") for r in resto)       # ninguno figura como verificado sin comprobarse
    assert all(("NO comprobado" in r["fuente"]) == (r["estado"] == "CANDIDATO_A_VERIFICAR") for r in resto)


# ------------------------------------------------------------------ redirecciones en el cliente
class SesionPorHost(FakeSession):
    """Como FakeSession, pero con robots.txt distinto por host y registro de lo solicitado."""

    def __init__(self, paginas, robots_por_host=None, errores=None):
        super().__init__(paginas)
        self.robots_por_host, self.errores = robots_por_host or {}, errores or {}

    def get(self, url, timeout=None, allow_redirects=True):
        host = urlparse(url).hostname
        if host in self.errores:
            self.pedidos.append(url)
            raise self.errores[host]
        if url.endswith("/robots.txt"):
            self.pedidos.append(url)
            t = self.robots_por_host.get(host)
            return R(200, t) if t else R(404)
        return super().get(url, timeout, allow_redirects)


def cliente(pag, **kw):
    ses = SesionPorHost(pag, **kw)
    return K.ClienteContactos(pausa=0, session=ses), ses


def test_redireccion_301_al_mismo_dominio_se_sigue():
    cli, ses = cliente({"https://muni-prueba.gob.ar/": R(301, location="https://www.muni-prueba.gob.ar/inicio/"),
                        "https://www.muni-prueba.gob.ar/inicio/": R(text="<html>ok</html>")})
    r = cli.get("https://muni-prueba.gob.ar/")
    assert r.ok and r.url_final == "https://www.muni-prueba.gob.ar/inicio/" and r.redirecciones == ((301, "https://www.muni-prueba.gob.ar/inicio/"),)
    assert "301" in r.diagnostico() and "www.muni-prueba.gob.ar/inicio" in r.diagnostico()


def test_http_a_https_se_sigue_y_https_a_http_se_rechaza():
    cli, _ = cliente({"http://muni-prueba.gob.ar/": R(308, location="https://muni-prueba.gob.ar/"), "https://muni-prueba.gob.ar/": R(text="<p>x</p>")})
    assert cli.get("http://muni-prueba.gob.ar/").ok
    cli, ses = cliente({"https://muni-prueba.gob.ar/": R(302, location="http://muni-prueba.gob.ar/"), "http://muni-prueba.gob.ar/": R(text="<p>x</p>")})
    r = cli.get("https://muni-prueba.gob.ar/")
    assert r.tipo_error == "REDIRECCION_NO_SEGURA" and "http://muni-prueba.gob.ar/" not in ses.pedidos


def test_destino_no_verificado_se_rechaza_sin_solicitarlo():
    """Caso real del piloto: el nombre del municipio existe en otra provincia con otro dominio."""
    cli, ses = cliente({"https://www.avellaneda-prueba.gob.ar/": R(301, location="https://avellaneda-otra-provincia.gob.ar/"),
                        "https://avellaneda-otra-provincia.gob.ar/": R(text="<html>otra provincia</html>")})
    r = cli.get("https://www.avellaneda-prueba.gob.ar/")
    assert r.tipo_error == "REDIRECCION_EXTERNA" and r.status == 301 and "avellaneda-otra-provincia.gob.ar" in r.detalle
    assert all("avellaneda-otra-provincia" not in p for p in ses.pedidos)            # ni la página ni su robots.txt
    assert r.url_final == "https://avellaneda-otra-provincia.gob.ar/"


def test_destino_verificado_en_la_config_se_sigue_y_se_revisa_su_robots():
    pag = {"https://tdf-prueba.gob.ar/": R(301, location="https://tdf-prueba.gov.ar/"), "https://tdf-prueba.gov.ar/": R(text="<p>ok</p>")}
    cli, ses = cliente(pag)
    assert cli.get("https://tdf-prueba.gob.ar/", hosts_ok={"tdf-prueba.gov.ar"}).ok
    assert "https://tdf-prueba.gov.ar/robots.txt" in ses.pedidos                    # robots del destino consultado antes de pedirlo
    cli, ses = cliente(pag)
    assert cli.get("https://tdf-prueba.gob.ar/").tipo_error == "REDIRECCION_EXTERNA"    # sin verificación previa: rechazado
    cli, ses = cliente(pag, robots_por_host={"tdf-prueba.gov.ar": "User-agent: *\nDisallow: /"})
    r = cli.get("https://tdf-prueba.gob.ar/", hosts_ok={"tdf-prueba.gov.ar"})
    assert r.tipo_error == "PROHIBIDO_POR_ROBOTS" and "https://tdf-prueba.gov.ar/" not in ses.pedidos


def test_bucle_de_redirecciones():
    cli, _ = cliente({"https://m-prueba.gob.ar/a": R(301, location="https://m-prueba.gob.ar/b"), "https://m-prueba.gob.ar/b": R(301, location="https://m-prueba.gob.ar/a")})
    assert cli.get("https://m-prueba.gob.ar/a").tipo_error == "REDIRECCION_EXCESIVA"


def test_tls_se_verifica_y_no_se_elude():
    err = requests.exceptions.SSLError("certificate verify failed")
    cli, ses = cliente({"https://tls-prueba.gob.ar/": R(text="<p>x</p>")}, errores={"tls-prueba.gob.ar": err})
    r = cli.get("https://tls-prueba.gob.ar/")
    assert r.tipo_error == "ROBOTS_NO_VERIFICABLE" and "ERROR_TLS" in r.detalle           # sin robots verificable no se consulta la página
    assert ses.pedidos == ["https://tls-prueba.gob.ar/robots.txt"]                         # ni se reintenta ni se desactiva la verificación
    # TLS inválido solo en la página (robots OK): ERROR_TLS, una única solicitud
    class SoloPagina(SesionPorHost):
        def get(self, url, timeout=None, allow_redirects=True):
            if not url.endswith("/robots.txt"):
                self.pedidos.append(url)
                raise err
            return super().get(url, timeout, allow_redirects)
    ses2 = SoloPagina({})
    r2 = K.ClienteContactos(pausa=0, session=ses2).get("https://tls-prueba.gob.ar/")
    assert r2.tipo_error == "ERROR_TLS" and ses2.pedidos.count("https://tls-prueba.gob.ar/") == 1


def test_el_cliente_de_indicadores_no_cambia():
    import inspect
    assert "hosts_ok" not in inspect.signature(E.Cliente.get).parameters and not hasattr(E.Cliente, "_get_con_saltos")


# ------------------------------------------------------------------ relevamiento con redirecciones
SITIO_VIEJO, SITIO_NUEVO = "https://www.tdf-prueba.gob.ar/", "https://www.tdf-prueba.gov.ar/"
HOME_NUEVO = '<html><head><title>Portal municipal</title></head><body><a href="/autoridades/">Autoridades</a></body></html>'


def relevar(dirs, pag, sitio, extra=None, robots_por_host=None):
    ses = SesionPorHost(pag, robots_por_host)
    cli = K.ClienteContactos(pausa=0, session=ses)
    cfg = {"municipio_id": "ba_tres_de_febrero", "municipio": "Tres de Febrero"}
    res = K.relevar_municipio(cli, cfg, dict({"sitio_oficial": sitio}, **(extra or {})), "2026-10-21", "S1")
    return res, K.aplicar([res], "2026-10-21", "S1", dirs[0], dirs[1]), ses


def paginas_nuevas():
    aut = AUTORIDADES.replace("avellaneda-prueba.gob.ar", "tdf-prueba.gov.ar")
    return {SITIO_VIEJO: R(301, location=SITIO_NUEVO), SITIO_NUEVO: R(text=HOME_NUEVO), SITIO_NUEVO + "autoridades/": R(text=aut)}


def test_301_a_dominio_verificado_permite_relevar(dirs):
    res, _, ses = relevar(dirs, paginas_nuevas(), SITIO_VIEJO,
                          {"estado": "CONFIRMADO", "dominios_verificados": "tdf-prueba.gov.ar"})
    assert res["sitio_ok"]
    f = {x["dependencia"]: x for x in C.leer_csv(dirs[0] / C.F_CONTACTOS)}
    assert f["Ceremonial y Protocolo"]["email_institucional"] == "protocolo@tdf-prueba.gov.ar"
    assert f["Ceremonial y Protocolo"]["url_fuente"] == SITIO_NUEVO + "autoridades/"
    completar_archivos(dirs)
    assert V.validar(dirs[0], "prueba")[0] == [], V.validar(dirs[0], "prueba")[0]


def test_301_a_dominio_no_verificado_deja_incidencia_y_no_relevamiento(dirs):
    res, _, ses = relevar(dirs, paginas_nuevas(), SITIO_VIEJO, {"estado": "CONFIRMADO"})
    assert not res["sitio_ok"] and C.leer_csv(dirs[0] / C.F_CONTACTOS) == []
    inc = [i for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS) if i["tipo_incidencia"] == "REDIRECCION_EXTERNA"]
    assert len(inc) == 1 and "301" in inc[0]["descripcion"] and "tdf-prueba.gov.ar" in inc[0]["descripcion"] and inc[0]["campo"] == "contacto:sitio_oficial"
    assert SITIO_NUEVO not in ses.pedidos


def test_sitio_confirmado_a_mano_no_exige_que_el_titulo_nombre_al_municipio(dirs):
    pag = {SITIO_NUEVO: R(text=HOME_NUEVO), SITIO_NUEVO + "autoridades/": R(text=AUTORIDADES.replace("avellaneda-prueba.gob.ar", "tdf-prueba.gov.ar"))}
    assert relevar(dirs, pag, SITIO_NUEVO, {"estado": "CONFIRMADO"})[0]["sitio_ok"]
    d2 = (dirs[0].parent / "a2", dirs[1])
    res, _, _ = relevar(d2, pag, SITIO_NUEVO, {"estado": "CANDIDATO_A_VERIFICAR"})        # sin confirmar: el título no lo identifica
    assert not res["sitio_ok"] and "SITIO_NO_VERIFICADO" in {i["tipo_incidencia"] for i in C.leer_csv(d2[0] / C.F_INCIDENCIAS)}


def test_robots_del_dominio_destino_se_respeta_en_el_relevamiento(dirs):
    res, _, ses = relevar(dirs, paginas_nuevas(), SITIO_VIEJO, {"estado": "CONFIRMADO", "dominios_verificados": "tdf-prueba.gov.ar"},
                          robots_por_host={"www.tdf-prueba.gov.ar": "User-agent: *\nDisallow: /"})
    assert not res["sitio_ok"] and SITIO_NUEVO not in ses.pedidos
    assert "PROHIBIDO_POR_ROBOTS" in {i["tipo_incidencia"] for i in C.leer_csv(dirs[0] / C.F_INCIDENCIAS)}
