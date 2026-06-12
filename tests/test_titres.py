"""Tests CRUD titres + versioning des thèses."""

from pathlib import Path

import pytest

from app.services import titres as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [])
    d.enregistrer("mouvements", [])
    return d


def test_creer_titre_genere_id_depuis_ticker(depot):
    t = svc.creer(depot, {"ticker": "stm", "nom": "STMicroelectronics"})
    assert t["id"] == "stm"
    assert t["ticker"] == "STM"
    assert t["nom"] == "STMicroelectronics"
    assert t["devise"] == "EUR"
    assert "date_creation" in t


def test_creer_titre_id_unique_avec_collision(depot):
    svc.creer(depot, {"ticker": "stm", "nom": "STM 1"})
    t2 = svc.creer(depot, {"ticker": "stm", "nom": "STM 2"})
    assert t2["id"] == "stm-2"


def test_validation_champs_obligatoires(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {})
    assert "ticker" in exc.value.erreurs


def test_versioning_these_modifiee(depot):
    t = svc.creer(depot, {
        "ticker": "stm", "nom": "STM",
        "these_lt": "Acteur européen.",
        "signaux_mt_positifs": "Reprise commandes",
    })
    # Modification de la thèse
    svc.mettre_a_jour(depot, t["id"], {
        "ticker": "stm", "nom": "STM",
        "these_lt": "Acteur européen, plus convaincu maintenant.",
        "signaux_mt_positifs": "Reprise commandes",
    })
    apres = svc.trouver(depot, t["id"])
    assert "historique_theses" in apres
    assert len(apres["historique_theses"]) == 1
    snap = apres["historique_theses"][0]
    assert snap["valeurs"]["these_lt"] == "Acteur européen."
    # Le snapshot conserve aussi les autres champs versionnés (signaux_mt_+/-)
    assert "signaux_mt_positifs" in snap["valeurs"]
    # perspectives n'est plus versionné depuis la fusion thèse/journal
    assert "perspectives" not in snap["valeurs"]


def test_versioning_pas_de_snapshot_si_seul_champ_libre_change(depot):
    """Modifier le secteur ou un champ non-versionné ne doit PAS créer de snapshot."""
    t = svc.creer(depot, {"ticker": "stm", "nom": "STM", "these_lt": "T1"})
    svc.mettre_a_jour(depot, t["id"], {
        "ticker": "stm", "nom": "STM",
        "these_lt": "T1",  # inchangée
        "secteur": "Semi-conducteurs",  # nouveau champ libre
    })
    apres = svc.trouver(depot, t["id"])
    assert "historique_theses" not in apres
    assert apres["secteur"] == "Semi-conducteurs"


def test_versioning_cumule_plusieurs_modifications(depot):
    t = svc.creer(depot, {"ticker": "stm", "nom": "STM", "these_lt": "v1"})
    svc.mettre_a_jour(depot, t["id"], {
        "ticker": "stm", "nom": "STM", "these_lt": "v2"
    })
    svc.mettre_a_jour(depot, t["id"], {
        "ticker": "stm", "nom": "STM", "these_lt": "v3"
    })
    apres = svc.trouver(depot, t["id"])
    assert len(apres["historique_theses"]) == 2
    # Les snapshots sont dans l'ordre chronologique : ancien d'abord
    assert apres["historique_theses"][0]["valeurs"]["these_lt"] == "v1"
    assert apres["historique_theses"][1]["valeurs"]["these_lt"] == "v2"
    assert apres["these_lt"] == "v3"


def test_suppression_bloquee_si_titre_reference(depot):
    svc.creer(depot, {"ticker": "stm", "nom": "STM"})
    depot.enregistrer("mouvements", [
        {"id": "m1", "type": "achat", "compte_id": "c1",
         "titre_id": "stm", "date": "2026-01-01", "quantite": 1,
         "prix_unitaire": "10"}
    ])
    with pytest.raises(ValueError, match="référencé"):
        svc.supprimer(depot, "stm")


def test_suppression_ok_si_pas_reference(depot):
    svc.creer(depot, {"ticker": "stm", "nom": "STM"})
    assert svc.supprimer(depot, "stm") is True
    assert svc.trouver(depot, "stm") is None


# --- Actualisation Yahoo (via la route) ------------------------------------


@pytest.fixture
def client(depot):
    from app import create_app

    app = create_app()
    app.config["DEPOT"] = depot
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c


def test_actualiser_yahoo_ecrase_chiffres_conserve_qualitatif(client, depot, monkeypatch):
    """Les chiffres financiers sont écrasés, les champs qualitatifs conservés."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "IFX",
        "nom": "Infineon Technologies AG",
        "marche": "Xetra (Deutsche Börse)",
        "devise": "EUR",
        "these_lt": "Leader semi-conducteurs de puissance.",
        "signaux_mt_positifs": "SiC montée.",
        "secteur": "Semi-conducteurs (Power, SiC, Auto)",
        "cap_boursiere_m": "50000",
        "dette_nette_m": "6000",
    })
    # Simule un champ legacy (perspectives) injecté directement dans le JSON
    items = depot.charger("titres")
    items[0]["perspectives"] = "Cycle haut anticipé."
    depot.enregistrer("titres", items)
    monkeypatch.setattr(
        yahoo,
        "enrichir_pour_titre",
        lambda *a, **k: {
            "cap_boursiere_m": "95409",
            "dette_nette_m": "6141",
            "valeur_entreprise_m": "101550",
            "dividende_par_action": "0.35",
            "frequence_dividende": "annuel",
            "verse_dividende": True,
        },
    )

    rep = client.post("/titres/ifx/actualiser-yahoo", follow_redirects=False)
    assert rep.status_code == 302

    t = svc.trouver(depot, "ifx")
    # Chiffres écrasés
    assert t["cap_boursiere_m"] == "95409"
    assert t["dette_nette_m"] == "6141"
    assert t["valeur_entreprise_m"] == "101550"
    assert t["dividende_par_action"] == "0.35"
    # Qualitatifs intacts
    assert t["these_lt"] == "Leader semi-conducteurs de puissance."
    assert t["signaux_mt_positifs"] == "SiC montée."
    assert t["perspectives"] == "Cycle haut anticipé."
    assert t["secteur"] == "Semi-conducteurs (Power, SiC, Auto)"
    assert t["marche"] == "Xetra (Deutsche Börse)"


def test_actualiser_yahoo_echec_pas_de_modif(client, depot, monkeypatch):
    """Si Yahoo ne renvoie rien, le titre reste inchangé."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "XYZ", "nom": "Test", "marche": "Mars",
        "cap_boursiere_m": "100",
    })
    monkeypatch.setattr(yahoo, "enrichir_pour_titre", lambda *a, **k: None)

    rep = client.post("/titres/xyz/actualiser-yahoo", follow_redirects=False)
    assert rep.status_code == 302
    t = svc.trouver(depot, "xyz")
    assert t["cap_boursiere_m"] == "100"  # inchangé


def test_actualiser_yahoo_aucun_changement_ne_modifie_pas(client, depot, monkeypatch):
    """Si Yahoo retourne les mêmes chiffres, no-op."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "STM", "nom": "STM", "marche": "Euronext Paris",
        "cap_boursiere_m": "25300",
    })
    monkeypatch.setattr(
        yahoo,
        "enrichir_pour_titre",
        lambda *a, **k: {"cap_boursiere_m": "25300"},
    )

    rep = client.post("/titres/stm/actualiser-yahoo", follow_redirects=False)
    assert rep.status_code == 302
    # Aucune modification (pas de versioning thèse inutile)
    t = svc.trouver(depot, "stm")
    assert "historique_theses" not in t
    # Et pas d'historique Yahoo non plus
    assert "historique_yahoo" not in t


def test_actualiser_yahoo_pousse_snapshot_dans_historique(client, depot, monkeypatch):
    """Quand les chiffres changent, l'ancien état est sauvegardé."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "PARRO", "nom": "Parrot", "marche": "Euronext Paris",
        "cap_boursiere_m": "405", "dette_nette_m": "35",
        "valeur_entreprise_m": "370",
    })
    monkeypatch.setattr(
        yahoo,
        "enrichir_pour_titre",
        lambda *a, **k: {
            "cap_boursiere_m": "355",
            "dette_nette_m": "-15",
            "valeur_entreprise_m": "342",
        },
    )

    client.post("/titres/parro/actualiser-yahoo")
    t = svc.trouver(depot, "parro")

    # Chiffres écrasés
    assert t["cap_boursiere_m"] == "355"
    assert t["dette_nette_m"] == "-15"
    assert t["valeur_entreprise_m"] == "342"

    # Historique poussé
    assert "historique_yahoo" in t
    assert len(t["historique_yahoo"]) == 1
    snap = t["historique_yahoo"][0]
    assert "date" in snap
    assert snap["valeurs"]["cap_boursiere_m"] == "405"
    assert snap["valeurs"]["dette_nette_m"] == "35"
    assert snap["valeurs"]["valeur_entreprise_m"] == "370"


def test_actualiser_yahoo_snapshot_ne_contient_que_les_champs_modifies(client, depot, monkeypatch):
    """Si seule la cap change, le snapshot ne contient que cap_boursiere_m."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "X", "nom": "X", "marche": "Euronext Paris",
        "cap_boursiere_m": "1000",
        "dette_nette_m": "100",
        "valeur_entreprise_m": "1100",
    })
    monkeypatch.setattr(
        yahoo,
        "enrichir_pour_titre",
        lambda *a, **k: {
            "cap_boursiere_m": "1200",   # change
            "dette_nette_m": "100",       # identique
            "valeur_entreprise_m": "1100",  # identique
        },
    )
    client.post("/titres/x/actualiser-yahoo")
    t = svc.trouver(depot, "x")
    assert "historique_yahoo" in t
    snap = t["historique_yahoo"][0]
    # Seul cap_boursiere_m est dans le snapshot
    assert set(snap["valeurs"].keys()) == {"cap_boursiere_m"}
    assert snap["valeurs"]["cap_boursiere_m"] == "1000"


def test_actualiser_yahoo_historique_cumule(client, depot, monkeypatch):
    """Plusieurs actualisations successives accumulent dans l'historique."""
    from app.services import yahoo

    svc.creer(depot, {
        "ticker": "PARRO", "nom": "Parrot", "marche": "Euronext Paris",
        "cap_boursiere_m": "405",
    })
    # 1ère actualisation : 405 → 355
    monkeypatch.setattr(
        yahoo, "enrichir_pour_titre", lambda *a, **k: {"cap_boursiere_m": "355"}
    )
    client.post("/titres/parro/actualiser-yahoo")
    # 2ème : 355 → 380
    monkeypatch.setattr(
        yahoo, "enrichir_pour_titre", lambda *a, **k: {"cap_boursiere_m": "380"}
    )
    client.post("/titres/parro/actualiser-yahoo")

    t = svc.trouver(depot, "parro")
    assert t["cap_boursiere_m"] == "380"
    assert len(t["historique_yahoo"]) == 2
    assert t["historique_yahoo"][0]["valeurs"]["cap_boursiere_m"] == "405"
    assert t["historique_yahoo"][1]["valeurs"]["cap_boursiere_m"] == "355"
