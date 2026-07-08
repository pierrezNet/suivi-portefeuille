"""Routes : liste + CRUD mouvements (5 sous-types)."""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.services import mouvements as svc
from app.services.mouvements import (
    LIBELLES_TYPES,
    ErreursValidation,
)
from app.services.pru import quantite_disponible


bp = Blueprint("mouvements", __name__, url_prefix="/mouvements")


# --- Liste ---------------------------------------------------------------


@bp.route("/export.csv", methods=["GET"])
def export_csv():
    """Export CSV de tous les mouvements (optionnellement filtrés)."""
    from app.services.csv_export import csv_mouvements

    depot = current_app.config["DEPOT"]
    mouvements = depot.charger("mouvements")
    compte_id = request.args.get("compte_id") or None
    date_debut = request.args.get("date_debut") or None
    date_fin = request.args.get("date_fin") or None
    if compte_id:
        mouvements = [m for m in mouvements if m.get("compte_id") == compte_id]
    if date_debut:
        mouvements = [m for m in mouvements if (m.get("date") or "") >= date_debut]
    if date_fin:
        mouvements = [m for m in mouvements if (m.get("date") or "") <= date_fin]
    contenu = csv_mouvements(
        mouvements, depot.charger("comptes"), depot.charger("titres")
    )
    from datetime import date as _date
    nom_fichier = f"mouvements-{_date.today().isoformat()}.csv"
    return Response(
        contenu,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    filtres = {
        "compte_id": request.args.get("compte_id") or None,
        "titre_id": request.args.get("titre_id") or None,
        "type_": request.args.get("type") or None,
        "date_debut": request.args.get("date_debut") or None,
        "date_fin": request.args.get("date_fin") or None,
    }
    mvts = svc.lister(depot, **filtres)
    comptes = depot.charger("comptes")
    titres = depot.charger("titres")
    titres_par_id = {t["id"]: t for t in titres}
    comptes_par_id = {c["id"]: c for c in comptes}
    return render_template(
        "mouvements/liste.html",
        mouvements=mvts,
        comptes=comptes,
        titres=titres,
        titres_par_id=titres_par_id,
        comptes_par_id=comptes_par_id,
        filtres=filtres,
        types=LIBELLES_TYPES,
    )


# --- Création ------------------------------------------------------------


@bp.route("/nouveau", methods=["GET"])
def choisir_type():
    return render_template(
        "mouvements/choisir_type.html",
        types=LIBELLES_TYPES,
    )


@bp.route("/nouveau/<type_mouvement>", methods=["GET", "POST"])
def creer(type_mouvement: str):
    if type_mouvement not in LIBELLES_TYPES:
        abort(404)
    depot = current_app.config["DEPOT"]

    erreurs: dict[str, str] = {}
    suggestion_dca = None
    if request.method == "POST":
        donnees = dict(request.form)
    else:
        # Pré-remplissage depuis query params (utilisé par "Marquer ordre exécuté"
        # ou "Honorer rappel DCA")
        donnees = {
            k: v
            for k, v in request.args.items()
            if k
            in (
                "compte_id",
                "titre_id",
                "quantite",
                "prix_unitaire",
                "prix_unitaire_vente",
                "devise",
                "date",
                "source_ordre_watch_id",
                "source_ordre_id",
                "source_evenement_id",
                "montant_cible",
            )
            and v
        }
        # Date par défaut = aujourd'hui pour les achats issus d'ordres exécutés
        if donnees.get("source_ordre_id") and not donnees.get("date"):
            from datetime import date as _date
            donnees["date"] = _date.today().isoformat()
        # Idem pour les rappels DCA honorés
        if donnees.get("source_evenement_id") and not donnees.get("date"):
            from datetime import date as _date
            donnees["date"] = _date.today().isoformat()

        # Pré-remplissage suggéré quand on honore un rappel DCA : quantité et
        # prix estimés d'après le dernier cours importé du titre (éditables ;
        # on ne touche à rien si l'utilisateur a déjà fourni les valeurs).
        if (
            type_mouvement == "achat"
            and donnees.get("source_evenement_id")
            and donnees.get("titre_id")
            and donnees.get("montant_cible")
        ):
            from app.services import virements_programmes as svc_vp

            titre = next(
                (
                    t
                    for t in depot.charger("titres")
                    if t.get("id") == donnees.get("titre_id")
                ),
                None,
            )
            sugg = svc_vp.suggestion_achat_dca(donnees.get("montant_cible"), titre)
            if sugg:
                donnees.setdefault("quantite", str(sugg["quantite"]))
                donnees.setdefault("prix_unitaire", str(sugg["prix_unitaire"]))
                suggestion_dca = {
                    "cours": sugg["cours"],
                    "date": sugg["date_cours"],
                }

    source_watch_id = donnees.get("source_ordre_watch_id")
    source_ordre_id = donnees.get("source_ordre_id")
    source_evenement_id = donnees.get("source_evenement_id")

    if request.method == "POST":
        try:
            mouvement = svc.creer(depot, type_mouvement, donnees)
            # Si le mouvement provient d'un ordre (achat ou vente), marquer cet
            # ordre exécuté et le lier au mouvement créé.
            if (
                source_watch_id
                and source_ordre_id
                and type_mouvement in ("achat", "vente")
            ):
                from app.services.watchlist import marquer_ordre

                marquer_ordre(
                    depot,
                    source_watch_id,
                    source_ordre_id,
                    "execute",
                    mouvement_id=mouvement["id"],
                )
                flash(
                    f"{LIBELLES_TYPES[type_mouvement]} enregistré "
                    f"({mouvement['id']}) — ordre marqué comme exécuté.",
                    "success",
                )
                return redirect(
                    url_for("titres.detail", titre_id=mouvement.get("titre_id"))
                    if mouvement.get("titre_id")
                    else url_for("mouvements.liste")
                )
            # Si le mouvement honore un rappel DCA, marquer l'événement
            if source_evenement_id and type_mouvement == "achat":
                from app.services.evenements import marquer_honore

                marquer_honore(depot, source_evenement_id, mouvement["id"])
                flash(
                    f"{LIBELLES_TYPES[type_mouvement]} enregistré "
                    f"({mouvement['id']}) — rappel DCA marqué comme honoré.",
                    "success",
                )
                return redirect(url_for("evenements.liste"))
            flash(
                f"{LIBELLES_TYPES[type_mouvement]} enregistré ({mouvement['id']}).",
                "success",
            )
            return redirect(url_for("mouvements.liste"))
        except ErreursValidation as e:
            erreurs = e.erreurs

    # Charger la watch source pour le bandeau d'info
    source_watch = None
    if source_watch_id:
        from app.services import watchlist as svc_watchlist

        source_watch = svc_watchlist.trouver(depot, source_watch_id)

    # Charger l'événement source (rappel DCA) pour le bandeau d'info
    source_evenement = None
    if source_evenement_id:
        from app.services import evenements as svc_evenements

        source_evenement = svc_evenements.trouver(depot, source_evenement_id)

    return render_template(
        "mouvements/formulaire.html",
        mode="creation",
        type_mouvement=type_mouvement,
        libelle_type=LIBELLES_TYPES[type_mouvement],
        donnees=donnees,
        erreurs=erreurs,
        comptes=depot.charger("comptes"),
        titres=depot.charger("titres"),
        source_ordre_watch_id=source_watch_id,
        source_ordre_id=source_ordre_id,
        source_watch=source_watch,
        source_evenement_id=source_evenement_id,
        source_evenement=source_evenement,
        suggestion_dca=suggestion_dca,
    )


# --- Édition / suppression ------------------------------------------------


@bp.route("/<mouvement_id>/editer", methods=["GET", "POST"])
def editer(mouvement_id: str):
    depot = current_app.config["DEPOT"]
    mouvement = svc.trouver(depot, mouvement_id)
    if mouvement is None:
        abort(404)
    type_mouvement = mouvement["type"]

    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(mouvement)

    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, mouvement_id, {**donnees, "type": type_mouvement})
            flash(
                f"{LIBELLES_TYPES[type_mouvement]} mis à jour.", "success"
            )
            return redirect(url_for("mouvements.liste"))
        except ErreursValidation as e:
            erreurs = e.erreurs

    return render_template(
        "mouvements/formulaire.html",
        mode="edition",
        type_mouvement=type_mouvement,
        libelle_type=LIBELLES_TYPES[type_mouvement],
        mouvement_id=mouvement_id,
        donnees=donnees,
        erreurs=erreurs,
        comptes=depot.charger("comptes"),
        titres=depot.charger("titres"),
    )


@bp.route("/<mouvement_id>/supprimer", methods=["POST"])
def supprimer(mouvement_id: str):
    depot = current_app.config["DEPOT"]
    try:
        if svc.supprimer(depot, mouvement_id):
            flash("Mouvement supprimé.", "success")
        else:
            flash("Mouvement introuvable.", "error")
    except ValueError as e:
        flash(str(e), "error")
    # Retour sur la page d'origine si fournie (ex. fiche titre), sinon journal.
    # On n'accepte qu'un chemin interne (garde-fou open-redirect).
    next_url = request.form.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("mouvements.liste"))


# --- Endpoint utilitaire : quantité dispo (vente) -------------------------


@bp.route("/dispo", methods=["GET"])
def dispo():
    """JSON minimal pour aider le formulaire de vente côté client."""
    depot = current_app.config["DEPOT"]
    compte_id = request.args.get("compte_id")
    titre_id = request.args.get("titre_id")
    exclure_id = request.args.get("exclure_id") or None
    if not compte_id or not titre_id:
        return {"quantite": "0"}
    q = quantite_disponible(
        depot.charger("mouvements"),
        compte_id,
        titre_id,
        exclure_id=exclure_id,
    )
    return {"quantite": str(q)}
