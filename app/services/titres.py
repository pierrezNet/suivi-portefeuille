"""Service titres : CRUD + versioning simple des thèses long terme.

Quand l'un des 4 champs « réflexifs » change (perspectives, these_lt,
signaux_mt_positifs, signaux_mt_negatifs), l'ancienne valeur est
poussée dans `historique_theses` avant la mutation, datée du jour.
"""

from __future__ import annotations

import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from app.services.stockage import Depot


CHAMPS_VERSIONNES = (
    "these_lt",
    "signaux_mt_positifs",
    "signaux_mt_negatifs",
)


CHAMPS_LIBRES = (
    "ticker",
    "nom",
    "isin",
    "marche",
    "devise",
    "secteur",
    "site_ir",
    "horizon",
    "frequence_dividende",
    "dividende_par_action",
    "cap_boursiere_m",
    "dette_nette_m",
    "valeur_entreprise_m",
    "ticker_yahoo",
)


SLUG_RE = re.compile(r"[^a-z0-9]+")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = SLUG_RE.sub("-", s)
    return s.strip("-")


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _normaliser(donnees: dict, *, ids_existants: set[str], id_actuel: str | None = None) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    ticker = _str_propre(donnees.get("ticker")).upper()
    nom = _str_propre(donnees.get("nom"))
    if not ticker:
        erreurs["ticker"] = "obligatoire"
    if not nom:
        erreurs["nom"] = "obligatoire"

    # ID : conservé si édition, sinon dérivé du ticker / nom
    if id_actuel:
        out["id"] = id_actuel
    else:
        propose = _slug(donnees.get("id") or ticker or nom)
        if not propose:
            erreurs["id"] = "ticker ou nom requis pour générer l'identifiant"
        else:
            base = propose
            i = 2
            while propose in ids_existants:
                propose = f"{base}-{i}"
                i += 1
            out["id"] = propose

    out["ticker"] = ticker
    out["nom"] = nom

    for c in CHAMPS_LIBRES:
        if c in ("ticker", "nom"):
            continue
        v = _str_propre(donnees.get(c))
        if v:
            out[c] = v

    out["devise"] = (out.get("devise") or "EUR").upper()

    # Booléen verse_dividende
    vd = donnees.get("verse_dividende")
    if isinstance(vd, bool):
        out["verse_dividende"] = vd
    elif _str_propre(vd).lower() in ("1", "true", "on", "oui"):
        out["verse_dividende"] = True
    elif _str_propre(vd).lower() in ("0", "false", "off", "non"):
        out["verse_dividende"] = False

    # Champs versionnés (toujours présents même si vides pour traçabilité)
    for c in CHAMPS_VERSIONNES:
        v = _str_propre(donnees.get(c))
        out[c] = v

    # Validation décimaux des montants financiers
    for c in ("dividende_par_action", "cap_boursiere_m", "dette_nette_m", "valeur_entreprise_m"):
        if c in out:
            try:
                Decimal(out[c].replace(",", "."))
                out[c] = out[c].replace(",", ".")
            except InvalidOperation:
                erreurs[c] = "nombre invalide"

    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(depot: Depot) -> list[dict]:
    items = depot.charger("titres")
    return sorted(items, key=lambda t: (t.get("ticker") or "").upper())


def trouver(depot: Depot, titre_id: str) -> dict | None:
    for t in depot.charger("titres"):
        if t.get("id") == titre_id:
            return t
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    items = depot.charger("titres")
    ids = {t.get("id") for t in items}
    titre = _normaliser(donnees, ids_existants=ids)
    titre["date_creation"] = _date.today().isoformat()
    items.append(titre)
    depot.enregistrer("titres", items)
    return titre


def _diff_versionnee(ancien: dict, nouveau: dict) -> bool:
    return any(
        (ancien.get(c) or "") != (nouveau.get(c) or "")
        for c in CHAMPS_VERSIONNES
    )


def _snapshot(titre: dict) -> dict:
    return {
        "date": _date.today().isoformat(),
        "valeurs": {c: titre.get(c, "") for c in CHAMPS_VERSIONNES},
    }


def mettre_a_jour(depot: Depot, titre_id: str, donnees: dict) -> dict:
    items = depot.charger("titres")
    for i, t in enumerate(items):
        if t.get("id") != titre_id:
            continue
        ids = {x.get("id") for x in items}
        nouveau = _normaliser(donnees, ids_existants=ids, id_actuel=titre_id)
        # Préserver historique + date_creation
        nouveau["date_creation"] = t.get("date_creation") or _date.today().isoformat()
        historique = list(t.get("historique_theses") or [])
        if _diff_versionnee(t, nouveau):
            historique.append(_snapshot(t))
        if historique:
            nouveau["historique_theses"] = historique
        # Conserver les éventuels champs additionnels non gérés ici
        for k, v in t.items():
            if k not in nouveau and k not in ("historique_theses",):
                nouveau[k] = v
        items[i] = nouveau
        depot.enregistrer("titres", items)
        return nouveau
    raise KeyError(titre_id)


def supprimer(depot: Depot, titre_id: str) -> bool:
    """Supprime un titre seulement s'il n'est pas référencé par un mouvement."""
    mouvements = depot.charger("mouvements")
    if any(m.get("titre_id") == titre_id for m in mouvements):
        raise ValueError(
            "Ce titre est référencé par un ou plusieurs mouvements ; "
            "supprime-les d'abord ou édite le titre plutôt."
        )
    items = depot.charger("titres")
    nouveau = [t for t in items if t.get("id") != titre_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("titres", nouveau)
    return True
