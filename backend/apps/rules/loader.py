"""
stratum.yaml loader with Redis caching.

Cache key : rules:{repo_id}
TTL       : 1 hour (3600 seconds) — Caching Strategy from CLAUDE.md
Miss path : read from cloned repo directory on disk
Fallback  : DEFAULT_CONFIG when no stratum.yaml is present

Always returns a fully-populated config dict — never raises.
"""
import os

import structlog
import yaml
from django.conf import settings
from django.core.cache import cache

logger = structlog.get_logger(__name__)

_CACHE_TTL = 3600  # 1 hour

DEFAULT_CONFIG: dict = {
    "rules": {
        "max_function_lines": 50,
        "max_complexity": 10,
        "forbidden_imports": {},
        "naming_conventions": {},
    },
    "scoring_weights": {
        "complexity": 0.3,
        "duplication": 0.3,
        "violations": 0.2,
        "cluster_membership": 0.2,
    },
    "semantic": {
        "similarity_threshold": 0.97,
        "cross_language_clustering": False,
    },
}


def load_rules(repo_id: str) -> dict:
    """
    Return the validated rule config for a repo.

    Checks Redis cache first; reads from cloned repo on miss.
    Always returns a valid config — never raises.
    """
    cache_key = f"rules:{repo_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("rules_cache_hit", repo_id=repo_id, cache_key=cache_key)
        return cached

    raw = _load_from_disk(repo_id)
    if raw is None:
        logger.info("rules_using_defaults", repo_id=repo_id)
        config = _validate_and_fill_defaults({})
    else:
        config = _validate_and_fill_defaults(raw)

    cache.set(cache_key, config, timeout=_CACHE_TTL)
    logger.info(
        "rules_cached",
        repo_id=repo_id,
        cache_key=cache_key,
        ttl=_CACHE_TTL,
        max_function_lines=config["rules"]["max_function_lines"],
        max_complexity=config["rules"]["max_complexity"],
    )
    return config


def invalidate_cache(repo_id: str) -> None:
    """
    Bust the cached config for a repo.
    Call this whenever stratum.yaml is updated in the connected repo.
    """
    cache.delete(f"rules:{repo_id}")
    logger.info("rules_cache_invalidated", repo_id=repo_id)


def _load_from_disk(repo_id: str) -> dict | None:
    """Read stratum.yaml from the cloned repo directory. Returns None if absent."""
    clone_base = getattr(settings, "REPO_CLONE_BASE_DIR", "")
    yaml_path = os.path.join(clone_base, str(repo_id), "stratum.yaml")

    if not os.path.exists(yaml_path):
        return None

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            logger.info("rules_loaded_from_disk", repo_id=repo_id, path=yaml_path)
            return data
        logger.warning("rules_yaml_invalid_structure", repo_id=repo_id, path=yaml_path)
    except yaml.YAMLError as exc:
        logger.warning("rules_yaml_parse_error", repo_id=repo_id, path=yaml_path, error=str(exc))
    except OSError as exc:
        logger.warning("rules_yaml_read_error", repo_id=repo_id, path=yaml_path, error=str(exc))

    return None


def _validate_and_fill_defaults(raw: dict) -> dict:
    """
    Ensure all expected keys exist with the correct types.
    Unknown top-level keys are preserved for forward compatibility.
    """
    rules_raw = raw.get("rules", {})
    weights_raw = raw.get("scoring_weights", {})
    semantic_raw = raw.get("semantic", {})

    return {
        "rules": {
            "max_function_lines": _safe_int(rules_raw.get("max_function_lines"), default=50, minimum=1),
            "max_complexity": _safe_int(rules_raw.get("max_complexity"), default=10, minimum=1),
            "forbidden_imports": _normalize_list_map(rules_raw.get("forbidden_imports", {})),
            "naming_conventions": _normalize_str_map(rules_raw.get("naming_conventions", {})),
        },
        "scoring_weights": {
            "complexity": _safe_float(weights_raw.get("complexity"), default=0.3),
            "duplication": _safe_float(weights_raw.get("duplication"), default=0.3),
            "violations": _safe_float(weights_raw.get("violations"), default=0.2),
            "cluster_membership": _safe_float(weights_raw.get("cluster_membership"), default=0.2),
        },
        "semantic": {
            "similarity_threshold": _safe_float(
                semantic_raw.get("similarity_threshold"), default=0.97
            ),
            "cross_language_clustering": bool(semantic_raw.get("cross_language_clustering", False)),
        },
    }


def _safe_int(value, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float) -> float:
    try:
        result = float(value)
        return result if 0.0 <= result <= 1.0 else default
    except (TypeError, ValueError):
        return default


def _normalize_list_map(value) -> dict:
    """Ensure {language: [list of strings]} structure."""
    if not isinstance(value, dict):
        return {}
    return {
        lang: [str(item) for item in items] if isinstance(items, list) else []
        for lang, items in value.items()
    }


def _normalize_str_map(value) -> dict:
    """Ensure {language: string} structure."""
    if not isinstance(value, dict):
        return {}
    return {lang: str(convention) for lang, convention in value.items()}
