# Setup GitHub Pages — dashboard mobile chiffré

L'app desktop reste 100 % locale. Ce setup ajoute une **publication
chiffrée** vers GitHub Pages : ton smartphone consomme un JSON chiffré
client-side, sans que ton PC ait besoin d'être allumé pour consulter.

## Architecture

```
PC desktop                   GitHub                  Smartphone
──────────                   ──────                  ──────────
[Bouton « Publier »]
   ↓ chiffre via AES-256-GCM
   ↓ git push                ▼
                       repo public statique          navigateur
                       ├─ index.html (HTML+JS)  ─►   fetch + WebCrypto
                       └─ data.enc.json         ─►   déchiffre
                                                      ↓
                                              Dashboard affiché
```

## Setup unique (~10 min)

### 1. Créer le repo GitHub

Sur https://github.com/new :
- **Nom** : `portefeuille-dashboard` (ou autre)
- **Public** ✅
- **Add README** : non
- **Create repository**

### 2. Cloner localement

```bash
cd /var/www/html
git clone git@github.com:pierrezNet/portefeuille-dashboard.git
cd portefeuille-dashboard
# Premier commit vide pour initialiser main
git commit --allow-empty -m "Init"
git push origin main
```

### 3. Activer GitHub Pages

Sur le repo GitHub :
- **Settings** → **Pages** (menu de gauche)
- Source : **Deploy from a branch**
- Branch : `main` / `/(root)`
- **Save**

Ta page sera accessible à `https://pierreznet.github.io/portefeuille-dashboard/` au bout de 1-2 minutes.

### 4. Choisir un mot de passe fort

Au moins **15 caractères**. Une phrase de passe est idéale :
```
exemple : tortue-bleue-piano-marche-2026
```
Mémorise-le dans un gestionnaire de mots de passe (Bitwarden, 1Password, KeePassXC…).
**Si tu le perds, tu n'as pas accès au cloud** (mais tes données locales restent intactes).

### 5. Configurer le service systemd

```bash
systemctl --user edit suivi-portefeuille
```

Ajoute (et garde l'ancienne section `BOURSE_PUBLIER_SORTIE` si elle existe — elle ne sert plus mais ne gêne pas) :

```ini
[Service]
Environment="BOURSE_PASSWORD=ta-phrase-de-passe-forte-ici"
Environment="BOURSE_DASHBOARD_REPO=/var/www/html/portefeuille-dashboard"
```

Puis :
```bash
systemctl --user restart suivi-portefeuille
```

## Vérification

```bash
# Test CLI direct (commit local, sans push, pour valider)
cd /var/www/html/Bourse
BOURSE_PASSWORD='ta-phrase-de-passe-forte-ici' \
  BOURSE_DASHBOARD_REPO=/var/www/html/portefeuille-dashboard \
  BOURSE_DASHBOARD_NO_PUSH=1 \
  .venv/bin/python tools/publier_dashboard.py

# Vérification : fichiers présents et commit local
ls -lh /var/www/html/portefeuille-dashboard/{index.html,data.enc.json,.nojekyll}
git -C /var/www/html/portefeuille-dashboard log --oneline | head
```

## Publication régulière

Trois manières équivalentes :

### a) Bouton UI desktop
Dashboard → bouton **📱 Publier vers mobile** → push automatique.

### b) CLI manuel
```bash
cd /var/www/html/Bourse
.venv/bin/python tools/publier_dashboard.py
```

### c) Cron / tâche planifiée
Ajoute par exemple dans `crontab -e` :
```
0 22 * * * cd /var/www/html/Bourse && .venv/bin/python tools/publier_dashboard.py >> ~/portefeuille-publish.log 2>&1
```

## Consultation mobile

1. Sur smartphone, ouvre `https://TON_USER.github.io/portefeuille-dashboard/`
2. Une modale demande le mot de passe → tape-le, coche « Mémoriser »
3. Le dashboard s'affiche, les données sont déchiffrées côté navigateur
4. Ajoute la page en favori ou sur l'écran d'accueil

À chaque visite suivante, le mot de passe est repris automatiquement du `localStorage`. Bouton 🔑 pour l'oublier, 🔄 pour recharger.

## Sécurité

| Aspect | Mesure |
|---|---|
| Algo | AES-256-GCM (chiffrement authentifié) |
| Dérivation | PBKDF2-SHA256, **600 000 itérations** (OWASP) |
| Sel | 32 bytes aléatoires, régénéré à chaque publication |
| IV | 12 bytes aléatoires, régénéré à chaque publication |
| Stockage | Repo public — sans clé, le JSON est opaque |
| Persistance | `localStorage` côté navigateur — effaçable via bouton 🔑 |

**Surface d'attaque** : pour accéder à tes données, un attaquant doit
(1) connaître l'URL GitHub Pages, (2) télécharger `data.enc.json`, et
(3) brute-forcer la clé. Avec une phrase de passe ≥ 15 caractères + 200 k
itérations PBKDF2, c'est calculatoirement infaisable.

## Modifier le mot de passe

Aucun mécanisme de rotation automatique. Pour changer :
1. Met à jour `BOURSE_PASSWORD` dans le drop-in systemd
2. `systemctl --user restart suivi-portefeuille`
3. Publie une fois → le nouveau JSON est chiffré avec le nouveau mdp
4. Sur smartphone : bouton 🔑 (oublier), recharger, taper le nouveau mdp

## Désactiver la publication cloud

Si tu veux suspendre temporairement, il suffit de désactiver le bouton ou
de supprimer les env vars :

```bash
systemctl --user edit suivi-portefeuille
# Commente les Environment=... avec un #
systemctl --user restart suivi-portefeuille
```

Le bouton UI affichera une erreur claire (`Variable BOURSE_PASSWORD non définie`).
