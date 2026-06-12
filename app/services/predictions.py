"""Service prédictions : journal de paris directionnels sans capital engagé.

Une prédiction note un avis daté (hausse / baisse) sur un titre, à un horizon
donné. Aucun ordre, aucune position : l'objectif est de calibrer la qualité
du jugement en mesurant a posteriori le pourcentage de prédictions justes.

Cours saisis manuellement (cohérent avec le choix 100 % offline du projet).
"""

from __future__ import annotations

import re
import uuid
from datetime import date as _date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.services.stockage import Depot


SENS = ("hausse", "baisse")
STATUTS = ("en_cours", "evaluee")
RESULTATS = ("juste", "faux")

LIBELLES_SENS = {"hausse": "Hausse", "baisse": "Baisse"}
LIBELLES_STATUTS = {"en_cours": "En cours", "evaluee": "Évaluée"}
LIBELLES_RESULTATS = {"juste": "Juste", "faux": "Faux"}

CONVICTIONS = (1, 2, 3, 4, 5)

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


# --- Helpers de parsing / validation -----------------------------------------


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _parse_decimal_strict_positif(valeur) -> Decimal:
    s = _str_propre(valeur).replace(",", ".")
    if not s:
        raise ValueError("valeur requise")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError("nombre invalide")
    if d <= 0:
        raise ValueError("doit être strictement positif")
    return d


def _parse_int_positif(valeur) -> int:
    s = _str_propre(valeur)
    if not s:
        raise ValueError("valeur requise")
    try:
        n = int(s)
    except ValueError:
        raise ValueError("entier invalide")
    if n <= 0:
        raise ValueError("doit être strictement positif")
    return n


def _valider_date(v) -> str:
    s = _str_propre(v)
    if not s or not ISO_DATE.match(s):
        raise ValueError("format attendu YYYY-MM-DD")
    try:
        _date.fromisoformat(s)
    except ValueError:
        raise ValueError("date invalide")
    return s


def _calcul_ecart_pct(cours_reference: Decimal, cours_echeance: Decimal) -> Decimal:
    """Variation en pourcentage arrondie à 2 décimales (ROUND_HALF_UP)."""
    brut = (cours_echeance - cours_reference) / cours_reference * Decimal("100")
    return brut.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _resultat_pour(sens: str, cours_reference: Decimal, cours_echeance: Decimal) -> str:
    """Une égalité stricte est traitée comme un "faux" par convention :
    une prédiction de mouvement non confirmée par un mouvement est fausse."""
    if sens == "hausse":
        return "juste" if cours_echeance > cours_reference else "faux"
    return "juste" if cours_echeance < cours_reference else "faux"


# --- Normalisation à la création --------------------------------------------


def _normaliser_creation(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    # Sens
    sens = _str_propre(donnees.get("sens")).lower()
    if not sens:
        erreurs["sens"] = "obligatoire"
    elif sens not in SENS:
        erreurs["sens"] = f"valeur attendue parmi {', '.join(SENS)}"
    else:
        out["sens"] = sens

    # Date de prédiction
    try:
        out["date_prediction"] = _valider_date(donnees.get("date_prediction"))
    except ValueError as e:
        erreurs["date_prediction"] = str(e)

    # Date cible (échéance) — saisie directement, doit être > date_prediction
    try:
        out["date_echeance"] = _valider_date(donnees.get("date_echeance"))
    except ValueError as e:
        erreurs["date_echeance"] = str(e)

    if "date_prediction" in out and "date_echeance" in out:
        if out["date_echeance"] <= out["date_prediction"]:
            erreurs["date_echeance"] = "doit être postérieure à la date de prédiction"

    # Cours de référence
    try:
        cours = _parse_decimal_strict_positif(donnees.get("cours_reference"))
        out["cours_reference"] = str(cours)
    except ValueError as e:
        erreurs["cours_reference"] = str(e)

    # Conviction
    try:
        c = _parse_int_positif(donnees.get("conviction"))
        if c not in CONVICTIONS:
            raise ValueError("valeur attendue entre 1 et 5")
        out["conviction"] = c
    except ValueError as e:
        erreurs["conviction"] = str(e)

    # titre_id : optionnel ; si fourni, doit exister
    titre_id = _str_propre(donnees.get("titre_id"))
    titre_lie: dict | None = None
    if titre_id:
        for t in depot.charger("titres"):
            if t.get("id") == titre_id:
                titre_lie = t
                break
        if titre_lie is None:
            erreurs["titre_id"] = "titre inconnu au catalogue"
        else:
            out["titre_id"] = titre_id
    else:
        out["titre_id"] = None

    # Ticker / nom / devise : auto-complétés depuis le titre lié si vides
    def _auto(champ: str, defaut: str = "") -> str:
        val = _str_propre(donnees.get(champ))
        if not val and titre_lie:
            val = _str_propre(titre_lie.get(champ)) or defaut
        return val

    ticker = _auto("ticker")
    nom = _auto("nom")
    devise = _auto("devise", defaut="EUR")

    if not ticker:
        erreurs["ticker"] = "obligatoire"
    else:
        out["ticker"] = ticker
    if not nom:
        erreurs["nom"] = "obligatoire"
    else:
        out["nom"] = nom
    if not devise:
        erreurs["devise"] = "obligatoire"
    else:
        out["devise"] = devise

    # Raisonnement : optionnel mais conservé
    out["raisonnement"] = _str_propre(donnees.get("raisonnement"))

    if erreurs:
        raise ErreursValidation(erreurs)

    # Horizon (jours) dérivé des deux dates — conservé pour usages stats
    base = _date.fromisoformat(out["date_prediction"])
    cible = _date.fromisoformat(out["date_echeance"])
    out["horizon_jours"] = (cible - base).days

    return out


# --- API publique ------------------------------------------------------------


def creer_prediction(depot: Depot, donnees: dict) -> dict:
    """Crée une prédiction en cours (statut "en_cours")."""
    pred = _normaliser_creation(depot, donnees)
    pred["id"] = "p-" + uuid.uuid4().hex[:10]
    pred["statut"] = "en_cours"
    pred["cours_echeance"] = None
    pred["resultat"] = None
    pred["ecart_pct"] = None
    pred["notes_evaluation"] = None
    pred["date_creation"] = _date.today().isoformat()

    items = depot.charger("predictions")
    items.append(pred)
    depot.enregistrer("predictions", items)
    return pred


def evaluer_prediction(
    depot: Depot,
    prediction_id: str,
    cours_echeance,
    notes_evaluation: str | None = None,
) -> dict:
    """Bascule une prédiction en `evaluee` et calcule resultat + ecart_pct.

    Lève `ErreursValidation` si le cours est invalide.
    Lève `KeyError` si la prédiction n'existe pas.
    Lève `ValueError` si la prédiction est déjà évaluée.
    """
    items = depot.charger("predictions")
    for i, p in enumerate(items):
        if p.get("id") != prediction_id:
            continue
        if p.get("statut") == "evaluee":
            raise ValueError("prédiction déjà évaluée")

        erreurs: dict[str, str] = {}
        try:
            ce = _parse_decimal_strict_positif(cours_echeance)
        except ValueError as e:
            erreurs["cours_echeance"] = str(e)
        if erreurs:
            raise ErreursValidation(erreurs)

        cr = Decimal(str(p["cours_reference"]))
        ecart = _calcul_ecart_pct(cr, ce)
        resultat = _resultat_pour(p["sens"], cr, ce)

        p["cours_echeance"] = str(ce)
        p["ecart_pct"] = str(ecart)
        p["resultat"] = resultat
        p["statut"] = "evaluee"
        p["notes_evaluation"] = _str_propre(notes_evaluation) or None
        p["date_evaluation"] = _date.today().isoformat()

        items[i] = p
        depot.enregistrer("predictions", items)
        return p
    raise KeyError(prediction_id)


def mettre_a_jour(depot: Depot, prediction_id: str, donnees: dict) -> dict:
    """Met à jour une prédiction `en_cours`. Recalcule date_echeance.

    Refuse de modifier une prédiction déjà évaluée (le verdict est figé ;
    pour corriger, supprimer puis recréer).
    """
    items = depot.charger("predictions")
    for i, p in enumerate(items):
        if p.get("id") != prediction_id:
            continue
        if p.get("statut") == "evaluee":
            raise ValueError("prédiction déjà évaluée — édition impossible")

        nouveau = _normaliser_creation(depot, donnees)
        nouveau["id"] = prediction_id
        nouveau["statut"] = "en_cours"
        nouveau["cours_echeance"] = None
        nouveau["resultat"] = None
        nouveau["ecart_pct"] = None
        nouveau["notes_evaluation"] = None
        nouveau["date_creation"] = p.get("date_creation") or _date.today().isoformat()
        items[i] = nouveau
        depot.enregistrer("predictions", items)
        return nouveau
    raise KeyError(prediction_id)


def trouver(depot: Depot, prediction_id: str) -> dict | None:
    for p in depot.charger("predictions"):
        if p.get("id") == prediction_id:
            return p
    return None


def lister(
    depot: Depot,
    *,
    statut: str | None = None,
    sens: str | None = None,
) -> list[dict]:
    """Liste triée date_prediction décroissante."""
    items = depot.charger("predictions")
    res = []
    for p in items:
        if statut and p.get("statut") != statut:
            continue
        if sens and p.get("sens") != sens:
            continue
        res.append(p)
    res.sort(
        key=lambda p: (p.get("date_prediction", ""), p.get("id", "")),
        reverse=True,
    )
    return res


def supprimer(depot: Depot, prediction_id: str) -> bool:
    items = depot.charger("predictions")
    restants = [p for p in items if p.get("id") != prediction_id]
    if len(restants) == len(items):
        return False
    depot.enregistrer("predictions", restants)
    return True


def echeances_depassees(depot: Depot, aujourdhui: str | None = None) -> list[dict]:
    """Prédictions en_cours dont la date d'échéance est passée."""
    today = aujourdhui or _date.today().isoformat()
    return [
        p for p in depot.charger("predictions")
        if p.get("statut") == "en_cours" and (p.get("date_echeance") or "") <= today
    ]


# --- Statistiques ------------------------------------------------------------


def _stats_groupe(items: list[dict]) -> dict:
    total = len(items)
    justes = sum(1 for p in items if p.get("resultat") == "juste")
    taux = None
    if total > 0:
        taux = (Decimal(justes) / Decimal(total) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return {"total": total, "justes": justes, "taux_pct": taux}


def taux_reussite(depot: Depot, *, filtre: dict | None = None) -> dict:
    """Statistiques sur les prédictions évaluées.

    `filtre` : dict optionnel {"sens": "hausse"} pour restreindre l'assiette.

    Retourne :
      - total_evaluees, total_justes, taux_global_pct (None si aucune évaluée)
      - par_sens : {"hausse": {total, justes, taux_pct}, "baisse": {...}}
      - par_conviction : {1: {...}, 2: {...}, ..., 5: {...}}
    """
    items = [p for p in depot.charger("predictions") if p.get("statut") == "evaluee"]
    if filtre:
        sens = filtre.get("sens")
        if sens:
            items = [p for p in items if p.get("sens") == sens]

    global_stats = _stats_groupe(items)
    par_sens = {s: _stats_groupe([p for p in items if p.get("sens") == s]) for s in SENS}
    par_conviction = {
        c: _stats_groupe([p for p in items if p.get("conviction") == c])
        for c in CONVICTIONS
    }

    return {
        "total_evaluees": global_stats["total"],
        "total_justes": global_stats["justes"],
        "taux_global_pct": global_stats["taux_pct"],
        "par_sens": par_sens,
        "par_conviction": par_conviction,
    }
