"""Affichage de la liste des mouvements : l'impact cash des achats/ventes doit
utiliser la virgule française (via le filtre `euros`), pas le point du `round`
JS/Jinja."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services import mouvements as svc
from app.services.soldes import impact_cash_mouvement
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "dcam", "ticker": "DCAM", "nom": "Amundi PEA Monde", "devise": "EUR"},
    ])
    for n in ("mouvements", "evenements", "notes_titres", "watchlist",
              "suggestions_ia", "virements_programmes"):
        d.enregistrer(n, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_impact_cash_achat_utilise_la_virgule(depot):
    # 2 × 33.34 = 66.68 → impact cash −66,68 € (virgule, pas point)
    svc.creer(depot, "achat", {
        "compte_id": "pea", "titre_id": "dcam", "date": "2026-07-06",
        "quantite": "2", "prix_unitaire": "33.34", "frais_courtage": "0",
        "devise": "EUR", "taux_change": "1.0",
    })
    html = _client(depot).get("/mouvements/").get_data(as_text=True)
    assert "66,68" in html          # virgule française
    assert "66.68" not in html      # plus de point décimal


def test_impact_cash_mouvement_signes():
    assert impact_cash_mouvement({"type": "alimentation_cash", "montant": "200"}) == Decimal("200")
    assert impact_cash_mouvement({"type": "retrait_cash", "montant": "95"}) == Decimal("-95")
    assert impact_cash_mouvement({"type": "frais", "montant": "6"}) == Decimal("-6")
    assert impact_cash_mouvement({
        "type": "achat", "quantite": "2", "prix_unitaire": "33.34",
        "frais_courtage": "1"}) == Decimal("-67.68")
    assert impact_cash_mouvement({
        "type": "vente", "quantite": "2", "prix_unitaire_vente": "40",
        "frais_courtage": "1"}) == Decimal("79")


def test_total_impact_cash_en_bas(depot):
    svc.creer(depot, "alimentation_cash", {
        "compte_id": "pea", "date": "2026-07-01", "montant": "200"})
    svc.creer(depot, "achat", {
        "compte_id": "pea", "titre_id": "dcam", "date": "2026-07-06",
        "quantite": "2", "prix_unitaire": "33.34", "frais_courtage": "0",
        "devise": "EUR", "taux_change": "1.0"})
    html = _client(depot).get("/mouvements/").get_data(as_text=True)
    assert "total-mouvements" in html          # ligne de total présente
    assert "2 mouvements" in html
    assert "133,32" in html                    # 200 − 66,68 (net cash)


def test_bouton_filtre_est_une_icone(depot):
    html = _client(depot).get("/mouvements/").get_data(as_text=True)
    assert 'aria-label="Filtrer"' in html       # bouton-icône accessible
    assert ">Filtrer</button>" not in html      # plus de libellé texte
