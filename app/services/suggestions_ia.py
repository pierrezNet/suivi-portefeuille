"""Service suggestions_ia : file de propositions IA en attente de validation.

Une suggestion est produite par le serveur MCP (Claude, cf. tools/mcp_server.py)
et n'est **jamais** appliquée automatiquement : l'utilisateur l'accepte (en
l'éditant éventuellement) ou la rejette depuis la fiche du titre. À l'acceptation :
  - cible "note"  → crée une note de journal (`notes_titres.creer`) ;
  - cible "these" → met à jour un champ de thèse versionné (`titres.mettre_a_jour`,
    qui archive automatiquement l'ancienne valeur dans `historique_theses`).

Modèle unifié : chaque suggestion porte un unique `contenu` éditable.
"""

from __future__ import annotations

import uuid
from datetime import date as _date

from app.services.notes_titres import TYPES_NOTE
from app.services.stockage import Depot


CIBLES = ("note", "these")
# Révisions de thèse limitées aux champs VERSIONNÉS (traçabilité gratuite).
CHAMPS_THESE = ("these_lt", "signaux_mt_positifs", "signaux_mt_negatifs")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _normaliser(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    titre_id = _str_propre(donnees.get("titre_id"))
    if not titre_id:
        erreurs["titre_id"] = "obligatoire"
    elif titre_id not in {t["id"] for t in depot.charger("titres")}:
        erreurs["titre_id"] = "titre inconnu au catalogue"
    else:
        out["titre_id"] = titre_id

    cible = _str_propre(donnees.get("cible"))
    if cible not in CIBLES:
        erreurs["cible"] = f"valeur attendue parmi {', '.join(CIBLES)}"
    else:
        out["cible"] = cible

    contenu = _str_propre(donnees.get("contenu"))
    if not contenu:
        erreurs["contenu"] = "obligatoire"
    else:
        out["contenu"] = contenu

    if cible == "note":
        type_note = _str_propre(donnees.get("type_note")) or "observation"
        if type_note not in TYPES_NOTE:
            erreurs["type_note"] = f"valeur attendue parmi {', '.join(TYPES_NOTE)}"
        else:
            out["type_note"] = type_note
        titre_court = _str_propre(donnees.get("titre_court"))
        if titre_court:
            out["titre_court"] = titre_court
    elif cible == "these":
        champ = _str_propre(donnees.get("champ_these"))
        if champ not in CHAMPS_THESE:
            erreurs["champ_these"] = f"valeur attendue parmi {', '.join(CHAMPS_THESE)}"
        else:
            out["champ_these"] = champ

    commentaire = _str_propre(donnees.get("commentaire"))
    if commentaire:
        out["commentaire"] = commentaire
    out["source"] = _str_propre(donnees.get("source")) or "claude-mcp"

    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(depot: Depot, *, titre_id: str | None = None) -> list[dict]:
    """Suggestions en attente, triées par date de proposition décroissante."""
    items = depot.charger("suggestions_ia")
    res = [s for s in items if not titre_id or s.get("titre_id") == titre_id]
    res.sort(key=lambda s: (s.get("date_proposition", ""), s.get("id", "")), reverse=True)
    return res


def trouver(depot: Depot, suggestion_id: str) -> dict | None:
    for s in depot.charger("suggestions_ia"):
        if s.get("id") == suggestion_id:
            return s
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    s = _normaliser(depot, donnees)
    s["id"] = "s-" + uuid.uuid4().hex[:10]
    s["date_proposition"] = _date.today().isoformat()
    items = depot.charger("suggestions_ia")
    items.append(s)
    depot.enregistrer("suggestions_ia", items)
    return s


def supprimer(depot: Depot, suggestion_id: str) -> bool:
    items = depot.charger("suggestions_ia")
    nouveau = [s for s in items if s.get("id") != suggestion_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("suggestions_ia", nouveau)
    return True


def accepter(depot: Depot, suggestion_id: str, *, contenu: str | None = None) -> dict:
    """Applique une suggestion (note créée ou thèse mise à jour) puis la retire.

    `contenu` permet à l'utilisateur de retoucher le texte avant acceptation.
    Lève KeyError si la suggestion (ou le titre) est introuvable.
    """
    from app.services import notes_titres, titres

    s = trouver(depot, suggestion_id)
    if not s:
        raise KeyError(suggestion_id)
    texte = _str_propre(contenu) or s.get("contenu", "")

    if s["cible"] == "note":
        # Provenance discrète dans le journal (la note reste éditable/supprimable).
        marque = f"[IA validé le {_date.today().isoformat()}] "
        note = notes_titres.creer(depot, {
            "titre_id": s["titre_id"],
            "date": _date.today().isoformat(),
            "type": s.get("type_note", "observation"),
            "contenu": marque + texte,
            "titre_court": s.get("titre_court", ""),
        })
        supprimer(depot, suggestion_id)
        return {"cible": "note", "note_id": note["id"]}

    # cible "these" : on passe le titre COMPLET + le champ révisé (texte propre,
    # sans marque : la traçabilité vient du snapshot dans historique_theses).
    titre = titres.trouver(depot, s["titre_id"])
    if not titre:
        raise KeyError(s["titre_id"])
    donnees = dict(titre)
    donnees[s["champ_these"]] = texte
    titres.mettre_a_jour(depot, s["titre_id"], donnees)
    supprimer(depot, suggestion_id)
    return {"cible": "these", "champ": s["champ_these"]}
