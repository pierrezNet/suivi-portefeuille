"""Tests de la publication via l'API HTTP GitHub (transport « api »).

Aucun appel réseau réel : on injecte une fausse session (`session=...`) ou on
monkeypatche `requests.Session`. Indépendant du `data/` réel (fixture isolée).
"""

import base64

import pytest

from app.services import chiffrement
from app.services.stockage import Depot
from tools import publier_dashboard as pub
from tools.publier_dashboard import ConfigManquante, publier_via_api


MDP_TEST = "phrase-de-passe-test-2026"


@pytest.fixture
def data_exemple(tmp_path):
    dossier = tmp_path / "data"
    depot = Depot(dossier)
    depot.enregistrer("comptes", [
        {"id": "pea", "nom": "PEA Test", "type": "PEA", "broker": "Test",
         "numero": "PEA-EXEMPLE-0001", "date_ouverture": "2026-01-01",
         "devise_principale": "EUR"},
    ])
    depot.enregistrer("mouvements", [
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-01-05", "montant": "1000.00", "devise": "EUR",
         "libelle": "Dépôt initial"},
    ])
    return dossier


# --- Fausse session HTTP ----------------------------------------------------

class _FausseReponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("pas de JSON")
        return self._payload


class _FausseSession:
    """Enregistre GET/PUT. `existants` = chemins déjà présents (→ GET 200+sha)."""

    def __init__(self, existants=None, statut_put=201):
        self.existants = set(existants or ())
        self.statut_put = statut_put
        self.gets = []
        self.puts = []

    def _chemin(self, url):
        return url.split("/contents/", 1)[1]

    def get(self, url, headers=None, params=None, timeout=None):
        chemin = self._chemin(url)
        self.gets.append(chemin)
        if chemin in self.existants:
            return _FausseReponse(200, {"sha": "deadbeef"})
        return _FausseReponse(404, {"message": "Not Found"})

    def put(self, url, headers=None, json=None, timeout=None):
        self.puts.append((self._chemin(url), json))
        if self.statut_put not in (200, 201):
            return _FausseReponse(self.statut_put, {"message": "Bad credentials"})
        return _FausseReponse(self.statut_put, {"content": {}})


# --- _transport_api_github --------------------------------------------------

def test_transport_put_chaque_fichier():
    fichiers = {"data.enc.json": b"chiffre", "index.html": b"<html>"}
    sess = _FausseSession()
    pub._transport_api_github(
        fichiers, owner="alice", repo="dash", branche="main",
        token="tok", message="m", session=sess,
    )
    chemins = {c for c, _ in sess.puts}
    assert chemins == {"data.enc.json", "index.html"}
    # Le contenu est bien encodé en base64.
    corps = dict(sess.puts)
    assert base64.b64decode(corps["data.enc.json"]["content"]) == b"chiffre"
    assert corps["index.html"]["branch"] == "main"
    # Fichier neuf → pas de sha.
    assert "sha" not in corps["index.html"]


def test_transport_inclut_sha_si_fichier_existant():
    sess = _FausseSession(existants={"index.html"})
    pub._transport_api_github(
        {"index.html": b"x"}, owner="a", repo="d", branche="main",
        token="t", message="m", session=sess,
    )
    _, corps = sess.puts[0]
    assert corps["sha"] == "deadbeef"


def test_transport_erreur_put_leve():
    sess = _FausseSession(statut_put=401)
    with pytest.raises(pub.PublicationAPIErreur, match="401"):
        pub._transport_api_github(
            {"data.enc.json": b"x"}, owner="a", repo="d", branche="main",
            token="mauvais", message="m", session=sess,
        )


# --- publier_via_api --------------------------------------------------------

def test_publier_via_api_bout_en_bout(data_exemple):
    sess = _FausseSession()
    recap = publier_via_api(
        data_dir=data_exemple, mot_passe=MDP_TEST,
        owner="alice", repo="mon-dash", token="ghp_xxx", session=sess,
    )
    assert recap["url_pages"] == "https://alice.github.io/mon-dash/"
    assert recap["taille_data"] > 0
    chemins = {c for c, _ in sess.puts}
    # Données + shell + assets PWA tous poussés.
    for attendu in ("data.enc.json", "index.html", "sw.js", "manifest.json",
                    "icon-512.png", ".nojekyll"):
        assert attendu in chemins, f"non poussé : {attendu}"


def test_publier_via_api_cree_session_par_defaut(data_exemple, monkeypatch):
    """Sans session injectée, requests.Session() est utilisé (et monkeypatché)."""
    sess = _FausseSession()
    import requests
    monkeypatch.setattr(requests, "Session", lambda: sess)
    publier_via_api(
        data_dir=data_exemple, mot_passe=MDP_TEST,
        owner="bob", repo="d", token="t",
    )
    assert sess.puts  # des fichiers ont bien été poussés


def test_publier_via_api_params_manquants_leve(data_exemple):
    with pytest.raises(ConfigManquante, match="token GitHub"):
        publier_via_api(
            data_dir=data_exemple, mot_passe=MDP_TEST,
            owner="a", repo="d", token=None,
        )


def test_publier_via_api_mdp_court_leve(data_exemple):
    with pytest.raises(chiffrement.MotPasseInvalide):
        publier_via_api(
            data_dir=data_exemple, mot_passe="court",
            owner="a", repo="d", token="t", session=_FausseSession(),
        )
