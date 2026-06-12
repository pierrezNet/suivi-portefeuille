"""Enrichissement Yahoo Finance — module métier réutilisable.

Centralise la logique de récupération des chiffres financiers depuis Yahoo
Finance via `yfinance`. Importable depuis :
  - le runtime Flask (route POST « Actualiser Yahoo » et « Promouvoir »)
  - le CLI `tools/enrichir_titre.py`

**L'import de `yfinance` est lazy** : aucune dépendance réseau au démarrage
de l'app. Le module se charge uniquement quand `enrichir()` est appelé.

L'app Flask reste donc 100 % offline en runtime par défaut — les appels
Yahoo ne se déclenchent qu'à la suite d'un clic utilisateur explicite.
"""

from __future__ import annotations

import re
from datetime import date as _date


# ---------------------------------------------------------------------------
# Mapping marché → suffixe Yahoo
# ---------------------------------------------------------------------------

SUFFIXES_YAHOO: dict[str, str] = {
    "Xetra": ".DE",
    "Xetra (Deutsche Börse)": ".DE",
    "Deutsche Börse": ".DE",
    "Euronext Paris": ".PA",
    "Euronext Amsterdam": ".AS",
    "Euronext Bruxelles": ".BR",
    "Euronext (UCITS)": ".PA",
    "NYSE": "",
    "Nasdaq": "",
    "Borsa Italiana": ".MI",
    "LSE": ".L",
    "London Stock Exchange": ".L",
    "Bourse de Séoul": ".KS",
    "TSE": ".T",
    "BMV Mexico": ".MX",
}


def inferer_ticker_yahoo(ticker: str, marche: str | None) -> str:
    """Construit le ticker Yahoo en concaténant ticker + suffixe du marché.

    Si `marche` est absent ou inconnu, on tente le ticker brut (fallback).
    Si le ticker contient déjà un point (ex: IFX.DE saisi manuellement),
    on ne touche pas.
    """
    t = (ticker or "").strip()
    if not t:
        return ""
    if "." in t:
        return t  # déjà suffixé
    suffixe = SUFFIXES_YAHOO.get((marche or "").strip(), "")
    return t + suffixe


# ---------------------------------------------------------------------------
# Helpers d'extraction / format
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = _SLUG_RE.sub("-", s)
    return s.strip("-") or "titre"


def _arrondir_m(v) -> str | None:
    """Convertit une valeur en millions arrondies (chaîne)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f == 0:
        return None
    return str(round(f / 1_000_000))


def _marche_humain(exchange: str | None) -> str:
    """Tente d'inférer un nom de marché lisible depuis le code Yahoo."""
    if not exchange:
        return ""
    mapping = {
        "GER": "Xetra (Deutsche Börse)",
        "PAR": "Euronext Paris",
        "NYQ": "NYSE",
        "NMS": "Nasdaq",
        "NCM": "Nasdaq Capital Market",
        "NGM": "Nasdaq Global Market",
        "AMS": "Euronext Amsterdam",
        "BRU": "Euronext Bruxelles",
        "MIL": "Borsa Italiana",
        "TOR": "Toronto Stock Exchange",
        "LSE": "London Stock Exchange",
        "MEX": "BMV Mexico",
    }
    return mapping.get(exchange.upper(), exchange)


# ---------------------------------------------------------------------------
# Appel principal
# ---------------------------------------------------------------------------


def enrichir(ticker_yahoo: str, *, id_override: str | None = None,
             horizon: str = "5-10 ans") -> dict:
    """Interroge Yahoo Finance et renvoie un dict prêt pour `data/titres.json`.

    Lève RuntimeError si aucune donnée trouvée.
    """
    import yfinance as yf  # import lazy — pas chargé au démarrage de Flask

    t = yf.Ticker(ticker_yahoo)
    info = t.info or {}
    if not info or (not info.get("longName") and not info.get("shortName")):
        raise RuntimeError(
            f"Aucune donnée Yahoo Finance pour {ticker_yahoo!r}. "
            "Vérifier le ticker (essayer un suffixe comme .DE, .PA, .L, etc.)."
        )

    nom = info.get("longName") or info.get("shortName") or ticker_yahoo
    ticker_court = ticker_yahoo.split(".")[0].upper()
    devise = info.get("currency") or info.get("financialCurrency") or "EUR"
    marche = _marche_humain(info.get("exchange"))
    isin = info.get("isin") or ""

    sortie: dict = {
        "id": id_override or _slug(ticker_court),
        "ticker": ticker_court,
        "nom": nom,
        "isin": isin,
        "marche": marche,
        "devise": devise,
        "secteur": info.get("sector") or info.get("industry") or "",
        "site_ir": info.get("irWebsite") or info.get("website") or "",
        "perspectives": "",
        "these_lt": "",
        "signaux_mt_positifs": "",
        "signaux_mt_negatifs": "",
        "horizon": horizon,
        "verse_dividende": bool(info.get("dividendRate"))
        or bool(info.get("trailingAnnualDividendRate")),
    }

    if sortie["verse_dividende"]:
        freq = info.get("dividendFrequency")
        sortie["frequence_dividende"] = str(freq).lower() if freq else "annuel"
        dpa = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
        if dpa:
            sortie["dividende_par_action"] = str(dpa)

    cap_m = _arrondir_m(info.get("marketCap"))
    if cap_m:
        sortie["cap_boursiere_m"] = cap_m

    dette = info.get("totalDebt")
    cash = info.get("totalCash")
    if dette is not None and cash is not None:
        dette_nette = _arrondir_m((dette or 0) - (cash or 0))
        if dette_nette is not None:
            sortie["dette_nette_m"] = dette_nette

    ev_m = _arrondir_m(info.get("enterpriseValue"))
    if ev_m:
        sortie["valeur_entreprise_m"] = ev_m

    sortie["date_creation"] = _date.today().isoformat()
    return sortie


def enrichir_pour_titre(
    ticker: str,
    marche: str | None,
    *,
    ticker_yahoo_override: str | None = None,
) -> dict | None:
    """Variante haut niveau : combine inférence du suffixe + appel + extraction.

    Args:
        ticker: ticker court (ex : "IFX", "PCEW").
        marche: nom du marché (ex : "Euronext Paris"), utilisé pour inférer
            le suffixe si `ticker_yahoo_override` est absent.
        ticker_yahoo_override: ticker Yahoo complet renseigné manuellement
            (ex : "CW8.PA" pour PCEW qui n'est pas indexé). Prime sur l'inférence.

    Renvoie `None` en cas d'échec (au lieu de lever).
    """
    if ticker_yahoo_override and ticker_yahoo_override.strip():
        ticker_yahoo = ticker_yahoo_override.strip()
    else:
        ticker_yahoo = inferer_ticker_yahoo(ticker, marche)
    if not ticker_yahoo:
        return None
    try:
        return enrichir(ticker_yahoo)
    except Exception:
        return None
