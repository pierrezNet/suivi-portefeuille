"""Ordres limites actifs, désormais portés par le titre (service `titres` +
helpers purs `suivi`) : parsing/validation, marquer_ordre, agenda dashboard,
export ICS, flux d'exécution (achat/vente), réactivation."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.services import suivi
from app.services import titres as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "cto", "nom": "CTO", "type": "CTO"},
        {"id": "pea", "nom": "PEA", "type": "PEA"},
    ])
    d.enregistrer("titres", [
        {"id": "net", "ticker": "NET", "nom": "Cloudflare", "devise": "USD",
         "statut": "veille", "priorite": "moyenne"},
    ])
    d.enregistrer("evenements", [])
    d.enregistrer("mouvements", [])
    d.enregistrer("watchlist", [])
    return d


def _pose_ordre(depot, titre_id, *, sens="achat", prix="175", quantite="1",
                validite="", statut="en_attente", compte_cible=None):
    """Attache un ordre à un titre existant (écriture directe, comme la migration)."""
    items = depot.charger("titres")
    for t in items:
        if t["id"] == titre_id:
            if compte_cible:
                t["compte_cible"] = compte_cible
            ordre = {
                "prix_limite": prix, "quantite": quantite, "sens": sens,
                "statut": statut,
            }
            if validite:
                ordre["validite"] = validite
            t["ordres_actifs"] = suivi._parse_ordres([ordre])
            depot.enregistrer("titres", items)
            return t["ordres_actifs"][0]["id"]
    raise KeyError(titre_id)


# --- _parse_ordres + validation --------------------------------------------


def test_parse_ordres_normalise():
    ordres = suivi._parse_ordres([
        {"prix_limite": "100", "quantite": "1", "validite": "2026-06-01", "note": "A"},
        {"prix_limite": "50", "quantite": "2"},
    ])
    assert len(ordres) == 2
    o1, o2 = ordres
    assert o1["prix_limite"] == "100"
    assert o1["quantite"] == 1
    assert o1["validite"] == "2026-06-01"
    assert o1["statut"] == "en_attente"
    assert o1["note"] == "A"
    assert o1["id"].startswith("o-")
    assert o2["prix_limite"] == "50" and o2["quantite"] == 2


def test_validation_prix_negatif_rejete():
    with pytest.raises(ValueError):
        suivi._parse_ordres([{"prix_limite": "-10", "quantite": "1"}])


def test_validation_quantite_zero_rejete():
    with pytest.raises(ValueError):
        suivi._parse_ordres([{"prix_limite": "100", "quantite": "0"}])


def test_validation_validite_format_iso():
    with pytest.raises(ValueError):
        suivi._parse_ordres([{"prix_limite": "100", "quantite": "1", "validite": "06/01/2026"}])


def test_validation_statut_invalide():
    with pytest.raises(ValueError):
        suivi._parse_ordres([{"prix_limite": "100", "quantite": "1", "statut": "bidon"}])


def test_id_existant_preserve_lors_de_re_saisie():
    ordres = suivi._parse_ordres([{
        "prix_limite": "100", "quantite": "1",
        "id": "o-deja-attribue", "statut": "en_attente",
        "date_creation": "2026-01-01",
    }])
    assert ordres[0]["id"] == "o-deja-attribue"
    assert ordres[0]["date_creation"] == "2026-01-01"


def test_ordre_sens_defaut_achat():
    assert suivi._parse_ordres([{"prix_limite": "100", "quantite": "1"}])[0]["sens"] == "achat"


def test_ordre_sens_vente_persiste():
    ordres = suivi._parse_ordres([{"prix_limite": "45", "quantite": "2", "sens": "vente"}])
    assert ordres[0]["sens"] == "vente"


def test_ordre_sens_invalide_rejete():
    with pytest.raises(ValueError):
        suivi._parse_ordres([{"prix_limite": "45", "quantite": "1", "sens": "location"}])


# --- marquer_ordre ---------------------------------------------------------


def test_marquer_ordre_execute(depot):
    oid = _pose_ordre(depot, "net", prix="100", quantite="1")
    assert svc.marquer_ordre(depot, "net", oid, "execute", mouvement_id="m-123") is True
    apres = svc.trouver(depot, "net")
    assert apres["ordres_actifs"][0]["statut"] == "execute"
    assert apres["ordres_actifs"][0]["mouvement_id"] == "m-123"


def test_marquer_ordre_annule(depot):
    oid = _pose_ordre(depot, "net", prix="100", quantite="1")
    assert svc.marquer_ordre(depot, "net", oid, "annule") is True
    assert svc.trouver(depot, "net")["ordres_actifs"][0]["statut"] == "annule"


def test_marquer_ordre_inexistant(depot):
    assert svc.marquer_ordre(depot, "inconnu", "o-x", "annule") is False


# --- agenda dashboard ------------------------------------------------------


def test_agenda_inclut_ordre_en_attente(depot):
    from app.services.dashboard_data import construire

    demain = (date.today() + timedelta(days=8)).isoformat()
    _pose_ordre(depot, "net", prix="175", quantite="1", validite=demain)
    data = construire(depot, rattraper_virements=False)
    items = [i for i in data["agenda"] if i.get("kind") == "ordre_actif"]
    assert len(items) == 1
    assert items[0]["date"] == demain
    assert "175" in items[0]["libelle"] and "$" in items[0]["libelle"]


def test_agenda_exclut_ordre_execute(depot):
    from app.services.dashboard_data import construire

    demain = (date.today() + timedelta(days=8)).isoformat()
    _pose_ordre(depot, "net", validite=demain, statut="execute")
    data = construire(depot, rattraper_virements=False)
    assert not any(i.get("kind") == "ordre_actif" for i in data["agenda"])


def test_agenda_exclut_ordre_expire(depot):
    from app.services.dashboard_data import construire

    hier = (date.today() - timedelta(days=1)).isoformat()
    _pose_ordre(depot, "net", validite=hier)
    data = construire(depot, rattraper_virements=False)
    assert not any(i.get("kind") == "ordre_actif" for i in data["agenda"])


def test_dashboard_agenda_libelle_ordre_vente(depot):
    from app.services import dashboard_data

    echeance = (date.today() + timedelta(days=5)).isoformat()
    _pose_ordre(depot, "net", sens="vente", prix="45", quantite="2", validite=echeance)
    data = dashboard_data.construire(depot, rattraper_virements=False)
    assert any("Ordre de vente actif" in str(e) for e in data["agenda"])


# --- ICS export ------------------------------------------------------------


def test_ics_inclut_ordre_avec_uid_stable(depot):
    from app.services.ics_export import generer_ics

    demain = (date.today() + timedelta(days=8)).isoformat()
    _pose_ordre(depot, "net", prix="175", quantite="1", validite=demain)
    ics1 = generer_ics(depot).decode("utf-8")
    ics2 = generer_ics(depot).decode("utf-8")
    assert "ordre-net" in ics1
    assert "ordre-net" in ics2
    assert "175" in ics1


# --- Flux d'exécution complet ----------------------------------------------


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_executer_ordre_via_route_marque_execute_et_lie_mouvement(depot):
    oid = _pose_ordre(depot, "net", prix="175", quantite="1",
                      validite="2026-06-01", compte_cible="cto")
    rep = _client(depot).post("/mouvements/nouveau/achat", data={
        "compte_id": "cto", "titre_id": "net", "date": "2026-05-25",
        "quantite": "1", "prix_unitaire": "175", "frais_courtage": "8.50",
        "devise": "USD",
        "source_ordre_titre_id": "net", "source_ordre_id": oid,
    })
    assert rep.status_code == 302
    achats = [m for m in depot.charger("mouvements")
              if m.get("type") == "achat" and m.get("titre_id") == "net"]
    assert len(achats) == 1
    o = svc.trouver(depot, "net")["ordres_actifs"][0]
    assert o["statut"] == "execute"
    assert o["mouvement_id"] == achats[0]["id"]


def test_liste_executer_ordre_vente_pointe_vers_vente(depot):
    _pose_ordre(depot, "net", sens="vente", prix="175", quantite="1",
                compte_cible="cto")
    html = _client(depot).get("/titres/").get_data(as_text=True)
    assert "nouveau/vente" in html
    assert "prix_unitaire_vente=175" in html


def test_executer_ordre_vente_cree_vente_et_marque_execute(depot):
    depot.enregistrer("mouvements", [{
        "id": "a1", "type": "achat", "compte_id": "cto", "titre_id": "net",
        "date": "2026-01-01", "quantite": 2, "prix_unitaire": "100",
        "devise": "USD", "frais_courtage": "0", "taux_change": "1.0",
    }])
    oid = _pose_ordre(depot, "net", sens="vente", prix="175", quantite="1",
                      compte_cible="cto")
    rep = _client(depot).post("/mouvements/nouveau/vente", data={
        "compte_id": "cto", "titre_id": "net", "date": "2026-05-25",
        "quantite": "1", "prix_unitaire_vente": "175", "frais_courtage": "8.50",
        "devise": "USD", "taux_change": "1.0",
        "source_ordre_titre_id": "net", "source_ordre_id": oid,
    })
    assert rep.status_code == 302
    ventes = [m for m in depot.charger("mouvements")
              if m.get("type") == "vente" and m.get("titre_id") == "net"]
    assert len(ventes) == 1
    o = svc.trouver(depot, "net")["ordres_actifs"][0]
    assert o["statut"] == "execute"
    assert o["mouvement_id"] == ventes[0]["id"]


def test_reactiver_ordre_depuis_la_fiche(depot):
    """Un ordre clos réapparaît dans l'historique de la fiche avec un bouton
    « ↻ Réactiver » (form non imbriqué) qui le remet en attente."""
    oid = _pose_ordre(depot, "net", prix="103", quantite="1")
    svc.marquer_ordre(depot, "net", oid, "annule")  # clos → historique

    c = _client(depot)
    html = c.get("/titres/net").get_data(as_text=True)
    assert f"/ordre/{oid}/reactiver" in html

    rep = c.post(f"/titres/net/ordre/{oid}/reactiver")
    assert rep.status_code == 302
    assert svc.trouver(depot, "net")["ordres_actifs"][0]["statut"] == "en_attente"
