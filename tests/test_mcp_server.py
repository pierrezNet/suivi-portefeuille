"""Tests du serveur MCP (tools/mcp_server.py).

Les implémentations d'outils sont de simples fonctions, testables sans le SDK
`mcp`. La construction du serveur FastMCP est skippée si le SDK est absent.
"""

import importlib
import importlib.util

import pytest

from app.services import suggestions_ia
from app.services.stockage import Depot
from tools import mcp_server


@pytest.fixture
def depot(tmp_path, monkeypatch):
    d = Depot(tmp_path)
    d.enregistrer("titres", [{
        "id": "stm", "ticker": "STM", "nom": "STMicroelectronics",
        "secteur": "Semi-conducteurs", "horizon": "5-10 ans",
        "these_lt": "Acteur européen stratégique.",
        "signaux_mt_positifs": "", "signaux_mt_negatifs": "",
    }])
    d.enregistrer("notes_titres", [])
    d.enregistrer("evenements", [])
    # Les outils lisent le dépôt via _depot() → on l'injecte sur le tmp_path.
    monkeypatch.setattr(mcp_server, "_depot", lambda: d)
    return d


def test_outils_lecture(depot):
    assert any(t["id"] == "stm" for t in mcp_server.lister_titres())
    assert mcp_server.lire_titre("stm")["ticker"] == "STM"
    assert mcp_server.lire_titre("inconnu")["erreur"]
    assert mcp_server.lire_journal("stm") == []


def test_proposer_note_depose_une_suggestion(depot):
    r = mcp_server.proposer_note("stm", "Le Q1 confirme le rebond.", "observation")
    assert r["ok"] is True
    suggestions = suggestions_ia.lister(depot, titre_id="stm")
    assert len(suggestions) == 1
    assert suggestions[0]["cible"] == "note"


def test_proposer_revision_these_depose_une_suggestion(depot):
    r = mcp_server.proposer_revision_these("stm", "these_lt", "Thèse révisée.")
    assert r["ok"] is True
    s = suggestions_ia.lister(depot, titre_id="stm")[0]
    assert s["cible"] == "these" and s["champ_these"] == "these_lt"


def test_proposer_titre_inconnu_renvoie_erreur(depot):
    r = mcp_server.proposer_note("xxx", "test")
    assert r["ok"] is False and "erreur" in r


def test_six_outils_exposes():
    assert len(mcp_server.OUTILS) == 6


@pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="SDK mcp non installé (dépendance optionnelle)",
)
def test_creer_serveur_ok_si_sdk_present():
    serveur = mcp_server.creer_serveur()
    assert serveur is not None
