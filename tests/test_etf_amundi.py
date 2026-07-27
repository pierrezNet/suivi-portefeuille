"""Exposition ETF Amundi : cache journalier, garde-fous réseau, intégration
dans la page détail (section affichée pour les seuls ETF connus)."""

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from app.services import etf_amundi as etf
from app.services.stockage import Depot

ISIN = "FR0013412020"  # PAEEM — présent dans la table de config ETF_AMUNDI


@pytest.fixture(autouse=True)
def cache_temporaire(tmp_path, monkeypatch):
    """Isole le cache disque dans un tmp_path (aucune écriture dans data/etf)."""
    monkeypatch.setattr(etf, "CACHE_DIR", tmp_path)
    return tmp_path


def _ecrire_cache(cache_dir, isin, jour, data):
    (cache_dir / f"{isin}_{jour}.json").write_text(
        json.dumps({"isin": isin, "date": jour, **data}, ensure_ascii=False),
        encoding="utf-8",
    )


def _interdire_reseau(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("appel réseau interdit ici")
    monkeypatch.setattr(etf.requests, "post", _boom)


# --- Config -----------------------------------------------------------------

def test_est_etf_amundi():
    assert etf.est_etf_amundi(ISIN) is True
    assert etf.est_etf_amundi("FR001400U5Q4") is True   # DCAM
    assert etf.est_etf_amundi("US0378331005") is False   # action quelconque
    assert etf.est_etf_amundi(None) is False


# --- Cache : pas de réseau si fichier du jour présent -----------------------

def test_cache_du_jour_sans_reseau(cache_temporaire, monkeypatch):
    _interdire_reseau(monkeypatch)
    jour = date.today().isoformat()
    _ecrire_cache(cache_temporaire, ISIN, jour,
                  {"INDEX_TOP10": [{"nom": "TSMC", "poids_pct": 9.1}]})
    data = etf.get_etf_composition(ISIN)
    assert data["INDEX_TOP10"][0]["nom"] == "TSMC"


def test_lire_cache_local_uniquement(cache_temporaire, monkeypatch):
    _interdire_reseau(monkeypatch)
    _ecrire_cache(cache_temporaire, ISIN, "2026-01-02",
                  {"INDEX_TOP10": [{"nom": "ANCIEN", "poids_pct": 1}]})
    # lire_cache prend le fichier le plus récent, jamais le réseau
    assert etf.lire_cache(ISIN)["INDEX_TOP10"][0]["nom"] == "ANCIEN"
    assert etf.lire_cache("US0378331005") is None       # ISIN non ETF → None


# --- Garde-fou : réseau coupé, pas de cache → None (pas d'exception) ---------

def test_indisponible_renvoie_none(monkeypatch):
    def _offline(*a, **k):
        raise requests.RequestException("réseau coupé")
    monkeypatch.setattr(etf.requests, "post", _offline)
    assert etf.get_etf_composition(ISIN) is None        # aucun cache + échec


def test_echec_reseau_repli_sur_dernier_cache(cache_temporaire, monkeypatch):
    _ecrire_cache(cache_temporaire, ISIN, "2026-01-02",
                  {"INDEX_TOP10": [{"nom": "REPLI", "poids_pct": 2}]})

    def _offline(*a, **k):
        raise requests.RequestException("réseau coupé")
    monkeypatch.setattr(etf.requests, "post", _offline)
    # pas de fichier du jour → tente le réseau → échoue → dernier cache connu
    data = etf.get_etf_composition(ISIN, force_refresh=True)
    assert data["INDEX_TOP10"][0]["nom"] == "REPLI"


# --- Succès réseau : parse + écrit le cache ---------------------------------

class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_fetch_parse_et_ecrit_cache(cache_temporaire, monkeypatch):
    raw = {"produits": [{"breakDowns": [
        {"aggregationField": "INDEX_TOP10", "breakDownData": [
            {"aggregationName": "APPLE", "adjustedWeight": 0.05,
             "additionalProperties": {"isin": "US0378331005", "sector": "Tech",
                                      "currency": "USD", "countryOfRisk": "USA"}},
        ]},
        {"aggregationField": "INDEX_COUNTRIES", "breakDownData": [
            {"aggregationName": "USA", "adjustedWeight": 0.70,
             "additionalProperties": {}},
        ]},
    ]}]}
    monkeypatch.setattr(etf.requests, "post", lambda *a, **k: _FakeResp(raw))
    data = etf.get_etf_composition(ISIN, force_refresh=True)
    assert data["INDEX_TOP10"][0] == {
        "nom": "APPLE", "poids_pct": 5.0, "isin": "US0378331005",
        "secteur": "Tech", "devise": "USD", "pays": "USA"}
    assert data["INDEX_COUNTRIES"][0]["poids_pct"] == 70.0
    # cache du jour écrit → 2e appel sans réseau
    monkeypatch.setattr(etf.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert etf.get_etf_composition(ISIN)["INDEX_TOP10"][0]["nom"] == "APPLE"


# --- Intégration page détail ------------------------------------------------

def _depot_avec_titre(tmp_path, isin):
    d = Depot(tmp_path / "data")
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [{
        "id": "etf", "ticker": "PAEEM", "nom": "Amundi PEA Émergent",
        "isin": isin, "devise": "EUR"}])
    for n in ("mouvements", "evenements", "notes_titres", "watchlist",
              "suggestions_ia", "virements_programmes"):
        d.enregistrer(n, [])
    return d


def _client(depot):
    from app import create_app
    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_detail_affiche_section_pour_etf_connu(tmp_path, cache_temporaire):
    _ecrire_cache(cache_temporaire, ISIN, date.today().isoformat(),
                  {"INDEX_TOP10": [{"nom": "APPLE", "poids_pct": 5.0,
                                    "pays": "USA", "secteur": "Tech"}]})
    depot = _depot_avec_titre(tmp_path, ISIN)
    html = _client(depot).get("/titres/etf").get_data(as_text=True)
    assert "Exposition réelle de l'indice" in html
    assert "APPLE" in html
    assert "via swap" in html


def test_detail_pas_de_section_hors_etf(tmp_path):
    depot = _depot_avec_titre(tmp_path, "US0378331005")  # ISIN non ETF Amundi
    html = _client(depot).get("/titres/etf").get_data(as_text=True)
    assert "Exposition réelle de l'indice" not in html
