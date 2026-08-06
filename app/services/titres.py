"""Service titres : CRUD + versioning simple des thèses long terme.

Quand l'un des 4 champs « réflexifs » change (perspectives, these_lt,
signaux_mt_positifs, signaux_mt_negatifs), l'ancienne valeur est
poussée dans `historique_theses` avant la mutation, datée du jour.
"""

from __future__ import annotations

import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from app.services.stockage import Depot
from app.services.suivi import (  # suivi porté par le titre (ex-watchlist)
    PRIORITES,
    STATUTS,
    STATUTS_ORDRE,
    _parse_ordres,
    _parse_paliers,
    _paliers_depuis_formulaire,
    _valider_date_optionnelle,
    fusionner_ordre_actif,
    reserve_cash_par_compte,
)

__all__ = [
    "PRIORITES", "STATUTS", "reserve_cash_par_compte", "ErreursValidation",
    "lister", "trouver", "creer", "mettre_a_jour", "supprimer",
    "definir_ordre_actif", "definir_paliers", "marquer_ordre",
    "basculer_apres_achat",
]


CHAMPS_VERSIONNES = (
    "these_lt",
    "signaux_mt_positifs",
    "signaux_mt_negatifs",
)


CHAMPS_LIBRES = (
    "ticker",
    "nom",
    "isin",
    "marche",
    "devise",
    "secteur",
    "categorie",
    "site_ir",
    "horizon",
    "frequence_dividende",
    "dividende_par_action",
    "cap_boursiere_m",
    "dette_nette_m",
    "valeur_entreprise_m",
    "ticker_yahoo",
)


SLUG_RE = re.compile(r"[^a-z0-9]+")


class ErreursValidation(Exception):
    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = SLUG_RE.sub("-", s)
    return s.strip("-")


def _str_propre(v) -> str:
    return str(v).strip() if v is not None else ""


def _normaliser(donnees: dict, *, ids_existants: set[str], id_actuel: str | None = None) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {}

    ticker = _str_propre(donnees.get("ticker")).upper()
    nom = _str_propre(donnees.get("nom"))
    # Ticker facultatif : les valeurs pré-IPO / non cotées (statut ipo_attendue,
    # levee_fonds) n'en ont pas. On exige au moins un nom OU un ticker.
    if not nom and not ticker:
        erreurs["nom"] = "renseigner au moins un nom ou un ticker"

    # ID : conservé si édition, sinon dérivé du ticker / nom
    if id_actuel:
        out["id"] = id_actuel
    else:
        propose = _slug(donnees.get("id") or ticker or nom)
        if not propose:
            erreurs["id"] = "ticker ou nom requis pour générer l'identifiant"
        else:
            base = propose
            i = 2
            while propose in ids_existants:
                propose = f"{base}-{i}"
                i += 1
            out["id"] = propose

    out["ticker"] = ticker
    out["nom"] = nom

    for c in CHAMPS_LIBRES:
        if c in ("ticker", "nom"):
            continue
        v = _str_propre(donnees.get(c))
        if v:
            out[c] = v

    out["devise"] = (out.get("devise") or "EUR").upper()

    # Booléen verse_dividende
    vd = donnees.get("verse_dividende")
    if isinstance(vd, bool):
        out["verse_dividende"] = vd
    elif _str_propre(vd).lower() in ("1", "true", "on", "oui"):
        out["verse_dividende"] = True
    elif _str_propre(vd).lower() in ("0", "false", "off", "non"):
        out["verse_dividende"] = False

    # Champs versionnés (toujours présents même si vides pour traçabilité)
    for c in CHAMPS_VERSIONNES:
        v = _str_propre(donnees.get(c))
        out[c] = v

    # Validation décimaux des montants financiers
    for c in ("dividende_par_action", "cap_boursiere_m", "dette_nette_m", "valeur_entreprise_m"):
        if c in out:
            try:
                Decimal(out[c].replace(",", "."))
                out[c] = out[c].replace(",", ".")
            except InvalidOperation:
                erreurs[c] = "nombre invalide"

    # Champs de suivi (ex-watchlist), désormais portés par le titre. Émis
    # seulement s'ils sont fournis non vides (comme les CHAMPS_LIBRES) : une
    # édition partielle (ex. chiffres Yahoo) ne les efface pas — mettre_a_jour
    # préserve les valeurs absentes. `paliers_rachat`/`ordres_actifs` ne
    # transitent PAS par ici : ils sont gérés par definir_paliers/ordre_actif.
    statut = _str_propre(donnees.get("statut"))
    if statut:
        if statut not in STATUTS:
            erreurs["statut"] = f"valeur attendue parmi {', '.join(STATUTS)}"
        else:
            out["statut"] = statut

    priorite = _str_propre(donnees.get("priorite"))
    if priorite:
        if priorite not in PRIORITES:
            erreurs["priorite"] = f"valeur attendue parmi {', '.join(PRIORITES)}"
        else:
            out["priorite"] = priorite

    for c in ("compte_cible", "notes_suivi", "cap_boursiere_txt", "cible_totale"):
        v = _str_propre(donnees.get(c))
        if v:
            out[c] = v

    for c in ("echeance_abandon", "ajoute_le"):
        if _str_propre(donnees.get(c)):
            try:
                out[c] = _valider_date_optionnelle(donnees.get(c))
            except ValueError as e:
                erreurs[c] = str(e)

    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def lister(depot: Depot) -> list[dict]:
    items = depot.charger("titres")
    # Tri par ticker ; les titres sans ticker sont renvoyés en fin de liste.
    return sorted(
        items,
        key=lambda t: (
            not (t.get("ticker") or "").strip(),
            (t.get("ticker") or "").upper(),
        ),
    )


def trouver(depot: Depot, titre_id: str) -> dict | None:
    for t in depot.charger("titres"):
        if t.get("id") == titre_id:
            return t
    return None


def creer(depot: Depot, donnees: dict) -> dict:
    items = depot.charger("titres")
    ids = {t.get("id") for t in items}
    titre = _normaliser(donnees, ids_existants=ids)
    titre["date_creation"] = _date.today().isoformat()
    # Tout titre de la liste-pivot porte un statut/priorité de suivi + une date
    # d'ajout, pour l'affichage et les filtres (défauts si non fournis).
    titre.setdefault("statut", "veille")
    titre.setdefault("priorite", "moyenne")
    titre.setdefault("ajoute_le", titre["date_creation"])
    items.append(titre)
    depot.enregistrer("titres", items)
    return titre


def _diff_versionnee(ancien: dict, nouveau: dict) -> bool:
    return any(
        (ancien.get(c) or "") != (nouveau.get(c) or "")
        for c in CHAMPS_VERSIONNES
    )


def _snapshot(titre: dict) -> dict:
    return {
        "date": _date.today().isoformat(),
        "valeurs": {c: titre.get(c, "") for c in CHAMPS_VERSIONNES},
    }


def mettre_a_jour(depot: Depot, titre_id: str, donnees: dict) -> dict:
    items = depot.charger("titres")
    for i, t in enumerate(items):
        if t.get("id") != titre_id:
            continue
        ids = {x.get("id") for x in items}
        nouveau = _normaliser(donnees, ids_existants=ids, id_actuel=titre_id)
        # Préserver historique + date_creation
        nouveau["date_creation"] = t.get("date_creation") or _date.today().isoformat()
        historique = list(t.get("historique_theses") or [])
        if _diff_versionnee(t, nouveau):
            historique.append(_snapshot(t))
        if historique:
            nouveau["historique_theses"] = historique
        # Conserver les éventuels champs additionnels non gérés ici
        for k, v in t.items():
            if k not in nouveau and k not in ("historique_theses",):
                nouveau[k] = v
        items[i] = nouveau
        depot.enregistrer("titres", items)
        return nouveau
    raise KeyError(titre_id)


def supprimer(depot: Depot, titre_id: str) -> bool:
    """Supprime un titre seulement s'il n'est pas référencé par un mouvement."""
    mouvements = depot.charger("mouvements")
    if any(m.get("titre_id") == titre_id for m in mouvements):
        raise ValueError(
            "Ce titre est référencé par un ou plusieurs mouvements ; "
            "supprime-les d'abord ou édite le titre plutôt."
        )
    items = depot.charger("titres")
    nouveau = [t for t in items if t.get("id") != titre_id]
    if len(nouveau) == len(items):
        return False
    depot.enregistrer("titres", nouveau)
    return True


# ---------------------------------------------------------------------------
# Suivi porté par le titre : ordres limites, plan de rachat, statut.
# (Anciennement dans le service watchlist ; opère désormais par `titre_id`.)
# ---------------------------------------------------------------------------

def definir_ordre_actif(depot: Depot, titre_id: str, ordre_form: dict) -> dict:
    """Pose / remplace / retire l'ordre actif d'un titre à partir des champs
    `ordre_*` d'un formulaire, en préservant les ordres déjà clos. Valide via
    `_parse_ordres` (peut lever ValueError). Renvoie le titre mis à jour."""
    items = depot.charger("titres")
    for i, t in enumerate(items):
        if t.get("id") != titre_id:
            continue
        t["ordres_actifs"] = _parse_ordres(
            fusionner_ordre_actif(ordre_form, t.get("ordres_actifs"))
        )
        items[i] = t
        depot.enregistrer("titres", items)
        return t
    raise KeyError(titre_id)


def definir_paliers(depot: Depot, titre_id: str, form: dict) -> dict:
    """Remplace le plan de rachat d'un titre (quantité cible totale + paliers) à
    partir des champs du formulaire. Valide via `_parse_paliers` (peut lever
    ValueError). Renvoie le titre mis à jour."""
    items = depot.charger("titres")
    for i, t in enumerate(items):
        if t.get("id") != titre_id:
            continue
        t["paliers_rachat"] = _parse_paliers(_paliers_depuis_formulaire(form))
        cible = (form.get("cible_totale") or "").strip()
        if cible:
            t["cible_totale"] = cible
        else:
            t.pop("cible_totale", None)
        items[i] = t
        depot.enregistrer("titres", items)
        return t
    raise KeyError(titre_id)


def marquer_ordre(
    depot: Depot,
    titre_id: str,
    ordre_id: str,
    nouveau_statut: str,
    *,
    mouvement_id: str | None = None,
) -> bool:
    """Met à jour le statut d'un ordre actif d'un titre. Renvoie True si modifié.

    Idempotent : si l'ordre est déjà dans le statut cible (et sans mouvement_id
    à poser), no-op. Utilisé après exécution (`execute` + mouvement_id) ou
    annulation/réactivation.
    """
    if nouveau_statut not in STATUTS_ORDRE:
        raise ValueError(f"statut inconnu : {nouveau_statut}")
    items = depot.charger("titres")
    for t in items:
        if t.get("id") != titre_id:
            continue
        for ordre in t.get("ordres_actifs") or []:
            if ordre.get("id") != ordre_id:
                continue
            if ordre.get("statut") == nouveau_statut and not mouvement_id:
                return False
            ordre["statut"] = nouveau_statut
            if mouvement_id:
                ordre["mouvement_id"] = mouvement_id
            depot.enregistrer("titres", items)
            return True
    return False


_STATUTS_AVANT_ACHAT = ("veille", "achat_souhaite")


def basculer_apres_achat(depot: Depot, titre_id: str) -> list[str]:
    """Après un achat, un titre en attente d'entrée passe en `conservation`.

    Si le titre était `veille` (surveillé) ou `achat_souhaite` (à acheter),
    l'achat crée la position : il devient donc *détenu, conservé*. On ne le met
    pas en `renforcement` — celui-ci exprime un projet d'ajout, que l'utilisateur
    pose explicitement. Idempotent : no-op si le titre n'est pas dans un statut
    d'avant-achat. Renvoie la liste des identifiants modifiés (0 ou 1 titre).
    """
    if not titre_id:
        return []
    items = depot.charger("titres")
    modifies: list[str] = []
    for t in items:
        if t.get("id") != titre_id:
            continue
        if t.get("statut") not in _STATUTS_AVANT_ACHAT:
            continue
        t["statut"] = "conservation"
        modifies.append(t.get("id") or "")
    if modifies:
        depot.enregistrer("titres", items)
    return modifies
