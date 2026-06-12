# Installer Suivi Portefeuille sur Windows

Guide pour utiliser l'application sur **Windows**, sans installer Python ni quoi
que ce soit de technique. Tu as reçu un fichier **`Suivi-Portefeuille-windows.zip`**.

> 🔒 **Tes données restent chez toi.** L'application tourne entièrement sur ton
> ordinateur. Rien n'est envoyé sur Internet, sauf si **toi** tu actives la
> publication mobile (voir [GUIDE_MOBILE_AMI.md](GUIDE_MOBILE_AMI.md)).

---

## 1. Décompresser et lancer

1. **Clic droit** sur `Suivi-Portefeuille-windows.zip` → **Extraire tout…**
2. Ouvre le dossier extrait, double-clique sur **`Suivi-Portefeuille.exe`**.
3. Au premier lancement, Windows met quelques secondes à démarrer, puis **ton
   navigateur s'ouvre tout seul** sur l'application (adresse `http://127.0.0.1:5000`).
4. Laisse la petite fenêtre du programme ouverte tant que tu utilises l'app.
   Pour quitter : ferme l'onglet du navigateur puis la fenêtre du programme.

> 💡 Garde le dossier extrait quelque part de stable (ex. `Documents`). Tu peux
> créer un raccourci vers `Suivi-Portefeuille.exe` sur le Bureau (clic droit →
> Envoyer vers → Bureau).

---

## 2. Les avertissements Windows (normaux)

Le programme n'est pas signé par un éditeur payant : Windows se montre prudent.
**Ce n'est pas un virus**, c'est juste un logiciel « inconnu » pour Windows.

### Écran bleu « Windows a protégé votre ordinateur » (SmartScreen)
→ Clique sur **« Informations complémentaires »** puis sur **« Exécuter quand même »**.

### L'antivirus (Windows Defender) bloque ou supprime le fichier
PyInstaller (la techno utilisée) déclenche parfois un **faux positif**. Si le
`.exe` disparaît ou est mis en quarantaine :
1. Ouvre **Sécurité Windows** → **Protection contre les virus et menaces** →
   **Historique de la protection** : tu peux **restaurer** le fichier.
2. Ajoute une **exclusion** sur le dossier de l'application : Paramètres de la
   protection → **Exclusions** → Ajouter → Dossier.

En cas de doute, tu peux faire analyser le fichier sur <https://www.virustotal.com/>.

### Le pare-feu demande une autorisation
Au premier lancement, Windows peut demander d'autoriser le programme sur le
**réseau privé**. Tu peux **autoriser** (l'app n'écoute que sur ton propre PC)
ou refuser : l'application fonctionne quand même en local.

---

## 3. Où sont mes données ?

Tes données (comptes, mouvements, titres…) sont enregistrées **hors** du dossier
de l'application, ici :

```
C:\Users\TON_NOM\AppData\Local\Suivi-Portefeuille\data
```

(Copie-colle `%LOCALAPPDATA%\Suivi-Portefeuille\data` dans la barre d'adresse de
l'Explorateur pour y accéder directement.)

Conséquence pratique : **tu peux remplacer le `.exe` par une nouvelle version
sans perdre tes données** — elles ne sont pas dans le dossier du programme.

---

## 4. Sauvegarder mes données

- L'application crée **automatiquement une sauvegarde** (archives `.zip` dans le
  dossier `backups` à côté de `data`) avant toute mise à jour interne du format.
  Ces archives **excluent** ton token GitHub : tu peux les partager sans risque.
- **Sauvegarde manuelle** : copie le dossier
  `%LOCALAPPDATA%\Suivi-Portefeuille\data` sur une clé USB ou un cloud perso.
  ⚠️ Ce dossier contient le fichier `reglages.json` avec **ton token GitHub** :
  garde cette copie **privée** (ou préfère les archives `backups/`, qui ne le
  contiennent pas).

> 🛠️ **Changer l'emplacement des données** (avancé) : définis la variable
> d'environnement `BOURSE_DATA_DIR` vers le dossier de ton choix avant de lancer
> l'application.

---

## 5. Premiers pas

Au tout premier lancement, l'app t'accueille avec un **écran de démarrage** :

1. **Crée ton premier compte** (PEA ou CTO).
2. (Optionnel) **Importe tes fichiers xlsx Bourse Direct** pour récupérer tes
   titres et leurs cours.
3. **Saisis tes mouvements** (achats, ventes, dividendes…).

Tu peux aussi cliquer **« Charger un jeu d'exemple »** pour voir l'app remplie
avant de saisir tes vraies données.

👉 Pour la suite (usage au quotidien, mobile), voir
[USAGE_POUR_AMI.md](USAGE_POUR_AMI.md).

---

## 6. Problèmes courants

| Symptôme | Solution |
|---|---|
| Le navigateur ne s'ouvre pas | Ouvre-le à la main et tape `http://127.0.0.1:5000`. |
| « Le port est déjà utilisé » | L'app choisit automatiquement un autre port — regarde l'adresse ouverte dans le navigateur. |
| Rien ne s'affiche / erreur | Un fichier `app.log` est créé dans `%LOCALAPPDATA%\Suivi-Portefeuille\data` : envoie-le pour diagnostic. |
| Defender supprime le `.exe` | Voir § 2 (restaurer + exclusion). |
