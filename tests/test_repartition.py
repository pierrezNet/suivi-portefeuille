"""Tests répartition + camembert SVG."""

from decimal import Decimal

import pytest

from app.services.repartition import (
    coordonnees_camembert,
    repartition_par_axe,
)


# --- Fixtures ---------------------------------------------------------------


def _vue_comptes():
    """Reproduit la structure renvoyée par dashboard_data."""
    return [
        {
            "compte": {"id": "pea", "nom": "PEA BD"},
            "positions": [
                {"titre_id": "stm", "valo_eur": Decimal("100")},
                {"titre_id": "dcam", "valo_eur": Decimal("200")},
            ],
        },
        {
            "compte": {"id": "cto", "nom": "CTO BD"},
            "positions": [
                {"titre_id": "net", "valo_eur": Decimal("300")},
                {"titre_id": "gtlb", "valo_eur": Decimal("100")},
                # Position non valorisée — doit être ignorée
                {"titre_id": "ifx", "valo_eur": None},
            ],
        },
    ]


def _titres_par_id():
    return {
        "stm": {"secteur": "Semi-conducteurs", "devise": "EUR"},
        "dcam": {"secteur": "ETF", "devise": "EUR"},
        "net": {"secteur": "Internet infra", "devise": "USD"},
        "gtlb": {"secteur": "Logiciel", "devise": "USD"},
        "ifx": {"secteur": "Semi-conducteurs", "devise": "EUR"},
    }


# --- Répartition par axe ---------------------------------------------------


def test_repartition_par_compte():
    r = repartition_par_axe(_vue_comptes(), _titres_par_id(), "compte")
    par_label = {x["label"]: x for x in r}
    assert par_label["CTO BD"]["valeur"] == Decimal("400")
    assert par_label["PEA BD"]["valeur"] == Decimal("300")
    # Total 700 → CTO ≈ 57.1 % / PEA ≈ 42.9 %
    assert par_label["CTO BD"]["pourcentage"] == Decimal("57.1")
    assert par_label["PEA BD"]["pourcentage"] == Decimal("42.9")
    # Tri par valeur décroissante
    assert r[0]["label"] == "CTO BD"


def test_repartition_par_categorie():
    r = repartition_par_axe(_vue_comptes(), _titres_par_id(), "categorie")
    par_label = {x["label"]: x["valeur"] for x in r}
    # NET "Internet infra" (300) + GTLB "Logiciel" (100) → Logiciel & Cloud
    # DCAM "ETF" (200) → ETF diversifiés
    # STM "Semi-conducteurs" (100 ; IFX ignoré car valo None) → Semi-conducteurs
    assert par_label == {
        "Logiciel & Cloud": Decimal("400"),
        "ETF diversifiés": Decimal("200"),
        "Semi-conducteurs": Decimal("100"),
    }


def test_repartition_par_devise():
    r = repartition_par_axe(_vue_comptes(), _titres_par_id(), "devise")
    par_label = {x["label"]: x["valeur"] for x in r}
    assert par_label == {"EUR": Decimal("300"), "USD": Decimal("400")}


def test_repartition_categorie_inconnue_devient_autre():
    vue = [{"compte": {"id": "x", "nom": "X"}, "positions": [
        {"titre_id": "t1", "valo_eur": Decimal("100")},
        {"titre_id": "t2", "valo_eur": Decimal("50")},
    ]}]
    titres = {"t1": {"secteur": "", "devise": "EUR"},
              "t2": {"devise": "EUR"}}
    r = repartition_par_axe(vue, titres, "categorie")
    assert len(r) == 1
    assert r[0]["label"] == "Autre"
    assert r[0]["valeur"] == Decimal("150")


def test_repartition_vide():
    r = repartition_par_axe([], {}, "compte")
    assert r == []


def test_repartition_axe_invalide():
    with pytest.raises(ValueError):
        repartition_par_axe([], {}, "n_importe_quoi")


# --- Coordonnées SVG -------------------------------------------------------


def test_camembert_vide():
    c = coordonnees_camembert([])
    assert c["vide"] is True
    assert c["slices"] == []


def test_camembert_une_part_devient_cercle():
    parts = [{"label": "PEA", "valeur": Decimal("100"), "pourcentage": Decimal("100.0")}]
    c = coordonnees_camembert(parts)
    assert c["vide"] is False
    assert len(c["slices"]) == 1
    assert c["slices"][0]["circle"] is True
    assert c["slices"][0]["pourcentage"] == Decimal("100.0")


def test_camembert_deux_parts_arcs_valides():
    parts = [
        {"label": "A", "valeur": Decimal("60"), "pourcentage": Decimal("60.0")},
        {"label": "B", "valeur": Decimal("40"), "pourcentage": Decimal("40.0")},
    ]
    c = coordonnees_camembert(parts, taille=200)
    assert len(c["slices"]) == 2
    # Chaque slice a un path SVG démarrant par "M cx cy L"
    for s in c["slices"]:
        assert s["circle"] is False
        assert s["path"].startswith(f"M {c['cx']} {c['cy']} L")
        assert " A " in s["path"]
        assert s["path"].endswith("Z")
    # Les couleurs sont différentes
    assert c["slices"][0]["couleur"] != c["slices"][1]["couleur"]


def test_camembert_large_arc_quand_part_majoritaire():
    """Une part > 50 % doit utiliser large-arc = 1 (sinon l'arc se trompe)."""
    parts = [
        {"label": "A", "valeur": Decimal("80"), "pourcentage": Decimal("80.0")},
        {"label": "B", "valeur": Decimal("20"), "pourcentage": Decimal("20.0")},
    ]
    c = coordonnees_camembert(parts)
    # 1re part (80%) → large arc flag 1 dans le chemin
    assert " 0 1 1 " in c["slices"][0]["path"]
    # 2nde part (20%) → large arc flag 0
    assert " 0 0 1 " in c["slices"][1]["path"]
