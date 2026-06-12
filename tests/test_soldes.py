"""Tests du recalcul de solde cash et des positions."""

from decimal import Decimal

from app.services.soldes import calculer_positions, calculer_solde_cash


def test_taux_change_naffecte_pas_le_solde():
    """Le champ taux_change est purement informatif, le prix est en EUR."""
    mvts = [
        {"type": "alimentation_cash", "compte_id": "c1",
         "date": "2026-01-01", "montant": "1000.00"},
        {"type": "achat", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 1, "prix_unitaire": "100.00",
         "frais_courtage": "5.00", "taux_change": "1.1676",
         "devise": "USD"},
    ]
    # 1000 - (1 * 100 + 5) = 895, indépendamment du taux
    assert calculer_solde_cash(mvts, "c1") == Decimal("895.00")


def test_taux_change_naffecte_pas_le_solde_pour_vente():
    mvts = [
        {"type": "vente", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 1, "prix_unitaire_vente": "150.00",
         "frais_courtage": "5.00", "taux_change": "0.5",
         "devise": "USD"},
    ]
    # 150 - 5 = 145, indépendamment du taux
    assert calculer_solde_cash(mvts, "c1") == Decimal("145.00")


def test_solde_alimentation_seule():
    mvts = [
        {"type": "alimentation_cash", "compte_id": "c1",
         "date": "2026-01-01", "montant": "100.00"},
    ]
    assert calculer_solde_cash(mvts, "c1") == Decimal("100.00")


def test_solde_achat_diminue_avec_frais():
    mvts = [
        {"type": "alimentation_cash", "compte_id": "c1",
         "date": "2026-01-01", "montant": "1000.00"},
        {"type": "achat", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 2, "prix_unitaire": "100.00",
         "frais_courtage": "1.99", "taux_change": "1.0"},
    ]
    # 1000 - (2 * 100 + 1.99) = 798.01
    assert calculer_solde_cash(mvts, "c1") == Decimal("798.01")


def test_solde_vente_credite_net_des_frais():
    mvts = [
        {"type": "vente", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 1, "prix_unitaire_vente": "50.00",
         "frais_courtage": "0.99", "taux_change": "1.0"},
    ]
    assert calculer_solde_cash(mvts, "c1") == Decimal("49.01")


def test_solde_dividende_net_eur_si_dispo():
    mvts = [
        {"type": "dividende_recu", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-06-24", "montant_brut_total": "10.00",
         "montant_net_eur": "8.00"},
    ]
    assert calculer_solde_cash(mvts, "c1") == Decimal("8.00")


def test_solde_dividende_brut_si_pas_de_net():
    mvts = [
        {"type": "dividende_recu", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-06-24", "montant_brut_total": "10.00"},
    ]
    assert calculer_solde_cash(mvts, "c1") == Decimal("10.00")


def test_positions_apres_achat_et_vente_partielle():
    mvts = [
        {"type": "achat", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 5, "prix_unitaire": "10.00"},
        {"type": "vente", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-02-02", "quantite": 2,
         "prix_unitaire_vente": "12.00"},
    ]
    positions = calculer_positions(mvts, "c1")
    assert positions == {"t1": Decimal("3")}


def test_position_nulle_filtree():
    mvts = [
        {"type": "achat", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-01-02", "quantite": 1, "prix_unitaire": "10.00"},
        {"type": "vente", "compte_id": "c1", "titre_id": "t1",
         "date": "2026-02-02", "quantite": 1, "prix_unitaire_vente": "12.00"},
    ]
    assert calculer_positions(mvts, "c1") == {}
