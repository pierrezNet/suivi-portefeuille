"""Réserve de cash calculée sur les titres fusionnés (helper partagé `suivi`)."""

from decimal import Decimal

from app.services import suivi


def test_reserve_groupe_par_compte():
    titres = [
        {"ticker": "A", "compte_cible": "pea", "ordres_actifs": [
            {"prix_limite": "10", "quantite": "3", "sens": "achat", "statut": "en_attente"}]},
        {"ticker": "B", "compte_cible": "pea", "ordres_actifs": [
            {"prix_limite": "5", "quantite": "2", "sens": "achat", "statut": "en_attente"}]},
    ]
    r = suivi.reserve_cash_par_compte(titres)
    assert r["pea"]["total"] == Decimal("40.00")  # 30 + 10
    assert len(r["pea"]["ordres"]) == 2


def test_reserve_exclut_vente_execute_et_sans_compte():
    titres = [
        {"compte_cible": "pea", "ordres_actifs": [
            {"prix_limite": "10", "quantite": "3", "sens": "vente", "statut": "en_attente"}]},
        {"compte_cible": "pea", "ordres_actifs": [
            {"prix_limite": "10", "quantite": "3", "sens": "achat", "statut": "execute"}]},
        {"ordres_actifs": [  # pas de compte_cible → ignoré
            {"prix_limite": "10", "quantite": "3", "sens": "achat", "statut": "en_attente"}]},
    ]
    assert suivi.reserve_cash_par_compte(titres) == {}


def test_reserve_exclut_ordre_expire():
    titres = [{"compte_cible": "pea", "ordres_actifs": [
        {"prix_limite": "10", "quantite": "3", "sens": "achat",
         "statut": "en_attente", "validite": "2026-01-01"}]}]
    assert suivi.reserve_cash_par_compte(titres, today_iso="2026-08-06") == {}
