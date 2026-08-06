"""Étape 2 : pré-remplissage des formulaires DCA et prédiction depuis la
liste-pivot des titres (query param `titre_id`)."""

from pathlib import Path

import pytest

from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "ifx", "ticker": "IFX", "nom": "Infineon", "devise": "EUR",
         "statut": "veille", "priorite": "moyenne"},
    ])
    for nom in ("mouvements", "evenements", "notes_titres", "suggestions_ia",
                "virements_programmes", "predictions", "watchlist"):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_dca_preselectionne_le_titre(depot):
    html = _client(depot).get(
        "/virements-programmes/nouveau?titre_id=ifx").get_data(as_text=True)
    assert 'value="ifx" selected' in html


def test_prediction_preselectionne_le_titre(depot):
    html = _client(depot).get(
        "/predictions/nouvelle?titre_id=ifx").get_data(as_text=True)
    assert "ifx" in html and "selected" in html


def test_prediction_post_autocomplete_ticker_depuis_titre(depot):
    rep = _client(depot).post("/predictions/nouvelle", data={
        "titre_id": "ifx", "sens": "hausse",
        "date_prediction": "2026-08-06", "date_echeance": "2026-12-31",
        "cours_reference": "30", "conviction": "3",
    })
    assert rep.status_code == 302
    preds = depot.charger("predictions")
    assert preds and preds[0]["ticker"] == "IFX"


def test_creation_titre_allegee_enregistre_le_suivi(depot):
    rep = _client(depot).post("/titres/nouveau", data={
        "ticker": "mu", "nom": "Micron", "marche": "Nasdaq", "devise": "USD",
        "secteur": "Semi", "statut": "achat_souhaite", "priorite": "haute",
        "compte_cible": "pea", "these_lt": "Mémoires HBM",
    })
    assert rep.status_code == 302
    t = {x["id"]: x for x in depot.charger("titres")}["mu"]
    assert t["statut"] == "achat_souhaite"
    assert t["priorite"] == "haute"
    assert t["compte_cible"] == "pea"
    assert t["these_lt"] == "Mémoires HBM"
