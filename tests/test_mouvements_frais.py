"""Frais autonome (frais bancaires, frais sur virement, droits de garde…) :
type de mouvement saisissable, ventilé comme un COÛT qui réduit le cash — et
non comme un retrait (l'argent est réellement parti)."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services import mouvements as svc
from app.services.soldes import calculer_solde_cash, calculer_ventilation_cash
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    for nom in (
        "mouvements", "titres", "evenements", "notes_titres",
        "watchlist", "suggestions_ia", "virements_programmes",
    ):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_creer_frais_reduit_le_cash_et_est_ventile_comme_cout(depot):
    svc.creer(depot, "alimentation_cash", {
        "compte_id": "pea", "date": "2026-04-18", "montant": "100"})
    svc.creer(depot, "frais", {
        "compte_id": "pea", "date": "2026-04-18", "montant": "6",
        "libelle": "Frais sur virement"})

    mvts = depot.charger("mouvements")
    frais = next(m for m in mvts if m["type"] == "frais")
    assert frais["montant"] == "6"
    assert frais["libelle"] == "Frais sur virement"

    # Cash : 100 − 6 = 94 (le frais retire du cash)
    assert calculer_solde_cash(mvts, "pea") == Decimal("94.00")
    # Ventilé comme un coût, PAS comme un retrait
    v = calculer_ventilation_cash(mvts, "pea")
    assert v["frais"] == Decimal("6")
    assert v["retraits"] == Decimal("0")


def test_frais_montant_negatif_ou_nul_refuse(depot):
    with pytest.raises(svc.ErreursValidation):
        svc.creer(depot, "frais", {
            "compte_id": "pea", "date": "2026-04-18", "montant": "0"})


def test_frais_saisissable_dans_l_interface(depot):
    c = _client(depot)
    # Carte « Frais » proposée dans le choix de type
    choix = c.get("/mouvements/nouveau").get_data(as_text=True)
    assert "type_mouvement=frais" in choix or "/nouveau/frais" in choix
    # Le formulaire du frais expose bien un champ Montant (la régression : il
    # n'y avait aucune branche `frais`, donc pas de saisie possible)
    form = c.get("/mouvements/nouveau/frais").get_data(as_text=True)
    assert 'name="montant"' in form
