import hashlib
import hmac

import structlog

logger = structlog.get_logger(__name__)


def verify_github_signature(secret: str, payload_body: bytes, signature_header: str) -> bool:
    """
    Verify the HMAC-SHA256 signature from GitHub's X-Hub-Signature-256 header.

    GitHub docs: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not secret:
        logger.error("webhook_secret_not_configured")
        return False

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("webhook_missing_or_malformed_signature")
        return False

    expected_sig = signature_header[7:]  # strip "sha256=" prefix

    mac = hmac.new(
        secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    )
    return hmac.compare_digest(mac.hexdigest(), expected_sig)
