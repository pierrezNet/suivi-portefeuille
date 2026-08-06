"""Migrations de schéma appliquées AU DÉMARRAGE de l'app.

Les amis (Windows .exe) n'ont ni shell ni Python : impossible de lancer un
script de migration à la main (contrairement aux `tools/migrer_*.py` historiques
d'Emmanuel, déjà appliqués). On applique donc les migrations nécessaires au
démarrage, après une sauvegarde automatique des données.

La version du schéma est stockée dans ``DATA_DIR/meta.json``. Pour ajouter une
migration : incrémenter ``VERSION_SCHEMA_COURANTE`` et ajouter ``(N, fonction)``
à ``MIGRATIONS`` (``fonction(depot)`` fait passer le schéma de N-1 à N et doit
tolérer un dépôt vide).
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from app.services.stockage import Depot, ecrire_json_atomique, lire_json


FICHIER_META = "meta.json"

# Version du schéma à l'introduction de meta.json : si meta.json est absent
# (install existant d'Emmanuel ou install neuf), on considère les données à
# cette version, puis on applique les migrations ultérieures éventuelles.
VERSION_INITIALE = 1
VERSION_SCHEMA_COURANTE = 4


def _migration_v2_categorie(depot: Depot) -> None:
    """v1→v2 : renseigne le champ contrôlé `categorie` sur chaque titre qui ne
    l'a pas encore, en classant son `secteur` libre (voir app.services.categories).
    Idempotent : ne touche pas un titre déjà catégorisé."""
    from app.services.categories import CATEGORIES, categoriser

    titres = depot.charger("titres")
    modifie = False
    for t in titres:
        if (t.get("categorie") or "").strip() in CATEGORIES:
            continue
        t["categorie"] = categoriser(t)
        modifie = True
    if modifie:
        depot.enregistrer("titres", titres)


def _position_titre(mouvements: list[dict], titre_id: str) -> Decimal:
    """Quantité nette détenue (achats − ventes) pour un titre."""
    pos = Decimal("0")
    for m in mouvements:
        if m.get("titre_id") != titre_id:
            continue
        try:
            q = Decimal(str(m.get("quantite") or "0"))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if m.get("type") == "achat":
            pos += q
        elif m.get("type") == "vente":
            pos -= q
    return pos


# Champs de suivi copiés tels quels de la watch vers le titre (setdefault :
# on ne réécrit jamais une valeur déjà présente → idempotent).
_CHAMPS_SUIVI_SIMPLES = ("statut", "priorite", "compte_cible", "echeance_abandon", "ajoute_le")


def _absorber_suivi(titre: dict, watch: dict) -> None:
    """Copie le suivi d'une watch sur un titre, sans écraser l'existant.

    Idempotent : `setdefault` pour les champs simples, fusion par `id` pour les
    ordres, pose unique pour les paliers. Applique la règle `these_lt`
    (le titre est la source versionnée : on ne l'écrase pas) et les renommages
    `notes → notes_suivi`, `cap_boursiere → cap_boursiere_txt`.
    """
    for c in _CHAMPS_SUIVI_SIMPLES:
        v = watch.get(c)
        if v not in (None, "") and c not in titre:
            titre[c] = v

    # Ordres actifs : fusion par id (préserve l'existant, ajoute les nouveaux).
    incoming_ordres = watch.get("ordres_actifs") or []
    if incoming_ordres:
        existants = titre.get("ordres_actifs") or []
        vus = {o.get("id") for o in existants}
        for o in incoming_ordres:
            if o.get("id") not in vus:
                existants.append(o)
                vus.add(o.get("id"))
        titre["ordres_actifs"] = existants

    # Paliers : pose unique (ne pas dupliquer si déjà présents).
    if watch.get("paliers_rachat") and not titre.get("paliers_rachat"):
        titre["paliers_rachat"] = watch["paliers_rachat"]

    # cap_boursiere (texte) → cap_boursiere_txt (cohabite avec cap_boursiere_m).
    cap = (watch.get("cap_boursiere") or "").strip()
    if cap and not titre.get("cap_boursiere_txt"):
        titre["cap_boursiere_txt"] = cap

    # notes (texte watch) → notes_suivi.
    notes = (watch.get("notes") or "").strip()

    # Thèse : le titre est la source versionnée. Ne pas l'écraser.
    these_titre = (titre.get("these_lt") or "").strip()
    these_watch = (watch.get("these_lt") or "").strip()
    annexes: list[str] = []
    if these_watch and not these_titre:
        titre["these_lt"] = these_watch
    elif these_watch and these_watch != these_titre:
        annexes.append(f"[thèse watch importée] {these_watch}")
    if notes:
        annexes.append(notes)
    if annexes:
        existant = (titre.get("notes_suivi") or "").strip()
        fusion = "\n\n".join(([existant] if existant else []) + [
            a for a in annexes if a not in existant
        ])
        if fusion:
            titre["notes_suivi"] = fusion


def _migration_v3_fusion_watchlist(depot: Depot) -> None:
    """v2→v3 : fusionne la watchlist dans les titres (une seule entité).

    - watch liée (`titre_id` connu) → son suivi est absorbé par le titre ;
    - watch orpheline → un titre est créé depuis elle (ou rattaché à un titre de
      même ticker/slug s'il existe déjà, pour l'idempotence) ;
    - titre possédé sans suivi → statut par défaut (`renforcement` si position
      > 0, sinon `actif`).

    `watchlist.json` est laissé intact (rollback ; la sauvegarde automatique est
    déjà prise par `appliquer`). Idempotente et autonome (n'utilise que
    `depot.charger/enregistrer`).
    """
    from app.services.titres import _slug  # slug + dédup partagés

    titres = depot.charger("titres")
    watchs = depot.charger("watchlist")
    mouvements = depot.charger("mouvements")

    index: dict[str, dict] = {t.get("id"): t for t in titres}
    ids: set[str] = set(index)
    par_ticker: dict[str, dict] = {}
    for t in titres:
        tk = (t.get("ticker") or "").strip().upper()
        if tk:
            par_ticker.setdefault(tk, t)

    today = _date.today().isoformat()
    modifie = False

    for w in watchs:
        # 1) Cible : lien explicite, sinon ticker connu, sinon slug déjà présent,
        #    sinon création (permet de rejouer la migration sans dupliquer).
        cible = None
        tid = (w.get("titre_id") or "").strip()
        ticker = (w.get("ticker") or "").strip().upper()
        nom = (w.get("nom") or "").strip()
        if tid and tid in index:
            cible = index[tid]
        elif ticker and ticker in par_ticker:
            cible = par_ticker[ticker]
        else:
            slug = _slug(ticker or nom)
            if slug and slug in index:
                cible = index[slug]

        if cible is None:
            if not ticker and not nom:
                continue  # watch inqualifiable : ignorée
            base = _slug(ticker or nom)
            nouvel_id = base
            i = 2
            while nouvel_id in ids:
                nouvel_id = f"{base}-{i}"
                i += 1
            cible = {
                "id": nouvel_id,
                "ticker": ticker,
                "nom": nom or ticker,
                "devise": (w.get("devise") or "EUR").upper(),
                "date_creation": w.get("ajoute_le") or today,
            }
            if w.get("marche"):
                cible["marche"] = w["marche"]
            titres.append(cible)
            index[nouvel_id] = cible
            ids.add(nouvel_id)
            if ticker:
                par_ticker.setdefault(ticker, cible)

        _absorber_suivi(cible, w)
        modifie = True

    # 2) Titres possédés sans suivi : poser un statut/priorité par défaut.
    for t in titres:
        if "statut" not in t:
            t["statut"] = "renforcement" if _position_titre(mouvements, t["id"]) > 0 else "actif"
            modifie = True
        if "priorite" not in t:
            t["priorite"] = "moyenne"
            modifie = True
        if "ajoute_le" not in t:
            t["ajoute_le"] = t.get("date_creation") or today
            modifie = True

    if modifie:
        depot.enregistrer("titres", titres)


def _migration_v4_remap_statuts(depot: Depot) -> None:
    """v3→v4 : le statut `actif` (ambigu depuis la fusion) est remplacé par
    `conservation` (si le titre est détenu) ou `veille` (sinon). Idempotent :
    ne touche que les titres encore en `actif`."""
    titres = depot.charger("titres")
    mouvements = depot.charger("mouvements")
    modifie = False
    for t in titres:
        if t.get("statut") == "actif":
            t["statut"] = (
                "conservation" if _position_titre(mouvements, t["id"]) > 0 else "veille"
            )
            modifie = True
    if modifie:
        depot.enregistrer("titres", titres)


# Liste ordonnée : (version_cible, fonction(depot) -> None).
MIGRATIONS: list[tuple[int, Callable[[Depot], None]]] = [
    (2, _migration_v2_categorie),
    (3, _migration_v3_fusion_watchlist),
    (4, _migration_v4_remap_statuts),
]


def _chemin_meta(data_dir) -> Path:
    return Path(data_dir) / FICHIER_META


def version_actuelle(data_dir) -> int:
    """Version du schéma enregistrée (``VERSION_INITIALE`` si meta.json absent)."""
    meta = lire_json(_chemin_meta(data_dir))
    return int(meta.get("version_schema", VERSION_INITIALE))


def _ecrire_version(data_dir, version: int) -> None:
    chemin = _chemin_meta(data_dir)
    meta = lire_json(chemin)
    meta["version_schema"] = version
    ecrire_json_atomique(chemin, meta)


def appliquer(data_dir, *, sauvegarder: Callable[[Path], object] | None = None) -> int:
    """Applique les migrations en attente puis estampille la version courante.

    ``sauvegarder(data_dir)`` est appelé UNE fois avant d'appliquer la moindre
    migration (jamais si rien à migrer). Renvoie la version finale.
    """
    data_dir = Path(data_dir)
    meta_present = _chemin_meta(data_dir).exists()
    courante = version_actuelle(data_dir)
    a_appliquer = sorted(
        (v, f) for (v, f) in MIGRATIONS if courante < v <= VERSION_SCHEMA_COURANTE
    )
    if a_appliquer and sauvegarder is not None:
        sauvegarder(data_dir)
    depot = Depot(data_dir)
    for _version, fonction in a_appliquer:
        fonction(depot)

    # On n'estampille QUE vers le haut, et seulement si nécessaire :
    # - jamais en dessous de la version déjà enregistrée (pas de rétrogradation
    #   si les données viennent d'un .exe plus récent) ;
    # - pas de réécriture parasite de meta.json à chaque démarrage de régime.
    cible = max(courante, VERSION_SCHEMA_COURANTE)
    if not meta_present or a_appliquer or cible != courante:
        _ecrire_version(data_dir, cible)
    return version_actuelle(data_dir)
