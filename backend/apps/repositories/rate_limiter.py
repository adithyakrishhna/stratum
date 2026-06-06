"""
Redis-based concurrent analysis rate limiter.

Enforces: max 2 concurrent analyses per user (Principle 3 — Rate Limiting).

Design
------
Each user has a counter in Redis: "analysis_slots:{user_id}"
- acquire_analysis_slot()  → atomically increments; rolls back if over limit
- release_analysis_slot()  → decrements when analysis ends
- get_active_count()        → read-only check (for API responses)

Atomicity
---------
INCR + compare is NOT atomic on its own. We use a Lua script so the
check-and-increment is a single Redis operation with no race conditions.
Two workers cannot both read "1" and both increment to "2" simultaneously.

Safety TTL
----------
Every slot key has a 2-hour TTL. If a Celery worker crashes without
releasing its slot, the counter self-heals after 2 hours instead of
permanently blocking the user.
"""
import redis
import structlog
from django.conf import settings

logger = structlog.get_logger(__name__)

MAX_CONCURRENT_ANALYSES = 2
_SLOT_TTL = 7200   # 2 hours safety expiry

# Module-level client — reused across calls (connection pool inside redis-py)
_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
    return _redis_client


def _slot_key(user_id: str) -> str:
    return f"analysis_slots:{user_id}"


# ---------------------------------------------------------------------------
# Lua script — atomic check-and-increment
# Increments the counter only if the result would be <= MAX_CONCURRENT.
# Returns the new value on success, or -1 if the limit is already reached.
# ---------------------------------------------------------------------------
_ACQUIRE_LUA = """
local key   = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl   = tonumber(ARGV[2])
local cur   = tonumber(redis.call('GET', key) or 0)
if cur >= limit then
    return -1
end
local new = redis.call('INCR', key)
redis.call('EXPIRE', key, ttl)
return new
"""


def acquire_analysis_slot(user_id: str) -> bool:
    """
    Attempt to claim one analysis slot for this user.

    Returns True  → slot acquired, analysis may proceed.
    Returns False → limit reached (2 already running), caller must 429.

    Thread/process safe: backed by a Redis Lua script (atomic).
    """
    key = _slot_key(user_id)

    try:
        result = _get_redis().eval(
            _ACQUIRE_LUA,
            1,          # number of KEYS
            key,        # KEYS[1]
            str(MAX_CONCURRENT_ANALYSES),  # ARGV[1]
            str(_SLOT_TTL),                # ARGV[2]
        )
        acquired = int(result) != -1
        logger.info(
            "analysis_slot_acquire",
            user_id=user_id,
            acquired=acquired,
            slot_count=int(result) if acquired else MAX_CONCURRENT_ANALYSES,
        )
        return acquired

    except Exception as exc:
        # If Redis is unreachable, fail open — allow the analysis rather
        # than blocking all users because of an infrastructure hiccup.
        logger.warning(
            "analysis_slot_acquire_error",
            user_id=user_id,
            error=str(exc),
        )
        return True


def release_analysis_slot(user_id: str) -> None:
    """
    Release one analysis slot when an analysis completes or fails.

    Always call this in a finally block so slots are never permanently held.
    Never raises — a failure here must not mask the original task result.
    """
    key = _slot_key(user_id)

    try:
        r = _get_redis()
        current = r.get(key)
        if current and int(current) > 0:
            r.decr(key)
            logger.info("analysis_slot_released", user_id=user_id)
        else:
            # Counter is already 0 or missing — safe to ignore
            logger.debug("analysis_slot_release_noop", user_id=user_id)

    except Exception as exc:
        logger.warning(
            "analysis_slot_release_error",
            user_id=user_id,
            error=str(exc),
        )


def get_active_count(user_id: str) -> int:
    """
    Return how many analyses are currently running for this user.
    Used by the API to include the count in 429 responses.
    """
    key = _slot_key(user_id)
    try:
        val = _get_redis().get(key)
        return int(val) if val else 0
    except Exception:
        return 0
