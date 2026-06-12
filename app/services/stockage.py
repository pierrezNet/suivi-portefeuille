"""Lecture et écriture atomique des fichiers JSON de données."""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any


class DecimalEncoder(json.JSONEncoder):
    """Sérialise les `Decimal` en chaîne pour préserver la précision."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def lire_json(chemin: Path) -> dict:
    """Lit un fichier JSON. Renvoie un dict vide si absent."""
    chemin = Path(chemin)
    if not chemin.exists():
        return {}
    with chemin.open("r", encoding="utf-8") as f:
        return json.load(f)


def ecrire_json_atomique(chemin: Path, donnees: dict) -> None:
    """Écrit un JSON via fichier temporaire + rename pour éviter la corruption."""
    chemin = Path(chemin)
    dossier = chemin.parent
    dossier.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=dossier,
        delete=False,
        suffix=".tmp",
        encoding="utf-8",
    ) as f:
        json.dump(
            donnees,
            f,
            indent=2,
            ensure_ascii=False,
            cls=DecimalEncoder,
        )
        f.flush()
        os.fsync(f.fileno())
        chemin_temp = f.name
    os.replace(chemin_temp, chemin)


class Depot:
    """Façade de lecture/écriture par fichier de données."""

    FICHIERS = {
        "comptes": "comptes.json",
        "titres": "titres.json",
        "mouvements": "mouvements.json",
        "watchlist": "watchlist.json",
        "evenements": "evenements.json",
        "notes_titres": "notes_titres.json",
        "virements_programmes": "virements_programmes.json",
        "predictions": "predictions.json",
        "snapshots": "snapshots.json",
    }

    def __init__(self, dossier_data: Path) -> None:
        self.dossier = Path(dossier_data)

    def _chemin(self, nom: str) -> Path:
        if nom not in self.FICHIERS:
            raise KeyError(f"Fichier inconnu : {nom}")
        return self.dossier / self.FICHIERS[nom]

    def charger(self, nom: str) -> list[dict]:
        """Renvoie la liste contenue dans `data/<nom>.json`."""
        donnees = lire_json(self._chemin(nom))
        return donnees.get(nom, [])

    def enregistrer(self, nom: str, items: list[dict]) -> None:
        ecrire_json_atomique(self._chemin(nom), {nom: items})
