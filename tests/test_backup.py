"""Tests de la sauvegarde portable (zip cross-platform)."""

import zipfile

from app.services.stockage import Depot
from tools import backup


def test_creer_sauvegarde_contient_les_json(tmp_path):
    data_dir = tmp_path / "data"
    depot = Depot(data_dir)
    depot.enregistrer("comptes", [{"id": "x", "nom": "X", "type": "PEA"}])
    depot.enregistrer("mouvements", [])

    archive = backup.creer_sauvegarde(data_dir, horodatage="20260101-120000")
    assert archive.exists()
    assert archive.name == "data-20260101-120000.zip"
    with zipfile.ZipFile(archive) as z:
        noms = set(z.namelist())
    assert "comptes.json" in noms
    assert "mouvements.json" in noms


def test_creer_sauvegarde_destination_par_defaut(tmp_path):
    data_dir = tmp_path / "data"
    Depot(data_dir).enregistrer("comptes", [])
    archive = backup.creer_sauvegarde(data_dir, horodatage="20260101-120000")
    # Par défaut : ../backups/ à côté du dossier data.
    assert archive.parent == data_dir.parent / "backups"


def test_purger_anciennes(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    for i in range(5):
        (dest / f"data-2026010{i}-000000.zip").write_bytes(b"x")
    supprimees = backup.purger_anciennes(dest, garder=2)
    restantes = sorted(p.name for p in dest.glob("data-*.zip"))
    assert len(restantes) == 2
    assert len(supprimees) == 3
    # On garde les plus récentes (ordre décroissant du nom horodaté).
    assert restantes == ["data-20260103-000000.zip", "data-20260104-000000.zip"]
