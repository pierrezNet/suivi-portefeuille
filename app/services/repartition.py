"""Calcul de répartitions (compte / secteur / devise) et coordonnées SVG
pour des camemberts d'allocation natifs (pas de dépendance JS).
"""

from __future__ import annotations

import math
from decimal import Decimal

from app.services.categories import categoriser

# Palette inspirée DSFR (cohérente avec le reste de l'app)
COULEURS = (
    "#000091", "#18753c", "#b34700", "#6e2782",
    "#007c8a", "#ce0500", "#fcc63a", "#888",
)


AXES = ("compte", "categorie", "devise")


def repartition_par_axe(
    vue_comptes: list[dict],
    titres_par_id: dict[str, dict],
    axe: str,
) -> list[dict]:
    """Renvoie une liste triée par valeur décroissante :
    `[{label, valeur (Decimal), pourcentage (Decimal, 1 décimale)}, ...]`."""
    if axe not in AXES:
        raise ValueError(f"axe inconnu : {axe}")
    par_label: dict[str, Decimal] = {}
    for vue in vue_comptes:
        for p in vue.get("positions") or []:
            v = p.get("valo_eur")
            if v is None or v <= 0:
                continue
            if axe == "compte":
                label = (vue.get("compte") or {}).get("nom") or (vue.get("compte") or {}).get("id", "")
            elif axe == "categorie":
                t = titres_par_id.get(p.get("titre_id")) or {}
                label = categoriser(t)
            else:  # devise
                t = titres_par_id.get(p.get("titre_id")) or {}
                label = (t.get("devise") or "EUR").upper()
            par_label[label] = par_label.get(label, Decimal("0")) + v
    total = sum(par_label.values())
    if total <= 0:
        return []
    res = []
    for label, valeur in par_label.items():
        pct = (valeur / total * Decimal("100")).quantize(Decimal("0.1"))
        res.append({"label": label, "valeur": valeur, "pourcentage": pct})
    res.sort(key=lambda x: x["valeur"], reverse=True)
    return res


def coordonnees_camembert(
    parts: list[dict],
    *,
    taille: int = 180,
) -> dict:
    """Convertit une répartition en arcs SVG.

    Renvoie :
      {"slices": [{path, couleur, label, pourcentage}],
       "taille": int, "cx": int, "cy": int, "rayon": int,
       "total": Decimal, "vide": bool}
    """
    if not parts:
        return {"slices": [], "taille": taille, "cx": taille // 2,
                "cy": taille // 2, "rayon": taille // 2 - 2,
                "total": Decimal("0"), "vide": True}

    total = sum(p["valeur"] for p in parts)
    cx = taille // 2
    cy = taille // 2
    rayon = taille // 2 - 2

    # Cas dégénéré : une seule part = cercle complet (les arcs SVG ne ferment
    # pas proprement à 360°, il faut un <circle>).
    if len(parts) == 1:
        return {
            "slices": [{
                "circle": True,
                "couleur": COULEURS[0],
                "label": parts[0]["label"],
                "pourcentage": parts[0]["pourcentage"],
            }],
            "taille": taille, "cx": cx, "cy": cy, "rayon": rayon,
            "total": total, "vide": False,
        }

    slices = []
    angle = -math.pi / 2  # démarre en haut (12 h)
    for i, p in enumerate(parts):
        fraction = float(p["valeur"] / total)
        delta = fraction * 2 * math.pi
        x1 = cx + rayon * math.cos(angle)
        y1 = cy + rayon * math.sin(angle)
        angle_fin = angle + delta
        x2 = cx + rayon * math.cos(angle_fin)
        y2 = cy + rayon * math.sin(angle_fin)
        large_arc = 1 if delta > math.pi else 0
        path = (
            f"M {cx} {cy} "
            f"L {x1:.2f} {y1:.2f} "
            f"A {rayon} {rayon} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z"
        )
        slices.append({
            "circle": False,
            "path": path,
            "couleur": COULEURS[i % len(COULEURS)],
            "label": p["label"],
            "pourcentage": p["pourcentage"],
        })
        angle = angle_fin
    return {"slices": slices, "taille": taille, "cx": cx, "cy": cy,
            "rayon": rayon, "total": total, "vide": False}
