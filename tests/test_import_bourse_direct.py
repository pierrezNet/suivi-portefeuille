"""Tests import xlsx Bourse Direct."""

import io
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from app.services import import_bourse_direct as svc
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [
        {"id": "net", "ticker": "NET", "nom": "Cloudflare",
         "isin": "US18915M1071", "devise": "USD"},
        {"id": "stm", "ticker": "STMPA", "nom": "STMicroelectronics N.V.",
         "isin": "NL0000226223", "devise": "EUR"},
        # Titre dans le catalogue mais absent du xlsx (cas "non présent")
        {"id": "ifx", "ticker": "IFX", "nom": "Infineon",
         "isin": "DE0006231004", "devise": "EUR"},
    ])
    d.enregistrer("mouvements", [])
    return d


def _xlsx_bourse_direct(lignes: list[list]) -> io.BytesIO:
    """Construit un fichier xlsx au format Bourse Direct."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Nom", "ISIN", "Cours", "Devise", "Variation Veille %",
        "Quantité", "PRU (EUR)", "+/- value (EUR)", "+/- value %",
        "Valorisation (EUR)", "Règlement", "MIC", "Marché",
    ])
    for row in lignes:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# --- Parser -----------------------------------------------------------------


def test_parser_lit_les_lignes_valides():
    buf = _xlsx_bourse_direct([
        ["CLOUDFLARE INC(XNYS)", "US18915M1071", 252.95, "USD", -6.9, 1,
         173.98, 45.17588, 25.97, 219.15588, "cash", "XNYS", "NEW YORK"],
        ["STMicroelectronics N.V.", "NL0000226223", 64.28, "EUR", 2.32, 2,
         34.12, 60.32, 88.39, 128.56, "cash", "XPAR", "EURONEXT PARIS"],
    ])
    lignes = svc.parser_xlsx(buf)
    assert len(lignes) == 2
    assert lignes[0].isin == "US18915M1071"
    assert lignes[0].cours == Decimal("252.95")
    assert lignes[0].devise == "USD"
    assert lignes[0].quantite == Decimal("1")
    assert lignes[0].valorisation_eur == Decimal("219.15588")
    assert lignes[0].mic == "XNYS"


def test_parser_calcule_cours_eur():
    buf = _xlsx_bourse_direct([
        ["CLOUDFLARE", "US18915M1071", 252.95, "USD", 0, 1, 0, 0, 0,
         219.15588, "cash", "XNYS", "NYSE"],
    ])
    lignes = svc.parser_xlsx(buf)
    # 219.15588 / 1 = 219.1559 (arrondi 4 décimales)
    assert lignes[0].cours_eur == Decimal("219.1559")


def test_parser_cours_eur_titre_eur():
    """Pour un titre EUR, cours_eur ≈ cours."""
    buf = _xlsx_bourse_direct([
        ["STM", "NL0000226223", 64.28, "EUR", 0, 2, 0, 0, 0,
         128.56, "cash", "XPAR", "PARIS"],
    ])
    lignes = svc.parser_xlsx(buf)
    assert lignes[0].cours_eur == Decimal("64.2800")


def test_parser_ignore_lignes_sans_isin():
    buf = _xlsx_bourse_direct([
        ["STM", "NL0000226223", 64.28, "EUR", 0, 2, 0, 0, 0,
         128.56, "cash", "XPAR", "PARIS"],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
        ["Sans ISIN", None, 100, "EUR", 0, 1, 0, 0, 0, 100, "cash", None, None],
    ])
    lignes = svc.parser_xlsx(buf)
    assert len(lignes) == 1


def test_parser_ignore_quantite_nulle_ou_cours_negatif():
    buf = _xlsx_bourse_direct([
        ["A", "FR0001", 100, "EUR", 0, 0, 0, 0, 0, 0, "cash", "XPAR", "P"],
        ["B", "FR0002", -10, "EUR", 0, 1, 0, 0, 0, 0, "cash", "XPAR", "P"],
        ["C", "FR0003", 50, "EUR", 0, 1, 0, 0, 0, 50, "cash", "XPAR", "P"],
    ])
    lignes = svc.parser_xlsx(buf)
    assert len(lignes) == 1
    assert lignes[0].isin == "FR0003"


def test_parser_rejette_entete_invalide():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Wrong", "Headers", "Here"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    with pytest.raises(svc.ErreurImport):
        svc.parser_xlsx(buf)


def test_parser_accepte_virgule_decimale():
    """Si une cellule arrive en chaîne « 252,95 » (export selon locale), parser doit gérer."""
    buf = _xlsx_bourse_direct([
        ["CLOUDFLARE", "US18915M1071", "252,95", "USD", 0, 1,
         0, 0, 0, "219,16", "cash", "XNYS", "NYSE"],
    ])
    lignes = svc.parser_xlsx(buf)
    assert lignes[0].cours == Decimal("252.95")
    assert lignes[0].valorisation_eur == Decimal("219.16")


# --- Application ------------------------------------------------------------


def _ligne(isin, cours, devise, quantite, valo, **kw):
    return svc.LigneImport(
        nom=kw.get("nom", "Test"),
        isin=isin, cours=Decimal(str(cours)), devise=devise,
        quantite=Decimal(str(quantite)),
        valorisation_eur=Decimal(str(valo)),
        cours_eur=(Decimal(str(valo)) / Decimal(str(quantite))).quantize(Decimal("0.0001")),
        mic=kw.get("mic"), marche=kw.get("marche"),
    )


def test_appliquer_met_a_jour_par_isin(depot):
    lignes = [
        _ligne("US18915M1071", "252.95", "USD", "1", "219.1559"),
        _ligne("NL0000226223", "64.28", "EUR", "2", "128.56"),
    ]
    res = svc.appliquer(depot, lignes, date_import="2026-06-08")
    assert len(res.mis_a_jour) == 2
    titres = depot.charger("titres")
    net = next(t for t in titres if t["id"] == "net")
    assert net["cours_jour"] == "252.95"
    assert net["cours_jour_eur"] == "219.1559"
    assert net["date_cours_jour"] == "2026-06-08"


def test_appliquer_idempotent(depot):
    lignes = [_ligne("US18915M1071", "252.95", "USD", "1", "219.1559")]
    svc.appliquer(depot, lignes, date_import="2026-06-08")
    snap1 = depot.charger("titres")
    svc.appliquer(depot, lignes, date_import="2026-06-08")
    snap2 = depot.charger("titres")
    assert snap1 == snap2


def test_appliquer_titre_inconnu_ignore_si_pas_creer(depot):
    lignes = [_ligne("US5949181045", "415.00", "USD", "1", "359.60",
                     nom="Microsoft Corp")]
    res = svc.appliquer(depot, lignes, creer_inconnus=False)
    assert res.mis_a_jour == []
    assert res.crees == []
    assert len(res.ignores) == 1
    assert res.ignores[0]["isin"] == "US5949181045"


def test_appliquer_cree_titre_si_demande(depot):
    lignes = [_ligne("US5949181045", "415.00", "USD", "1", "359.60",
                     nom="Microsoft Corp", mic="XNGS", marche="NASDAQ")]
    res = svc.appliquer(depot, lignes, creer_inconnus=True,
                        date_import="2026-06-08")
    assert len(res.crees) == 1
    assert len(res.mis_a_jour) == 1

    titres = depot.charger("titres")
    msft = next(t for t in titres if t.get("isin") == "US5949181045")
    assert msft["nom"] == "Microsoft Corp"
    assert msft["devise"] == "USD"
    assert msft["marche"] == "NASDAQ"
    assert msft["cours_jour"] == "415.00"


def test_non_presents_dans_xlsx(depot):
    """Si un titre du catalogue n'est pas dans le xlsx, il est listé."""
    lignes = [_ligne("US18915M1071", "252.95", "USD", "1", "219.1559")]
    res = svc.appliquer(depot, lignes)
    # IFX et STM sont en catalogue, pas dans le xlsx
    assert "IFX" in res.non_presents_dans_xlsx
    assert "STMPA" in res.non_presents_dans_xlsx


def test_appliquer_nettoie_le_nom_a_la_creation(depot):
    """« CLOUDFLARE INC(XNYS) » → « CLOUDFLARE INC »."""
    lignes = [_ligne("US18915M1072", "100", "USD", "1", "86",
                     nom="CLOUDFLARE INC(XNYS)")]
    svc.appliquer(depot, lignes, creer_inconnus=True)
    titres = depot.charger("titres")
    t = next(t for t in titres if t.get("isin") == "US18915M1072")
    assert t["nom"] == "CLOUDFLARE INC"


def test_appliquer_preserve_les_autres_champs_du_titre(depot):
    """L'import ne doit pas écraser these_lt, secteur, etc."""
    items = depot.charger("titres")
    for t in items:
        if t["id"] == "net":
            t["these_lt"] = "Long edge sur le réseau."
            t["secteur"] = "Internet infra"
    depot.enregistrer("titres", items)

    lignes = [_ligne("US18915M1071", "300", "USD", "1", "260")]
    svc.appliquer(depot, lignes)

    net = next(t for t in depot.charger("titres") if t["id"] == "net")
    assert net["these_lt"] == "Long edge sur le réseau."
    assert net["secteur"] == "Internet infra"
    assert net["cours_jour"] == "300"
