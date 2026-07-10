"""Tests snapshots + série mensuelle + coordonnées SVG."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import snapshots as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("snapshots", [])
    return d


def _enreg(depot, *, jour, total="1000", cash="200", valo="800", pv="50"):
    return svc.enregistrer_snapshot(
        depot,
        cash_total=Decimal(cash),
        valo_titres_total=Decimal(valo),
        portefeuille_total=Decimal(total),
        pv_latente_total=Decimal(pv),
        aujourdhui=date.fromisoformat(jour),
    )


def test_enregistrer_snapshot_basique(depot):
    snap = _enreg(depot, jour="2026-06-08")
    assert snap["date"] == "2026-06-08"
    assert snap["portefeuille_total"] == "1000"
    items = depot.charger("snapshots")
    assert len(items) == 1


def test_snapshot_idempotent_meme_jour(depot):
    _enreg(depot, jour="2026-06-08", total="1000")
    _enreg(depot, jour="2026-06-08", total="1100")
    items = depot.charger("snapshots")
    assert len(items) == 1
    # Le dernier prime (plusieurs imports dans la journée)
    assert items[0]["portefeuille_total"] == "1100"


def test_snapshots_tries_par_date(depot):
    _enreg(depot, jour="2026-06-08")
    _enreg(depot, jour="2026-05-15")
    _enreg(depot, jour="2026-07-02")
    dates = [s["date"] for s in depot.charger("snapshots")]
    assert dates == ["2026-05-15", "2026-06-08", "2026-07-02"]


def test_serie_mensuelle_vide(depot):
    assert svc.serie_mensuelle(depot) == []


def test_serie_mensuelle_un_point_par_mois(depot):
    # Deux snapshots en juin → seul le dernier compte
    _enreg(depot, jour="2026-06-01", total="1000")
    _enreg(depot, jour="2026-06-15", total="1200")
    _enreg(depot, jour="2026-07-10", total="1300")
    serie = svc.serie_mensuelle(depot)
    assert len(serie) == 2
    assert serie[0]["mois"] == "2026-06"
    assert serie[0]["portefeuille_total"] == Decimal("1200")
    assert serie[1]["mois"] == "2026-07"


def test_serie_mensuelle_limite_n_mois(depot):
    for m in range(1, 13):
        _enreg(depot, jour=f"2026-{m:02d}-15", total=str(1000 + m * 10))
    serie = svc.serie_mensuelle(depot, mois=3)
    assert len(serie) == 3
    assert [p["mois"] for p in serie] == ["2026-10", "2026-11", "2026-12"]


# --- Coordonnées SVG --------------------------------------------------------


def test_coordonnees_svg_vide():
    c = svc.coordonnees_svg([])
    assert c["polyline"] == ""
    assert c["labels_x"] == []


def test_coordonnees_svg_un_point():
    points = [{"mois": "2026-06", "portefeuille_total": Decimal("1000"),
               "cash_total": Decimal("0"), "valo_titres_total": Decimal("1000"),
               "pv_latente_total": Decimal("0"), "date": "2026-06-15"}]
    c = svc.coordonnees_svg(points, largeur=600, hauteur=180, marge=30)
    assert c["polyline"].count(",") == 1
    assert c["min"] == c["max"] == Decimal("1000")


def test_coordonnees_svg_polyline_format():
    points = [
        {"mois": "2026-05", "portefeuille_total": Decimal("1000"),
         "cash_total": Decimal("0"), "valo_titres_total": Decimal("0"),
         "pv_latente_total": Decimal("0"), "date": "2026-05-15"},
        {"mois": "2026-06", "portefeuille_total": Decimal("2000"),
         "cash_total": Decimal("0"), "valo_titres_total": Decimal("0"),
         "pv_latente_total": Decimal("0"), "date": "2026-06-15"},
    ]
    c = svc.coordonnees_svg(points, largeur=600, hauteur=180, marge=30)
    coords = c["polyline"].split()
    assert len(coords) == 2
    # 1er point doit être à gauche (x=marge), 2nd à droite
    x1 = int(coords[0].split(",")[0])
    x2 = int(coords[1].split(",")[0])
    assert x1 == 30  # marge
    assert x2 == 570  # largeur - marge
    # Le point le plus haut (2000€) doit être plus haut visuellement (y plus petit)
    y1 = int(coords[0].split(",")[1])
    y2 = int(coords[1].split(",")[1])
    assert y2 < y1
    # Champs d'enrichissement du graphique
    assert len(c["points_xy"]) == 2
    assert c["aire"].startswith("M ") and c["aire"].rstrip().endswith("Z")
    assert c["hausse"] is True  # 1000 → 2000


def test_coordonnees_svg_tendance_baisse():
    points = [
        {"mois": "2026-05", "portefeuille_total": Decimal("2000")},
        {"mois": "2026-06", "portefeuille_total": Decimal("1500")},
    ]
    c = svc.coordonnees_svg(points)
    assert c["hausse"] is False
