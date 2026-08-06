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

from app.routes._filtres import resoudre_filtres
from app.services import notes_titres as svc_notes
from app.services import titres as svc
from app.services.categories import CATEGORIES
from app.services.etf_amundi import (
    ETF_AMUNDI,
    est_etf_amundi,
    get_etf_composition,
    lire_cache,
)
from app.services.evenements import LIBELLES_TYPES as LIBELLES_EVENEMENT
from app.services.evenements import lister as lister_evenements
from app.services.mouvements import lister as lister_mouvements
from app.services.notes_titres import LIBELLES_TYPES as LIBELLES_NOTE
from app.services.plus_values import cumul_plus_values
from app.services.pru import calculer_pru, quantite_disponible
from app.services import suggestions_ia as svc_suggestions


bp = Blueprint("titres", __name__, url_prefix="/titres")


ZERO = Decimal("0")


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]

    # Filtres persistants (statut / priorité de suivi), comme les autres listes.
    redir, vals, nb_filtres_actifs = resoudre_filtres(
        "filtres_titres", "titres.liste",
        ("statut", "priorite", "inclure_abandonnes"))
    if redir:
        return redir
    inclure_abandonnes = vals["inclure_abandonnes"] == "1"

    titres = svc.lister(depot)
    if vals["statut"]:
        titres = [t for t in titres if t.get("statut") == vals["statut"]]
    if vals["priorite"]:
        titres = [t for t in titres if t.get("priorite") == vals["priorite"]]

    # Par défaut, les titres abandonnés sont masqués (case « Inclure les
    # abandonnés » décochée) — sauf si on filtre explicitement sur ce statut.
    nb_abandonnes_masques = 0
    if not inclure_abandonnes and vals["statut"] != "abandonne":
        avant = len(titres)
        titres = [t for t in titres if t.get("statut") != "abandonne"]
        nb_abandonnes_masques = avant - len(titres)

    mouvements = depot.charger("mouvements")
    notes = depot.charger("notes_titres")
    comptes = {c["id"]: c for c in depot.charger("comptes")}

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

    # Pré-remplissage des formulaires de suivi du panneau d'actions (ordre +
    # plan de rachat) et repérage de l'ordre actif pour le bouton « Exécuter ».
    form_suivi: dict[str, dict] = {}
    ordre_actif_par_titre: dict[str, dict] = {}
    for t in titres:
        paliers = t.get("paliers_rachat") or []
        actif = next(
            (o for o in (t.get("ordres_actifs") or [])
             if o.get("statut") == "en_attente"),
            None,
        )
        if actif:
            ordre_actif_par_titre[t["id"]] = actif
        form_suivi[t["id"]] = {
            "cible_totale": t.get("cible_totale", ""),
            "paliers_prix": "\n".join(p.get("prix", "") for p in paliers),
            "paliers_quantite": "\n".join(
                p.get("quantite") or p.get("tranche") or "" for p in paliers),
            "paliers_commentaire": "\n".join(p.get("commentaire", "") for p in paliers),
            "ordre_sens": (actif or {}).get("sens", "achat"),
            "ordre_prix": (actif or {}).get("prix_limite", ""),
            "ordre_quantite": (actif or {}).get("quantite", ""),
            "ordre_validite": (actif or {}).get("validite", ""),
            "ordre_note": (actif or {}).get("note", ""),
            "ordre_id": (actif or {}).get("id", ""),
            "ordre_date_creation": (actif or {}).get("date_creation", ""),
        }

    return render_template(
        "titres/liste.html",
        titres=titres,
        positions_par_titre=positions_par_titre,
        pv_par_titre=pv_par_titre,
        activite_par_titre=activite_par_titre,
        comptes=comptes,
        form_suivi=form_suivi,
        ordre_actif_par_titre=ordre_actif_par_titre,
        filtres={"statut": vals["statut"] or None, "priorite": vals["priorite"] or None},
        nb_filtres_actifs=nb_filtres_actifs,
        inclure_abandonnes=inclure_abandonnes,
        nb_abandonnes_masques=nb_abandonnes_masques,
        statuts=svc.STATUTS,
        priorites=svc.PRIORITES,
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
        categories=CATEGORIES,
        statuts=svc.STATUTS,
        priorites=svc.PRIORITES,
        comptes=depot.charger("comptes"),
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

    position_totale = sum((p["quantite"] for p in positions), ZERO)
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

    # Ordres actifs / plan de rachat : portés désormais par le titre lui-même.
    ordres_actifs = [
        o for o in (titre.get("ordres_actifs") or [])
        if o.get("statut") == "en_attente"
    ]
    historique_ordres = sorted(
        [o for o in (titre.get("ordres_actifs") or [])
         if o.get("statut") != "en_attente"],
        key=lambda o: o.get("date_creation", ""),
        reverse=True,
    )
    symbole = "$" if (titre.get("devise") or "EUR").upper() == "USD" else "€"
    paliers = titre.get("paliers_rachat") or []
    plan_donnees = {
        "cible_totale": titre.get("cible_totale", ""),
        "paliers_prix": "\n".join(p.get("prix", "") for p in paliers),
        "paliers_quantite": "\n".join(
            p.get("quantite") or p.get("tranche") or "" for p in paliers),
        "paliers_commentaire": "\n".join(p.get("commentaire", "") for p in paliers),
    }

    # Exposition réelle de l'indice (ETF Amundi synthétique) : lecture du cache
    # LOCAL uniquement — aucun appel réseau au rendu. Le réseau n'est déclenché
    # que par le bouton « Rafraîchir » (route rafraichir_etf ci-dessous).
    isin = titre.get("isin")
    etf_isin = isin if est_etf_amundi(isin) else None
    etf_compo = lire_cache(isin) if etf_isin else None
    etf_meta = ETF_AMUNDI.get(isin) if etf_isin else None

    return render_template(
        "titres/detail.html",
        titre=titre,
        etf_isin=etf_isin,
        etf_compo=etf_compo,
        etf_meta=etf_meta,
        ordres_actifs=ordres_actifs,
        historique_ordres=historique_ordres,
        symbole=symbole,
        paliers=paliers,
        plan_donnees=plan_donnees,
        mouvements=mouvements_titre,
        comptes=comptes,
        positions=positions,
        position_totale=position_totale,
        pv_titre=pv_titre,
        dividendes_eur=dividendes_eur,
        nb_dividendes=nb_dividendes,
        journal=journal,
        suggestions_ia=svc_suggestions.lister(depot, titre_id=titre_id),
        evenements_a_venir=evenements_a_venir,
        types_note=LIBELLES_NOTE,
        types_evenement=LIBELLES_EVENEMENT,
        types_note_codes=svc_notes.TYPES_NOTE,
        evenements_pour_lien=depot.charger("evenements"),
    )


@bp.route("/<titre_id>/etf/refresh", methods=["POST"])
def rafraichir_etf(titre_id: str):
    """Force la mise à jour de la compo indice depuis Amundi (seul appel réseau).
    Débrayable : en cas d'échec, la page reste fonctionnelle (flash + redirect)."""
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)
    isin = titre.get("isin")
    if not est_etf_amundi(isin):
        abort(404)
    data = get_etf_composition(isin, force_refresh=True)
    if data:
        flash("Composition de l'indice mise à jour.", "success")
    else:
        flash(
            "Composition indisponible pour le moment (réseau ou API). "
            "Réessaie plus tard.",
            "error",
        )
    return redirect(url_for("titres.detail", titre_id=titre_id))


def _retour(titre_id: str) -> str:
    """URL de retour après une action de suivi : `next` du formulaire s'il est
    sûr (chemin local), sinon la fiche du titre. Permet aux boutons de la
    liste-pivot de revenir à la liste, et à ceux de la fiche d'y rester."""
    nxt = request.form.get("next")
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return url_for("titres.detail", titre_id=titre_id)


@bp.route("/<titre_id>/ordre", methods=["POST"])
def enregistrer_ordre(titre_id: str):
    """Pose / modifie / retire l'ordre limite actif d'un titre (porté par le
    titre lui-même)."""
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)
    try:
        svc.definir_ordre_actif(depot, titre_id, dict(request.form))
        flash("Ordre enregistré.", "success")
    except ValueError as e:
        flash(f"Ordre invalide : {e}", "error")
    return redirect(_retour(titre_id))


@bp.route("/<titre_id>/paliers", methods=["POST"])
def enregistrer_paliers(titre_id: str):
    """Met à jour le plan de rachat indicatif d'un titre (porté par le titre)."""
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)
    try:
        svc.definir_paliers(depot, titre_id, dict(request.form))
        flash("Plan de rachat mis à jour.", "success")
    except ValueError as e:
        flash(f"Plan invalide : {e}", "error")
    return redirect(_retour(titre_id))


@bp.route("/<titre_id>/ordre/<ordre_id>/annuler", methods=["POST"])
def annuler_ordre(titre_id: str, ordre_id: str):
    """Marque un ordre comme annulé sans créer de mouvement."""
    depot = current_app.config["DEPOT"]
    if svc.marquer_ordre(depot, titre_id, ordre_id, "annule"):
        flash("Ordre marqué comme annulé.", "success")
    else:
        flash("Ordre introuvable ou déjà annulé.", "error")
    return redirect(_retour(titre_id))


@bp.route("/<titre_id>/ordre/<ordre_id>/reactiver", methods=["POST"])
def reactiver_ordre(titre_id: str, ordre_id: str):
    """Réactive un ordre clos (un seul ordre actif à la fois)."""
    depot = current_app.config["DEPOT"]
    titre = svc.trouver(depot, titre_id)
    if not titre:
        abort(404)
    if any(o.get("statut") == "en_attente" for o in (titre.get("ordres_actifs") or [])):
        flash("Un ordre actif existe déjà pour ce titre — annule-le d'abord.", "error")
        return redirect(_retour(titre_id))
    if svc.marquer_ordre(depot, titre_id, ordre_id, "en_attente"):
        flash("Ordre réactivé.", "success")
    else:
        flash("Ordre introuvable.", "error")
    return redirect(_retour(titre_id))


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
        categories=CATEGORIES,
        statuts=svc.STATUTS,
        priorites=svc.PRIORITES,
        comptes=depot.charger("comptes"),
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
