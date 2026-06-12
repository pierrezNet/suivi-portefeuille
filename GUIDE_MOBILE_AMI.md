# Consulter mon portefeuille sur smartphone

L'application desktop reste **100 % locale**. Si tu veux consulter ton
portefeuille **sur ton téléphone**, tu publies une copie **chiffrée** de tes
chiffres sur **ton propre** espace GitHub Pages. Personne d'autre que toi (avec
ta phrase de passe) ne peut la lire.

> Remplace partout **`TON_USER`** par ton pseudo GitHub et **`TON_REPO`** par le
> nom de dépôt que tu choisis (ex. `mon-portefeuille-prive`).

---

## ⚠️ À comprendre avant de commencer

- Le fichier publié (`data.enc.json`) est **chiffré** (AES-256-GCM, PBKDF2
  600 000 itérations). Sans ta **phrase de passe**, il est illisible.
- Par défaut, un dépôt GitHub Pages est **public** : le fichier chiffré est donc
  **téléchargeable** par quelqu'un qui connaît l'adresse — mais **inexploitable**
  sans ta phrase de passe. Pour réduire encore le risque :
  - choisis un **nom de dépôt peu devinable** ;
  - choisis une **phrase de passe forte** (la page Réglages t'en suggère une) ;
  - si tu as un abonnement GitHub payant, tu peux mettre le dépôt **privé**
    (Pages privé nécessite un plan payant).
- **Si tu perds ta phrase de passe**, la version mobile devient illisible — mais
  **tes données locales restent intactes** sur ton PC.

---

## Étape 1 — Créer un compte GitHub (gratuit)

Si tu n'en as pas : <https://github.com/signup>.

## Étape 2 — Créer ton dépôt

1. <https://github.com/new>
2. **Repository name** : `TON_REPO` (ex. `mon-portefeuille-prive`)
3. Laisse **Public** coché (voir l'avertissement ci-dessus), **sans** README.
4. **Create repository**.

## Étape 3 — Activer GitHub Pages

1. Sur ton dépôt : **Settings** → **Pages** (menu de gauche).
2. **Source** : *Deploy from a branch* · **Branch** : `main` · `/(root)` · **Save**.
3. (Tu pourras revenir vérifier l'adresse après la première publication.)

## Étape 4 — Créer un token GitHub

Un *token* autorise l'app à écrire dans **ce seul dépôt**.

1. <https://github.com/settings/personal-access-tokens/new> (**Fine-grained token**).
2. **Token name** : `suivi-portefeuille` · **Expiration** : à ta convenance.
3. **Repository access** : *Only select repositories* → choisis **`TON_REPO`**.
4. **Permissions** → **Repository permissions** → **Contents** : **Read and write**.
5. **Generate token** et **copie-le** (il ne s'affiche qu'une fois).

## Étape 5 — Renseigner les Réglages dans l'app

Dans l'application desktop : menu **Réglages**.

| Champ | Valeur |
|---|---|
| Nom d'utilisateur GitHub | `TON_USER` |
| Nom du dépôt | `TON_REPO` |
| Branche | `main` |
| Token GitHub | *(colle le token de l'étape 4)* |

**Enregistrer**. (Le token est stocké uniquement sur ta machine.)

## Étape 6 — Choisir une phrase de passe

La page Réglages **te suggère** une phrase de passe forte (≥ 15 caractères).
Note-la dans un gestionnaire de mots de passe (Bitwarden, KeePassXC…).
Elle n'est **jamais** enregistrée par l'application.

## Étape 7 — Publier

1. Va sur le **Tableau de bord**.
2. Dans le champ à côté de **« 📱 Publier vers mobile »**, saisis ta **phrase de
   passe**, puis clique sur le bouton.
3. Un message confirme la publication et affiche l'adresse :
   `https://TON_USER.github.io/TON_REPO/`

## Étape 8 — Consulter sur smartphone

1. Ouvre `https://TON_USER.github.io/TON_REPO/` sur ton téléphone
   (compte 1–2 minutes après la toute première publication).
2. Saisis ta **phrase de passe** → le dashboard s'affiche (déchiffré dans le
   navigateur). Coche « Mémoriser » pour ne plus la retaper.
3. **Ajoute la page à l'écran d'accueil** (menu du navigateur) : tu obtiens une
   icône d'application (PWA), consultable même hors connexion.

---

## Republier après des modifs

Refais l'**étape 7** quand tu veux mettre à jour la version mobile (saisie de la
phrase de passe + bouton). Sur le téléphone, recharge la page (bouton 🔄).

## Changer de phrase de passe

Republie avec une nouvelle phrase de passe. Sur le téléphone : bouton 🔑 pour
oublier l'ancienne, recharge, saisis la nouvelle.
