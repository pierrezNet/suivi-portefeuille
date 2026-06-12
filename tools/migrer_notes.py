#!/usr/bin/env python
"""Migration idempotente : déplace l'événement « Évolution de la thèse Cloudflare »
de la collection `evenements` vers la nouvelle collection `notes_titres`.

Cible précise :
  - id `e-a806e55918`
  - type `assemblee_generale`
  - titre_id `net`

Si l'événement n'existe plus (déjà migré ou supprimé), no-op silencieux.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date as _date
from pathlib import Path

# Ajout du dossier projet au sys.path pour importer app/
RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.services.stockage import Depot

EVENEMENT_CIBLE_ID = "e-a806e55918"


def main() -> int:
    depot = Depot(RACINE / "data")
    evenements = depot.charger("evenements")
    notes = depot.charger("notes_titres")

    cible = next((e for e in evenements if e.get("id") == EVENEMENT_CIBLE_ID), None)
    if cible is None:
        # Vérifier si déjà migré : on cherche une note de mise_a_jour_these
        # avec le même titre court (signature simple).
        deja = any(
            n.get("type") == "mise_a_jour_these"
            and n.get("titre_id") == "net"
            and "Évolution de la thèse Cloudflare" in (n.get("titre_court") or "")
            for n in notes
        )
        if deja:
            print("✓ Migration déjà effectuée — aucune action.")
            return 0
        print("ℹ Événement cible non trouvé et pas de note correspondante. Rien à faire.")
        return 0

    nouvelle_note = {
        "id": "n-" + uuid.uuid4().hex[:10],
        "titre_id": cible.get("titre_id", "net"),
        "date": cible.get("date", "2026-05-08"),
        "type": "mise_a_jour_these",
        "titre_court": "Évolution de la thèse Cloudflare",
        "contenu": cible.get("notes", ""),
        "date_creation": _date.today().isoformat(),
    }
    notes.append(nouvelle_note)
    nouveaux_evts = [e for e in evenements if e.get("id") != EVENEMENT_CIBLE_ID]

    depot.enregistrer("notes_titres", notes)
    depot.enregistrer("evenements", nouveaux_evts)

    print("✓ Migration effectuée :")
    print(f"  - Événement supprimé : {EVENEMENT_CIBLE_ID}")
    print(f"  - Note créée : {nouvelle_note['id']} (titre_id={nouvelle_note['titre_id']}, "
          f"date={nouvelle_note['date']}, type={nouvelle_note['type']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
