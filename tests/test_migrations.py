"""Tests des migrations de schéma au démarrage."""

import json

from app.services import migrations
from app.services.stockage import Depot


def test_version_initiale_si_meta_absent(tmp_path):
    assert migrations.version_actuelle(tmp_path) == migrations.VERSION_INITIALE


def test_appliquer_sans_migration_estampille(tmp_path):
    version = migrations.appliquer(tmp_path)
    assert version == migrations.VERSION_SCHEMA_COURANTE
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["version_schema"] == migrations.VERSION_SCHEMA_COURANTE


def test_appliquer_sans_migration_ne_sauvegarde_pas(tmp_path):
    appels = []
    # dépôt déjà à la version courante → rien à migrer
    migrations._ecrire_version(tmp_path, migrations.VERSION_SCHEMA_COURANTE)
    migrations.appliquer(tmp_path, sauvegarder=lambda dd: appels.append(dd))
    assert appels == []  # rien à migrer → pas de sauvegarde


def test_migration_v2_backfill_categorie(tmp_path):
    """La migration v2 renseigne `categorie` sur les titres qui n'en ont pas,
    sans écraser une catégorie déjà valide."""
    d = Depot(tmp_path)
    d.enregistrer("titres", [
        {"id": "ml", "ticker": "ML", "nom": "Michelin", "secteur": "Penumatiques"},
        {"id": "ho", "ticker": "HO", "nom": "Thales", "secteur": "Défense"},
        # déjà catégorisé (valide) → doit rester intact malgré un secteur logiciel
        {"id": "x", "ticker": "X", "nom": "X", "secteur": "Software", "categorie": "Défense"},
    ])
    migrations._ecrire_version(tmp_path, 1)
    migrations.appliquer(tmp_path)
    titres = {t["id"]: t for t in Depot(tmp_path).charger("titres")}
    assert titres["ml"]["categorie"] == "Industrie & Matériaux"
    assert titres["ho"]["categorie"] == "Défense"
    assert titres["x"]["categorie"] == "Défense"


def test_appliquer_migration_en_attente(tmp_path, monkeypatch):
    """Une migration en attente est appliquée, après sauvegarde, et estampillée."""
    appliquees = []
    appels_sauvegarde = []

    def _migration_v2(depot):
        appliquees.append(2)
        depot.enregistrer("comptes", [{"id": "migre", "nom": "Migré", "type": "PEA"}])

    monkeypatch.setattr(migrations, "VERSION_SCHEMA_COURANTE", 2)
    monkeypatch.setattr(migrations, "MIGRATIONS", [(2, _migration_v2)])
    # On part d'un dépôt déjà estampillé v1.
    migrations._ecrire_version(tmp_path, 1)

    version = migrations.appliquer(
        tmp_path, sauvegarder=lambda dd: appels_sauvegarde.append(dd)
    )
    assert version == 2
    assert appliquees == [2]
    assert appels_sauvegarde  # sauvegarde déclenchée avant migration
    assert migrations.version_actuelle(tmp_path) == 2
    assert Depot(tmp_path).charger("comptes")[0]["id"] == "migre"


def test_migration_deja_appliquee_non_rejouee(tmp_path, monkeypatch):
    compteur = []
    monkeypatch.setattr(migrations, "VERSION_SCHEMA_COURANTE", 2)
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [(2, lambda depot: compteur.append(1))]
    )
    migrations._ecrire_version(tmp_path, 2)  # déjà à jour
    migrations.appliquer(tmp_path)
    assert compteur == []  # non rejouée


def test_appliquer_ne_retrograde_pas(tmp_path):
    """Des données d'un .exe plus récent (v5) ne sont jamais rétrogradées."""
    migrations._ecrire_version(tmp_path, 5)
    version = migrations.appliquer(tmp_path)  # binaire à VERSION_SCHEMA_COURANTE=1
    assert version == 5
    assert migrations.version_actuelle(tmp_path) == 5


def test_appliquer_n_ecrit_pas_si_deja_a_jour(tmp_path, monkeypatch):
    """Pas d'écriture parasite de meta.json à chaque démarrage de régime."""
    migrations.appliquer(tmp_path)  # premier passage : crée meta.json
    appels = []
    monkeypatch.setattr(migrations, "_ecrire_version", lambda dd, v: appels.append(v))
    migrations.appliquer(tmp_path)  # déjà à jour → aucune réécriture
    assert appels == []
