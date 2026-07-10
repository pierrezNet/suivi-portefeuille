"""Construction du dictionnaire d'agrégats utilisé par le dashboard.

Ce module factorise la logique qui produit la donnée affichée sur le tableau
de bord (route `dashboard.index`) ET sur l'export mobile statique
(`tools/publier_dashboard.py`). Il appelle uniquement les services métier
existants — aucun nouveau calcul.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from app.services import fiscal, predictions, repartition, snapshots, virements_programmes
from app.services.evenements import LIBELLES_TYPES as LIBELLES_EVENEMENT
from app.services.evenements import lister as lister_evenements
from app.services.pru import calculer_pru
from app.services.soldes import (
    calculer_positions,
    calculer_ventilation_cash,
)
from app.services.stockage import Depot
from app.services.watchlist import lister as lister_watchlist
from app.services.watchlist import reserve_cash_par_compte


JOURS_AGENDA_DEFAUT = 60

# Seuil au-delà duquel on affiche un bandeau « cours à actualiser ».
AGE_COURS_ALERTE_JOURS = 7


def _decimal_safe(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def valoriser_position(
    titre: dict | None,
    quantite: Decimal,
    pru: Decimal | None,
    *,
    today: _date,
) -> dict:
    """Calcule valo / PV latente / âge du cours pour UNE position.

    Renvoie toujours toutes les clés (`valo_eur`, `pv_latente_eur`,
    `cours_jour_eur`, `age_jours` peuvent être None si pas de cours).
    """
    cours = _decimal_safe((titre or {}).get("cours_jour_eur"))
    date_cours = (titre or {}).get("date_cours_jour")
    age_jours: int | None = None
    if date_cours:
        try:
            age_jours = (today - _date.fromisoformat(date_cours)).days
        except ValueError:
            age_jours = None
    valo: Decimal | None = None
    pv_latente: Decimal | None = None
    if cours is not None and quantite is not None:
        valo = (quantite * cours).quantize(Decimal("0.01"))
        if pru is not None:
            pv_latente = (quantite * (cours - pru)).quantize(Decimal("0.01"))
    return {
        "cours_jour_eur": cours,
        "age_jours": age_jours,
        "valo_eur": valo,
        "pv_latente_eur": pv_latente,
    }


def construire(
    depot: Depot,
    *,
    rattraper_virements: bool = True,
    jours_agenda: int = JOURS_AGENDA_DEFAUT,
    aujourd_hui: _date | None = None,
) -> dict:
    """Retourne le dict complet utilisé par le dashboard.

    Args:
        depot: dépôt JSON.
        rattraper_virements: si True, lance le rattrapage des virements
            programmés avant de calculer (par défaut True ; le script
            d'export peut souhaiter le désactiver pour rester en lecture pure).
        jours_agenda: horizon de l'agenda en jours (défaut 60).
        aujourd_hui: date de référence (utile pour les tests).
    """
    today = aujourd_hui or _date.today()
    virements_rattrapes = (
        virements_programmes.rattraper(depot, jusqu_a=today)
        if rattraper_virements
        else []
    )

    comptes = depot.charger("comptes")
    titres = {t["id"]: t for t in depot.charger("titres")}
    mouvements = depot.charger("mouvements")
    watchlist_brut = depot.charger("watchlist")
    # Cash « réservé » par les ordres d'achat en attente, par compte.
    reserve_par_compte = reserve_cash_par_compte(
        watchlist_brut, today_iso=today.isoformat()
    )

    annee_courante = today.year

    # Comptes : soldes cash + positions avec PRU + valorisation au jour J
    vue_comptes = []
    total_cash = Decimal("0.00")
    total_valo_titres = Decimal("0.00")
    total_pv_latente = Decimal("0.00")
    total_reserve_ordres = Decimal("0.00")
    nb_positions_sans_cours = 0
    age_cours_max_jours: int | None = None
    for compte in comptes:
        ventilation = calculer_ventilation_cash(mouvements, compte["id"])
        solde = ventilation["solde"]
        positions = calculer_positions(mouvements, compte["id"])
        positions_vue = []
        valo_compte = Decimal("0.00")
        pv_latente_compte = Decimal("0.00")
        for tid, q in sorted(positions.items()):
            pru = calculer_pru(mouvements, compte["id"], tid)
            v = valoriser_position(titres.get(tid), q, pru, today=today)
            positions_vue.append(
                {
                    "titre_id": tid,
                    "ticker": titres.get(tid, {}).get("ticker", tid),
                    "nom": titres.get(tid, {}).get("nom", tid),
                    "quantite": q,
                    "pru": pru,
                    "cours_jour_eur": v["cours_jour_eur"],
                    "valo_eur": v["valo_eur"],
                    "pv_latente_eur": v["pv_latente_eur"],
                    "age_jours": v["age_jours"],
                }
            )
            if v["valo_eur"] is not None:
                valo_compte += v["valo_eur"]
            else:
                nb_positions_sans_cours += 1
            if v["pv_latente_eur"] is not None:
                pv_latente_compte += v["pv_latente_eur"]
            if v["age_jours"] is not None:
                age_cours_max_jours = (
                    v["age_jours"] if age_cours_max_jours is None
                    else max(age_cours_max_jours, v["age_jours"])
                )
        reserve = reserve_par_compte.get(
            compte["id"], {"total": Decimal("0.00"), "ordres": []}
        )
        disponible = (solde - reserve["total"]).quantize(Decimal("0.01"))
        total_cash += solde
        total_valo_titres += valo_compte
        total_pv_latente += pv_latente_compte
        total_reserve_ordres += reserve["total"]
        vue_comptes.append(
            {
                "compte": compte,
                "solde_cash": solde,
                "valo_titres_eur": valo_compte,
                "pv_latente_eur": pv_latente_compte,
                "total_eur": solde + valo_compte,
                "positions": positions_vue,
                "tresorerie": {
                    "versements": ventilation["versements"],
                    "ventes": ventilation["ventes"],
                    "dividendes": ventilation["dividendes"],
                    "achats": ventilation["achats"],
                    "frais": ventilation["frais"],
                    "retraits": ventilation["retraits"],
                    "solde_especes": solde,
                    "reserve_total": reserve["total"],
                    "ordres_reserve": reserve["ordres"],
                    "disponible_comptant": disponible,
                },
            }
        )
    total_portefeuille = total_cash + total_valo_titres
    total_disponible_comptant = (
        total_cash - total_reserve_ordres
    ).quantize(Decimal("0.01"))
    cours_a_actualiser = (
        nb_positions_sans_cours > 0
        or (age_cours_max_jours is not None and age_cours_max_jours > AGE_COURS_ALERTE_JOURS)
    )

    # Stats annuelles globales (année en cours)
    stats_annee = fiscal.stats_globales_annee(
        mouvements, comptes, annee_courante
    )["cumul"]

    # Agenda : événements + échéances watchlist dans les jours à venir
    horizon = (today + timedelta(days=jours_agenda)).isoformat()
    today_iso = today.isoformat()

    evenements_a_venir = lister_evenements(
        depot, date_debut=today_iso, date_fin=horizon
    )
    echeances_watch = [
        w
        for w in watchlist_brut
        if (w.get("echeance_abandon") or "")
        and today_iso <= w["echeance_abandon"] <= horizon
    ]

    agenda = []
    for e in evenements_a_venir:
        agenda.append(
            {
                "date": e["date"],
                "type_libelle": LIBELLES_EVENEMENT.get(
                    e.get("type", "autre"), e.get("type", "autre")
                ),
                "ticker": (titres.get(e.get("titre_id"), {}).get("ticker")),
                "libelle": e["libelle"],
                "notes": e.get("notes", ""),
                "kind": "evenement",
            }
        )
    for w in echeances_watch:
        nom = w.get("nom") or w.get("ticker") or "Surveillance"
        agenda.append(
            {
                "date": w["echeance_abandon"],
                "type_libelle": "Échéance watchlist",
                "ticker": w.get("ticker"),
                "libelle": f"Réévaluer : {nom}",
                "notes": w.get("these_lt", ""),
                "kind": "echeance",
            }
        )

    # Ordres actifs (achat ou vente) en attente dont la validité tombe dans l'horizon
    for w in watchlist_brut:
        for ordre in w.get("ordres_actifs") or []:
            if ordre.get("statut") != "en_attente":
                continue
            validite = ordre.get("validite") or ""
            if not validite or not (today_iso <= validite <= horizon):
                continue
            ticker = w.get("ticker") or ""
            nom = w.get("nom") or ticker or "—"
            devise = (w.get("devise") or "EUR").upper()
            symbole = "$" if devise == "USD" else ("€" if devise == "EUR" else devise)
            est_vente = ordre.get("sens") == "vente"
            agenda.append(
                {
                    "date": validite,
                    "type_libelle": "Ordre de vente actif" if est_vente else "Ordre d'achat actif",
                    "ticker": ticker,
                    "libelle": (
                        f"Validité ordre {nom} — {ordre.get('prix_limite')} "
                        f"{symbole} × {ordre.get('quantite')}"
                    ),
                    "notes": ordre.get("note", ""),
                    "kind": "ordre_actif",
                }
            )

    agenda.sort(key=lambda i: i["date"])

    # Rappel LECTURE SEULE : tous les ordres limites actifs (achat ET vente),
    # sans filtre d'horizon — pour se rappeler ses ordres sans ouvrir le broker.
    ordres_actifs: list[dict] = []
    for w in watchlist_brut:
        for ordre in w.get("ordres_actifs") or []:
            if ordre.get("statut") != "en_attente":
                continue
            ordres_actifs.append({
                "ticker": w.get("ticker") or "",
                "nom": w.get("nom") or w.get("ticker") or "—",
                "sens": ordre.get("sens") or "achat",
                "prix_limite": ordre.get("prix_limite"),
                "quantite": ordre.get("quantite"),
                "validite": ordre.get("validite") or "",
                "note": ordre.get("note", ""),
                "devise": (w.get("devise") or "EUR").upper(),
            })
    ordres_actifs.sort(key=lambda o: o.get("validite") or "9999")

    # Rappel LECTURE SEULE : prédictions en cours (paris datés non encore évalués).
    predictions_en_cours = [
        {
            "ticker": p.get("ticker") or "",
            "nom": p.get("nom") or p.get("ticker") or "—",
            "sens": p.get("sens"),
            "cours_reference": p.get("cours_reference"),
            "date_echeance": p.get("date_echeance") or "",
            "conviction": p.get("conviction"),
            "horizon_jours": p.get("horizon_jours"),
            "devise": (p.get("devise") or "EUR").upper(),
            "raisonnement": p.get("raisonnement", ""),
        }
        for p in predictions.lister(depot, statut="en_cours")
    ]

    # Watchlist priorité haute (max 6)
    watchlist_haute = lister_watchlist(depot, priorite="haute")[:6]

    # Série mensuelle pour la courbe d'équity (24 derniers mois)
    points_equity = snapshots.serie_points(depot)
    coords_equity = snapshots.coordonnees_svg(points_equity)

    # Répartitions pour les camemberts d'allocation
    repartitions = {}
    coords_camemberts = {}
    for axe in repartition.AXES:
        parts = repartition.repartition_par_axe(vue_comptes, titres, axe)
        repartitions[axe] = parts
        coords_camemberts[axe] = repartition.coordonnees_camembert(parts)

    return {
        "comptes": vue_comptes,
        "total_cash": total_cash,
        "total_disponible_comptant": total_disponible_comptant,
        "total_reserve_ordres": total_reserve_ordres,
        "total_valo_titres": total_valo_titres,
        "total_pv_latente": total_pv_latente,
        "total_portefeuille": total_portefeuille,
        "nb_positions_sans_cours": nb_positions_sans_cours,
        "age_cours_max_jours": age_cours_max_jours,
        "cours_a_actualiser": cours_a_actualiser,
        "nb_titres": len(titres),
        "nb_mouvements": len(mouvements),
        "annee_courante": annee_courante,
        "stats_annee": stats_annee,
        "agenda": agenda,
        "agenda_horizon_jours": jours_agenda,
        "ordres_actifs": ordres_actifs,
        "predictions_en_cours": predictions_en_cours,
        "watchlist_haute": watchlist_haute,
        "titres": titres,
        "virements_rattrapes": virements_rattrapes,
        "equity_points": points_equity,
        "equity_coords": coords_equity,
        "repartitions": repartitions,
        "coords_camemberts": coords_camemberts,
    }
