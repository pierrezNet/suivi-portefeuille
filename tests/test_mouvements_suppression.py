"""Suppression d'un mouvement : bouton exposé sur la fiche titre + redirection
`next` de retour vers la fiche (avec garde-fou open-redirect)."""

from pathlib import Path

import pytest

from app.services import mouvements as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "pea-bd", "nom": "PEA Bourse Direct", "type": "PEA"},
    ])
    d.enregistrer("titres", [
        {"id": "t1", "ticker": "T1", "nom": "Titre 1", "devise": "EUR"},
    ])
    for nom in (
        "mouvements", "evenements", "notes_titres", "watchlist",
        "suggestions_ia", "virements_programmes",
    ):
        d.enregistrer(nom, [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


def _creer_achat(depot):
    return svc.creer(depot, "achat", {
        "compte_id": "pea-bd", "titre_id": "t1", "date": "2026-06-05",
        "quantite": "3", "prix_unitaire": "35.52", "frais_courtage": "0",
        "devise": "EUR", "taux_change": "1.0",
    })


def test_fiche_titre_expose_bouton_supprimer(depot):
    m = _creer_achat(depot)
    c = _client(depot)
    html = c.get("/titres/t1").get_data(as_text=True)
    assert f"/mouvements/{m['id']}/supprimer" in html
    assert 'name="next"' in html  # retour sur la fiche


def test_supprimer_avec_next_revient_sur_la_fiche(depot):
    m = _creer_achat(depot)
    c = _client(depot)
    rep = c.post(f"/mouvements/{m['id']}/supprimer", data={"next": "/titres/t1"})
    assert rep.status_code == 302
    assert rep.headers["Location"].endswith("/titres/t1")
    assert svc.trouver(depot, m["id"]) is None


def test_supprimer_sans_next_redirige_vers_le_journal(depot):
    m = _creer_achat(depot)
    c = _client(depot)
    rep = c.post(f"/mouvements/{m['id']}/supprimer", data={})
    assert rep.status_code == 302
    assert rep.headers["Location"].rstrip("/").endswith("/mouvements")


def test_supprimer_next_externe_est_ignore(depot):
    """Garde-fou open-redirect : une URL externe est refusée → retour journal."""
    m = _creer_achat(depot)
    c = _client(depot)
    rep = c.post(
        f"/mouvements/{m['id']}/supprimer", data={"next": "//evil.example/x"}
    )
    assert rep.status_code == 302
    loc = rep.headers["Location"]
    assert "evil.example" not in loc
    assert loc.rstrip("/").endswith("/mouvements")
