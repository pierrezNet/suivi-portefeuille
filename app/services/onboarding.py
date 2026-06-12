"""Onboarding : détection d'un dépôt vierge + jeu de données d'exemple.

Au premier lancement (typiquement le .exe d'un ami), `data/` est vide. Plutôt
que d'afficher un dashboard vide demandant d'« éditer data/comptes.json », on
propose un écran de démarrage guidé et un jeu d'exemple FICTIF.
"""

from __future__ import annotations

from datetime import date as _date

from app.services.stockage import Depot


def est_vierge(depot: Depot) -> bool:
    """Vrai si aucun compte n'est enregistré (premier lancement)."""
    return not depot.charger("comptes")


def creer_jeu_exemple(depot: Depot) -> None:
    """Crée un petit jeu de données FICTIF pour découvrir l'app remplie.

    Numéros de compte volontairement factices (placeholders) — jamais de vraies
    coordonnées. N'écrase rien si des comptes existent déjà.
    """
    if not est_vierge(depot):
        return

    depot.enregistrer("comptes", [
        {
            "id": "pea-exemple", "nom": "PEA (exemple)", "type": "PEA",
            "broker": "Mon courtier", "numero": "PEA-EXEMPLE-0001",
            "date_ouverture": "2026-01-02", "devise_principale": "EUR",
        },
        {
            "id": "cto-exemple", "nom": "CTO (exemple)", "type": "CTO",
            "broker": "Mon courtier", "numero": "CTO-EXEMPLE-0001",
            "date_ouverture": "2026-01-02", "devise_principale": "EUR",
        },
    ])
    depot.enregistrer("titres", [
        {
            "id": "exemple-sa", "ticker": "EXPL", "nom": "Exemple S.A.",
            "isin": "FR0000000000", "marche": "Euronext Paris", "devise": "EUR",
            "secteur": "Démonstration",
            "these_lt": "Titre d'exemple — remplace-le par tes vraies positions.",
            "date_creation": _date.today().isoformat(),
        },
    ])
    depot.enregistrer("mouvements", [
        {
            "id": "ex-alim", "type": "alimentation_cash", "compte_id": "pea-exemple",
            "date": "2026-01-03", "montant": "1000.00", "devise": "EUR",
            "libelle": "Dépôt d'exemple",
        },
        {
            "id": "ex-achat", "type": "achat", "compte_id": "pea-exemple",
            "titre_id": "exemple-sa", "date": "2026-01-04", "quantite": 5,
            "prix_unitaire": "20.00", "devise": "EUR", "frais_courtage": "0.00",
            "taux_change": "1.0", "notes": "Achat d'exemple",
        },
    ])
