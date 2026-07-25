"""Liste des mouvements : persistance des filtres (mémorisés en session) et
rappel visuel des filtres actifs (surbrillance des champs, accent de barre,
badge de comptage)."""

from pathlib import Path

import pytest

from app.services import mouvements as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "cto", "nom": "CTO Bourse Direct", "type": "CTO"},
        {"id": "pea", "nom": "PEA", "type": "PEA"},
    ])
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STMicro", "devise": "EUR"},
    ])
    for n in ("mouvements", "evenements", "notes_titres", "watchlist",
              "suggestions_ia", "virements_programmes"):
        d.enregistrer(n, [])
    svc.creer(d, "alimentation_cash", {
        "compte_id": "cto", "date": "2026-04-01", "montant": "100"})
    svc.creer(d, "alimentation_cash", {
        "compte_id": "pea", "date": "2026-04-02", "montant": "200"})
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def test_filtre_applique_est_signale_visuellement(depot):
    c = _client(depot)
    html = c.get("/mouvements/?f=1&compte_id=cto").get_data(as_text=True)
    assert "filtre-actif" in html            # champ surligné
    assert "filtres-bar--actifs" in html      # accent de barre
    assert "filtre actif" in html             # badge de comptage (1 filtre)


def test_retour_sur_la_page_reapplique_les_filtres(depot):
    c = _client(depot)
    c.get("/mouvements/?f=1&compte_id=cto")   # pose le filtre → mémorisé
    r = c.get("/mouvements/")                  # arrivée « nue »
    assert r.status_code == 302               # redirection vers l'URL filtrée
    assert "compte_id=cto" in r.headers["Location"]


def test_sans_filtre_aucun_rappel_ni_redirection(depot):
    c = _client(depot)
    r = c.get("/mouvements/")
    assert r.status_code == 200               # pas de filtre mémorisé → pas de redirect
    html = r.get_data(as_text=True)
    assert "filtres-bar--actifs" not in html


def test_reinitialiser_oublie_les_filtres(depot):
    c = _client(depot)
    c.get("/mouvements/?f=1&compte_id=cto")   # mémorise
    c.get("/mouvements/?reinit=1")             # oublie
    r = c.get("/mouvements/")
    assert r.status_code == 200               # plus de redirection
    assert "filtres-bar--actifs" not in r.get_data(as_text=True)
