"""Réglages locaux de l'utilisateur pour la publication mobile — service pur.

Stockés dans ``DATA_DIR/reglages.json`` (hors repo Pages, jamais committé,
exclu par .gitignore). Permettent au .exe Windows de configurer la publication
sans systemd ni variables d'environnement.

⚠️ Le **mot de passe de chiffrement** n'est JAMAIS stocké ici : il est re-saisi
à chaque publication (principe de moindre exposition). Seuls les paramètres
GitHub non secrets + le token (sur la machine de l'utilisateur, dans son propre
périmètre) y figurent.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from app.services.stockage import ecrire_json_atomique, lire_json


FICHIER = "reglages.json"
CHAMPS = ("github_user", "github_repo", "branche", "github_token")

# Petit dictionnaire de mots simples (sans accents, faciles à taper) pour
# suggérer une phrase de passe diceware mémorisable. Ce n'est qu'une suggestion :
# l'utilisateur peut la régénérer ou utiliser son gestionnaire de mots de passe.
_MOTS = (
    "abricot", "ancre", "argile", "atelier", "avion", "balcon", "banane",
    "baobab", "bison", "boussole", "branche", "brume", "bureau", "cactus",
    "canard", "caramel", "cerise", "chalet", "chamois", "cigale", "citron",
    "colline", "comete", "corail", "coton", "coucou", "dauphin", "domino",
    "ecluse", "ecureuil", "epice", "etoile", "falaise", "fenetre", "flamant",
    "foret", "fraise", "galet", "gazelle", "girafe", "glacier", "grenade",
    "guitare", "harpe", "hibou", "horizon", "igloo", "jardin", "jongleur",
    "kayak", "lagune", "lanterne", "lavande", "lezard", "lilas", "lutin",
    "macaron", "marais", "melodie", "menthe", "mimosa", "mirabelle", "mousse",
    "myrtille", "nageoire", "navire", "nuage", "ocean", "olive", "orchidee",
    "ortie", "panda", "papyrus", "pelican", "phare", "piano", "pivoine",
    "platane", "prairie", "quartz", "radis", "renard", "rivage", "roseau",
    "sablier", "safran", "saphir", "sardine", "sentier", "sirop", "sorbet",
    "soleil", "sureau", "tamaris", "tisane", "topaze", "tournesol", "tresor",
    "trefle", "truffe", "tulipe", "vague", "velours", "verger", "violette",
    "voilier", "yourte", "zephyr",
)


def chemin_reglages(data_dir) -> Path:
    return Path(data_dir) / FICHIER


def charger_reglages(data_dir) -> dict:
    """Renvoie les réglages, complétés par leurs valeurs par défaut."""
    donnees = lire_json(chemin_reglages(data_dir))
    reglages = {champ: "" for champ in CHAMPS}
    reglages["branche"] = "main"
    reglages.update({k: v for k, v in donnees.items() if k in CHAMPS})
    if not reglages.get("branche"):
        reglages["branche"] = "main"
    return reglages


def enregistrer_reglages(data_dir, valeurs: dict) -> dict:
    """Met à jour et persiste les réglages (écriture atomique)."""
    actuels = charger_reglages(data_dir)
    for champ in CHAMPS:
        if champ in valeurs:
            actuels[champ] = (valeurs[champ] or "").strip()
    if not actuels.get("branche"):
        actuels["branche"] = "main"
    ecrire_json_atomique(chemin_reglages(data_dir), actuels)
    return actuels


def publication_api_configuree(reglages: dict) -> bool:
    """Vrai si user + repo + token sont renseignés (publication API possible)."""
    return all(reglages.get(c) for c in ("github_user", "github_repo", "github_token"))


def generer_phrase_passe(nb_mots: int = 6) -> str:
    """Suggère une phrase de passe diceware (mots aléatoires + nombre).

    Garantit largement la longueur minimale (≥ 15 caractères) et reste
    mémorisable. Aléa cryptographique (``secrets``).
    """
    mots = [secrets.choice(_MOTS) for _ in range(max(4, nb_mots))]
    nombre = secrets.randbelow(90) + 10
    return "-".join(mots) + f"-{nombre}"
