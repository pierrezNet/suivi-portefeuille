# Suivi Portefeuille — Journal de bord d'investisseur

> **Application web locale en Flask pour tenir le journal de mes investissements sur PEA et CTO Bourse Direct : opérations, plus-values réalisées, thèses long terme, et préparation fiscale.**

> 👋 **Vous êtes un ami à qui Emmanuel a partagé l'application ?**
> Commencez par **[USAGE_POUR_AMI.md](USAGE_POUR_AMI.md)** (prise en main),
> **[INSTALL_WINDOWS.md](INSTALL_WINDOWS.md)** (installation du `.exe`) et
> **[GUIDE_MOBILE_AMI.md](GUIDE_MOBILE_AMI.md)** (consultation mobile). Le reste
> de ce README est la documentation technique du projet.

---

## 🎯 Objectif du projet

Remplacer le fichier tableur (LibreOffice Calc) par une application web personnelle et structurée, conçue comme un **journal de bord d'investisseur**. Elle ne suit pas les cours en temps réel — c'est volontaire.

### Trois usages combinés

1. **Journal d'investisseur** : enregistrer chaque opération (achat, vente, alimentation, dividende, frais) au fil de l'eau, garder une trace des décisions et de leurs justifications.
2. **Préparation fiscale** : calculer les plus-values réalisées sur CTO selon la méthode FIFO, générer les éléments nécessaires au formulaire 2074.
3. **Bibliothèque structurée** : documenter les thèses long terme, les signaux moyen terme, les watchlists et les événements à surveiller.

### Trois principes fondamentaux

- **100 % offline** : aucun appel à Internet en runtime. Les cours du jour sont importés ponctuellement via le xlsx que Bourse Direct propose au téléchargement — **c'est l'utilisateur qui pilote la fraîcheur**, pas une API tierce.
- **Aucune alerte de prix push** : les rappels passent par le calendrier (ICS) avec des `VALARM` que les apps de calendrier natives savent gérer (Thunderbird, GNOME Calendar, Apple Calendar).
- **Données chez soi, lisibles** : tout est en JSON dans `data/`. Aucun lock-in, aucune base opaque, `git diff` possible. Le dashboard mobile est chiffré et publié séparément.

> 💡 **Ce que l'application NE FAIT PAS volontairement** : cours live en streaming (pas de WebSocket broker), alertes push instantanées (sauf via PWA + Web Push, optionnel), trading actif / options / dérivés. Voir [`ROADMAP.md`](ROADMAP.md) pour ce qui est en réflexion vs hors scope.

---

## 🔀 Watchlist vs Programmes vs Événements — quand utiliser quoi ?

Trois modules couvrent des intentions différentes mais qui peuvent se chevaucher
sur un même titre. Sans clarté sur la frontière, on duplique vite la même info à
deux endroits. Règle simple : **l'intention dicte le module**, pas le titre.

| Module | Intention | Cas typique | Génère automatiquement |
|---|---|---|---|
| **Watchlist** | Surveiller et **agir ponctuellement** | « Si Infineon ≤ 60 €, j'achète 2 actions une seule fois » | Le bouton « ✓ Exécuté » crée le mouvement d'achat correspondant. |
| **Programmes** | Engagements **récurrents** (sans ou avec titre) | Virement permanent 100 €/mois · DCA Amundi 80 €/mois | Mouvement `alimentation_cash` auto si pas de titre · rappel d'événement DCA à honorer manuellement si titre. |
| **Événements** | Agenda des **dates importantes** | Publication T1, détachement dividende, AG · rappel DCA à honorer | Aucun (les rappels DCA viennent de Programmes). Alimente le calendrier ICS. |

**Comment trancher en cas de doute** :

- **C'est un achat unique chez le broker à un prix défini ?** → Watchlist (ordre limite).
- **C'est récurrent (mensuel, trimestriel) sans intervention manuelle ?** → Programmes.
- **C'est une date à laquelle il faut faire quelque chose / regarder un résultat ?** → Événement (ou laissé à Programmes si c'est un DCA récurrent).

**Le piège classique** : un même titre Amundi peut se retrouver à la fois en Watchlist
(pour décrire la thèse long terme et les paliers de renforcement) ET en Programmes
(pour exécuter le DCA mensuel automatique). C'est légitime — les deux ne se marchent
pas sur les pieds. Watchlist = la **réflexion**, Programmes = l'**exécution**.

Une bulle d'aide repliable « 💡 Quand utiliser cette page ? » est présente en haut
de chacune des trois pages dans l'application — n'hésite pas à l'ouvrir si tu hésites.

---

## 📅 Rythme d'utilisation

Le projet combine **trois surfaces** qu'on utilise à des cadences différentes.
Ce tableau sert de mode d'emploi à reprendre 6 mois plus tard sans relire
toute la doc.

| Surface | Où | Quoi | Quand |
|---|---|---|---|
| **App locale (édition)** | Navigateur sur le PC → `http://127.0.0.1:5000` | Saisie des mouvements, édition des thèses, watchlist, événements | À chaque opération sur Bourse Direct |
| **App locale (consultation)** | Même URL | Dashboard, soldes recalculés, récap fiscal, calendrier `/calendrier.ics` | À la demande, depuis le PC |
| **Dashboard mobile chiffré** | URL GitHub Pages, en read-only | Vue d'ensemble portefeuille, plus-values, événements à venir | À la demande, depuis le smartphone |

### Cadences typiques

- **À chaque opération** (achat/vente/dividende reçu/alimentation) → saisir
  immédiatement le mouvement dans l'app locale, pendant que les détails sont
  frais.
- **Hebdomadaire** (5 min) → publication mobile (bouton 📱 ou CLI). Avec un
  cron quotidien à 22 h, c'est automatique.
- **Mensuel** (10 min) → contrôler que les **soldes cash recalculés** et le
  **PRU par titre** correspondent à ceux affichés par Bourse Direct. Tout
  écart = un mouvement oublié.
- **Trimestriel** (30 min) → relire et mettre à jour les **thèses LT**, la
  **watchlist**, les **paliers de rachat** ; archiver les événements passés.
- **Annuel — printemps** (1 h) → générer le **récap fiscal** de l'année N-1,
  reporter les chiffres sur le formulaire 2074 ; sauvegarder l'export.
- **En continu** → s'abonner depuis GNOME Calendar / Thunderbird à
  `http://127.0.0.1:5000/calendrier.ics` ; les événements apparaissent
  automatiquement à côté de l'agenda personnel.

### Sauvegarde des données

Source de vérité unique : [`data/`](data/). Sauvegarder régulièrement via
[`tools/backup.sh`](tools/backup.sh) (cron quotidien à 22 h conseillé — voir
§ Sauvegarde).

---

## 🛠️ Stack technique

| Couche | Technologie | Justification |
|---|---|---|
| Langage | **Python 3.12** (Ubuntu 24.04) | Polyvalent, écosystème mature |
| Web framework | **Flask** | Simple, idéal pour app locale |
| Templates | **Jinja2** | Syntaxe quasi identique à Twig |
| Persistance | **Fichiers JSON** | Lisibles, sauvegardables, sans schéma |
| Manipulation décimaux | **decimal.Decimal** (stdlib) | Précision financière, éviter `float` |
| CSS | **Bootstrap 5** ou **DSFR** | DSFR aligné habitudes professionnelles |
| Génération iCalendar | **icalendar** (PyPI) | Bibliothèque mature pour `.ics` |
| Tests | **pytest** | Standard Python |
| Environnement | **venv** | Isolation des dépendances |

### Dépendances prévisibles (requirements.txt)

```
flask
jinja2
icalendar
python-dotenv
pytest
```

C'est tout. Pas besoin de plus pour une V1 fonctionnelle.

---

## 📂 Structure du projet

```
/var/www/html/Bourse/
├── app/
│   ├── __init__.py                  # Application factory Flask
│   ├── routes/                      # Endpoints Flask (Blueprints)
│   │   ├── dashboard.py             # Vue d'ensemble + bouton publication
│   │   ├── titres.py                # CRUD titres et thèses LT
│   │   ├── mouvements.py            # Achats, ventes, cash, dividendes
│   │   ├── notes_titres.py          # Journal de notes versionnées par titre
│   │   ├── watchlist.py             # Titres surveillés, paliers de rachat
│   │   ├── evenements.py            # Événements + endpoint .ics
│   │   ├── virements_programmes.py  # Alimentations récurrentes (DCA)
│   │   └── recap_fiscal.py          # Récapitulatifs annuels (CTO/PEA)
│   ├── services/                    # Logique métier pure
│   │   ├── stockage.py              # Lecture/écriture JSON atomique (Depot)
│   │   ├── pru.py                   # Calcul PRU FIFO
│   │   ├── plus_values.py           # Plus-values réalisées
│   │   ├── soldes.py                # Reconstitution des soldes cash
│   │   ├── mouvements.py            # Validation + persistance mouvements
│   │   ├── titres.py                # Logique titres
│   │   ├── notes_titres.py          # Versioning des notes
│   │   ├── watchlist.py             # Logique watchlist
│   │   ├── evenements.py            # Logique événements
│   │   ├── virements_programmes.py  # Rattrapage des virements récurrents
│   │   ├── ics_export.py            # Génération iCalendar
│   │   ├── fiscal.py                # Récap fiscal annuel
│   │   ├── dashboard_data.py        # Agrégats du dashboard (réutilisé export)
│   │   ├── chiffrement.py           # AES-256-GCM + PBKDF2 (export mobile)
│   │   └── yahoo.py                 # OPTIONNEL : cours indicatifs (off par défaut)
│   ├── templates/                   # Jinja2 (un sous-dossier par domaine)
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── comptes/  titres/  mouvements/  notes_titres/
│   │   ├── watchlist/  evenements/  virements_programmes/
│   │   └── recap_fiscal/
│   └── static/css/  static/js/
├── data/                            # Source de vérité — JAMAIS versionnée
│   ├── comptes.json
│   ├── titres.json
│   ├── mouvements.json
│   ├── notes_titres.json
│   ├── watchlist.json
│   ├── evenements.json
│   └── virements_programmes.json
├── tests/                           # pytest (1 fichier par service)
│   ├── test_pru.py  test_plus_values.py  test_soldes.py
│   ├── test_fiscal.py  test_ics_export.py  test_chiffrement.py
│   ├── test_titres.py  test_notes_titres.py  test_watchlist.py
│   ├── test_virements_programmes.py  test_ordres_actifs.py
│   ├── test_yahoo.py  test_publier_dashboard.py
│   └── conftest.py
├── tools/
│   ├── install-systemd.sh           # Installe l'unit systemd utilisateur
│   ├── suivi-portefeuille.service   # Unit systemd
│   ├── dev.sh                       # Lance run.py avec env vars du drop-in (mode dev)
│   ├── backup.sh                    # Sauvegarde datée de data/
│   ├── publier_dashboard.py         # Publication chiffrée vers GH Pages
│   ├── templates/                   # Assets HTML/CSS/JS pour le dashboard mobile
│   │   ├── cloud_index.html.j2  cloud_app.js
│   │   └── dashboard_mobile.html.j2  dashboard_mobile.css  dashboard_mobile.js
│   ├── SETUP_CLOUD.md               # Setup publication mobile chiffrée
│   ├── enrichir_titre.py            # Migration : enrichit fiches titres
│   ├── migrer_notes.py              # Migration historique
│   ├── migrer_ordre_net.py          # Migration historique
│   └── migrer_perspectives.py       # Migration historique
├── .venv/                           # Environnement virtuel Python
├── requirements.txt
├── config.py
├── run.py                           # Point d'entrée Flask (mode dev)
└── README.md
```

> 💡 Les scripts `tools/migrer_*.py` et `enrichir_titre.py` sont des migrations
> ponctuelles déjà appliquées sur les données. Conservés pour traçabilité —
> à archiver dans `tools/archive/` si la racine devient encombrée.

---

## 💾 Modèle de données (fichiers JSON)

### `data/comptes.json`

Les comptes sont **statiques** : tu en crées 1 ou 2 et tu n'y touches plus. Le solde cash est **recalculé dynamiquement** à partir de l'historique des mouvements, jamais stocké.

```json
{
  "comptes": [
    {
      "id": "pea-bd",
      "nom": "PEA Bourse Direct",
      "type": "PEA",
      "broker": "Bourse Direct",
      "numero": "508TI0008...3EUR",
      "date_ouverture": "2025-01-15",
      "devise_principale": "EUR"
    },
    {
      "id": "cto-bd",
      "nom": "CTO Bourse Direct",
      "type": "CTO",
      "broker": "Bourse Direct",
      "numero": "...",
      "date_ouverture": "2024-06-01",
      "devise_principale": "EUR"
    }
  ]
}
```

### `data/titres.json`

Catalogue des titres connus. **Aucune information de cours**.

```json
{
  "titres": [
    {
      "id": "stm",
      "ticker": "STMPA",
      "nom": "STMicroelectronics N.V.",
      "isin": "NL0000226223",
      "marche": "Euronext Paris",
      "devise": "EUR",
      "secteur": "Semi-conducteurs",
      "site_ir": "https://investors.st.com",
      "perspectives": "Cycle bas auto/industriel, rebond attendu, montée SiC",
      "these_lt": "Acteur européen stratégique des semi-conducteurs.",
      "signaux_mt_positifs": "Stabilisation CA, reprise commandes auto",
      "signaux_mt_negatifs": "Marge opérationnelle < 10%, perte gros contrat",
      "horizon": "5-10 ans",
      "verse_dividende": true,
      "frequence_dividende": "trimestriel",
      "date_creation": "2026-04-18"
    }
  ]
}
```

### `data/mouvements.json` — le cœur de l'application

Tous les types de mouvements dans une même collection, identifiés par leur champ `type`.

```json
{
  "mouvements": [
    {
      "id": "uuid-1",
      "type": "alimentation_cash",
      "compte_id": "pea-bd",
      "date": "2026-04-15",
      "montant": "30.00",
      "devise": "EUR",
      "libelle": "Virement permanent mensuel",
      "notes": "Premier mois du DCA"
    },
    {
      "id": "uuid-2",
      "type": "achat",
      "compte_id": "pea-bd",
      "titre_id": "dcam",
      "date": "2026-04-15",
      "quantite": 5,
      "prix_unitaire": "5.66",
      "devise": "EUR",
      "frais_courtage": "0.00",
      "taux_change": "1.0",
      "notes": "Investissement programmé sans frais"
    },
    {
      "id": "uuid-3",
      "type": "vente",
      "compte_id": "pea-bd",
      "titre_id": "soi",
      "date": "2026-04-19",
      "quantite": 1,
      "prix_unitaire_vente": "156.50",
      "devise": "EUR",
      "frais_courtage": "0.99",
      "calcul_fifo": {
        "lots_consommes": [
          {
            "achat_id": "uuid-soi-achat-1",
            "quantite": 1,
            "prix_unitaire_achat": "62.00",
            "frais_alloues": "0.50"
          }
        ],
        "prix_revient_total": "62.50",
        "produit_vente_net": "155.51",
        "plus_value_realisee": "93.01"
      },
      "notes": "Vente sur valorisation excessive +227% en 1 mois (bulle locale)"
    },
    {
      "id": "uuid-4",
      "type": "dividende_recu",
      "compte_id": "cto-bd",
      "titre_id": "stm",
      "date": "2026-06-24",
      "quantite_titres_concernes": 2,
      "montant_brut_par_action": "0.09",
      "montant_brut_total": "0.18",
      "devise": "USD",
      "taux_change": "1.13",
      "montant_net_eur": "0.16",
      "notes": "Acompte trimestriel STM"
    },
    {
      "id": "uuid-5",
      "type": "retrait_cash",
      "compte_id": "cto-bd",
      "date": "2026-04-18",
      "montant": "97.78",
      "devise": "EUR",
      "libelle": "Virement vers compte bancaire",
      "notes": "Ajustement trésorerie CTO"
    }
  ]
}
```

### Champ `calcul_fifo` : explication

Lors d'une vente, l'application calcule **automatiquement** :
- Les lots d'achat « consommés » selon FIFO (First In, First Out).
- Le prix de revient pondéré (incluant les frais d'achat alloués proportionnellement).
- Le produit net de la vente (prix vente − frais de vente).
- La plus-value réalisée.

Ce détail est **stocké de façon immuable** au moment de la vente pour garantir la traçabilité fiscale, même si tu corriges un achat plus tard.

### `data/watchlist.json`

Titres surveillés mais **pas encore détenus**, ou décisions à mûrir.

```json
{
  "watchlist": [
    {
      "id": "uuid-w-1",
      "titre_id": "ifx",
      "ticker": "IFX",
      "nom": "Infineon Technologies",
      "marche": "Xetra",
      "devise": "EUR",
      "compte_cible": "pea-bd",
      "these_lt": "Best-in-class européen sur SiC, complète STM. Éligible PEA.",
      "priorite": "haute",
      "ajoute_le": "2026-04-18",
      "notes": "À étudier quand cash dispo sur PEA"
    },
    {
      "id": "uuid-w-2",
      "titre_id": "soi",
      "nom": "Soitec",
      "statut": "rachat_potentiel",
      "these_lt": "Vendu en avril 2026 sur bulle. Racheter en cas de correction.",
      "paliers_rachat": [
        {"prix": "80", "tranche": "1/3", "commentaire": "Premier rachat"},
        {"prix": "65", "tranche": "1/3", "commentaire": "Renforcement"},
        {"prix": "50", "tranche": "1/3", "commentaire": "Renforcement final"}
      ],
      "echeance_abandon": "2027-10-19",
      "ajoute_le": "2026-04-19"
    }
  ]
}
```

### `data/evenements.json`

Événements à surveiller — alimentent le calendrier ICS.

```json
{
  "evenements": [
    {
      "id": "uuid-e-1",
      "titre_id": "stm",
      "type": "publication_resultats",
      "date": "2026-04-23",
      "libelle": "Résultats T1 2026 STMicroelectronics",
      "notes": "Surveiller guidance, carnet auto, SiC"
    },
    {
      "id": "uuid-e-2",
      "type": "rappel_personnel",
      "date": "2027-04-19",
      "libelle": "Réévaluer thèse Soitec — 12 mois après vente",
      "notes": "Si pas racheté, abandonner et allouer ailleurs"
    }
  ]
}
```

---

## 🧮 Logique métier clé : le PRU FIFO

### Principe

À chaque achat, on enregistre un **lot** : quantité, prix unitaire, frais. À chaque vente, on **consomme les lots dans l'ordre chronologique** (le plus ancien d'abord).

### Exemple concret

**Historique des achats sur STM (CTO)** :
1. 12/08/2025 : 2 actions à 34,12 €, frais 1,99 € → lot A.
2. 18/02/2026 : 1 action à 28,50 €, frais 1,50 € → lot B.

**Vente le 25/04/2026 : 2 actions à 38,20 €, frais 1,99 €.**

**Application de FIFO** :
- On consomme d'abord le lot A (le plus ancien) en entier : 2 actions à 34,12 €.
- Frais d'achat alloués au lot A : 1,99 € (totalité car on consomme tout le lot).
- **Prix de revient des 2 actions** = 2 × 34,12 + 1,99 = **70,23 €**.

**Calcul de la vente** :
- Produit brut = 2 × 38,20 = 76,40 €.
- Frais de vente : 1,99 €.
- **Produit net** = 76,40 − 1,99 = **74,41 €**.

**Plus-value réalisée** = 74,41 − 70,23 = **+4,18 €**.

Le **lot B reste intact** pour les ventes futures.

### Cas particulier : vente partielle d'un lot

Si on vend **1 seule action** au lieu de 2 dans l'exemple ci-dessus :
- On consomme **la moitié** du lot A.
- Frais d'achat alloués : 1,99 / 2 = 0,995 €.
- Prix de revient = 34,12 + 0,995 = 35,115 €.
- Le lot A est mis à jour : il reste 1 action à 34,12 € avec 0,995 € de frais résiduels.

### Précision financière

**Tous les calculs financiers utilisent `decimal.Decimal`**, jamais `float`, pour éviter les erreurs d'arrondi.

```python
from decimal import Decimal, ROUND_HALF_UP

prix = Decimal("34.12")
quantite = Decimal("2")
frais = Decimal("1.99")
prix_revient = (prix * quantite + frais).quantize(
    Decimal("0.01"), rounding=ROUND_HALF_UP
)
```

---

## 🚀 Plan de développement

> **État au 2026-06-08** : version **v2.0** livrée.
> Détails par version dans [`CHANGELOG.md`](CHANGELOG.md). Prochaines
> étapes dans [`ROADMAP.md`](ROADMAP.md).

| Version | Thème | Livré |
|---|---|---|
| **v1.0** | Fondations + Mouvements + Titres + Watchlist + Fiscal (itérations 1-5 du plan initial) | ✅ |
| **v1.1** | Publication mobile chiffrée (GH Pages + AES-256-GCM) | ✅ |
| **v1.2** | Virements programmés (DCA, rattrapage automatique) | ✅ |
| **v2.0** | Pivot UX/valorisation : import xlsx BD · valo jour J · courbe d'équity · camemberts · CSV · onglets · VALARM · PWA · module Prédictions | ✅ |

Les sous-sections détaillées qui suivaient ce tableau ont été déplacées dans
[`CHANGELOG.md`](CHANGELOG.md) pour garder ce README focalisé sur le **comment
utiliser** plutôt que sur le **comment on en est arrivé là**.

Voir [`CHANGELOG.md`](CHANGELOG.md) pour l'historique détaillé des livraisons
et [`ROADMAP.md`](ROADMAP.md) pour les chantiers en réflexion.

---

## ⚙️ Installation et lancement

Trois modes coexistent : **usage quotidien** (service systemd, ce que tu utilises
99 % du temps), **mode développement** (quand tu modifies le code), et
**première installation** (à faire une seule fois, déjà accomplie ici).

Projet déjà installé dans `/var/www/html/Bourse/`. L'app écoute sur
`http://127.0.0.1:5000`.

### A. Usage quotidien (service systemd utilisateur)

C'est le mode nominal. Le service tourne en arrière-plan, sans terminal
ouvert. Aucun sudo nécessaire.

```bash
systemctl --user status   suivi-portefeuille    # état
systemctl --user start    suivi-portefeuille    # démarrer
systemctl --user stop     suivi-portefeuille    # arrêter
systemctl --user restart  suivi-portefeuille    # après modif code
journalctl --user -u suivi-portefeuille -f      # logs temps réel
```

Le service est déjà activé au login (`enable --now`). Pour qu'il tourne
**même sans session graphique ouverte** (déjà fait une fois pour toutes) :

```bash
sudo loginctl enable-linger $USER
```

### B. Mode développement (Flask en foreground)

Quand tu modifies le code et veux voir les erreurs directement dans la
console, **avec le bouton « Publier vers mobile » fonctionnel**, utiliser
le wrapper `tools/dev.sh` qui injecte les env vars du drop-in systemd :

```bash
systemctl --user stop suivi-portefeuille
cd /var/www/html/Bourse
./tools/dev.sh
```

Variante minimale (sans bouton publier) :

```bash
.venv/bin/python run.py
```

> ⚠️ Toujours `.venv/bin/python`, jamais `python` ou `python3` du système —
> Flask n'y est pas installé (`ModuleNotFoundError: No module named 'flask'`).
>
> 💡 Le bouton **📱 Publier vers mobile** nécessite `BOURSE_PASSWORD` et
> `BOURSE_DASHBOARD_REPO`. Ces vars sont **uniquement** dans le drop-in
> systemd (par sécurité). Sans le wrapper `tools/dev.sh`, le bouton échouera
> en mode dev avec « Variable d'environnement BOURSE_DASHBOARD_REPO non définie ».

### C. Publication chiffrée vers mobile

Voir [`tools/SETUP_CLOUD.md`](tools/SETUP_CLOUD.md) pour le setup initial
(repo GitHub Pages + mot de passe ≥ 15 caractères). Une fois en place, trois
manières de publier :

| Mode | Commande | Cadence type |
|---|---|---|
| Bouton UI | Dashboard → **📱 Publier vers mobile** | À la demande |
| CLI | `.venv/bin/python tools/publier_dashboard.py` | Après batch de saisies |
| Cron | `0 22 * * * cd /var/www/html/Bourse && .venv/bin/python tools/publier_dashboard.py` | Quotidien automatique |

La consultation mobile se fait ensuite sur l'URL GitHub Pages, avec
déchiffrement WebCrypto côté navigateur (mot de passe mémorisé en
`localStorage`).

### D. Première installation (référence, déjà accomplie)

<details>
<summary>Commandes historiques pour bootstrapper le projet</summary>

```bash
mkdir -p ~/projets/suivi-portefeuille && cd ~/projets/suivi-portefeuille
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
mkdir -p app/routes app/services app/templates app/static/css \
         app/static/js data tests tools
echo '{"comptes": []}'    > data/comptes.json
echo '{"titres": []}'     > data/titres.json
echo '{"mouvements": []}' > data/mouvements.json
echo '{"watchlist": []}'  > data/watchlist.json
echo '{"evenements": []}' > data/evenements.json
./tools/install-systemd.sh
systemctl --user enable --now suivi-portefeuille
```

</details>

---

## 📐 Bonnes pratiques à respecter

### Précision financière

- **Toujours utiliser `decimal.Decimal`** pour les montants, jamais `float`.
- **Arrondir à 2 décimales** avec `ROUND_HALF_UP` au moment de l'affichage et du stockage final.
- **Stocker les montants en chaîne JSON** (`"34.12"`) pour éviter les pertes de précision lors de la (dé)sérialisation.

### Atomicité des écritures JSON

Pour éviter de corrompre un fichier JSON en cas de crash pendant l'écriture :

```python
import json
import os
import tempfile
from pathlib import Path
from decimal import Decimal


class DecimalEncoder(json.JSONEncoder):
    """Encodeur JSON qui sérialise Decimal en string."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def ecrire_json_atomique(chemin: Path, donnees: dict) -> None:
    """Écrit un fichier JSON de manière atomique."""
    chemin = Path(chemin)
    dossier = chemin.parent
    with tempfile.NamedTemporaryFile(
        mode='w',
        dir=dossier,
        delete=False,
        suffix='.tmp',
        encoding='utf-8',
    ) as f:
        json.dump(
            donnees, f,
            indent=2,
            ensure_ascii=False,
            cls=DecimalEncoder,
        )
        f.flush()
        os.fsync(f.fileno())
        chemin_temp = f.name
    os.replace(chemin_temp, chemin)
```

### Sécurité des données

- **Ne jamais committer le dossier `data/`** si Git est utilisé plus tard (numéros de compte, montants).
- Ajouter à `.gitignore` :
  ```
  data/
  .venv/
  __pycache__/
  *.pyc
  *.tmp
  .env
  ```
- **Valider toutes les entrées utilisateur** côté serveur.
- **Auto-escape Jinja2 activé par défaut** pour éviter les injections HTML.

### Sauvegarde

Les fichiers JSON sont l'**unique source de vérité**. Sauvegarder régulièrement le dossier `data/` :

- Script `tools/backup.sh` qui copie `data/` vers un dossier daté.
- Snapshot automatique vers Nextcloud / Dropbox personnel.

Exemple de script :

```bash
#!/bin/bash
# tools/backup.sh
DATE=$(date +%Y%m%d-%H%M%S)
DEST="$HOME/sauvegardes/suivi-portefeuille"
mkdir -p "$DEST"
tar czf "$DEST/data-$DATE.tar.gz" data/
echo "Sauvegarde créée : $DEST/data-$DATE.tar.gz"

# Garder les 30 dernières sauvegardes
cd "$DEST" && ls -1t data-*.tar.gz | tail -n +31 | xargs -r rm
```

### Automatisation via systemd timer (recommandé)

Sauvegarde quotidienne à 12h00, avec rattrapage si le PC était éteint
(`Persistent=true`). Cohérent avec le service `suivi-portefeuille` déjà
en place, logs centralisés via `journalctl`.

```bash
# Service unit
cat > ~/.config/systemd/user/suivi-portefeuille-backup.service <<'EOF'
[Unit]
Description=Sauvegarde quotidienne des donnees Suivi Portefeuille

[Service]
Type=oneshot
ExecStart=/var/www/html/Bourse/tools/backup.sh
EOF

# Timer unit
cat > ~/.config/systemd/user/suivi-portefeuille-backup.timer <<'EOF'
[Unit]
Description=Declenche la sauvegarde quotidienne Suivi Portefeuille a 12h00

[Timer]
OnCalendar=*-*-* 12:00:00
Persistent=true
Unit=suivi-portefeuille-backup.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now suivi-portefeuille-backup.timer
```

**Commandes utiles :**

```bash
systemctl --user list-timers suivi-portefeuille-backup.timer  # prochaine exec
systemctl --user start suivi-portefeuille-backup.service      # lancer maintenant
journalctl --user -u suivi-portefeuille-backup.service        # historique
```

> ⚠️ Pour que le timer tourne **même sans session graphique ouverte** :
> `sudo loginctl enable-linger $USER` (idem que pour le service Flask).
> Sans linger, le timer ne se déclenche que pendant tes sessions —
> acceptable si le PC est typiquement allumé à 12h00.

### Tests

- Chaque service de calcul **doit avoir ses tests unitaires**.
- `pytest tests/` à lancer avant chaque modification importante.
- Tests à privilégier :
  - PRU FIFO avec plusieurs lots et ventes partielles.
  - Plus-values avec frais.
  - Soldes cash avec mouvements multi-devises.
  - Génération ICS avec dates et fuseaux horaires.

### Internationalisation et formats

- Tout en **français** (interface, labels, messages d'erreur).
- **Format de date** : ISO `YYYY-MM-DD` en stockage, `DD/MM/YYYY` en affichage.
- **Format des montants** : séparateur de milliers `espace`, décimale `,` (style français).
- **Devises** : code ISO 4217 (`EUR`, `USD`).

---

## 🎓 Aspects pédagogiques (apprentissage Python)

Ce projet est aussi une opportunité de **monter en compétence Python** depuis tes bases en PHP/Symfony.

### Concepts Python à maîtriser au fil des itérations

| Itération | Concepts découverts |
|---|---|
| 1 | Flask basics, Blueprints, application factory, Jinja2 (proche Twig), `pathlib` |
| 2 | Type hints, dataclasses, validation d'entrées, `decimal.Decimal`, datetime |
| 3 | Logique métier séparée des routes, mutations immutables |
| 4 | Manipulation iCalendar, génération de fichiers, headers HTTP |
| 5 | Calculs financiers complexes, génération PDF (optionnelle) |

### Pièges Python pour développeur PHP

- **Indentation = syntaxe** : 4 espaces, pas de tabs. Erreur d'indentation = erreur de compilation.
- **Pas de `;`** en fin de ligne. Les retours à la ligne sont significatifs.
- **`dict` ≠ `array` PHP** : un dictionnaire Python est strictement clé→valeur. Pour des listes ordonnées, utiliser `list`.
- **`None` ≠ `null`** mais comportement similaire. Utiliser `is None` pour comparer.
- **Le scope** est fonctionnel, pas bloc. Les variables d'une boucle persistent après.
- **Décorateurs** : Flask en utilise beaucoup (`@app.route(...)`), équivalents des annotations Symfony.
- **F-strings** : `f"Bonjour {nom}"` remplace les concaténations PHP `"Bonjour " . $nom`.
- **`float` vs `Decimal`** : ne JAMAIS utiliser `float` pour de l'argent.

### Jinja2 vs Twig — les rares différences

| Twig | Jinja2 |
|---|---|
| `{{ user.name }}` | `{{ user.name }}` ✅ identique |
| `{% for item in list %}` | `{% for item in list %}` ✅ identique |
| `{% if condition %}` | `{% if condition %}` ✅ identique |
| `{{ user.name|escape }}` | `{{ user.name|e }}` ✅ |
| `{% set var = value %}` | `{% set var = value %}` ✅ identique |
| `{{ date|date("Y-m-d") }}` | `{{ date.strftime("%Y-%m-%d") }}` ⚠️ syntaxe Python |
| `{% include "template.twig" %}` | `{% include "template.html" %}` ✅ |

La transition est essentiellement transparente.

---

## ✅ Hygiène avant une modification

Checklist rapide avant de pousser une modification de code ou de données :

- [ ] Tests verts : `cd /var/www/html/Bourse && .venv/bin/pytest`
- [ ] Sauvegarde fraîche de `data/` : `./tools/backup.sh`
- [ ] Si modif code en cours : service systemd **arrêté** pour éviter le
      conflit de port (`systemctl --user stop suivi-portefeuille`), puis
      relancé après (`restart`)
- [ ] Si modif des modèles JSON : prévoir un script de migration dans
      `tools/` (cf. `migrer_*.py` existants pour les patterns)
- [ ] Publication mobile à refaire si l'export en a besoin
      (`.venv/bin/python tools/publier_dashboard.py`)

---

## 🔮 Évolutions possibles à long terme

À étudier seulement quand l'app sera mature :

1. **Migration vers SQLite** si les fichiers JSON deviennent gros (>1 Mo).
2. **Module fiscal avancé** : génération automatique du formulaire 2074 PDF.
3. **Intégration calendrier bidirectionnelle** via CalDAV.
4. **Mode lecture mobile** : interface responsive ou PWA.
5. **Module benchmarking optionnel** : comparaison avec un indice de référence.
6. **Chiffrement des données** si hébergement sur cloud personnel.

---

## 📝 Notes de conception

### Pourquoi Flask et pas Django ?

Pour ce besoin personnel, Django serait surdimensionné (admin, ORM, auth multi-utilisateur). Flask reste minimaliste, et tu peux tout maîtriser dans ta tête.

### Pourquoi JSON et pas SQLite ?

- **Lisibilité humaine** : tu peux ouvrir `data/titres.json` dans VSCode et corriger une faute.
- **Versioning simple** : si Git est utilisé, les diffs sont compréhensibles.
- **Pas de schéma à migrer** : tu peux ajouter un champ sans `ALTER TABLE`.
- **Pour ton volume** (quelques dizaines de titres, quelques centaines de mouvements à terme), JSON est largement suffisant.
- SQLite devient utile au-delà de quelques milliers de lignes et pour des requêtes complexes.

### Pourquoi pas de récupération automatique des cours ?

Choix volontaire, maintenu en v2.0 :
- **Reflète l'usage long terme** : pas besoin de cours streamés pour un horizon 5-10 ans.
- **Élimine toute dépendance externe** (Yahoo Finance peut casser, changer ses limites, demander une API key).
- **L'utilisateur pilote la fraîcheur** via l'import xlsx Bourse Direct (`/titres/import`) — un clic, multi-fichiers, idempotent.
- **Simplifie radicalement** le projet (pas de gestion d'erreurs réseau, pas de cache de cours, pas de coût d'API).
- Le bandeau « ⚠ cours à actualiser » sur le dashboard se déclenche dès que les cours datent de plus de 7 jours.

### Pourquoi pas d'alertes de prix en streaming ?

- **Bourse Direct gère déjà les alertes natives** (par email, en push).
- **Une alerte temps réel n'a pas sa place** dans un journal de bord long terme.
- **Le calendrier ICS avec VALARM** (depuis v2.0) suffit pour les événements prévisibles : tes apps de calendrier (Thunderbird, GNOME Calendar, Apple Calendar) sonnent à J-1 ou J-2 selon le type d'événement, sans rien à configurer côté serveur.

### Pourquoi pas de framework JS ?

- **Sur-ingénierie** pour ce besoin.
- Flask + Jinja2 rendent côté serveur, c'est largement suffisant.
- Quelques touches de JS vanilla suffisent.
- Si besoin un jour : **htmx** est une excellente option pour ajouter de l'interactivité sans framework lourd.

---

## 📞 Reprise du projet

Pour redémarrer après une longue pause (de soi-même ou de Claude) :

1. **Où sont les données** : [`/var/www/html/Bourse/data/`](data/) — source
   de vérité unique, non versionnée. Dernière sauvegarde dans
   `$HOME/sauvegardes/suivi-portefeuille/`.
2. **Vérifier que l'app tourne** :
   `systemctl --user status suivi-portefeuille` → sinon `start`.
3. **Ouvrir le dashboard** : <http://127.0.0.1:5000>.
4. **Statut courant** : voir le tableau en tête du § *Plan de développement*.
   Détails livraison dans [`CHANGELOG.md`](CHANGELOG.md), prochaines étapes
   dans [`ROADMAP.md`](ROADMAP.md).
5. **Pour modifier le code** : passer en mode dev (§ B *Installation et
   lancement*), tester (`.venv/bin/pytest`), redémarrer le service.
6. **Pour le mobile** : voir [`tools/SETUP_CLOUD.md`](tools/SETUP_CLOUD.md).

---

## Auteur

Emmanuel — pour usage personnel.
Projet planifié en avril 2026, démarrage en mai 2026, v2.0 livrée en juin 2026.

**Philosophie** : un journal de bord structuré pour soutenir des décisions d'investissement long terme, en complément (et non en remplacement) de l'interface broker. Depuis la v2.0, il intègre aussi la **valorisation au jour J** et les **graphiques** sans renoncer au principe « 100 % offline en runtime, données chez soi ».