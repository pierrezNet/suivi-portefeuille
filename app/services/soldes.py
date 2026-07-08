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


def calculer_ventilation_cash(
    mouvements: Iterable[dict], compte_id: str
) -> dict[str, Decimal]:
    """Ventile le cash d'un compte par composante et renvoie le solde net.

    Renvoie ``{versements, ventes, dividendes, achats, frais, retraits, solde}``
    (Decimals, arrondis à 0,01). Conventions identiques au solde :
      - versements  : Σ alimentation_cash
      - retraits    : Σ retrait_cash
      - achats      : Σ (quantité × prix_unitaire + frais)
      - ventes      : Σ (quantité × prix_unitaire_vente − frais)  [net encaissé]
      - dividendes  : Σ (montant net en EUR si fourni, sinon brut)
      - frais       : Σ frais (mouvements de type `frais` autonomes)
      - solde       : versements + ventes + dividendes − achats − frais − retraits

    Le `prix_unitaire` est le prix EUR effectivement facturé ; `taux_change`
    est purement informatif et n'intervient PAS dans le calcul.
    """
    v = {
        "versements": ZERO,
        "ventes": ZERO,
        "dividendes": ZERO,
        "achats": ZERO,
        "frais": ZERO,
        "retraits": ZERO,
    }
    for m in mouvements:
        if m.get("compte_id") != compte_id:
            continue
        t = m.get("type")
        if t == "alimentation_cash":
            v["versements"] += _to_decimal(m.get("montant"))
        elif t == "retrait_cash":
            v["retraits"] += _to_decimal(m.get("montant"))
        elif t == "achat":
            quantite = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire"))
            frais = _to_decimal(m.get("frais_courtage"))
            v["achats"] += (quantite * prix + frais)
        elif t == "vente":
            quantite = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire_vente"))
            frais = _to_decimal(m.get("frais_courtage"))
            v["ventes"] += (quantite * prix - frais)
        elif t == "dividende_recu":
            net = m.get("montant_net_eur")
            if net not in (None, ""):
                v["dividendes"] += _to_decimal(net)
            else:
                v["dividendes"] += _to_decimal(m.get("montant_brut_total"))
        elif t == "frais":
            v["frais"] += _to_decimal(m.get("montant"))
    solde = (
        v["versements"] + v["ventes"] + v["dividendes"]
        - v["achats"] - v["frais"] - v["retraits"]
    )
    resultat = {k: val.quantize(Decimal("0.01")) for k, val in v.items()}
    resultat["solde"] = solde.quantize(Decimal("0.01"))
    return resultat


def calculer_solde_cash(mouvements: Iterable[dict], compte_id: str) -> Decimal:
    """Recalcule dynamiquement le solde cash d'un compte.

    Conventions détaillées dans :func:`calculer_ventilation_cash`, dont cette
    fonction renvoie simplement la composante ``solde``.
    """
    return calculer_ventilation_cash(mouvements, compte_id)["solde"]


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
