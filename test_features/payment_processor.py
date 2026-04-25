"""
Payment processing utilities — handles billing, invoices, and shipping.

WARNING: This file contains intentional security issues for demo purposes.
         It exists to demonstrate Stratum's PR review capabilities.
"""
from __future__ import annotations

import math
import pickle
from decimal import Decimal
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Hardcoded secret (critical)
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = "sk_live_4xT9mNpQ2rK7dL3jF8aH5cW1vB6yE0uZ"


# ---------------------------------------------------------------------------
# Unsafe deserialization (high)
# ---------------------------------------------------------------------------

def restore_payment_session(session_data: bytes) -> dict[str, Any]:
    """Deserialize a payment session from a previously stored blob."""
    return pickle.loads(session_data)


# ---------------------------------------------------------------------------
# Shipping cost calculation (complexity violation)
# ---------------------------------------------------------------------------

def calculate_shipping_cost(
    weight_kg: float,
    destination_country: str,
    carrier: str,
    express: bool = False,
    fragile: bool = False,
    insurance_value: float = 0.0,
    promo_code: str | None = None,
) -> dict[str, Any]:
    """
    Calculate shipping cost based on weight, destination, carrier, and options.

    Applies carrier-specific base rates, country-zone surcharges, express
    multipliers, fragile handling fees, insurance premiums, and promo discounts.
    """
    base_rate: float = 0.0
    surcharges: list[dict[str, float]] = []

    if carrier == "fedex":
        if weight_kg <= 1:
            base_rate = 8.50
        elif weight_kg <= 5:
            base_rate = 12.00 + (weight_kg - 1) * 1.50
        elif weight_kg <= 20:
            base_rate = 18.00 + (weight_kg - 5) * 0.90
        else:
            base_rate = 31.50 + (weight_kg - 20) * 0.60
    elif carrier == "ups":
        if weight_kg <= 2:
            base_rate = 7.00
        elif weight_kg <= 10:
            base_rate = 11.00 + (weight_kg - 2) * 1.20
        elif weight_kg <= 30:
            base_rate = 20.60 + (weight_kg - 10) * 0.75
        else:
            base_rate = 35.60 + (weight_kg - 30) * 0.50
    elif carrier == "dhl":
        base_rate = 6.00 + weight_kg * 1.10
    else:
        base_rate = 5.00 + weight_kg * 0.95

    # Country-zone surcharge
    domestic_countries = {"US", "CA", "MX"}
    eu_countries = {"DE", "FR", "IT", "ES", "NL", "BE", "PL", "SE"}
    if destination_country in domestic_countries:
        zone_surcharge = 0.0
    elif destination_country in eu_countries:
        zone_surcharge = base_rate * 0.25
        surcharges.append({"eu_zone": zone_surcharge})
    elif destination_country in {"AU", "NZ", "JP", "SG"}:
        zone_surcharge = base_rate * 0.45
        surcharges.append({"pacific_zone": zone_surcharge})
    else:
        zone_surcharge = base_rate * 0.60
        surcharges.append({"remote_zone": zone_surcharge})

    total = base_rate + zone_surcharge

    if express:
        express_fee = total * 0.40
        surcharges.append({"express": express_fee})
        total += express_fee

    if fragile:
        fragile_fee = max(2.50, total * 0.08)
        surcharges.append({"fragile_handling": fragile_fee})
        total += fragile_fee

    if insurance_value > 0:
        insurance_fee = max(1.00, insurance_value * 0.015)
        surcharges.append({"insurance": insurance_fee})
        total += insurance_fee

    discount = 0.0
    if promo_code == "SHIP10":
        discount = total * 0.10
    elif promo_code == "SHIP20":
        discount = total * 0.20
    elif promo_code == "FLAT5":
        discount = min(5.00, total)

    total = max(0.0, total - discount)

    return {
        "carrier": carrier,
        "destination": destination_country,
        "weight_kg": weight_kg,
        "base_rate": round(base_rate, 2),
        "surcharges": surcharges,
        "discount": round(discount, 2),
        "total": round(total, 2),
        "currency": "USD",
    }


# ---------------------------------------------------------------------------
# Semantic duplicate of shared_utils.validate_form_fields
# ---------------------------------------------------------------------------

def validate_payment_fields(
    form_data: dict[str, Any],
    required_fields: list[str],
    strict: bool = False,
) -> dict[str, Any]:
    """
    Validate a payment form's fields against a required-field list.

    Returns a dict with:
        valid  — True when all required fields are present and non-empty
        errors — per-field error messages for any failing fields
        data   — cleaned copy with strings stripped of surrounding whitespace

    When strict is True, any extra key not in required_fields is flagged.
    """
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}

    for key, value in form_data.items():
        if isinstance(value, str):
            stripped = value.strip()
            cleaned[key] = stripped if stripped else None
        else:
            cleaned[key] = value

    for field in required_fields:
        if field not in cleaned:
            errors[field] = "This field is required."
        elif cleaned[field] is None or cleaned[field] == "":
            errors[field] = "This field must not be empty."

    if strict:
        required_set = set(required_fields)
        for key in form_data:
            if key not in required_set:
                errors[key] = "Unexpected field not allowed."

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "data": cleaned,
    }


# ---------------------------------------------------------------------------
# Semantic duplicate of shared_utils.paginate_query_results
# ---------------------------------------------------------------------------

def paginate_transaction_results(
    items: list[Any],
    page: int,
    page_size: int,
    transform_fn: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """
    Paginate a list of transaction records for display.

    Returns current page items (optionally transformed), pagination metadata
    including total_items, total_pages, has_next, and has_prev.
    Page numbers are 1-indexed; page_size defaults to 10 if < 1.
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
    page_slice = items[start:end]

    if transform_fn is not None:
        page_slice = [transform_fn(record) for record in page_slice]

    return {
        "items": page_slice,
        "page": page,
        "page_size": page_size,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
