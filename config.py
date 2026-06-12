"""Configuration de l'application Flask."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

# Vrai quand l'app tourne depuis un bundle PyInstaller (.exe gelé distribué).
EST_GELE = getattr(sys, "frozen", False)

NOM_APP = "Suivi-Portefeuille"


def _dossier_donnees_utilisateur(nom_app: str = NOM_APP) -> Path:
    """Dossier de données inscriptible propre à l'utilisateur, selon l'OS.

    Utilisé quand l'app est gelée (.exe) : on ne peut pas écrire à côté du
    binaire (Program Files en lecture seule, bundle temporaire ``_MEIPASS``
    effacé à la fermeture). Stdlib uniquement — pas de dépendance externe pour
    ne pas alourdir l'exécutable.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # linux et autres unix
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / nom_app / "data"


def _resoudre_data_dir() -> Path:
    """Résout le dossier de données selon une cascade explicite :

    1. variable d'env ``BOURSE_DATA_DIR`` (prioritaire, dev comme prod) ;
    2. si gelé (.exe) : dossier utilisateur inscriptible propre à l'OS ;
    3. sinon (dev / exécution depuis les sources) : ``data/`` à côté du code.
    """
    surcharge = os.environ.get("BOURSE_DATA_DIR")
    if surcharge:
        return Path(surcharge)
    if EST_GELE:
        return _dossier_donnees_utilisateur()
    return BASE_DIR / "data"


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-changeme-local-only")
    DATA_DIR = _resoudre_data_dir()
    EST_GELE = EST_GELE

    # DEBUG active le reloader Werkzeug, FATAL dans un .exe gelé (il relance
    # sys.executable = le .exe en boucle). Donc OFF par défaut quand gelé.
    DEBUG = os.environ.get("FLASK_DEBUG", "0" if EST_GELE else "1") == "1"

    # Chemin de sortie legacy du dashboard (`tools/publier_dashboard.py`).
    # Non utilisé par la publication cloud chiffrée. Conservé pour compat.
    # Surcharge possible via variable d'env BOURSE_PUBLIER_SORTIE.
    PUBLIER_SORTIE = os.environ.get(
        "BOURSE_PUBLIER_SORTIE", str(BASE_DIR / "dist" / "dashboard.html")
    )
