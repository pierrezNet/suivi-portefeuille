"""Tests publication du dashboard chiffré vers un repo Git local.

Les données sont fournies via un `data_dir` isolé (fixture `data_exemple`) :
les tests ne dépendent donc PAS du `data/` réel du projet — indispensable pour
qu'ils tournent aussi en CI (windows-latest) où `data/` est absent (gitignore).
"""

import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import chiffrement
from app.services.stockage import Depot
from tools.publier_dashboard import ConfigManquante, publier


MDP_TEST = "phrase-de-passe-test-2026"


@pytest.fixture
def repo_git(tmp_path: Path) -> Path:
    """Initialise un repo Git local vide dans tmp_path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


@pytest.fixture
def data_exemple(tmp_path: Path) -> Path:
    """Dossier de données minimal et isolé (indépendant du `data/` réel)."""
    dossier = tmp_path / "data"
    depot = Depot(dossier)
    depot.enregistrer("comptes", [
        {
            "id": "pea", "nom": "PEA Test", "type": "PEA", "broker": "Test",
            "numero": "PEA-EXEMPLE-0001", "date_ouverture": "2026-01-01",
            "devise_principale": "EUR",
        },
    ])
    depot.enregistrer("mouvements", [
        {
            "id": "m1", "type": "alimentation_cash", "compte_id": "pea",
            "date": "2026-01-05", "montant": "1000.00", "devise": "EUR",
            "libelle": "Dépôt initial",
        },
    ])
    return dossier


def test_publication_complete_no_push(repo_git, data_exemple, monkeypatch):
    """Publication réussie : fichiers écrits + commit local, sans push."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    chemin = publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    assert chemin == repo_git / "index.html"
    assert chemin.exists()
    assert (repo_git / "data.enc.json").exists()
    assert (repo_git / ".nojekyll").exists()


def test_donnees_chiffrees_dechiffrables_avec_le_mdp(repo_git, data_exemple, monkeypatch):
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    paquet = json.loads((repo_git / "data.enc.json").read_text(encoding="utf-8"))
    data = chiffrement.dechiffrer(paquet, MDP_TEST)
    cles = {"total_cash", "comptes", "stats_annee", "agenda", "genere_le_fr",
            "ordres_actifs", "predictions_en_cours"}
    assert cles.issubset(set(data.keys()))


def test_html_ne_contient_aucune_donnee_en_clair(repo_git, data_exemple, monkeypatch):
    """Le HTML doit être agnostique : aucune donnée métier inline."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    html = (repo_git / "index.html").read_text(encoding="utf-8")
    paquet = json.loads((repo_git / "data.enc.json").read_text(encoding="utf-8"))
    data = chiffrement.dechiffrer(paquet, MDP_TEST)
    total_cash_str = str(data["total_cash"])
    assert total_cash_str not in html
    assert "data.enc.json" in html
    assert "deriveKey" in html or "PBKDF2" in html
    assert "AES-GCM" in html


def test_publier_data_dir_personnalise(repo_git, data_exemple, monkeypatch):
    """Le `data_dir` fourni est bien lu, et les assets PWA sont publiés
    (résolus via `_chemin_ressource`, compatible bundle gelé)."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    paquet = json.loads((repo_git / "data.enc.json").read_text(encoding="utf-8"))
    data = chiffrement.dechiffrer(paquet, MDP_TEST)
    # Les données proviennent bien du data_dir fourni, pas d'un dossier vide.
    assert len(data["comptes"]) == 1
    assert Decimal(str(data["total_cash"])) == Decimal("1000.00")
    # Assets PWA présents pour que le mobile soit une vraie PWA installable.
    for asset in ("manifest.json", "sw.js", "icon.svg", "icon-192.png",
                  "icon-512.png", "apple-touch-icon-180.png", ".nojekyll"):
        assert (repo_git / asset).exists(), f"asset manquant : {asset}"


def test_repo_inexistant_leve(tmp_path, monkeypatch):
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    with pytest.raises(ConfigManquante, match="introuvable"):
        publier(repo=tmp_path / "n-existe-pas", mot_passe=MDP_TEST)


def test_repo_sans_git_leve(tmp_path, monkeypatch):
    """Un dossier qui n'est pas un repo Git doit être rejeté."""
    pas_un_repo = tmp_path / "dossier-simple"
    pas_un_repo.mkdir()
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    with pytest.raises(ConfigManquante, match="pas un repo Git"):
        publier(repo=pas_un_repo, mot_passe=MDP_TEST)


def test_mdp_absent_leve(repo_git, monkeypatch):
    monkeypatch.delenv("BOURSE_PASSWORD", raising=False)
    with pytest.raises(ConfigManquante, match="BOURSE_PASSWORD"):
        publier(repo=repo_git, mot_passe=None)


def test_mdp_trop_court_leve(repo_git, data_exemple, monkeypatch):
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    with pytest.raises(chiffrement.MotPasseInvalide):
        publier(repo=repo_git, mot_passe="trop-court", data_dir=data_exemple)


def test_repo_via_env(repo_git, data_exemple, monkeypatch):
    """L'utilisation via BOURSE_DASHBOARD_REPO doit fonctionner."""
    monkeypatch.setenv("BOURSE_DASHBOARD_REPO", str(repo_git))
    monkeypatch.setenv("BOURSE_PASSWORD", MDP_TEST)
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    chemin = publier(data_dir=data_exemple)
    assert chemin == repo_git / "index.html"


def test_commit_cree_si_changements(repo_git, data_exemple, monkeypatch):
    """Une publication crée un commit avec un message daté."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo_git, capture_output=True, text=True, check=True,
    )
    assert "Dashboard" in log.stdout
    assert "sync" in log.stdout


def test_idempotence_pas_de_commit_inutile(repo_git, data_exemple, monkeypatch):
    """Vu que salt/IV sont aléatoires, chaque publication produit un fichier
    différent et donc un commit. Ce test documente le comportement."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    publier(repo=repo_git, mot_passe=MDP_TEST, data_dir=data_exemple)
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo_git, capture_output=True, text=True, check=True,
    )
    assert len(log.stdout.strip().splitlines()) == 2
