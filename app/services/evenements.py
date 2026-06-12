"""Service événements : publications, dividendes, rappels personnels."""

from __future__ import annotations

import re
import uuid
from datetime import date as _date

from app.services.stockage import Depot


TYPES_EVENEMENT = (
    "publication_resultats",
    "detachement_dividende",
    "versement_dividende",
    "assemblee_generale",
    "rappel_personnel",
    "autre",
)

LIBELLES_TYPES = {
    "publication_resultats": "Publication de résultats",
    "detachement_dividende": "Détachement de dividende",
    "versement_dividende": "Versement de dividende",
    "assemblee_generale": "Assemblée générale",
    "rappel_personnel": "Rappel personnel",
    "autre": "Autre",
}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _valider_date(v) -> str:
    s = _str_propre(v)
    if not s or not ISO_DATE.match(s):
        raise ValueError("format attendu YYYY-MM-DD")
    try:
        _date.fromisoformat(s)
    except ValueError:
        raise ValueError("date invalide")
    return s


def _normaliser(donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    libelle = _str_propre(donnees.get("libelle"))
    if not libelle:
        erreurs["libelle"] = "obligatoire"
    out["libelle"] = libelle

    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)

    type_ = _str_propre(donnees.get("type")) or "autre"
    if type_ not in TYPES_EVENEMENT:
        erreurs["type"] = f"valeur attendue parmi {', '.join(TYPES_EVENEMENT)}"
    else:
        out["type"] = type_

    titre_id = _str_propre(donnees.get("titre_id"))
    if titre_id:
        out["titre_id"] = titre_id

    out["notes"] = _str_propre(donnees.get("notes"))
    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(
    depot: Depot,
    *,
    titre_id: str | None = None,
    type_: str | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
) -> list[dict]:
    items = depot.charger("evenements")
    res = []
    for e in items:
        if titre_id and e.get("titre_id") != titre_id:
            continue
        if type_ and e.get("type") != type_:
            continue
        d = e.get("date") or ""
        if date_debut and d < date_debut:
            continue
        if date_fin and d > date_fin:
            continue
        res.append(e)
    res.sort(key=lambda e: e.get("date") or "")
    return res


def trouver(depot: Depot, evenement_id: str) -> dict | None:
    for e in depot.charger("evenements"):
        if e.get("id") == evenement_id:
            return e
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    item = _normaliser(donnees)
    item["id"] = "e-" + uuid.uuid4().hex[:10]
    items = depot.charger("evenements")
    items.append(item)
    depot.enregistrer("evenements", items)
    return item


def mettre_a_jour(depot: Depot, evenement_id: str, donnees: dict) -> dict:
    items = depot.charger("evenements")
    for i, e in enumerate(items):
        if e.get("id") != evenement_id:
            continue
        nouveau = _normaliser(donnees)
        nouveau["id"] = evenement_id
        items[i] = nouveau
        depot.enregistrer("evenements", items)
        return nouveau
    raise KeyError(evenement_id)


def marquer_honore(depot: Depot, evenement_id: str, mouvement_id: str) -> bool:
    """Marque un événement (typiquement un rappel DCA) comme honoré par un
    mouvement réel. Préserve les champs non gérés par `_normaliser` (lien
    programme, etc.). Idempotent côté écriture : surécrit si déjà marqué."""
    items = depot.charger("evenements")
    for i, e in enumerate(items):
        if e.get("id") != evenement_id:
            continue
        e["mouvement_id"] = mouvement_id
        e["date_honore"] = _date.today().isoformat()
        items[i] = e
        depot.enregistrer("evenements", items)
        return True
    return False


def supprimer(depot: Depot, evenement_id: str) -> bool:
    items = depot.charger("evenements")
    nouveau = [e for e in items if e.get("id") != evenement_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("evenements", nouveau)
    return True
