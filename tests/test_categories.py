"""Taxonomie des catégories : classifieur `categoriser` et liste contrôlée."""

import pytest

from app.services.categories import CATEGORIES, categoriser


@pytest.mark.parametrize("secteur,attendu", [
    ("Défense", "Défense"),
    ("Drones / Défense", "Défense"),
    ("Semi-conducteurs", "Semi-conducteurs"),
    ("Semi-conducteurs (SOI/SmartCut)", "Semi-conducteurs"),
    ("Semi-conducteurs (Power, SiC, Auto)", "Semi-conducteurs"),
    ("Infrastructure cloud / Cybersécurité", "Logiciel & Cloud"),
    ("Software / DevSecOps", "Logiciel & Cloud"),
    ("CAO", "Logiciel & Cloud"),
    ("Penumatiques", "Industrie & Matériaux"),
    ("ETF Monde (PEA-éligible)", "ETF diversifiés"),
    ("ETF Marchés Émergents ESG (PEA-éligible)", "ETF diversifiés"),
])
def test_categoriser_par_secteur(secteur, attendu):
    assert categoriser({"secteur": secteur}) == attendu


def test_categoriser_secteur_inconnu_donne_autre():
    assert categoriser({"secteur": "Biotech exotique"}) == "Autre"
    assert categoriser({}) == "Autre"


def test_categoriser_respecte_categorie_explicite_valide():
    # une catégorie explicite valide prime sur le secteur
    assert categoriser({"secteur": "ETF Monde", "categorie": "Défense"}) == "Défense"


def test_categoriser_categorie_explicite_invalide_est_ignoree():
    # une valeur hors liste retombe sur la classification par secteur
    assert categoriser({"secteur": "Software", "categorie": "Bidon"}) == "Logiciel & Cloud"


def test_categoriser_renvoie_toujours_une_categorie_connue():
    for secteur in ["Défense", "Semi-conducteurs", "Software", "Penumatiques",
                    "ETF Monde", "n'importe quoi"]:
        assert categoriser({"secteur": secteur}) in CATEGORIES
