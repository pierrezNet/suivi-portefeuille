"""Tests génération iCalendar."""

from pathlib import Path

import pytest
from icalendar import Calendar

from app.services.ics_export import generer_ics
from app.services.stockage import Depot


@pytest.fixture
def depot(tmp_path: Path) -> Depot:
    d = Depot(tmp_path)
    d.enregistrer("titres", [
        {"id": "stm", "ticker": "STMPA", "nom": "STMicro"},
    ])
    d.enregistrer("evenements", [
        {"id": "e-1", "type": "publication_resultats", "titre_id": "stm",
         "date": "2026-04-23", "libelle": "Résultats T1 2026 STM",
         "notes": "Surveiller carnet auto"},
        {"id": "e-2", "type": "rappel_personnel",
         "date": "2027-05-06", "libelle": "Réévaluer thèse Soitec",
         "notes": ""},
    ])
    d.enregistrer("watchlist", [
        {"id": "w-soi", "nom": "Soitec",
         "echeance_abandon": "2027-05-06",
         "these_lt": "Vendu sur bulle, racheter en correction.",
         "paliers_rachat": [
             {"prix": "80", "tranche": "1/3", "commentaire": "Premier"},
         ]},
    ])
    d.enregistrer("comptes", [])
    d.enregistrer("mouvements", [])
    return d


def test_generer_ics_renvoie_bytes_vcalendar(depot):
    contenu = generer_ics(depot)
    assert isinstance(contenu, bytes)
    assert contenu.startswith(b"BEGIN:VCALENDAR")
    assert b"END:VCALENDAR" in contenu


def test_ics_contient_tous_les_evenements_et_echeances(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    events = [c for c in cal.walk() if c.name == "VEVENT"]
    # 2 événements + 1 échéance watchlist
    assert len(events) == 3


def test_ics_summary_prefixe_par_ticker_si_titre_lie(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    summaries = [str(c["summary"]) for c in cal.walk() if c.name == "VEVENT"]
    assert any(s.startswith("[STMPA]") for s in summaries)


def test_ics_uid_stable_par_evenement(depot):
    """Deux générations consécutives doivent produire le même UID pour un événement donné."""
    cal1 = Calendar.from_ical(generer_ics(depot))
    cal2 = Calendar.from_ical(generer_ics(depot))
    uids1 = sorted(str(c["uid"]) for c in cal1.walk() if c.name == "VEVENT")
    uids2 = sorted(str(c["uid"]) for c in cal2.walk() if c.name == "VEVENT")
    assert uids1 == uids2


def test_ics_inclut_paliers_dans_description(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    descriptions = [
        str(c.get("description", ""))
        for c in cal.walk()
        if c.name == "VEVENT"
    ]
    assert any("80€" in d or "80" in d for d in descriptions)


def test_ics_categorie_par_type(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    categories = []
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        cat = c.get("categories")
        if cat:
            categories.append(str(cat))
    assert any("publication_resultats" in c for c in categories)
    assert any("echeance_watchlist" in c for c in categories)


# --- Notifications VALARM --------------------------------------------------


def _trigger_jours(alarm) -> int:
    """Extrait le nombre de jours du TRIGGER d'une VALARM (renvoie un entier positif)."""
    from datetime import timedelta
    t = alarm.get("trigger")
    if isinstance(t.dt, timedelta):
        return -t.dt.days
    return 0


def test_valarm_rappel_personnel_2_jours(depot):
    """Un rappel personnel (souvent un rappel DCA) a une alarme à T-2 jours."""
    cal = Calendar.from_ical(generer_ics(depot))
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        if "Réévaluer thèse Soitec" not in str(c.get("summary", "")):
            continue
        alarms = [s for s in c.subcomponents if s.name == "VALARM"]
        assert len(alarms) == 1
        assert _trigger_jours(alarms[0]) == 2
        return
    pytest.fail("Événement rappel_personnel introuvable")


def test_valarm_publication_resultats_1_jour(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        if "STMPA" not in str(c.get("summary", "")):
            continue
        alarms = [s for s in c.subcomponents if s.name == "VALARM"]
        assert len(alarms) == 1
        assert _trigger_jours(alarms[0]) == 1
        return
    pytest.fail("Événement publication_resultats introuvable")


def test_valarm_echeance_watchlist_1_jour(depot):
    cal = Calendar.from_ical(generer_ics(depot))
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        if "Réévaluer : Soitec" not in str(c.get("summary", "")):
            continue
        alarms = [s for s in c.subcomponents if s.name == "VALARM"]
        assert len(alarms) == 1
        assert _trigger_jours(alarms[0]) == 1
        return
    pytest.fail("Échéance watchlist Soitec introuvable")


def test_valarm_ordre_limite_2_jours(tmp_path):
    """Un ordre limite watchlist en attente a une alarme à T-2 jours."""
    d = Depot(tmp_path)
    d.enregistrer("titres", [{"id": "ifx", "ticker": "IFX", "nom": "Infineon"}])
    d.enregistrer("evenements", [])
    d.enregistrer("watchlist", [{
        "id": "w-ifx", "ticker": "IFX", "nom": "Infineon",
        "ordres_actifs": [{
            "id": "o-1", "prix_limite": "60", "quantite": 2,
            "statut": "en_attente", "validite": "2026-08-01",
        }],
    }])
    d.enregistrer("comptes", [])
    d.enregistrer("mouvements", [])

    cal = Calendar.from_ical(generer_ics(d))
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        if "Validité ordre" not in str(c.get("summary", "")):
            continue
        alarms = [s for s in c.subcomponents if s.name == "VALARM"]
        assert len(alarms) == 1
        assert _trigger_jours(alarms[0]) == 2
        return
    pytest.fail("Événement ordre limite introuvable")


def test_valarm_alarme_a_description():
    """L'alarme doit avoir ACTION:DISPLAY + DESCRIPTION (sinon certains clients la rejettent)."""
    from app.services.ics_export import _ajouter_evenement
    from icalendar import Calendar
    from datetime import date

    cal = Calendar()
    _ajouter_evenement(
        cal, uid="t-1", date_evt=date(2026, 6, 30),
        sommaire="Test alarme", description="", categorie="autre",
        rappel_jours=2,
    )
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        alarms = [s for s in c.subcomponents if s.name == "VALARM"]
        assert len(alarms) == 1
        assert str(alarms[0]["action"]) == "DISPLAY"
        assert "Test alarme" in str(alarms[0]["description"])
