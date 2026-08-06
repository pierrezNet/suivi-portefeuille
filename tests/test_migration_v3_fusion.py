"""Migration v3 : fusion de la watchlist dans les titres."""

import copy
from pathlib import Path

from app.services import migrations
from app.services.stockage import Depot


def _depot(tmp_path: Path, titres, watchlist, mouvements=()) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", titres)
    d.enregistrer("watchlist", watchlist)
    d.enregistrer("mouvements", list(mouvements))
    return d


def _par_id(depot):
    return {t["id"]: t for t in depot.charger("titres")}


def test_watch_liee_absorbe_le_suivi(tmp_path):
    d = _depot(
        tmp_path,
        [{"id": "ifx", "ticker": "IFX", "nom": "Infineon", "devise": "EUR",
          "these_lt": "Thèse du titre"}],
        [{"id": "w1", "titre_id": "ifx", "statut": "renforcement",
          "priorite": "haute", "compte_cible": "pea",
          "echeance_abandon": "2027-01-01", "notes": "note watch",
          "cap_boursiere": "~50 Md€", "these_lt": "Thèse watch différente",
          "paliers_rachat": [{"prix": "40", "tranche": "1/2", "commentaire": ""}],
          "ordres_actifs": [{"id": "o1", "prix_limite": "35", "quantite": 2,
                             "sens": "achat", "statut": "en_attente"}]}],
    )
    migrations._migration_v3_fusion_watchlist(d)
    t = _par_id(d)["ifx"]
    assert t["statut"] == "renforcement" and t["priorite"] == "haute"
    assert t["compte_cible"] == "pea" and t["echeance_abandon"] == "2027-01-01"
    assert t["cap_boursiere_txt"] == "~50 Md€"
    assert t["ordres_actifs"][0]["id"] == "o1"
    assert t["paliers_rachat"][0]["prix"] == "40"
    # Thèse du titre (versionnée) NON écrasée ; thèse watch + notes annexées.
    assert t["these_lt"] == "Thèse du titre"
    assert "note watch" in t["notes_suivi"]
    assert "Thèse watch différente" in t["notes_suivi"]


def test_these_copiee_si_titre_vide(tmp_path):
    d = _depot(tmp_path,
               [{"id": "x", "ticker": "X", "nom": "X", "these_lt": ""}],
               [{"id": "w", "titre_id": "x", "these_lt": "thèse importée",
                 "statut": "actif"}])
    migrations._migration_v3_fusion_watchlist(d)
    assert _par_id(d)["x"]["these_lt"] == "thèse importée"


def test_watch_orpheline_cree_un_titre(tmp_path):
    d = _depot(tmp_path, [],
               [{"id": "w", "ticker": "MU", "nom": "Micron", "devise": "USD",
                 "statut": "achat_souhaite",
                 "paliers_rachat": [{"prix": "80", "tranche": "", "commentaire": ""}]}])
    migrations._migration_v3_fusion_watchlist(d)
    titres = d.charger("titres")
    assert len(titres) == 1
    t = titres[0]
    assert t["id"] == "mu" and t["ticker"] == "MU"
    assert t["statut"] == "achat_souhaite"
    assert t["paliers_rachat"][0]["prix"] == "80"


def test_titre_possede_sans_watch_recoit_statut(tmp_path):
    d = _depot(
        tmp_path,
        [{"id": "a", "ticker": "A", "nom": "A"},
         {"id": "b", "ticker": "B", "nom": "B"}],
        [],
        [{"id": "m", "type": "achat", "titre_id": "a", "compte_id": "c",
          "date": "2026-01-01", "quantite": "3", "prix_unitaire": "10"}],
    )
    migrations._migration_v3_fusion_watchlist(d)
    t = _par_id(d)
    assert t["a"]["statut"] == "renforcement"  # position > 0
    assert t["b"]["statut"] == "actif"         # aucune position


def test_idempotente(tmp_path):
    d = _depot(
        tmp_path,
        [{"id": "ifx", "ticker": "IFX", "nom": "Infineon", "these_lt": "T"}],
        [{"id": "w1", "titre_id": "ifx", "statut": "renforcement",
          "priorite": "haute", "notes": "n",
          "ordres_actifs": [{"id": "o1", "prix_limite": "35", "quantite": 2,
                             "sens": "achat", "statut": "en_attente"}]}],
    )
    migrations._migration_v3_fusion_watchlist(d)
    apres1 = copy.deepcopy(d.charger("titres"))
    migrations._migration_v3_fusion_watchlist(d)  # rejeu
    apres2 = d.charger("titres")
    assert apres1 == apres2
    assert len(apres2[0]["ordres_actifs"]) == 1  # pas de doublon d'ordre


def test_watchlist_json_preserve(tmp_path):
    wl = [{"id": "w", "ticker": "MU", "nom": "Micron"}]
    d = _depot(tmp_path, [], wl)
    migrations._migration_v3_fusion_watchlist(d)
    assert d.charger("watchlist") == wl


def test_migration_via_appliquer_estampille_version_courante(tmp_path):
    d = _depot(tmp_path,
               [{"id": "ifx", "ticker": "IFX", "nom": "I"}],
               [{"id": "w", "titre_id": "ifx", "statut": "renforcement"}])
    v = migrations.appliquer(tmp_path)  # meta absent → joue v2, v3, v4
    assert v == migrations.VERSION_SCHEMA_COURANTE >= 4
    assert _par_id(d)["ifx"]["statut"] == "renforcement"


# --- v4 : remap du statut 'actif' -----------------------------------------

def test_v4_remap_actif_selon_detention(tmp_path):
    d = _depot(
        tmp_path,
        [{"id": "held", "ticker": "H", "nom": "H", "statut": "actif"},
         {"id": "watched", "ticker": "W", "nom": "W", "statut": "actif"},
         {"id": "other", "ticker": "O", "nom": "O", "statut": "renforcement"}],
        [],
        [{"id": "m", "type": "achat", "titre_id": "held", "compte_id": "c",
          "date": "2026-01-01", "quantite": "1", "prix_unitaire": "10"}],
    )
    migrations._migration_v4_remap_statuts(d)
    t = _par_id(d)
    assert t["held"]["statut"] == "conservation"   # détenu
    assert t["watched"]["statut"] == "veille"      # non détenu
    assert t["other"]["statut"] == "renforcement"  # inchangé


def test_v4_idempotente(tmp_path):
    d = _depot(tmp_path, [{"id": "x", "ticker": "X", "nom": "X", "statut": "actif"}], [])
    migrations._migration_v4_remap_statuts(d)
    a = copy.deepcopy(d.charger("titres"))
    migrations._migration_v4_remap_statuts(d)
    assert d.charger("titres") == a
