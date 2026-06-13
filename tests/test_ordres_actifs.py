"""Tests des ordres d'achat actifs (watchlist)."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services import watchlist as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "cto", "nom": "CTO", "type": "CTO"},
        {"id": "pea", "nom": "PEA", "type": "PEA"},
    ])
    d.enregistrer("titres", [
        {"id": "net", "ticker": "NET", "nom": "Cloudflare", "devise": "USD"},
    ])
    d.enregistrer("evenements", [])
    d.enregistrer("mouvements", [])
    d.enregistrer("watchlist", [])
    return d


# --- _parse_ordres + normalisation -----------------------------------------


def test_parse_ordres_depuis_textareas(depot):
    """Saisie par textareas multi-lignes."""
    w = svc.creer(depot, {
        "nom": "Test", "ticker": "TST", "marche": "Nasdaq",
        "ordres_prix": "100\n50",
        "ordres_quantite": "1\n2",
        "ordres_validite": "2026-06-01\n2026-07-15",
        "ordres_note": "Note A\nNote B",
    })
    assert len(w["ordres_actifs"]) == 2
    o1, o2 = w["ordres_actifs"]
    assert o1["prix_limite"] == "100"
    assert o1["quantite"] == 1
    assert o1["validite"] == "2026-06-01"
    assert o1["statut"] == "en_attente"
    assert o1["note"] == "Note A"
    assert o1["id"].startswith("o-")
    assert o2["prix_limite"] == "50"
    assert o2["quantite"] == 2


def test_validation_prix_negatif_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "nom": "X", "ordres_prix": "-10", "ordres_quantite": "1",
        })
    assert "ordres_actifs" in exc.value.erreurs


def test_validation_quantite_zero_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "nom": "X", "ordres_prix": "100", "ordres_quantite": "0",
        })
    assert "ordres_actifs" in exc.value.erreurs


def test_validation_validite_format_iso(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "nom": "X", "ordres_prix": "100", "ordres_quantite": "1",
            "ordres_validite": "06/01/2026",  # mauvais format
        })
    assert "ordres_actifs" in exc.value.erreurs


def test_validation_statut_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "nom": "X", "ordres_prix": "100", "ordres_quantite": "1",
            "ordres_statut": "bidon",
        })
    assert "ordres_actifs" in exc.value.erreurs


def test_id_existant_preserve_lors_de_re_saisie(depot):
    """Si l'ordre a déjà un id (cas re-saisie via formulaire), on le garde."""
    w = svc.creer(depot, {
        "nom": "X", "ordres_prix": "100", "ordres_quantite": "1",
        "ordres_id": "o-deja-attribue",
        "ordres_statut": "en_attente",
        "ordres_date_creation": "2026-01-01",
    })
    o = w["ordres_actifs"][0]
    assert o["id"] == "o-deja-attribue"
    assert o["date_creation"] == "2026-01-01"


# --- marquer_ordre ---------------------------------------------------------


def test_marquer_ordre_execute(depot):
    w = svc.creer(depot, {
        "nom": "X", "titre_id": "net",
        "ordres_prix": "100", "ordres_quantite": "1",
    })
    ordre_id = w["ordres_actifs"][0]["id"]
    assert svc.marquer_ordre(depot, w["id"], ordre_id, "execute",
                             mouvement_id="m-123") is True
    apres = svc.trouver(depot, w["id"])
    assert apres["ordres_actifs"][0]["statut"] == "execute"
    assert apres["ordres_actifs"][0]["mouvement_id"] == "m-123"


def test_marquer_ordre_annule(depot):
    w = svc.creer(depot, {
        "nom": "X", "ordres_prix": "100", "ordres_quantite": "1",
    })
    ordre_id = w["ordres_actifs"][0]["id"]
    assert svc.marquer_ordre(depot, w["id"], ordre_id, "annule") is True
    apres = svc.trouver(depot, w["id"])
    assert apres["ordres_actifs"][0]["statut"] == "annule"


def test_marquer_ordre_inexistant(depot):
    assert svc.marquer_ordre(depot, "w-inconnu", "o-x", "annule") is False


# --- agenda dashboard ------------------------------------------------------


def test_agenda_inclut_ordre_en_attente(depot):
    from app.services.dashboard_data import construire

    demain = (date.today() + timedelta(days=8)).isoformat()
    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "marche": "NYSE", "devise": "USD",
        "ordres_prix": "175", "ordres_quantite": "1",
        "ordres_validite": demain,
    })
    data = construire(depot, rattraper_virements=False)
    items_ordres = [i for i in data["agenda"] if i.get("kind") == "ordre_actif"]
    assert len(items_ordres) == 1
    item = items_ordres[0]
    assert item["date"] == demain
    assert "175" in item["libelle"]
    assert "$" in item["libelle"]


def test_agenda_exclut_ordre_execute(depot):
    from app.services.dashboard_data import construire

    demain = (date.today() + timedelta(days=8)).isoformat()
    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "ordres_prix": "175", "ordres_quantite": "1",
        "ordres_validite": demain, "ordres_statut": "execute",
    })
    data = construire(depot, rattraper_virements=False)
    assert not any(i.get("kind") == "ordre_actif" for i in data["agenda"])


def test_agenda_exclut_ordre_expire(depot):
    from app.services.dashboard_data import construire

    hier = (date.today() - timedelta(days=1)).isoformat()
    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "ordres_prix": "175", "ordres_quantite": "1",
        "ordres_validite": hier,  # validité passée
    })
    data = construire(depot, rattraper_virements=False)
    assert not any(i.get("kind") == "ordre_actif" for i in data["agenda"])


# --- ICS export ------------------------------------------------------------


def test_ics_inclut_ordre_avec_uid_stable(depot):
    from app.services.ics_export import generer_ics

    demain = (date.today() + timedelta(days=8)).isoformat()
    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "devise": "USD",
        "ordres_prix": "175", "ordres_quantite": "1",
        "ordres_validite": demain,
    })
    ics1 = generer_ics(depot).decode("utf-8")
    ics2 = generer_ics(depot).decode("utf-8")
    # UID stable entre 2 générations
    assert f"ordre-{w['id']}" in ics1
    assert f"ordre-{w['id']}" in ics2
    # Contenu cohérent
    assert "175" in ics1


# --- Flux exécution complet ------------------------------------------------


def test_executer_ordre_via_route_marque_execute_et_lie_mouvement(depot):
    """Le POST sur /mouvements/nouveau/achat avec source_ordre_* doit :
    1. Créer le mouvement
    2. Marquer l'ordre comme exécuté avec mouvement_id"""
    from app import create_app

    app = create_app()
    app.config["DEPOT"] = depot
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"

    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "compte_cible": "cto", "devise": "USD",
        "ordres_prix": "175", "ordres_quantite": "1",
        "ordres_validite": "2026-06-01",
    })
    ordre_id = w["ordres_actifs"][0]["id"]

    with app.test_client() as c:
        rep = c.post(
            "/mouvements/nouveau/achat",
            data={
                "compte_id": "cto",
                "titre_id": "net",
                "date": "2026-05-25",
                "quantite": "1",
                "prix_unitaire": "175",
                "frais_courtage": "8.50",
                "devise": "USD",
                "source_ordre_watch_id": w["id"],
                "source_ordre_id": ordre_id,
            },
        )
    assert rep.status_code == 302

    # Vérif : mouvement créé
    mouvements = depot.charger("mouvements")
    achats = [m for m in mouvements if m.get("type") == "achat"
              and m.get("titre_id") == "net"]
    assert len(achats) == 1
    mvt_id = achats[0]["id"]

    # Vérif : ordre marqué exécuté + lié au mouvement
    apres = svc.trouver(depot, w["id"])
    o = apres["ordres_actifs"][0]
    assert o["statut"] == "execute"
    assert o["mouvement_id"] == mvt_id


def test_reactiver_bouton_non_imbrique_et_fonctionnel(depot):
    """Régression : le bouton « ↻ Réactiver » de l'historique doit cibler un
    <form> placé HORS du formulaire d'édition. Un <form> imbriqué dans un autre
    est ignoré par les navigateurs → le bouton soumettait le form parent (sans
    effet) au lieu d'appeler reactiver_ordre."""
    from app import create_app

    app = create_app()
    app.config["DEPOT"] = depot
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"

    w = svc.creer(depot, {
        "nom": "Soitec", "ticker": "SOI",
        "ordres_prix": "103", "ordres_quantite": "1",
        "ordres_validite": "2026-06-30",
    })
    ordre_id = w["ordres_actifs"][0]["id"]
    # On clôt l'ordre → il rejoint l'historique (réactivable).
    svc.marquer_ordre(depot, w["id"], ordre_id, "annule")

    with app.test_client() as c:
        html = c.get(f"/watchlist/{w['id']}/editer").get_data(as_text=True)
        # Le bouton cible un form externe via l'attribut `form` (pas d'imbrication).
        assert f'form="reactiver-{ordre_id}"' in html
        assert f'<form id="reactiver-{ordre_id}"' in html

        # Et la réactivation fonctionne réellement (POST → 302).
        rep = c.post(f"/watchlist/{w['id']}/ordre/{ordre_id}/reactiver")
        assert rep.status_code == 302

    o = svc.trouver(depot, w["id"])["ordres_actifs"][0]
    assert o["statut"] == "en_attente"


# --- sens achat / vente -----------------------------------------------------

def test_ordre_sens_defaut_achat(depot):
    w = svc.creer(depot, {
        "nom": "X", "ticker": "X", "ordres_prix": "100", "ordres_quantite": "1",
    })
    assert w["ordres_actifs"][0]["sens"] == "achat"


def test_ordre_sens_vente_persiste(depot):
    w = svc.creer(depot, {
        "nom": "STM", "ticker": "STM",
        "ordres_actifs": [{"prix_limite": "45", "quantite": "2", "sens": "vente"}],
    })
    assert w["ordres_actifs"][0]["sens"] == "vente"


def test_ordre_sens_invalide_rejete(depot):
    with pytest.raises(svc.ErreursValidation):
        svc.creer(depot, {
            "nom": "X",
            "ordres_actifs": [{"prix_limite": "45", "quantite": "1", "sens": "location"}],
        })


def test_editer_rend_selecteur_sens(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    w = svc.creer(depot, {"nom": "STM", "ticker": "STM", "titre_id": "net"})
    with app.test_client() as c:
        html = c.get(f"/watchlist/{w['id']}/editer").get_data(as_text=True)
    assert 'name="ordre_sens"' in html
    assert ">Vente<" in html


def test_liste_executer_ordre_vente_pointe_vers_vente(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "compte_cible": "cto", "devise": "USD",
        "ordres_actifs": [{
            "prix_limite": "175", "quantite": "1", "sens": "vente",
            "statut": "en_attente",
        }],
    })
    with app.test_client() as c:
        html = c.get("/watchlist/").get_data(as_text=True)
    assert "nouveau/vente" in html
    assert "prix_unitaire_vente=175" in html


def test_executer_ordre_vente_cree_vente_et_marque_execute(depot):
    """L'exécution d'un ordre de vente crée un mouvement `vente` et marque
    l'ordre exécuté + lié au mouvement (miroir de l'achat)."""
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    # Lot détenu, nécessaire au calcul FIFO de la vente.
    depot.enregistrer("mouvements", [{
        "id": "a1", "type": "achat", "compte_id": "cto", "titre_id": "net",
        "date": "2026-01-01", "quantite": 2, "prix_unitaire": "100",
        "devise": "USD", "frais_courtage": "0", "taux_change": "1.0",
    }])
    w = svc.creer(depot, {
        "nom": "NET", "ticker": "NET", "titre_id": "net",
        "compte_cible": "cto", "devise": "USD",
        "ordres_actifs": [{
            "prix_limite": "175", "quantite": "1", "sens": "vente",
            "statut": "en_attente",
        }],
    })
    ordre_id = w["ordres_actifs"][0]["id"]

    with app.test_client() as c:
        rep = c.post("/mouvements/nouveau/vente", data={
            "compte_id": "cto", "titre_id": "net", "date": "2026-05-25",
            "quantite": "1", "prix_unitaire_vente": "175",
            "frais_courtage": "8.50", "devise": "USD", "taux_change": "1.0",
            "source_ordre_watch_id": w["id"], "source_ordre_id": ordre_id,
        })
    assert rep.status_code == 302

    ventes = [m for m in depot.charger("mouvements")
              if m.get("type") == "vente" and m.get("titre_id") == "net"]
    assert len(ventes) == 1
    o = svc.trouver(depot, w["id"])["ordres_actifs"][0]
    assert o["statut"] == "execute"
    assert o["mouvement_id"] == ventes[0]["id"]


def test_dashboard_agenda_libelle_ordre_vente(depot):
    from datetime import date, timedelta

    from app.services import dashboard_data

    echeance = (date.today() + timedelta(days=5)).isoformat()
    svc.creer(depot, {
        "nom": "STM", "ticker": "STM", "titre_id": "net", "devise": "EUR",
        "ordres_actifs": [{
            "prix_limite": "45", "quantite": "2", "sens": "vente",
            "statut": "en_attente", "validite": echeance,
        }],
    })
    data = dashboard_data.construire(depot)
    assert any("Ordre de vente actif" in str(e) for e in data["agenda"])
