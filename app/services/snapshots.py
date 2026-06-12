"""Snapshots quotidiens du portefeuille (cash + valo titres + PV latente).

Un snapshot est enregistré au plus une fois par jour. Il sert à tracer la
courbe d'évolution mensuelle sur le dashboard. Déclenché à chaque import
xlsx réussi (les cours viennent d'être actualisés, donc la valo est fraîche).

Stockage : `data/snapshots.json` — liste triée par date croissante.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from app.services.stockage import Depot


def _serialiser(d: Decimal | None) -> str | None:
    if d is None:
        return None
    return str(d)


def enregistrer_snapshot(
    depot: Depot,
    *,
    cash_total: Decimal,
    valo_titres_total: Decimal,
    portefeuille_total: Decimal,
    pv_latente_total: Decimal,
    aujourdhui: _date | None = None,
) -> dict:
    """Enregistre un snapshot du jour. Idempotent : si un snapshot existe
    déjà pour la date, il est remplacé (la valeur la plus récente du jour
    prime — on accepte plusieurs imports le même jour)."""
    today_iso = (aujourdhui or _date.today()).isoformat()
    snap = {
        "date": today_iso,
        "cash_total": _serialiser(cash_total),
        "valo_titres_total": _serialiser(valo_titres_total),
        "portefeuille_total": _serialiser(portefeuille_total),
        "pv_latente_total": _serialiser(pv_latente_total),
    }
    items = depot.charger("snapshots")
    items = [s for s in items if s.get("date") != today_iso]
    items.append(snap)
    items.sort(key=lambda s: s.get("date") or "")
    depot.enregistrer("snapshots", items)
    return snap


def serie_mensuelle(depot: Depot, *, mois: int = 12) -> list[dict]:
    """Renvoie au plus `mois` points, un par mois (le dernier snapshot du
    mois prime). Trié chronologiquement croissant.

    Chaque point :
      {"mois": "2026-06", "portefeuille_total": Decimal,
       "cash_total": Decimal, "valo_titres_total": Decimal,
       "pv_latente_total": Decimal}
    """
    snaps = depot.charger("snapshots")
    if not snaps:
        return []
    # Garder le dernier snapshot de chaque mois
    par_mois: dict[str, dict] = {}
    for s in sorted(snaps, key=lambda x: x.get("date") or ""):
        d = s.get("date") or ""
        if len(d) < 7:
            continue
        m = d[:7]
        par_mois[m] = s

    points = []
    for mois_key in sorted(par_mois.keys())[-mois:]:
        s = par_mois[mois_key]
        points.append({
            "mois": mois_key,
            "date": s.get("date"),
            "portefeuille_total": Decimal(s.get("portefeuille_total") or "0"),
            "cash_total": Decimal(s.get("cash_total") or "0"),
            "valo_titres_total": Decimal(s.get("valo_titres_total") or "0"),
            "pv_latente_total": Decimal(s.get("pv_latente_total") or "0"),
        })
    return points


def coordonnees_svg(
    points: list[dict],
    *,
    largeur: int = 600,
    hauteur: int = 180,
    marge: int = 32,
) -> dict:
    """Convertit la série en coordonnées prêtes pour un <svg>.

    Renvoie :
      {"polyline": "x1,y1 x2,y2 ...",
       "labels_x": [{x, texte}],
       "min": Decimal, "max": Decimal,
       "largeur": int, "hauteur": int}
    """
    if not points:
        return {
            "polyline": "",
            "labels_x": [],
            "min": Decimal("0"),
            "max": Decimal("0"),
            "largeur": largeur,
            "hauteur": hauteur,
            "marge": marge,
        }
    valeurs = [p["portefeuille_total"] for p in points]
    vmin = min(valeurs)
    vmax = max(valeurs)
    plage = vmax - vmin
    if plage == 0:
        plage = Decimal("1")  # éviter division par zéro

    aire_l = largeur - 2 * marge
    aire_h = hauteur - 2 * marge

    coords: list[str] = []
    labels_x: list[dict] = []
    n = len(points)
    for i, p in enumerate(points):
        x = marge if n == 1 else marge + int(i * aire_l / (n - 1))
        ratio = (p["portefeuille_total"] - vmin) / plage
        y = (hauteur - marge) - int(float(ratio) * aire_h)
        coords.append(f"{x},{y}")
        labels_x.append({"x": x, "texte": p["mois"][5:] + "/" + p["mois"][2:4]})

    return {
        "polyline": " ".join(coords),
        "labels_x": labels_x,
        "min": vmin,
        "max": vmax,
        "dernier": valeurs[-1],
        "premier": valeurs[0],
        "largeur": largeur,
        "hauteur": hauteur,
        "marge": marge,
    }
