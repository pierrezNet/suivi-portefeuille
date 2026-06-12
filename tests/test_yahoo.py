"""Tests du module yahoo : inférence ticker + enrichissement (mocké)."""

import importlib.util
from unittest.mock import MagicMock, patch

import pytest

from app.services import yahoo


# yfinance est une dépendance OPTIONNELLE (métadonnées à la création d'un titre),
# volontairement NON embarquée dans le .exe (offline-first + poids pandas/numpy).
# Les tests qui patchent yfinance.Ticker exigent que le module soit importable :
# on les saute proprement quand il est absent (ex. CI / build .exe).
_sans_yfinance = pytest.mark.skipif(
    importlib.util.find_spec("yfinance") is None,
    reason="yfinance non installé (dépendance optionnelle, hors .exe)",
)


# --- inferer_ticker_yahoo --------------------------------------------------


def test_inferer_ticker_yahoo_xetra():
    assert yahoo.inferer_ticker_yahoo("IFX", "Xetra (Deutsche Börse)") == "IFX.DE"


def test_inferer_ticker_yahoo_paris():
    assert yahoo.inferer_ticker_yahoo("STMPA", "Euronext Paris") == "STMPA.PA"


def test_inferer_ticker_yahoo_nyse_pas_de_suffixe():
    assert yahoo.inferer_ticker_yahoo("NET", "NYSE") == "NET"


def test_inferer_ticker_yahoo_nasdaq_pas_de_suffixe():
    assert yahoo.inferer_ticker_yahoo("GTLB", "Nasdaq") == "GTLB"


def test_inferer_ticker_yahoo_marche_inconnu_fallback():
    """Si le marché n'est pas répertorié, on prend le ticker brut."""
    assert yahoo.inferer_ticker_yahoo("XYZ", "Bourse Lunaire") == "XYZ"


def test_inferer_ticker_yahoo_deja_suffixe():
    """Si l'utilisateur a déjà passé un ticker complet (avec point), on respecte."""
    assert yahoo.inferer_ticker_yahoo("IFX.DE", "Xetra") == "IFX.DE"


def test_inferer_ticker_yahoo_marche_manquant():
    """Pas de marché → ticker brut."""
    assert yahoo.inferer_ticker_yahoo("MU", None) == "MU"
    assert yahoo.inferer_ticker_yahoo("MU", "") == "MU"


def test_inferer_ticker_yahoo_ticker_vide():
    assert yahoo.inferer_ticker_yahoo("", "Xetra") == ""
    assert yahoo.inferer_ticker_yahoo(None, "Xetra") == ""


# --- enrichir (avec mock yfinance) ----------------------------------------


def _info_mock_ifx() -> dict:
    """Reproduit un dict info Yahoo réaliste pour Infineon."""
    return {
        "longName": "Infineon Technologies AG",
        "shortName": "INFINEON TECH.NA O.N.",
        "currency": "EUR",
        "exchange": "GER",
        "sector": "Technology",
        "industry": "Semiconductors",
        "website": "https://www.infineon.com",
        "isin": "",
        "marketCap": 95_409_000_000,
        "totalDebt": 7_500_000_000,
        "totalCash": 1_359_000_000,
        "enterpriseValue": 101_550_000_000,
        "dividendRate": 0.35,
    }


@_sans_yfinance
def test_enrichir_mock_yahoo_extrait_les_bons_champs():
    info = _info_mock_ifx()
    ticker_mock = MagicMock()
    ticker_mock.info = info
    with patch("yfinance.Ticker", return_value=ticker_mock):
        fiche = yahoo.enrichir("IFX.DE")

    assert fiche["ticker"] == "IFX"
    assert fiche["nom"] == "Infineon Technologies AG"
    assert fiche["devise"] == "EUR"
    assert fiche["marche"] == "Xetra (Deutsche Börse)"
    assert fiche["secteur"] == "Technology"
    assert fiche["verse_dividende"] is True
    assert fiche["dividende_par_action"] == "0.35"
    assert fiche["cap_boursiere_m"] == "95409"
    # dette nette = totalDebt - totalCash = 6 141 M
    assert fiche["dette_nette_m"] == "6141"
    assert fiche["valeur_entreprise_m"] == "101550"


@_sans_yfinance
def test_enrichir_sans_donnees_leve():
    ticker_mock = MagicMock()
    ticker_mock.info = {}
    with patch("yfinance.Ticker", return_value=ticker_mock):
        with pytest.raises(RuntimeError, match="Aucune donnée"):
            yahoo.enrichir("INCONNU.XX")


@_sans_yfinance
def test_enrichir_sans_dividende():
    info = {
        "longName": "Cloudflare Inc.",
        "currency": "USD",
        "exchange": "NYQ",
        "marketCap": 66_920_000_000,
    }
    ticker_mock = MagicMock()
    ticker_mock.info = info
    with patch("yfinance.Ticker", return_value=ticker_mock):
        fiche = yahoo.enrichir("NET")
    assert fiche["verse_dividende"] is False
    assert "dividende_par_action" not in fiche
    assert fiche["marche"] == "NYSE"


# --- enrichir_pour_titre (orchestrateur) ----------------------------------


def test_enrichir_pour_titre_succes(monkeypatch):
    monkeypatch.setattr(
        yahoo,
        "enrichir",
        lambda t, **kw: {"ticker": "IFX", "cap_boursiere_m": "95409"},
    )
    res = yahoo.enrichir_pour_titre("IFX", "Xetra (Deutsche Börse)")
    assert res is not None
    assert res["cap_boursiere_m"] == "95409"


def test_enrichir_pour_titre_echec_renvoie_none(monkeypatch):
    def _leve(*a, **k):
        raise RuntimeError("ticker inconnu")
    monkeypatch.setattr(yahoo, "enrichir", _leve)
    assert yahoo.enrichir_pour_titre("XXX", "Mars") is None


def test_enrichir_pour_titre_ticker_vide_renvoie_none():
    assert yahoo.enrichir_pour_titre("", "Xetra") is None
    assert yahoo.enrichir_pour_titre(None, "Xetra") is None


def test_enrichir_pour_titre_override_prend_priorite(monkeypatch):
    """Si ticker_yahoo_override est fourni, il prime sur l'inférence."""
    appels: list = []

    def fake_enrichir(t, **kw):
        appels.append(t)
        return {"ok": True}

    monkeypatch.setattr(yahoo, "enrichir", fake_enrichir)
    res = yahoo.enrichir_pour_titre(
        "PCEW", "Euronext Paris", ticker_yahoo_override="CW8.PA"
    )
    assert res == {"ok": True}
    assert appels == ["CW8.PA"]  # pas "PCEW.PA"


def test_enrichir_pour_titre_override_vide_ignore(monkeypatch):
    """Un override vide ou whitespace est ignoré, l'inférence reprend la main."""
    appels: list = []

    def fake_enrichir(t, **kw):
        appels.append(t)
        return {"ok": True}

    monkeypatch.setattr(yahoo, "enrichir", fake_enrichir)
    yahoo.enrichir_pour_titre("PCEW", "Euronext Paris", ticker_yahoo_override="  ")
    assert appels == ["PCEW.PA"]
