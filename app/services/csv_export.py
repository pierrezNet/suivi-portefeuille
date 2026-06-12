"""Export CSV des mouvements et des récaps fiscaux.

Format pensé pour LibreOffice Calc / Excel France :
  - encodage UTF-8 avec BOM (`﻿` en tête)
  - séparateur `;` (et pas `,` qui collerait avec le décimal français)
  - décimal `,` (Decimal → str remplace `.` par `,`)
  - dates ISO `YYYY-MM-DD` (universellement triable)
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Iterable

BOM = "﻿"


def _fr(d) -> str:
    """Decimal/str/int → string avec virgule décimale. Vide si None."""
    if d is None or d == "":
        return ""
    if isinstance(d, Decimal):
        return str(d).replace(".", ",")
    return str(d).replace(".", ",")


def _ecrire(rows: Iterable[Iterable]) -> str:
    buf = io.StringIO()
    buf.write(BOM)
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


# --- Mouvements -------------------------------------------------------------


COLONNES_MOUVEMENTS = (
    "Date", "Type", "Compte", "Ticker", "ISIN", "Quantité",
    "Prix unitaire (EUR)", "Frais (EUR)", "Montant (EUR)",
    "Devise", "Taux change", "Notes", "ID mouvement",
)


def csv_mouvements(
    mouvements: list[dict],
    comptes: list[dict],
    titres: list[dict],
) -> str:
    comptes_par_id = {c["id"]: c for c in comptes}
    titres_par_id = {t["id"]: t for t in titres}

    rows = [COLONNES_MOUVEMENTS]
    for m in sorted(mouvements, key=lambda x: (x.get("date") or "", x.get("id") or "")):
        t = titres_par_id.get(m.get("titre_id") or "", {})
        c = comptes_par_id.get(m.get("compte_id") or "", {})
        # Le « montant » utile dépend du type
        type_mvt = m.get("type") or ""
        if type_mvt in ("alimentation_cash", "retrait_cash", "frais"):
            montant = m.get("montant")
        elif type_mvt == "achat":
            qte = Decimal(str(m.get("quantite") or "0"))
            prix = Decimal(str(m.get("prix_unitaire") or "0"))
            frais = Decimal(str(m.get("frais_courtage") or "0"))
            montant = -(qte * prix + frais)  # impact cash
        elif type_mvt == "vente":
            qte = Decimal(str(m.get("quantite") or "0"))
            prix = Decimal(str(m.get("prix_unitaire_vente") or "0"))
            frais = Decimal(str(m.get("frais_courtage") or "0"))
            montant = qte * prix - frais
        elif type_mvt == "dividende_recu":
            montant = m.get("montant_net_eur") or m.get("montant_brut_total")
        else:
            montant = ""
        prix_u = m.get("prix_unitaire") or m.get("prix_unitaire_vente") or ""
        rows.append([
            m.get("date") or "",
            type_mvt,
            c.get("nom") or m.get("compte_id") or "",
            t.get("ticker") or "",
            t.get("isin") or "",
            _fr(m.get("quantite")),
            _fr(prix_u),
            _fr(m.get("frais_courtage")),
            _fr(montant),
            m.get("devise") or "",
            _fr(m.get("taux_change")),
            (m.get("notes") or "").replace("\r", " ").replace("\n", " "),
            m.get("id") or "",
        ])
    return _ecrire(rows)


# --- Récap fiscal -----------------------------------------------------------


COLONNES_RECAP = (
    "Compte", "Type",
    "Alimentations (€)", "Retraits (€)",
    "Investi (€)", "Brut ventes (€)",
    "PV réalisées (€)", "Dividendes nets (€)",
    "Frais courtage (€)",
)


def _attr(obj, k):
    """Lit `k` sur un dict ou un dataclass indifféremment."""
    if obj is None:
        return ""
    if isinstance(obj, dict):
        return obj.get(k)
    return getattr(obj, k, None)


def csv_recap_fiscal_annee(
    annee: int,
    stats_par_compte: list[dict],
    cumul,
) -> str:
    rows = [(f"Récapitulatif fiscal {annee}",)]
    rows.append([])
    rows.append(COLONNES_RECAP)
    for vue in stats_par_compte:
        c = vue.get("compte") or {}
        s = vue.get("stats")
        rows.append([
            c.get("nom") or vue.get("compte_id", ""),
            c.get("type") or "",
            _fr(_attr(s, "montant_alimentations")),
            _fr(_attr(s, "montant_retraits")),
            _fr(_attr(s, "montant_investi")),
            _fr(_attr(s, "montant_brut_ventes")),
            _fr(_attr(s, "plus_values_realisees")),
            _fr(_attr(s, "dividendes_recus_eur")),
            _fr(_attr(s, "frais_courtage_total")),
        ])
    rows.append([])
    rows.append(["Cumul"])
    rows.append([
        "TOTAL", "",
        _fr(_attr(cumul, "montant_alimentations")),
        _fr(_attr(cumul, "montant_retraits")),
        _fr(_attr(cumul, "montant_investi")),
        _fr(_attr(cumul, "montant_brut_ventes")),
        _fr(_attr(cumul, "plus_values_realisees")),
        _fr(_attr(cumul, "dividendes_recus_eur")),
        _fr(_attr(cumul, "frais_courtage_total")),
    ])
    return _ecrire(rows)
