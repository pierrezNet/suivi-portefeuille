"""Tests CRUD notes de journal de bord par titre."""

from pathlib import Path

import pytest

from app.services import notes_titres as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STMicro"},
        {"id": "net", "ticker": "NET", "nom": "Cloudflare"},
    ])
    d.enregistrer("evenements", [
        {"id": "e-1", "type": "publication_resultats", "titre_id": "stm",
         "date": "2026-04-23", "libelle": "T1 STM"},
    ])
    d.enregistrer("notes_titres", [])
    return d


def _note_valide(**override):
    base = {
        "titre_id": "stm",
        "date": "2026-05-08",
        "type": "observation",
        "titre_court": "Note test",
        "contenu": "Contenu de la note",
    }
    base.update(override)
    return base


def test_creer_note_genere_id_et_date_creation(depot):
    n = svc.creer(depot, _note_valide())
    assert n["id"].startswith("n-")
    assert n["titre_id"] == "stm"
    assert n["type"] == "observation"
    assert n["titre_court"] == "Note test"
    assert n["contenu"] == "Contenu de la note"
    assert "date_creation" in n


def test_validation_titre_inconnu(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(titre_id="inexistant"))
    assert "titre_id" in exc.value.erreurs
    assert "inconnu" in exc.value.erreurs["titre_id"]


def test_validation_titre_obligatoire(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(titre_id=""))
    assert "titre_id" in exc.value.erreurs


def test_validation_type_inconnu(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(type="bidon"))
    assert "type" in exc.value.erreurs


def test_validation_contenu_obligatoire(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(contenu="   "))
    assert "contenu" in exc.value.erreurs


def test_titre_court_auto_rempli_depuis_contenu(depot):
    """Si titre_court vide et contenu présent, on prend les 60 premiers caractères."""
    n = svc.creer(depot, _note_valide(
        titre_court="",
        contenu="Annonce de licenciement 20% effectifs, principalement tech.",
    ))
    # 60 premiers chars
    assert n["titre_court"] == "Annonce de licenciement 20% effectifs, principalement tech."


def test_titre_court_auto_avec_ellipsis_si_long(depot):
    long_contenu = "a" * 200
    n = svc.creer(depot, _note_valide(titre_court="", contenu=long_contenu))
    assert n["titre_court"].endswith("…")
    assert len(n["titre_court"]) == 61  # 60 chars + …


def test_validation_titre_court_et_contenu_vides(depot):
    """Si les deux sont vides, on doit rejeter."""
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(titre_court="", contenu=""))
    # Au minimum le contenu est rejeté
    assert "contenu" in exc.value.erreurs


def test_validation_date_iso(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(date="08/05/2026"))
    assert "date" in exc.value.erreurs


def test_lien_evenement_existant(depot):
    n = svc.creer(depot, _note_valide(evenement_id="e-1"))
    assert n["evenement_id"] == "e-1"


def test_lien_evenement_inconnu_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, _note_valide(evenement_id="e-fake"))
    assert "evenement_id" in exc.value.erreurs


def test_lister_filtre_par_titre(depot):
    svc.creer(depot, _note_valide(titre_id="stm", titre_court="Sur STM"))
    svc.creer(depot, _note_valide(titre_id="net", titre_court="Sur NET"))
    res_stm = svc.lister(depot, titre_id="stm")
    res_net = svc.lister(depot, titre_id="net")
    assert len(res_stm) == 1 and res_stm[0]["titre_court"] == "Sur STM"
    assert len(res_net) == 1 and res_net[0]["titre_court"] == "Sur NET"


def test_lister_tri_decroissant_par_date(depot):
    svc.creer(depot, _note_valide(date="2026-04-01", titre_court="vieille"))
    svc.creer(depot, _note_valide(date="2026-05-15", titre_court="recente"))
    svc.creer(depot, _note_valide(date="2026-04-20", titre_court="moyenne"))
    res = svc.lister(depot)
    assert [n["titre_court"] for n in res] == ["recente", "moyenne", "vieille"]


def test_mise_a_jour_preserve_id_et_date_creation(depot):
    n = svc.creer(depot, _note_valide())
    note_id = n["id"]
    creation = n["date_creation"]
    apres = svc.mettre_a_jour(depot, note_id, _note_valide(titre_court="Modifié"))
    assert apres["id"] == note_id
    assert apres["date_creation"] == creation
    assert apres["titre_court"] == "Modifié"


def test_supprimer(depot):
    n = svc.creer(depot, _note_valide())
    assert svc.supprimer(depot, n["id"]) is True
    assert svc.trouver(depot, n["id"]) is None
    assert svc.supprimer(depot, "n-inconnu") is False
