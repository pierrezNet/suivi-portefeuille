"""Point d'entrée local et exécutable .exe.

- Mode développement (depuis les sources) : comportement historique, debug
  selon la config, port 5000.
- Mode gelé (.exe PyInstaller distribué aux amis) : port libre choisi
  automatiquement, navigateur ouvert tout seul, reloader désactivé (fatal dans
  un bundle), et **toute** l'initialisation (création de l'app, migrations,
  sauvegarde) enveloppée dans un filet qui journalise et signale une erreur
  fatale par un popup — pour qu'une panne ne ferme jamais le .exe en silence.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app import create_app
from app.services import runtime


def _ouvrir_navigateur(url: str, delai: float = 1.0) -> None:
    """Ouvre le navigateur après un court délai (le temps que le serveur écoute)."""
    import threading
    import webbrowser

    threading.Timer(delai, lambda: webbrowser.open(url)).start()


def _signaler_erreur_fatale(e: Exception, data_dir: Path) -> None:
    """Journalise et signale une erreur fatale (popup Windows si possible)."""
    import traceback

    log = runtime.chemin_log(Path(data_dir))
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    try:  # popup best-effort pour que l'utilisateur sache que ça a échoué
        import tkinter
        from tkinter import messagebox

        racine = tkinter.Tk()
        racine.withdraw()
        messagebox.showerror(
            "Suivi Portefeuille",
            f"Le démarrage a échoué :\n\n{e}\n\nDétails : {log}",
        )
        racine.destroy()
    except Exception:  # noqa: BLE001 — tkinter peut être absent
        print(f"Erreur fatale : {e}\nDétails : {log}", file=sys.stderr)


def _securiser_sorties_standard(data_dir: Path) -> None:
    """En mode fenêtré (.exe console=False), ``sys.stdout``/``stderr`` valent
    ``None`` : Werkzeug (et tout ``print``) écrirait dans le vide et lèverait.
    On les redirige vers ``app.log``. Appelé **avant** toute initialisation.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = runtime.chemin_log(Path(data_dir))
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        flux = open(log, "a", encoding="utf-8")  # noqa: SIM115 — durée de vie = process
    except OSError:
        return
    if sys.stdout is None:
        sys.stdout = flux
    if sys.stderr is None:
        sys.stderr = flux


def _preparer_donnees(app) -> None:
    """Migrations de schéma au démarrage (sauvegarde + rotation des backups).

    Indispensable pour les amis Windows qui ne peuvent pas lancer de script de
    migration à la main. N'est jamais exécuté par les tests (qui importent
    ``create_app`` sans exécuter ce module).
    """
    from app.services import migrations
    from tools import backup

    data_dir = Path(app.config["DATA_DIR"])
    migrations.appliquer(data_dir, sauvegarder=lambda dd: backup.creer_sauvegarde(dd))
    backup.purger_anciennes(data_dir.parent / "backups", garder=30)


def _demarrer_gele() -> None:
    """Démarrage robuste pour l'exécutable distribué.

    On résout le dossier de données et on sécurise stdout/stderr + le filet
    d'erreur **avant** toute initialisation, de sorte qu'une panne (dossier non
    inscriptible, données corrompues) soit journalisée et affichée plutôt que de
    fermer le .exe en silence.
    """
    from config import Config

    data_dir = Path(Config.DATA_DIR)
    _securiser_sorties_standard(data_dir)
    try:
        app = create_app()  # verifier_ecriture peut lever ici (dossier read-only)
        _preparer_donnees(app)
        port = runtime.trouver_port_libre(5000)
        _ouvrir_navigateur(f"http://127.0.0.1:{port}")
        # use_reloader=False : le reloader relancerait le .exe en boucle.
        app.run(host="127.0.0.1", port=port, debug=False,
                use_reloader=False, threaded=True)
    except Exception as e:  # noqa: BLE001 — dernier rempart avant fermeture
        _signaler_erreur_fatale(e, data_dir)
        raise


def _demarrer_dev() -> None:
    """Démarrage en mode développement (depuis les sources)."""
    app = create_app()
    # Sous le reloader Werkzeug, le module tourne dans le superviseur ET dans le
    # worker rechargé : on n'applique migrations/backup qu'une fois, dans le
    # worker (WERKZEUG_RUN_MAIN), pour ne pas dupliquer sauvegardes et écritures.
    if not app.config.get("DEBUG") or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _preparer_donnees(app)
    app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False))


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _demarrer_gele()
    else:
        _demarrer_dev()
