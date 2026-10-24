"""PKCE helpers (CodeVerifier.kt: 32 random bytes, base64url no padding, S256)."""
from __future__ import annotations

import base64
import hashlib
import secrets


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_verifier() -> str:
    return _b64url(secrets.token_bytes(32))


def challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def challenge_method() -> str:
    return "S256"
