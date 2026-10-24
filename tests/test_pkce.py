import base64
import hashlib

from ica_handla import pkce


def test_verifier_is_urlsafe_no_padding():
    v = pkce.new_verifier()
    assert "=" not in v and "+" not in v and "/" not in v
    assert 42 <= len(v) <= 44  # 32 bytes -> 43 chars


def test_challenge_matches_s256():
    v = pkce.new_verifier()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(v.encode()).digest()
    ).decode().rstrip("=")
    assert pkce.challenge(v) == expected
    assert pkce.challenge_method() == "S256"


def test_verifiers_are_random():
    assert pkce.new_verifier() != pkce.new_verifier()
