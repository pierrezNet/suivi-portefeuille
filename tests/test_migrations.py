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
    migrations.appliquer(tmp_path, sauvegarder=lambda dd: appels.append(dd))
    assert appels == []  # rien à migrer → pas de sauvegarde


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
