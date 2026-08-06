"""Routes watchlist — compatibilité.

La watchlist a été fusionnée dans les titres (une seule liste-pivot, voir
`app.routes.titres`). Ce module ne conserve que des redirections de
compatibilité (anciens liens / signets) et l'endpoint racine `/calendrier.ics`.
"""

from __future__ import annotations

from flask import Blueprint, Response, current_app, flash, redirect, url_for

from app.services.ics_export import generer_ics


bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")


_MSG_FUSION = (
    "La watchlist a été fusionnée dans les Titres : suivi, ordres et plans de "
    "rachat vivent désormais sur la fiche de chaque titre."
)


@bp.route("/", methods=["GET"])
def liste():
    return redirect(url_for("titres.liste"))


@bp.route("/nouveau", methods=["GET", "POST"])
def creer():
    flash(_MSG_FUSION, "info")
    return redirect(url_for("titres.creer"))


@bp.route("/<watch_id>/editer", methods=["GET", "POST"])
def editer(watch_id: str):
    flash(_MSG_FUSION, "info")
    return redirect(url_for("titres.liste"))


@bp.route("/<watch_id>/supprimer", methods=["POST"])
def supprimer(watch_id: str):
    flash(_MSG_FUSION, "info")
    return redirect(url_for("titres.liste"))


@bp.route("/<watch_id>/promouvoir", methods=["POST"])
def promouvoir(watch_id: str):
    flash(_MSG_FUSION, "info")
    return redirect(url_for("titres.liste"))


@bp.route("/<watch_id>/ordre/<ordre_id>/annuler", methods=["POST"])
def annuler_ordre(watch_id: str, ordre_id: str):
    # Le suivi vit sur le titre : l'annulation passe par titres.annuler_ordre.
    return redirect(url_for("titres.liste"))


@bp.route("/<watch_id>/ordre/<ordre_id>/reactiver", methods=["POST"])
def reactiver_ordre(watch_id: str, ordre_id: str):
    return redirect(url_for("titres.liste"))


# Endpoint /calendrier.ics : enregistré au niveau racine (pas du blueprint)
def enregistrer_endpoint_ics(app) -> None:
    @app.route("/calendrier.ics")
    def calendrier_ics():
        depot = app.config["DEPOT"]
        contenu = generer_ics(depot)
        return Response(
            contenu,
            mimetype="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": 'inline; filename="calendrier-portefeuille.ics"',
                "Cache-Control": "no-cache",
            },
        )
