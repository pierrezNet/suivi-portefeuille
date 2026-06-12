"""Routes : CRUD notes de journal de bord, scopées sous un titre."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.services import notes_titres as svc
from app.services import titres as svc_titres


bp = Blueprint("notes_titres", __name__, url_prefix="/titres/<titre_id>/notes")


def _titre_ou_404(titre_id: str) -> dict:
    depot = current_app.config["DEPOT"]
    titre = svc_titres.trouver(depot, titre_id)
    if not titre:
        abort(404)
    return titre


@bp.route("/nouvelle", methods=["POST"])
def creer(titre_id: str):
    _titre_ou_404(titre_id)
    depot = current_app.config["DEPOT"]
    donnees = {**dict(request.form), "titre_id": titre_id}
    try:
        note = svc.creer(depot, donnees)
        flash(f"Note de journal ajoutée ({note['titre_court']}).", "success")
    except svc.ErreursValidation as e:
        # On affiche les erreurs de manière condensée, le formulaire est inline.
        details = "; ".join(f"{k} : {v}" for k, v in e.erreurs.items())
        flash(f"Saisie invalide — {details}", "error")
    return redirect(url_for("titres.detail", titre_id=titre_id))


@bp.route("/<note_id>/editer", methods=["GET", "POST"])
def editer(titre_id: str, note_id: str):
    _titre_ou_404(titre_id)
    depot = current_app.config["DEPOT"]
    note = svc.trouver(depot, note_id)
    if not note or note.get("titre_id") != titre_id:
        abort(404)

    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(note)
    donnees["titre_id"] = titre_id  # forcer la cohérence

    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, note_id, donnees)
            flash("Note mise à jour.", "success")
            return redirect(url_for("titres.detail", titre_id=titre_id))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs

    return render_template(
        "titres/note_editer.html",
        titre=_titre_ou_404(titre_id),
        note_id=note_id,
        donnees=donnees,
        erreurs=erreurs,
        types=svc.LIBELLES_TYPES,
        evenements=depot.charger("evenements"),
    )


@bp.route("/<note_id>/supprimer", methods=["POST"])
def supprimer(titre_id: str, note_id: str):
    _titre_ou_404(titre_id)
    depot = current_app.config["DEPOT"]
    note = svc.trouver(depot, note_id)
    if not note or note.get("titre_id") != titre_id:
        abort(404)
    if svc.supprimer(depot, note_id):
        flash("Note supprimée.", "success")
    else:
        flash("Note introuvable.", "error")
    return redirect(url_for("titres.detail", titre_id=titre_id))
