"""Service notes_titres : journal de bord daté par titre.

Une note est attachée à un titre du catalogue, datée, typée, avec un titre
court + un contenu libre. Optionnellement liée à un événement déclencheur.

Différent de l'historique des thèses (`titres.py:_snapshot`) :
  - L'historique de thèse versionne les 4 champs réflexifs lors d'une édition.
  - Une note de journal est une réflexion datée *autonome*, qui peut accompagner
    une mise à jour de thèse mais peut aussi être posée seule (observation,
    décision, signal positif/négatif).

Les notes ne sont JAMAIS exportées dans le calendrier ICS (séparation par
collection, pas de filtrage à faire).
"""

from __future__ import annotations

import re
import uuid
from datetime import date as _date

from app.services.stockage import Depot


TYPES_NOTE = (
    "mise_a_jour_these",
    "observation",
    "decision",
    "signal_positif",
    "signal_negatif",
)

LIBELLES_TYPES = {
    "mise_a_jour_these": "Mise à jour de thèse",
    "observation": "Observation",
    "decision": "Décision",
    "signal_positif": "Signal positif",
    "signal_negatif": "Signal négatif",
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


def _normaliser(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    titre_id = _str_propre(donnees.get("titre_id"))
    if not titre_id:
        erreurs["titre_id"] = "obligatoire"
    else:
        ids_titres = {t["id"] for t in depot.charger("titres")}
        if titre_id not in ids_titres:
            erreurs["titre_id"] = "titre inconnu au catalogue"
        else:
            out["titre_id"] = titre_id

    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)

    type_ = _str_propre(donnees.get("type"))
    if not type_:
        erreurs["type"] = "obligatoire"
    elif type_ not in TYPES_NOTE:
        erreurs["type"] = f"valeur attendue parmi {', '.join(TYPES_NOTE)}"
    else:
        out["type"] = type_

    contenu = _str_propre(donnees.get("contenu"))
    if not contenu:
        erreurs["contenu"] = "obligatoire"
    else:
        out["contenu"] = contenu

    titre_court = _str_propre(donnees.get("titre_court"))
    if not titre_court and contenu:
        # Auto-rempli : 60 premiers caractères du contenu
        titre_court = contenu[:60]
        if len(contenu) > 60:
            titre_court = titre_court.rstrip() + "…"
    if not titre_court:
        erreurs["titre_court"] = "obligatoire si contenu vide"
    else:
        out["titre_court"] = titre_court

    evenement_id = _str_propre(donnees.get("evenement_id"))
    if evenement_id:
        ids_evts = {e["id"] for e in depot.charger("evenements")}
        if evenement_id not in ids_evts:
            erreurs["evenement_id"] = "événement inconnu"
        else:
            out["evenement_id"] = evenement_id

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
    """Renvoie les notes filtrées, triées par date décroissante (récent d'abord)."""
    items = depot.charger("notes_titres")
    res = []
    for n in items:
        if titre_id and n.get("titre_id") != titre_id:
            continue
        if type_ and n.get("type") != type_:
            continue
        d = n.get("date") or ""
        if date_debut and d < date_debut:
            continue
        if date_fin and d > date_fin:
            continue
        res.append(n)
    res.sort(key=lambda n: (n.get("date", ""), n.get("id", "")), reverse=True)
    return res


def trouver(depot: Depot, note_id: str) -> dict | None:
    for n in depot.charger("notes_titres"):
        if n.get("id") == note_id:
            return n
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    note = _normaliser(depot, donnees)
    note["id"] = "n-" + uuid.uuid4().hex[:10]
    note["date_creation"] = _date.today().isoformat()
    items = depot.charger("notes_titres")
    items.append(note)
    depot.enregistrer("notes_titres", items)
    return note


def mettre_a_jour(depot: Depot, note_id: str, donnees: dict) -> dict:
    items = depot.charger("notes_titres")
    for i, n in enumerate(items):
        if n.get("id") != note_id:
            continue
        nouveau = _normaliser(depot, donnees)
        nouveau["id"] = note_id
        nouveau["date_creation"] = n.get("date_creation") or _date.today().isoformat()
        items[i] = nouveau
        depot.enregistrer("notes_titres", items)
        return nouveau
    raise KeyError(note_id)


def supprimer(depot: Depot, note_id: str) -> bool:
    items = depot.charger("notes_titres")
    nouveau = [n for n in items if n.get("id") != note_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("notes_titres", nouveau)
    return True
