"""Routes : catalogue de titres, page détail avec thèse, historique et PV."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

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

from datetime import date as _date

from app.services import notes_titres as svc_notes
from app.services import titres as svc
from app.services.evenements import LIBELLES_TYPES as LIBELLES_EVENEMENT
from app.services.evenements import lister as lister_evenements
from app.services.mouvements import lister as lister_mouvements
from app.services.notes_titres import LIBELLES_TYPES as LIBELLES_NOTE
from app.services.plus_values import cumul_plus_values
from app.services.pru import calculer_pru, quantite_disponible


bp = Blueprint("titres", __name__, url_prefix="/titres")


ZERO = Decimal("0")


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    titres = svc.lister(depot)
    mouvements = depot.charger("mouvements")
    notes = depot.charger("notes_titres")

    # Pré-calcul : positions agrégées + PV cumulée par titre
    positions_par_titre: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for m in mouvements:
        tid = m.get("titre_id")
        if not tid:
            continue
        if m["type"] == "achat":
            positions_par_titre[tid] += Decimal(str(m.get("quantite") or "0"))
        elif m["type"] == "vente":
            positions_par_titre[tid] -= Decimal(str(m.get("quantite") or "0"))

    pv_par_titre = {
        t["id"]: cumul_plus_values(mouvements, titre_id=t["id"]) for t in titres
    }

    # Activité par titre : nb d'entrées de journal (notes_titres + notes
    # libres des mouvements) + date de la dernière entrée
    activite_par_titre: dict[str, dict] = {}
    for n in notes:
        tid = n.get("titre_id")
        if not tid:
            continue
        a = activite_par_titre.setdefault(tid, {"nb": 0, "derniere_date": ""})
        a["nb"] += 1
        if (n.get("date") or "") > a["derniere_date"]:
            a["derniere_date"] = n["date"]
    for m in mouvements:
        tid = m.get("titre_id")
        if not tid:
            continue
        if not (m.get("notes") or "").strip():
            continue
        if m.get("type") not in ("achat", "vente", "dividende_recu"):
            continue
        a = activite_par_titre.setdefault(tid, {"nb": 0, "derniere_date": ""})
        a["nb"] += 1
        if (m.get("date") or "") > a["derniere_date"]:
            a["derniere_date"] = m["date"]

    return render_template(
        "titres/liste.html",
        titres=titres,
        positions_par_titre=positions_par_titre,
        pv_par_titre=pv_par_titre,
        activite_par_titre=activite_par_titre,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
def creer():
    depot = current_app.config["DEPOT"]
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}
    if request.method == "POST":
        try:
            t = svc.creer(depot, donnees)
            flash(f"Titre {t['ticker']} créé.", "success")
            return redirect(url_for("titres.detail", titre_id=t["id"]))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs
    return render_template(
        "titres/formulaire.html",
        mode="creation",
        donnees=donnees,
        erreurs=erreurs,
    )


@bp.route("/<titre_id>", methods=["GET"])
def detail(titre_id: str):
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)

    mouvements_titre = lister_mouvements(depot, titre_id=titre_id)
    comptes = {c["id"]: c for c in depot.charger("comptes")}

    # Positions et PRU par compte
    tous_mvts = depot.charger("mouvements")
    positions: list[dict] = []
    for cid, compte in comptes.items():
        q = quantite_disponible(tous_mvts, cid, titre_id)
        if q > ZERO:
            pru = calculer_pru(tous_mvts, cid, titre_id)
            positions.append(
                {"compte": compte, "quantite": q, "pru": pru}
            )

    pv_titre = cumul_plus_values(tous_mvts, titre_id=titre_id)

    # Cumul dividendes nets reçus (en EUR si dispo, sinon brut)
    dividendes_eur = ZERO
    nb_dividendes = 0
    for m in mouvements_titre:
        if m.get("type") != "dividende_recu":
            continue
        nb_dividendes += 1
        if m.get("montant_net_eur"):
            dividendes_eur += Decimal(str(m["montant_net_eur"]))
        elif m.get("montant_brut_total"):
            dividendes_eur += Decimal(str(m["montant_brut_total"]))

    # Journal de bord agrégé : notes_titres + notes des mouvements liés
    notes = svc_notes.lister(depot, titre_id=titre_id)
    journal = _construire_journal(notes, mouvements_titre, titre, comptes)

    # Événements à venir (liés au titre)
    today_iso = _date.today().isoformat()
    evenements_a_venir = lister_evenements(
        depot, titre_id=titre_id, date_debut=today_iso
    )

    return render_template(
        "titres/detail.html",
        titre=titre,
        mouvements=mouvements_titre,
        comptes=comptes,
        positions=positions,
        pv_titre=pv_titre,
        dividendes_eur=dividendes_eur,
        nb_dividendes=nb_dividendes,
        journal=journal,
        evenements_a_venir=evenements_a_venir,
        types_note=LIBELLES_NOTE,
        types_evenement=LIBELLES_EVENEMENT,
        types_note_codes=svc_notes.TYPES_NOTE,
        evenements_pour_lien=depot.charger("evenements"),
    )


def _construire_journal(
    notes: list[dict], mouvements: list[dict], titre: dict, comptes: dict
) -> list[dict]:
    """Fusionne notes_titres et notes des mouvements en un fil chronologique inversé.

    Chaque entrée a un champ `source` : "note" (éditable directement) ou
    "mouvement" (édition via formulaire mouvement). Les mouvements sans note
    libre sont ignorés.
    """
    LIBELLES_MOUVEMENT = {
        "achat": "Achat",
        "vente": "Vente",
        "dividende_recu": "Dividende",
    }
    ticker = titre.get("ticker") or titre.get("nom") or ""
    entrees: list[dict] = []

    for n in notes:
        entrees.append(
            {
                "source": "note",
                "id": n["id"],
                "date": n["date"],
                "type_code": n["type"],
                "titre_court": n["titre_court"],
                "contenu": n["contenu"],
                "evenement_id": n.get("evenement_id"),
            }
        )

    for m in mouvements:
        notes_libres = (m.get("notes") or "").strip()
        if not notes_libres:
            continue
        if m.get("type") not in ("achat", "vente", "dividende_recu"):
            continue
        compte_nom = comptes.get(m.get("compte_id"), {}).get("nom") or ""
        if m["type"] == "achat":
            titre_court = (
                f"Achat de {m.get('quantite')} × {ticker} "
                f"@ {m.get('prix_unitaire')} €"
                + (f" — {compte_nom}" if compte_nom else "")
            )
        elif m["type"] == "vente":
            titre_court = (
                f"Vente de {m.get('quantite')} × {ticker} "
                f"@ {m.get('prix_unitaire_vente')} €"
                + (f" — {compte_nom}" if compte_nom else "")
            )
        else:  # dividende_recu
            titre_court = (
                f"Dividende {ticker} : "
                f"{m.get('montant_net_eur') or m.get('montant_brut_total')} €"
            )
        entrees.append(
            {
                "source": "mouvement",
                "id": m["id"],
                "date": m["date"],
                "type_code": m["type"],  # achat | vente | dividende_recu
                "type_libelle": LIBELLES_MOUVEMENT.get(m["type"], m["type"]),
                "titre_court": titre_court,
                "contenu": notes_libres,
            }
        )

    entrees.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    return entrees


@bp.route("/<titre_id>/editer", methods=["GET", "POST"])
def editer(titre_id: str):
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else dict(titre)
    if request.method == "POST":
        try:
            svc.mettre_a_jour(depot, titre_id, donnees)
            flash(f"Titre {titre['ticker']} mis à jour.", "success")
            return redirect(url_for("titres.detail", titre_id=titre_id))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs
    return render_template(
        "titres/formulaire.html",
        mode="edition",
        titre_id=titre_id,
        donnees=donnees,
        erreurs=erreurs,
    )


@bp.route("/<titre_id>/supprimer", methods=["POST"])
def supprimer(titre_id: str):
    depot = current_app.config["DEPOT"]
    try:
        if svc.supprimer(depot, titre_id):
            flash("Titre supprimé.", "success")
        else:
            flash("Titre introuvable.", "error")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("titres.liste"))


# Champs financiers écrasés par l'actualisation Yahoo. Les autres (these_lt,
# signaux, perspectives, secteur, site_ir, horizon, isin, marche, devise…)
# sont conservés tels quels.
_CHAMPS_FINANCIERS_YAHOO = (
    "cap_boursiere_m",
    "dette_nette_m",
    "valeur_entreprise_m",
    "dividende_par_action",
    "frequence_dividende",
    "verse_dividende",
)
# Sous-ensemble historisé dans `historique_yahoo` (chiffres numériques utiles
# au calcul de tendance). On exclut `verse_dividende` et `frequence_dividende`
# qui ne se prêtent pas à un delta.
_CHAMPS_HISTORISES = (
    "cap_boursiere_m",
    "dette_nette_m",
    "valeur_entreprise_m",
    "dividende_par_action",
)


@bp.route("/import", methods=["GET", "POST"])
def importer_xlsx():
    """Import xlsx Bourse Direct → met à jour les cours du jour."""
    from app.services import import_bourse_direct as svc_import

    depot = current_app.config["DEPOT"]
    if request.method == "GET":
        return render_template("titres/import.html")

    fichiers = [f for f in request.files.getlist("fichiers") if f and f.filename]
    if not fichiers:
        flash("Aucun fichier sélectionné.", "error")
        return redirect(url_for("titres.importer_xlsx"))
    for f in fichiers:
        if not f.filename.lower().endswith(".xlsx"):
            flash(
                f"Format attendu : fichier .xlsx (« {f.filename} » rejeté).",
                "error",
            )
            return redirect(url_for("titres.importer_xlsx"))

    creer_inconnus = request.form.get("creer_inconnus") == "1"
    lignes: list[svc_import.LigneImport] = []
    for f in fichiers:
        try:
            lignes.extend(svc_import.parser_xlsx(f.stream))
        except svc_import.ErreurImport as e:
            flash(f"Lecture impossible pour « {f.filename} » : {e}", "error")
            return redirect(url_for("titres.importer_xlsx"))

    resultat = svc_import.appliquer(depot, lignes, creer_inconnus=creer_inconnus)

    # Snapshot du portefeuille après import (les cours viennent d'être actualisés).
    # Idempotent : un snapshot par jour, le dernier import écrase.
    if resultat.mis_a_jour:
        from app.services import dashboard_data, snapshots
        data = dashboard_data.construire(depot, rattraper_virements=False)
        snapshots.enregistrer_snapshot(
            depot,
            cash_total=data["total_cash"],
            valo_titres_total=data["total_valo_titres"],
            portefeuille_total=data["total_portefeuille"],
            pv_latente_total=data["total_pv_latente"],
        )

    parts: list[str] = []
    if resultat.mis_a_jour:
        details = ", ".join(
            f"{m['ticker'] or m['nom']} {m['cours_jour_eur']} €"
            for m in resultat.mis_a_jour[:6]
        )
        suffixe = f" …+{len(resultat.mis_a_jour) - 6} autres" if len(resultat.mis_a_jour) > 6 else ""
        parts.append(f"{len(resultat.mis_a_jour)} titre(s) mis à jour ({details}{suffixe})")
    if resultat.crees:
        details = ", ".join(c["nom"] for c in resultat.crees)
        parts.append(f"{len(resultat.crees)} titre(s) créé(s) : {details}")
    if resultat.ignores:
        details = ", ".join(f"{i['nom']} ({i['isin']})" for i in resultat.ignores)
        parts.append(f"{len(resultat.ignores)} ligne(s) ignorée(s) : {details}")
    if resultat.non_presents_dans_xlsx:
        parts.append(
            f"{len(resultat.non_presents_dans_xlsx)} titre(s) du catalogue absents du fichier : "
            + ", ".join(resultat.non_presents_dans_xlsx)
        )
    if not parts:
        parts.append("aucune ligne traitable dans le fichier")

    flash("✓ Import terminé. " + " · ".join(parts), "success")
    return redirect(url_for("titres.liste"))


@bp.route("/<titre_id>/actualiser-yahoo", methods=["POST"])
def actualiser_yahoo(titre_id: str):
    """Rafraîchit les chiffres financiers du titre depuis Yahoo Finance.

    Historise les anciens chiffres dans `titre.historique_yahoo` (liste
    de snapshots `{date, valeurs}`) pour permettre l'affichage de tendances.
    """
    from datetime import date as _date

    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)

    from app.services.yahoo import enrichir_pour_titre, inferer_ticker_yahoo  # lazy

    nouveau_yahoo = enrichir_pour_titre(
        titre.get("ticker"),
        titre.get("marche"),
        ticker_yahoo_override=titre.get("ticker_yahoo"),
    )
    if not nouveau_yahoo:
        ticker_essaye = titre.get("ticker_yahoo") or inferer_ticker_yahoo(
            titre.get("ticker"), titre.get("marche")
        )
        flash(
            f"Yahoo Finance : aucune donnée trouvée pour « {ticker_essaye} »"
            f" ({titre.get('ticker')} sur {titre.get('marche')})."
            " Tu peux saisir un ticker_yahoo personnalisé dans l'édition du titre"
            " (utile pour les ETF UCITS et tickers exotiques).",
            "error",
        )
        return redirect(url_for("titres.detail", titre_id=titre_id))

    # Construire le dict de mise à jour : tous les champs existants +
    # écrasement sélectif des chiffres financiers. Snapshot historisé limité
    # aux champs qui changent vraiment (évite le bruit dans l'historique).
    dict_update = dict(titre)
    deltas: list[str] = []
    snapshot_avant: dict = {}
    for champ in _CHAMPS_FINANCIERS_YAHOO:
        ancien = dict_update.get(champ)
        nouveau = nouveau_yahoo.get(champ)
        if nouveau in (None, ""):
            continue
        # Normalisation : éviter le piège `False or ""` qui vaut "".
        ancien_str = "" if ancien is None else str(ancien)
        nouveau_str = str(nouveau)
        if ancien_str != nouveau_str:
            etiquette_avant = ancien if ancien not in (None, "") else "—"
            deltas.append(f"{champ} : {etiquette_avant} → {nouveau}")
            dict_update[champ] = nouveau
            # Snapshot seulement les champs historisables qui ont vraiment bougé
            if champ in _CHAMPS_HISTORISES and ancien not in (None, ""):
                snapshot_avant[champ] = ancien

    if not deltas:
        flash("Yahoo : aucun changement à apporter (déjà à jour).", "info")
        return redirect(url_for("titres.detail", titre_id=titre_id))

    # Pousse le snapshot pré-modification dans l'historique (uniquement
    # les champs qui ont changé)
    if snapshot_avant:
        historique = list(titre.get("historique_yahoo") or [])
        historique.append(
            {
                "date": _date.today().isoformat(),
                "valeurs": snapshot_avant,
            }
        )
        dict_update["historique_yahoo"] = historique

    # Écriture directe : on modifie le titre cible dans la liste pour
    # préserver tous les champs custom (historique_yahoo, perspectives legacy,
    # etc.) que `svc.mettre_a_jour` filtre via `_normaliser`.
    items = depot.charger("titres")
    for i, t in enumerate(items):
        if t.get("id") == titre_id:
            items[i] = dict_update
            break
    depot.enregistrer("titres", items)

    flash(
        "Yahoo : " + " · ".join(deltas),
        "success",
    )
    return redirect(url_for("titres.detail", titre_id=titre_id))
