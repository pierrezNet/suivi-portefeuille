"""Tests des fondations runtime (port libre, écritabilité, log) et de la
résolution cross-platform du dossier de données (config)."""

import socket
import sys
from pathlib import Path

import pytest

import config
from app.services import runtime


# --- trouver_port_libre -----------------------------------------------------

def test_trouver_port_libre_renvoie_un_port_bindable():
    port = runtime.trouver_port_libre(5000)
    assert isinstance(port, int)
    # Le port renvoyé doit être réellement bindable.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))


def test_trouver_port_libre_saute_un_port_occupe():
    libre = runtime.trouver_port_libre(5000)
    occupant = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupant.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupant.bind(("127.0.0.1", libre))
    occupant.listen(1)
    try:
        suivant = runtime.trouver_port_libre(libre)
        assert suivant > libre
    finally:
        occupant.close()


def test_trouver_port_libre_epuise_leve():
    with pytest.raises(OSError):
        runtime.trouver_port_libre(5000, max_essais=0)


# --- verifier_ecriture ------------------------------------------------------

def test_verifier_ecriture_ok(tmp_path):
    runtime.verifier_ecriture(tmp_path / "data")
    # Aucune sonde ne doit subsister.
    assert not (tmp_path / "data" / ".write_test").exists()


def test_verifier_ecriture_dossier_non_inscriptible_leve(tmp_path):
    fichier = tmp_path / "pas-un-dossier"
    fichier.write_text("x", encoding="utf-8")
    # Tenter de créer un dossier sous un fichier échoue → message lisible.
    with pytest.raises(runtime.DossierNonInscriptible):
        runtime.verifier_ecriture(fichier / "sous-dossier")


def test_chemin_log(tmp_path):
    assert runtime.chemin_log(tmp_path) == tmp_path / "app.log"


# --- résolution du dossier de données (config) ------------------------------

def test_dossier_donnees_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Ami\AppData\Local")
    chemin = config._dossier_donnees_utilisateur("Suivi-Portefeuille")
    assert chemin.parts[-2:] == ("Suivi-Portefeuille", "data")
    assert "AppData" in str(chemin)


def test_dossier_donnees_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/ami/.local/share")
    chemin = config._dossier_donnees_utilisateur("Suivi-Portefeuille")
    assert chemin == Path("/home/ami/.local/share/Suivi-Portefeuille/data")


def test_resoudre_data_dir_priorite_env(monkeypatch):
    monkeypatch.setenv("BOURSE_DATA_DIR", "/tmp/donnees-perso")
    assert config._resoudre_data_dir() == Path("/tmp/donnees-perso")


def test_resoudre_data_dir_gele_sans_env(monkeypatch):
    monkeypatch.delenv("BOURSE_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "EST_GELE", True)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/ami/.local/share")
    chemin = config._resoudre_data_dir()
    assert chemin == Path("/home/ami/.local/share/Suivi-Portefeuille/data")


def test_resoudre_data_dir_dev_par_defaut(monkeypatch):
    monkeypatch.delenv("BOURSE_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "EST_GELE", False)
    assert config._resoudre_data_dir() == config.BASE_DIR / "data"
