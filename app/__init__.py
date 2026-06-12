"""Application factory Flask."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from app.services.stockage import Depot


def create_app(config_object: str = "config.Config") -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)

    # Dépôt JSON injecté dans la config pour les vues / services.
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    # En .exe gelé, on vérifie tôt que le dossier est inscriptible (Program
    # Files / antivirus) pour ne pas perdre silencieusement les saisies.
    if app.config.get("EST_GELE"):
        from app.services import runtime

        runtime.verifier_ecriture(data_dir)
    app.config["DEPOT"] = Depot(data_dir)

    _enregistrer_filtres(app)
    _enregistrer_blueprints(app)

    return app


def _enregistrer_filtres(app: Flask) -> None:
    from decimal import Decimal

    @app.template_filter("quantite")
    def formater_quantite(valeur) -> str:
        """Affiche une quantité de titres : entier brut si valeur entière,
        sinon décimal français (`,` séparateur) sans zéros morts."""
        if valeur is None or valeur == "":
            return "—"
        try:
            d = Decimal(str(valeur))
        except Exception:
            return str(valeur)
        if d == d.to_integral_value():
            return str(int(d))
        # Normalise pour retirer les zéros morts (12.500 → 12.5)
        normalisee = d.normalize()
        return format(normalisee, "f").replace(".", ",")

    @app.template_filter("euros")
    def formater_euros(valeur) -> str:
        if valeur is None or valeur == "":
            return "—"
        d = Decimal(str(valeur)).quantize(Decimal("0.01"))
        signe = "-" if d < 0 else ""
        d_abs = abs(d)
        entiere, _, decimale = f"{d_abs:.2f}".partition(".")
        # Séparateur milliers = espace insécable
        groupes = []
        while len(entiere) > 3:
            groupes.insert(0, entiere[-3:])
            entiere = entiere[:-3]
        groupes.insert(0, entiere)
        entiere_format = " ".join(groupes)
        return f"{signe}{entiere_format},{decimale} €"

    @app.template_filter("date_fr")
    def formater_date(valeur) -> str:
        if not valeur:
            return ""
        try:
            annee, mois, jour = valeur.split("-")
            return f"{jour}/{mois}/{annee}"
        except (ValueError, AttributeError):
            return str(valeur)

    @app.template_filter("date_courte")
    def formater_date_courte(valeur) -> str:
        """Format JJ/MM/AA (2 chiffres pour l'année)."""
        if not valeur:
            return ""
        try:
            annee, mois, jour = valeur.split("-")
            return f"{jour}/{mois}/{annee[-2:]}"
        except (ValueError, AttributeError):
            return str(valeur)

    @app.template_filter("millions")
    def formater_millions(valeur, devise: str = "€") -> str:
        """Formate un nombre en millions avec séparateurs et devise.
        Ex : '95409' → '95 409 M €' · '-15' → '-15 M €'."""
        if valeur is None or valeur == "":
            return "—"
        try:
            d = Decimal(str(valeur))
        except Exception:
            return str(valeur)
        signe = "-" if d < 0 else ""
        d_abs = abs(d)
        entiere = f"{int(d_abs)}"
        groupes = []
        while len(entiere) > 3:
            groupes.insert(0, entiere[-3:])
            entiere = entiere[:-3]
        groupes.insert(0, entiere)
        return f"{signe}{' '.join(groupes)} M {devise}".strip()

    @app.template_filter("date_iso_to_obj")
    def date_iso_to_obj(valeur):
        from datetime import date

        if not valeur:
            return None
        try:
            return date.fromisoformat(valeur)
        except (ValueError, TypeError):
            return None

    @app.template_filter("jours_avant")
    def jours_avant(valeur) -> int | None:
        """Nombre de jours entre aujourd'hui et la date ISO donnée.
        Positif = futur, négatif = passé, None si invalide."""
        from datetime import date

        d = date_iso_to_obj(valeur)
        if d is None:
            return None
        return (d - date.today()).days

    @app.context_processor
    def _injecter_helpers():
        from datetime import date

        return {"now_date": date.today}


def _enregistrer_blueprints(app: Flask) -> None:
    from app.routes.dashboard import bp as bp_dashboard
    from app.routes.mouvements import bp as bp_mouvements
    from app.routes.titres import bp as bp_titres
    from app.routes.watchlist import bp as bp_watchlist
    from app.routes.watchlist import enregistrer_endpoint_ics
    from app.routes.evenements import bp as bp_evenements
    from app.routes.notes_titres import bp as bp_notes_titres
    from app.routes.recap_fiscal import bp as bp_recap_fiscal
    from app.routes.virements_programmes import bp as bp_virements_programmes
    from app.routes.predictions import bp as bp_predictions
    from app.routes.reglages import bp as bp_reglages

    app.register_blueprint(bp_dashboard)
    app.register_blueprint(bp_mouvements)
    app.register_blueprint(bp_titres)
    app.register_blueprint(bp_watchlist)
    app.register_blueprint(bp_evenements)
    app.register_blueprint(bp_notes_titres)
    app.register_blueprint(bp_recap_fiscal)
    app.register_blueprint(bp_virements_programmes)
    app.register_blueprint(bp_predictions)
    app.register_blueprint(bp_reglages)
    enregistrer_endpoint_ics(app)
