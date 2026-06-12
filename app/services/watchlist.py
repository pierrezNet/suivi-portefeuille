"""Service watchlist : titres surveillés, paliers de rachat, échéances."""

from __future__ import annotations

import re
import uuid
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from app.services.stockage import Depot


PRIORITES = ("haute", "moyenne", "basse", "veille")
STATUTS = ("actif", "renforcement", "rachat_potentiel", "achat_souhaite", "ipo_attendue", "abandonne")
STATUTS_ORDRE = ("en_attente", "execute", "annule", "expire")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


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
    """Lit les ordres actifs depuis un formulaire (champs `ordres_prix`,
    `ordres_quantite`, `ordres_validite`, `ordres_note`, `ordres_id` —
    une ligne = un ordre) ou directement une liste dict.

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
            ordre = {
                "id": _str_propre(o.get("id"))
                or "o-" + uuid.uuid4().hex[:10],
                "prix_limite": prix.replace(",", "."),
                "quantite": int(qte_dec) if qte_dec == qte_dec.to_integral_value() else str(qte_dec),
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
    """Lit les paliers de rachat depuis un formulaire (champs paliers_prix[],
    paliers_tranche[], paliers_commentaire[]) ou directement une liste dict."""
    if isinstance(donnees, list):
        # Cas dict direct
        paliers = []
        for p in donnees:
            prix = _str_propre(p.get("prix"))
            if not prix:
                continue
            try:
                Decimal(prix.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"prix invalide : {prix}")
            paliers.append({
                "prix": prix.replace(",", "."),
                "tranche": _str_propre(p.get("tranche")),
                "commentaire": _str_propre(p.get("commentaire")),
            })
        return paliers
    return []


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
