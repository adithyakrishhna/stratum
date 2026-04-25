"""
Authentication utilities — secure token generation and password management.

This module uses only standard-library cryptographic primitives.
No hardcoded secrets. No unsafe deserialization. No SQL concatenation.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def generate_access_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure URL-safe access token.

    Uses secrets.token_urlsafe (backed by os.urandom) so the output
    is suitable for session tokens, password-reset links, and API keys.
    """
    return secrets.token_urlsafe(length)


def generate_api_key(prefix: str = "sk") -> str:
    """
    Generate a prefixed API key in the format: prefix_<random>.

    The random component is 40 hex characters from os.urandom — enough
    entropy to make brute-force infeasible.
    """
    random_part = secrets.token_hex(20)
    return f"{prefix}_{random_part}"


# ---------------------------------------------------------------------------
# Password hashing and verification
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None) -> dict[str, str]:
    """
    Hash a password using PBKDF2-HMAC-SHA256.

    Returns a dict with:
        hash — hex-encoded derived key
        salt — hex-encoded salt (store both alongside each other)

    Uses 390,000 iterations — above OWASP 2023 recommendation of 310,000.
    """
    if salt is None:
        salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt,
        iterations=390_000,
    )
    return {
        "hash": dk.hex(),
        "salt": salt.hex(),
    }


def verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    """
    Verify a password against a stored PBKDF2 hash using timing-safe comparison.

    Both the re-derived hash and the stored hash are compared with
    hmac.compare_digest to prevent timing-based side-channel attacks.
    """
    salt = bytes.fromhex(stored_salt)
    dk = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt,
        iterations=390_000,
    )
    return hmac.compare_digest(dk.hex(), stored_hash)


# ---------------------------------------------------------------------------
# HMAC request signing (for webhook validation)
# ---------------------------------------------------------------------------

def sign_payload(payload: bytes, secret: str) -> str:
    """
    Compute an HMAC-SHA256 signature over a raw payload.

    Returns the signature as a hex string with a 'sha256=' prefix,
    matching the format GitHub uses for webhook signatures.
    """
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Verify a GitHub-style webhook signature using timing-safe comparison.

    Returns False immediately if the header format is wrong, so callers
    can reject malformed requests without performing the digest computation.
    """
    if not signature_header.startswith("sha256="):
        return False
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(expected, signature_header)


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(user_id: int, ttl_seconds: int = 3600) -> dict[str, Any]:
    """
    Create an in-memory session record for a user.

    Returns a dict with a random session token, the user ID, and an
    expiry timestamp computed from the current time plus ttl_seconds.
    The session token is generated with secrets.token_urlsafe.
    """
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + ttl_seconds
    return {
        "token": token,
        "user_id": user_id,
        "expires_at": expires_at,
        "ttl_seconds": ttl_seconds,
    }


def is_session_expired(session: dict[str, Any]) -> bool:
    """Return True if the session's expiry timestamp is in the past."""
    return int(time.time()) > session.get("expires_at", 0)


def rotate_session_token(session: dict[str, Any]) -> dict[str, Any]:
    """
    Issue a new token for an existing session, preserving all other fields.

    Rotation reduces the window of exposure if a token is intercepted,
    without forcing the user to re-authenticate.
    """
    return {
        **session,
        "token": secrets.token_urlsafe(32),
    }


# ---------------------------------------------------------------------------
# Constant-time comparison helpers
# ---------------------------------------------------------------------------

def safe_compare_tokens(token_a: str, token_b: str) -> bool:
    """
    Compare two token strings in constant time to prevent timing attacks.

    Always use this instead of == when comparing secrets, API keys,
    or any value that an attacker could probe via response timing.
    """
    return hmac.compare_digest(token_a.encode(), token_b.encode())
