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


def _publier_fichiers(repo: Path, data_chiffre: dict, html: str) -> None:
    """Écrit data.enc.json + index.html + assets PWA dans le repo."""
    (repo / "data.enc.json").write_text(
        json.dumps(data_chiffre, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "index.html").write_text(html, encoding="utf-8")
    # Un .nojekyll évite le pipeline Jekyll de GitHub Pages
    (repo / ".nojekyll").write_text("", encoding="utf-8")

    # --- Assets PWA (manifest, icônes, service worker) ---
    import shutil
    for nom in ("manifest.json", "icon.svg", "icon-192.png", "icon-512.png",
                "apple-touch-icon-180.png"):
        shutil.copyfile(TEMPLATES / nom, repo / nom)

    # Service worker : on injecte un BUILD_ID unique pour versionner le cache
    # (date+heure de publication). À chaque sync, l'ancien cache est purgé.
    build_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    sw_contenu = (TEMPLATES / "sw.js").read_text(encoding="utf-8")
    sw_contenu = sw_contenu.replace("__BUILD_ID__", build_id)
    (repo / "sw.js").write_text(sw_contenu, encoding="utf-8")


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

    # 1. Construire les données. DATA_DIR configurable : en .exe gelé, RACINE
    #    pointe dans le bundle (lecture seule) → on lit le dossier utilisateur.
    depot = Depot(Path(data_dir) if data_dir else RACINE / "data")
    data = dashboard_data.construire(depot, rattraper_virements=True)
    data = _enrichir_pour_export(data)

    # 2. Chiffrer (lèvera MotPasseInvalide si < 15 caractères)
    payload_clair = json.loads(
        json.dumps(data, cls=_EncodeurDashboard, ensure_ascii=False)
    )
    paquet = chiffrement.chiffrer(payload_clair, mdp)

    # 3. Construire le HTML statique (CSS + JS inlinés, AUCUNE donnée inline)
    css_inline = (TEMPLATES / "dashboard_mobile.css").read_text(encoding="utf-8")
    js_inline = (TEMPLATES / "cloud_app.js").read_text(encoding="utf-8")
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("cloud_index.html.j2")
    html = template.render(
        css_inline=css_inline,
        js_inline=js_inline,
    )

    # 4. Écrire dans le repo
    _publier_fichiers(repo_path, paquet.to_dict(), html)

    # 5. Commit + push
    message = f"Dashboard : sync {_format_date_fr(datetime.now())}"
    _git_push(repo_path, branche, message, push=push)

    return repo_path / "index.html"


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
