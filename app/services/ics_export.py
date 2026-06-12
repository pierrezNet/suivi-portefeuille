"""Génération du calendrier iCalendar (.ics).

Inclut :
  - Tous les événements enregistrés (publications, dividendes, AG, rappels).
  - Les échéances de décisions issues de la watchlist (`echeance_abandon`).
  - Une mention courte de la thèse / des notes dans la description.

Les UID sont stables pour permettre la mise à jour côté client lors du re-fetch
de l'abonnement (GNOME Calendar, Thunderbird, etc.).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta, timezone

from icalendar import Alarm, Calendar, Event

from app.services.evenements import LIBELLES_TYPES
from app.services.stockage import Depot


CAL_PROD_ID = "-//Suivi Portefeuille//FR"
DOMAINE_UID = "suivi-portefeuille.local"


# Délai (en jours) avant l'événement pour le rappel calendrier (VALARM).
# Le calendrier natif de l'utilisateur (GNOME / Apple / Thunderbird) déclenchera
# une notification à T-N. None = pas de rappel.
RAPPELS_PAR_TYPE_EVT = {
    "rappel_personnel": 2,          # surtout les rappels DCA
    "publication_resultats": 1,
    "detachement_dividende": 1,
    "versement_dividende": 1,
    "assemblee_generale": 1,
    "autre": 1,
}
RAPPEL_ORDRE_LIMITE_JOURS = 2
RAPPEL_ECHEANCE_WATCHLIST_JOURS = 1


def _parse_iso_date(s: str) -> _date | None:
    if not s:
        return None
    try:
        return _date.fromisoformat(s)
    except ValueError:
        return None


def _ajouter_evenement(
    cal: Calendar,
    *,
    uid: str,
    date_evt: _date,
    sommaire: str,
    description: str,
    categorie: str,
    rappel_jours: int | None = None,
) -> None:
    e = Event()
    e.add("uid", f"{uid}@{DOMAINE_UID}")
    # All-day event
    e.add("dtstart", date_evt)
    e.add("dtend", date_evt)
    e.add("summary", sommaire)
    if description:
        e.add("description", description)
    e.add("categories", [categorie])
    e.add("dtstamp", datetime.now(tz=timezone.utc))
    if rappel_jours is not None and rappel_jours > 0:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", sommaire)
        alarm.add("trigger", timedelta(days=-rappel_jours))
        e.add_component(alarm)
    cal.add_component(e)


def construire_calendrier(depot: Depot) -> Calendar:
    cal = Calendar()
    cal.add("prodid", CAL_PROD_ID)
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Suivi Portefeuille")
    cal.add("x-wr-caldesc", "Événements et échéances de mon portefeuille")

    titres = {t["id"]: t for t in depot.charger("titres")}

    # 1. Événements explicites
    for e in depot.charger("evenements"):
        d = _parse_iso_date(e.get("date"))
        if d is None:
            continue
        sommaire = e.get("libelle") or LIBELLES_TYPES.get(
            e.get("type", "autre"), "Événement"
        )
        if (tid := e.get("titre_id")) and tid in titres:
            ticker = titres[tid].get("ticker") or tid
            sommaire = f"[{ticker}] {sommaire}"
        description_parts = []
        if e.get("type"):
            description_parts.append(
                "Type : " + LIBELLES_TYPES.get(e["type"], e["type"])
            )
        if e.get("notes"):
            description_parts.append(e["notes"])
        type_evt = e.get("type") or "autre"
        rappel = RAPPELS_PAR_TYPE_EVT.get(type_evt)
        _ajouter_evenement(
            cal,
            uid=f"evt-{e.get('id') or e.get('libelle','sans-id')}",
            date_evt=d,
            sommaire=sommaire,
            description="\n\n".join(description_parts),
            categorie=type_evt,
            rappel_jours=rappel,
        )

    # 2. Échéances watchlist
    for w in depot.charger("watchlist"):
        d = _parse_iso_date(w.get("echeance_abandon"))
        if d is None:
            continue
        nom = w.get("nom") or w.get("ticker") or "Surveillance"
        sommaire = f"[Watchlist] Réévaluer : {nom}"
        description_parts = []
        if w.get("these_lt"):
            description_parts.append(w["these_lt"])
        if w.get("notes"):
            description_parts.append(w["notes"])
        if w.get("paliers_rachat"):
            paliers = ", ".join(
                f"{p.get('prix')}€ ({p.get('tranche')})"
                for p in w["paliers_rachat"]
            )
            description_parts.append("Paliers : " + paliers)
        _ajouter_evenement(
            cal,
            uid=f"watch-{w.get('id', nom)}",
            date_evt=d,
            sommaire=sommaire,
            description="\n\n".join(description_parts),
            categorie="echeance_watchlist",
            rappel_jours=RAPPEL_ECHEANCE_WATCHLIST_JOURS,
        )

    # 3. Ordres d'achat actifs en attente
    for w in depot.charger("watchlist"):
        for ordre in w.get("ordres_actifs") or []:
            if ordre.get("statut") != "en_attente":
                continue
            d = _parse_iso_date(ordre.get("validite"))
            if d is None:
                continue
            ticker = w.get("ticker") or ""
            nom = w.get("nom") or ticker or "—"
            devise = (w.get("devise") or "EUR").upper()
            symbole = "$" if devise == "USD" else ("€" if devise == "EUR" else devise)
            sommaire_parts = []
            if ticker:
                sommaire_parts.append(f"[{ticker}]")
            sommaire_parts.append(
                f"Validité ordre {ordre.get('prix_limite')} {symbole}"
                f" × {ordre.get('quantite')}"
            )
            description_parts = [
                f"Ordre d'achat actif sur {nom}",
                f"Prix limite : {ordre.get('prix_limite')} {symbole}",
                f"Quantité : {ordre.get('quantite')}",
            ]
            if ordre.get("note"):
                description_parts.append(ordre["note"])
            _ajouter_evenement(
                cal,
                uid=f"ordre-{w.get('id', '?')}-{ordre.get('id', '?')}",
                date_evt=d,
                sommaire=" ".join(sommaire_parts),
                description="\n\n".join(description_parts),
                categorie="ordre_achat_actif",
                rappel_jours=RAPPEL_ORDRE_LIMITE_JOURS,
            )

    return cal


def generer_ics(depot: Depot) -> bytes:
    return construire_calendrier(depot).to_ical()
