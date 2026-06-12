"""Routes : CRUD événements."""

from __future__ import annotations

from datetime import date as _date

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

from app.services import evenements as svc


bp = Blueprint("evenements", __name__, url_prefix="/evenements")


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    inclure_passe = request.args.get("inclure_passe") == "1"
    date_debut_saisi = request.args.get("date_debut") or None
    today_iso = _date.today().isoformat()

    # Par défaut, n'afficher que les événements >= aujourd'hui.
    # L'utilisateur peut afficher le passé via `?inclure_passe=1` ou en
    # saisissant lui-même une `date_debut` antérieure.
    if date_debut_saisi:
        date_debut_effective = date_debut_saisi
    elif inclure_passe:
        date_debut_effective = None
    else:
        date_debut_effective = today_iso

    filtres = {
        "titre_id": request.args.get("titre_id") or None,
        "type_": request.args.get("type") or None,
        "date_debut": date_debut_saisi,  # ce qui a été tapé (pour repopuler)
        "date_fin": request.args.get("date_fin") or None,
    }
    items = svc.lister(
        depot,
        titre_id=filtres["titre_id"],
        type_=filtres["type_"],
        date_debut=date_debut_effective,
        date_fin=filtres["date_fin"],
    )
    titres = depot.charger("titres")
    titres_par_id = {t["id"]: t for t in titres}

    # Enrichir les rappels DCA non honorés avec les infos du programme lié
    # (compte cible, devise, montant cible) pour pré-remplir le bouton "Honorer".
    programmes_par_id = {
        vp["id"]: vp for vp in depot.charger("virements_programmes")
    }
    info_dca_par_id: dict[str, dict] = {}
    for e in items:
        if not e.get("id", "").startswith("e-dca-"):
            continue
        if e.get("mouvement_id"):
            continue  # déjà honoré
        vp_id = e.get("virement_programme_id")
        if not vp_id:
            continue
        vp = programmes_par_id.get(vp_id)
        if not vp:
            continue
        titre = titres_par_id.get(vp.get("titre_id")) or {}
        info_dca_par_id[e["id"]] = {
            "compte_id": vp.get("compte_id"),
            "titre_id": vp.get("titre_id"),
            "devise": titre.get("devise") or vp.get("devise") or "EUR",
            "montant_cible": vp.get("montant"),
        }

    return render_template(
        "evenements/liste.html",
        evenements=items,
        titres=titres,
        titres_par_id=titres_par_id,
        filtres=filtres,
        inclure_passe=inclure_passe,
        passe_masque=not inclure_passe and not date_debut_saisi,
        types=svc.LIBELLES_TYPES,
        info_dca_par_id=info_dca_par_id,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
def creer():
    depot = current_app.config["DEPOT"]
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}
    if request.method == "POST":
        try:
            e = svc.creer(depot, donnees)
            flash(f"Événement « {e['libelle']} » créé.", "success")
            return redirect(url_for("evenements.liste"))
        except svc.ErreursValidation as exc:
            erreurs = exc.erreurs
    return render_template(
        "evenements/formulaire.html",
        mode="creation",
        donnees=donnees,
        erreurs=erreurs,
        types=svc.LIBELLES_TYPES,
        titres=depot.charger("titres"),
    )


@bp.route("/<evenement_id>/editer", methods=["GET", "POST"])
def editer(evenement_id: str):
    depot = current_app.config["DEPOT"]
    e = svc.trouver(depot, evenement_id)
    if not e:
        abort(404)
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(e)
    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, evenement_id, donnees)
            flash("Événement mis à jour.", "success")
            return redirect(url_for("evenements.liste"))
        except svc.ErreursValidation as exc:
            erreurs = exc.erreurs
    return render_template(
        "evenements/formulaire.html",
        mode="edition",
        evenement_id=evenement_id,
        donnees=donnees,
        erreurs=erreurs,
        types=svc.LIBELLES_TYPES,
        titres=depot.charger("titres"),
    )


@bp.route("/<evenement_id>/supprimer", methods=["POST"])
def supprimer(evenement_id: str):
    depot = current_app.config["DEPOT"]
    if svc.supprimer(depot, evenement_id):
        flash("Événement supprimé.", "success")
    else:
        flash("Événement introuvable.", "error")
    return redirect(url_for("evenements.liste"))
