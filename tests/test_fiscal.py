"""Tests du service fiscal : stats annuelles, imputations MV, indicateurs PEA."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import fiscal as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    return d


def _achat(id_, compte, titre, date_, qte, prix, frais="0"):
    return {"id": id_, "type": "achat", "compte_id": compte, "titre_id": titre,
            "date": date_, "quantite": qte, "prix_unitaire": prix,
            "frais_courtage": frais, "taux_change": "1"}


def _vente(id_, compte, titre, date_, qte, prix, frais="0", pv="0"):
    return {"id": id_, "type": "vente", "compte_id": compte, "titre_id": titre,
            "date": date_, "quantite": qte, "prix_unitaire_vente": prix,
            "frais_courtage": frais, "taux_change": "1",
            "calcul_fifo": {"plus_value_realisee": pv,
                            "prix_revient_total": "0",
                            "produit_vente_net": "0"}}


# --- stats_compte_annee ----------------------------------------------------


def test_stats_compte_annee_filtre_annee_et_compte():
    mvts = [
        {"id": "1", "type": "alimentation_cash", "compte_id": "cto",
         "date": "2026-01-01", "montant": "100"},
        {"id": "2", "type": "alimentation_cash", "compte_id": "cto",
         "date": "2025-12-01", "montant": "50"},
        {"id": "3", "type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-01-01", "montant": "999"},
    ]
    s = svc.stats_compte_annee(mvts, "cto", 2026)
    assert s.montant_alimentations == Decimal("100.00")


def test_stats_dividendes_prefere_net_eur_si_dispo():
    mvts = [
        {"type": "dividende_recu", "compte_id": "cto", "titre_id": "x",
         "date": "2026-04-01", "montant_brut_total": "10",
         "montant_net_eur": "8"},
        {"type": "dividende_recu", "compte_id": "cto", "titre_id": "y",
         "date": "2026-04-02", "montant_brut_total": "5"},
    ]
    s = svc.stats_compte_annee(mvts, "cto", 2026)
    assert s.dividendes_recus_eur == Decimal("13.00")


def test_stats_pv_realisees_somme():
    mvts = [
        _vente("1", "cto", "x", "2026-04-01", 1, "10", pv="50"),
        _vente("2", "cto", "x", "2026-05-01", 1, "10", pv="-10"),
    ]
    s = svc.stats_compte_annee(mvts, "cto", 2026)
    assert s.plus_values_realisees == Decimal("40.00")


# --- imputations -----------------------------------------------------------


def test_imputations_aucune_mv_anterieure():
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="100")]
    res = svc.calculer_imputations(mvts, "cto", 2026)
    assert res.pv_brute_annee == Decimal("100.00")
    assert res.moins_values_imputees == Decimal("0.00")
    assert res.pv_nette_imposable == Decimal("100.00")
    assert res.moins_values_a_reporter_total == Decimal("0.00")


def test_imputations_mv_anterieure_partielle():
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="100")]
    res = svc.calculer_imputations(
        mvts, "cto", 2026,
        moins_values_anterieures=[{"annee": 2024, "montant": "30"}],
    )
    assert res.moins_values_imputees == Decimal("30.00")
    assert res.pv_nette_imposable == Decimal("70.00")
    assert res.moins_values_a_reporter_total == Decimal("0.00")


def test_imputations_mv_anterieure_excedentaire():
    """MV anciennes > PV de l'année : reste reportable."""
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="50")]
    res = svc.calculer_imputations(
        mvts, "cto", 2026,
        moins_values_anterieures=[{"annee": 2024, "montant": "200"}],
    )
    assert res.moins_values_imputees == Decimal("50.00")
    assert res.pv_nette_imposable == Decimal("0.00")
    assert res.moins_values_a_reporter_total == Decimal("150.00")
    assert res.detail_reports[0]["annee_origine"] == 2024
    assert res.detail_reports[0]["restant"] == Decimal("150.00")


def test_imputations_perte_annee_courante_creee_un_report():
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="-80")]
    res = svc.calculer_imputations(mvts, "cto", 2026)
    assert res.pv_brute_annee == Decimal("-80.00")
    assert res.moins_values_a_reporter_total == Decimal("80.00")
    assert res.detail_reports[0]["annee_origine"] == 2026
    assert res.detail_reports[0]["expire_apres"] == 2036


def test_imputations_expiration_apres_10_ans():
    """Une moins-value de 2014 ne doit plus être utilisable en 2026."""
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="100")]
    res = svc.calculer_imputations(
        mvts, "cto", 2026,
        moins_values_anterieures=[{"annee": 2014, "montant": "200"}],
    )
    assert res.moins_values_imputees == Decimal("0.00")
    assert res.pv_nette_imposable == Decimal("100.00")


def test_imputations_fifo_sur_les_reports_anciens_dabord():
    mvts = [_vente("1", "cto", "x", "2026-04-01", 1, "10", pv="100")]
    res = svc.calculer_imputations(
        mvts, "cto", 2026,
        moins_values_anterieures=[
            {"annee": 2025, "montant": "60"},
            {"annee": 2020, "montant": "40"},
        ],
    )
    # Le 2020 est consommé en entier d'abord (40), puis 60 du 2025.
    assert res.moins_values_imputees == Decimal("100.00")


# --- indicateurs PEA -------------------------------------------------------


def test_pea_apports_nets_et_plafond():
    compte = {"id": "pea", "type": "PEA", "date_ouverture": "2025-01-15"}
    mvts = [
        {"type": "alimentation_cash", "compte_id": "pea",
         "date": "2025-01-15", "montant": "1000"},
        {"type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-04-15", "montant": "500"},
        {"type": "retrait_cash", "compte_id": "pea",
         "date": "2026-05-15", "montant": "200"},
    ]
    ind = svc.indicateurs_pea(mvts, compte, aujourd_hui=date(2026, 5, 6))
    assert ind.apports_nets_cumules == Decimal("1300.00")
    assert ind.plafond_restant == Decimal("148700.00")
    assert ind.annees_de_detention == 1
    assert ind.eligible_exoneration_5_ans is False


def test_pea_eligible_apres_5_ans():
    compte = {"id": "pea", "type": "PEA", "date_ouverture": "2020-01-01"}
    ind = svc.indicateurs_pea([], compte, aujourd_hui=date(2026, 1, 2))
    assert ind.annees_de_detention == 6
    assert ind.eligible_exoneration_5_ans is True


# --- annees_avec_activite --------------------------------------------------


def test_annees_avec_activite():
    mvts = [
        {"date": "2024-01-01"},
        {"date": "2026-04-15"},
        {"date": "2025-12-31"},
    ]
    assert svc.annees_avec_activite(mvts) == [2024, 2025, 2026]


def test_stats_globales_annee_cumule_tous_comptes():
    mvts = [
        {"type": "alimentation_cash", "compte_id": "a",
         "date": "2026-01-01", "montant": "100"},
        {"type": "alimentation_cash", "compte_id": "b",
         "date": "2026-02-01", "montant": "200"},
    ]
    comptes = [{"id": "a", "type": "CTO"}, {"id": "b", "type": "PEA"}]
    agg = svc.stats_globales_annee(mvts, comptes, 2026)
    assert agg["cumul"].montant_alimentations == Decimal("300.00")
    assert len(agg["par_compte"]) == 2
