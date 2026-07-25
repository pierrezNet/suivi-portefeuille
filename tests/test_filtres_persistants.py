"""Persistance + rappel visuel des filtres, appliqués aux 4 pages « liste »
(mouvements, événements, watchlist, prédictions) via le helper partagé
``app.routes._filtres.resoudre_filtres``."""

from pathlib import Path

import pytest

from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "cto", "nom": "CTO", "type": "CTO"}])
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STMicro", "devise": "EUR"},
    ])
    d.enregistrer("watchlist", [
        {"id": "w1", "ticker": "AIR", "nom": "Air Liquide",
         "statut": "actif", "priorite": "haute"},
    ])
    d.enregistrer("predictions", [
        {"id": "p1", "ticker": "STM", "sens": "hausse", "statut": "en_cours",
         "date_echeance": "2026-12-31"},
    ])
    for n in ("mouvements", "evenements", "notes_titres",
              "suggestions_ia", "virements_programmes"):
        d.enregistrer(n, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


# (page, url, param, valeur) — un filtre représentatif par page.
CAS = [
    ("evenements", "/evenements/", "titre_id", "stm"),
    ("watchlist", "/watchlist/", "statut", "actif"),
    ("predictions", "/predictions/", "sens", "hausse"),
]


@pytest.mark.parametrize("nom,url,param,val", CAS)
def test_filtre_signale_puis_reapplique_puis_reinit(depot, nom, url, param, val):
    c = _client(depot)

    # 1. Applique un filtre → signalé visuellement
    html = c.get(f"{url}?f=1&{param}={val}").get_data(as_text=True)
    assert "filtres-bar--actifs" in html, f"{nom}: accent de barre absent"
    assert "filtre-actif" in html, f"{nom}: champ non surligné"
    assert "filtre actif" in html, f"{nom}: badge absent"
    # Le badge est lui-même le bouton de suppression des filtres
    assert 'class="filtres-badge"' in html and "reinit=1" in html, \
        f"{nom}: badge non cliquable pour supprimer les filtres"

    # 2. Retour « nu » sur la page → redirige vers l'URL filtrée mémorisée
    r = c.get(url)
    assert r.status_code == 302, f"{nom}: pas de ré-application des filtres"
    assert f"{param}={val}" in r.headers["Location"]

    # 3. Réinitialiser → oublie, plus de redirection ni d'accent
    c.get(f"{url}?reinit=1")
    r = c.get(url)
    assert r.status_code == 200, f"{nom}: filtres non oubliés"
    assert "filtres-bar--actifs" not in r.get_data(as_text=True)


def test_filtres_cloisonnes_par_page(depot):
    """Un filtre posé sur une page ne fuite pas sur une autre."""
    c = _client(depot)
    c.get("/watchlist/?f=1&statut=actif")     # filtre watchlist mémorisé
    # La page prédictions ne doit pas être redirigée à cause du filtre watchlist
    r = c.get("/predictions/")
    assert r.status_code == 200
