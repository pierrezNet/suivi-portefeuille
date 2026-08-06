"""Service watchlist (compatibilité).

Le suivi (statut, priorité, paliers, ordres) vit désormais sur le titre lui-même
(voir `app.services.titres` + `app.services.suivi`). Ce module est conservé pour
les redirections de compatibilité et l'historique `watchlist.json` ; il réutilise
les helpers purs de `app.services.suivi` (source unique de vérité)."""

from __future__ import annotations

import uuid
from datetime import date as _date

from app.services.stockage import Depot
from app.services.suivi import (
    ISO_DATE,
    PRIORITES,
    SENS_ORDRE,
    STATUTS,
    STATUTS_ORDRE,
    _paliers_depuis_formulaire,
    _parse_ordres,
    _parse_paliers,
    _str_propre,
    _valider_date_optionnelle,
    fusionner_ordre_actif,
    reserve_cash_par_compte,
)

__all__ = [
    "ISO_DATE", "PRIORITES", "SENS_ORDRE", "STATUTS", "STATUTS_ORDRE",
    "ErreursValidation", "reserve_cash_par_compte", "fusionner_ordre_actif",
    "lister", "trouver", "creer", "mettre_a_jour", "supprimer", "marquer_ordre",
    "trouver_watch_par_titre", "definir_ordre_actif", "definir_paliers",
    "basculer_actif_vers_renforcement",
]


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _normaliser(donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    nom = _str_propre(donnees.get("nom"))
    ticker = _str_propre(donnees.get("ticker")).upper()
    if not nom and not ticker:
        erreurs["nom"] = "renseigner au moins un nom ou un ticker"

    out["nom"] = nom
    if ticker:
        out["ticker"] = ticker

    for c in ("titre_id", "marche", "compte_cible"):
        v = _str_propre(donnees.get(c))
        if v:
            out[c] = v

    devise = _str_propre(donnees.get("devise")).upper()
    if devise:
        out["devise"] = devise

    cap = _str_propre(donnees.get("cap_boursiere"))
    if cap:
        out["cap_boursiere"] = cap

    statut = _str_propre(donnees.get("statut")) or "actif"
    if statut not in STATUTS:
        erreurs["statut"] = f"valeur attendue parmi {', '.join(STATUTS)}"
    else:
        out["statut"] = statut

    priorite = _str_propre(donnees.get("priorite")) or "moyenne"
    if priorite not in PRIORITES:
        erreurs["priorite"] = f"valeur attendue parmi {', '.join(PRIORITES)}"
    else:
        out["priorite"] = priorite

    out["these_lt"] = _str_propre(donnees.get("these_lt"))
    out["notes"] = _str_propre(donnees.get("notes"))

    try:
        out["echeance_abandon"] = _valider_date_optionnelle(
            donnees.get("echeance_abandon")
        )
        if out["echeance_abandon"] is None:
            del out["echeance_abandon"]
    except ValueError as e:
        erreurs["echeance_abandon"] = str(e)

    try:
        out["ajoute_le"] = (
            _valider_date_optionnelle(donnees.get("ajoute_le"))
            or _date.today().isoformat()
        )
    except ValueError as e:
        erreurs["ajoute_le"] = str(e)

    # Paliers : on accepte plusieurs formats
    paliers_input = donnees.get("paliers_rachat")
    if paliers_input is None:
        # Lecture des champs de formulaire répétés (paliers[i][prix] etc. non standard)
        # Format simple : paliers_prix séparés par newlines, paliers_tranche idem
        prix_lines = _str_propre(donnees.get("paliers_prix")).splitlines()
        tranche_lines = _str_propre(donnees.get("paliers_tranche")).splitlines()
        comm_lines = _str_propre(donnees.get("paliers_commentaire")).splitlines()
        paliers_input = []
        for i, prix in enumerate(prix_lines):
            prix = prix.strip()
            if not prix:
                continue
            paliers_input.append({
                "prix": prix,
                "tranche": tranche_lines[i].strip() if i < len(tranche_lines) else "",
                "commentaire": comm_lines[i].strip() if i < len(comm_lines) else "",
            })
    try:
        paliers = _parse_paliers(paliers_input)
        if paliers:
            out["paliers_rachat"] = paliers
    except ValueError as e:
        erreurs["paliers_rachat"] = str(e)

    # Ordres actifs : depuis listes parallèles textareas OU dict direct
    ordres_input = donnees.get("ordres_actifs")
    if ordres_input is None:
        prix_lines = _str_propre(donnees.get("ordres_prix")).splitlines()
        qte_lines = _str_propre(donnees.get("ordres_quantite")).splitlines()
        valid_lines = _str_propre(donnees.get("ordres_validite")).splitlines()
        note_lines = _str_propre(donnees.get("ordres_note")).splitlines()
        id_lines = _str_propre(donnees.get("ordres_id")).splitlines()
        statut_lines = _str_propre(donnees.get("ordres_statut")).splitlines()
        creation_lines = _str_propre(donnees.get("ordres_date_creation")).splitlines()
        mvt_lines = _str_propre(donnees.get("ordres_mouvement_id")).splitlines()
        ordres_input = []
        for i, prix in enumerate(prix_lines):
            prix = prix.strip()
            if not prix:
                continue
            ordres_input.append({
                "prix_limite": prix,
                "quantite": qte_lines[i].strip() if i < len(qte_lines) else "",
                "validite": valid_lines[i].strip() if i < len(valid_lines) else "",
                "note": note_lines[i].strip() if i < len(note_lines) else "",
                "id": id_lines[i].strip() if i < len(id_lines) else "",
                "statut": statut_lines[i].strip() if i < len(statut_lines) else "",
                "date_creation": creation_lines[i].strip() if i < len(creation_lines) else "",
                "mouvement_id": mvt_lines[i].strip() if i < len(mvt_lines) else "",
            })
    try:
        ordres = _parse_ordres(ordres_input)
        if ordres:
            out["ordres_actifs"] = ordres
    except ValueError as e:
        erreurs["ordres_actifs"] = str(e)

    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(depot: Depot, *, statut: str | None = None, priorite: str | None = None) -> list[dict]:
    items = depot.charger("watchlist")
    res = []
    for w in items:
        if statut and w.get("statut", "actif") != statut:
            continue
        if priorite and w.get("priorite") != priorite:
            continue
        res.append(w)
    ordre_priorite = {p: i for i, p in enumerate(PRIORITES)}
    res.sort(key=lambda w: (
        ordre_priorite.get(w.get("priorite"), 99),
        w.get("nom") or w.get("ticker") or "",
    ))
    return res


def trouver(depot: Depot, watch_id: str) -> dict | None:
    for w in depot.charger("watchlist"):
        if w.get("id") == watch_id:
            return w
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    item = _normaliser(donnees)
    item["id"] = "w-" + uuid.uuid4().hex[:10]
    items = depot.charger("watchlist")
    items.append(item)
    depot.enregistrer("watchlist", items)
    return item


def mettre_a_jour(depot: Depot, watch_id: str, donnees: dict) -> dict:
    items = depot.charger("watchlist")
    for i, w in enumerate(items):
        if w.get("id") != watch_id:
            continue
        nouveau = _normaliser(donnees)
        nouveau["id"] = watch_id
        items[i] = nouveau
        depot.enregistrer("watchlist", items)
        return nouveau
    raise KeyError(watch_id)


def supprimer(depot: Depot, watch_id: str) -> bool:
    items = depot.charger("watchlist")
    nouveau = [w for w in items if w.get("id") != watch_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("watchlist", nouveau)
    return True


def marquer_ordre(
    depot: Depot,
    watch_id: str,
    ordre_id: str,
    nouveau_statut: str,
    *,
    mouvement_id: str | None = None,
) -> bool:
    """Met à jour le statut d'un ordre actif. Renvoie True si modifié.

    Idempotent : si l'ordre est déjà dans le statut cible, no-op.
    Utilisé après exécution (statut='execute' + mouvement_id) ou annulation.
    """
    if nouveau_statut not in STATUTS_ORDRE:
        raise ValueError(f"statut inconnu : {nouveau_statut}")
    items = depot.charger("watchlist")
    for w in items:
        if w.get("id") != watch_id:
            continue
        for ordre in w.get("ordres_actifs") or []:
            if ordre.get("id") != ordre_id:
                continue
            if ordre.get("statut") == nouveau_statut and not mouvement_id:
                return False
            ordre["statut"] = nouveau_statut
            if mouvement_id:
                ordre["mouvement_id"] = mouvement_id
            depot.enregistrer("watchlist", items)
            return True
    return False


def trouver_watch_par_titre(depot: Depot, titre_id: str) -> dict | None:
    """Première entrée watchlist reliée à ce titre (`titre_id`), ou None."""
    if not titre_id:
        return None
    for w in depot.charger("watchlist"):
        if w.get("titre_id") == titre_id:
            return w
    return None


def definir_ordre_actif(depot: Depot, watch_id: str, ordre_form: dict) -> dict:
    """Pose / remplace / retire l'ordre actif d'une watch à partir des champs
    `ordre_*` d'un formulaire, en préservant les ordres déjà clos. Valide via
    `_parse_ordres` (peut lever ValueError). Renvoie la watch mise à jour."""
    items = depot.charger("watchlist")
    for i, w in enumerate(items):
        if w.get("id") != watch_id:
            continue
        w["ordres_actifs"] = _parse_ordres(
            fusionner_ordre_actif(ordre_form, w.get("ordres_actifs"))
        )
        items[i] = w
        depot.enregistrer("watchlist", items)
        return w
    raise KeyError(watch_id)


def definir_paliers(depot: Depot, watch_id: str, form: dict) -> dict:
    """Remplace le plan de rachat (paliers indicatifs) d'une watch à partir des
    champs multilignes du formulaire. Valide via `_parse_paliers` (peut lever
    ValueError). Renvoie la watch mise à jour."""
    items = depot.charger("watchlist")
    for i, w in enumerate(items):
        if w.get("id") != watch_id:
            continue
        w["paliers_rachat"] = _parse_paliers(_paliers_depuis_formulaire(form))
        items[i] = w
        depot.enregistrer("watchlist", items)
        return w
    raise KeyError(watch_id)


def basculer_actif_vers_renforcement(depot: Depot, titre_id: str) -> list[str]:
    """Passe automatiquement les watch `actif` liées à `titre_id` en `renforcement`.

    Appelé après l'enregistrement d'un achat : si l'utilisateur surveillait le
    titre en `actif`, l'achat signifie que la position existe désormais et le
    suivi devient un *renforcement*.

    Idempotent : si aucune watch ne matche, no-op. Renvoie la liste des
    identifiants modifiés.
    """
    if not titre_id:
        return []
    items = depot.charger("watchlist")
    modifies: list[str] = []
    for w in items:
        if w.get("titre_id") != titre_id:
            continue
        if w.get("statut") != "actif":
            continue
        w["statut"] = "renforcement"
        modifies.append(w.get("id") or "")
    if modifies:
        depot.enregistrer("watchlist", items)
    return modifies
