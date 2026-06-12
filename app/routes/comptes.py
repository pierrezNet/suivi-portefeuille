"""Comptes (création) + écran de démarrage guidé (onboarding)."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.services import comptes as svc
from app.services import onboarding


bp = Blueprint("comptes", __name__)


@bp.route("/demarrage")
def demarrage():
    """Écran d'accueil guidé affiché quand l'app est vierge (ou via la nav)."""
    depot = current_app.config["DEPOT"]
    return render_template(
        "comptes/demarrage.html",
        vierge=onboarding.est_vierge(depot),
    )


@bp.route("/demarrage/exemple", methods=["POST"])
def charger_exemple():
    """Charge un jeu de données d'exemple (fictif) pour découvrir l'app."""
    depot = current_app.config["DEPOT"]
    onboarding.creer_jeu_exemple(depot)
    flash(
        "Jeu d'exemple chargé. Explore librement, puis remplace-le par tes "
        "vraies données (les numéros de compte sont fictifs).",
        "success",
    )
    return redirect(url_for("dashboard.index"))


@bp.route("/comptes/nouveau", methods=["GET", "POST"])
def nouveau():
    """Crée un compte (PEA/CTO) via un formulaire — comble l'absence de CRUD."""
    depot = current_app.config["DEPOT"]
    if request.method == "POST":
        try:
            compte = svc.creer(depot, request.form.to_dict())
            flash(f"Compte « {compte['nom']} » créé.", "success")
            return redirect(url_for("dashboard.index"))
        except svc.ErreursValidation as e:
            return render_template(
                "comptes/nouveau.html", erreurs=e.erreurs, valeurs=request.form
            )
    return render_template("comptes/nouveau.html", erreurs={}, valeurs={})
