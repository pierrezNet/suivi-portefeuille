"""Tests du calcul FIFO et reconstitution des lots."""

from decimal import Decimal

from app.services.pru import (
    calculer_fifo_vente,
    calculer_pru,
    quantite_disponible,
    reconstituer_lots,
)


def _achat(id_, date, quantite, prix, frais="0"):
    return {
        "id": id_,
        "type": "achat",
        "compte_id": "c1",
        "titre_id": "t1",
        "date": date,
        "quantite": quantite,
        "prix_unitaire": prix,
        "frais_courtage": frais,
    }


def _vente(id_, date, quantite, prix, frais, calcul_fifo):
    return {
        "id": id_,
        "type": "vente",
        "compte_id": "c1",
        "titre_id": "t1",
        "date": date,
        "quantite": quantite,
        "prix_unitaire_vente": prix,
        "frais_courtage": frais,
        "calcul_fifo": calcul_fifo,
    }


def test_fifo_vente_simple_lot_unique():
    """Vente totale d'un lot unique : prix de revient = prix × qté + frais."""
    mvts = [_achat("a1", "2025-08-12", 2, "34.12", "1.99")]
    res = calculer_fifo_vente(mvts, "c1", "t1", 2)
    assert res.prix_revient_total == Decimal("70.23")
    assert res.quantite_manquante == 0
    assert len(res.lots_consommes) == 1
    lc = res.lots_consommes[0]
    assert lc.achat_id == "a1"
    assert lc.quantite == Decimal("2")
    assert lc.frais_alloues == Decimal("1.99")


def test_fifo_vente_partielle_un_lot():
    """Vente d'1/2 d'un lot : moitié des frais alloués."""
    mvts = [_achat("a1", "2025-08-12", 2, "34.12", "1.99")]
    res = calculer_fifo_vente(mvts, "c1", "t1", 1)
    # 34.12 + 0.995 (arrondi à 1.00 ROUND_HALF_EVEN ? on utilise quantize default = HALF_EVEN)
    # Decimal('1.99') / 2 = 0.995 → quantize(0.01) = 1.00 (banker's rounding)
    assert res.lots_consommes[0].frais_alloues == Decimal("1.00")
    assert res.prix_revient_total == Decimal("35.12")


def test_fifo_vente_chevauchant_deux_lots():
    """Exemple du README étendu : on consomme A en entier puis on entame B."""
    mvts = [
        _achat("a1", "2025-08-12", 2, "34.12", "1.99"),
        _achat("a2", "2026-02-18", 1, "28.50", "1.50"),
    ]
    res = calculer_fifo_vente(mvts, "c1", "t1", 3)
    assert len(res.lots_consommes) == 2
    # Lot A en entier : 2 × 34.12 + 1.99 = 70.23
    # Lot B en entier : 1 × 28.50 + 1.50 = 30.00
    assert res.prix_revient_total == Decimal("100.23")
    assert res.quantite_manquante == 0


def test_fifo_lot_intact_apres_vente_partielle():
    """Après vente partielle, le lot doit conserver le reliquat (qté + frais)."""
    achats = [_achat("a1", "2025-08-12", 4, "10.00", "2.00")]
    res = calculer_fifo_vente(achats, "c1", "t1", 1)
    # Construire le mouvement de vente correspondant
    vente = _vente(
        "v1", "2026-01-15", 1, "20.00", "0",
        {
            "lots_consommes": [
                {
                    "achat_id": lc.achat_id,
                    "quantite": str(lc.quantite),
                    "prix_unitaire_achat": str(lc.prix_unitaire_achat),
                    "frais_alloues": str(lc.frais_alloues),
                }
                for lc in res.lots_consommes
            ],
        },
    )
    lots = reconstituer_lots([*achats, vente], "c1", "t1")
    assert len(lots) == 1
    lot = lots[0]
    assert lot.quantite_restante == Decimal("3")
    # Frais initiaux 2.00 - frais_alloues = 2.00 - 0.50 = 1.50
    assert lot.frais_restants == Decimal("1.50")


def test_fifo_quantite_insuffisante():
    mvts = [_achat("a1", "2025-08-12", 2, "10.00", "0")]
    res = calculer_fifo_vente(mvts, "c1", "t1", 5)
    assert res.quantite_manquante == Decimal("3")


def test_quantite_disponible():
    mvts = [
        _achat("a1", "2025-08-12", 2, "34.12", "1.99"),
        _achat("a2", "2026-02-18", 1, "28.50", "1.50"),
    ]
    assert quantite_disponible(mvts, "c1", "t1") == Decimal("3")


def test_pru_courant():
    """PRU = (somme cout lots restants) / qte restante."""
    mvts = [
        _achat("a1", "2025-08-12", 2, "10.00", "2.00"),  # cout 22, qte 2 → PRU 11
        _achat("a2", "2026-02-18", 2, "20.00", "2.00"),  # cout 42, qte 2 → PRU 21
    ]
    # PRU global = (22 + 42) / 4 = 16
    assert calculer_pru(mvts, "c1", "t1") == Decimal("16.00")


def test_pru_aucune_position():
    assert calculer_pru([], "c1", "t1") is None


def test_fifo_exclure_id_pour_edition_vente():
    """Lors de l'édition d'une vente, on doit pouvoir l'exclure du calcul."""
    achats = [_achat("a1", "2025-08-12", 2, "10.00", "0")]
    vente_existante = _vente(
        "v1", "2026-01-15", 2, "15.00", "0",
        {
            "lots_consommes": [
                {"achat_id": "a1", "quantite": "2",
                 "prix_unitaire_achat": "10.00", "frais_alloues": "0"}
            ]
        },
    )
    # Sans exclusion : 0 dispo
    assert quantite_disponible([*achats, vente_existante], "c1", "t1") == Decimal("0")
    # Avec exclusion : 2 dispo (l'achat redevient consommable)
    assert quantite_disponible(
        [*achats, vente_existante], "c1", "t1", exclure_id="v1"
    ) == Decimal("2")
