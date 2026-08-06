"""Liste-pivot fusionnée : tableau + panneau d'actions câblé + filtres."""

from pathlib import Path

import pytest

from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "ifx", "ticker": "IFX", "nom": "Infineon", "devise": "EUR",
         "statut": "renforcement", "priorite": "haute", "compte_cible": "pea",
         "ordres_actifs": [{"id": "o1", "prix_limite": "35", "quantite": 2,
                            "sens": "achat", "statut": "en_attente"}]},
        {"id": "stm", "ticker": "STM", "nom": "STMicro", "devise": "EUR",
         "statut": "veille", "priorite": "basse"},
    ])
    for nom in ("mouvements", "notes_titres", "evenements", "suggestions_ia",
                "virements_programmes", "predictions", "watchlist"):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_liste_pivot_tableau_et_panneaux(depot):
    html = _client(depot).get("/titres/").get_data(as_text=True)
    assert "table-pivot" in html
    assert html.count('class="titre-panneau"') == 2  # un panneau par titre


def test_panneau_cable_les_7_actions(depot):
    html = _client(depot).get("/titres/").get_data(as_text=True)
    # DCA + prédiction + note pré-remplis par titre_id
    assert "titre_id=ifx" in html
    assert "/predictions/nouvelle?titre_id=ifx" in html
    assert "/virements-programmes/nouveau?titre_id=ifx" in html
    # ordre + paliers (formulaires du panneau)
    assert "/titres/ifx/ordre" in html
    assert "/titres/ifx/paliers" in html
    # actualiser Yahoo
    assert "/titres/ifx/actualiser-yahoo" in html
    # exécuter l'ordre actif d'IFX
    assert "source_ordre_titre_id=ifx" in html
    assert "source_ordre_id=o1" in html


def test_filtre_priorite_reduit_la_liste(depot):
    html = _client(depot).get("/titres/?f=1&priorite=haute").get_data(as_text=True)
    assert "IFX" in html
    assert "STMicro" not in html
    assert "filtres-bar--actifs" in html
