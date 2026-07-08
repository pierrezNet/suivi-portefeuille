#!/usr/bin/env python
"""Publication du dashboard vers un repo Git (GitHub Pages) chiffré.

Workflow :
  1. Calcule les agrégats du dashboard (dashboard_data.construire)
  2. Chiffre les données via AES-256-GCM + PBKDF2 (mot de passe `BOURSE_PASSWORD`)
  3. Écrit `data.enc.json` + `index.html` (page statique avec déchiffrement WebCrypto) dans le repo Git local
  4. `git add/commit/push` automatique

Variables d'environnement :
  BOURSE_PASSWORD          : mot de passe de chiffrement (obligatoire, ≥ 15 caractères)
  BOURSE_DASHBOARD_REPO    : chemin du repo Git local (obligatoire)
  BOURSE_DASHBOARD_BRANCH  : branche Git (défaut : main)
  BOURSE_DASHBOARD_NO_PUSH : si "1", commit local uniquement (utile pour tests)

Usage :
  python tools/publier_dashboard.py
  python tools/publier_dashboard.py --repo /chemin/vers/repo
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services import chiffrement, dashboard_data
from app.services.stockage import Depot, DecimalEncoder


def _chemin_ressource(rel: str) -> Path:
    """Résout une ressource embarquée, que l'app tourne depuis les sources ou
    depuis un bundle PyInstaller gelé.

    En .exe gelé, ``RACINE`` pointe dans le bundle temporaire ``_MEIPASS`` (lecture
    seule) : on s'y réfère explicitement pour retrouver les templates/assets.
    """
    base = Path(getattr(sys, "_MEIPASS", RACINE))
    return base / rel


TEMPLATES = _chemin_ressource("tools/templates")


class ConfigManquante(RuntimeError):
    """Variable d'environnement requise absente."""


class _EncodeurDashboard(DecimalEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, (_date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _format_date_fr(d: datetime) -> str:
    return d.strftime("%d/%m/%Y %H:%M")


def _enrichir_pour_export(data: dict) -> dict:
    now = datetime.now()
    out = dict(data)
    out["genere_le"] = now.isoformat()
    out["genere_le_fr"] = _format_date_fr(now)
    out.pop("titres", None)
    out.pop("virements_rattrapes", None)
    # La trésorerie (cascade cash + disponible) est desktop-only : on la retire
    # de l'export pour que la charge utile chiffrée et le rendu mobile restent
    # strictement inchangés (champ par compte + deux totaux globaux).
    out.pop("total_disponible_comptant", None)
    out.pop("total_reserve_ordres", None)
    out["comptes"] = [
        {k: v for k, v in c.items() if k != "tresorerie"}
        for c in data.get("comptes", [])
    ]
    return out


def _exec_git(args: list[str], cwd: Path) -> str:
    """Lance git avec gestion d'erreur lisible. Renvoie stdout."""
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} a échoué (exit={res.returncode}) :\n"
            f"stdout: {res.stdout}\nstderr: {res.stderr}"
        )
    return res.stdout


def _construire_fichiers(data_chiffre: dict, html: str) -> dict[str, bytes]:
    """Assemble le jeu de fichiers à publier, **indépendamment du transport**
    (git local ou API GitHub). Clé = chemin dans le repo, valeur = contenu.

    Ordre important pour le transport API (PUT un par un, non atomique) :
    le shell et les assets d'abord, ``data.enc.json`` **en dernier**. Ainsi un
    échec partiel laisse au pire « anciennes données + shell neuf » (bénin)
    plutôt que « données neuves + shell ancien » (cache incohérent).
    """
    fichiers: dict[str, bytes] = {
        "index.html": html.encode("utf-8"),
        # .nojekyll évite le pipeline Jekyll de GitHub Pages
        ".nojekyll": b"",
    }
    # Assets PWA (manifest, icônes)
    for nom in ("manifest.json", "icon.svg", "icon-192.png", "icon-512.png",
                "apple-touch-icon-180.png"):
        fichiers[nom] = (TEMPLATES / nom).read_bytes()
    # Service worker : BUILD_ID unique (date+heure) pour versionner le cache —
    # à chaque sync, l'ancien cache est purgé côté navigateur.
    build_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    sw = (TEMPLATES / "sw.js").read_text(encoding="utf-8").replace(
        "__BUILD_ID__", build_id
    )
    fichiers["sw.js"] = sw.encode("utf-8")
    # Données chiffrées EN DERNIER (cf. docstring).
    fichiers["data.enc.json"] = json.dumps(
        data_chiffre, indent=2, ensure_ascii=False
    ).encode("utf-8")
    return fichiers


def _ecrire_fichiers_disque(repo: Path, fichiers: dict[str, bytes]) -> None:
    """Écrit les fichiers dans le repo Git local (transport git)."""
    for nom, contenu in fichiers.items():
        (repo / nom).write_bytes(contenu)


def _preparer_fichiers(depot: Depot, mot_passe: str) -> dict[str, bytes]:
    """Construit + chiffre les données, rend le HTML, et assemble le jeu de
    fichiers prêt à publier. Commun aux transports git et API.

    Lève ``chiffrement.MotPasseInvalide`` si le mot de passe fait < 15 car.
    """
    data = dashboard_data.construire(depot, rattraper_virements=True)
    data = _enrichir_pour_export(data)
    # Sérialise les Decimal/dataclass/dates puis re-parse en types JSON purs.
    payload_clair = json.loads(
        json.dumps(data, cls=_EncodeurDashboard, ensure_ascii=False)
    )
    paquet = chiffrement.chiffrer(payload_clair, mot_passe)

    # HTML statique : CSS + JS inlinés, AUCUNE donnée métier en clair.
    css_inline = (TEMPLATES / "dashboard_mobile.css").read_text(encoding="utf-8")
    js_inline = (TEMPLATES / "cloud_app.js").read_text(encoding="utf-8")
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("cloud_index.html.j2").render(
        css_inline=css_inline,
        js_inline=js_inline,
    )
    return _construire_fichiers(paquet.to_dict(), html)


def _git_push(repo: Path, branche: str, message: str, push: bool = True) -> None:
    _exec_git(
        ["add", "data.enc.json", "index.html", ".nojekyll",
         "manifest.json", "sw.js", "icon.svg", "icon-192.png", "icon-512.png",
         "apple-touch-icon-180.png"],
        cwd=repo,
    )
    statut = _exec_git(["status", "--porcelain"], cwd=repo).strip()
    if not statut:
        print("ℹ Aucun changement à pousser (le contenu chiffré est identique).")
        return
    _exec_git(["commit", "-m", message], cwd=repo)
    if push:
        _exec_git(["push", "origin", branche], cwd=repo)


def publier(
    *,
    repo: str | Path | None = None,
    mot_passe: str | None = None,
    branche: str | None = None,
    push: bool | None = None,
    data_dir: str | Path | None = None,
) -> Path:
    """Effectue la publication complète. Renvoie le chemin du fichier HTML écrit."""
    repo_str = repo or os.environ.get("BOURSE_DASHBOARD_REPO")
    if not repo_str:
        raise ConfigManquante(
            "Variable d'environnement BOURSE_DASHBOARD_REPO non définie. "
            "Renseigne le chemin du repo Git local (ex: ~/projets/portefeuille-dashboard)."
        )
    repo_path = Path(repo_str).expanduser().resolve()
    if not repo_path.is_dir():
        raise ConfigManquante(f"Repo Git introuvable : {repo_path}")
    if not (repo_path / ".git").is_dir():
        raise ConfigManquante(
            f"{repo_path} n'est pas un repo Git (pas de sous-dossier .git)."
        )

    mdp = mot_passe or os.environ.get("BOURSE_PASSWORD")
    if not mdp:
        raise ConfigManquante(
            "Variable d'environnement BOURSE_PASSWORD non définie. "
            "Définir un mot de passe ≥ 15 caractères pour chiffrer les données."
        )

    branche = branche or os.environ.get("BOURSE_DASHBOARD_BRANCH") or "main"
    if push is None:
        push = os.environ.get("BOURSE_DASHBOARD_NO_PUSH") != "1"

    # Construire le jeu de fichiers (DATA_DIR configurable : en .exe gelé,
    # RACINE pointe dans le bundle lecture seule → on lit le dossier utilisateur).
    depot = Depot(Path(data_dir) if data_dir else RACINE / "data")
    fichiers = _preparer_fichiers(depot, mdp)  # lève si mdp < 15 caractères

    # Écrire dans le repo local puis commit + push.
    _ecrire_fichiers_disque(repo_path, fichiers)
    message = f"Dashboard : sync {_format_date_fr(datetime.now())}"
    _git_push(repo_path, branche, message, push=push)

    return repo_path / "index.html"


class PublicationAPIErreur(RuntimeError):
    """Échec d'une requête vers l'API GitHub lors de la publication."""


def _message_erreur_api(reponse, contexte: str) -> str:
    """Construit un message d'erreur lisible à partir d'une réponse GitHub."""
    try:
        details = reponse.json().get("message") or reponse.text
    except Exception:  # noqa: BLE001 — corps non-JSON
        details = reponse.text
    indices = {
        401: " (token invalide ou expiré ?)",
        403: " (permissions du token insuffisantes ou quota atteint ?)",
        404: " (dépôt ou utilisateur introuvable ? token sans accès ?)",
        409: " (conflit : réessaie la publication)",
    }.get(reponse.status_code, "")
    return f"{contexte} : HTTP {reponse.status_code} — {details}{indices}"


def _transport_api_github(
    fichiers: dict[str, bytes],
    *,
    owner: str,
    repo: str,
    branche: str,
    token: str,
    message: str,
    session=None,
) -> None:
    """Pousse chaque fichier via l'API HTTP GitHub (Contents API).

    Aucun git ni SSH requis : c'est le transport utilisé par le .exe des amis.
    Pour chaque fichier on récupère d'abord le ``sha`` existant (nécessaire pour
    une mise à jour), puis on ``PUT`` le contenu encodé en base64.
    """
    import base64

    if session is None:
        import requests  # import paresseux : pas requis au démarrage de l'app

        session = requests.Session()

    base = f"https://api.github.com/repos/{owner}/{repo}/contents/"
    entetes = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    contenu_b64 = {c: base64.b64encode(b).decode("ascii") for c, b in fichiers.items()}
    for chemin in fichiers:
        url = base + chemin
        # Jusqu'à 3 tentatives : un 409/422 vient d'un sha périmé (le HEAD de
        # branche a bougé entre le GET et le PUT) — on relit le sha et on réessaie.
        for tentative in range(3):
            reponse = session.get(url, headers=entetes, params={"ref": branche}, timeout=30)
            sha = None
            if reponse.status_code == 200:
                sha = reponse.json().get("sha")
            elif reponse.status_code != 404:
                raise PublicationAPIErreur(_message_erreur_api(reponse, f"lecture {chemin}"))

            corps = {"message": message, "content": contenu_b64[chemin], "branch": branche}
            if sha:
                corps["sha"] = sha
            rep_put = session.put(url, headers=entetes, json=corps, timeout=30)
            if rep_put.status_code in (200, 201):
                break
            if rep_put.status_code in (409, 422) and tentative < 2:
                continue  # sha périmé : on relit et on réessaie
            raise PublicationAPIErreur(_message_erreur_api(rep_put, f"écriture {chemin}"))


def publier_via_api(
    *,
    data_dir: str | Path | None = None,
    mot_passe: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    token: str | None = None,
    branche: str = "main",
    message: str | None = None,
    session=None,
) -> dict:
    """Publication via l'API HTTP GitHub (transport « api », sans git local).

    Destinée au .exe Windows des amis : aucun git ni SSH requis, juste un token
    GitHub. Renvoie un récap ``{fichiers, taille_data, url_pages}``.
    """
    manquants = [
        nom for nom, val in (
            ("propriétaire (owner)", owner),
            ("dépôt (repo)", repo),
            ("token GitHub", token),
            ("mot de passe", mot_passe),
        ) if not val
    ]
    if manquants:
        raise ConfigManquante(
            "Publication mobile impossible — paramètres manquants : "
            + ", ".join(manquants)
            + ". Renseigne-les dans la page Réglages."
        )

    depot = Depot(Path(data_dir) if data_dir else RACINE / "data")
    fichiers = _preparer_fichiers(depot, mot_passe)  # lève si mdp < 15 caractères
    message = message or f"Dashboard : sync {_format_date_fr(datetime.now())}"
    _transport_api_github(
        fichiers, owner=owner, repo=repo, branche=branche,
        token=token, message=message, session=session,
    )
    return {
        "fichiers": sorted(fichiers),
        "taille_data": len(fichiers["data.enc.json"]),
        "url_pages": f"https://{owner}.github.io/{repo}/",
    }


def _humaniser_taille(n: int) -> str:
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko"
    return f"{n / (1024 * 1024):.2f} Mo"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="Chemin du repo Git local (ou env BOURSE_DASHBOARD_REPO)")
    parser.add_argument("--branche", default=None, help="Branche Git (défaut: main)")
    parser.add_argument("--no-push", action="store_true", help="Commit local uniquement")
    args = parser.parse_args()

    try:
        chemin = publier(
            repo=args.repo,
            branche=args.branche,
            push=not args.no_push if args.no_push else None,
        )
        taille_html = chemin.stat().st_size
        taille_data = (chemin.parent / "data.enc.json").stat().st_size
        print(
            f"✓ Publié : {chemin.parent}\n"
            f"  index.html       {_humaniser_taille(taille_html)}\n"
            f"  data.enc.json    {_humaniser_taille(taille_data)}\n"
            f"  Synchro le {_format_date_fr(datetime.now())}"
        )
        return 0
    except ConfigManquante as e:
        print(f"❌ Config : {e}", file=sys.stderr)
        return 2
    except chiffrement.MotPasseInvalide as e:
        print(f"❌ Mot de passe : {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"❌ Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
