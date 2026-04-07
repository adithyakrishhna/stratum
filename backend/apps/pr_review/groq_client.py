"""
Groq API client for AI-generated fix suggestions.

Design:
- Only called for critical and high severity findings (not medium/low)
  to preserve the free-tier quota of 14,400 requests/day.
- Results cached in Redis keyed by sha256(finding_type + title + code_snippet)
  with a 24-hour TTL — the same code pattern gets the same suggestion.
- If GROQ_API_KEY is not set or ENABLE_LLM_SUGGESTIONS=False in .env,
  returns empty string silently (graceful degradation).
- Uses groq library with llama-3.1-8b-instant model (fastest, free tier).
"""
import hashlib

import structlog
from django.conf import settings
from django.core.cache import cache

logger = structlog.get_logger(__name__)

_CACHE_TTL = 86400   # 24 hours
_MODEL = "llama-3.1-8b-instant"
_MAX_TOKENS = 256    # keep suggestions concise


def get_fix_suggestion(
    finding_type: str,
    severity: str,
    title: str,
    description: str,
    code_snippet: str,
    language: str,
) -> str:
    """
    Return a concise fix suggestion for a security or rule finding.

    Returns empty string when:
    - ENABLE_LLM_SUGGESTIONS is False in settings
    - GROQ_API_KEY is not configured
    - Severity is below high (caller should filter, but we guard here too)
    - Any Groq API error occurs (graceful degradation)
    """
    if not getattr(settings, "ENABLE_LLM_SUGGESTIONS", True):
        return ""

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        return ""

    if severity not in ("critical", "high"):
        return ""

    # Cache key based on the unique combination of finding characteristics
    fingerprint = hashlib.sha256(
        f"{finding_type}:{title}:{code_snippet[:300]}".encode()
    ).hexdigest()
    cache_key = f"groq_suggestion:{fingerprint}"

    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("groq_suggestion_cache_hit", cache_key=cache_key)
        return cached

    suggestion = _call_groq(
        api_key=api_key,
        finding_type=finding_type,
        title=title,
        description=description,
        code_snippet=code_snippet,
        language=language,
    )

    if suggestion:
        cache.set(cache_key, suggestion, timeout=_CACHE_TTL)

    return suggestion


def _call_groq(
    api_key: str,
    finding_type: str,
    title: str,
    description: str,
    code_snippet: str,
    language: str,
) -> str:
    """
    Make the actual Groq API call.

    Returns empty string on any error — the PR review will still post
    without a suggestion rather than failing entirely.
    """
    try:
        from groq import Groq

        client = Groq(api_key=api_key)

        snippet_preview = code_snippet[:400] if code_snippet else "(no snippet)"

        prompt = (
            f"A {severity_label(finding_type)} issue was found in {language} code:\n\n"
            f"Issue: {title}\n"
            f"Details: {description}\n\n"
            f"Code:\n```{language}\n{snippet_preview}\n```\n\n"
            f"Provide a concise, specific fix in 2-3 sentences. "
            f"Focus on exactly what to change in this code. No preamble."
        )

        response = client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_TOKENS,
            temperature=0.2,
        )

        suggestion = response.choices[0].message.content.strip()
        logger.info(
            "groq_suggestion_generated",
            finding_type=finding_type,
            title=title,
            tokens_used=response.usage.total_tokens if response.usage else 0,
        )
        return suggestion

    except Exception as exc:
        logger.warning(
            "groq_suggestion_failed",
            finding_type=finding_type,
            title=title,
            error=str(exc),
        )
        return ""


def severity_label(finding_type: str) -> str:
    """Map finding type to a human-readable label for the prompt."""
    labels = {
        "HARDCODED_SECRET": "security",
        "SQL_INJECTION": "security",
        "DANGEROUS_FUNCTION": "security",
        "MISSING_AUTH": "security",
        "INSECURE_RANDOM": "security",
        "OPEN_REDIRECT": "security",
    }
    return labels.get(finding_type, "code quality")
