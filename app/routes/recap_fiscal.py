"""Routes : récapitulatifs fiscaux par année et par compte."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    render_template,
    request,
)

from app.services import fiscal as svc


bp = Blueprint("recap_fiscal", __name__, url_prefix="/recap-fiscal")


def _moins_values_anterieures(args) -> list[dict]:
    """Lit les moins-values antérieures saisies dans l'URL : `?mv_2023=250&mv_2024=120`."""
    out = []
    for clef, valeur in args.items():
        if not clef.startswith("mv_"):
            continue
        try:
            annee = int(clef[3:])
            montant = Decimal(str(valeur).replace(",", "."))
            if montant > 0:
                out.append({"annee": annee, "montant": montant})
        except (ValueError, InvalidOperation):
            continue
    return out


@bp.route("/", methods=["GET"])
def index():
    depot = current_app.config["DEPOT"]
    mouvements = depot.charger("mouvements")
    annees = svc.annees_avec_activite(mouvements)
    comptes = depot.charger("comptes")
    apercu_par_annee = []
    for an in reversed(annees):
        agg = svc.stats_globales_annee(mouvements, comptes, an)
        apercu_par_annee.append({"annee": an, "cumul": agg["cumul"]})
    return render_template(
        "recap_fiscal/index.html",
        annees=apercu_par_annee,
        nb_comptes=len(comptes),
    )


@bp.route("/<int:annee>/export.csv", methods=["GET"])
def export_csv(annee: int):
    """Export CSV du récap fiscal pour une année donnée."""
    from app.services.csv_export import csv_recap_fiscal_annee

    depot = current_app.config["DEPOT"]
    mouvements = depot.charger("mouvements")
    comptes = depot.charger("comptes")
    if annee not in svc.annees_avec_activite(mouvements):
        abort(404)
    agg = svc.stats_globales_annee(mouvements, comptes, annee)
    contenu = csv_recap_fiscal_annee(annee, agg["par_compte"], agg["cumul"])
    nom_fichier = f"recap-fiscal-{annee}.csv"
    return Response(
        contenu,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@bp.route("/<int:annee>", methods=["GET"])
def annee(annee: int):
    depot = current_app.config["DEPOT"]
    mouvements = depot.charger("mouvements")
    comptes = depot.charger("comptes")
    if annee not in svc.annees_avec_activite(mouvements):
        abort(404)
    agg = svc.stats_globales_annee(mouvements, comptes, annee)
    return render_template(
        "recap_fiscal/annee.html",
        annee=annee,
        cumul=agg["cumul"],
        par_compte=agg["par_compte"],
    )


@bp.route("/<int:annee>/<compte_id>", methods=["GET"])
def compte_annee(annee: int, compte_id: str):
    depot = current_app.config["DEPOT"]
    mouvements = depot.charger("mouvements")
    comptes = {c["id"]: c for c in depot.charger("comptes")}
    titres_par_id = {t["id"]: t for t in depot.charger("titres")}
    compte = comptes.get(compte_id)
    if not compte:
        abort(404)

    stats = svc.stats_compte_annee(mouvements, compte_id, annee)
    type_compte = compte.get("type")

    contexte = {
        "annee": annee,
        "compte": compte,
        "stats": stats,
        "type_compte": type_compte,
    }

    if type_compte == "CTO":
        moins_values = _moins_values_anterieures(request.args)
        contexte["ventes_2074"] = svc.detail_ventes_cto(
            mouvements, titres_par_id, compte_id, annee
        )
        contexte["imputations"] = svc.calculer_imputations(
            mouvements,
            compte_id,
            annee,
            moins_values_anterieures=moins_values,
        )
        contexte["moins_values_anterieures"] = moins_values
    elif type_compte == "PEA":
        contexte["indicateurs_pea"] = svc.indicateurs_pea(mouvements, compte)

    return render_template("recap_fiscal/compte.html", **contexte)
