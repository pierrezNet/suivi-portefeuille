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


# --- Rappels lecture seule : ordres actifs + prédictions en cours ----------


def _depot_rappels(tmp_path):
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "cto", "nom": "CTO", "type": "CTO", "devise_principale": "EUR"}])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    d.enregistrer("watchlist", [{
        "id": "w1", "ticker": "STM", "nom": "STMicro", "devise": "EUR",
        "ordres_actifs": [
            # achat dont la validité est LOIN (hors horizon agenda 60 j)
            {"id": "o1", "prix_limite": "40", "quantite": 2, "sens": "achat",
             "statut": "en_attente", "validite": "2027-12-31"},
            # ordre de VENTE
            {"id": "o2", "prix_limite": "55", "quantite": 1, "sens": "vente",
             "statut": "en_attente", "validite": "2026-07-10"},
            # annulé → exclu
            {"id": "o3", "prix_limite": "30", "quantite": 1, "sens": "achat",
             "statut": "annule"},
        ],
    }])
    d.enregistrer("predictions", [
        {"id": "p1", "ticker": "NVDA", "nom": "Nvidia", "sens": "hausse",
         "cours_reference": "200", "date_echeance": "2026-12-01", "conviction": 3,
         "horizon_jours": 180, "devise": "USD", "statut": "en_cours",
         "date_prediction": "2026-06-01"},
        {"id": "p2", "ticker": "X", "nom": "X", "sens": "baisse",
         "cours_reference": "10", "date_echeance": "2026-05-01", "conviction": 2,
         "statut": "evaluee", "date_prediction": "2026-01-01"},
    ])
    return d


def test_construire_ordres_actifs_tous_sens_et_hors_horizon(tmp_path):
    data = construire(_depot_rappels(tmp_path), rattraper_virements=False,
                      aujourd_hui=date(2026, 6, 10))
    ordres = data["ordres_actifs"]
    assert len(ordres) == 2  # les 2 en_attente, pas l'annulé
    assert {o["sens"] for o in ordres} == {"achat", "vente"}
    # l'ordre hors horizon (2027) est présent — contrairement à l'agenda qui le filtre
    assert any(o["validite"] == "2027-12-31" for o in ordres)


def test_construire_predictions_en_cours_seules(tmp_path):
    data = construire(_depot_rappels(tmp_path), rattraper_virements=False,
                      aujourd_hui=date(2026, 6, 10))
    preds = data["predictions_en_cours"]
    assert len(preds) == 1  # la "evaluee" est exclue
    assert preds[0]["ticker"] == "NVDA"


def test_dashboard_affiche_ordres_et_predictions(tmp_path):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=_depot_rappels(tmp_path), TESTING=True, SECRET_KEY="t")
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Ordres limites actifs" in html and "STM" in html
    assert "Prédictions en cours" in html and "NVDA" in html


def test_construire_equity_gains_latent_realise(tmp_path):
    """Par relevé : capital, PV réalisées cumulées, gains totaux. 2e panneau =
    latentes (base) + réalisées (bande) = totales (haut)."""
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [
        {"id": "v1", "type": "vente", "compte_id": "pea", "titre_id": "x",
         "date": "2026-07-01", "quantite": "1", "prix_unitaire_vente": "100",
         "calcul_fifo": {"plus_value_realisee": "30"}},
    ])
    d.enregistrer("snapshots", [
        {"date": "2026-06-15", "portefeuille_total": "1050", "cash_total": "1000",
         "valo_titres_total": "50", "pv_latente_total": "50"},
        {"date": "2026-07-15", "portefeuille_total": "1400", "cash_total": "1300",
         "valo_titres_total": "100", "pv_latente_total": "100"},
    ])
    for nom in ("watchlist", "evenements", "virements_programmes"):
        d.enregistrer(nom, [])
    data = construire(d, rattraper_virements=False, aujourd_hui=date(2026, 7, 20))
    pts = data["equity_points"]
    assert pts[0]["realise_cumul"] == Decimal("0.00")   # 15/06 : avant la vente
    assert pts[1]["realise_cumul"] == Decimal("30")     # 15/07 : après
    assert pts[0]["capital"] == Decimal("1000")         # 1050 − 50
    assert pts[1]["gains_totaux"] == Decimal("130")     # latent 100 + réalisé 30
    pv = data["equity_pv_coords"]
    assert pv["derniere_bande"] == Decimal("30")        # bande = réalisé (dernier)
    assert pv["min"] == Decimal("50") and pv["max"] == Decimal("130")


def test_dashboard_courbe_tooltips_accessibles(tmp_path):
    from app import create_app

    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    d.enregistrer("snapshots", [
        {"date": "2026-06-15", "portefeuille_total": "1050", "pv_latente_total": "50"},
        {"date": "2026-07-15", "portefeuille_total": "1400", "pv_latente_total": "100"},
    ])
    for nom in ("watchlist", "evenements", "virements_programmes"):
        d.enregistrer(nom, [])
    app = create_app()
    app.config.update(DEPOT=d, TESTING=True, SECRET_KEY="t")
    html = app.test_client().get("/").get_data(as_text=True)
    assert "equity-hit" in html and "data-tip=" in html        # zones interactives
    assert 'role="img"' in html and "capital investi" in html  # aria-label des points
    assert "PV totales" in html                                 # légende 2e graphe
