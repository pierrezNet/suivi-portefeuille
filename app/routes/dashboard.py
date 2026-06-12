"""Dashboard : vue d'ensemble enrichie."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from app.services import dashboard_data


bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    depot = current_app.config["DEPOT"]
    data = dashboard_data.construire(depot)
    return render_template(
        "dashboard.html",
        **data,
    )


@bp.route("/publier-dashboard", methods=["POST"])
def publier():
    """Chiffre les données du dashboard et les pousse vers le repo Git
    (GitHub Pages). Requiert les env BOURSE_PASSWORD + BOURSE_DASHBOARD_REPO."""
    # Import lazy pour ne pas imposer cryptography/git au démarrage de l'app.
    from tools.publier_dashboard import publier as publier_script

    try:
        chemin = publier_script()
        taille_data = (chemin.parent / "data.enc.json").stat().st_size
        flash(
            f"Dashboard chiffré publié → {chemin.parent} "
            f"(data.enc.json : {taille_data / 1024:.1f} Ko). "
            "Git push effectué — vérifie GitHub Pages.",
            "success",
        )
    except Exception as e:
        flash(f"Échec publication : {e}", "error")
    return redirect(url_for("dashboard.index"))
