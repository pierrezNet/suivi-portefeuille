#!/usr/bin/env python
"""Enrichit la fiche d'un titre à partir de Yahoo Finance (CLI).

Thin wrapper sur `app.services.yahoo.enrichir()`. Aucun import du runtime
Flask. Le module métier est partagé avec les routes Flask (bouton
« Actualiser Yahoo » et « Promouvoir en titre »).

Tickers Yahoo classiques :
  IFX.DE   = Infineon Technologies (Xetra)
  STMPA.PA = STMicroelectronics (Euronext Paris)
  NET      = Cloudflare (NYSE)
  GTLB     = GitLab (Nasdaq)

Usage :
  python tools/enrichir_titre.py IFX.DE
  python tools/enrichir_titre.py STMPA.PA --id stm --horizon "5-10 ans"
  python tools/enrichir_titre.py IFX.DE --raw   # dump info brut Yahoo

⚠️ Yahoo Finance n'est pas une API officielle (yfinance scrape). Toujours
re-vérifier les chiffres dans le rapport annuel / sur le site IR avant
de prendre une décision d'investissement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.services import yahoo


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ticker", help="Ticker Yahoo (ex: IFX.DE, STMPA.PA, NET)")
    p.add_argument("--id", dest="id_override",
                   help="ID à utiliser (défaut: dérivé du ticker)")
    p.add_argument("--horizon", default="5-10 ans")
    p.add_argument("--raw", action="store_true",
                   help="Affiche aussi le dict `info` Yahoo brut (debug)")
    args = p.parse_args()

    try:
        fiche = yahoo.enrichir(
            args.ticker,
            id_override=args.id_override,
            horizon=args.horizon,
        )
    except Exception as e:
        print(f"❌ Erreur : {e}", file=sys.stderr)
        return 1

    print("# Bloc à copier-coller dans data/titres.json (dans la liste titres) :")
    print(json.dumps(fiche, indent=2, ensure_ascii=False))
    print()
    print(
        "# 💡 Pense à compléter manuellement : perspectives, these_lt, "
        "signaux_mt_positifs/négatifs (Yahoo ne les a pas)."
    )

    if args.raw:
        import yfinance as yf
        print("\n--- info brut Yahoo (debug) ---", file=sys.stderr)
        print(
            json.dumps(yf.Ticker(args.ticker).info, indent=2,
                       ensure_ascii=False, default=str),
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
