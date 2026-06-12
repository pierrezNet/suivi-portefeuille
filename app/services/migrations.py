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

from pathlib import Path
from typing import Callable

from app.services.stockage import Depot, ecrire_json_atomique, lire_json


FICHIER_META = "meta.json"

# Version du schéma à l'introduction de meta.json : si meta.json est absent
# (install existant d'Emmanuel ou install neuf), on considère les données à
# cette version, puis on applique les migrations ultérieures éventuelles.
VERSION_INITIALE = 1
VERSION_SCHEMA_COURANTE = 1

# Liste ordonnée : (version_cible, fonction(depot) -> None). Vide aujourd'hui.
MIGRATIONS: list[tuple[int, Callable[[Depot], None]]] = [
    # (2, _migration_v2_exemple),
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
