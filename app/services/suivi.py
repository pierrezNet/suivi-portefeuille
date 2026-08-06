"""Helpers de *suivi* partagés (paliers de rachat, ordres limites, réserve cash).

Fonctions **pures** (aucune dépendance à ``Depot``) extraites de l'ancien service
watchlist, pour être réutilisées à la fois par le service `titres` (le titre
porte désormais son propre suivi) et par le service `watchlist` conservé en
compatibilité. Garder ces helpers ici évite une dépendance `titres → watchlist`.
"""

from __future__ import annotations

import re
import uuid
from datetime import date as _date
from decimal import Decimal, InvalidOperation


PRIORITES = ("haute", "moyenne", "basse", "veille")
# Statuts = intention vis-à-vis du titre (la détention est montrée à part).
# `conservation`/`veille` remplacent l'ancien `actif` ambigu (détenu vs surveillé).
STATUTS = (
    "conservation",
    "veille",
    "achat_souhaite",
    "renforcement",
    "rachat_potentiel",
    "ipo_attendue",
    "levee_fonds",
    "abandonne",
)
STATUTS_ORDRE = ("en_attente", "execute", "annule", "expire")
SENS_ORDRE = ("achat", "vente")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _valider_date_optionnelle(v) -> str | None:
    s = _str_propre(v)
    if not s:
        return None
    if not ISO_DATE.match(s):
        raise ValueError("format attendu YYYY-MM-DD")
    try:
        _date.fromisoformat(s)
    except ValueError:
        raise ValueError("date invalide")
    return s


def _parse_ordres(donnees) -> list[dict]:
    """Lit les ordres actifs depuis une liste de dicts (champs `prix_limite`,
    `quantite`, `validite`, `note`, `sens`, `id`, `statut`, `date_creation`,
    `mouvement_id`) — une entrée = un ordre.

    Préserve `id`, `statut`, `date_creation`, `mouvement_id` quand ils sont
    fournis (cas re-saisie via formulaire ou conservation lors d'une édition).
    """
    if isinstance(donnees, list):
        ordres = []
        for o in donnees:
            prix = _str_propre(o.get("prix_limite"))
            qte = _str_propre(o.get("quantite"))
            if not prix and not qte:
                continue
            try:
                Decimal(prix.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"prix_limite invalide : {prix}")
            if Decimal(prix.replace(",", ".")) <= 0:
                raise ValueError(f"prix_limite doit être > 0 : {prix}")
            try:
                qte_dec = Decimal(qte.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"quantité invalide : {qte}")
            if qte_dec <= 0:
                raise ValueError(f"quantité doit être > 0 : {qte}")
            validite = _str_propre(o.get("validite"))
            if validite and not ISO_DATE.match(validite):
                raise ValueError(f"validité doit être YYYY-MM-DD : {validite}")
            statut = _str_propre(o.get("statut")) or "en_attente"
            if statut not in STATUTS_ORDRE:
                raise ValueError(f"statut ordre invalide : {statut}")
            sens = _str_propre(o.get("sens")) or "achat"
            if sens not in SENS_ORDRE:
                raise ValueError(f"sens ordre invalide : {sens}")
            ordre = {
                "id": _str_propre(o.get("id"))
                or "o-" + uuid.uuid4().hex[:10],
                "prix_limite": prix.replace(",", "."),
                "quantite": int(qte_dec) if qte_dec == qte_dec.to_integral_value() else str(qte_dec),
                "sens": sens,
                "statut": statut,
                "note": _str_propre(o.get("note")),
                "date_creation": _str_propre(o.get("date_creation"))
                or _date.today().isoformat(),
            }
            if validite:
                ordre["validite"] = validite
            mvt_id = _str_propre(o.get("mouvement_id"))
            if mvt_id:
                ordre["mouvement_id"] = mvt_id
            ordres.append(ordre)
        return ordres
    return []


def _parse_paliers(donnees) -> list[dict]:
    """Lit les paliers de rachat depuis une liste de dicts (`prix`, `quantite`,
    `commentaire`) ; ignore les paliers sans prix. Rétro-compatible : l'ancien
    champ `tranche` est relu comme `quantite` s'il est présent."""
    if isinstance(donnees, list):
        paliers = []
        for p in donnees:
            prix = _str_propre(p.get("prix"))
            if not prix:
                continue
            try:
                Decimal(prix.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"prix invalide : {prix}")
            quantite = _str_propre(p.get("quantite")) or _str_propre(p.get("tranche"))
            paliers.append({
                "prix": prix.replace(",", "."),
                "quantite": quantite,
                "commentaire": _str_propre(p.get("commentaire")),
            })
        return paliers
    return []


def _paliers_depuis_formulaire(form: dict) -> list[dict]:
    """Champs multilignes `paliers_prix/quantite/commentaire` (une ligne = un
    palier) → liste de dicts brute (validée ensuite par `_parse_paliers`).
    Rétro-compatible avec l'ancien champ `paliers_tranche`."""
    prix_lines = _str_propre(form.get("paliers_prix")).splitlines()
    qte_lines = _str_propre(
        form.get("paliers_quantite") or form.get("paliers_tranche")
    ).splitlines()
    comm_lines = _str_propre(form.get("paliers_commentaire")).splitlines()
    liste = []
    for i, prix in enumerate(prix_lines):
        prix = prix.strip()
        if not prix:
            continue
        liste.append({
            "prix": prix,
            "quantite": qte_lines[i].strip() if i < len(qte_lines) else "",
            "commentaire": comm_lines[i].strip() if i < len(comm_lines) else "",
        })
    return liste


def fusionner_ordre_actif(ordre_form: dict, ordres_existants: list[dict] | None) -> list[dict]:
    """Liste `ordres_actifs` finale = ordres déjà clos (statut ≠ en_attente)
    conservés + au plus 1 ordre actif issu du formulaire (champs `ordre_prix/
    quantite/validite/note/sens/id/date_creation`).

    Vider `ordre_prix` = pas d'ordre actif (l'ancien actif, s'il existait, n'est
    pas repris → annulation silencieuse). Renvoie des dicts BRUTS ; la
    validation/normalisation se fait ensuite via `_parse_ordres`.
    """
    finaux = [
        o for o in (ordres_existants or []) if o.get("statut") != "en_attente"
    ]
    prix = (ordre_form.get("ordre_prix") or "").strip()
    if prix:
        finaux.append({
            "prix_limite": prix,
            "quantite": ordre_form.get("ordre_quantite", ""),
            "validite": ordre_form.get("ordre_validite", ""),
            "note": ordre_form.get("ordre_note", ""),
            "sens": ordre_form.get("ordre_sens", "achat"),
            "statut": "en_attente",
            "id": ordre_form.get("ordre_id") or "",
            "date_creation": ordre_form.get("ordre_date_creation") or "",
        })
    return finaux


def reserve_cash_par_compte(
    entrees: list[dict], *, today_iso: str | None = None
) -> dict[str, dict]:
    """Cash réservé par les ordres d'ACHAT en attente, groupé par compte cible.

    ``entrees`` est une liste de porteurs de suivi (titres fusionnés — ou watchs
    historiques) exposant ``compte_cible`` et ``ordres_actifs``. Un ordre d'achat
    en attente (statut ``en_attente``, non expiré) « bloque » ``prix_limite ×
    quantite`` chez le broker tant qu'il n'est pas exécuté. Renvoie
    ``{compte_id: {"total": Decimal, "ordres": [ {ticker, prix_limite, quantite,
    montant} ]}}``.

    Règles : les ordres de **vente** ne réservent pas de cash ; un ordre sans
    ``sens`` est considéré comme un achat ; un ordre expiré (``validite`` <
    ``today_iso``) est exclu ; une entrée sans ``compte_cible`` est ignorée.
    """
    reserve: dict[str, dict] = {}
    for w in entrees or []:
        compte_id = w.get("compte_cible")
        if not compte_id:
            continue
        ticker = w.get("ticker") or w.get("nom") or ""
        for o in w.get("ordres_actifs") or []:
            if o.get("statut") != "en_attente":
                continue
            if (o.get("sens") or "achat") != "achat":
                continue
            validite = o.get("validite") or ""
            if today_iso and validite and validite < today_iso:
                continue
            try:
                montant = Decimal(str(o.get("prix_limite"))) * Decimal(
                    str(o.get("quantite"))
                )
            except (InvalidOperation, TypeError, ValueError):
                continue
            entree = reserve.setdefault(
                compte_id, {"total": Decimal("0.00"), "ordres": []}
            )
            entree["total"] += montant
            entree["ordres"].append(
                {
                    "ticker": ticker,
                    "prix_limite": o.get("prix_limite"),
                    "quantite": o.get("quantite"),
                    "montant": montant.quantize(Decimal("0.01")),
                }
            )
    for entree in reserve.values():
        entree["total"] = entree["total"].quantize(Decimal("0.01"))
    return reserve
