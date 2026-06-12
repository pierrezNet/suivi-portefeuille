"""Service fiscal : récapitulatifs annuels par compte, suivi PEA, formulaire 2074.

Modèle simple : tout est dérivé des mouvements.
Une seule entrée saisie manuellement : les moins-values reportées d'avant
l'historique connu (champ optionnel dans le récap CTO).

Plafonds PEA :
  - Plafond d'apports nets : 150 000 €.
  - Durée de détention : ancienneté en années depuis date_ouverture du compte.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as _date
from decimal import Decimal
from typing import Iterable

from app.services.stockage import Depot


ZERO = Decimal("0.00")
PLAFOND_PEA = Decimal("150000.00")
DUREE_PEA_EXONERATION = 5  # années


def _to_decimal(v, defaut: str = "0") -> Decimal:
    if v in (None, ""):
        return Decimal(defaut)
    return Decimal(str(v))


def _annees_disponibles(mouvements: Iterable[dict]) -> list[int]:
    annees = set()
    for m in mouvements:
        d = m.get("date") or ""
        if len(d) >= 4 and d[:4].isdigit():
            annees.add(int(d[:4]))
    return sorted(annees)


# ---------------------------------------------------------------------------
# Stats par compte / année
# ---------------------------------------------------------------------------


@dataclass
class StatsCompteAnnee:
    compte_id: str
    annee: int
    montant_alimentations: Decimal = ZERO
    montant_retraits: Decimal = ZERO
    montant_investi: Decimal = ZERO  # somme des achats nets de frais
    montant_brut_ventes: Decimal = ZERO
    frais_courtage_total: Decimal = ZERO
    dividendes_recus_eur: Decimal = ZERO
    plus_values_realisees: Decimal = ZERO  # somme algébrique


def stats_compte_annee(
    mouvements: Iterable[dict], compte_id: str, annee: int
) -> StatsCompteAnnee:
    s = StatsCompteAnnee(compte_id=compte_id, annee=annee)
    cle_annee = f"{annee:04d}"
    for m in mouvements:
        if m.get("compte_id") != compte_id:
            continue
        if not (m.get("date") or "").startswith(cle_annee):
            continue
        t = m.get("type")
        frais = _to_decimal(m.get("frais_courtage"))
        if t == "alimentation_cash":
            s.montant_alimentations += _to_decimal(m.get("montant"))
        elif t == "retrait_cash":
            s.montant_retraits += _to_decimal(m.get("montant"))
        elif t == "achat":
            qte = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire"))
            # prix_unitaire est en EUR (facturé par le broker). taux_change
            # est purement informatif et n'est pas appliqué ici.
            s.montant_investi += (qte * prix + frais)
            s.frais_courtage_total += frais
        elif t == "vente":
            qte = _to_decimal(m.get("quantite"))
            prix = _to_decimal(m.get("prix_unitaire_vente"))
            s.montant_brut_ventes += (qte * prix)
            s.frais_courtage_total += frais
            calcul = m.get("calcul_fifo") or {}
            s.plus_values_realisees += _to_decimal(
                calcul.get("plus_value_realisee")
            )
        elif t == "dividende_recu":
            net = m.get("montant_net_eur")
            if net not in (None, ""):
                s.dividendes_recus_eur += _to_decimal(net)
            else:
                s.dividendes_recus_eur += _to_decimal(m.get("montant_brut_total"))
        elif t == "frais":
            s.frais_courtage_total += _to_decimal(m.get("montant"))
    s.montant_alimentations = s.montant_alimentations.quantize(Decimal("0.01"))
    s.montant_retraits = s.montant_retraits.quantize(Decimal("0.01"))
    s.montant_investi = s.montant_investi.quantize(Decimal("0.01"))
    s.montant_brut_ventes = s.montant_brut_ventes.quantize(Decimal("0.01"))
    s.frais_courtage_total = s.frais_courtage_total.quantize(Decimal("0.01"))
    s.dividendes_recus_eur = s.dividendes_recus_eur.quantize(Decimal("0.01"))
    s.plus_values_realisees = s.plus_values_realisees.quantize(Decimal("0.01"))
    return s


# ---------------------------------------------------------------------------
# Détail des ventes pour formulaire 2074 (CTO)
# ---------------------------------------------------------------------------


@dataclass
class LigneVente2074:
    """Une vente, format inspiré du formulaire 2074."""

    date: str
    titre_id: str
    ticker: str
    nom_titre: str
    quantite: Decimal
    prix_revient: Decimal       # ligne « prix d'achat global »
    produit_vente_net: Decimal  # ligne « prix de vente net »
    plus_value: Decimal


def detail_ventes_cto(
    mouvements: Iterable[dict],
    titres_par_id: dict,
    compte_id: str,
    annee: int,
) -> list[LigneVente2074]:
    cle = f"{annee:04d}"
    res: list[LigneVente2074] = []
    for m in mouvements:
        if m.get("type") != "vente":
            continue
        if m.get("compte_id") != compte_id:
            continue
        if not (m.get("date") or "").startswith(cle):
            continue
        calcul = m.get("calcul_fifo") or {}
        tid = m.get("titre_id") or ""
        titre = titres_par_id.get(tid, {})
        res.append(
            LigneVente2074(
                date=m.get("date", ""),
                titre_id=tid,
                ticker=titre.get("ticker") or tid,
                nom_titre=titre.get("nom") or tid,
                quantite=_to_decimal(m.get("quantite")),
                prix_revient=_to_decimal(calcul.get("prix_revient_total")),
                produit_vente_net=_to_decimal(calcul.get("produit_vente_net")),
                plus_value=_to_decimal(calcul.get("plus_value_realisee")),
            )
        )
    res.sort(key=lambda l: l.date)
    return res


# ---------------------------------------------------------------------------
# Moins-values reportables (CTO uniquement)
# ---------------------------------------------------------------------------


@dataclass
class ImputationsMoinsValues:
    """Suivi des moins-values reportables pour une année donnée.

    Algorithme :
      - une moins-value (PV totale annuelle < 0) est utilisable les 10 années
        suivantes ;
      - elle est consommée par les plus-values ultérieures dans l'ordre
        chronologique (plus ancienne d'abord, FIFO).
    """

    pv_brute_annee: Decimal = ZERO
    moins_values_imputees: Decimal = ZERO
    pv_nette_imposable: Decimal = ZERO
    moins_values_a_reporter_total: Decimal = ZERO
    detail_reports: list[dict] = field(default_factory=list)
    # Liste : {"annee_origine": int, "montant_initial": Decimal,
    #          "deja_impute": Decimal, "restant": Decimal,
    #          "expire_apres": int (année)}


def calculer_imputations(
    mouvements: Iterable[dict],
    compte_id: str,
    annee_cible: int,
    *,
    moins_values_anterieures: list[dict] | None = None,
) -> ImputationsMoinsValues:
    """Calcule les imputations pour l'année cible.

    `moins_values_anterieures` permet d'injecter des moins-values d'années
    antérieures à l'historique stocké (saisies manuellement). Format :
      [{"annee": 2023, "montant": Decimal("250.00")}, ...]
    """
    mvts = list(mouvements)
    annees = sorted(_annees_disponibles(mvts))

    # Stock des moins-values disponibles : liste de dicts par année d'origine
    stock: list[dict] = []
    for mv in moins_values_anterieures or []:
        montant = _to_decimal(mv.get("montant"))
        if montant > ZERO:
            stock.append({
                "annee_origine": int(mv["annee"]),
                "montant_initial": montant,
                "deja_impute": ZERO,
                "restant": montant,
                "expire_apres": int(mv["annee"]) + 10,
            })

    pv_par_annee: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for m in mvts:
        if m.get("type") != "vente":
            continue
        if m.get("compte_id") != compte_id:
            continue
        d = m.get("date") or ""
        if len(d) < 4 or not d[:4].isdigit():
            continue
        annee = int(d[:4])
        pv_par_annee[annee] += _to_decimal(
            (m.get("calcul_fifo") or {}).get("plus_value_realisee")
        )

    # Rejouer chaque année dans l'ordre, en imputant ou stockant
    annees_a_traiter = sorted(set(list(pv_par_annee) + [annee_cible]))
    derniere = ImputationsMoinsValues()
    for an in annees_a_traiter:
        # Purger les moins-values expirées
        stock = [r for r in stock if r["expire_apres"] >= an and r["restant"] > 0]

        pv_brute = pv_par_annee.get(an, ZERO).quantize(Decimal("0.01"))
        imputees = ZERO

        if pv_brute > ZERO:
            # Consommer le stock dans l'ordre chronologique
            stock.sort(key=lambda r: r["annee_origine"])
            reste_a_imputer = pv_brute
            for r in stock:
                if reste_a_imputer <= ZERO:
                    break
                consommable = min(r["restant"], reste_a_imputer)
                r["deja_impute"] += consommable
                r["restant"] -= consommable
                imputees += consommable
                reste_a_imputer -= consommable
            stock = [r for r in stock if r["restant"] > 0]
            pv_nette = pv_brute - imputees
            mv_a_reporter_creee = ZERO
        elif pv_brute < ZERO:
            # Créer un nouveau stock
            mv_a_reporter_creee = -pv_brute
            stock.append({
                "annee_origine": an,
                "montant_initial": mv_a_reporter_creee,
                "deja_impute": ZERO,
                "restant": mv_a_reporter_creee,
                "expire_apres": an + 10,
            })
            pv_nette = ZERO
        else:
            mv_a_reporter_creee = ZERO
            pv_nette = ZERO

        if an == annee_cible:
            derniere = ImputationsMoinsValues(
                pv_brute_annee=pv_brute,
                moins_values_imputees=imputees.quantize(Decimal("0.01")),
                pv_nette_imposable=pv_nette.quantize(Decimal("0.01")),
                moins_values_a_reporter_total=sum(
                    (r["restant"] for r in stock), ZERO
                ).quantize(Decimal("0.01")),
                detail_reports=[
                    {
                        "annee_origine": r["annee_origine"],
                        "montant_initial": r["montant_initial"].quantize(Decimal("0.01")),
                        "deja_impute": r["deja_impute"].quantize(Decimal("0.01")),
                        "restant": r["restant"].quantize(Decimal("0.01")),
                        "expire_apres": r["expire_apres"],
                    }
                    for r in stock
                ],
            )
    return derniere


# ---------------------------------------------------------------------------
# Indicateurs PEA (plafond, durée)
# ---------------------------------------------------------------------------


@dataclass
class IndicateursPEA:
    plafond: Decimal = PLAFOND_PEA
    apports_nets_cumules: Decimal = ZERO
    plafond_restant: Decimal = ZERO
    date_ouverture: str | None = None
    annees_de_detention: int = 0
    eligible_exoneration_5_ans: bool = False


def indicateurs_pea(
    mouvements: Iterable[dict], compte: dict, *, aujourd_hui: _date | None = None
) -> IndicateursPEA:
    today = aujourd_hui or _date.today()
    apports = ZERO
    retraits = ZERO
    cid = compte.get("id")
    for m in mouvements:
        if m.get("compte_id") != cid:
            continue
        if m.get("type") == "alimentation_cash":
            apports += _to_decimal(m.get("montant"))
        elif m.get("type") == "retrait_cash":
            retraits += _to_decimal(m.get("montant"))
    apports_nets = (apports - retraits).quantize(Decimal("0.01"))

    date_ouv = compte.get("date_ouverture")
    annees = 0
    if date_ouv:
        try:
            d = _date.fromisoformat(date_ouv)
            annees = (
                today.year - d.year
                - (1 if (today.month, today.day) < (d.month, d.day) else 0)
            )
        except ValueError:
            pass

    return IndicateursPEA(
        plafond=PLAFOND_PEA,
        apports_nets_cumules=apports_nets,
        plafond_restant=(PLAFOND_PEA - apports_nets).quantize(Decimal("0.01")),
        date_ouverture=date_ouv,
        annees_de_detention=annees,
        eligible_exoneration_5_ans=annees >= DUREE_PEA_EXONERATION,
    )


# ---------------------------------------------------------------------------
# Vue d'ensemble : années disponibles et toutes les comptes
# ---------------------------------------------------------------------------


def annees_avec_activite(mouvements: Iterable[dict]) -> list[int]:
    return _annees_disponibles(mouvements)


def stats_globales_annee(
    mouvements: Iterable[dict],
    comptes: list[dict],
    annee: int,
) -> dict:
    """Agrège les stats sur tous les comptes pour une année."""
    cumul = StatsCompteAnnee(compte_id="*", annee=annee)
    par_compte = []
    for c in comptes:
        s = stats_compte_annee(mouvements, c["id"], annee)
        par_compte.append({"compte": c, "stats": s})
        cumul.montant_alimentations += s.montant_alimentations
        cumul.montant_retraits += s.montant_retraits
        cumul.montant_investi += s.montant_investi
        cumul.montant_brut_ventes += s.montant_brut_ventes
        cumul.frais_courtage_total += s.frais_courtage_total
        cumul.dividendes_recus_eur += s.dividendes_recus_eur
        cumul.plus_values_realisees += s.plus_values_realisees
    return {"cumul": cumul, "par_compte": par_compte}
