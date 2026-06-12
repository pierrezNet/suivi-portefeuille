"""Tests virements programmés : CRUD, rattrapage, idempotence, edge cases."""

from datetime import date
from pathlib import Path

import pytest

from app.services import virements_programmes as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("comptes", [
        {"id": "pea-bd", "nom": "PEA Bourse Direct", "type": "PEA"},
        {"id": "cto-bd", "nom": "CTO Bourse Direct", "type": "CTO"},
    ])
    d.enregistrer("titres", [
        {"id": "amundi-monde", "ticker": "PAEEM", "nom": "Amundi PEA Monde UCITS ETF"},
        {"id": "amundi-emer", "ticker": "PAEEM2", "nom": "Amundi PEA Emergent"},
    ])
    d.enregistrer("mouvements", [])
    d.enregistrer("evenements", [])
    d.enregistrer("virements_programmes", [])
    return d


# --- CRUD ----------------------------------------------------------------


def test_creer_virement_valide(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd",
        "montant": "100",
        "jour_du_mois": "1",
        "libelle": "Virement permanent",
        "date_debut": "2026-06-01",
    })
    assert vp["id"].startswith("vp-")
    assert vp["compte_id"] == "pea-bd"
    assert vp["montant"] == "100"
    assert vp["jour_du_mois"] == 1
    assert vp["actif"] is True


def test_compte_inconnu_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "compte_id": "fantome", "montant": "100",
            "jour_du_mois": "1", "date_debut": "2026-06-01",
        })
    assert "compte_id" in exc.value.erreurs


def test_montant_doit_etre_positif(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "compte_id": "pea-bd", "montant": "-10",
            "jour_du_mois": "1", "date_debut": "2026-06-01",
        })
    assert "montant" in exc.value.erreurs


def test_jour_hors_bornes_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "compte_id": "pea-bd", "montant": "100",
            "jour_du_mois": "32", "date_debut": "2026-06-01",
        })
    assert "jour_du_mois" in exc.value.erreurs


# --- _dates_echeance -----------------------------------------------------


def test_dates_echeance_simple():
    res = svc._dates_echeance(date(2026, 6, 1), date(2026, 9, 15), jour=1)
    assert res == [date(2026, 6, 1), date(2026, 7, 1),
                   date(2026, 8, 1), date(2026, 9, 1)]


def test_dates_echeance_jour_apres_debut():
    """Si jour=15 et date_debut=10 du mois, première échéance = 15 du même mois."""
    res = svc._dates_echeance(date(2026, 6, 10), date(2026, 7, 31), jour=15)
    assert res == [date(2026, 6, 15), date(2026, 7, 15)]


def test_dates_echeance_jour_avant_debut():
    """Si jour=5 et date_debut=10 du mois, première échéance = 5 du mois suivant."""
    res = svc._dates_echeance(date(2026, 6, 10), date(2026, 8, 31), jour=5)
    assert res == [date(2026, 7, 5), date(2026, 8, 5)]


def test_dates_echeance_jour_31_retombe_sur_dernier_jour():
    """31 février → 28 février (ou 29 en bissextile)."""
    res = svc._dates_echeance(date(2026, 1, 1), date(2026, 4, 30), jour=31)
    assert res == [
        date(2026, 1, 31),
        date(2026, 2, 28),  # 2026 n'est pas bissextile
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_dates_echeance_plage_vide():
    assert svc._dates_echeance(date(2026, 6, 1), date(2026, 5, 1), jour=1) == []


# --- rattraper -----------------------------------------------------------


def test_rattraper_cree_les_mouvements_manquants(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    # On simule "aujourd'hui = 2026-08-15"
    crees = svc.rattraper(depot, jusqu_a=date(2026, 8, 15))
    assert len(crees) == 3  # 01/06, 01/07, 01/08
    dates = sorted(m["date"] for m in crees)
    assert dates == ["2026-06-01", "2026-07-01", "2026-08-01"]
    # Les mouvements sont bien des alimentation_cash
    for m in crees:
        assert m["type"] == "alimentation_cash"
        assert m["compte_id"] == "pea-bd"
        assert m["montant"] == "100"
        assert m["id"].startswith("auto-")
        assert m["virement_programme_id"]


def test_rattraper_idempotent(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    svc.rattraper(depot, jusqu_a=date(2026, 8, 15))
    crees_2 = svc.rattraper(depot, jusqu_a=date(2026, 8, 15))
    assert crees_2 == []
    mouvements = depot.charger("mouvements")
    assert len(mouvements) == 3  # pas de doublon


def test_rattraper_ignore_inactif(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    svc.mettre_a_jour(depot, vp["id"], {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
        "actif": False,
    })
    crees = svc.rattraper(depot, jusqu_a=date(2026, 8, 15))
    assert crees == []


def test_rattraper_respecte_date_fin(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1",
        "date_debut": "2026-06-01",
        "date_fin": "2026-07-31",
    })
    crees = svc.rattraper(depot, jusqu_a=date(2026, 12, 31))
    assert len(crees) == 2  # 01/06 et 01/07 seulement
    assert sorted(m["date"] for m in crees) == ["2026-06-01", "2026-07-01"]


def test_rattraper_ne_cree_pas_dans_le_futur(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    # jusqu_a = 15/06, donc seul le 01/06 est passé
    crees = svc.rattraper(depot, jusqu_a=date(2026, 6, 15))
    assert len(crees) == 1
    assert crees[0]["date"] == "2026-06-01"


def test_rattraper_avec_mouvement_existant_deja_cree_ne_double_pas(depot):
    """Si un mouvement avec le même ID auto existe déjà, on ne le recrée pas."""
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    # On insère manuellement le mouvement attendu pour 01/06
    mvts = depot.charger("mouvements")
    mvts.append({
        "id": f"auto-{vp['id']}-2026-06-01",
        "type": "alimentation_cash", "compte_id": "pea-bd",
        "date": "2026-06-01", "montant": "100",
    })
    depot.enregistrer("mouvements", mvts)
    crees = svc.rattraper(depot, jusqu_a=date(2026, 6, 30))
    assert crees == []


# --- Périodicité & DCA (investissements programmés) ---------------------


def test_dates_echeance_trimestriel():
    res = svc._dates_echeance(
        date(2026, 1, 5), date(2026, 12, 31), jour=5, periodicite="trimestriel"
    )
    assert res == [date(2026, 1, 5), date(2026, 4, 5),
                   date(2026, 7, 5), date(2026, 10, 5)]


def test_dates_echeance_annuel():
    res = svc._dates_echeance(
        date(2024, 6, 1), date(2027, 12, 31), jour=1, periodicite="annuel"
    )
    assert res == [date(2024, 6, 1), date(2025, 6, 1),
                   date(2026, 6, 1), date(2027, 6, 1)]


def test_dates_echeance_one_shot():
    """one_shot : une seule échéance."""
    res = svc._dates_echeance(
        date(2026, 6, 1), date(2027, 12, 31), jour=10, periodicite="one_shot"
    )
    assert res == [date(2026, 6, 10)]


def test_dates_echeance_one_shot_jour_passe_dans_mois_courant():
    """one_shot : si jour saisi est avant date_debut dans le mois courant,
    bascule au mois suivant."""
    res = svc._dates_echeance(
        date(2026, 6, 15), date(2027, 12, 31), jour=5, periodicite="one_shot"
    )
    assert res == [date(2026, 7, 5)]


def test_creer_dca_avec_titre_et_periodicite(depot):
    vp = svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80",
        "jour_du_mois": "5", "date_debut": "2026-04-05",
        "periodicite": "mensuel", "titre_id": "amundi-monde",
        "libelle": "DCA Amundi PEA Monde",
    })
    assert vp["periodicite"] == "mensuel"
    assert vp["titre_id"] == "amundi-monde"


def test_periodicite_invalide_rejetee(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "compte_id": "pea-bd", "montant": "80",
            "jour_du_mois": "5", "date_debut": "2026-04-05",
            "periodicite": "quotidien",
        })
    assert "periodicite" in exc.value.erreurs


def test_titre_inconnu_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "compte_id": "pea-bd", "montant": "80",
            "jour_du_mois": "5", "date_debut": "2026-04-05",
            "titre_id": "fantome",
        })
    assert "titre_id" in exc.value.erreurs


def test_rattraper_dca_cree_evenements_pas_mouvements(depot):
    """Avec titre_id : rattrapage crée des événements rappel, pas des mouvements."""
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80",
        "jour_du_mois": "5", "date_debut": "2026-04-05",
        "periodicite": "mensuel", "titre_id": "amundi-monde",
    })
    crees = svc.rattraper(depot, jusqu_a=date(2026, 7, 15))
    # 5 avril, 5 mai, 5 juin, 5 juillet = 4 échéances
    assert len(crees) == 4
    for e in crees:
        assert e["id"].startswith("e-dca-")
        assert e["type"] == "rappel_personnel"
        assert e["titre_id"] == "amundi-monde"
        assert "DCA" in e["libelle"]
        assert "80" in e["libelle"]
    # Aucun mouvement créé
    assert depot.charger("mouvements") == []
    # Les événements sont bien persistés
    evts = depot.charger("evenements")
    assert len(evts) == 4


def test_rattraper_dca_idempotent(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "105",
        "jour_du_mois": "5", "date_debut": "2026-04-05",
        "periodicite": "trimestriel", "titre_id": "amundi-emer",
    })
    crees_1 = svc.rattraper(depot, jusqu_a=date(2026, 12, 31))
    crees_2 = svc.rattraper(depot, jusqu_a=date(2026, 12, 31))
    # avril, juillet, octobre = 3 échéances
    assert len(crees_1) == 3
    assert crees_2 == []
    assert len(depot.charger("evenements")) == 3


def test_rattraper_melange_cash_et_dca(depot):
    """Un programme cash et un programme DCA : chacun produit son artefact."""
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "100",
        "jour_du_mois": "1", "date_debut": "2026-06-01",
    })
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "80",
        "jour_du_mois": "5", "date_debut": "2026-06-05",
        "periodicite": "mensuel", "titre_id": "amundi-monde",
    })
    svc.rattraper(depot, jusqu_a=date(2026, 7, 15))
    mvts = depot.charger("mouvements")
    evts = depot.charger("evenements")
    # 2 alimentations cash (01/06, 01/07)
    assert len(mvts) == 2
    assert all(m["type"] == "alimentation_cash" for m in mvts)
    # 2 événements DCA (05/06, 05/07)
    assert len(evts) == 2
    assert all(e["type"] == "rappel_personnel" for e in evts)


def test_rattraper_dca_one_shot_une_seule_echeance(depot):
    svc.creer(depot, {
        "compte_id": "pea-bd", "montant": "500",
        "jour_du_mois": "15", "date_debut": "2026-04-01",
        "periodicite": "one_shot", "titre_id": "amundi-monde",
    })
    crees = svc.rattraper(depot, jusqu_a=date(2027, 1, 1))
    assert len(crees) == 1
    assert crees[0]["date"] == "2026-04-15"


# --- Récap actifs (bandeau page liste) --------------------------------------


def test_recap_actifs_mensuel_pur():
    from decimal import Decimal
    from app.routes.virements_programmes import _recap_actifs

    virements = [
        {"actif": True, "periodicite": "mensuel", "montant": "80", "titre_id": "x"},
        {"actif": True, "periodicite": "mensuel", "montant": "100", "titre_id": None},
    ]
    echeances = [
        {"date": "2026-07-01", "vp": virements[1]},
        {"date": "2026-07-05", "vp": virements[0]},
    ]
    recap = _recap_actifs(virements, echeances)
    assert recap["total_mensuel_eq"] == Decimal("180.00")
    assert recap["total_dca"] == Decimal("80.00")
    assert recap["total_cash"] == Decimal("100.00")
    assert recap["prochaine"]["date"] == "2026-07-01"
    assert recap["prochaine"]["is_dca"] is False


def test_recap_actifs_melange_periodicites():
    from decimal import Decimal
    from app.routes.virements_programmes import _recap_actifs

    virements = [
        {"actif": True, "periodicite": "mensuel", "montant": "80", "titre_id": "x"},
        {"actif": True, "periodicite": "trimestriel", "montant": "105", "titre_id": "y"},
        {"actif": True, "periodicite": "annuel", "montant": "1200", "titre_id": None},
        # one_shot et inactif ignorés
        {"actif": True, "periodicite": "one_shot", "montant": "500", "titre_id": "z"},
        {"actif": False, "periodicite": "mensuel", "montant": "999", "titre_id": None},
    ]
    recap = _recap_actifs(virements, [])
    # 80 + 105/3 + 1200/12 = 80 + 35 + 100 = 215
    assert recap["total_mensuel_eq"] == Decimal("215.00")
    assert recap["total_dca"] == Decimal("115.00")  # 80 + 35
    assert recap["total_cash"] == Decimal("100.00")
    assert recap["prochaine"] is None


def test_recap_actifs_aucune_echeance():
    from decimal import Decimal
    from app.routes.virements_programmes import _recap_actifs

    recap = _recap_actifs([], [])
    assert recap["total_mensuel_eq"] == Decimal("0")
    assert recap["total_dca"] == Decimal("0")
    assert recap["total_cash"] == Decimal("0")
    assert recap["prochaine"] is None
