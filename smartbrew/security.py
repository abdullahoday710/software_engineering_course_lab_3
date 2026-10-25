"""Small security helpers: salted PBKDF2 hashing for passwords, PINs and card IDs."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 60_000


def hash_secret(secret: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a secret with PBKDF2-HMAC-SHA256 and a random salt.

    Args:
        secret: the plain-text password, PIN or card identifier.
        salt: hex salt to reuse (for verification); a new one is made if None.

    Returns:
        tuple[str, str]: ``(hash_hex, salt_hex)``.
    """
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex(), salt


def verify_secret(secret: str, expected_hash: str, salt: str) -> bool:
    """Check a plain-text secret against a stored hash in constant time.

    Args:
        secret: the value the user typed or tapped.
        expected_hash: stored hex hash from :func:`hash_secret`.
        salt: stored hex salt from :func:`hash_secret`.

    Returns:
        bool: True if the secret matches.
    """
    candidate, _ = hash_secret(secret, salt)
    return hmac.compare_digest(candidate, expected_hash)
