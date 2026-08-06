"""Ordres actifs et paliers, désormais portés par le titre lui-même : helpers
de suivi, route détail, routes d'enregistrement, retour `next` sur annulation."""

from pathlib import Path

import pytest

from app.services import suivi
from app.services import titres as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea-bd", "nom": "PEA BD", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "dsy", "ticker": "DSY", "nom": "Dassault", "devise": "EUR",
         "compte_cible": "pea-bd", "statut": "renforcement", "priorite": "moyenne",
         "ordres_actifs": [
             {"id": "o-1", "prix_limite": "17", "quantite": 5, "sens": "achat",
              "statut": "en_attente", "date_creation": "2026-07-08"},
             {"id": "o-old", "prix_limite": "20", "quantite": 1, "sens": "achat",
              "statut": "annule", "date_creation": "2026-06-01"},
         ]},
        {"id": "orphelin", "ticker": "ORP", "nom": "Sans suivi", "devise": "EUR",
         "statut": "veille", "priorite": "moyenne"},
    ])
    for nom in ("mouvements", "evenements", "notes_titres",
                "suggestions_ia", "virements_programmes", "watchlist"):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


# --- Helpers purs (module suivi) -----------------------------------------

def test_fusionner_ordre_actif_conserve_clos_et_remplace_actif():
    existants = [
        {"id": "o-old", "prix_limite": "20", "statut": "annule"},
        {"id": "o-1", "prix_limite": "17", "statut": "en_attente"},
    ]
    r = suivi.fusionner_ordre_actif({"ordre_prix": "16", "ordre_quantite": "5"}, existants)
    assert [o["statut"] for o in r].count("annule") == 1  # clos conservé
    assert r[-1]["prix_limite"] == "16" and r[-1]["statut"] == "en_attente"


def test_fusionner_ordre_actif_prix_vide_retire_actif():
    existants = [{"id": "o-1", "prix_limite": "17", "statut": "en_attente"}]
    assert suivi.fusionner_ordre_actif({"ordre_prix": ""}, existants) == []


def test_definir_ordre_actif_pose_valide_et_preserve_clos(depot):
    svc.definir_ordre_actif(depot, "dsy", {
        "ordre_prix": "16", "ordre_quantite": "3", "ordre_sens": "achat",
    })
    t = svc.trouver(depot, "dsy")
    actifs = [o for o in t["ordres_actifs"] if o["statut"] == "en_attente"]
    assert len(actifs) == 1
    assert actifs[0]["prix_limite"] == "16"
    assert actifs[0]["id"]  # id assigné par _parse_ordres
    assert any(o["id"] == "o-old" for o in t["ordres_actifs"])  # clos préservé


def test_definir_ordre_actif_prix_vide_annule(depot):
    svc.definir_ordre_actif(depot, "dsy", {"ordre_prix": ""})
    t = svc.trouver(depot, "dsy")
    assert not any(o["statut"] == "en_attente" for o in t["ordres_actifs"])
    assert any(o["id"] == "o-old" for o in t["ordres_actifs"])


# --- Route détail ---------------------------------------------------------

def test_fiche_affiche_le_bloc_ordres(depot):
    html = _client(depot).get("/titres/dsy").get_data(as_text=True)
    assert "Ordres actifs" in html
    assert "source_ordre_titre_id=dsy" in html   # lien Exécuter
    assert "/ordre/o-1/annuler" in html            # form Annuler
    assert 'name="next"' in html


# --- Route enregistrer_ordre ---------------------------------------------

def test_enregistrer_ordre_sur_titre(depot):
    _client(depot).post("/titres/dsy/ordre", data={
        "ordre_prix": "15", "ordre_quantite": "4", "ordre_sens": "achat",
    })
    t = svc.trouver(depot, "dsy")
    actifs = [o for o in t["ordres_actifs"] if o["statut"] == "en_attente"]
    assert len(actifs) == 1 and actifs[0]["prix_limite"] == "15"


def test_enregistrer_ordre_sur_titre_sans_suivi_prealable(depot):
    _client(depot).post("/titres/orphelin/ordre", data={
        "ordre_prix": "10", "ordre_quantite": "2", "ordre_sens": "achat",
    })
    t = svc.trouver(depot, "orphelin")
    actifs = [o for o in (t.get("ordres_actifs") or []) if o["statut"] == "en_attente"]
    assert actifs and actifs[0]["prix_limite"] == "10"


# --- Annulation avec retour `next` ---------------------------------------

def test_annuler_ordre_next_revient_a_la_liste(depot):
    rep = _client(depot).post(
        "/titres/dsy/ordre/o-1/annuler", data={"next": "/titres/"}
    )
    assert rep.status_code == 302
    assert rep.headers["Location"].endswith("/titres/")


def test_annuler_ordre_sans_next_va_a_la_fiche(depot):
    rep = _client(depot).post("/titres/dsy/ordre/o-1/annuler", data={})
    assert rep.status_code == 302
    assert "/titres/dsy" in rep.headers["Location"]


# --- Plan de rachat (paliers) --------------------------------------------

def test_definir_paliers_remplace_le_plan(depot):
    svc.definir_paliers(depot, "dsy", {
        "cible_totale": "4",
        "paliers_prix": "18\n16",
        "paliers_quantite": "2\n2",
        "paliers_commentaire": "Premier achat\nRenforcement",
    })
    t = svc.trouver(depot, "dsy")
    p = t["paliers_rachat"]
    assert [x["prix"] for x in p] == ["18", "16"]
    assert p[0]["quantite"] == "2"
    assert p[1]["commentaire"] == "Renforcement"
    assert t["cible_totale"] == "4"


def test_definir_paliers_accepte_ancien_champ_tranche(depot):
    # Rétro-compat : un formulaire legacy envoyant `paliers_tranche` reste lu.
    svc.definir_paliers(depot, "dsy", {
        "paliers_prix": "18", "paliers_tranche": "5/10",
    })
    assert svc.trouver(depot, "dsy")["paliers_rachat"][0]["quantite"] == "5/10"


def test_definir_paliers_vide_supprime(depot):
    svc.definir_paliers(depot, "dsy", {"paliers_prix": "18"})
    assert svc.trouver(depot, "dsy")["paliers_rachat"][0]["prix"] == "18"
    svc.definir_paliers(depot, "dsy", {"paliers_prix": ""})
    assert svc.trouver(depot, "dsy")["paliers_rachat"] == []


def test_enregistrer_paliers_route(depot):
    _client(depot).post("/titres/dsy/paliers", data={
        "paliers_prix": "17\n15", "paliers_tranche": "1/2\n2/2",
        "paliers_commentaire": "a\nb",
    })
    assert [x["prix"] for x in svc.trouver(depot, "dsy")["paliers_rachat"]] == ["17", "15"]


def test_enregistrer_paliers_sur_titre_sans_suivi_prealable(depot):
    _client(depot).post("/titres/orphelin/paliers", data={"paliers_prix": "9"})
    t = svc.trouver(depot, "orphelin")
    assert t["paliers_rachat"][0]["prix"] == "9"


def test_fiche_affiche_le_plan_de_rachat(depot):
    svc.definir_paliers(depot, "dsy",
                        {"paliers_prix": "16", "paliers_commentaire": "cible"})
    html = _client(depot).get("/titres/dsy").get_data(as_text=True)
    assert "Plan de rachat indicatif" in html
    assert "cible" in html
