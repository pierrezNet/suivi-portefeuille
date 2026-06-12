#!/usr/bin/env python
"""Migration idempotente : convertit le palier NET 175 USD en ordre actif.

Avant la fonctionnalité « ordres d'achat actifs », l'utilisateur stockait
l'info de son ordre Cloudflare dans `paliers_rachat` (juste indicatif) +
une note texte libre « Validité de l'ordre : 6 mois à compter du 08/05/2026 ».

Ce script :
1. Cherche la watch w-net
2. Si elle n'a pas encore `ordres_actifs`, crée un ordre à partir du palier
   existant (prix 175, quantité 1, validité 2026-06-01, statut en_attente)
3. Vide `paliers_rachat` (l'info est désormais dans `ordres_actifs`)
4. Idempotent : si l'ordre existe déjà, no-op
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path


RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.services.stockage import Depot


WATCH_ID_CIBLE = "w-net"
PRIX_CIBLE = "175"
VALIDITE_CIBLE = "2026-06-01"
NOTE_ORDRE = "Ordre conditionnel — doublement de la position"
DATE_POSE = "2026-05-08"


def main() -> int:
    depot = Depot(RACINE / "data")
    watches = depot.charger("watchlist")

    cible = next((w for w in watches if w.get("id") == WATCH_ID_CIBLE), None)
    if cible is None:
        print(f"ℹ Watch {WATCH_ID_CIBLE} introuvable. Rien à faire.")
        return 0

    # Idempotence : ordre similaire déjà présent ?
    ordres = cible.get("ordres_actifs") or []
    deja = any(
        str(o.get("prix_limite")) == PRIX_CIBLE
        and o.get("validite") == VALIDITE_CIBLE
        for o in ordres
    )
    if deja:
        print("✓ Ordre déjà migré (prix 175, validité 2026-06-01). No-op.")
        return 0

    nouvel_ordre = {
        "id": "o-" + uuid.uuid4().hex[:10],
        "prix_limite": PRIX_CIBLE,
        "quantite": 1,
        "validite": VALIDITE_CIBLE,
        "statut": "en_attente",
        "note": NOTE_ORDRE,
        "date_creation": DATE_POSE,
    }

    cible["ordres_actifs"] = ordres + [nouvel_ordre]
    # Vidage des paliers (l'info est désormais dans l'ordre actif)
    cible.pop("paliers_rachat", None)
    depot.enregistrer("watchlist", watches)

    print(
        f"✓ Ordre NET {PRIX_CIBLE} USD validité {VALIDITE_CIBLE} créé "
        f"({nouvel_ordre['id']}).\n"
        f"  Paliers indicatifs supprimés (info désormais dans ordres_actifs)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
