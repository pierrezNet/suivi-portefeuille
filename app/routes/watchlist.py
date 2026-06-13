"""Routes : watchlist + endpoint /calendrier.ics."""

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

from app.services import titres as svc_titres
from app.services import watchlist as svc
from app.services.ics_export import generer_ics


bp = Blueprint("watchlist", __name__, url_prefix="/watchlist")


@bp.route("/", methods=["GET"])
def liste():
    depot = current_app.config["DEPOT"]
    filtres = {
        "statut": request.args.get("statut") or None,
        "priorite": request.args.get("priorite") or None,
    }
    items = svc.lister(depot, **filtres)
    titres = {t["id"]: t for t in depot.charger("titres")}
    comptes = {c["id"]: c for c in depot.charger("comptes")}
    return render_template(
        "watchlist/liste.html",
        watchlist=items,
        titres=titres,
        comptes=comptes,
        filtres=filtres,
        priorites=svc.PRIORITES,
        statuts=svc.STATUTS,
    )


def _fusionner_ordres(donnees: dict, historique_archive: list[dict]) -> list[dict]:
    """Construit la liste finale `ordres_actifs` à partir du formulaire
    (1 ordre actif au plus) + de l'historique des ordres déjà clos.

    `historique_archive` : ordres dont `statut != "en_attente"` issus de la
    base. `donnees` peut contenir `ordre_prix/quantite/validite/note/id/
    date_creation` pour l'ordre actif courant.

    Si le formulaire ne contient pas d'ordre actif mais qu'un actif existait
    en base (cas édition avec champs vidés), il est archivé en `annule`.
    """
    finaux = list(historique_archive)
    prix = (donnees.get("ordre_prix") or "").strip()
    if prix:
        finaux.append({
            "prix_limite": prix,
            "quantite": donnees.get("ordre_quantite", ""),
            "validite": donnees.get("ordre_validite", ""),
            "note": donnees.get("ordre_note", ""),
            "sens": donnees.get("ordre_sens", "achat"),
            "statut": "en_attente",
            "id": donnees.get("ordre_id") or "",
            "date_creation": donnees.get("ordre_date_creation") or "",
        })
    return finaux


@bp.route("/nouveau", methods=["GET", "POST"])
def creer():
    depot = current_app.config["DEPOT"]
    erreurs: dict[str, str] = {}
    donnees = dict(request.form) if request.method == "POST" else {}
    if request.method == "POST":
        try:
            donnees = _enrichir_paliers(donnees, request.form)
            donnees["ordres_actifs"] = _fusionner_ordres(donnees, [])
            w = svc.creer(depot, donnees)
            flash(f"« {w.get('nom') or w.get('ticker')} » ajouté à la watchlist.", "success")
            return redirect(url_for("watchlist.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs
    return render_template(
        "watchlist/formulaire.html",
        mode="creation",
        donnees=donnees,
        erreurs=erreurs,
        priorites=svc.PRIORITES,
        statuts=svc.STATUTS,
        titres=depot.charger("titres"),
        comptes=depot.charger("comptes"),
        historique=[],
        a_un_actif=bool((donnees.get("ordre_prix") or "").strip()),
    )


@bp.route("/<watch_id>/editer", methods=["GET", "POST"])
def editer(watch_id: str):
    depot = current_app.config["DEPOT"]
    item = svc.trouver(depot, watch_id)
    if not item:
        abort(404)
    erreurs: dict[str, str] = {}
    info_enrichissement: str | None = None
    if request.method == "POST":
        donnees = dict(request.form)
    else:
        # Préremplir : sérialiser les paliers en lignes texte pour le formulaire
        donnees = dict(item)
        if item.get("paliers_rachat"):
            donnees["paliers_prix"] = "\n".join(
                p.get("prix", "") for p in item["paliers_rachat"]
            )
            donnees["paliers_tranche"] = "\n".join(
                p.get("tranche", "") for p in item["paliers_rachat"]
            )
            donnees["paliers_commentaire"] = "\n".join(
                p.get("commentaire", "") for p in item["paliers_rachat"]
            )

        # Préremplir l'ordre actif courant (au plus un) + préparer l'historique
        actif = next(
            (o for o in (item.get("ordres_actifs") or [])
             if o.get("statut") == "en_attente"),
            None,
        )
        if actif:
            donnees["ordre_prix"] = str(actif.get("prix_limite", ""))
            donnees["ordre_quantite"] = str(actif.get("quantite", ""))
            donnees["ordre_validite"] = actif.get("validite", "")
            donnees["ordre_note"] = actif.get("note", "")
            donnees["ordre_sens"] = actif.get("sens", "achat")
            donnees["ordre_id"] = actif.get("id", "")
            donnees["ordre_date_creation"] = actif.get("date_creation", "")

        # Si on demande un enrichissement Yahoo, on pré-remplit les champs
        # vides sans sauvegarder. L'utilisateur vérifie puis Enregistre.
        if request.args.get("enrichir_yahoo") == "1":
            donnees, info_enrichissement = _appliquer_enrichissement_yahoo(
                donnees, item
            )

    if request.method == "POST":
        try:
            donnees = _enrichir_paliers(donnees, request.form)
            # Fusionner : ordres clos (statut != en_attente) restent intouchés,
            # l'actif est remplacé par le contenu du formulaire (ou supprimé
            # silencieusement si les champs sont vides).
            historique = [
                o for o in (item.get("ordres_actifs") or [])
                if o.get("statut") != "en_attente"
            ]
            donnees["ordres_actifs"] = _fusionner_ordres(donnees, historique)
            svc.mettre_a_jour(depot, watch_id, donnees)
            flash("Watchlist mise à jour.", "success")
            return redirect(url_for("watchlist.liste"))
        except svc.ErreursValidation as e:
            erreurs = e.erreurs

    # Historique des ordres clos, pour affichage sous le formulaire
    historique = sorted(
        [o for o in (item.get("ordres_actifs") or [])
         if o.get("statut") != "en_attente"],
        key=lambda o: o.get("date_creation", ""),
        reverse=True,
    )
    a_un_actif = any(
        o.get("statut") == "en_attente"
        for o in (item.get("ordres_actifs") or [])
    ) or bool((donnees.get("ordre_prix") or "").strip())

    return render_template(
        "watchlist/formulaire.html",
        mode="edition",
        watch_id=watch_id,
        donnees=donnees,
        erreurs=erreurs,
        priorites=svc.PRIORITES,
        statuts=svc.STATUTS,
        titres=depot.charger("titres"),
        comptes=depot.charger("comptes"),
        info_enrichissement=info_enrichissement,
        historique=historique,
        a_un_actif=a_un_actif,
    )


def _appliquer_enrichissement_yahoo(
    donnees: dict, watch: dict
) -> tuple[dict, str]:
    """Pré-remplit les champs vides du formulaire avec les données Yahoo.

    Ne touche pas aux champs déjà saisis (thèse, notes, priorité, paliers,
    cap_boursiere, etc.). Sert juste à compléter une watch incomplète.
    Renvoie (donnees_modifiees, message_info).
    """
    ticker = (watch.get("ticker") or "").strip()
    if not ticker:
        return donnees, "Pas de ticker renseigné — enrichissement impossible."

    from app.services.yahoo import enrichir_pour_titre  # lazy

    yahoo_data = enrichir_pour_titre(ticker, watch.get("marche"))
    if not yahoo_data:
        return (
            donnees,
            f"Yahoo Finance : aucune donnée trouvée pour « {ticker} » "
            f"({watch.get('marche') or 'marché non précisé'}).",
        )

    champs_remplis: list[str] = []
    # Mapping yahoo (titre) → watch
    mappings = {
        "nom": "nom",
        "marche": "marche",
        "devise": "devise",
    }
    for champ_yahoo, champ_watch in mappings.items():
        actuel = (donnees.get(champ_watch) or "").strip()
        if not actuel and yahoo_data.get(champ_yahoo):
            donnees[champ_watch] = yahoo_data[champ_yahoo]
            champs_remplis.append(champ_watch)

    # Cas spécifique cap_boursiere : on formate en Md€/M€/Md$/M$
    actuelle_cap = (donnees.get("cap_boursiere") or "").strip()
    if not actuelle_cap and yahoo_data.get("cap_boursiere_m"):
        cap_m = int(float(yahoo_data["cap_boursiere_m"]))
        devise_sym = "$" if (yahoo_data.get("devise") or "").upper() == "USD" else "€"
        if cap_m >= 1000:
            donnees["cap_boursiere"] = f"~{cap_m / 1000:.1f} Md{devise_sym}".replace(".0", "")
        else:
            donnees["cap_boursiere"] = f"~{cap_m} M{devise_sym}"
        champs_remplis.append("cap_boursiere")

    if champs_remplis:
        return (
            donnees,
            f"✓ Yahoo a complété : {', '.join(champs_remplis)}."
            " Vérifie et clique « Enregistrer » pour sauvegarder.",
        )
    return (
        donnees,
        "Yahoo n'a rien ajouté (les champs sont déjà tous renseignés).",
    )


@bp.route("/<watch_id>/ordre/<ordre_id>/reactiver", methods=["POST"])
def reactiver_ordre(watch_id: str, ordre_id: str):
    depot = current_app.config["DEPOT"]
    item = svc.trouver(depot, watch_id)
    if not item:
        abort(404)
    if any(o.get("statut") == "en_attente" for o in (item.get("ordres_actifs") or [])):
        flash(
            "Un ordre actif existe déjà pour cette position — annule-le d'abord.",
            "error",
        )
        return redirect(url_for("watchlist.editer", watch_id=watch_id))
    if svc.marquer_ordre(depot, watch_id, ordre_id, "en_attente"):
        flash("Ordre réactivé.", "success")
    else:
        flash("Ordre introuvable.", "error")
    return redirect(url_for("watchlist.editer", watch_id=watch_id))


@bp.route("/<watch_id>/supprimer", methods=["POST"])
def supprimer(watch_id: str):
    depot = current_app.config["DEPOT"]
    if svc.supprimer(depot, watch_id):
        flash("Élément retiré de la watchlist.", "success")
    else:
        flash("Élément introuvable.", "error")
    return redirect(url_for("watchlist.liste"))


@bp.route("/<watch_id>/promouvoir", methods=["POST"])
def promouvoir(watch_id: str):
    """Crée une fiche titre à partir d'une entrée watchlist et lie les deux.

    Si le ticker + marché sont présents, tente l'enrichissement Yahoo
    automatiquement (best effort, n'échoue pas si Yahoo indispo).
    """
    depot = current_app.config["DEPOT"]
    watch = svc.trouver(depot, watch_id)
    if not watch:
        abort(404)

    if watch.get("titre_id"):
        flash(
            "Cette entrée est déjà liée à un titre du catalogue.",
            "error",
        )
        return redirect(url_for("watchlist.liste"))

    ticker = (watch.get("ticker") or "").strip()
    nom = (watch.get("nom") or "").strip()
    if not ticker and not nom:
        flash(
            "Impossible de promouvoir : la watch n'a ni ticker ni nom.",
            "error",
        )
        return redirect(url_for("watchlist.liste"))

    # 1. Champs de base depuis la watch
    dict_titre: dict = {"ticker": ticker, "nom": nom or ticker}
    for c in ("marche", "devise", "these_lt"):
        v = (watch.get(c) or "").strip() if isinstance(watch.get(c), str) else watch.get(c)
        if v:
            dict_titre[c] = v

    # 2. Enrichissement Yahoo best-effort
    yahoo_ok = False
    if ticker:
        from app.services.yahoo import enrichir_pour_titre  # lazy

        yahoo_data = enrichir_pour_titre(ticker, watch.get("marche"))
        if yahoo_data:
            yahoo_ok = True
            # Merge sélectif : les champs déjà présents dans la watch priment
            # (ex : marche/devise saisis manuellement), Yahoo complète le reste.
            for c in (
                "isin",
                "secteur",
                "site_ir",
                "verse_dividende",
                "frequence_dividende",
                "dividende_par_action",
                "cap_boursiere_m",
                "dette_nette_m",
                "valeur_entreprise_m",
            ):
                if c in yahoo_data and yahoo_data[c] not in (None, ""):
                    dict_titre[c] = yahoo_data[c]
            # marche / devise / nom : on prend Yahoo si la watch ne l'a pas
            for c in ("marche", "devise", "nom"):
                if not dict_titre.get(c) and yahoo_data.get(c):
                    dict_titre[c] = yahoo_data[c]

    # 3. Création du titre (collision ID → suffixe -2 automatique)
    try:
        titre = svc_titres.creer(depot, dict_titre)
    except svc_titres.ErreursValidation as e:
        flash(f"Création du titre refusée : {e}", "error")
        return redirect(url_for("watchlist.liste"))

    # 4. Lien watch → titre
    nouveau_watch = dict(watch)
    nouveau_watch["titre_id"] = titre["id"]
    try:
        svc.mettre_a_jour(depot, watch_id, nouveau_watch)
    except svc.ErreursValidation as e:
        flash(
            f"Titre {titre['id']} créé mais lien watch échoué : {e}",
            "error",
        )
        return redirect(url_for("titres.detail", titre_id=titre["id"]))

    msg = f"Titre {titre['ticker']} créé"
    if yahoo_ok:
        msg += " et enrichi via Yahoo"
    msg += f". Watch reliée."
    flash(msg, "success")
    return redirect(url_for("titres.detail", titre_id=titre["id"]))


@bp.route("/<watch_id>/ordre/<ordre_id>/annuler", methods=["POST"])
def annuler_ordre(watch_id: str, ordre_id: str):
    """Marque un ordre comme annulé sans créer de mouvement."""
    depot = current_app.config["DEPOT"]
    if svc.marquer_ordre(depot, watch_id, ordre_id, "annule"):
        flash("Ordre marqué comme annulé.", "success")
    else:
        flash("Ordre introuvable ou déjà annulé.", "error")
    return redirect(url_for("watchlist.liste"))


def _enrichir_paliers(donnees: dict, form) -> dict:
    """Repasse les champs paliers_* et ordres_* bruts depuis le form."""
    sortie = dict(donnees)
    for c in (
        "paliers_prix", "paliers_tranche", "paliers_commentaire",
        "ordres_prix", "ordres_quantite", "ordres_validite", "ordres_note",
        "ordres_id", "ordres_statut", "ordres_date_creation", "ordres_mouvement_id",
    ):
        sortie[c] = form.get(c, donnees.get(c, ""))
    return sortie


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
