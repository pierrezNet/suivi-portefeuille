"""Tests du calcul de plus-value et du bloc calcul_fifo immuable."""

from decimal import Decimal

import pytest

from app.services.plus_values import cumul_plus_values, preparer_calcul_fifo


def _achat(id_, date, quantite, prix, frais="0"):
    return {
        "id": id_, "type": "achat", "compte_id": "c1", "titre_id": "t1",
        "date": date, "quantite": quantite, "prix_unitaire": prix,
        "frais_courtage": frais,
    }


def test_preparer_calcul_fifo_exemple_readme():
    """Reproduit l'exemple du README : 2 lots, vente partielle de 2 actions."""
    mvts = [
        _achat("a", "2025-08-12", 2, "34.12", "1.99"),
        _achat("b", "2026-02-18", 1, "28.50", "1.50"),
    ]
    bloc = preparer_calcul_fifo(
        mvts, "c1", "t1", quantite=2, prix_unitaire_vente="38.20",
        frais_courtage="1.99",
    )
    assert bloc["prix_revient_total"] == "70.23"
    assert bloc["produit_vente_brut"] == "76.40"
    assert bloc["produit_vente_net"] == "74.41"
    assert bloc["plus_value_realisee"] == "4.18"
    assert len(bloc["lots_consommes"]) == 1
    assert bloc["lots_consommes"][0]["achat_id"] == "a"


def test_preparer_calcul_fifo_quantite_insuffisante():
    mvts = [_achat("a", "2025-08-12", 1, "10.00", "0")]
    with pytest.raises(ValueError, match="Quantité insuffisante"):
        preparer_calcul_fifo(
            mvts, "c1", "t1", quantite=2, prix_unitaire_vente="20.00",
        )


def test_cumul_plus_values_par_titre():
    mvts = [
        {"type": "vente", "titre_id": "t1", "compte_id": "c1",
         "date": "2026-04-01",
         "calcul_fifo": {"plus_value_realisee": "10.50"}},
        {"type": "vente", "titre_id": "t1", "compte_id": "c1",
         "date": "2026-05-01",
         "calcul_fifo": {"plus_value_realisee": "-3.20"}},
        {"type": "vente", "titre_id": "t2", "compte_id": "c1",
         "date": "2026-04-15",
         "calcul_fifo": {"plus_value_realisee": "100.00"}},
        {"type": "achat", "titre_id": "t1", "compte_id": "c1"},
    ]
    assert cumul_plus_values(mvts, titre_id="t1") == Decimal("7.30")
    assert cumul_plus_values(mvts, titre_id="t2") == Decimal("100.00")
    assert cumul_plus_values(mvts) == Decimal("107.30")
    assert cumul_plus_values(mvts, annee=2026) == Decimal("107.30")
    assert cumul_plus_values(mvts, annee=2025) == Decimal("0.00")
