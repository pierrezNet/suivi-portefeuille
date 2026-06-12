"""Tests CRUD watchlist."""

from pathlib import Path

import pytest

from app.services import watchlist as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("watchlist", [])
    return d


def test_creer_watch_avec_ticker_seul(depot):
    w = svc.creer(depot, {"ticker": "ifx"})
    assert w["ticker"] == "IFX"
    assert w["statut"] == "actif"
    assert w["priorite"] == "moyenne"
    assert w["id"].startswith("w-")
    assert "ajoute_le" in w


def test_creation_invalide_sans_nom_ni_ticker(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {})
    assert "nom" in exc.value.erreurs


def test_paliers_rachat_depuis_lignes(depot):
    w = svc.creer(depot, {
        "nom": "Soitec",
        "paliers_prix": "80\n65\n50",
        "paliers_tranche": "1/3\n1/3\n1/3",
        "paliers_commentaire": "Premier\nRenforcement\nFinal",
    })
    assert len(w["paliers_rachat"]) == 3
    assert w["paliers_rachat"][0] == {
        "prix": "80", "tranche": "1/3", "commentaire": "Premier"
    }
    assert w["paliers_rachat"][2]["prix"] == "50"


def test_paliers_invalides(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {
            "nom": "X",
            "paliers_prix": "abc",
        })
    assert "paliers_rachat" in exc.value.erreurs


def test_lister_filtre_priorite(depot):
    svc.creer(depot, {"nom": "A", "priorite": "haute"})
    svc.creer(depot, {"nom": "B", "priorite": "basse"})
    res = svc.lister(depot, priorite="haute")
    assert len(res) == 1
    assert res[0]["nom"] == "A"


def test_lister_tri_par_priorite(depot):
    svc.creer(depot, {"nom": "Z basse", "priorite": "basse"})
    svc.creer(depot, {"nom": "A haute", "priorite": "haute"})
    svc.creer(depot, {"nom": "M moyenne", "priorite": "moyenne"})
    res = svc.lister(depot)
    assert [w["nom"] for w in res] == ["A haute", "M moyenne", "Z basse"]


def test_mise_a_jour_preserve_id(depot):
    w = svc.creer(depot, {"nom": "STM"})
    apres = svc.mettre_a_jour(depot, w["id"], {"nom": "STMicro"})
    assert apres["id"] == w["id"]
    assert apres["nom"] == "STMicro"


def test_validation_echeance_format(depot):
    with pytest.raises(svc.ErreursValidation) as exc:
        svc.creer(depot, {"nom": "X", "echeance_abandon": "06/05/2027"})
    assert "echeance_abandon" in exc.value.erreurs


def test_bascule_actif_vers_renforcement(depot):
    """Une watch en `actif` liée à un titre bascule en `renforcement`."""
    w = svc.creer(depot, {
        "nom": "X", "titre_id": "stm", "statut": "actif",
    })
    modifies = svc.basculer_actif_vers_renforcement(depot, "stm")
    assert modifies == [w["id"]]
    apres = svc.trouver(depot, w["id"])
    assert apres["statut"] == "renforcement"


def test_bascule_ignore_les_autres_statuts(depot):
    """Une watch déjà en renforcement, ipo_attendue, etc. n'est pas touchée."""
    w_renf = svc.creer(depot, {
        "nom": "X", "titre_id": "soi", "statut": "renforcement",
    })
    w_rachat = svc.creer(depot, {
        "nom": "Y", "titre_id": "soi", "statut": "rachat_potentiel",
    })
    modifies = svc.basculer_actif_vers_renforcement(depot, "soi")
    assert modifies == []
    assert svc.trouver(depot, w_renf["id"])["statut"] == "renforcement"
    assert svc.trouver(depot, w_rachat["id"])["statut"] == "rachat_potentiel"


def test_bascule_filtre_par_titre(depot):
    """Seul le titre concerné est modifié."""
    w_stm = svc.creer(depot, {
        "nom": "STM", "titre_id": "stm", "statut": "actif",
    })
    w_net = svc.creer(depot, {
        "nom": "NET", "titre_id": "net", "statut": "actif",
    })
    modifies = svc.basculer_actif_vers_renforcement(depot, "stm")
    assert modifies == [w_stm["id"]]
    assert svc.trouver(depot, w_stm["id"])["statut"] == "renforcement"
    assert svc.trouver(depot, w_net["id"])["statut"] == "actif"


def test_bascule_idempotente_sans_titre_id(depot):
    assert svc.basculer_actif_vers_renforcement(depot, "") == []
    assert svc.basculer_actif_vers_renforcement(depot, None) == []


def test_integration_achat_bascule_watchlist(depot):
    """Quand on crée un achat sur un titre, la watch `actif` correspondante
    bascule automatiquement en `renforcement`."""
    from app.services import mouvements as svc_mvt

    # Setup : compte + titre + watch en actif
    depot.enregistrer("comptes", [{"id": "c1", "type": "CTO"}])
    depot.enregistrer("titres", [{"id": "ifx", "ticker": "IFX", "nom": "Infineon"}])
    w = svc.creer(depot, {
        "nom": "Infineon", "titre_id": "ifx", "statut": "actif",
    })
    assert svc.trouver(depot, w["id"])["statut"] == "actif"

    # Création d'un achat sur ce titre
    svc_mvt.creer(depot, "achat", {
        "compte_id": "c1", "titre_id": "ifx",
        "date": "2026-05-14",
        "quantite": "1", "prix_unitaire": "52",
    })

    # La watch a basculé
    assert svc.trouver(depot, w["id"])["statut"] == "renforcement"


def test_integration_achat_sans_watch_ne_casse_rien(depot):
    """Un achat sur un titre sans watch active ne lève pas d'erreur."""
    from app.services import mouvements as svc_mvt

    depot.enregistrer("comptes", [{"id": "c1", "type": "CTO"}])
    depot.enregistrer("titres", [{"id": "xyz", "ticker": "XYZ", "nom": "X"}])
    svc_mvt.creer(depot, "achat", {
        "compte_id": "c1", "titre_id": "xyz",
        "date": "2026-05-14",
        "quantite": "1", "prix_unitaire": "10",
    })
    # Pas d'exception = OK


def test_integration_alimentation_ne_bascule_pas(depot):
    """Une alimentation_cash n'a pas de titre_id donc ne bascule rien."""
    from app.services import mouvements as svc_mvt

    depot.enregistrer("comptes", [{"id": "c1", "type": "CTO"}])
    depot.enregistrer("titres", [{"id": "ifx", "ticker": "IFX", "nom": "Infineon"}])
    w = svc.creer(depot, {
        "nom": "Infineon", "titre_id": "ifx", "statut": "actif",
    })
    svc_mvt.creer(depot, "alimentation_cash", {
        "compte_id": "c1", "date": "2026-05-14", "montant": "100",
    })
    assert svc.trouver(depot, w["id"])["statut"] == "actif"


# --- Promotion watchlist → titre (via les routes) -------------------------


@pytest.fixture
def client(depot):
    """Client Flask de test, avec dépôt isolé partagé."""
    from app import create_app

    app = create_app()
    app.config["DEPOT"] = depot
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c


def test_promouvoir_cree_titre_et_lie_watch(client, depot, monkeypatch):
    """Une watch sans titre_id devient un titre du catalogue + lien établi."""
    # Yahoo désactivé pour ce test (pas de réseau)
    from app.services import yahoo

    monkeypatch.setattr(yahoo, "enrichir_pour_titre", lambda *a, **k: None)

    depot.enregistrer("titres", [])
    w = svc.creer(depot, {
        "nom": "Micron Technology",
        "ticker": "MU",
        "marche": "Nasdaq",
        "devise": "USD",
        "statut": "actif",
        "these_lt": "Mémoires HBM / DRAM.",
    })

    rep = client.post(f"/watchlist/{w['id']}/promouvoir", follow_redirects=False)
    assert rep.status_code == 302
    assert "/titres/mu" in rep.headers["Location"]

    # Titre créé
    titres = depot.charger("titres")
    assert len(titres) == 1
    assert titres[0]["id"] == "mu"
    assert titres[0]["ticker"] == "MU"
    assert titres[0]["nom"] == "Micron Technology"
    assert titres[0]["these_lt"] == "Mémoires HBM / DRAM."

    # Watch liée
    apres = svc.trouver(depot, w["id"])
    assert apres["titre_id"] == "mu"


def test_promouvoir_avec_enrichissement_yahoo(client, depot, monkeypatch):
    """Si Yahoo répond, les champs financiers sont fusionnés."""
    from app.services import yahoo

    monkeypatch.setattr(
        yahoo,
        "enrichir_pour_titre",
        lambda *a, **k: {
            "cap_boursiere_m": "100000",
            "dette_nette_m": "5000",
            "valeur_entreprise_m": "105000",
            "isin": "US123",
            "secteur": "Semiconductors",
            "site_ir": "https://ir.example.com",
            "verse_dividende": False,
        },
    )

    depot.enregistrer("titres", [])
    w = svc.creer(depot, {
        "nom": "Exemple", "ticker": "EXMP", "marche": "Nasdaq",
        "statut": "actif",
    })
    client.post(f"/watchlist/{w['id']}/promouvoir")
    titres = depot.charger("titres")
    t = titres[0]
    assert t["cap_boursiere_m"] == "100000"
    assert t["isin"] == "US123"
    assert t["secteur"] == "Semiconductors"


def test_promouvoir_refuse_si_deja_lie(client, depot, monkeypatch):
    from app.services import yahoo

    monkeypatch.setattr(yahoo, "enrichir_pour_titre", lambda *a, **k: None)

    depot.enregistrer("titres", [{"id": "ifx", "ticker": "IFX", "nom": "Infineon"}])
    w = svc.creer(depot, {
        "nom": "Infineon", "ticker": "IFX", "titre_id": "ifx",
        "statut": "renforcement",
    })
    client.post(f"/watchlist/{w['id']}/promouvoir", follow_redirects=False)
    # Pas de nouveau titre créé
    assert len(depot.charger("titres")) == 1
