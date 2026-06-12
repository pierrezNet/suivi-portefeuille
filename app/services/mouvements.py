"""Service CRUD des mouvements : validation, calcul FIFO, persistance."""

from __future__ import annotations

import re
import uuid
from datetime import date as _date
from decimal import Decimal, InvalidOperation

from app.services.plus_values import preparer_calcul_fifo
from app.services.pru import quantite_disponible
from app.services.stockage import Depot


TYPES_MOUVEMENT = (
    "alimentation_cash",
    "retrait_cash",
    "achat",
    "vente",
    "dividende_recu",
    "frais",
)

LIBELLES_TYPES = {
    "alimentation_cash": "Alimentation cash",
    "retrait_cash": "Retrait cash",
    "achat": "Achat de titre",
    "vente": "Vente de titre",
    "dividende_recu": "Dividende reçu",
    "frais": "Frais divers",
}

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErreursValidation(Exception):
    """Levée quand des erreurs de validation empêchent l'enregistrement."""

    def __init__(self, erreurs: dict[str, str]):
        self.erreurs = erreurs
        super().__init__("; ".join(f"{k}: {v}" for k, v in erreurs.items()))


# --- Helpers de parsing/validation ----------------------------------------


def _str_propre(valeur) -> str:
    return str(valeur).strip() if valeur is not None else ""


def _parse_decimal_positif(valeur, *, autoriser_zero: bool = True) -> Decimal:
    s = _str_propre(valeur).replace(",", ".")
    if not s:
        raise ValueError("valeur requise")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError("nombre invalide")
    if d < 0:
        raise ValueError("doit être positif")
    if not autoriser_zero and d == 0:
        raise ValueError("doit être strictement positif")
    return d


def _parse_decimal(valeur) -> Decimal:
    s = _str_propre(valeur).replace(",", ".")
    if not s:
        raise ValueError("valeur requise")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError("nombre invalide")


def _valider_date(valeur) -> str:
    s = _str_propre(valeur)
    if not s or not ISO_DATE.match(s):
        raise ValueError("format attendu YYYY-MM-DD")
    try:
        _date.fromisoformat(s)
    except ValueError:
        raise ValueError("date invalide")
    return s


def _valider_compte(depot: Depot, compte_id: str) -> str:
    s = _str_propre(compte_id)
    if not s:
        raise ValueError("compte requis")
    ids = {c["id"] for c in depot.charger("comptes")}
    if s not in ids:
        raise ValueError("compte inconnu")
    return s


def _valider_titre(depot: Depot, titre_id: str) -> str:
    s = _str_propre(titre_id)
    if not s:
        raise ValueError("titre requis")
    ids = {t["id"] for t in depot.charger("titres")}
    if s not in ids:
        raise ValueError("titre inconnu")
    return s


# --- Normalisation par type -----------------------------------------------


def _normaliser_alim_ou_retrait(
    depot: Depot, donnees: dict, type_: str
) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {"type": type_}
    try:
        out["compte_id"] = _valider_compte(depot, donnees.get("compte_id"))
    except ValueError as e:
        erreurs["compte_id"] = str(e)
    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)
    try:
        out["montant"] = str(
            _parse_decimal_positif(donnees.get("montant"), autoriser_zero=False)
        )
    except ValueError as e:
        erreurs["montant"] = str(e)
    out["devise"] = _str_propre(donnees.get("devise") or "EUR").upper() or "EUR"
    out["libelle"] = _str_propre(donnees.get("libelle"))
    out["notes"] = _str_propre(donnees.get("notes"))
    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def _normaliser_achat(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {"type": "achat"}
    try:
        out["compte_id"] = _valider_compte(depot, donnees.get("compte_id"))
    except ValueError as e:
        erreurs["compte_id"] = str(e)
    try:
        out["titre_id"] = _valider_titre(depot, donnees.get("titre_id"))
    except ValueError as e:
        erreurs["titre_id"] = str(e)
    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)
    try:
        qte = _parse_decimal_positif(
            donnees.get("quantite"), autoriser_zero=False
        )
        # quantité stockée comme nombre (entier ou décimal pour fractions ETF)
        out["quantite"] = int(qte) if qte == qte.to_integral_value() else str(qte)
    except ValueError as e:
        erreurs["quantite"] = str(e)
    try:
        out["prix_unitaire"] = str(
            _parse_decimal_positif(donnees.get("prix_unitaire"))
        )
    except ValueError as e:
        erreurs["prix_unitaire"] = str(e)
    try:
        out["frais_courtage"] = str(
            _parse_decimal_positif(donnees.get("frais_courtage") or "0")
        )
    except ValueError as e:
        erreurs["frais_courtage"] = str(e)
    try:
        out["taux_change"] = str(
            _parse_decimal_positif(
                donnees.get("taux_change") or "1", autoriser_zero=False
            )
        )
    except ValueError as e:
        erreurs["taux_change"] = str(e)
    out["devise"] = _str_propre(donnees.get("devise") or "EUR").upper() or "EUR"
    out["notes"] = _str_propre(donnees.get("notes"))
    if erreurs:
        raise ErreursValidation(erreurs)
    return out


def _normaliser_vente(
    depot: Depot, donnees: dict, *, exclure_id: str | None = None
) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {"type": "vente"}
    try:
        out["compte_id"] = _valider_compte(depot, donnees.get("compte_id"))
    except ValueError as e:
        erreurs["compte_id"] = str(e)
    try:
        out["titre_id"] = _valider_titre(depot, donnees.get("titre_id"))
    except ValueError as e:
        erreurs["titre_id"] = str(e)
    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)
    try:
        qte = _parse_decimal_positif(
            donnees.get("quantite"), autoriser_zero=False
        )
        out["quantite"] = int(qte) if qte == qte.to_integral_value() else str(qte)
    except ValueError as e:
        erreurs["quantite"] = str(e)
    try:
        out["prix_unitaire_vente"] = str(
            _parse_decimal_positif(donnees.get("prix_unitaire_vente"))
        )
    except ValueError as e:
        erreurs["prix_unitaire_vente"] = str(e)
    try:
        out["frais_courtage"] = str(
            _parse_decimal_positif(donnees.get("frais_courtage") or "0")
        )
    except ValueError as e:
        erreurs["frais_courtage"] = str(e)
    try:
        out["taux_change"] = str(
            _parse_decimal_positif(
                donnees.get("taux_change") or "1", autoriser_zero=False
            )
        )
    except ValueError as e:
        erreurs["taux_change"] = str(e)
    out["devise"] = _str_propre(donnees.get("devise") or "EUR").upper() or "EUR"
    out["notes"] = _str_propre(donnees.get("notes"))

    if erreurs:
        raise ErreursValidation(erreurs)

    # FIFO + plus-value (peut lever ValueError si quantité insuffisante)
    mouvements = depot.charger("mouvements")
    try:
        out["calcul_fifo"] = preparer_calcul_fifo(
            mouvements,
            compte_id=out["compte_id"],
            titre_id=out["titre_id"],
            quantite=out["quantite"],
            prix_unitaire_vente=out["prix_unitaire_vente"],
            frais_courtage=out["frais_courtage"],
            exclure_id=exclure_id,
        )
    except ValueError as e:
        raise ErreursValidation({"quantite": str(e)})

    return out


def _normaliser_dividende(depot: Depot, donnees: dict) -> dict:
    erreurs: dict[str, str] = {}
    out: dict = {"type": "dividende_recu"}
    try:
        out["compte_id"] = _valider_compte(depot, donnees.get("compte_id"))
    except ValueError as e:
        erreurs["compte_id"] = str(e)
    try:
        out["titre_id"] = _valider_titre(depot, donnees.get("titre_id"))
    except ValueError as e:
        erreurs["titre_id"] = str(e)
    try:
        out["date"] = _valider_date(donnees.get("date"))
    except ValueError as e:
        erreurs["date"] = str(e)
    try:
        qte = _parse_decimal_positif(
            donnees.get("quantite_titres_concernes"), autoriser_zero=False
        )
        out["quantite_titres_concernes"] = (
            int(qte) if qte == qte.to_integral_value() else str(qte)
        )
    except ValueError as e:
        erreurs["quantite_titres_concernes"] = str(e)
    try:
        out["montant_brut_par_action"] = str(
            _parse_decimal_positif(
                donnees.get("montant_brut_par_action") or "0"
            )
        )
    except ValueError as e:
        erreurs["montant_brut_par_action"] = str(e)
    try:
        out["montant_brut_total"] = str(
            _parse_decimal_positif(
                donnees.get("montant_brut_total"), autoriser_zero=False
            )
        )
    except ValueError as e:
        erreurs["montant_brut_total"] = str(e)
    try:
        out["taux_change"] = str(
            _parse_decimal_positif(
                donnees.get("taux_change") or "1", autoriser_zero=False
            )
        )
    except ValueError as e:
        erreurs["taux_change"] = str(e)
    net_eur = donnees.get("montant_net_eur")
    if net_eur not in (None, ""):
        try:
            out["montant_net_eur"] = str(_parse_decimal_positif(net_eur))
        except ValueError as e:
            erreurs["montant_net_eur"] = str(e)
    out["devise"] = _str_propre(donnees.get("devise") or "EUR").upper() or "EUR"
    out["notes"] = _str_propre(donnees.get("notes"))
    if erreurs:
        raise ErreursValidation(erreurs)
    return out


_NORMALISATEURS = {
    "alimentation_cash": lambda d, x: _normaliser_alim_ou_retrait(
        d, x, "alimentation_cash"
    ),
    "retrait_cash": lambda d, x: _normaliser_alim_ou_retrait(
        d, x, "retrait_cash"
    ),
    "achat": _normaliser_achat,
    "vente": _normaliser_vente,
    "dividende_recu": _normaliser_dividende,
}


def normaliser(
    depot: Depot, type_: str, donnees: dict, *, exclure_id: str | None = None
) -> dict:
    if type_ not in _NORMALISATEURS:
        raise ErreursValidation({"type": f"type inconnu : {type_}"})
    if type_ == "vente":
        return _normaliser_vente(depot, donnees, exclure_id=exclure_id)
    return _NORMALISATEURS[type_](depot, donnees)


# --- CRUD -----------------------------------------------------------------


def _generer_id() -> str:
    return uuid.uuid4().hex[:12]


def creer(depot: Depot, type_: str, donnees: dict) -> dict:
    mouvement = normaliser(depot, type_, donnees)
    mouvement["id"] = _generer_id()
    items = depot.charger("mouvements")
    items.append(mouvement)
    items.sort(key=lambda m: (m.get("date", ""), m.get("id", "")))
    depot.enregistrer("mouvements", items)
    _basculer_watchlist_si_achat(depot, mouvement)
    return mouvement


def _basculer_watchlist_si_achat(depot: Depot, mouvement: dict) -> None:
    """Si le mouvement est un achat lié à un titre, fait passer les watch
    `actif` correspondantes en `renforcement`. Import local pour éviter
    une dépendance circulaire entre services."""
    if mouvement.get("type") != "achat":
        return
    titre_id = mouvement.get("titre_id")
    if not titre_id:
        return
    from app.services.watchlist import basculer_actif_vers_renforcement

    basculer_actif_vers_renforcement(depot, titre_id)


def trouver(depot: Depot, mouvement_id: str) -> dict | None:
    for m in depot.charger("mouvements"):
        if m.get("id") == mouvement_id:
            return m
    return None


def mettre_a_jour(depot: Depot, mouvement_id: str, donnees: dict) -> dict:
    items = depot.charger("mouvements")
    for i, m in enumerate(items):
        if m.get("id") == mouvement_id:
            type_ = donnees.get("type") or m.get("type")
            mouvement = normaliser(
                depot, type_, donnees, exclure_id=mouvement_id
            )
            mouvement["id"] = mouvement_id
            items[i] = mouvement
            items.sort(key=lambda m: (m.get("date", ""), m.get("id", "")))
            depot.enregistrer("mouvements", items)
            _basculer_watchlist_si_achat(depot, mouvement)
            return mouvement
    raise KeyError(mouvement_id)


def supprimer(depot: Depot, mouvement_id: str) -> bool:
    items = depot.charger("mouvements")
    nouveau = [m for m in items if m.get("id") != mouvement_id]
    if len(nouveau) == len(items):
        return False
    # Vérification : si on supprime un achat consommé par une vente postérieure,
    # la vente perdra une référence. On laisse passer mais on alerte via ValueError.
    cible = next(m for m in items if m.get("id") == mouvement_id)
    if cible.get("type") == "achat":
        for m in nouveau:
            if m.get("type") != "vente":
                continue
            for lc in (m.get("calcul_fifo") or {}).get("lots_consommes", []):
                if lc.get("achat_id") == mouvement_id:
                    raise ValueError(
                        "Cet achat a été consommé par une vente "
                        f"({m.get('date')}) ; il faut d'abord supprimer "
                        "ou modifier cette vente."
                    )
    depot.enregistrer("mouvements", nouveau)
    return True


# --- Filtrage liste -------------------------------------------------------


def lister(
    depot: Depot,
    *,
    compte_id: str | None = None,
    titre_id: str | None = None,
    type_: str | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
) -> list[dict]:
    items = depot.charger("mouvements")
    res: list[dict] = []
    for m in items:
        if compte_id and m.get("compte_id") != compte_id:
            continue
        if titre_id and m.get("titre_id") != titre_id:
            continue
        if type_ and m.get("type") != type_:
            continue
        d = m.get("date") or ""
        if date_debut and d < date_debut:
            continue
        if date_fin and d > date_fin:
            continue
        res.append(m)
    res.sort(key=lambda m: (m.get("date", ""), m.get("id", "")), reverse=True)
    return res
