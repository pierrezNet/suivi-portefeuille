"""Chiffrement symétrique pour publication client-side encrypted.

Le contenu chiffré côté Python doit pouvoir être déchiffré côté navigateur
via la WebCrypto API. On utilise donc des primitives strictement
interopérables :

  - PBKDF2-HMAC-SHA256, 200 000 itérations, sel 32 bytes
  - AES-256-GCM, IV 12 bytes (96 bits, standard pour GCM)
  - Sortie : dict JSON `{v, salt, iv, ct, iter}` (tout en base64 standard)

Côté JS (script du HTML statique) :
  - crypto.subtle.importKey("raw", mdp) → deriveKey(PBKDF2, salt) → AES-GCM key
  - crypto.subtle.decrypt({name:"AES-GCM", iv}, key, ct) → texte clair
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


VERSION = 1
ITERATIONS = 200_000
TAILLE_SEL = 32
TAILLE_IV = 12
TAILLE_CLE = 32  # 256 bits
LONGUEUR_MIN_MOT_PASSE = 15


class MotPasseInvalide(ValueError):
    """Mot de passe absent ou trop court."""


class DechiffrementInvalide(ValueError):
    """Échec du déchiffrement (mot de passe incorrect ou contenu corrompu)."""


@dataclass
class PaquetChiffre:
    version: int
    salt_b64: str
    iv_b64: str
    ct_b64: str
    iterations: int

    def to_dict(self) -> dict:
        return {
            "v": self.version,
            "salt": self.salt_b64,
            "iv": self.iv_b64,
            "ct": self.ct_b64,
            "iter": self.iterations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PaquetChiffre":
        return cls(
            version=int(data["v"]),
            salt_b64=data["salt"],
            iv_b64=data["iv"],
            ct_b64=data["ct"],
            iterations=int(data.get("iter", ITERATIONS)),
        )


def _valider_mot_passe(mot_passe: str) -> None:
    if not mot_passe or len(mot_passe) < LONGUEUR_MIN_MOT_PASSE:
        raise MotPasseInvalide(
            f"Mot de passe trop court : {len(mot_passe)} caractères "
            f"(minimum {LONGUEUR_MIN_MOT_PASSE})."
        )


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _from_b64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _deriver_cle(mot_passe: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=TAILLE_CLE,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(mot_passe.encode("utf-8"))


def chiffrer(donnees: dict, mot_passe: str) -> PaquetChiffre:
    """Chiffre un dict Python en JSON puis AES-256-GCM.

    Renvoie un PaquetChiffre prêt à être sérialisé en JSON publiable.
    """
    _valider_mot_passe(mot_passe)
    payload = json.dumps(donnees, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(TAILLE_SEL)
    iv = os.urandom(TAILLE_IV)
    cle = _deriver_cle(mot_passe, salt)
    ct = AESGCM(cle).encrypt(iv, payload, associated_data=None)
    return PaquetChiffre(
        version=VERSION,
        salt_b64=_b64(salt),
        iv_b64=_b64(iv),
        ct_b64=_b64(ct),
        iterations=ITERATIONS,
    )


def dechiffrer(paquet: PaquetChiffre | dict, mot_passe: str) -> dict:
    """Déchiffre un PaquetChiffre vers le dict d'origine."""
    if isinstance(paquet, dict):
        paquet = PaquetChiffre.from_dict(paquet)
    if paquet.version != VERSION:
        raise DechiffrementInvalide(
            f"Version inconnue : {paquet.version} (attendu {VERSION})"
        )
    salt = _from_b64(paquet.salt_b64)
    iv = _from_b64(paquet.iv_b64)
    ct = _from_b64(paquet.ct_b64)
    cle = _deriver_cle(mot_passe, salt, paquet.iterations)
    try:
        clair = AESGCM(cle).decrypt(iv, ct, associated_data=None)
    except Exception as e:  # InvalidTag, etc.
        raise DechiffrementInvalide(
            "Mot de passe incorrect ou contenu corrompu."
        ) from e
    return json.loads(clair.decode("utf-8"))
