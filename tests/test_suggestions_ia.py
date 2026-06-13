"""Tests du service suggestions_ia (file de propositions IA + acceptation)."""

import pytest

from app.services import notes_titres, suggestions_ia as svc, titres
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path):
    d = Depot(tmp_path)
    d.enregistrer("titres", [{
        "id": "stm", "ticker": "STM", "nom": "STMicroelectronics", "devise": "EUR",
        "these_lt": "Acteur européen des semi-conducteurs.",
        "signaux_mt_positifs": "Reprise commandes auto",
        "signaux_mt_negatifs": "Marge opérationnelle sous pression",
    }])
    d.enregistrer("notes_titres", [])
    d.enregistrer("evenements", [])
    return d


# --- CRUD + validation ------------------------------------------------------

def test_creer_suggestion_note(depot):
    s = svc.creer(depot, {
        "titre_id": "stm", "cible": "note", "type_note": "observation",
        "contenu": "Le Q1 confirme le rebond auto.",
    })
    assert s["id"].startswith("s-")
    assert s["source"] == "claude-mcp"
    assert s["date_proposition"]
    assert svc.trouver(depot, s["id"])["contenu"].startswith("Le Q1")
    assert len(svc.lister(depot, titre_id="stm")) == 1


def test_creer_suggestion_these(depot):
    s = svc.creer(depot, {
        "titre_id": "stm", "cible": "these", "champ_these": "these_lt",
        "contenu": "Thèse révisée : montée SiC + souveraineté UE.",
        "commentaire": "Au vu du dernier earnings.",
    })
    assert s["cible"] == "these"
    assert s["champ_these"] == "these_lt"


def test_validation_titre_inconnu(depot):
    with pytest.raises(svc.ErreursValidation) as e:
        svc.creer(depot, {"titre_id": "xxx", "cible": "note", "contenu": "x"})
    assert "titre_id" in e.value.erreurs


def test_validation_cible_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as e:
        svc.creer(depot, {"titre_id": "stm", "cible": "autre", "contenu": "x"})
    assert "cible" in e.value.erreurs


def test_validation_contenu_vide(depot):
    with pytest.raises(svc.ErreursValidation) as e:
        svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": ""})
    assert "contenu" in e.value.erreurs


def test_validation_champ_these_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as e:
        svc.creer(depot, {
            "titre_id": "stm", "cible": "these",
            "champ_these": "perspectives", "contenu": "x",
        })
    assert "champ_these" in e.value.erreurs


def test_supprimer(depot):
    s = svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "x"})
    assert svc.supprimer(depot, s["id"]) is True
    assert svc.lister(depot, titre_id="stm") == []
    assert svc.supprimer(depot, "s-inexistant") is False


# --- accepter ---------------------------------------------------------------

def test_accepter_note_cree_la_note_et_vide_la_file(depot):
    s = svc.creer(depot, {
        "titre_id": "stm", "cible": "note", "type_note": "decision",
        "contenu": "Conserver, ne pas renforcer avant Q2.",
    })
    res = svc.accepter(depot, s["id"])
    assert res["cible"] == "note"
    notes = notes_titres.lister(depot, titre_id="stm")
    assert len(notes) == 1
    assert notes[0]["type"] == "decision"
    assert "Conserver" in notes[0]["contenu"]
    assert "[IA validé" in notes[0]["contenu"]  # provenance discrète
    assert svc.lister(depot, titre_id="stm") == []  # file vidée


def test_accepter_note_avec_contenu_edite(depot):
    s = svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "brouillon"})
    svc.accepter(depot, s["id"], contenu="version corrigée par moi")
    notes = notes_titres.lister(depot, titre_id="stm")
    assert "version corrigée par moi" in notes[0]["contenu"]
    assert "brouillon" not in notes[0]["contenu"]


def test_accepter_these_met_a_jour_et_versionne(depot):
    ancienne = titres.trouver(depot, "stm")["these_lt"]
    s = svc.creer(depot, {
        "titre_id": "stm", "cible": "these", "champ_these": "these_lt",
        "contenu": "Nouvelle thèse : pari SiC automobile + reshoring UE.",
    })
    res = svc.accepter(depot, s["id"])
    assert res["cible"] == "these"
    titre = titres.trouver(depot, "stm")
    # Champ mis à jour (texte propre, sans marque IA).
    assert titre["these_lt"] == "Nouvelle thèse : pari SiC automobile + reshoring UE."
    # Ancienne valeur archivée (traçabilité).
    snaps = titre.get("historique_theses") or []
    assert any(sn["valeurs"].get("these_lt") == ancienne for sn in snaps)
    assert svc.lister(depot, titre_id="stm") == []


def test_accepter_introuvable_leve(depot):
    with pytest.raises(KeyError):
        svc.accepter(depot, "s-inexistant")


# --- routes -----------------------------------------------------------------

def _app(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app


def test_route_accepter_note(depot):
    s = svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "brouillon"})
    with _app(depot).test_client() as c:
        rep = c.post(f"/titres/stm/suggestions/{s['id']}/accepter",
                     data={"contenu": "texte final"})
    assert rep.status_code == 302
    assert "texte final" in notes_titres.lister(depot, titre_id="stm")[0]["contenu"]
    assert svc.lister(depot, titre_id="stm") == []


def test_route_accepter_these(depot):
    s = svc.creer(depot, {
        "titre_id": "stm", "cible": "these", "champ_these": "these_lt",
        "contenu": "proposé",
    })
    with _app(depot).test_client() as c:
        rep = c.post(f"/titres/stm/suggestions/{s['id']}/accepter",
                     data={"contenu": "nouvelle thèse validée"})
    assert rep.status_code == 302
    assert titres.trouver(depot, "stm")["these_lt"] == "nouvelle thèse validée"


def test_route_rejeter(depot):
    s = svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "x"})
    with _app(depot).test_client() as c:
        rep = c.post(f"/titres/stm/suggestions/{s['id']}/rejeter")
    assert rep.status_code == 302
    assert svc.lister(depot, titre_id="stm") == []


def test_route_404_si_titre_ne_correspond_pas(depot):
    depot.enregistrer("titres", depot.charger("titres") + [{
        "id": "net", "ticker": "NET", "nom": "Cloudflare", "devise": "USD",
        "these_lt": "", "signaux_mt_positifs": "", "signaux_mt_negatifs": "",
    }])
    s = svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "x"})
    with _app(depot).test_client() as c:
        rep = c.post(f"/titres/net/suggestions/{s['id']}/accepter")
    assert rep.status_code == 404


def test_detail_rend_section_suggestions(depot):
    svc.creer(depot, {"titre_id": "stm", "cible": "note", "contenu": "challenge Q1 auto"})
    with _app(depot).test_client() as c:
        html = c.get("/titres/stm").get_data(as_text=True)
    assert "Suggestions IA en attente" in html
    assert "challenge Q1 auto" in html
