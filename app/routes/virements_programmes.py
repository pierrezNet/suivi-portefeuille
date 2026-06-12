"""Routes : CRUD virements programmés + page d'aperçu des prochaines échéances."""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

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

from app.services import virements_programmes as svc
from app.services.virements_programmes import _dates_echeance


bp = Blueprint(
    "virements_programmes", __name__, url_prefix="/virements-programmes"
)


HORIZON_PREVU_JOURS = 365

DIVISEURS_VERS_MENSUEL = {
    "mensuel": Decimal("1"),
    "trimestriel": Decimal("3"),
    "semestriel": Decimal("6"),
    "annuel": Decimal("12"),
}


def _recap_actifs(virements: list[dict], echeances: list[dict]) -> dict:
    """Synthèse pour le bandeau en tête de page.

    Calcule l'effort mensuel équivalent des programmes actifs (one_shot ignoré)
    et renvoie aussi la prochaine échéance globale (la 1re de `echeances`).
    """
    total_dca = Decimal("0")
    total_cash = Decimal("0")
    for vp in virements:
        if not vp.get("actif", True):
            continue
        periodicite = vp.get("periodicite") or "mensuel"
        diviseur = DIVISEURS_VERS_MENSUEL.get(periodicite)
        if diviseur is None:
            continue  # one_shot ou inconnu : exclu du récurrent
        try:
            montant = Decimal(str(vp.get("montant", "0")))
        except Exception:
            continue
        equivalent = (montant / diviseur).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if vp.get("titre_id"):
            total_dca += equivalent
        else:
            total_cash += equivalent
    total = total_dca + total_cash

    prochaine = None
    if echeances:
        e = echeances[0]
        prochaine = {
            "date": e["date"],
            "montant": e["vp"].get("montant"),
            "libelle": e["vp"].get("libelle"),
            "is_dca": bool(e["vp"].get("titre_id")),
        }

    return {
        "total_mensuel_eq": total,
        "total_dca": total_dca,
        "total_cash": total_cash,
        "prochaine": prochaine,
    }


def _prochaines_echeances(virements: list[dict], jours: int = HORIZON_PREVU_JOURS) -> list[dict]:
    """Calcule les prochaines échéances à venir dans la fenêtre donnée."""
    today = _date.today()
    horizon = today + timedelta(days=jours)
    res = []
    for vp in virements:
        if not vp.get("actif", True):
            continue
        try:
            debut = _date.fromisoformat(vp["date_debut"])
        except (KeyError, ValueError):
            continue
        debut_effectif = max(debut, today)
        fin_effective = horizon
        if vp.get("date_fin"):
            try:
                fin_effective = min(
                    fin_effective, _date.fromisoformat(vp["date_fin"])
                )
            except ValueError:
                pass
        periodicite = vp.get("periodicite") or "mensuel"
        for d in _dates_echeance(
            debut_effectif, fin_effective, int(vp.get("jour_du_mois", 1)), periodicite
        ):
            res.append({"date": d.isoformat(), "vp": vp})
    res.sort(key=lambda x: x["date"])
    return res


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    items = svc.lister(depot)
    comptes = {c["id"]: c for c in depot.charger("comptes")}
    titres = {t["id"]: t for t in depot.charger("titres")}
    echeances = _prochaines_echeances(items)
    recap = _recap_actifs(items, echeances)
    return render_template(
        "virements_programmes/liste.html",
        virements=items,
        comptes=comptes,
        titres=titres,
        echeances=echeances,
        recap=recap,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
def creer():
    depot = current_app.config["DEPOT"]
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}
    if request.method == "POST":
        try:
            vp = svc.creer(depot, donnees)
            if vp.get("titre_id"):
                flash(
                    f"Investissement programmé créé : {vp['montant']} € "
                    f"({vp.get('periodicite', 'mensuel')}) sur {vp['titre_id']}.",
                    "success",
                )
            else:
                flash(
                    f"Virement programmé créé : {vp['montant']} € le jour "
                    f"{vp['jour_du_mois']} sur {vp['compte_id']}.",
                    "success",
                )
            return redirect(url_for("virements_programmes.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs
    return render_template(
        "virements_programmes/formulaire.html",
        mode="creation",
        donnees=donnees,
        erreurs=erreurs,
        comptes=depot.charger("comptes"),
        titres=depot.charger("titres"),
    )


@bp.route("/<vp_id>/editer", methods=["GET", "POST"])
def editer(vp_id: str):
    depot = current_app.config["DEPOT"]
    vp = svc.trouver(depot, vp_id)
    if not vp:
        abort(404)
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(vp)
    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, vp_id, donnees)
            flash("Programme mis à jour.", "success")
            return redirect(url_for("virements_programmes.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs
    return render_template(
        "virements_programmes/formulaire.html",
        mode="edition",
        vp_id=vp_id,
        donnees=donnees,
        erreurs=erreurs,
        comptes=depot.charger("comptes"),
        titres=depot.charger("titres"),
    )


@bp.route("/<vp_id>/supprimer", methods=["POST"])
def supprimer(vp_id: str):
    depot = current_app.config["DEPOT"]
    if svc.supprimer(depot, vp_id):
        flash("Virement programmé supprimé.", "success")
    else:
        flash("Virement programmé introuvable.", "error")
    return redirect(url_for("virements_programmes.liste"))


@bp.route("/rattraper", methods=["POST"])
def rattraper_maintenant():
    """Lance manuellement le rattrapage (utile si on a changé la date d'un VP
    ou ajusté la date système)."""
    depot = current_app.config["DEPOT"]
    crees = svc.rattraper(depot)
    if crees:
        flash(
            f"{len(crees)} mouvement{'s' if len(crees) > 1 else ''} créé{'s' if len(crees) > 1 else ''} par rattrapage.",
            "success",
        )
    else:
        flash("Rien à rattraper.", "info")
    return redirect(url_for("virements_programmes.liste"))
