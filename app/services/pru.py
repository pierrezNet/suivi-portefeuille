"""Calcul FIFO : reconstitution des lots disponibles + consommation pour une vente.

Principes :
  - Chaque achat crée un *lot* identifié par l'id du mouvement d'achat.
  - Une vente *consomme* les lots dans l'ordre chronologique (date, puis id),
    en partant du plus ancien.
  - Les frais d'achat sont alloués proportionnellement à la quantité consommée
    (frais_alloues = frais_courtage * quantite_consommee / quantite_lot_initiale).
  - Le détail FIFO d'une vente (champ `calcul_fifo`) est *immuable* :
    quand on rejoue l'historique, on respecte ce qu'a déjà consommé chaque
    vente passée, même si ses lots d'origine ont été corrigés depuis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable


ZERO = Decimal("0")
CENT = Decimal("0.01")


def _to_decimal(valeur, defaut: str = "0") -> Decimal:
    if valeur in (None, ""):
        return Decimal(defaut)
    return Decimal(str(valeur))


@dataclass
class Lot:
    """Un lot d'achat avec ses quantités et frais résiduels."""

    achat_id: str
    date: str
    prix_unitaire: Decimal
    quantite_initiale: Decimal
    quantite_restante: Decimal
    frais_initiaux: Decimal
    frais_restants: Decimal


@dataclass
class LotConsomme:
    """Une portion d'un lot consommée par une vente."""

    achat_id: str
    quantite: Decimal
    prix_unitaire_achat: Decimal
    frais_alloues: Decimal


@dataclass
class ResultatFifo:
    """Sortie du calcul FIFO pour une vente projetée."""

    lots_consommes: list[LotConsomme] = field(default_factory=list)
    prix_revient_total: Decimal = ZERO
    quantite_manquante: Decimal = ZERO  # > 0 si pas assez de lots disponibles


def _filtrer_et_trier(
    mouvements: Iterable[dict], compte_id: str, titre_id: str
) -> list[dict]:
    """Renvoie les mouvements d'un (compte, titre) triés par (date, id)."""
    lignes = [
        m
        for m in mouvements
        if m.get("compte_id") == compte_id
        and m.get("titre_id") == titre_id
        and m.get("type") in ("achat", "vente")
    ]
    return sorted(lignes, key=lambda m: (m.get("date", ""), m.get("id", "")))


def reconstituer_lots(
    mouvements: Iterable[dict],
    compte_id: str,
    titre_id: str,
    *,
    exclure_id: str | None = None,
) -> list[Lot]:
    """Rejoue les achats/ventes pour produire la liste des lots actuellement disponibles.

    `exclure_id` permet d'ignorer un mouvement (utile lors de l'édition d'une vente
    ou d'un achat : on évite de prendre en compte la version pré-modification).
    """
    lots: dict[str, Lot] = {}
    for m in _filtrer_et_trier(mouvements, compte_id, titre_id):
        if exclure_id and m.get("id") == exclure_id:
            continue
        if m["type"] == "achat":
            qte = _to_decimal(m.get("quantite"))
            frais = _to_decimal(m.get("frais_courtage"))
            lots[m["id"]] = Lot(
                achat_id=m["id"],
                date=m.get("date", ""),
                prix_unitaire=_to_decimal(m.get("prix_unitaire")),
                quantite_initiale=qte,
                quantite_restante=qte,
                frais_initiaux=frais,
                frais_restants=frais,
            )
        else:  # vente
            calcul = m.get("calcul_fifo") or {}
            for lc in calcul.get("lots_consommes", []):
                achat_id = lc.get("achat_id")
                lot = lots.get(achat_id)
                if lot is None:
                    # Lot d'origine introuvable (achat supprimé après vente ?) :
                    # on ignore proprement plutôt que crasher.
                    continue
                lot.quantite_restante -= _to_decimal(lc.get("quantite"))
                lot.frais_restants -= _to_decimal(lc.get("frais_alloues"))
                if lot.quantite_restante <= ZERO:
                    lots.pop(achat_id, None)
    # Lots restants triés chronologiquement
    return sorted(lots.values(), key=lambda l: (l.date, l.achat_id))


def quantite_disponible(
    mouvements: Iterable[dict],
    compte_id: str,
    titre_id: str,
    *,
    exclure_id: str | None = None,
) -> Decimal:
    return sum(
        (l.quantite_restante for l in reconstituer_lots(
            mouvements, compte_id, titre_id, exclure_id=exclure_id
        )),
        ZERO,
    )


def calculer_fifo_vente(
    mouvements: Iterable[dict],
    compte_id: str,
    titre_id: str,
    quantite_a_vendre: Decimal | str | int,
    *,
    exclure_id: str | None = None,
) -> ResultatFifo:
    """Consomme les lots disponibles dans l'ordre FIFO pour la quantité demandée."""
    qte_restante = _to_decimal(quantite_a_vendre)
    if qte_restante <= ZERO:
        return ResultatFifo()

    lots = reconstituer_lots(
        mouvements, compte_id, titre_id, exclure_id=exclure_id
    )
    consommes: list[LotConsomme] = []
    prix_revient_total = ZERO

    for lot in lots:
        if qte_restante <= ZERO:
            break
        a_prendre = min(lot.quantite_restante, qte_restante)
        # Frais alloués proportionnels à la quantité prise sur les frais initiaux
        if lot.quantite_initiale > ZERO:
            frais_alloues = (
                lot.frais_initiaux * a_prendre / lot.quantite_initiale
            ).quantize(CENT)
        else:
            frais_alloues = ZERO
        cout_lot = (lot.prix_unitaire * a_prendre + frais_alloues).quantize(CENT)
        consommes.append(
            LotConsomme(
                achat_id=lot.achat_id,
                quantite=a_prendre,
                prix_unitaire_achat=lot.prix_unitaire,
                frais_alloues=frais_alloues,
            )
        )
        prix_revient_total += cout_lot
        qte_restante -= a_prendre

    return ResultatFifo(
        lots_consommes=consommes,
        prix_revient_total=prix_revient_total.quantize(CENT),
        quantite_manquante=qte_restante if qte_restante > ZERO else ZERO,
    )


def calculer_pru(
    mouvements: Iterable[dict],
    compte_id: str,
    titre_id: str,
) -> Decimal | None:
    """PRU courant = (somme prix_revient lots restants) / quantité restante.

    Renvoie None si plus aucune position.
    """
    lots = reconstituer_lots(mouvements, compte_id, titre_id)
    qte = sum((l.quantite_restante for l in lots), ZERO)
    if qte <= ZERO:
        return None
    cout = sum(
        (l.prix_unitaire * l.quantite_restante + l.frais_restants for l in lots),
        ZERO,
    )
    return (cout / qte).quantize(CENT)
