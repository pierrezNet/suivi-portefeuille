"""Exposition économique réelle d'un ETF Amundi à réplication synthétique :
top 10 de l'indice répliqué + répartition pays/secteurs, via l'API interne
(publique, sans cookie) d'Amundi.

Enrichissement DÉBRAYABLE : le cœur de l'app tourne sans réseau. La compo est
lue depuis un cache journalier (data/etf/), rafraîchi au plus une fois par ISIN
par jour. Aucune exception ne doit remonter jusqu'à une vue : en cas d'échec
(réseau coupé, API changée), on se replie sur le dernier cache connu, sinon on
renvoie None — la page s'affiche normalement, juste sans la section.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# data/etf sous la racine du projet (indépendant du répertoire courant).
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "etf"

URL = "https://www.amundietf.fr/mapi/ProductAPI/getProductsData"

# « Passeport » public du site amundietf.fr (aucun secret ni token de session).
# Donnée de CONFIG — extraite du cURL DevTools, pas disséminée dans le code.
CONTEXT: dict = {
    "countryCode": "FRA",
    "countryName": "France",
    "googleCountryCode": "FR",
    "domainName": "www.amundietf.fr",
    "bcp47Code": "fr-FR",
    "languageName": "French",
    "languageCode": "fr",
    "gtmCode": "GTM-W6ZRWNR",
    "userProfileName": "RETAIL",
    "userProfileSlug": "retail",
    "portalProfileName": None,
    "portalProfileSlug": None,
}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr,fr-FR;q=0.9",
    "Referer": "https://www.amundietf.fr/",
    "Origin": "https://www.amundietf.fr",
    "User-Agent": (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) "
        "Gecko/20100101 Firefox/152.0"
    ),
}

# --- Table de config ISIN → ETF Amundi synthétique -------------------------
# La PRÉSENCE d'un ISIN ici décide de l'affichage de la section « exposition
# réelle ». Ajouter un ETF = ajouter une ligne (pas de `if isin == …` épars).
ETF_AMUNDI: dict[str, dict] = {
    "FR001400U5Q4": {"indice": "MSCI World"},             # DCAM (Amundi PEA Monde)
    "FR0013412020": {"indice": "MSCI Emerging Markets"},  # PAEEM (Amundi PEA Émergent)
}

_CHAMPS = ("INDEX_TOP10", "INDEX_COUNTRIES", "INDEX_SECTORS")
_TIMEOUT = 12  # court : ne pas laisser un « Rafraîchir » pendre trop longtemps


def est_etf_amundi(isin: str | None) -> bool:
    """True si l'ISIN est un ETF Amundi connu (→ section exposition affichable)."""
    return bool(isin) and isin in ETF_AMUNDI


def _payload(isin: str) -> dict:
    return {
        "productIds": [isin],  # l'API accepte l'ISIN directement comme productId
        "productType": "PRODUCT",
        "context": CONTEXT,
        "breakDown": {"aggregationFields": list(_CHAMPS)},
    }


def _fetch(isin: str) -> dict:
    """Interroge l'API et renvoie le JSON brut. Lève en cas d'échec."""
    resp = requests.post(URL, json=_payload(isin), headers=HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _extract_breakdowns(raw: dict) -> dict:
    """Isole top 10 / pays / secteurs du JSON verbeux (cherche récursivement le
    premier champ 'breakDowns', dont l'emplacement peut varier)."""

    def find_breakdowns(node):
        if isinstance(node, dict):
            if "breakDowns" in node:
                return node["breakDowns"]
            for v in node.values():
                found = find_breakdowns(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_breakdowns(item)
                if found is not None:
                    return found
        return None

    breakdowns = find_breakdowns(raw)
    if breakdowns is None:
        raise ValueError("Champ 'breakDowns' introuvable — l'API a peut-être changé.")

    result: dict = {}
    for block in breakdowns:
        field = block.get("aggregationField")
        if field not in _CHAMPS:
            continue
        lignes = []
        for entry in block.get("breakDownData", []):
            props = entry.get("additionalProperties") or {}
            lignes.append({
                "nom": entry.get("aggregationName"),
                "poids_pct": round(100 * (entry.get("adjustedWeight") or 0), 2),
                "isin": props.get("isin"),
                "secteur": props.get("sector"),
                "devise": props.get("currency"),
                "pays": props.get("countryOfRisk"),
            })
        result[field] = lignes
    return result


def _fichier_du_jour(isin: str, jour: str) -> Path:
    return CACHE_DIR / f"{isin}_{jour}.json"


def _charger(fichier: Path) -> dict | None:
    try:
        return json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dernier_cache(isin: str) -> dict | None:
    """Le fichier de cache le plus récent pour cet ISIN (hors *_brut), ou None."""
    if not CACHE_DIR.exists():
        return None
    fichiers = sorted(
        f for f in CACHE_DIR.glob(f"{isin}_*.json")
        if not f.name.endswith("_brut.json")
    )
    return _charger(fichiers[-1]) if fichiers else None


def lire_cache(isin: str) -> dict | None:
    """Compo depuis le cache local UNIQUEMENT (jamais de réseau). Pour les vues :
    lit le fichier le plus récent disponible pour cet ISIN, sinon None."""
    if not est_etf_amundi(isin):
        return None
    return _dernier_cache(isin)


def get_etf_composition(isin: str, force_refresh: bool = False) -> dict | None:
    """Renvoie la compo indice (top10/pays/secteurs) depuis le cache du jour,
    sinon interroge l'API. Renvoie None si indisponible (réseau coupé, API
    changée) — l'appli doit rester fonctionnelle dans ce cas.

    En cas d'échec réseau, repli sur le dernier cache connu (même ancien) si
    présent, sinon None. N'écrit sur disque qu'en cas de succès réseau.
    """
    if not est_etf_amundi(isin):
        return None
    jour = date.today().isoformat()
    cache = _fichier_du_jour(isin, jour)
    if not force_refresh and cache.exists():
        data = _charger(cache)
        if data is not None:
            return data  # cache du jour valide → aucun appel réseau
    try:
        raw = _fetch(isin)
        data = _extract_breakdowns(raw)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Brut conservé une fois par jour : indispensable si l'API évolue.
        (CACHE_DIR / f"{isin}_{jour}_brut.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        paquet = {"isin": isin, "date": jour, "source": URL, **data}
        cache.write_text(
            json.dumps(paquet, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return paquet
    except Exception as e:  # réseau, HTTP 4xx/5xx, JSON inattendu…
        logger.warning("ETF Amundi %s : compo indisponible (%s)", isin, e)
        return _dernier_cache(isin)  # dernier cache connu, sinon None
