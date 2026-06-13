#!/usr/bin/env python
"""Serveur MCP local — expose le portefeuille à Claude (Desktop / Code).

Lancé **séparément** de l'app Flask : jamais dans le runtime offline, jamais
embarqué dans le .exe. Claude (le client) lit les thèses / le journal / le
portefeuille via les outils de LECTURE, fait sa propre recherche web pour
l'actualité, puis dépose des PROPOSITIONS — qui ne sont **jamais** appliquées
sans validation humaine dans l'app (fiche du titre → Accepter/Rejeter).

Lancement :  python tools/mcp_server.py        (transport stdio)
Dépendance optionnelle :  pip install -r requirements-mcp.txt

Le module s'importe **sans** le paquet `mcp` (les implémentations sont de
simples fonctions Python testables) ; `mcp` n'est requis que par
`creer_serveur()` / l'exécution réelle.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.services import dashboard_data, notes_titres, suggestions_ia, titres
from app.services.stockage import Depot


def _depot() -> Depot:
    """Dépôt pointant sur le même DATA_DIR que l'app (BOURSE_DATA_DIR sinon défaut)."""
    from config import Config

    return Depot(Path(Config.DATA_DIR))


# --- Outils LECTURE ---------------------------------------------------------

def lister_titres() -> list[dict]:
    """Liste les titres du catalogue (id, ticker, nom, secteur, horizon)."""
    return [
        {c: t.get(c) for c in ("id", "ticker", "nom", "secteur", "horizon")}
        for t in titres.lister(_depot())
    ]


def lire_titre(titre_id: str) -> dict:
    """Renvoie la fiche complète d'un titre : thèse LT, signaux MT+/-,
    perspectives, et l'historique des thèses (historique_theses)."""
    t = titres.trouver(_depot(), titre_id)
    return t if t else {"erreur": f"titre inconnu : {titre_id}"}


def lire_journal(titre_id: str) -> list[dict]:
    """Journal de bord (notes datées) d'un titre, du plus récent au plus ancien."""
    return notes_titres.lister(_depot(), titre_id=titre_id)


def resume_portefeuille() -> dict:
    """Résumé du portefeuille : cash, valorisation, PV latente, comptes/positions."""
    d = dashboard_data.construire(_depot(), rattraper_virements=False)
    return {
        c: d.get(c)
        for c in (
            "total_cash", "total_valo_titres", "total_pv_latente",
            "total_portefeuille", "comptes",
        )
    }


# --- Outils PROPOSITION (déposés en file, validés par l'humain dans l'app) ---

def proposer_note(titre_id: str, contenu: str, type_note: str = "observation",
                  titre_court: str = "") -> dict:
    """Propose une NOTE de journal pour un titre. N'est PAS appliquée : elle
    apparaît dans l'app pour validation. type_note ∈ observation | decision |
    signal_positif | signal_negatif | mise_a_jour_these."""
    try:
        s = suggestions_ia.creer(_depot(), {
            "titre_id": titre_id, "cible": "note", "type_note": type_note,
            "contenu": contenu, "titre_court": titre_court, "source": "claude-mcp",
        })
    except suggestions_ia.ErreursValidation as e:
        return {"ok": False, "erreur": str(e)}
    return {"ok": True, "suggestion_id": s["id"],
            "message": "Proposition déposée — à valider dans l'app (fiche du titre)."}


def proposer_revision_these(titre_id: str, champ: str, nouveau_texte: str,
                            commentaire: str = "") -> dict:
    """Propose une RÉVISION d'un champ de thèse VERSIONNÉ. N'est PAS appliquée :
    à valider dans l'app (l'ancienne valeur sera archivée). champ ∈ these_lt |
    signaux_mt_positifs | signaux_mt_negatifs."""
    try:
        s = suggestions_ia.creer(_depot(), {
            "titre_id": titre_id, "cible": "these", "champ_these": champ,
            "contenu": nouveau_texte, "commentaire": commentaire, "source": "claude-mcp",
        })
    except suggestions_ia.ErreursValidation as e:
        return {"ok": False, "erreur": str(e)}
    return {"ok": True, "suggestion_id": s["id"],
            "message": "Révision proposée — à valider dans l'app (fiche du titre)."}


OUTILS = (
    lister_titres, lire_titre, lire_journal, resume_portefeuille,
    proposer_note, proposer_revision_these,
)


def creer_serveur():
    """Construit le serveur FastMCP en enregistrant tous les OUTILS.

    Nécessite le paquet `mcp` (cf. requirements-mcp.txt).
    """
    from mcp.server.fastmcp import FastMCP

    serveur = FastMCP("suivi-portefeuille")
    for fonction in OUTILS:
        serveur.tool()(fonction)
    return serveur


def main() -> None:
    creer_serveur().run()


if __name__ == "__main__":
    main()
