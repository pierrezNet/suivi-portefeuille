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


def serie_points(depot: Depot, *, max_points: int = 180) -> list[dict]:
    """Renvoie les snapshots RÉELS (déjà au plus un par jour), triés
    chronologiquement, limités aux `max_points` plus récents.

    Contrairement à `serie_mensuelle`, on NE réduit PAS à un point par mois :
    chaque relevé (import) reste un point — on ne perd pas la granularité
    quotidienne déjà présente dans les données.
    """
    snaps = [s for s in depot.charger("snapshots") if s.get("date")]
    snaps.sort(key=lambda s: s.get("date") or "")
    if max_points and len(snaps) > max_points:
        snaps = snaps[-max_points:]
    points = []
    for s in snaps:
        d = s.get("date") or ""
        points.append({
            "date": d,
            "label": (d[8:10] + "/" + d[5:7]) if len(d) >= 10 else d,
            "portefeuille_total": Decimal(s.get("portefeuille_total") or "0"),
            "cash_total": Decimal(s.get("cash_total") or "0"),
            "valo_titres_total": Decimal(s.get("valo_titres_total") or "0"),
            "pv_latente_total": Decimal(s.get("pv_latente_total") or "0"),
        })
    return points


def _chemin_lisse(xy: list[tuple[int, int]]) -> str:
    """Chemin SVG lissé passant par TOUS les points, via une spline cubique
    **monotone** (Fritsch-Carlson). Adoucit les ruptures de pente sans jamais
    dépasser les valeurs des points : à un minimum/maximum local la tangente
    devient horizontale → pas de faux creux ni de faux sommet inventés.
    """
    n = len(xy)
    if n == 0:
        return ""
    if n == 1:
        return f"M {xy[0][0]},{xy[0][1]}"
    xs = [float(p[0]) for p in xy]
    ys = [float(p[1]) for p in xy]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    delta = [(ys[i + 1] - ys[i]) / dx[i] if dx[i] else 0.0 for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = delta[0], delta[-1]
    for i in range(1, n - 1):
        m[i] = 0.0 if delta[i - 1] * delta[i] <= 0 else (delta[i - 1] + delta[i]) / 2
    # Bornage de monotonie : empêche tout dépassement entre deux points.
    for i in range(n - 1):
        if delta[i] == 0:
            m[i] = m[i + 1] = 0.0
        else:
            a, b = m[i] / delta[i], m[i + 1] / delta[i]
            s = a * a + b * b
            if s > 9:
                t = 3.0 / (s ** 0.5)
                m[i], m[i + 1] = t * a * delta[i], t * b * delta[i]
    d = [f"M {xy[0][0]},{xy[0][1]}"]
    for i in range(n - 1):
        c1x, c1y = xs[i] + dx[i] / 3, ys[i] + m[i] * dx[i] / 3
        c2x, c2y = xs[i + 1] - dx[i] / 3, ys[i + 1] - m[i + 1] * dx[i] / 3
        d.append(f"C {c1x:.1f},{c1y:.1f} {c2x:.1f},{c2y:.1f} {xy[i + 1][0]},{xy[i + 1][1]}")
    return " ".join(d)


def _segments_chemin(chemin: str) -> str:
    """Retire le « M x,y » initial d'un chemin lissé, garde les segments de
    courbe (pour enchaîner un tracé de retour dans une aire fermée)."""
    parts = chemin.split(" ")
    return " ".join(parts[2:]) if len(parts) > 2 else ""


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
            "polyline_base": "",
            "chemin": "",
            "chemin_base": "",
            "bande": "",
            "points_xy": [],
            "hausse": True,
            "bande_positive": True,
            "derniere_bande": Decimal("0"),
            "labels_x": [],
            "min": Decimal("0"),
            "max": Decimal("0"),
            "largeur": largeur,
            "hauteur": hauteur,
            "marge": marge,
        }

    def _pv(p):
        return p.get("pv_latente_total") or Decimal("0")

    def _base(p):
        # Courbe basse : « base » explicite (ex. versements nets) si fournie,
        # sinon « capital investi » = total − plus-value latente.
        b = p.get("base")
        return b if b is not None else p["portefeuille_total"] - _pv(p)

    totaux = [p["portefeuille_total"] for p in points]
    bases = [_base(p) for p in points]
    vmin = min(min(totaux), min(bases))
    vmax = max(max(totaux), max(bases))
    plage = vmax - vmin
    if plage == 0:
        plage = Decimal("1")  # éviter division par zéro

    aire_l = largeur - 2 * marge
    aire_h = hauteur - 2 * marge
    base_y = hauteur - marge

    # Respiration verticale : ~15 % de marge en haut et en bas pour que la
    # courbe ne soit pas collée aux bords (surtout avec peu de points).
    pad = plage * Decimal("0.15")
    lo = vmin - pad
    span = plage + 2 * pad

    def _y(valeur: Decimal) -> int:
        return base_y - int(float((valeur - lo) / span) * aire_h)

    n = len(points)
    # Position X proportionnelle à la DATE réelle si toutes les dates sont
    # exploitables (sinon espacement régulier par index) : un grand écart de
    # temps n'est plus dessiné comme un pas régulier quasi vertical (ex. le saut
    # 24/06 → 03/07), et les jours rapprochés ne sont plus étirés.
    ordinaux: list[int] = []
    for p in points:
        try:
            ordinaux.append(_date.fromisoformat(p.get("date") or "").toordinal())
        except (TypeError, ValueError):
            ordinaux = []
            break
    if len(ordinaux) == n and n > 1 and ordinaux[-1] != ordinaux[0]:
        etendue = ordinaux[-1] - ordinaux[0]

        def _x(i: int) -> int:
            return marge + int((ordinaux[i] - ordinaux[0]) * aire_l / etendue)
    else:
        def _x(i: int) -> int:
            return marge if n == 1 else marge + int(i * aire_l / (n - 1))

    xy_total: list[tuple[int, int]] = []
    xy_base: list[tuple[int, int]] = []
    labels_x: list[dict] = []
    for i, p in enumerate(points):
        x = _x(i)
        xy_total.append((x, _y(p["portefeuille_total"])))
        xy_base.append((x, _y(_base(p))))  # honore la « base » explicite (ex. PV latente)
        texte = p.get("label")
        if not texte:
            m = p.get("mois") or ""
            texte = (m[5:] + "/" + m[2:4]) if len(m) >= 7 else ""
        labels_x.append({"x": x, "texte": texte})

    # Courbes lissées (spline) : plus d'angle net aux ruptures de pente.
    chemin_total = _chemin_lisse(xy_total)
    chemin_base = _chemin_lisse(xy_base)
    # Bande = aire entre « capital investi » (base) et total, à bords lissés :
    # base à l'aller (lissée), total lissé au retour, tracé fermé.
    bande = (
        chemin_base
        + f" L {xy_total[-1][0]},{xy_total[-1][1]} "
        + _segments_chemin(_chemin_lisse(list(reversed(xy_total))))
        + " Z"
    )

    return {
        "polyline": " ".join(f"{x},{y}" for x, y in xy_total),
        "polyline_base": " ".join(f"{x},{y}" for x, y in xy_base),
        "chemin": chemin_total,
        "chemin_base": chemin_base,
        "bande": bande,
        "points_xy": [{"x": x, "y": y} for x, y in xy_total],
        "hausse": totaux[-1] >= totaux[0],
        "bande_positive": (totaux[-1] - bases[-1]) >= 0,
        "derniere_bande": totaux[-1] - bases[-1],
        "labels_x": labels_x,
        "min": vmin,
        "max": vmax,
        "dernier": totaux[-1],
        "premier": totaux[0],
        "largeur": largeur,
        "hauteur": hauteur,
        "marge": marge,
    }
