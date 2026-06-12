"""Reconstitution des soldes cash et des positions à partir des mouvements."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Iterable


ZERO = Decimal("0.00")


def _to_decimal(valeur) -> Decimal:
    if valeur in (None, ""):
        return ZERO
    return Decimal(str(valeur))


def calculer_solde_cash(mouvements: Iterable[dict], compte_id: str) -> Decimal:
    """Recalcule dynamiquement le solde cash d'un compte.

    Conventions :
      - alimentation_cash : crédit
      - retrait_cash      : débit
      - achat             : débit (quantité × prix_unitaire + frais)
      - vente             : crédit (quantité × prix_unitaire_vente − frais)
      - dividende_recu    : crédit (montant net en EUR si fourni, sinon brut)
      - frais             : débit

    Le `prix_unitaire` est toujours interprété comme le prix EUR effectivement
    facturé par le broker. Le champ `taux_change` est purement informatif
    (traçabilité fiscale) et n'intervient PAS dans le calcul du solde cash.
    """
    solde = ZERO
    for m in mouvements:
        if m.get("compte_id") != compte_id:
            continue
        t = m.get("type")
        if t == "alimentation_cash":
            solde += _to_decimal(m.get("montant"))
        elif t == "retrait_cash":
            solde -= _to_decimal(m.get("montant"))
        elif t == "achat":
            quantite = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire"))
            frais = _to_decimal(m.get("frais_courtage"))
            solde -= (quantite * prix + frais)
        elif t == "vente":
            quantite = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire_vente"))
            frais = _to_decimal(m.get("frais_courtage"))
            solde += (quantite * prix - frais)
        elif t == "dividende_recu":
            net = m.get("montant_net_eur")
            if net not in (None, ""):
                solde += _to_decimal(net)
            else:
                solde += _to_decimal(m.get("montant_brut_total"))
        elif t == "frais":
            solde -= _to_decimal(m.get("montant"))
    return solde.quantize(Decimal("0.01"))


def calculer_positions(mouvements: Iterable[dict], compte_id: str) -> dict[str, Decimal]:
    """Renvoie {titre_id: quantité courante} pour un compte.

    Approche simple FIFO globale : achat = +, vente = -. Aucun calcul de PRU ici.
    """
    positions: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for m in mouvements:
        if m.get("compte_id") != compte_id:
            continue
        t = m.get("type")
        titre_id = m.get("titre_id")
        if not titre_id:
            continue
        quantite = _to_decimal(m.get("quantite"))
        if t == "achat":
            positions[titre_id] += quantite
        elif t == "vente":
            positions[titre_id] -= quantite
    # Filtre les positions nulles
    return {tid: q for tid, q in positions.items() if q != ZERO}
