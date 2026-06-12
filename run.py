"""Point d'entrée local et exécutable .exe.

- Mode développement (depuis les sources) : comportement historique, debug
  selon la config, port 5000.
- Mode gelé (.exe PyInstaller distribué aux amis) : port libre choisi
  automatiquement, navigateur ouvert tout seul, reloader désactivé (fatal dans
  un bundle), erreur fatale journalisée et signalée à l'utilisateur Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app import create_app
from app.services import runtime


app = create_app()


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
    ``None`` : Werkzeug écrirait dans le vide et lèverait. On les redirige vers
    ``app.log`` pour que la journalisation du serveur fonctionne sans planter.
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


def _demarrer_gele() -> None:
    """Démarrage robuste pour l'exécutable distribué."""
    data_dir = Path(app.config["DATA_DIR"])
    _securiser_sorties_standard(data_dir)
    try:
        port = runtime.trouver_port_libre(5000)
        url = f"http://127.0.0.1:{port}"
        _ouvrir_navigateur(url)
        # use_reloader=False : le reloader relancerait le .exe en boucle.
        app.run(host="127.0.0.1", port=port, debug=False,
                use_reloader=False, threaded=True)
    except Exception as e:  # noqa: BLE001 — dernier rempart avant fermeture
        _signaler_erreur_fatale(e, data_dir)
        raise


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _demarrer_gele()
    else:
        app.run(host="127.0.0.1", port=5000, debug=app.config.get("DEBUG", False))
