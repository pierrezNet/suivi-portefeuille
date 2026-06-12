"""Tests du service comptes (CRUD minimal) et des routes comptes/onboarding."""

import pytest

from app.services import comptes as svc
from app.services.stockage import Depot


# --- Service ----------------------------------------------------------------

def test_creer_compte_valide(tmp_path):
    depot = Depot(tmp_path)
    c = svc.creer(depot, {"nom": "PEA Bourse Direct", "type": "PEA", "broker": "BD"})
    assert c["id"] == "pea-bourse-direct"
    assert c["type"] == "PEA"
    assert c["broker"] == "BD"
    assert c["devise_principale"] == "EUR"
    assert depot.charger("comptes")[0]["nom"] == "PEA Bourse Direct"


def test_creer_compte_nom_manquant(tmp_path):
    depot = Depot(tmp_path)
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"nom": "", "type": "PEA"})
    assert "nom" in exc.value.erreurs


def test_creer_compte_type_invalide(tmp_path):
    depot = Depot(tmp_path)
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"nom": "Livret", "type": "LIVRET"})
    assert "type" in exc.value.erreurs


def test_creer_compte_date_invalide(tmp_path):
    depot = Depot(tmp_path)
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"nom": "X", "type": "PEA", "date_ouverture": "32/13/2026"})
    assert "date_ouverture" in exc.value.erreurs


def test_creer_compte_id_unique(tmp_path):
    depot = Depot(tmp_path)
    a = svc.creer(depot, {"nom": "PEA", "type": "PEA"})
    b = svc.creer(depot, {"nom": "PEA", "type": "CTO"})
    assert a["id"] != b["id"]


# --- Routes -----------------------------------------------------------------

def _app(tmp_path, *, testing=True, depot=None):
    from app import create_app

    app = create_app()
    app.config["DEPOT"] = depot if depot is not None else Depot(tmp_path)
    app.config["DATA_DIR"] = tmp_path
    app.config["TESTING"] = testing
    app.config["SECRET_KEY"] = "test"
    return app


@pytest.fixture
def client(tmp_path):
    app = _app(tmp_path)
    with app.test_client() as c:
        yield c, app


def test_get_nouveau_200(client):
    c, _ = client
    assert c.get("/comptes/nouveau").status_code == 200


def test_post_nouveau_cree_et_redirige(client):
    c, app = client
    rep = c.post("/comptes/nouveau", data={"nom": "PEA Test", "type": "PEA"})
    assert rep.status_code == 302
    assert app.config["DEPOT"].charger("comptes")[0]["nom"] == "PEA Test"


def test_post_nouveau_invalide_reaffiche(client):
    c, _ = client
    rep = c.post("/comptes/nouveau", data={"nom": "", "type": ""})
    assert rep.status_code == 200
    assert "erreur" in rep.get_data(as_text=True).lower()


def test_get_demarrage_200(client):
    c, _ = client
    assert c.get("/demarrage").status_code == 200


def test_charger_exemple(client):
    c, app = client
    rep = c.post("/demarrage/exemple")
    assert rep.status_code == 302
    assert len(app.config["DEPOT"].charger("comptes")) == 2


def test_index_redirige_vers_demarrage_si_vierge(tmp_path):
    app = _app(tmp_path, testing=False)  # TESTING False → redirection active
    with app.test_client() as c:
        rep = c.get("/")
        assert rep.status_code == 302
        assert "/demarrage" in rep.headers["Location"]


def test_index_pas_de_redirection_si_comptes(tmp_path):
    depot = Depot(tmp_path)
    depot.enregistrer("comptes", [
        {"id": "x", "nom": "X", "type": "PEA", "devise_principale": "EUR"},
    ])
    app = _app(tmp_path, testing=False, depot=depot)
    with app.test_client() as c:
        assert c.get("/").status_code == 200
