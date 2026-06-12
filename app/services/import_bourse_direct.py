"""Import xlsx Bourse Direct → mise à jour des cours du jour.

L'utilisateur télécharge le xlsx « Mes positions » depuis Bourse Direct (un
titre par ligne, avec ISIN, cours en devise locale, valorisation en EUR), et
l'app extrait `cours_jour`, `cours_jour_eur`, `date_cours_jour` pour chaque
titre du catalogue. Matching par ISIN (clé stable).

Reste 100 % offline : aucune requête réseau, le fichier xlsx est le seul
canal d'information.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import BinaryIO

import openpyxl


# Bourse Direct exporte des xlsx avec un namespace OOXML obsolète
# (`purl.oclc.org/ooxml/...`) qu'openpyxl ne reconnaît pas (il considère
# alors la feuille comme invalide et la retire). On patche en mémoire.
_NS_OBSOLETES = {
    b"http://purl.oclc.org/ooxml/spreadsheetml/main":
        b"http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    b"http://purl.oclc.org/ooxml/officeDocument/relationships":
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    b"http://purl.oclc.org/ooxml/officeDocument/sharedTypes":
        b"http://schemas.openxmlformats.org/officeDocument/2006/sharedTypes",
}


def _patcher_namespaces_xlsx(buf_in: BinaryIO) -> io.BytesIO:
    """Réécrit le xlsx avec les namespaces OOXML standards. No-op si déjà OK."""
    data = buf_in.read()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zin:
            out = io.BytesIO()
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    contenu = zin.read(info.filename)
                    if info.filename.endswith(".xml") or info.filename.endswith(".rels"):
                        for ancien, nouveau in _NS_OBSOLETES.items():
                            contenu = contenu.replace(ancien, nouveau)
                    zout.writestr(info, contenu)
            out.seek(0)
            return out
    except zipfile.BadZipFile as e:
        raise ErreurImport(f"fichier xlsx illisible (zip invalide) : {e}")

from app.services import titres as svc_titres
from app.services.stockage import Depot


# Colonnes attendues dans la 1re ligne du xlsx (ordre Bourse Direct).
# On vérifie la présence d'au moins les colonnes critiques.
COLONNES_REQUISES = ("Nom", "ISIN", "Cours", "Devise", "Quantité", "Valorisation (EUR)")


@dataclass
class LigneImport:
    nom: str
    isin: str
    cours: Decimal              # devise locale
    devise: str                 # "EUR", "USD", etc.
    quantite: Decimal
    valorisation_eur: Decimal
    mic: str | None = None
    marche: str | None = None
    cours_eur: Decimal = Decimal("0")  # dérivé après construction


@dataclass
class ResultatImport:
    mis_a_jour: list[dict] = field(default_factory=list)
    crees: list[dict] = field(default_factory=list)
    ignores: list[dict] = field(default_factory=list)
    non_presents_dans_xlsx: list[str] = field(default_factory=list)


class ErreurImport(Exception):
    pass


# --- Helpers de parsing ------------------------------------------------------


def _to_decimal(v, *, defaut: Decimal | None = None) -> Decimal | None:
    """Convertit un Cell openpyxl (str / int / float) en Decimal. None si vide."""
    if v is None:
        return defaut
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        # Passer par str pour éviter les artefacts float → Decimal
        return Decimal(str(v))
    s = str(v).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not s or s in ("—", "-"):
        return defaut
    try:
        return Decimal(s)
    except InvalidOperation:
        return defaut


def _to_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


# --- Parsing du xlsx ---------------------------------------------------------


def parser_xlsx(fichier: BinaryIO) -> list[LigneImport]:
    """Lit un xlsx Bourse Direct et renvoie les lignes valides.

    Lève `ErreurImport` si les colonnes attendues sont absentes.
    Ignore silencieusement les lignes incomplètes (sans ISIN, sans cours).
    """
    # Bourse Direct utilise un namespace obsolète qui fait disparaître la
    # feuille. On normalise systématiquement en mémoire avant d'ouvrir.
    fichier_norm = _patcher_namespaces_xlsx(fichier)
    try:
        # read_only=False : le xlsx de Bourse Direct déclare `dimension ref="A1"`
        # ce qui fait croire à openpyxl en mode read_only que la feuille est vide.
        wb = openpyxl.load_workbook(fichier_norm, read_only=False, data_only=True)
    except Exception as e:
        raise ErreurImport(f"fichier xlsx illisible : {e}")
    if not wb.worksheets:
        raise ErreurImport("aucune feuille trouvée dans le fichier")
    ws = wb.worksheets[0]

    rows = ws.iter_rows(values_only=True)
    try:
        entete = next(rows)
    except StopIteration:
        raise ErreurImport("fichier vide")
    entete_norm = [_to_str(c) for c in entete]
    index: dict[str, int] = {c: i for i, c in enumerate(entete_norm) if c}
    manquantes = [c for c in COLONNES_REQUISES if c not in index]
    if manquantes:
        raise ErreurImport(
            "colonnes manquantes dans l'en-tête : " + ", ".join(manquantes)
        )

    def cell(row, col_name):
        return row[index[col_name]] if col_name in index else None

    lignes: list[LigneImport] = []
    for row in rows:
        if not row or all(c is None or _to_str(c) == "" for c in row):
            continue
        isin = _to_str(cell(row, "ISIN"))
        if not isin:
            continue
        cours = _to_decimal(cell(row, "Cours"))
        quantite = _to_decimal(cell(row, "Quantité"))
        valorisation = _to_decimal(cell(row, "Valorisation (EUR)"))
        if cours is None or cours <= 0:
            continue
        if quantite is None or quantite <= 0:
            continue
        if valorisation is None or valorisation <= 0:
            continue
        cours_eur = (valorisation / quantite).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        lignes.append(LigneImport(
            nom=_to_str(cell(row, "Nom")),
            isin=isin,
            cours=cours,
            devise=_to_str(cell(row, "Devise")).upper() or "EUR",
            quantite=quantite,
            valorisation_eur=valorisation,
            mic=_to_str(cell(row, "MIC")) or None,
            marche=_to_str(cell(row, "Marché")) or None,
            cours_eur=cours_eur,
        ))
    return lignes


# --- Application au dépôt ---------------------------------------------------


def _nettoyer_nom(nom_brut: str) -> str:
    """« CLOUDFLARE INC(XNYS) » → « CLOUDFLARE INC ». BD suffixe avec le MIC."""
    if "(" in nom_brut:
        return nom_brut.split("(", 1)[0].strip()
    return nom_brut.strip()


def appliquer(
    depot: Depot,
    lignes: list[LigneImport],
    *,
    creer_inconnus: bool = False,
    date_import: str | None = None,
) -> ResultatImport:
    """Met à jour les `cours_jour*` des titres correspondants (ISIN).

    Si `creer_inconnus=True`, les ISIN absents du catalogue donnent lieu à un
    `titres.creer()` avec nom + ISIN + devise + marché + MIC. Idempotent :
    ré-appliquer le même import écrase juste les `cours_jour*` à l'identique.
    """
    date_iso = date_import or _date.today().isoformat()
    resultat = ResultatImport()

    items = depot.charger("titres")
    par_isin: dict[str, dict] = {
        (t.get("isin") or "").upper(): t for t in items if t.get("isin")
    }

    titres_modifies_par_id: dict[str, dict] = {}

    isins_dans_xlsx: set[str] = set()
    for ligne in lignes:
        isin = ligne.isin.upper()
        isins_dans_xlsx.add(isin)
        existant = par_isin.get(isin)

        if existant is None and not creer_inconnus:
            resultat.ignores.append({
                "isin": ligne.isin,
                "nom": ligne.nom,
                "raison": "titre inconnu (cocher « créer les titres absents »)",
            })
            continue

        if existant is None:
            # Création depuis le xlsx
            cree = svc_titres.creer(depot, {
                "ticker": isin[:6],  # ticker provisoire, à éditer ensuite
                "nom": _nettoyer_nom(ligne.nom),
                "isin": isin,
                "devise": ligne.devise,
                "marche": ligne.marche or "",
            })
            # Recharger items pour avoir les nouveaux IDs
            items = depot.charger("titres")
            par_isin = {(t.get("isin") or "").upper(): t for t in items if t.get("isin")}
            existant = par_isin[isin]
            resultat.crees.append({
                "titre_id": cree["id"],
                "ticker": cree["ticker"],
                "nom": cree["nom"],
                "isin": isin,
            })

        # Mise à jour du cours (en place, sans repasser par _normaliser)
        for i, t in enumerate(items):
            if t.get("id") != existant.get("id"):
                continue
            t["cours_jour"] = str(ligne.cours)
            t["cours_jour_eur"] = str(ligne.cours_eur)
            t["date_cours_jour"] = date_iso
            items[i] = t
            titres_modifies_par_id[t["id"]] = t
            resultat.mis_a_jour.append({
                "titre_id": t["id"],
                "ticker": t.get("ticker"),
                "nom": t.get("nom"),
                "cours_jour": str(ligne.cours),
                "devise": ligne.devise,
                "cours_jour_eur": str(ligne.cours_eur),
            })
            break

    # Titres en catalogue absents du xlsx (info, pas un problème)
    for t in items:
        isin = (t.get("isin") or "").upper()
        if isin and isin not in isins_dans_xlsx:
            resultat.non_presents_dans_xlsx.append(t.get("ticker") or t.get("id"))

    depot.enregistrer("titres", items)
    return resultat
