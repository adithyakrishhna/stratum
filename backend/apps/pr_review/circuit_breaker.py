"""
Circuit breaker for the FastAPI embedding microservice.

From CLAUDE.md — Principle 5:
    FastAPI embedding service protected by pybreaker.
    Opens after 5 consecutive failures.
    Retries after 60 seconds (half-open).
    When open: skip embedding features, still post security and
    rule findings, log degradation clearly.

State machine
-------------
    CLOSED  → normal operation, requests pass through
    OPEN    → circuit tripped, requests blocked immediately
              (no HTTP calls made — avoids hammering a dead service)
    HALF-OPEN → one test request allowed after reset_timeout seconds;
                success → CLOSED, failure → OPEN again

Why this matters
----------------
Without a circuit breaker, every PR review would hang for 30s
waiting for a timeout when the embedding service is down. With it,
the decision to skip semantic analysis is made in microseconds.
"""
import requests as _requests
import structlog
import pybreaker

from django.conf import settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Listener — logs every state change and failure to structlog (Principle 4)
# ---------------------------------------------------------------------------

class _StructlogListener(pybreaker.CircuitBreakerListener):
    """Bridges pybreaker events into the structlog pipeline."""

    def state_change(self, cb, old_state, new_state):
        logger.warning(
            "circuit_breaker_state_change",
            name=cb.name,
            old_state=str(old_state),
            new_state=str(new_state),
        )

    def failure(self, cb, exc):
        logger.warning(
            "circuit_breaker_failure",
            name=cb.name,
            fail_count=cb.fail_counter,
            fail_max=cb.fail_max,
            error=str(exc),
        )

    def success(self, cb):
        logger.info("circuit_breaker_success", name=cb.name)


# ---------------------------------------------------------------------------
# The circuit breaker instance — module-level singleton
# ---------------------------------------------------------------------------

embedding_breaker = pybreaker.CircuitBreaker(
    fail_max=5,        # open after 5 consecutive failures
    reset_timeout=60,  # attempt half-open after 60 seconds
    name="embedding_service",
    listeners=[_StructlogListener()],
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_embedding_available() -> bool:
    """
    Return True if the circuit is CLOSED or HALF-OPEN (service may be up).
    Return False if the circuit is OPEN (service is known to be down).

    Called before every embedding operation so the orchestrator can decide
    whether to attempt semantic analysis or skip it immediately.
    """
    return embedding_breaker.current_state != pybreaker.STATE_OPEN


def get_circuit_state() -> str:
    """Return the current state string: 'closed', 'open', or 'half_open'."""
    return str(embedding_breaker.current_state)


def call_embedding_service(texts: list[str]) -> list[list[float]]:
    """
    Call POST /embed on the embedding microservice with circuit breaker.

    Args:
        texts: list of raw source code strings to embed (batch of up to 64)

    Returns:
        list of 768-dimensional embedding vectors, one per input text

    Raises:
        pybreaker.CircuitBreakerError — when circuit is OPEN (fast-fail)
        requests.RequestException     — when circuit is CLOSED but call fails
                                        (this failure is counted by pybreaker)
    """
    @embedding_breaker
    def _call():
        url = f"{settings.EMBEDDING_SERVICE_URL}/embed"
        response = _requests.post(
            url,
            json={"texts": texts},
            timeout=60,   # CodeBERT on CPU can take up to ~45s for large batches
        )
        response.raise_for_status()
        data = response.json()
        return data.get("embeddings", [])

    return _call()


def check_embedding_health() -> bool:
    """
    Probe GET /health on the embedding service.

    Returns True/False — does NOT go through the circuit breaker so it
    can be used for dashboard status checks without affecting the breaker
    state. Only real embed calls should count as failures.
    """
    try:
        url = f"{settings.EMBEDDING_SERVICE_URL}/health"
        response = _requests.get(url, timeout=5)
        return response.status_code == 200
    except Exception as exc:
        logger.debug("embedding_health_check_failed", error=str(exc))
        return False
