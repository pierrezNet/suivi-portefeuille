"""Tests chiffrement AES-256-GCM + PBKDF2."""

import json

import pytest

from app.services import chiffrement as chf
from app.services.chiffrement import (
    DechiffrementInvalide,
    MotPasseInvalide,
    PaquetChiffre,
)


MDP_VALIDE = "phrase-de-passe-forte-2026"  # 26 chars


def test_round_trip_simple():
    donnees = {"hello": "world", "n": 42}
    paquet = chf.chiffrer(donnees, MDP_VALIDE)
    assert chf.dechiffrer(paquet, MDP_VALIDE) == donnees


def test_round_trip_dict_complexe():
    donnees = {
        "comptes": [
            {"id": "pea", "nom": "PEA Bourse Direct", "solde": "175.64"},
            {"id": "cto", "nom": "CTO Bourse Direct", "solde": "211.74"},
        ],
        "total": "387.38",
        "annee": 2026,
        "unicode": "éèàü — €",
    }
    paquet = chf.chiffrer(donnees, MDP_VALIDE)
    assert chf.dechiffrer(paquet, MDP_VALIDE) == donnees


def test_mauvais_mot_de_passe_leve():
    paquet = chf.chiffrer({"x": 1}, MDP_VALIDE)
    with pytest.raises(DechiffrementInvalide):
        chf.dechiffrer(paquet, "phrase-de-passe-fausse-zzz")


def test_mot_de_passe_trop_court_refuse():
    with pytest.raises(MotPasseInvalide):
        chf.chiffrer({"x": 1}, "court")


def test_mot_de_passe_vide_refuse():
    with pytest.raises(MotPasseInvalide):
        chf.chiffrer({"x": 1}, "")


def test_paquet_serializable_json():
    """Le paquet doit pouvoir transiter via JSON sans perte."""
    paquet = chf.chiffrer({"x": 1, "y": 2}, MDP_VALIDE)
    j = json.dumps(paquet.to_dict())
    paquet_restaure = PaquetChiffre.from_dict(json.loads(j))
    assert chf.dechiffrer(paquet_restaure, MDP_VALIDE) == {"x": 1, "y": 2}


def test_salt_et_iv_aleatoires_a_chaque_chiffrement():
    """Deux chiffrements consécutifs du même contenu doivent différer."""
    p1 = chf.chiffrer({"x": 1}, MDP_VALIDE)
    p2 = chf.chiffrer({"x": 1}, MDP_VALIDE)
    assert p1.salt_b64 != p2.salt_b64
    assert p1.iv_b64 != p2.iv_b64
    assert p1.ct_b64 != p2.ct_b64
    # Mais déchiffrement OK pour les deux
    assert chf.dechiffrer(p1, MDP_VALIDE) == {"x": 1}
    assert chf.dechiffrer(p2, MDP_VALIDE) == {"x": 1}


def test_modification_ciphertext_detectee():
    """AES-GCM est authentifié : modification = détection."""
    paquet = chf.chiffrer({"x": 1}, MDP_VALIDE)
    # On bricole un caractère du ciphertext
    ct_modif = paquet.ct_b64
    ct_modif = ("A" if ct_modif[0] != "A" else "B") + ct_modif[1:]
    paquet_corrompu = PaquetChiffre(
        version=paquet.version,
        salt_b64=paquet.salt_b64,
        iv_b64=paquet.iv_b64,
        ct_b64=ct_modif,
        iterations=paquet.iterations,
    )
    with pytest.raises(DechiffrementInvalide):
        chf.dechiffrer(paquet_corrompu, MDP_VALIDE)


def test_format_paquet_attendu():
    """Vérifie la forme attendue côté JS (WebCrypto compatible)."""
    paquet = chf.chiffrer({"x": 1}, MDP_VALIDE)
    d = paquet.to_dict()
    assert set(d.keys()) == {"v", "salt", "iv", "ct", "iter"}
    assert d["v"] == 1
    assert d["iter"] == chf.ITERATIONS
    assert d["iter"] >= 600_000  # durci (OWASP) — rétro-compatible (iter stocké)
    # Tailles binaires attendues (avant base64)
    import base64
    assert len(base64.b64decode(d["salt"])) == 32
    assert len(base64.b64decode(d["iv"])) == 12
