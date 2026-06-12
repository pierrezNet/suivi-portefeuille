"""Tests du service d'onboarding (dépôt vierge + jeu d'exemple)."""

from app.services import dashboard_data, onboarding
from app.services.stockage import Depot


def test_est_vierge(tmp_path):
    depot = Depot(tmp_path)
    assert onboarding.est_vierge(depot)
    depot.enregistrer("comptes", [
        {"id": "x", "nom": "X", "type": "PEA", "devise_principale": "EUR"},
    ])
    assert not onboarding.est_vierge(depot)


def test_creer_jeu_exemple(tmp_path):
    depot = Depot(tmp_path)
    onboarding.creer_jeu_exemple(depot)
    assert not onboarding.est_vierge(depot)
    comptes = depot.charger("comptes")
    assert len(comptes) == 2
    # Numéros volontairement fictifs (jamais de vraies coordonnées).
    for c in comptes:
        assert "EXEMPLE" in c["numero"]
    # Le dashboard se construit sans erreur sur le jeu d'exemple.
    data = dashboard_data.construire(depot)
    assert "total_cash" in data


def test_creer_jeu_exemple_n_ecrase_pas_les_donnees(tmp_path):
    depot = Depot(tmp_path)
    depot.enregistrer("comptes", [
        {"id": "mien", "nom": "Mien", "type": "CTO", "devise_principale": "EUR"},
    ])
    onboarding.creer_jeu_exemple(depot)
    comptes = depot.charger("comptes")
    assert len(comptes) == 1  # inchangé : on n'écrase pas un dépôt non vierge
    assert comptes[0]["id"] == "mien"
