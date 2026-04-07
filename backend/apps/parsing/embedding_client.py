"""
Django embedding client — Redis cache + circuit breaker wrapper.

Sits between the Celery embedding task and the FastAPI microservice:

    embed_chunks task
        ↓
    get_embeddings_batch()   ← THIS FILE
        ↓                  ↘
    Redis cache hit         circuit_breaker.call_embedding_service()
    (Optimization 5)             ↓
                           FastAPI /embed endpoint
                           (Optimization 1: batch of 64)

Caching strategy (Principle 9)
-------------------------------
Key:  emb:{sha256(raw_code)}
TTL:  604800 seconds (7 days)
Hit:  return cached vector, zero HTTP call (500x speedup on repeat)
Miss: forward to embedding service, store on return

Batch efficiency (Optimization 3 / Principle 10)
-------------------------------------------------
- cache.get_many()  → single Redis round-trip for all keys
- call_embedding_service() → one HTTP call for all cache misses
- cache.set_many()  → single Redis round-trip to store all new vectors

Circuit breaker (Principle 5)
------------------------------
If the embedding service circuit is OPEN, call_embedding_service()
raises pybreaker.CircuitBreakerError.  We catch it here, log the
skip, and return None for every text — callers treat None as
"embedding unavailable".
"""
import hashlib
import structlog
import pybreaker

from django.core.cache import cache

logger = structlog.get_logger(__name__)

_CACHE_TTL = 604_800   # 7 days in seconds
_CACHE_PREFIX = "emb"


def _cache_key(text: str) -> str:
    """Stable, collision-resistant cache key for a raw code string."""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"{_CACHE_PREFIX}:{digest}"


def get_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """
    Return 768-dim embedding vectors for each input text.

    Uses a two-level lookup:
      1. Redis cache  → O(1) per hit, no HTTP call (Optimization 5)
      2. Embedding service (circuit-broken) → batch HTTP call for misses

    Args:
        texts: list of raw source code strings (any length, any language)

    Returns:
        list of the same length as ``texts``.
        Each element is either:
          - list[float]  — 768-dim L2-normalised embedding
          - None         — embedding unavailable (circuit open, service error,
                           or input was empty string)

    Never raises.  All errors are caught, logged, and returned as None.
    """
    if not texts:
        return []

    # -----------------------------------------------------------------------
    # Step 1: Build cache keys and batch-lookup
    # -----------------------------------------------------------------------
    cache_keys = [_cache_key(t) for t in texts]
    cached = cache.get_many(cache_keys)          # single Redis round-trip

    hits = sum(1 for k in cache_keys if k in cached)
    misses = len(texts) - hits

    if hits:
        logger.info(
            "embedding_cache_hit",
            hits=hits,
            misses=misses,
            total=len(texts),
        )

    # -----------------------------------------------------------------------
    # Step 2: Identify texts that were NOT in cache
    # -----------------------------------------------------------------------
    miss_indices: list[int] = []
    miss_texts:   list[str] = []

    for i, (text, key) in enumerate(zip(texts, cache_keys)):
        if key not in cached:
            if text.strip():   # skip empty / whitespace-only strings
                miss_indices.append(i)
                miss_texts.append(text)
            # empty string → result stays None

    # -----------------------------------------------------------------------
    # Step 3: Call embedding service for cache misses
    # -----------------------------------------------------------------------
    fetched: list[list[float]] | None = None

    if miss_texts:
        from apps.pr_review.circuit_breaker import call_embedding_service
        try:
            fetched = call_embedding_service(miss_texts)
            logger.info(
                "embedding_service_fetched",
                count=len(fetched),
            )
        except pybreaker.CircuitBreakerError:
            logger.warning(
                "embedding_service_circuit_open",
                skipped_count=len(miss_texts),
            )
            # fetched stays None — all miss slots will be None in output
        except Exception as exc:
            logger.error(
                "embedding_service_error",
                error=str(exc),
                skipped_count=len(miss_texts),
            )
            # fetched stays None

    # -----------------------------------------------------------------------
    # Step 4: Build result list + populate cache for newly fetched vectors
    # -----------------------------------------------------------------------
    result: list[list[float] | None] = [None] * len(texts)
    to_cache: dict[str, list[float]] = {}

    # Fill cache hits
    for i, key in enumerate(cache_keys):
        if key in cached:
            result[i] = cached[key]

    # Fill service responses and queue for cache
    if fetched is not None:
        for local_idx, orig_idx in enumerate(miss_indices):
            if local_idx < len(fetched):
                vec = fetched[local_idx]
                result[orig_idx] = vec
                to_cache[cache_keys[orig_idx]] = vec

    # Store new vectors in a single Redis round-trip (Optimization 3)
    if to_cache:
        cache.set_many(to_cache, timeout=_CACHE_TTL)
        logger.info("embedding_cache_stored", count=len(to_cache))

    return result
