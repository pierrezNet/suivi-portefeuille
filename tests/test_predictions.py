"""Tests CRUD prédictions + évaluation + statistiques."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.services import predictions as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STMicro", "devise": "EUR"},
        {"id": "net", "ticker": "NET", "nom": "Cloudflare", "devise": "USD"},
    ])
    d.enregistrer("predictions", [])
    return d


def _payload_valide(**override):
    base = {
        "titre_id": "stm",
        "sens": "hausse",
        "date_prediction": "2026-06-03",
        "date_echeance": "2026-09-01",
        "cours_reference": "38.72",
        "conviction": "3",
        "raisonnement": "Test.",
    }
    base.update({k: ("" if v is None else v) for k, v in override.items()})
    return base


# --- Création ---------------------------------------------------------------


def test_creer_genere_id_statut_et_echeance(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    assert p["id"].startswith("p-")
    assert p["statut"] == "en_cours"
    assert p["resultat"] is None
    assert p["cours_echeance"] is None
    assert p["date_echeance"] == "2026-09-01"
    # horizon_jours dérivé : 2026-06-03 → 2026-09-01 = 90 jours
    assert p["horizon_jours"] == 90


def test_creer_auto_complete_ticker_nom_depuis_titre(depot):
    p = svc.creer_prediction(depot, _payload_valide(ticker="", nom="", devise=""))
    assert p["ticker"] == "STMPA"
    assert p["nom"] == "STMicro"
    assert p["devise"] == "EUR"


def test_creer_sans_titre_id_accepte_saisie_libre(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        titre_id="", ticker="XYZ", nom="Société Libre", devise="EUR",
    ))
    assert p["titre_id"] is None
    assert p["ticker"] == "XYZ"


def test_creer_sans_titre_id_et_sans_ticker_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(titre_id="", ticker="", nom=""))
    assert "ticker" in exc.value.erreurs
    assert "nom" in exc.value.erreurs


def test_creer_titre_id_inconnu_rejete(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(titre_id="fantome"))
    assert "titre_id" in exc.value.erreurs


def test_creer_sens_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(sens="lateral"))
    assert "sens" in exc.value.erreurs


def test_creer_sens_obligatoire(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(sens=""))
    assert "sens" in exc.value.erreurs


def test_creer_cours_doit_etre_strictement_positif(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(cours_reference="0"))
    assert "cours_reference" in exc.value.erreurs

    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(cours_reference="-1"))
    assert "cours_reference" in exc.value.erreurs


def test_creer_conviction_hors_bornes(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(conviction="6"))
    assert "conviction" in exc.value.erreurs


def test_creer_date_echeance_doit_etre_posterieure(depot):
    # Égale à la date de prédiction → rejet
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(
            date_prediction="2026-06-03", date_echeance="2026-06-03",
        ))
    assert "date_echeance" in exc.value.erreurs

    # Antérieure → rejet
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(
            date_prediction="2026-06-03", date_echeance="2026-05-01",
        ))
    assert "date_echeance" in exc.value.erreurs


def test_creer_date_echeance_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(date_echeance="01/09/2026"))
    assert "date_echeance" in exc.value.erreurs


def test_creer_date_invalide(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer_prediction(depot, _payload_valide(date_prediction="03/06/2026"))
    assert "date_prediction" in exc.value.erreurs


def test_creer_accepte_virgule_decimale_francaise(depot):
    p = svc.creer_prediction(depot, _payload_valide(cours_reference="38,72"))
    assert p["cours_reference"] == "38.72"


def test_cours_stocke_en_string(depot):
    p = svc.creer_prediction(depot, _payload_valide(cours_reference="38.72"))
    assert isinstance(p["cours_reference"], str)


# --- Évaluation : 4 combinaisons sens / résultat ----------------------------


def test_evaluation_hausse_juste(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "110")
    assert res["statut"] == "evaluee"
    assert res["resultat"] == "juste"
    assert res["cours_echeance"] == "110"


def test_evaluation_hausse_fausse(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "95")
    assert res["resultat"] == "faux"


def test_evaluation_baisse_juste(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="baisse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "85")
    assert res["resultat"] == "juste"


def test_evaluation_baisse_fausse(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="baisse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "120")
    assert res["resultat"] == "faux"


# --- Cas limite documenté : égalité stricte = faux --------------------------


def test_evaluation_egalite_hausse_est_fausse(depot):
    """Convention : aucune variation = prédiction de mouvement non confirmée."""
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "100")
    assert res["resultat"] == "faux"
    assert res["ecart_pct"] == "0.00"


def test_evaluation_egalite_baisse_est_fausse(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="baisse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "100")
    assert res["resultat"] == "faux"


# --- Calcul ecart_pct : précision Decimal et arrondi ROUND_HALF_UP ----------


def test_ecart_pct_arrondi_2_decimales(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="38.72",
    ))
    # 42.10 vs 38.72 → +8.7293... % → 8.73 (ROUND_HALF_UP)
    res = svc.evaluer_prediction(depot, p["id"], "42.10")
    assert res["ecart_pct"] == "8.73"


def test_ecart_pct_round_half_up_strict(depot):
    """0.005 doit s'arrondir à 0.01 et non 0.00 (différence vs banker's rounding)."""
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="200",
    ))
    # 200 → 200.01 = +0.005 % exact → ROUND_HALF_UP → 0.01
    res = svc.evaluer_prediction(depot, p["id"], "200.01")
    assert res["ecart_pct"] == "0.01"


def test_ecart_pct_negatif(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        sens="baisse", cours_reference="100",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "85")
    assert res["ecart_pct"] == "-15.00"


def test_ecart_pct_calcule_en_decimal(depot):
    """Vérifie qu'on n'a pas un artefact float (ex: 0.1 + 0.2 = 0.30000004)."""
    p = svc.creer_prediction(depot, _payload_valide(
        sens="hausse", cours_reference="0.1",
    ))
    res = svc.evaluer_prediction(depot, p["id"], "0.3")
    # (0.3 - 0.1) / 0.1 * 100 = 200 exact, pas 199.999...
    assert res["ecart_pct"] == "200.00"


# --- Garde-fous évaluation --------------------------------------------------


def test_evaluation_cours_invalide(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.evaluer_prediction(depot, p["id"], "-1")
    assert "cours_echeance" in exc.value.erreurs


def test_evaluation_id_inconnu(depot):
    with pytest.raises(KeyError):
        svc.evaluer_prediction(depot, "p-fantome", "42")


def test_evaluation_deja_evaluee_rejetee(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    svc.evaluer_prediction(depot, p["id"], "42")
    with pytest.raises(ValueError):
        svc.evaluer_prediction(depot, p["id"], "43")


# --- taux_reussite ----------------------------------------------------------


def _creer_et_evaluer(depot, sens, conviction, cours_ref, cours_ech):
    p = svc.creer_prediction(depot, _payload_valide(
        sens=sens, conviction=str(conviction), cours_reference=cours_ref,
    ))
    svc.evaluer_prediction(depot, p["id"], cours_ech)


def test_taux_reussite_vide(depot):
    stats = svc.taux_reussite(depot)
    assert stats["total_evaluees"] == 0
    assert stats["taux_global_pct"] is None
    assert stats["par_sens"]["hausse"]["taux_pct"] is None


def test_taux_reussite_ignore_les_en_cours(depot):
    svc.creer_prediction(depot, _payload_valide())  # reste en_cours
    _creer_et_evaluer(depot, "hausse", 3, "100", "110")
    stats = svc.taux_reussite(depot)
    assert stats["total_evaluees"] == 1
    assert stats["total_justes"] == 1


def test_taux_reussite_global_et_par_sens(depot):
    # Hausse : 2 justes / 3
    _creer_et_evaluer(depot, "hausse", 3, "100", "110")  # juste
    _creer_et_evaluer(depot, "hausse", 3, "100", "120")  # juste
    _creer_et_evaluer(depot, "hausse", 3, "100", "95")   # faux
    # Baisse : 1 juste / 2
    _creer_et_evaluer(depot, "baisse", 3, "100", "85")   # juste
    _creer_et_evaluer(depot, "baisse", 3, "100", "120")  # faux

    stats = svc.taux_reussite(depot)
    assert stats["total_evaluees"] == 5
    assert stats["total_justes"] == 3
    # 3/5 = 60.00
    assert stats["taux_global_pct"] == Decimal("60.00")

    assert stats["par_sens"]["hausse"]["total"] == 3
    assert stats["par_sens"]["hausse"]["justes"] == 2
    # 2/3 = 66.666... → 66.67
    assert stats["par_sens"]["hausse"]["taux_pct"] == Decimal("66.67")

    assert stats["par_sens"]["baisse"]["total"] == 2
    assert stats["par_sens"]["baisse"]["justes"] == 1
    assert stats["par_sens"]["baisse"]["taux_pct"] == Decimal("50.00")


def test_taux_reussite_par_conviction(depot):
    _creer_et_evaluer(depot, "hausse", 5, "100", "110")  # juste, c5
    _creer_et_evaluer(depot, "hausse", 5, "100", "90")   # faux, c5
    _creer_et_evaluer(depot, "hausse", 1, "100", "110")  # juste, c1

    stats = svc.taux_reussite(depot)
    assert stats["par_conviction"][5]["total"] == 2
    assert stats["par_conviction"][5]["justes"] == 1
    assert stats["par_conviction"][5]["taux_pct"] == Decimal("50.00")
    assert stats["par_conviction"][1]["total"] == 1
    assert stats["par_conviction"][1]["taux_pct"] == Decimal("100.00")
    # Convictions absentes : présentes avec total=0
    assert stats["par_conviction"][3]["total"] == 0
    assert stats["par_conviction"][3]["taux_pct"] is None


def test_taux_reussite_filtre_par_sens(depot):
    _creer_et_evaluer(depot, "hausse", 3, "100", "110")  # juste
    _creer_et_evaluer(depot, "baisse", 3, "100", "120")  # faux
    stats = svc.taux_reussite(depot, filtre={"sens": "hausse"})
    assert stats["total_evaluees"] == 1
    assert stats["total_justes"] == 1


# --- lister / supprimer / échéances dépassées -------------------------------


def test_lister_filtre_par_statut(depot):
    p1 = svc.creer_prediction(depot, _payload_valide())
    svc.creer_prediction(depot, _payload_valide(sens="baisse"))
    svc.evaluer_prediction(depot, p1["id"], "42")
    en_cours = svc.lister(depot, statut="en_cours")
    evaluees = svc.lister(depot, statut="evaluee")
    assert len(en_cours) == 1
    assert len(evaluees) == 1


def test_lister_filtre_par_sens(depot):
    svc.creer_prediction(depot, _payload_valide(sens="hausse"))
    svc.creer_prediction(depot, _payload_valide(sens="baisse"))
    assert len(svc.lister(depot, sens="hausse")) == 1
    assert len(svc.lister(depot, sens="baisse")) == 1


def test_lister_trie_par_date_decroissante(depot):
    svc.creer_prediction(depot, _payload_valide(date_prediction="2026-01-15"))
    svc.creer_prediction(depot, _payload_valide(date_prediction="2026-06-03"))
    svc.creer_prediction(depot, _payload_valide(date_prediction="2026-04-01"))
    res = svc.lister(depot)
    dates = [p["date_prediction"] for p in res]
    assert dates == ["2026-06-03", "2026-04-01", "2026-01-15"]


def test_mettre_a_jour_preserve_id_et_date_creation(depot):
    p = svc.creer_prediction(depot, _payload_valide(cours_reference="100"))
    nouveau = svc.mettre_a_jour(depot, p["id"], _payload_valide(
        cours_reference="120", conviction="5",
    ))
    assert nouveau["id"] == p["id"]
    assert nouveau["date_creation"] == p["date_creation"]
    assert nouveau["cours_reference"] == "120"
    assert nouveau["conviction"] == 5


def test_mettre_a_jour_recalcule_horizon(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        date_prediction="2026-06-03", date_echeance="2026-09-01",
    ))
    assert p["horizon_jours"] == 90
    nouveau = svc.mettre_a_jour(depot, p["id"], _payload_valide(
        date_prediction="2026-06-03", date_echeance="2026-11-30",
    ))
    assert nouveau["date_echeance"] == "2026-11-30"
    assert nouveau["horizon_jours"] == 180


def test_mettre_a_jour_rejette_si_evaluee(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    svc.evaluer_prediction(depot, p["id"], "42")
    with pytest.raises(ValueError):
        svc.mettre_a_jour(depot, p["id"], _payload_valide(cours_reference="50"))


def test_mettre_a_jour_id_inconnu(depot):
    with pytest.raises(KeyError):
        svc.mettre_a_jour(depot, "p-fantome", _payload_valide())


def test_mettre_a_jour_validation(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.mettre_a_jour(depot, p["id"], _payload_valide(sens="bidon"))
    assert "sens" in exc.value.erreurs


def test_supprimer(depot):
    p = svc.creer_prediction(depot, _payload_valide())
    assert svc.supprimer(depot, p["id"]) is True
    assert svc.trouver(depot, p["id"]) is None
    assert svc.supprimer(depot, "p-fantome") is False


def test_echeances_depassees(depot):
    # Échéance 2026-04-01 (passée à la date pivot)
    svc.creer_prediction(depot, _payload_valide(
        date_prediction="2026-01-01", date_echeance="2026-04-01",
    ))
    # Échéance 2026-12-30 (future)
    svc.creer_prediction(depot, _payload_valide(
        date_prediction="2026-10-01", date_echeance="2026-12-30",
    ))
    depassees = svc.echeances_depassees(depot, aujourdhui="2026-06-15")
    assert len(depassees) == 1
    assert depassees[0]["date_echeance"] == "2026-04-01"


def test_echeances_depassees_ignore_evaluees(depot):
    p = svc.creer_prediction(depot, _payload_valide(
        date_prediction="2026-01-01", date_echeance="2026-04-01",
    ))
    svc.evaluer_prediction(depot, p["id"], "42")
    assert svc.echeances_depassees(depot, aujourdhui="2026-06-15") == []
