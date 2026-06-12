"""Tests de la route Réglages (GET formulaire, POST persistance)."""

import pytest

from app.services import reglages as svc


@pytest.fixture
def client(tmp_path):
    from app import create_app

    app = create_app()
    app.config["DATA_DIR"] = tmp_path
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c, tmp_path


def test_get_reglages_200(client):
    c, _ = client
    rep = c.get("/reglages")
    assert rep.status_code == 200
    corps = rep.get_data(as_text=True)
    assert "Réglages" in corps
    assert "Publication mobile" in corps


def test_post_reglages_persiste(client):
    c, data_dir = client
    rep = c.post("/reglages", data={
        "github_user": "alice", "github_repo": "mon-dash",
        "branche": "main", "github_token": "ghp_xyz",
    })
    assert rep.status_code == 302  # redirection après enregistrement
    rg = svc.charger_reglages(data_dir)
    assert rg["github_user"] == "alice"
    assert rg["github_repo"] == "mon-dash"
    assert rg["github_token"] == "ghp_xyz"


def test_post_token_vide_conserve_existant(client):
    c, data_dir = client
    svc.enregistrer_reglages(data_dir, {"github_token": "tok-initial"})
    c.post("/reglages", data={
        "github_user": "bob", "github_repo": "d", "github_token": "",
    })
    rg = svc.charger_reglages(data_dir)
    assert rg["github_user"] == "bob"
    assert rg["github_token"] == "tok-initial"


def test_get_affiche_suggestion_phrase(client):
    c, _ = client
    corps = c.get("/reglages").get_data(as_text=True)
    # La suggestion diceware comporte des mots séparés par des tirets.
    assert "Phrase de passe de chiffrement" in corps
