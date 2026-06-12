"""Tests du service de réglages (publication mobile cross-platform)."""

import json

from app.services import chiffrement
from app.services import reglages as svc


def test_charger_defauts_si_absent(tmp_path):
    rg = svc.charger_reglages(tmp_path)
    assert rg["branche"] == "main"
    assert rg["github_user"] == ""
    assert rg["github_repo"] == ""
    assert rg["github_token"] == ""


def test_enregistrer_puis_recharger(tmp_path):
    svc.enregistrer_reglages(tmp_path, {
        "github_user": "alice", "github_repo": "dash",
        "branche": "main", "github_token": "ghp_secret",
    })
    rg = svc.charger_reglages(tmp_path)
    assert rg["github_user"] == "alice"
    assert rg["github_repo"] == "dash"
    assert rg["github_token"] == "ghp_secret"
    # Écrit bien dans DATA_DIR/reglages.json (atomique).
    contenu = json.loads((tmp_path / "reglages.json").read_text(encoding="utf-8"))
    assert contenu["github_user"] == "alice"


def test_enregistrer_conserve_token_si_absent(tmp_path):
    svc.enregistrer_reglages(tmp_path, {"github_token": "tok-initial"})
    # Mise à jour d'un autre champ sans fournir le token → token conservé.
    svc.enregistrer_reglages(tmp_path, {"github_user": "bob"})
    rg = svc.charger_reglages(tmp_path)
    assert rg["github_user"] == "bob"
    assert rg["github_token"] == "tok-initial"


def test_branche_defaut_main_si_vide(tmp_path):
    svc.enregistrer_reglages(tmp_path, {"branche": ""})
    assert svc.charger_reglages(tmp_path)["branche"] == "main"


def test_publication_api_configuree(tmp_path):
    assert not svc.publication_api_configuree(svc.charger_reglages(tmp_path))
    svc.enregistrer_reglages(tmp_path, {
        "github_user": "a", "github_repo": "d", "github_token": "t",
    })
    assert svc.publication_api_configuree(svc.charger_reglages(tmp_path))


def test_generer_phrase_passe_valide():
    phrase = svc.generer_phrase_passe()
    assert len(phrase) >= chiffrement.LONGUEUR_MIN_MOT_PASSE
    assert "-" in phrase
    # Doit passer la validation de chiffrement (≥ 15 caractères).
    chiffrement._valider_mot_passe(phrase)  # ne lève pas
    # Deux tirages diffèrent (aléa).
    assert svc.generer_phrase_passe() != svc.generer_phrase_passe()
