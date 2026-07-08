# Changelog

Historique des livraisons. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [v2.1] — 2026-07-08 · Gestion depuis la fiche & clarté trésorerie

Session de raffinements : investir via le DCA devient fluide, la **fiche titre** devient le centre de gestion (mouvements, ordres, plan de rachat), et le tableau de bord gagne en clarté (trésorerie, catégories).

### Ajouts

- **DCA fluidifié** — bouton « ✓ Enregistrer l'achat » directement sur la page Programmes, et **pré-remplissage** de la quantité et du prix du formulaire d'achat depuis le dernier cours importé (`cours_jour_eur`). ([app/services/virements_programmes.py](app/services/virements_programmes.py))
- **Panneau Trésorerie** au tableau de bord — cascade Versements/Ventes/Dividendes − Achats/Frais/Retraits = Solde espèces, puis − ordres d'achat en attente = **Disponible au comptant**, par compte. ([app/services/soldes.py](app/services/soldes.py))
- **Camembert « Par catégorie »** — champ `categorie` contrôlé sur les titres + classifieur automatique + **migration v2** de backfill. Fini le patchwork de secteurs libres. ([app/services/categories.py](app/services/categories.py))
- **Ordres actifs & plan de rachat gérables depuis la fiche titre** — mêmes données que la watchlist (source unique), création automatique d'une watch si absente. ([app/routes/titres.py](app/routes/titres.py))
- **Suppression d'un mouvement depuis l'historique de la fiche** (retour sur la fiche via `next`). ([app/routes/mouvements.py](app/routes/mouvements.py))

### Modifications

- **Programmes** — les indicateurs distinguent l'**investissement (DCA)** de l'**alimentation (cash)** ; « Prochain investissement » pointe le prochain DCA réel, pas le virement de financement. Bouton de rattrapage renommé « Générer les échéances manquantes » + confirmation rassurante.
- **Mobile** — Trésorerie desktop-only (retirée de l'export chiffré) ; camembert « Par catégorie ». Correctif service worker (cache toujours rafraîchi → plus de `data.enc.json` périmé).

### Technique

- Suite de tests portée à **413** verts (`test_categories`, `test_dca_flux`, `test_tresorerie`, `test_ordres_fiche`, `test_mouvements_suppression`).
- Migration de schéma **v2** (backfill `categorie`) appliquée au démarrage, avec sauvegarde.

### Sécurité

- **`cryptography` 48.0.0 → 48.0.1** — les wheels < 48.0.1 embarquaient un OpenSSL vulnérable ([advisory 2026-06-09](https://openssl-library.org/news/secadv/20260609.txt)). Corrige l'alerte Dependabot.

---

## [v2.0] — 2026-06-08 · Pivot UX / valorisation

Refonte massive de l'expérience : on passe d'un journal de bord pur à un **outil de pilotage complet** avec valorisation au jour J, graphiques, et expérience mobile native.

### Ajouts

- **Module Prédictions** ([app/services/predictions.py](app/services/predictions.py), [app/routes/predictions.py](app/routes/predictions.py), [app/templates/predictions/](app/templates/predictions/))
  - Paris directionnels datés (hausse / baisse) sans capital engagé, pour calibrer le jugement.
  - Saisie : titre catalogue ou libre · sens · cours référence · date d'échéance · conviction (1-5) · raisonnement.
  - Évaluation a posteriori : saisie du cours d'échéance → calcul `ecart_pct` (Decimal, ROUND_HALF_UP) + résultat juste/faux. Égalité stricte = faux (par convention).
  - Statistiques : taux de réussite global + par sens + par conviction.
  - 43 tests dédiés.

- **Import xlsx Bourse Direct** ([app/services/import_bourse_direct.py](app/services/import_bourse_direct.py))
  - Upload multi-fichiers (CTO + PEA en un clic).
  - Matching par ISIN, calcul `cours_eur = valorisation_eur / quantité`.
  - Création optionnelle des titres absents du catalogue.
  - Patch des namespaces OOXML obsolètes (BD utilise `purl.oclc.org` non standard).
  - Idempotent. 14 tests.

- **Valorisation au jour J au dashboard**
  - Nouveaux champs sur les titres : `cours_jour`, `cours_jour_eur`, `date_cours_jour`.
  - KPI « Portefeuille total » (cash + valo titres) et « PV latente » (colorée).
  - Colonnes Cours / Valo / PV latente dans le tableau des positions.
  - Bandeau d'alerte si cours > 7 jours ou positions sans cours.

- **Snapshot mensuel + courbe d'équity SVG** ([app/services/snapshots.py](app/services/snapshots.py))
  - Snapshot écrit à chaque import xlsx réussi (idempotent par jour).
  - Courbe d'évolution SVG native (pas de Chart.js), série mensuelle 24 mois max.
  - 9 tests.

- **Camembert d'allocation SVG** ([app/services/repartition.py](app/services/repartition.py))
  - 3 axes : par compte, par secteur, par devise.
  - Arcs SVG natifs, palette DSFR, gestion du cas « une seule part = cercle ».
  - 10 tests.

- **Export CSV** ([app/services/csv_export.py](app/services/csv_export.py))
  - `GET /mouvements/export.csv` (respecte les filtres en cours).
  - `GET /recap-fiscal/<annee>/export.csv` avec ventilation par compte + ligne TOTAL.
  - Format UTF-8 BOM, séparateur `;`, virgule décimale (compatible Excel / LibreOffice FR).
  - 5 tests.

- **Onglets dashboard desktop** : « 📊 Portefeuille en chiffres » / « 📈 Portefeuille en graphiques »
  - Persistance du choix via `localStorage`.
  - Sidebar Agenda + Watchlist haute reste affichée dans les deux onglets.

- **Bulles d'aide UX** sur Watchlist / Programmes / Événements
  - `<details>` repliable « 💡 Quand utiliser cette page ? » qui clarifie la frontière entre les 3 modules.
  - Section consolidée dans le README (tableau de décision).

- **Notifications via VALARM dans ICS** ([app/services/ics_export.py](app/services/ics_export.py))
  - Rappels DCA / rappels personnels : J-2.
  - Publications / dividendes / AG : J-1.
  - Validité ordres limite watchlist : J-2.
  - Échéances d'abandon watchlist : J-1.
  - Calendrier réel : 9 alarmes générées sur la base courante.

- **PWA mobile v2.0** ([tools/templates/](tools/templates/))
  - Manifest, 3 icônes PNG (192/512/180) générées via `rsvg-convert` depuis un SVG source, service worker avec versionning par BUILD_ID.
  - Stratégie : network-first + fallback cache pour `data.enc.json`, network-first pour le shell, cache-first pour les icônes.
  - Indicateur « 📡 mode hors ligne » dans l'en-tête si `!navigator.onLine`.
  - Installable sur écran d'accueil iOS / Android, mode standalone.

- **Édition des prédictions et watchlist refondue**
  - Watchlist : un seul ordre limite « actif » par position au lieu d'une liste multi-textareas, picker de date pour la validité, historique des ordres clos avec bouton « ↻ Réactiver ».
  - Prédictions : édition complète d'une prédiction en cours, picker de date pour l'échéance.

- **Bouton « ✓ Honorer » sur les rappels DCA** ([app/templates/evenements/liste.html](app/templates/evenements/liste.html))
  - Pré-remplit un mouvement d'achat depuis le rappel (titre, compte, devise, montant cible).
  - Marque l'événement comme honoré après création du mouvement (champ `mouvement_id` ajouté).

### Changements

- Page mobile : layout cartes par position au lieu de tableau 6 colonnes (lisibilité petits écrans).
- Récap mobile et desktop synchronisé via `dashboard_data.construire()` enrichi.
- Section « 🔀 Watchlist vs Programmes vs Événements » ajoutée au README.

### Tests

- **262 tests verts** au total (vs 197 avant la v2.0).
- Aucun test cassé pendant le pivot.

---

## [v1.x] — 2026-04 → 2026-05 · Bonus hors plan initial

### v1.2 — Virements programmés

Module `virements_programmes.json` : engagements récurrents (virement bancaire permanent + DCA). Rattrapage automatique à chaque ouverture du dashboard. Génère :

- `alimentation_cash` (mouvement) pour les programmes sans titre.
- `rappel_personnel` (événement) pour les DCA (à honorer manuellement après exécution broker).

### v1.1 — Publication mobile chiffrée

Chiffrement AES-256-GCM côté serveur (PBKDF2-SHA256 200 000 itérations, mot de passe ≥ 15 chars). `tools/publier_dashboard.py` pousse `index.html` + `data.enc.json` vers un repo Git séparé (GitHub Pages). Déchiffrement WebCrypto côté navigateur.

Doc détaillée : [`tools/SETUP_CLOUD.md`](tools/SETUP_CLOUD.md).

---

## [v1.0] — 2026-02 → 2026-04 · Itérations 1 à 5 du plan initial

### Itération 5 — Récapitulatifs fiscaux

Récap fiscal par année et par compte. CTO : tableau 2074, plus-values réalisées par titre, suivi des moins-values reportables (10 ans). PEA : récap opérations internes + suivi plafond (150 000 €) et durée (≥ 5 ans). Stats annuelles globales.

### Itération 4 — Watchlist et calendrier ICS

CRUD watchlist (priorités, paliers de rachat, ordres limite). CRUD événements (publications, dividendes, rappels). Endpoint `/calendrier.ics` consommable par GNOME Calendar / Thunderbird / Apple Calendar.

### Itération 3 — Titres et thèses LT

Page dédiée par titre avec métadonnées (ISIN, secteur), thèse long terme versionnée, signaux MT positifs/négatifs, historique mouvements pour ce titre, plus-values réalisées cumulées.

### Itération 2 — Saisie des mouvements (cœur)

Formulaires CRUD pour les 6 types de mouvements (alimentation/retrait cash, achat, vente, dividende, frais). Calcul FIFO automatique des plus-values sur ventes. Reconstitution dynamique du solde cash à chaque consultation. Liste filtrable.

### Itération 1 — Fondations

Application factory Flask, service de stockage JSON avec écriture atomique, modèles JSON initialisés, dashboard de base, template `base.html`.

---

## Notes de versioning

- Les versions suivent un schéma proche de SemVer mais sans contrainte forte sur les ruptures (l'app est mono-utilisateur, pas d'API publique).
- Les versions « **v1.x** » sont les itérations du plan initial + bonus hors-plan.
- La version **v2.0** marque le pivot UX/valorisation : l'app passe d'un journal de bord à un outil de pilotage avec graphiques et expérience mobile native.
