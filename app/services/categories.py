"""Taxonomie contrôlée des catégories d'investissement.

Le champ `secteur` d'un titre est du texte libre (typé à la main ou issu de
Yahoo) : inutilisable tel quel pour une allocation lisible. On introduit une
liste FERMÉE de catégories (`CATEGORIES`) et un classifieur (`categoriser`)
qui :
  - renvoie la `categorie` explicite du titre si elle est valide ;
  - sinon la déduit par mots-clés sur le `secteur`/`nom` (fallback) ;
  - retombe sur « Autre » si rien ne correspond.

Sert au camembert d'allocation, au menu déroulant du formulaire titre, et à la
migration de backfill.
"""

from __future__ import annotations


CATEGORIES = (
    "Défense",
    "Semi-conducteurs",
    "Logiciel & Cloud",
    "Industrie & Matériaux",
    "ETF diversifiés",
    "Autre",
)

# Règles par mots-clés, dans l'ORDRE de priorité. Chaque entrée : (mots, catégorie).
# Le test se fait sur `secteur` + `nom` en minuscules. ETF en premier pour ne pas
# qu'un libellé de fonds tombe dans une catégorie sectorielle.
_REGLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("etf", "ucits", "msci"), "ETF diversifiés"),
    (("défense", "defense", "drone", "aéronautique", "aeronautique"), "Défense"),
    (("semi-conduc", "semiconduc", "semi conduc", "puce", "wafer"), "Semi-conducteurs"),
    (
        ("logiciel", "software", "saas", "cloud", "cyber", "cao", "plm",
         "devsecops", "infrastructure", "internet", "data"),
        "Logiciel & Cloud",
    ),
    (
        ("pneu", "penumatique", "pneumatique", "matériaux", "materiaux",
         "industrie", "chimie", "automobile", "câble", "cable"),
        "Industrie & Matériaux",
    ),
)


def categoriser(titre: dict) -> str:
    """Catégorie canonique d'un titre (voir module).

    Priorité à la `categorie` explicite si elle appartient à `CATEGORIES` ;
    sinon classification par mots-clés ; sinon « Autre ».
    """
    explicite = (titre.get("categorie") or "").strip()
    if explicite in CATEGORIES:
        return explicite
    texte = f"{titre.get('secteur') or ''} {titre.get('nom') or ''}".lower()
    for mots, categorie in _REGLES:
        if any(m in texte for m in mots):
            return categorie
    return "Autre"
