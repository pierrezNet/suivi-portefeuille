"""Réglages : configuration de la publication mobile (dépôt GitHub par ami).

Remplace, pour le .exe Windows, les variables d'environnement injectées par
systemd chez Emmanuel. Le mot de passe de chiffrement n'est PAS stocké ici.
"""

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

from app.services import reglages as svc


bp = Blueprint("reglages", __name__)


@bp.route("/reglages", methods=["GET"])
def index():
    data_dir = current_app.config["DATA_DIR"]
    reglages = svc.charger_reglages(data_dir)
    return render_template(
        "reglages/index.html",
        reglages=reglages,
        api_configuree=svc.publication_api_configuree(reglages),
        token_present=bool(reglages.get("github_token")),
        suggestion_phrase=svc.generer_phrase_passe(),
    )


@bp.route("/reglages", methods=["POST"])
def enregistrer():
    data_dir = current_app.config["DATA_DIR"]
    valeurs = {
        "github_user": request.form.get("github_user", ""),
        "github_repo": request.form.get("github_repo", ""),
        "branche": request.form.get("branche", "") or "main",
    }
    # Le token n'est jamais pré-rempli dans le formulaire (secret) : s'il est
    # laissé vide, on conserve celui déjà enregistré au lieu de l'effacer.
    token = request.form.get("github_token", "").strip()
    if token:
        valeurs["github_token"] = token

    svc.enregistrer_reglages(data_dir, valeurs)
    flash("Réglages enregistrés.", "success")
    return redirect(url_for("reglages.index"))
