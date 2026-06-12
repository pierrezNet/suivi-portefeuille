"""Tests de la valorisation des positions au dashboard."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.dashboard_data import (
    AGE_COURS_ALERTE_JOURS,
    construire,
    valoriser_position,
)
from app.services.stockage import Depot


# --- Tests unitaires sur valoriser_position --------------------------------


def test_valoriser_position_avec_cours():
    titre = {"cours_jour_eur": "219.16", "date_cours_jour": "2026-06-08"}
    r = valoriser_position(titre, Decimal("2"), Decimal("180"), today=date(2026, 6, 10))
    assert r["cours_jour_eur"] == Decimal("219.16")
    assert r["valo_eur"] == Decimal("438.32")
    assert r["pv_latente_eur"] == Decimal("78.32")  # (219.16-180) * 2
    assert r["age_jours"] == 2


def test_valoriser_position_sans_cours():
    titre = {}
    r = valoriser_position(titre, Decimal("3"), Decimal("100"), today=date(2026, 6, 10))
    assert r["cours_jour_eur"] is None
    assert r["valo_eur"] is None
    assert r["pv_latente_eur"] is None
    assert r["age_jours"] is None


def test_valoriser_position_sans_pru_calcule_valo_mais_pas_pv():
    titre = {"cours_jour_eur": "100", "date_cours_jour": "2026-06-08"}
    r = valoriser_position(titre, Decimal("5"), None, today=date(2026, 6, 8))
    assert r["valo_eur"] == Decimal("500.00")
    assert r["pv_latente_eur"] is None  # pas de PRU connu


def test_valoriser_position_cours_invalide_ignore():
    titre = {"cours_jour_eur": "n/a", "date_cours_jour": "2026-06-08"}
    r = valoriser_position(titre, Decimal("1"), Decimal("10"), today=date(2026, 6, 8))
    assert r["cours_jour_eur"] is None
    assert r["valo_eur"] is None


def test_valoriser_position_titre_none():
    r = valoriser_position(None, Decimal("1"), Decimal("10"), today=date(2026, 6, 8))
    assert r["valo_eur"] is None


# --- Tests d'intégration via construire() ----------------------------------


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "pea", "nom": "PEA BD", "type": "PEA", "broker": "BD", "numero": "1"},
        {"id": "cto", "nom": "CTO BD", "type": "CTO", "broker": "BD", "numero": "2"},
    ])
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STM", "devise": "EUR",
         "cours_jour_eur": "64.28", "date_cours_jour": "2026-06-08"},
        {"id": "net", "ticker": "NET", "nom": "Cloudflare", "devise": "USD",
         "cours_jour_eur": "219.16", "date_cours_jour": "2026-06-05"},
        # Pas de cours pour celui-ci
        {"id": "soi", "ticker": "SOI", "nom": "Soitec", "devise": "EUR"},
    ])
    d.enregistrer("mouvements", [
        # Cash PEA : +200
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-05-01", "montant": "200"},
        # Achat STM : 2 @ 50 PEA
        {"id": "m2", "type": "achat", "compte_id": "pea", "titre_id": "stm",
         "date": "2026-05-10", "quantite": "2", "prix_unitaire": "50", "frais": "0"},
        # Cash CTO : +1000
        {"id": "m3", "type": "alimentation_cash", "compte_id": "cto",
         "date": "2026-05-01", "montant": "1000"},
        # Achat NET : 1 @ 200 CTO
        {"id": "m4", "type": "achat", "compte_id": "cto", "titre_id": "net",
         "date": "2026-05-10", "quantite": "1", "prix_unitaire": "200", "frais": "0"},
        # Achat SOI : 1 @ 80 CTO (pas de cours)
        {"id": "m5", "type": "achat", "compte_id": "cto", "titre_id": "soi",
         "date": "2026-05-12", "quantite": "1", "prix_unitaire": "80", "frais": "0"},
    ])
    d.enregistrer("watchlist", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    return d


def test_construire_calcule_valo_par_compte(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 6, 10))
    par_id = {c["compte"]["id"]: c for c in data["comptes"]}
    pea = par_id["pea"]
    cto = par_id["cto"]

    # PEA : 2 STM @ 64.28 = 128.56 ; PRU 50 → PV latente = (64.28-50)*2 = 28.56
    assert pea["valo_titres_eur"] == Decimal("128.56")
    assert pea["pv_latente_eur"] == Decimal("28.56")

    # CTO : 1 NET @ 219.16 = 219.16 ; SOI pas valorisé
    assert cto["valo_titres_eur"] == Decimal("219.16")
    assert cto["pv_latente_eur"] == Decimal("19.16")  # PRU NET = 200


def test_construire_totaux_globaux(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 6, 10))
    # Cash : 200 - 100 (achat STM) + 1000 - 200 (achat NET) - 80 (achat SOI) = 820
    assert data["total_cash"] == Decimal("820.00")
    # Valo : 128.56 + 219.16 = 347.72
    assert data["total_valo_titres"] == Decimal("347.72")
    # Total : 820 + 347.72 = 1167.72
    assert data["total_portefeuille"] == Decimal("1167.72")
    # PV latente : 28.56 + 19.16 = 47.72
    assert data["total_pv_latente"] == Decimal("47.72")


def test_construire_signale_positions_sans_cours(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 6, 10))
    # SOI n'a pas de cours → 1 position sans cours
    assert data["nb_positions_sans_cours"] == 1
    assert data["cours_a_actualiser"] is True


def test_construire_age_cours_max(depot):
    # Cours STM 2026-06-08, NET 2026-06-05 → max age = 5 jours au 2026-06-10
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 6, 10))
    assert data["age_cours_max_jours"] == 5


def test_alerte_si_age_cours_depasse_seuil(depot):
    # On simule une date longtemps après l'import (> 7 jours)
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 7, 1))
    assert data["age_cours_max_jours"] > AGE_COURS_ALERTE_JOURS
    assert data["cours_a_actualiser"] is True


def test_aucun_titre_valorisable_renvoie_zero(tmp_path):
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "pea", "nom": "PEA", "type": "PEA", "broker": "BD", "numero": "1"}
    ])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    d.enregistrer("watchlist", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    data = construire(d, rattraper_virements=False, aujourd_hui=date(2026, 6, 10))
    assert data["total_valo_titres"] == Decimal("0.00")
    assert data["total_pv_latente"] == Decimal("0.00")
    assert data["age_cours_max_jours"] is None
    assert data["nb_positions_sans_cours"] == 0
    assert data["cours_a_actualiser"] is False
