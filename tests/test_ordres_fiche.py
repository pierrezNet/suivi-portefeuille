"""Gestion des ordres actifs depuis la fiche titre (mêmes données que la
watchlist) : service factorisé, route détail, route d'enregistrement, retour
`next` sur annulation."""

from pathlib import Path

import pytest

from app.services import watchlist as wl
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea-bd", "nom": "PEA BD", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "dsy", "ticker": "DSY", "nom": "Dassault", "devise": "EUR"},
        {"id": "orphelin", "ticker": "ORP", "nom": "Sans watch", "devise": "EUR"},
    ])
    d.enregistrer("watchlist", [{
        "id": "w-dsy", "titre_id": "dsy", "nom": "Dassault", "ticker": "DSY",
        "compte_cible": "pea-bd", "devise": "EUR", "statut": "renforcement",
        "ordres_actifs": [
            {"id": "o-1", "prix_limite": "17", "quantite": 5, "sens": "achat",
             "statut": "en_attente", "date_creation": "2026-07-08"},
            {"id": "o-old", "prix_limite": "20", "quantite": 1, "sens": "achat",
             "statut": "annule", "date_creation": "2026-06-01"},
        ],
    }])
    for nom in ("mouvements", "evenements", "notes_titres",
                "suggestions_ia", "virements_programmes"):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


# --- Service --------------------------------------------------------------

def test_trouver_watch_par_titre(depot):
    assert wl.trouver_watch_par_titre(depot, "dsy")["id"] == "w-dsy"
    assert wl.trouver_watch_par_titre(depot, "orphelin") is None


def test_fusionner_ordre_actif_conserve_clos_et_remplace_actif():
    existants = [
        {"id": "o-old", "prix_limite": "20", "statut": "annule"},
        {"id": "o-1", "prix_limite": "17", "statut": "en_attente"},
    ]
    r = wl.fusionner_ordre_actif({"ordre_prix": "16", "ordre_quantite": "5"}, existants)
    assert [o["statut"] for o in r].count("annule") == 1  # clos conservé
    assert r[-1]["prix_limite"] == "16" and r[-1]["statut"] == "en_attente"


def test_fusionner_ordre_actif_prix_vide_retire_actif():
    existants = [{"id": "o-1", "prix_limite": "17", "statut": "en_attente"}]
    assert wl.fusionner_ordre_actif({"ordre_prix": ""}, existants) == []


def test_definir_ordre_actif_pose_valide_et_preserve_clos(depot):
    wl.definir_ordre_actif(depot, "w-dsy", {
        "ordre_prix": "16", "ordre_quantite": "3", "ordre_sens": "achat",
    })
    w = wl.trouver(depot, "w-dsy")
    actifs = [o for o in w["ordres_actifs"] if o["statut"] == "en_attente"]
    assert len(actifs) == 1
    assert actifs[0]["prix_limite"] == "16"
    assert actifs[0]["id"]  # id assigné par _parse_ordres
    assert any(o["id"] == "o-old" for o in w["ordres_actifs"])  # clos préservé


def test_definir_ordre_actif_prix_vide_annule(depot):
    wl.definir_ordre_actif(depot, "w-dsy", {"ordre_prix": ""})
    w = wl.trouver(depot, "w-dsy")
    assert not any(o["statut"] == "en_attente" for o in w["ordres_actifs"])
    assert any(o["id"] == "o-old" for o in w["ordres_actifs"])


# --- Route détail ---------------------------------------------------------

def test_fiche_affiche_le_bloc_ordres(depot):
    html = _client(depot).get("/titres/dsy").get_data(as_text=True)
    assert "Ordres actifs" in html
    assert "source_ordre_watch_id=w-dsy" in html   # lien Exécuter
    assert "/ordre/o-1/annuler" in html            # form Annuler
    assert 'name="next"' in html


# --- Route enregistrer_ordre ---------------------------------------------

def test_enregistrer_ordre_sur_titre_avec_watch(depot):
    _client(depot).post("/titres/dsy/ordre", data={
        "ordre_prix": "15", "ordre_quantite": "4", "ordre_sens": "achat",
    })
    w = wl.trouver(depot, "w-dsy")
    actifs = [o for o in w["ordres_actifs"] if o["statut"] == "en_attente"]
    assert len(actifs) == 1 and actifs[0]["prix_limite"] == "15"


def test_enregistrer_ordre_cree_watch_si_absente(depot):
    assert wl.trouver_watch_par_titre(depot, "orphelin") is None
    _client(depot).post("/titres/orphelin/ordre", data={
        "ordre_prix": "10", "ordre_quantite": "2", "ordre_sens": "achat",
    })
    w = wl.trouver_watch_par_titre(depot, "orphelin")
    assert w is not None and w["titre_id"] == "orphelin"
    actifs = [o for o in w["ordres_actifs"] if o["statut"] == "en_attente"]
    assert actifs and actifs[0]["prix_limite"] == "10"


# --- Annulation avec retour `next` ---------------------------------------

def test_annuler_ordre_next_revient_sur_la_fiche(depot):
    rep = _client(depot).post(
        "/watchlist/w-dsy/ordre/o-1/annuler", data={"next": "/titres/dsy"}
    )
    assert rep.status_code == 302
    assert rep.headers["Location"].endswith("/titres/dsy")


def test_annuler_ordre_sans_next_va_a_la_watchlist(depot):
    rep = _client(depot).post("/watchlist/w-dsy/ordre/o-1/annuler", data={})
    assert rep.status_code == 302
    assert "/watchlist" in rep.headers["Location"]


# --- Plan de rachat (paliers) depuis la fiche ----------------------------

def test_definir_paliers_remplace_le_plan(depot):
    wl.definir_paliers(depot, "w-dsy", {
        "paliers_prix": "18\n16",
        "paliers_tranche": "5/10\n10/10",
        "paliers_commentaire": "Premier\nRenfort",
    })
    p = wl.trouver(depot, "w-dsy")["paliers_rachat"]
    assert [x["prix"] for x in p] == ["18", "16"]
    assert p[0]["tranche"] == "5/10"
    assert p[1]["commentaire"] == "Renfort"


def test_definir_paliers_vide_supprime(depot):
    wl.definir_paliers(depot, "w-dsy", {"paliers_prix": "18"})
    assert wl.trouver(depot, "w-dsy")["paliers_rachat"][0]["prix"] == "18"
    wl.definir_paliers(depot, "w-dsy", {"paliers_prix": ""})
    assert wl.trouver(depot, "w-dsy")["paliers_rachat"] == []


def test_enregistrer_paliers_route_avec_watch(depot):
    _client(depot).post("/titres/dsy/paliers", data={
        "paliers_prix": "17\n15", "paliers_tranche": "1/2\n2/2",
        "paliers_commentaire": "a\nb",
    })
    assert [x["prix"] for x in wl.trouver(depot, "w-dsy")["paliers_rachat"]] == ["17", "15"]


def test_enregistrer_paliers_cree_watch_si_absente(depot):
    _client(depot).post("/titres/orphelin/paliers", data={"paliers_prix": "9"})
    w = wl.trouver_watch_par_titre(depot, "orphelin")
    assert w and w["paliers_rachat"][0]["prix"] == "9"


def test_fiche_affiche_le_plan_de_rachat(depot):
    wl.definir_paliers(depot, "w-dsy",
                       {"paliers_prix": "16", "paliers_commentaire": "cible"})
    html = _client(depot).get("/titres/dsy").get_data(as_text=True)
    assert "Plan de rachat indicatif" in html
    assert "cible" in html
