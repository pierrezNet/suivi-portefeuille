"""Routes : journal de prédictions (paris directionnels sans capital)."""

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

from app.services import predictions as svc


bp = Blueprint("predictions", __name__, url_prefix="/predictions")


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    statut = request.args.get("statut") or None
    sens = request.args.get("sens") or None
    if statut not in (None, *svc.STATUTS):
        statut = None
    if sens not in (None, *svc.SENS):
        sens = None

    predictions = svc.lister(depot, statut=statut, sens=sens)
    stats = svc.taux_reussite(depot)
    a_evaluer = svc.echeances_depassees(depot)

    return render_template(
        "predictions/liste.html",
        predictions=predictions,
        stats=stats,
        a_evaluer=a_evaluer,
        filtre_statut=statut,
        filtre_sens=sens,
        libelles_sens=svc.LIBELLES_SENS,
        libelles_statuts=svc.LIBELLES_STATUTS,
        libelles_resultats=svc.LIBELLES_RESULTATS,
    )


@bp.route("/nouvelle", methods=["GET", "POST"])
def nouvelle():
    depot = current_app.config["DEPOT"]
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}

    if request.method == "POST":
        try:
            p = svc.creer_prediction(depot, donnees)
            flash(
                f"Prédiction enregistrée : {p['sens']} sur {p['ticker']} "
                f"(échéance {p['date_echeance']}).",
                "success",
            )
            return redirect(url_for("predictions.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs

    titres = sorted(depot.charger("titres"), key=lambda t: t.get("ticker", ""))
    return render_template(
        "predictions/nouvelle.html",
        donnees=donnees,
        erreurs=erreurs,
        titres=titres,
        sens_choix=svc.LIBELLES_SENS,
        action_url=url_for("predictions.nouvelle"),
        bouton_label="Enregistrer la prédiction",
        annuler_url=url_for("predictions.liste"),
    )


@bp.route("/<prediction_id>/editer", methods=["GET", "POST"])
def editer(prediction_id: str):
    depot = current_app.config["DEPOT"]
    pred = svc.trouver(depot, prediction_id)
    if not pred:
        abort(404)
    if pred.get("statut") == "evaluee":
        flash(
            "Cette prédiction est déjà évaluée — elle ne peut plus être modifiée. "
            "Supprime-la et recrée-la si nécessaire.",
            "error",
        )
        return redirect(url_for("predictions.liste"))

    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(pred)

    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, prediction_id, donnees)
            flash("Prédiction mise à jour.", "success")
            return redirect(url_for("predictions.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs

    titres = sorted(depot.charger("titres"), key=lambda t: t.get("ticker", ""))
    return render_template(
        "predictions/editer.html",
        donnees=donnees,
        erreurs=erreurs,
        titres=titres,
        sens_choix=svc.LIBELLES_SENS,
        action_url=url_for("predictions.editer", prediction_id=prediction_id),
        bouton_label="Enregistrer les modifications",
        annuler_url=url_for("predictions.liste"),
    )


@bp.route("/<prediction_id>/evaluer", methods=["GET", "POST"])
def evaluer(prediction_id: str):
    depot = current_app.config["DEPOT"]
    pred = svc.trouver(depot, prediction_id)
    if not pred:
        abort(404)
    if pred.get("statut") == "evaluee":
        flash("Cette prédiction est déjà évaluée.", "error")
        return redirect(url_for("predictions.liste"))

    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}

    if request.method == "POST":
        try:
            svc.evaluer_prediction(
                depot,
                prediction_id,
                donnees.get("cours_echeance"),
                notes_evaluation=donnees.get("notes_evaluation"),
            )
            flash("Prédiction évaluée.", "success")
            return redirect(url_for("predictions.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs

    return render_template(
        "predictions/evaluer.html",
        prediction=pred,
        donnees=donnees,
        erreurs=erreurs,
    )


@bp.route("/<prediction_id>/supprimer", methods=["POST"])
def supprimer(prediction_id: str):
    depot = current_app.config["DEPOT"]
    if svc.supprimer(depot, prediction_id):
        flash("Prédiction supprimée.", "success")
    else:
        flash("Prédiction introuvable.", "error")
    return redirect(url_for("predictions.liste"))
