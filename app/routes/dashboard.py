"""Dashboard : vue d'ensemble enrichie."""

from __future__ import annotations

import os

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.services import dashboard_data


bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    depot = current_app.config["DEPOT"]
    # Premier lancement (aucun compte) : on guide l'utilisateur plutôt que
    # d'afficher un dashboard vide. Désactivé en mode TESTING pour ne pas
    # perturber les tests qui ne seedent pas de compte.
    from app.services import onboarding

    if onboarding.est_vierge(depot) and not current_app.config.get("TESTING"):
        return redirect(url_for("comptes.demarrage"))
    data = dashboard_data.construire(depot)
    return render_template(
        "dashboard.html",
        **data,
    )


@bp.route("/publier-dashboard", methods=["POST"])
def publier():
    """Chiffre les données du dashboard et les publie vers GitHub Pages.

    Deux transports selon la configuration :
    - **API GitHub** (sans git) si les Réglages contiennent user+repo+token
      (cas du .exe Windows des amis) ;
    - **git local** sinon (cas d'Emmanuel sous Linux, via env BOURSE_*).

    Le mot de passe de chiffrement vient du formulaire (champ `mot_passe`) ou,
    à défaut, de la variable d'environnement BOURSE_PASSWORD.
    """
    # Import lazy pour ne pas imposer cryptography/git au démarrage de l'app.
    from tools.publier_dashboard import publier as publier_git, publier_via_api
    from app.services import reglages as svc_reglages

    data_dir = current_app.config["DATA_DIR"]
    reglages = svc_reglages.charger_reglages(data_dir)
    # .strip() : un espace parasite (copier-coller, autofill) ne doit pas
    # produire une clé différente de celle saisie sur mobile (qui trim aussi).
    mot_passe = (request.form.get("mot_passe") or os.environ.get("BOURSE_PASSWORD") or "").strip()

    try:
        if svc_reglages.publication_api_configuree(reglages):
            recap = publier_via_api(
                data_dir=data_dir,
                mot_passe=mot_passe,
                owner=reglages["github_user"],
                repo=reglages["github_repo"],
                token=reglages["github_token"],
                branche=reglages.get("branche") or "main",
            )
            flash(
                f"Dashboard chiffré publié → {recap['url_pages']} "
                f"(data.enc.json : {recap['taille_data'] / 1024:.1f} Ko). "
                "Vérifie l'activation de GitHub Pages sur ton dépôt.",
                "success",
            )
        else:
            # data_dir runtime : en .exe gelé, dossier utilisateur, pas le bundle.
            chemin = publier_git(data_dir=data_dir, mot_passe=mot_passe)
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
