"""Logique métier des comptes (PEA/CTO) — service pur.

Les comptes sont statiques (créés une fois). Le solde cash n'est PAS stocké ici :
il est recalculé dynamiquement à partir des mouvements (cf. `soldes.py`).

Comble l'absence historique de gestion de comptes (auparavant créés uniquement
par édition manuelle de `data/comptes.json`).
"""

from __future__ import annotations

import re
from datetime import date as _date

from app.services.stockage import Depot


SLUG_RE = re.compile(r"[^a-z0-9]+")
TYPES = ("PEA", "CTO")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    return SLUG_RE.sub("-", s).strip("-")


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def lister(depot: Depot) -> list[dict]:
    return depot.charger("comptes")


def trouver(depot: Depot, compte_id: str) -> dict | None:
    for c in depot.charger("comptes"):
        if c.get("id") == compte_id:
            return c
    return None


def _normaliser(donnees: dict, *, ids_existants: set[str]) -> dict:
    erreurs: dict[str, str] = {}

    nom = _str_propre(donnees.get("nom"))
    type_ = _str_propre(donnees.get("type")).upper()
    broker = _str_propre(donnees.get("broker"))
    numero = _str_propre(donnees.get("numero"))
    date_ouverture = _str_propre(donnees.get("date_ouverture"))
    devise = (_str_propre(donnees.get("devise_principale")) or "EUR").upper()

    if not nom:
        erreurs["nom"] = "obligatoire"
    if type_ not in TYPES:
        erreurs["type"] = "choisir PEA ou CTO"
    if date_ouverture:
        try:
            _date.fromisoformat(date_ouverture)
        except ValueError:
            erreurs["date_ouverture"] = "date invalide (format AAAA-MM-JJ)"

    propose = _slug(donnees.get("id") or nom)
    if not propose:
        erreurs["id"] = "nom requis pour générer l'identifiant"
    else:
        base, i = propose, 2
        while propose in ids_existants:
            propose = f"{base}-{i}"
            i += 1

    if erreurs:
        raise ErreursValidation(erreurs)

    out: dict = {"id": propose, "nom": nom, "type": type_}
    if broker:
        out["broker"] = broker
    if numero:
        out["numero"] = numero
    if date_ouverture:
        out["date_ouverture"] = date_ouverture
    out["devise_principale"] = devise
    return out


def creer(depot: Depot, donnees: dict) -> dict:
    items = depot.charger("comptes")
    ids = {c.get("id") for c in items}
    compte = _normaliser(donnees, ids_existants=ids)
    items.append(compte)
    depot.enregistrer("comptes", items)
    return compte
