#!/usr/bin/env python
"""Sauvegarde portable (zip) du dossier de données — cross-platform.

Remplace ``tools/backup.sh`` (bash, Linux-only) pour les amis Windows. Stdlib
uniquement. Utilisable en ligne de commande ET importable (appelé avant une
migration de schéma).

Usage :
  python tools/backup.py                 # sauvegarde DATA_DIR → ../backups/
  python tools/backup.py --dest D --garder 30
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import datetime
from pathlib import Path


# Fichiers JAMAIS inclus dans une sauvegarde : reglages.json contient le token
# GitHub en clair. On ne veut pas le dupliquer dans des archives que
# l'utilisateur peut copier sur une clé / un cloud (fuite de secret).
FICHIERS_EXCLUS = {"reglages.json"}


def creer_sauvegarde(data_dir, dest_dir=None, *, horodatage: str | None = None) -> Path:
    """Zippe les fichiers JSON de données de ``data_dir`` dans une archive datée.

    Exclut les fichiers de secrets (``FICHIERS_EXCLUS``). Renvoie le chemin de
    l'archive créée.
    """
    data_dir = Path(data_dir)
    dest_dir = Path(dest_dir) if dest_dir else data_dir.parent / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    horodatage = horodatage or datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = dest_dir / f"data-{horodatage}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for fichier in sorted(data_dir.rglob("*.json")):
            if fichier.is_file() and fichier.name not in FICHIERS_EXCLUS:
                z.write(fichier, fichier.relative_to(data_dir))
    return archive


def purger_anciennes(dest_dir, garder: int = 30) -> list[Path]:
    """Conserve les ``garder`` archives les plus récentes, supprime le reste."""
    dest_dir = Path(dest_dir)
    archives = sorted(dest_dir.glob("data-*.zip"), reverse=True)
    a_supprimer = archives[garder:]
    for vieille in a_supprimer:
        vieille.unlink()
    return a_supprimer


def main() -> int:
    parser = argparse.ArgumentParser(description="Sauvegarde zip du dossier de données.")
    parser.add_argument("--data-dir", default=None, help="Dossier de données (défaut : config de l'app)")
    parser.add_argument("--dest", default=None, help="Dossier de destination des archives")
    parser.add_argument("--garder", type=int, default=30, help="Nombre d'archives à conserver")
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import Config

        data_dir = Config.DATA_DIR

    archive = creer_sauvegarde(data_dir, args.dest)
    dest = Path(args.dest) if args.dest else Path(data_dir).parent / "backups"
    purger_anciennes(dest, args.garder)
    print(f"✓ Sauvegarde : {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
