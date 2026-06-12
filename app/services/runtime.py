"""Helpers d'exécution (port libre, écritabilité, log) — service pur testable.

Séparé des routes et de ``run.py`` pour être testable sans démarrer Flask ni
geler un .exe. Indispensable pour la distribution Windows : un .exe lancé en
double-clic doit choisir un port libre, vérifier qu'il peut écrire ses données,
et savoir où journaliser une erreur fatale.
"""

from __future__ import annotations

import socket
from pathlib import Path


class DossierNonInscriptible(RuntimeError):
    """Le dossier de données n'est pas accessible en écriture."""


def trouver_port_libre(
    prefere: int = 5000, host: str = "127.0.0.1", max_essais: int = 20
) -> int:
    """Renvoie un port TCP libre, en partant de ``prefere`` puis en incrémentant.

    Si 5000 est déjà occupé (autre app, instance déjà lancée), on ne veut pas
    que le .exe échoue silencieusement : on prend le port suivant disponible.
    """
    for delta in range(max_essais):
        port = prefere + delta
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(
        f"Aucun port libre entre {prefere} et {prefere + max_essais - 1}."
    )


def verifier_ecriture(dossier: Path) -> None:
    """Vérifie qu'on peut écrire dans ``dossier`` (sinon lève un message lisible).

    Sur Windows, un .exe lancé depuis Program Files ou bloqué par l'antivirus
    peut avoir un dossier de données non inscriptible : on le détecte au
    démarrage plutôt que de perdre silencieusement les saisies de l'utilisateur.
    """
    dossier = Path(dossier)
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        sonde = dossier / ".write_test"
        sonde.write_text("ok", encoding="utf-8")
        sonde.unlink()
    except OSError as e:
        raise DossierNonInscriptible(
            f"Le dossier de données « {dossier} » n'est pas accessible en "
            f"écriture ({e}). Vérifie les permissions ou choisis un autre "
            f"emplacement via la variable d'environnement BOURSE_DATA_DIR."
        ) from e


def chemin_log(data_dir: Path) -> Path:
    """Chemin du fichier de log applicatif, à côté des données utilisateur."""
    return Path(data_dir) / "app.log"
