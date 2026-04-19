from __future__ import annotations

import hashlib
import secrets


def generate_secure_token(length: int = 32) -> str:
    """
    Generates a cryptographically secure random token.

    Args:
        length: The length of the token to generate.

    Returns:
        A secure random hex string.
    """
    return secrets.token_hex(length // 2)


def hash_password(password: str, salt: str) -> str:
    """
    Hashes a password with a given salt using SHA-256.

    Args:
        password: The plain-text password.
        salt: The salt to be used for hashing.

    Returns:
        The hex digest of the hashed password.
    """
    combined = password + salt
    return hashlib.sha256(combined.encode()).hexdigest()
