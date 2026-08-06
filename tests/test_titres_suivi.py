"""Suivi porté par le titre (ex-watchlist fusionnée) : défauts à la création,
validation des champs de suivi, préservation lors d'une édition partielle,
bascule actif→renforcement après un achat."""

from pathlib import Path

import pytest

from app.services import titres as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    return d


# --- Défauts + validation à la création -----------------------------------

def test_creer_titre_defauts_de_suivi(depot):
    t = svc.creer(depot, {"ticker": "ifx", "nom": "Infineon"})
    assert t["statut"] == "veille"
    assert t["priorite"] == "moyenne"
    assert "ajoute_le" in t


def test_creer_titre_avec_suivi_explicite(depot):
    t = svc.creer(depot, {
        "ticker": "ifx", "nom": "Infineon",
        "statut": "renforcement", "priorite": "haute", "compte_cible": "pea",
    })
    assert t["statut"] == "renforcement"
    assert t["priorite"] == "haute"
    assert t["compte_cible"] == "pea"


def test_statut_invalide_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"ticker": "X", "nom": "X", "statut": "bidon"})
    assert "statut" in exc.value.erreurs


def test_priorite_invalide_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"ticker": "X", "nom": "X", "priorite": "urgente"})
    assert "priorite" in exc.value.erreurs


def test_echeance_format_invalide_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"ticker": "X", "nom": "X", "echeance_abandon": "06/05/2027"})
    assert "echeance_abandon" in exc.value.erreurs


# --- Préservation du suivi lors d'une édition partielle --------------------

def test_edition_partielle_preserve_le_suivi(depot):
    """Éditer les chiffres financiers ne doit pas effacer ordres/paliers/statut."""
    t = svc.creer(depot, {"ticker": "dsy", "nom": "Dassault", "statut": "renforcement"})
    svc.definir_ordre_actif(depot, t["id"], {"ordre_prix": "20", "ordre_quantite": "5"})
    svc.definir_paliers(depot, t["id"], {"paliers_prix": "18\n15"})

    svc.mettre_a_jour(depot, t["id"], {
        "ticker": "DSY", "nom": "Dassault", "cap_boursiere_m": "50000",
    })
    apres = svc.trouver(depot, t["id"])
    assert apres["statut"] == "renforcement"
    assert apres["cap_boursiere_m"] == "50000"
    assert len([o for o in apres["ordres_actifs"] if o["statut"] == "en_attente"]) == 1
    assert len(apres["paliers_rachat"]) == 2


# --- Bascule après achat : veille/achat_souhaite → conservation -----------

def test_bascule_apres_achat_veille_vers_conservation(depot):
    t = svc.creer(depot, {"ticker": "STM", "nom": "STMicro", "statut": "veille"})
    modifies = svc.basculer_apres_achat(depot, t["id"])
    assert modifies == [t["id"]]
    assert svc.trouver(depot, t["id"])["statut"] == "conservation"


def test_bascule_apres_achat_achat_souhaite_vers_conservation(depot):
    t = svc.creer(depot, {"ticker": "MU", "nom": "Micron", "statut": "achat_souhaite"})
    assert svc.basculer_apres_achat(depot, t["id"]) == [t["id"]]
    assert svc.trouver(depot, t["id"])["statut"] == "conservation"


def test_bascule_ignore_les_autres_statuts(depot):
    """Un statut déjà « avancé » (renforcement, rachat_potentiel…) n'est pas touché."""
    t = svc.creer(depot, {"ticker": "SOI", "nom": "Soitec", "statut": "rachat_potentiel"})
    assert svc.basculer_apres_achat(depot, t["id"]) == []
    assert svc.trouver(depot, t["id"])["statut"] == "rachat_potentiel"


def test_bascule_idempotente_sans_titre_id(depot):
    assert svc.basculer_apres_achat(depot, "") == []
    assert svc.basculer_apres_achat(depot, None) == []


def test_integration_achat_bascule_le_titre(depot):
    """Un achat sur un titre `veille` le fait passer en `conservation`."""
    from app.services import mouvements as svc_mvt

    depot.enregistrer("comptes", [{"id": "c1", "type": "CTO"}])
    t = svc.creer(depot, {"ticker": "IFX", "nom": "Infineon", "statut": "veille"})
    svc_mvt.creer(depot, "achat", {
        "compte_id": "c1", "titre_id": t["id"],
        "date": "2026-05-14", "quantite": "1", "prix_unitaire": "52",
    })
    assert svc.trouver(depot, t["id"])["statut"] == "conservation"


def test_integration_alimentation_ne_bascule_pas(depot):
    from app.services import mouvements as svc_mvt

    depot.enregistrer("comptes", [{"id": "c1", "type": "CTO"}])
    t = svc.creer(depot, {"ticker": "IFX", "nom": "Infineon", "statut": "veille"})
    svc_mvt.creer(depot, "alimentation_cash", {
        "compte_id": "c1", "date": "2026-05-14", "montant": "100",
    })
    assert svc.trouver(depot, t["id"])["statut"] == "veille"
