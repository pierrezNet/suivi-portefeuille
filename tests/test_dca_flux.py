"""Tests du flux DCA fluidifié :

- helper pur `info_dca_pour_rappel` (partagé Événements / Programmes) ;
- helper pur `suggestion_achat_dca` (quantité + prix d'après le dernier cours) ;
- pré-remplissage suggéré du formulaire d'achat depuis un rappel DCA ;
- bouton « Enregistrer l'achat » exposé sur la page Programmes.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import evenements as svc_evt
from app.services import virements_programmes as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "pea-bd", "nom": "PEA Bourse Direct", "type": "PEA"},
    ])
    d.enregistrer("titres", [
        {
            "id": "amundi-pea-monde", "ticker": "DCAM",
            "nom": "Amundi PEA Monde", "devise": "EUR",
            "cours_jour_eur": "6.098", "date_cours_jour": "2026-07-01",
        },
        {"id": "sans-cours", "ticker": "XXX", "nom": "Titre sans cours"},
    ])
    d.enregistrer("mouvements", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    return d


def _client(depot):
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    return app.test_client()


# --- Helper info_dca_pour_rappel ----------------------------------------

def _programmes_titres(depot):
    programmes = {v["id"]: v for v in depot.charger("virements_programmes")}
    titres = {t["id"]: t for t in depot.charger("titres")}
    return programmes, titres


def test_info_dca_pour_rappel_non_honore(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80", "jour_du_mois": "5",
        "titre_id": "amundi-pea-monde", "date_debut": "2026-06-01",
    })
    programmes, titres = _programmes_titres(depot)
    evt = {"id": f"e-dca-{vp['id']}-2026-06-05", "virement_programme_id": vp["id"]}
    info = svc.info_dca_pour_rappel(evt, programmes, titres)
    assert info == {
        "compte_id": "pea-bd",
        "titre_id": "amundi-pea-monde",
        "devise": "EUR",
        "montant_cible": "80",
    }


def test_info_dca_pour_rappel_honore_retourne_none(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80", "jour_du_mois": "5",
        "titre_id": "amundi-pea-monde", "date_debut": "2026-06-01",
    })
    programmes, titres = _programmes_titres(depot)
    evt = {
        "id": f"e-dca-{vp['id']}-2026-06-05",
        "virement_programme_id": vp["id"],
        "mouvement_id": "m-42",  # déjà honoré
    }
    assert svc.info_dca_pour_rappel(evt, programmes, titres) is None


def test_info_dca_pour_rappel_non_dca_retourne_none(depot):
    programmes, titres = _programmes_titres(depot)
    evt = {"id": "e-stm-q1-2026", "titre_id": "stm"}
    assert svc.info_dca_pour_rappel(evt, programmes, titres) is None


def test_info_dca_pour_rappel_programme_supprime_retourne_none(depot):
    programmes, titres = _programmes_titres(depot)
    evt = {"id": "e-dca-vp-fantome-2026-06-05", "virement_programme_id": "vp-fantome"}
    assert svc.info_dca_pour_rappel(evt, programmes, titres) is None


def test_info_dca_devise_fallback_sur_vp_puis_eur(depot):
    # titre sans devise → on retombe sur la devise du VP.
    depot.enregistrer("titres", [{"id": "t-sans-devise", "ticker": "T", "nom": "T"}])
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "50", "jour_du_mois": "5",
        "titre_id": "t-sans-devise", "devise": "USD", "date_debut": "2026-06-01",
    })
    programmes, titres = _programmes_titres(depot)
    evt = {"id": f"e-dca-{vp['id']}-2026-06-05", "virement_programme_id": vp["id"]}
    assert svc.info_dca_pour_rappel(evt, programmes, titres)["devise"] == "USD"


# --- Helper suggestion_achat_dca ----------------------------------------

def test_suggestion_achat_dca_nominal():
    titre = {"cours_jour_eur": "6.098", "date_cours_jour": "2026-07-01"}
    sugg = svc.suggestion_achat_dca("80", titre)
    assert sugg["quantite"] == Decimal("13.1191")  # 80 / 6.098 arrondi 4 déc.
    assert sugg["prix_unitaire"] == Decimal("6.0980")
    assert sugg["cours"] == Decimal("6.098")
    assert sugg["date_cours"] == "2026-07-01"


def test_suggestion_achat_dca_cours_absent_retourne_none():
    assert svc.suggestion_achat_dca("80", {"nom": "sans cours"}) is None
    assert svc.suggestion_achat_dca("80", None) is None


def test_suggestion_achat_dca_cours_zero_retourne_none():
    assert svc.suggestion_achat_dca("80", {"cours_jour_eur": "0"}) is None


def test_suggestion_achat_dca_montant_invalide_retourne_none():
    assert svc.suggestion_achat_dca("", {"cours_jour_eur": "6.098"}) is None
    assert svc.suggestion_achat_dca("abc", {"cours_jour_eur": "6.098"}) is None


# --- Route : pré-remplissage du formulaire d'achat -----------------------

def _vp_dca_avec_rappels(depot, *, titre_id="amundi-pea-monde", montant="80"):
    """Crée un DCA et génère ses rappels via rattraper(). Renvoie (vp, rappels)."""
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": montant, "jour_du_mois": "5",
        "titre_id": titre_id, "date_debut": "2026-06-01",
    })
    svc.rattraper(depot, jusqu_a=date(2026, 7, 5))
    rappels = [
        e for e in depot.charger("evenements")
        if e.get("virement_programme_id") == vp["id"]
    ]
    return vp, rappels


def test_prefill_formulaire_achat_depuis_rappel_dca(depot):
    vp, rappels = _vp_dca_avec_rappels(depot)
    evt = rappels[0]
    c = _client(depot)
    html = c.get(
        "/mouvements/nouveau/achat"
        f"?source_evenement_id={evt['id']}&titre_id=amundi-pea-monde"
        "&compte_id=pea-bd&montant_cible=80&date=2026-07-05"
    ).get_data(as_text=True)
    assert 'value="13.1191"' in html   # quantité suggérée
    assert 'value="6.0980"' in html    # prix suggéré
    assert "dernier cours importé" in html


def test_prefill_absent_si_cours_manquant(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80", "jour_du_mois": "5",
        "titre_id": "sans-cours", "date_debut": "2026-06-01",
    })
    svc.rattraper(depot, jusqu_a=date(2026, 7, 5))
    evt = depot.charger("evenements")[0]
    c = _client(depot)
    html = c.get(
        "/mouvements/nouveau/achat"
        f"?source_evenement_id={evt['id']}&titre_id=sans-cours"
        "&compte_id=pea-bd&montant_cible=80&date=2026-07-05"
    ).get_data(as_text=True)
    assert "dernier cours importé" not in html
    assert "13.1191" not in html


def test_prefill_ne_ecrase_pas_valeur_fournie(depot):
    vp, rappels = _vp_dca_avec_rappels(depot)
    evt = rappels[0]
    c = _client(depot)
    html = c.get(
        "/mouvements/nouveau/achat"
        f"?source_evenement_id={evt['id']}&titre_id=amundi-pea-monde"
        "&compte_id=pea-bd&montant_cible=80&date=2026-07-05&quantite=5"
    ).get_data(as_text=True)
    assert 'value="5"' in html          # la valeur fournie est préservée
    assert 'value="13.1191"' not in html


# --- Route Programmes : bouton « Enregistrer l'achat » -------------------

def test_page_programmes_expose_bouton_enregistrer_achat(depot):
    vp, rappels = _vp_dca_avec_rappels(depot)
    assert rappels, "le rattrapage doit générer au moins un rappel"
    c = _client(depot)
    html = c.get("/virements-programmes/").get_data(as_text=True)
    assert "source_evenement_id=e-dca-" in html
    assert "montant_cible=80" in html


def test_page_programmes_masque_rappel_honore(depot):
    vp, rappels = _vp_dca_avec_rappels(depot)
    for e in rappels:
        svc_evt.marquer_honore(depot, e["id"], "m-honore")
    c = _client(depot)
    html = c.get("/virements-programmes/").get_data(as_text=True)
    assert "source_evenement_id=e-dca-" not in html


# --- Non-régression : le flux d'honoration reste intact ------------------

def test_page_evenements_honorer_toujours_ok_apres_refacto(depot):
    # La logique info_dca a été factorisée dans le service : la page Événements
    # doit continuer d'exposer « ✓ Honorer » sur les rappels DCA non honorés.
    vp, rappels = _vp_dca_avec_rappels(depot)
    c = _client(depot)
    html = c.get("/evenements/?inclure_passe=1").get_data(as_text=True)
    assert "✓ Honorer" in html
    assert "source_evenement_id=e-dca-" in html


def test_post_achat_honore_le_rappel(depot):
    vp, rappels = _vp_dca_avec_rappels(depot)
    evt = rappels[0]
    c = _client(depot)
    c.post(
        f"/mouvements/nouveau/achat?source_evenement_id={evt['id']}",
        data={
            "compte_id": "pea-bd", "titre_id": "amundi-pea-monde",
            "date": "2026-07-05", "quantite": "13", "prix_unitaire": "6.10",
            "frais_courtage": "0", "devise": "EUR", "taux_change": "1.0",
            "source_evenement_id": evt["id"],
        },
    )
    evt_apres = svc_evt.trouver(depot, evt["id"])
    assert evt_apres.get("mouvement_id")  # rappel marqué honoré
