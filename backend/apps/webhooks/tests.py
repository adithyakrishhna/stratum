"""
Tests for webhook HMAC signature verification.

These are pure logic tests — no DB, no external services.
The HMAC bug (iss must be a string) cost a full day; keeping this
path well-covered prevents regressions.
"""
import hashlib
import hmac

from django.test import SimpleTestCase

from apps.webhooks.services import verify_github_signature


def _make_signature(secret: str, body: bytes) -> str:
    """Helper: compute the correct HMAC-SHA256 signature for a payload."""
    mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


class TestVerifyGithubSignature(SimpleTestCase):

    def test_valid_signature_accepted(self):
        secret = "stratum-secret-2026"
        body = b'{"action": "opened", "number": 1}'
        sig = _make_signature(secret, body)
        self.assertTrue(verify_github_signature(secret, body, sig))

    def test_wrong_secret_rejected(self):
        body = b'{"action": "opened"}'
        sig = _make_signature("correct-secret", body)
        self.assertFalse(verify_github_signature("wrong-secret", body, sig))

    def test_tampered_body_rejected(self):
        secret = "stratum-secret-2026"
        body = b'{"action": "opened"}'
        sig = _make_signature(secret, body)
        self.assertFalse(verify_github_signature(secret, b'{"action": "closed"}', sig))

    def test_missing_signature_header_rejected(self):
        self.assertFalse(verify_github_signature("secret", b"payload", ""))

    def test_signature_without_sha256_prefix_rejected(self):
        """GitHub always sends 'sha256=<hex>' — bare hex must be rejected."""
        secret = "secret"
        body = b"payload"
        mac = hmac.new(secret.encode(), msg=body, digestmod=hashlib.sha256)
        bare_hex = mac.hexdigest()  # no "sha256=" prefix
        self.assertFalse(verify_github_signature(secret, body, bare_hex))

    def test_empty_secret_rejected(self):
        """An unconfigured secret must never pass verification."""
        self.assertFalse(verify_github_signature("", b"payload", "sha256=abc"))

    def test_timing_safe_comparison(self):
        """Correct signature always accepted regardless of string position."""
        secret = "timing-test-secret"
        body = b"some payload bytes"
        sig = _make_signature(secret, body)
        self.assertTrue(verify_github_signature(secret, body, sig))

    def test_unicode_secret_handled(self):
        """Secret may contain non-ASCII chars from .env — must not raise."""
        secret = "sécret-clé-2026"
        body = b'{"zen": "hello"}'
        sig = _make_signature(secret, body)
        self.assertTrue(verify_github_signature(secret, body, sig))

    def test_large_payload_accepted(self):
        """Webhooks for large PRs can have big payloads — must not truncate."""
        secret = "secret"
        body = b"x" * 100_000
        sig = _make_signature(secret, body)
        self.assertTrue(verify_github_signature(secret, body, sig))
