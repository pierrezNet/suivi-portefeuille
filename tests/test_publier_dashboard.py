"""Tests publication du dashboard chiffré vers un repo Git local."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.services import chiffrement
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


def test_publication_complete_no_push(repo_git, monkeypatch):
    """Publication réussie : fichiers écrits + commit local, sans push."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    chemin = publier(repo=repo_git, mot_passe=MDP_TEST)
    assert chemin == repo_git / "index.html"
    assert chemin.exists()
    assert (repo_git / "data.enc.json").exists()
    assert (repo_git / ".nojekyll").exists()


def test_donnees_chiffrees_dechiffrables_avec_le_mdp(repo_git, monkeypatch):
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST)
    paquet = json.loads((repo_git / "data.enc.json").read_text(encoding="utf-8"))
    data = chiffrement.dechiffrer(paquet, MDP_TEST)
    # Les clés attendues du dashboard sont présentes
    cles = {"total_cash", "comptes", "stats_annee", "agenda", "genere_le_fr"}
    assert cles.issubset(set(data.keys()))


def test_html_ne_contient_aucune_donnee_en_clair(repo_git, monkeypatch):
    """Le HTML doit être agnostique : aucune donnée métier inline."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST)
    html = (repo_git / "index.html").read_text(encoding="utf-8")
    # Le HTML ne doit pas contenir le total_cash en clair, ni de nom de compte
    paquet = json.loads((repo_git / "data.enc.json").read_text(encoding="utf-8"))
    data = chiffrement.dechiffrer(paquet, MDP_TEST)
    total_cash_str = str(data["total_cash"])
    # Vérification : la valeur n'est pas embarquée dans le HTML
    assert total_cash_str not in html
    # Le HTML contient bien le bloc de chiffrement / fetch
    assert "data.enc.json" in html
    assert "deriveKey" in html or "PBKDF2" in html
    assert "AES-GCM" in html


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


def test_mdp_trop_court_leve(repo_git, monkeypatch):
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    with pytest.raises(chiffrement.MotPasseInvalide):
        publier(repo=repo_git, mot_passe="trop-court")


def test_repo_via_env(repo_git, monkeypatch):
    """L'utilisation via BOURSE_DASHBOARD_REPO doit fonctionner."""
    monkeypatch.setenv("BOURSE_DASHBOARD_REPO", str(repo_git))
    monkeypatch.setenv("BOURSE_PASSWORD", MDP_TEST)
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    chemin = publier()
    assert chemin == repo_git / "index.html"


def test_commit_cree_si_changements(repo_git, monkeypatch):
    """Une publication crée un commit avec un message daté."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST)
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo_git,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Dashboard" in log.stdout
    assert "sync" in log.stdout


def test_idempotence_pas_de_commit_inutile(repo_git, monkeypatch):
    """Vu que salt/IV sont aléatoires, chaque publication produit un fichier
    différent et donc un commit. Ce test documente le comportement."""
    monkeypatch.setenv("BOURSE_DASHBOARD_NO_PUSH", "1")
    publier(repo=repo_git, mot_passe=MDP_TEST)
    publier(repo=repo_git, mot_passe=MDP_TEST)
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo_git,
        capture_output=True,
        text=True,
        check=True,
    )
    # 2 commits attendus (chaque publication change salt/IV)
    assert len(log.stdout.strip().splitlines()) == 2
