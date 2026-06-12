"""Tests export CSV mouvements + récap fiscal."""

from decimal import Decimal

from app.services.csv_export import (
    BOM,
    csv_mouvements,
    csv_recap_fiscal_annee,
)


def test_export_mouvements_bom_et_separateur():
    csv = csv_mouvements([], [], [])
    assert csv.startswith(BOM)
    # L'en-tête contient les colonnes attendues séparées par `;`
    premiere_ligne = csv[len(BOM):].split("\r\n")[0]
    assert "Date" in premiere_ligne
    assert ";" in premiere_ligne


def test_export_mouvements_lignes():
    mouvements = [
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-05-01", "montant": "100"},
        {"id": "m2", "type": "achat", "compte_id": "pea", "titre_id": "stm",
         "date": "2026-05-10", "quantite": "2", "prix_unitaire": "50",
         "frais_courtage": "0.50", "devise": "EUR"},
    ]
    comptes = [{"id": "pea", "nom": "PEA BD", "type": "PEA"}]
    titres = [{"id": "stm", "ticker": "STMPA", "isin": "NL0000226223"}]

    csv = csv_mouvements(mouvements, comptes, titres)
    lignes = csv.split("\r\n")
    # 1 BOM+header + 2 lignes + ligne vide finale
    assert "PEA BD" in csv
    assert "STMPA" in csv
    assert "NL0000226223" in csv
    # Le montant achat doit être négatif (impact cash = -(2*50 + 0.50) = -100.50)
    assert "-100,50" in csv
    # Décimal en virgule française
    assert "0,50" in csv


def test_export_mouvements_dividende_utilise_net_si_present():
    mouvements = [
        {"id": "m1", "type": "dividende_recu", "compte_id": "cto",
         "titre_id": "net", "date": "2026-03-01",
         "montant_brut_total": "10", "montant_net_eur": "7.50"},
    ]
    csv = csv_mouvements(mouvements, [{"id": "cto", "nom": "CTO"}], [{"id": "net", "ticker": "NET"}])
    assert "7,50" in csv


def test_export_recap_structure():
    stats_par_compte = [
        {"compte": {"nom": "PEA BD", "type": "PEA"}, "stats": {
            "montant_alimentations": Decimal("1000"),
            "montant_retraits": Decimal("0"),
            "montant_investi": Decimal("950"),
            "montant_brut_ventes": Decimal("0"),
            "plus_values_realisees": Decimal("0"),
            "dividendes_recus_eur": Decimal("12.50"),
            "frais_courtage_total": Decimal("5"),
        }},
    ]
    cumul = {
        "montant_alimentations": Decimal("1000"),
        "montant_retraits": Decimal("0"),
        "montant_investi": Decimal("950"),
        "montant_brut_ventes": Decimal("0"),
        "plus_values_realisees": Decimal("0"),
        "dividendes_recus_eur": Decimal("12.50"),
        "frais_courtage_total": Decimal("5"),
    }
    csv = csv_recap_fiscal_annee(2026, stats_par_compte, cumul)
    assert csv.startswith(BOM)
    assert "Récapitulatif fiscal 2026" in csv
    assert "PEA BD" in csv
    assert "12,50" in csv
    assert "TOTAL" in csv


def test_export_mouvements_notes_avec_saut_de_ligne_aplatie():
    mouvements = [
        {"id": "m1", "type": "alimentation_cash", "compte_id": "pea",
         "date": "2026-05-01", "montant": "100",
         "notes": "ligne1\nligne2\r\nligne3"},
    ]
    csv = csv_mouvements(mouvements, [{"id": "pea", "nom": "PEA"}], [])
    # Le \n et \r dans notes ne doivent pas casser le CSV ligne par ligne
    assert "ligne1 ligne2  ligne3" in csv or "ligne1 ligne2 ligne3" in csv
