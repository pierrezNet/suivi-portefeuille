"""Service virements & investissements programmés : engagements récurrents
qui doivent apparaître automatiquement dans le journal sans saisie manuelle.

Deux cas selon le champ `titre_id` :
  - **Sans `titre_id`** : virement bancaire pur (alimentation cash). Le
    rattrapage crée un mouvement `alimentation_cash`.
  - **Avec `titre_id`** : investissement programmé (DCA Amundi par ex.). Le
    rattrapage crée un événement-rappel ; l'utilisateur saisira le vrai
    mouvement d'achat a posteriori (quantité et prix unitaire connus
    seulement après lecture du relevé broker).

Idempotence : ID déterministe — `auto-{vp_id}-{YYYY-MM-DD}` pour les
mouvements cash, `e-dca-{vp_id}-{YYYY-MM-DD}` pour les événements DCA.

Périodicité : `mensuel` (défaut, rétrocompat), `trimestriel`, `semestriel`,
`annuel`, `one_shot` (une seule échéance, la première qui matche).
Si le jour saisi n'existe pas dans un mois (ex : 31 février), on retombe
sur le dernier jour du mois.
"""

from __future__ import annotations

import calendar
import re
import uuid
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from app.services.stockage import Depot


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PERIODICITES = ("mensuel", "trimestriel", "semestriel", "annuel", "one_shot")

# Pas en mois pour les périodicités récurrentes
_PAS_MOIS = {
    "mensuel": 1,
    "trimestriel": 3,
    "semestriel": 6,
    "annuel": 12,
}

# Libellés humains pour les événements DCA
_LIBELLES_PERIODICITE = {
    "mensuel": "mois",
    "trimestriel": "trimestre",
    "semestriel": "semestre",
    "annuel": "an",
    "one_shot": "one-shot",
}


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _valider_date(v, *, optionnelle: bool = False) -> str | None:
    s = _str_propre(v)
    if not s:
        if optionnelle:
            return None
        raise ValueError("date requise")
    if not ISO_DATE.match(s):
        raise ValueError("format attendu YYYY-MM-DD")
    try:
        _date.fromisoformat(s)
    except ValueError:
        raise ValueError("date invalide")
    return s


def _normaliser(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    compte_id = _str_propre(donnees.get("compte_id"))
    if not compte_id:
        erreurs["compte_id"] = "obligatoire"
    else:
        ids_comptes = {c["id"] for c in depot.charger("comptes")}
        if compte_id not in ids_comptes:
            erreurs["compte_id"] = "compte inconnu"
        else:
            out["compte_id"] = compte_id

    try:
        montant = Decimal(_str_propre(donnees.get("montant")).replace(",", "."))
        if montant <= 0:
            erreurs["montant"] = "doit être strictement positif"
        else:
            out["montant"] = str(montant)
    except InvalidOperation:
        erreurs["montant"] = "nombre invalide"

    out["devise"] = (_str_propre(donnees.get("devise")) or "EUR").upper()

    try:
        jour = int(donnees.get("jour_du_mois", 0))
        if not (1 <= jour <= 31):
            erreurs["jour_du_mois"] = "doit être entre 1 et 31"
        else:
            out["jour_du_mois"] = jour
    except (TypeError, ValueError):
        erreurs["jour_du_mois"] = "nombre invalide"

    periodicite = _str_propre(donnees.get("periodicite")) or "mensuel"
    if periodicite not in PERIODICITES:
        erreurs["periodicite"] = f"valeur attendue parmi {', '.join(PERIODICITES)}"
    else:
        out["periodicite"] = periodicite

    titre_id = _str_propre(donnees.get("titre_id"))
    if titre_id:
        ids_titres = {t["id"] for t in depot.charger("titres")}
        if titre_id not in ids_titres:
            erreurs["titre_id"] = "titre inconnu"
        else:
            out["titre_id"] = titre_id

    out["libelle"] = _str_propre(donnees.get("libelle")) or "Virement programmé"
    out["notes"] = _str_propre(donnees.get("notes"))

    try:
        out["date_debut"] = _valider_date(donnees.get("date_debut"))
    except ValueError as e:
        erreurs["date_debut"] = str(e)

    try:
        date_fin = _valider_date(donnees.get("date_fin"), optionnelle=True)
        if date_fin:
            out["date_fin"] = date_fin
    except ValueError as e:
        erreurs["date_fin"] = str(e)

    actif_raw = donnees.get("actif")
    if isinstance(actif_raw, bool):
        out["actif"] = actif_raw
    elif _str_propre(actif_raw).lower() in ("0", "false", "off", "non"):
        out["actif"] = False
    else:
        out["actif"] = True

    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(depot: Depot, *, seulement_actifs: bool = False) -> list[dict]:
    items = depot.charger("virements_programmes")
    if seulement_actifs:
        items = [v for v in items if v.get("actif", True)]
    items.sort(key=lambda v: (v.get("compte_id", ""), v.get("date_debut", "")))
    return items


def trouver(depot: Depot, vp_id: str) -> dict | None:
    for v in depot.charger("virements_programmes"):
        if v.get("id") == vp_id:
            return v
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    item = _normaliser(depot, donnees)
    item["id"] = "vp-" + uuid.uuid4().hex[:10]
    item["date_creation"] = _date.today().isoformat()
    items = depot.charger("virements_programmes")
    items.append(item)
    depot.enregistrer("virements_programmes", items)
    return item


def mettre_a_jour(depot: Depot, vp_id: str, donnees: dict) -> dict:
    items = depot.charger("virements_programmes")
    for i, v in enumerate(items):
        if v.get("id") != vp_id:
            continue
        nouveau = _normaliser(depot, donnees)
        nouveau["id"] = vp_id
        nouveau["date_creation"] = v.get("date_creation") or _date.today().isoformat()
        items[i] = nouveau
        depot.enregistrer("virements_programmes", items)
        return nouveau
    raise KeyError(vp_id)


def supprimer(depot: Depot, vp_id: str) -> bool:
    items = depot.charger("virements_programmes")
    nouveau = [v for v in items if v.get("id") != vp_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("virements_programmes", nouveau)
    return True


# ---------------------------------------------------------------------------
# Rattrapage : génération des mouvements manquants
# ---------------------------------------------------------------------------


def _dates_echeance(
    date_debut: _date,
    date_fin: _date,
    jour: int,
    periodicite: str = "mensuel",
) -> list[_date]:
    """Renvoie les dates d'échéance entre date_debut et date_fin (incl.) pour
    le `jour` du mois, selon la périodicité. Si le mois a moins de jours,
    retombe sur le dernier jour.

    Pour `one_shot` : une seule échéance, la première qui matche (peut être
    `date_debut` même si jour saisi != jour de date_debut).
    """
    if date_fin < date_debut:
        return []
    if periodicite == "one_shot":
        # Premier candidat à partir de date_debut au jour saisi
        annee, mois = date_debut.year, date_debut.month
        nb_jours = calendar.monthrange(annee, mois)[1]
        jour_effectif = min(jour, nb_jours)
        candidate = _date(annee, mois, jour_effectif)
        if candidate < date_debut:
            # Premier candidat dans le mois suivant
            mois += 1
            if mois == 13:
                annee += 1
                mois = 1
            nb_jours = calendar.monthrange(annee, mois)[1]
            jour_effectif = min(jour, nb_jours)
            candidate = _date(annee, mois, jour_effectif)
        if candidate > date_fin:
            return []
        return [candidate]

    pas = _PAS_MOIS.get(periodicite, 1)
    echeances: list[_date] = []
    annee, mois = date_debut.year, date_debut.month
    while True:
        nb_jours = calendar.monthrange(annee, mois)[1]
        jour_effectif = min(jour, nb_jours)
        candidate = _date(annee, mois, jour_effectif)
        if candidate > date_fin:
            break
        if candidate >= date_debut:
            echeances.append(candidate)
        # Mois suivant selon le pas
        mois += pas
        while mois > 12:
            annee += 1
            mois -= 12
    return echeances


def rattraper(depot: Depot, *, jusqu_a: _date | None = None) -> list[dict]:
    """Crée les artefacts manquants pour tous les programmes actifs, jusqu'à
    `jusqu_a` (inclus, défaut aujourd'hui).

    Selon le programme :
      - sans `titre_id` : mouvement `alimentation_cash` (ID `auto-{vp_id}-{date}`)
      - avec `titre_id` : événement `rappel_personnel` (ID `e-dca-{vp_id}-{date}`)

    Idempotent : un artefact dont l'ID existe déjà est ignoré.
    Renvoie la liste fusionnée des artefacts créés (mouvements + événements).
    """
    if jusqu_a is None:
        jusqu_a = _date.today()

    programmes = [v for v in depot.charger("virements_programmes") if v.get("actif", True)]
    if not programmes:
        return []

    mouvements = depot.charger("mouvements")
    evenements = depot.charger("evenements")
    titres_par_id = {t["id"]: t for t in depot.charger("titres")}
    ids_mvt_existants = {m.get("id") for m in mouvements}
    ids_evt_existants = {e.get("id") for e in evenements}

    nouveaux_mvt: list[dict] = []
    nouveaux_evt: list[dict] = []

    for vp in programmes:
        date_debut_str = vp.get("date_debut")
        if not date_debut_str:
            continue
        try:
            date_debut = _date.fromisoformat(date_debut_str)
        except ValueError:
            continue
        try:
            date_fin = _date.fromisoformat(vp["date_fin"]) if vp.get("date_fin") else jusqu_a
        except ValueError:
            date_fin = jusqu_a
        date_fin = min(date_fin, jusqu_a)
        jour = int(vp.get("jour_du_mois", 1))
        periodicite = vp.get("periodicite") or "mensuel"
        titre_id = vp.get("titre_id")

        for echeance in _dates_echeance(date_debut, date_fin, jour, periodicite):
            if titre_id:
                evt_id = f"e-dca-{vp['id']}-{echeance.isoformat()}"
                if evt_id in ids_evt_existants:
                    continue
                titre = titres_par_id.get(titre_id, {})
                ticker = titre.get("ticker") or titre.get("nom") or titre_id
                periode_label = _LIBELLES_PERIODICITE.get(periodicite, periodicite)
                evt = {
                    "id": evt_id,
                    "type": "rappel_personnel",
                    "titre_id": titre_id,
                    "date": echeance.isoformat(),
                    "libelle": (
                        f"DCA {ticker} : {vp['montant']} €/{periode_label} "
                        f"— saisir le mouvement réel"
                    ),
                    "notes": (
                        "[investissement programmé auto] "
                        + (vp.get("notes", "") or "")
                    ).strip(),
                    "virement_programme_id": vp["id"],
                }
                nouveaux_evt.append(evt)
                ids_evt_existants.add(evt_id)
            else:
                mvt_id = f"auto-{vp['id']}-{echeance.isoformat()}"
                if mvt_id in ids_mvt_existants:
                    continue
                mvt = {
                    "id": mvt_id,
                    "type": "alimentation_cash",
                    "compte_id": vp["compte_id"],
                    "date": echeance.isoformat(),
                    "montant": vp["montant"],
                    "devise": vp.get("devise", "EUR"),
                    "libelle": vp.get("libelle", "Virement programmé"),
                    "notes": (
                        "[programmé auto] " + (vp.get("notes", "") or "")
                    ).strip(),
                    "virement_programme_id": vp["id"],
                }
                nouveaux_mvt.append(mvt)
                ids_mvt_existants.add(mvt_id)

    if nouveaux_mvt:
        mouvements.extend(nouveaux_mvt)
        mouvements.sort(key=lambda m: (m.get("date", ""), m.get("id", "")))
        depot.enregistrer("mouvements", mouvements)
    if nouveaux_evt:
        evenements.extend(nouveaux_evt)
        evenements.sort(key=lambda e: (e.get("date", ""), e.get("id", "")))
        depot.enregistrer("evenements", evenements)
    return nouveaux_mvt + nouveaux_evt
