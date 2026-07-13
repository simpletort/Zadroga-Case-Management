"""
shared/crypto.py — Cloud KMS CMEK encryption for PHI fields (SSN, etc.).

Usage:
    from shared.crypto import encrypt_ssn, decrypt_ssn, normalize_ssn

The key name is read from SSN_KMS_KEY_NAME env var at first use.
Format: projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}

SECURITY: Never log plaintext SSN values.  Only log "ssn_encrypted" or
"ssn_present=true/false" when audit-trailing.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Optional

from google.cloud import kms

_client: Optional[kms.KeyManagementServiceClient] = None
_SSN_DIGITS = re.compile(r"^\d{9}$")
_HASH_SALT = "simpletort-zadroga-ssn-v1"  # fixed salt for deterministic Firestore lookups


def _get_client() -> kms.KeyManagementServiceClient:
    global _client
    if _client is None:
        _client = kms.KeyManagementServiceClient()
    return _client


def _get_key_name() -> str:
    key = os.environ.get("SSN_KMS_KEY_NAME", "")
    if not key:
        raise RuntimeError(
            "SSN_KMS_KEY_NAME env var is required for SSN encryption. "
            "Format: projects/{project}/locations/{loc}/keyRings/{ring}/cryptoKeys/{key}"
        )
    return key


def normalize_ssn(raw: str) -> str:
    """
    Strip all non-digit characters and validate exactly 9 digits.
    Raises ValueError if the result is not a valid SSN shape.
    """
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) != 9:
        raise ValueError(f"SSN must be exactly 9 digits after normalisation, got {len(digits)}")
    return digits


def encrypt_ssn(raw_ssn: str) -> str:
    """
    Normalize to digits-only, then encrypt via Cloud KMS CMEK.
    Returns a base64-encoded ciphertext string safe for Firestore storage.
    """
    digits = normalize_ssn(raw_ssn)
    key_name = _get_key_name()
    resp = _get_client().encrypt(
        request={"name": key_name, "plaintext": digits.encode("utf-8")}
    )
    return base64.b64encode(resp.ciphertext).decode("utf-8")


def decrypt_ssn(ciphertext_b64: str) -> str:
    """
    Decrypt a base64-encoded KMS ciphertext back to a 9-digit SSN string.
    """
    key_name = _get_key_name()
    ciphertext = base64.b64decode(ciphertext_b64)
    resp = _get_client().decrypt(
        request={"name": key_name, "ciphertext": ciphertext}
    )
    return resp.plaintext.decode("utf-8")


def compute_ssn_hash(raw_ssn: str) -> str:
    """
    Normalize to digits-only, then return a salted SHA-256 hex digest.

    This is a DETERMINISTIC one-way hash used for Firestore duplicate-detection
    queries.  KMS encrypt() is non-deterministic (random padding each call),
    so we cannot use ssn_encrypted for lookups.

    The salt prevents rainbow-table attacks if the Firestore export leaks.
    """
    digits = normalize_ssn(raw_ssn)
    return hashlib.sha256(f"{_HASH_SALT}:{digits}".encode("utf-8")).hexdigest()
