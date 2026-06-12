"""Calcul de la plus-value réalisée à la vente."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Iterable

from app.services.pru import (
    CENT,
    ZERO,
    ResultatFifo,
    _to_decimal,
    calculer_fifo_vente,
)


def preparer_calcul_fifo(
    mouvements: Iterable[dict],
    compte_id: str,
    titre_id: str,
    quantite: Decimal | str | int,
    prix_unitaire_vente: Decimal | str,
    frais_courtage: Decimal | str = "0",
    *,
    exclure_id: str | None = None,
) -> dict:
    """Calcule le bloc `calcul_fifo` à stocker sur un mouvement de vente.

    Renvoie le dict prêt à sérialiser, ou lève ValueError si la quantité disponible
    est insuffisante.
    """
    qte = _to_decimal(quantite)
    prix_vente = _to_decimal(prix_unitaire_vente)
    frais = _to_decimal(frais_courtage)

    fifo: ResultatFifo = calculer_fifo_vente(
        mouvements, compte_id, titre_id, qte, exclure_id=exclure_id
    )
    if fifo.quantite_manquante > ZERO:
        raise ValueError(
            f"Quantité insuffisante en portefeuille : il manque "
            f"{fifo.quantite_manquante} titre(s) pour cette vente."
        )

    produit_brut = (qte * prix_vente).quantize(CENT)
    produit_net = (produit_brut - frais).quantize(CENT)
    plus_value = (produit_net - fifo.prix_revient_total).quantize(CENT)

    return {
        "lots_consommes": [
            {
                "achat_id": lc.achat_id,
                "quantite": str(lc.quantite),
                "prix_unitaire_achat": str(lc.prix_unitaire_achat),
                "frais_alloues": str(lc.frais_alloues),
            }
            for lc in fifo.lots_consommes
        ],
        "prix_revient_total": str(fifo.prix_revient_total),
        "produit_vente_brut": str(produit_brut),
        "produit_vente_net": str(produit_net),
        "plus_value_realisee": str(plus_value),
    }


def cumul_plus_values(
    mouvements: Iterable[dict],
    *,
    titre_id: str | None = None,
    compte_id: str | None = None,
    annee: int | None = None,
) -> Decimal:
    """Somme des plus-values réalisées (peut être négative).

    Filtres optionnels par titre, compte, année.
    """
    total = ZERO
    for m in mouvements:
        if m.get("type") != "vente":
            continue
        if titre_id and m.get("titre_id") != titre_id:
            continue
        if compte_id and m.get("compte_id") != compte_id:
            continue
        if annee:
            date = m.get("date") or ""
            if not date.startswith(str(annee)):
                continue
        calc = m.get("calcul_fifo") or {}
        total += _to_decimal(calc.get("plus_value_realisee"))
    return total.quantize(CENT)
