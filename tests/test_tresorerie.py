"""Panneau Trésorerie : ventilation du cash, cash réservé par les ordres
d'achat en attente, disponible au comptant, et non-contamination de l'export
mobile."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.dashboard_data import construire
from app.services.soldes import calculer_solde_cash, calculer_ventilation_cash
from app.services.stockage import Depot
from app.services.watchlist import reserve_cash_par_compte
from tools.publier_dashboard import _enrichir_pour_export


# --- Ventilation du cash (soldes.py) -------------------------------------

_MVTS = [
    {"type": "alimentation_cash", "compte_id": "c", "montant": "1000"},
    {"type": "retrait_cash", "compte_id": "c", "montant": "50"},
    {"type": "achat", "compte_id": "c", "quantite": "2", "prix_unitaire": "100", "frais_courtage": "1"},
    {"type": "vente", "compte_id": "c", "quantite": "1", "prix_unitaire_vente": "150", "frais_courtage": "0.5"},
    {"type": "dividende_recu", "compte_id": "c", "montant_net_eur": "10"},
    {"type": "frais", "compte_id": "c", "montant": "3"},
    {"type": "alimentation_cash", "compte_id": "autre", "montant": "9999"},  # ignoré
]


def test_ventilation_cash_composantes():
    v = calculer_ventilation_cash(_MVTS, "c")
    assert v["versements"] == Decimal("1000.00")
    assert v["retraits"] == Decimal("50.00")
    assert v["achats"] == Decimal("201.00")   # 2×100 + 1
    assert v["ventes"] == Decimal("149.50")    # 1×150 − 0.5
    assert v["dividendes"] == Decimal("10.00")
    assert v["frais"] == Decimal("3.00")
    # solde = 1000 + 149.5 + 10 − 201 − 3 − 50
    assert v["solde"] == Decimal("905.50")


def test_solde_cash_egale_ventilation_solde():
    assert calculer_solde_cash(_MVTS, "c") == calculer_ventilation_cash(_MVTS, "c")["solde"]


def test_ventilation_dividende_brut_si_pas_de_net():
    mvts = [{"type": "dividende_recu", "compte_id": "c", "montant_brut_total": "20"}]
    assert calculer_ventilation_cash(mvts, "c")["dividendes"] == Decimal("20.00")


# --- Cash réservé par les ordres d'achat (watchlist.py) ------------------

def test_reserve_groupe_par_compte_cible():
    wl = [
        {"ticker": "DSY", "compte_cible": "pea-bd", "ordres_actifs": [
            {"prix_limite": "17", "quantite": 5, "sens": "achat",
             "statut": "en_attente", "validite": "2026-07-31"},
        ]},
        {"ticker": "MU", "compte_cible": "cto-bd", "ordres_actifs": [
            {"prix_limite": "10", "quantite": 2, "sens": "achat", "statut": "en_attente"},
        ]},
    ]
    r = reserve_cash_par_compte(wl, today_iso="2026-07-08")
    assert r["pea-bd"]["total"] == Decimal("85.00")
    assert r["cto-bd"]["total"] == Decimal("20.00")
    assert r["pea-bd"]["ordres"][0]["montant"] == Decimal("85.00")
    assert r["pea-bd"]["ordres"][0]["ticker"] == "DSY"


def test_reserve_exclut_ventes_non_attente_expires_et_sans_compte():
    wl = [
        {"ticker": "P", "compte_cible": "pea-bd", "ordres_actifs": [
            {"prix_limite": "12", "quantite": 8, "sens": "vente", "statut": "en_attente"},
            {"prix_limite": "60", "quantite": 2, "sens": "achat", "statut": "annule"},
            {"prix_limite": "100", "quantite": 1, "sens": "achat",
             "statut": "en_attente", "validite": "2026-06-01"},  # expiré
        ]},
        {"ticker": "N", "ordres_actifs": [  # pas de compte_cible
            {"prix_limite": "50", "quantite": 1, "sens": "achat", "statut": "en_attente"},
        ]},
    ]
    assert reserve_cash_par_compte(wl, today_iso="2026-07-08") == {}


def test_reserve_sens_absent_compte_comme_achat():
    wl = [{"ticker": "X", "compte_cible": "pea-bd", "ordres_actifs": [
        {"prix_limite": "10", "quantite": 3, "statut": "en_attente"},  # sens absent
    ]}]
    r = reserve_cash_par_compte(wl, today_iso="2026-07-08")
    assert r["pea-bd"]["total"] == Decimal("30.00")


# --- Intégration dashboard : reproduit les chiffres réels ----------------

@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea-bd", "nom": "PEA BD", "type": "PEA"}])
    d.enregistrer("titres", [
        {"id": "dsy", "ticker": "DSY", "nom": "Dassault",
         "cours_jour_eur": "18", "date_cours_jour": "2026-07-08"},
    ])
    d.enregistrer("mouvements", [
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea-bd",
         "date": "2026-06-01", "montant": "400"},
        {"id": "m2", "type": "achat", "compte_id": "pea-bd", "titre_id": "dsy",
         "date": "2026-06-24", "quantite": "5", "prix_unitaire": "18.394",
         "frais_courtage": "0"},   # 5 × 18.394 = 91.97 → solde 308.03
    ])
    d.enregistrer("watchlist", [{
        "nom": "Dassault", "ticker": "DSY", "titre_id": "dsy",
        "compte_cible": "pea-bd",
        "ordres_actifs": [{
            "id": "o1", "prix_limite": "17", "quantite": 5, "sens": "achat",
            "statut": "en_attente", "validite": "2026-07-31",
        }],
    }])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    return d


def test_construire_tresorerie_par_compte(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 7, 8))
    tr = data["comptes"][0]["tresorerie"]
    assert tr["versements"] == Decimal("400.00")
    assert tr["achats"] == Decimal("91.97")
    assert tr["solde_especes"] == Decimal("308.03")
    assert tr["reserve_total"] == Decimal("85.00")
    assert tr["disponible_comptant"] == Decimal("223.03")
    assert len(tr["ordres_reserve"]) == 1
    assert tr["ordres_reserve"][0]["montant"] == Decimal("85.00")


def test_construire_totaux_disponible_globaux(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 7, 8))
    assert data["total_reserve_ordres"] == Decimal("85.00")
    assert data["total_disponible_comptant"] == Decimal("223.03")


def test_disponible_egale_solde_sans_ordre(tmp_path):
    d = Depot(tmp_path)
    d.enregistrer("comptes", [{"id": "pea-bd", "nom": "PEA", "type": "PEA"}])
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea-bd",
         "date": "2026-06-01", "montant": "200"},
    ])
    d.enregistrer("watchlist", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    data = construire(d, rattraper_virements=False, aujourd_hui=date(2026, 7, 8))
    tr = data["comptes"][0]["tresorerie"]
    assert tr["reserve_total"] == Decimal("0.00")
    assert tr["disponible_comptant"] == tr["solde_especes"] == Decimal("200.00")


# --- Export mobile strictement inchangé ----------------------------------

def test_dashboard_page_rend_la_tresorerie(depot):
    """Le tableau de bord (/) s'affiche et montre le KPI + la cascade."""
    from app import create_app

    app = create_app()
    app.config.update(DEPOT=depot, TESTING=True, SECRET_KEY="test")
    with app.test_client() as c:
        rep = c.get("/")
    html = rep.get_data(as_text=True)
    assert rep.status_code == 200
    assert "Disponible au comptant" in html
    assert "Trésorerie" in html
    assert "223,03" in html  # disponible calculé, formaté par |euros


def test_export_mobile_ne_contient_pas_la_tresorerie(depot):
    data = construire(depot, rattraper_virements=False, aujourd_hui=date(2026, 7, 8))
    out = _enrichir_pour_export(data)
    # rien de la trésorerie ne fuit dans la charge utile mobile
    assert "total_disponible_comptant" not in out
    assert "total_reserve_ordres" not in out
    assert all("tresorerie" not in c for c in out["comptes"])
    # ...mais le dict d'origine (desktop) reste intact
    assert "tresorerie" in data["comptes"][0]
    assert "total_disponible_comptant" in data
