# Roadmap

Prochaines étapes structurées par horizon. Les livraisons passées sont dans [`CHANGELOG.md`](CHANGELOG.md).

---

## 🎯 Cibles immédiates (1-2 semaines)

Aucune cible immédiate active — la v2.0 vient d'être livrée. La prochaine
session démarrera selon les sujets ci-dessous, après quelques jours de
réflexion utilisateur.

---

## 🤔 En réflexion (à décider à la prochaine session)

| Chantier | Effort | ROI | Pourquoi maintenant ? |
|---|---|---|---|
| **Docker Compose + Dockerfile** | 🟠 moyen (2-3 j) | 🟢 fort | Débloque le grand public Mac/Windows (80 % du marché 10 €). Couplé à l'onboarding. |
| **Onboarding** : jeu d'exemple + écran d'accueil vide | 🟢 petit (1-2 j) | 🟢 fort | Sans ça, un nouvel utilisateur arrive sur un dashboard vide sans savoir quoi faire. À coupler avec Docker. |
| **Notifications email digest quotidien** | 🟠 moyen (2-3 j) | 🟡 moyen | Complément de l'ICS (l'ICS dépend du calendrier natif de l'utilisateur). Pour ceux qui veulent un mail à 8 h chaque matin. |

---

## 💭 Idées long terme (sans urgence)

### PWA v2.1+ — Push + saisie

- **Web Push (VAPID)** : pousser une notif sur le téléphone (« Détachement dividende STM aujourd'hui »).
- **Saisie depuis mobile** : taper un mouvement d'achat depuis l'iPhone et le faire revenir sur le PC.
  - Option A : sync Git bidirectionnelle (mobile push commit chiffré → desktop pull).
  - Option B : file d'attente chiffrée (mobile écrit dans le repo, desktop consomme).
- Effort : 1-2 semaines selon ambition.

### Distribution exécutable cross-platform

Phasé selon l'audience.

| Phase | Cible | Effort | Coût annexe |
|---|---|---|---|
| **10a — AppImage Linux** (PyInstaller + pywebview) | Linuxiens non-tech | 🟠 1-2 j | Gratuit. À faire après Docker. |
| **10b — Mac/Windows signés** (.dmg / .exe) | Grand public payant | 🔴 2-3 sem | ~99 $/an Apple + ~250-400 €/an cert Windows. **À ne lancer qu'après 50-100 utilisateurs payants confirmés.** |
| **10c — Briefcase** (.msi / .pkg installeurs natifs) | Audience établie | 🔴 2-3 sem | Voir 10b. |

### Autres pistes

- **Comparaison avec indices** (vs MSCI World, CAC 40) en surimpression sur la courbe d'équity.
- **Génération PDF du formulaire 2074** pré-rempli depuis le récap fiscal (ReportLab ou WeasyPrint).
- **Migration JSON → SQLite** : uniquement si les fichiers dépassent ~1 Mo ou les requêtes deviennent lentes (peu probable à l'horizon visible).
- **Multi-utilisateur** : pas dans l'esprit du produit, à éviter sauf demande explicite.

---

## 🚫 Hors scope volontaire

Ces sujets ne seront pas implémentés sauf changement majeur d'intention :

- **Cours en temps réel** : choix assumé. L'import xlsx Bourse Direct couvre 90 % du besoin sans dépendance réseau.
- **Alertes de prix en push live** : couvertes par les VALARM du calendrier ICS.
- **Trading actif / options / dérivés** : hors cible (petit porteur buy & hold + DCA).
