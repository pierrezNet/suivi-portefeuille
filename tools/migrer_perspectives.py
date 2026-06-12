#!/usr/bin/env python
"""Migration idempotente : transforme le champ `perspectives` non-vide
de chaque titre en une note de journal datée du jour de migration.

Le champ `perspectives` n'est plus lu par l'app (S6 — fusion des concepts
"thèse" et "journal de bord"). Cette migration préserve l'information existante
en la déplaçant dans le journal de bord du titre.

Idempotence : une note de migration est marquée par un `titre_court` spécifique
("Perspectives reportées dans le journal — migration"). Si elle existe déjà
pour un titre donné, on ignore.
"""

from __future__ import annotations

import sys
import uuid
from datetime import date as _date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.services.stockage import Depot

MARQUEUR_MIGRATION = "Perspectives reportées dans le journal — migration"


def main() -> int:
    depot = Depot(RACINE / "data")
    titres = depot.charger("titres")
    notes = depot.charger("notes_titres")

    aujourd_hui = _date.today().isoformat()
    migrations = 0
    deja_faites = 0

    for titre in titres:
        perspectives = (titre.get("perspectives") or "").strip()
        if not perspectives:
            continue

        # Vérifier idempotence
        deja = any(
            n.get("titre_id") == titre["id"]
            and n.get("titre_court") == MARQUEUR_MIGRATION
            for n in notes
        )
        if deja:
            deja_faites += 1
            continue

        nouvelle_note = {
            "id": "n-" + uuid.uuid4().hex[:10],
            "titre_id": titre["id"],
            "date": aujourd_hui,
            "type": "mise_a_jour_these",
            "titre_court": MARQUEUR_MIGRATION,
            "contenu": perspectives,
            "date_creation": aujourd_hui,
        }
        notes.append(nouvelle_note)
        migrations += 1
        print(
            f"  + {titre.get('ticker') or titre['id']} : note créée "
            f"({len(perspectives)} caractères migrés)"
        )

    if migrations:
        depot.enregistrer("notes_titres", notes)
        print(f"\n✓ {migrations} note(s) de migration ajoutée(s).")
    if deja_faites:
        print(f"ℹ {deja_faites} titre(s) déjà migré(s) — ignoré(s).")
    if not migrations and not deja_faites:
        print("ℹ Aucun champ `perspectives` non-vide à migrer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
