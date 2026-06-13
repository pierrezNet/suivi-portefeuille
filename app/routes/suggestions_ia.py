"""Routes : validation des suggestions IA (accepter / rejeter), scopées sous un titre.

L'IA (via le serveur MCP) ne fait que *proposer* ; c'est ici, sur action
explicite de l'utilisateur, que la proposition devient une note de journal ou
une révision de thèse (versionnée).
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    request,
    url_for,
)

from app.services import suggestions_ia as svc


bp = Blueprint("suggestions_ia", __name__, url_prefix="/titres/<titre_id>/suggestions")


def _suggestion_ou_404(titre_id: str, suggestion_id: str) -> dict:
    depot = current_app.config["DEPOT"]
    s = svc.trouver(depot, suggestion_id)
    if not s or s.get("titre_id") != titre_id:
        abort(404)
    return s


@bp.route("/<suggestion_id>/accepter", methods=["POST"])
def accepter(titre_id: str, suggestion_id: str):
    _suggestion_ou_404(titre_id, suggestion_id)
    depot = current_app.config["DEPOT"]
    try:
        res = svc.accepter(depot, suggestion_id, contenu=request.form.get("contenu"))
        if res["cible"] == "these":
            flash(
                "Suggestion appliquée à la thèse — l'ancienne version est archivée "
                "dans l'historique.",
                "success",
            )
        else:
            flash("Suggestion ajoutée au journal de bord.", "success")
    except Exception as e:  # noqa: BLE001 — erreur de validation/écriture lisible
        flash(f"Impossible d'appliquer la suggestion : {e}", "error")
    return redirect(url_for("titres.detail", titre_id=titre_id))


@bp.route("/<suggestion_id>/rejeter", methods=["POST"])
def rejeter(titre_id: str, suggestion_id: str):
    _suggestion_ou_404(titre_id, suggestion_id)
    depot = current_app.config["DEPOT"]
    svc.supprimer(depot, suggestion_id)
    flash("Suggestion rejetée.", "info")
    return redirect(url_for("titres.detail", titre_id=titre_id))
