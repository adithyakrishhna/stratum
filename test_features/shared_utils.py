"""
Shared utility helpers used across test_features examples.

These functions are intentionally general-purpose so that similar
implementations in other modules can be detected as semantic duplicates
by Stratum's duplicate-detection pipeline.
"""
from __future__ import annotations

import math
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Form / input validation
# ---------------------------------------------------------------------------

def validate_form_fields(
    form_data: dict[str, Any],
    required_fields: list[str],
    strict: bool = False,
) -> dict[str, Any]:
    """
    Validate a form data dictionary against a list of required field names.

    Returns a result dict with:
        valid   — True if all required fields are present and non-empty
        errors  — dict of field_name → error message for each failing field
        data    — cleaned copy of form_data (stripped strings, None for blanks)

    When strict=True, any key in form_data that is NOT in required_fields
    is treated as an unexpected field and added to errors.
    """
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}

    for key, value in form_data.items():
        if isinstance(value, str):
            cleaned[key] = value.strip() or None
        else:
            cleaned[key] = value

    for field in required_fields:
        if field not in cleaned:
            errors[field] = "This field is required."
            continue
        val = cleaned[field]
        if val is None or val == "" or val == []:
            errors[field] = "This field must not be empty."

    if strict:
        required_set = set(required_fields)
        for key in form_data:
            if key not in required_set:
                errors[key] = "Unexpected field."

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "data": cleaned,
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate_query_results(
    items: list[Any],
    page: int,
    page_size: int,
    transform_fn: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """
    Paginate an in-memory list of items.

    Returns:
        items       — the page slice, optionally transformed
        page        — current page number (1-indexed)
        page_size   — items per page as requested
        total_items — total number of items before pagination
        total_pages — total page count
        has_next    — True if a next page exists
        has_prev    — True if a previous page exists
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10

    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / page_size))

    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    if transform_fn is not None:
        page_items = [transform_fn(item) for item in page_items]

    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
