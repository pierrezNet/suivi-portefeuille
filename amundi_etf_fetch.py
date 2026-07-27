#!/usr/bin/env python3
"""Télécharge la compo indice d'un (ou des) ETF Amundi dans data/etf/.

Usage :
    python3 amundi_etf_fetch.py                # tous les ISIN connus
    python3 amundi_etf_fetch.py FR001400U5Q4   # un ISIN précis

La logique réutilisable vit dans app.services.etf_amundi ; ce script n'est
qu'une façade en ligne de commande. Respecte le cache journalier (1 appel par
ISIN par jour au plus).
"""

from __future__ import annotations

import sys

from app.services.etf_amundi import ETF_AMUNDI, get_etf_composition


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    isins = argv or list(ETF_AMUNDI)
    for isin in isins:
        data = get_etf_composition(isin)  # cache du jour, sinon appel réseau
        if not data:
            print(f"{isin} : composition indisponible (réseau / API / ISIN inconnu).")
            continue
        top10 = data.get("INDEX_TOP10", [])
        print(f"\n=== Top 10 de l'indice {isin} au {data.get('date')} ===")
        for ligne in top10:
            print(
                f"  {ligne['poids_pct']:5.2f} %  {ligne['nom']:<32} "
                f"{ligne.get('pays') or '':<14} {ligne.get('secteur') or ''}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
