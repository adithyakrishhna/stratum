"""
Data processor module — intentionally contains security vulnerabilities
and code quality issues to test Stratum PR review detection.

Expected Stratum findings when this file is in a PR
----------------------------------------------------
Security:
  CRITICAL  Hardcoded secret key              line  18
  CRITICAL  SQL injection (format string)     search_records_by_field
  CRITICAL  SQL injection (concatenation)     bulk_delete_records
  HIGH      exec usage                        run_user_script

Rules (default thresholds):
  MEDIUM    MAX_FUNCTION_LINES   process_and_validate_records  (~60 lines > 50)
  HIGH      MAX_COMPLEXITY       process_and_validate_records  (complexity ~22 > 10)

Rules (only with stratum.yaml in cloned repo):
  HIGH      FORBIDDEN_IMPORT shelve  line 14

Duplicate detection note
------------------------
process_and_validate_records and validate_access_token (auth_service.py)
are both long validation-heavy functions. Whether duplicate detection fires
depends on the embedding service being available and existing code chunks
in the database from a prior analysis run of this repository.

DO NOT DEPLOY — testing file only.
"""
import shelve
import json
import time
import base64


# ── Hardcoded secret ──────────────────────────────────────────────────
# Triggers: HARDCODED_SECRET (critical)
SECRET_KEY = "internal_api_secret_xR9kP2mQ4nT7wY1v"


# ── SQL injection via .format() ───────────────────────────────────────
# Triggers: SQL_INJECTION (critical)
def search_records_by_field(field_name, field_value, cursor):
    query = "SELECT * FROM records WHERE {} = '{}'".format(field_name, field_value)
    cursor.execute(query)
    return cursor.fetchall()


# ── SQL injection via concatenation ──────────────────────────────────
# Triggers: SQL_INJECTION (critical)
def bulk_delete_records(record_ids, cursor):
    id_list = ",".join(str(i) for i in record_ids)
    query = "DELETE FROM records WHERE id IN (" + id_list + ")"
    cursor.execute(query)
    return cursor.rowcount


# ── exec() on user-supplied script ────────────────────────────────────
# Triggers: DANGEROUS_FUNCTION exec() (high)
def run_user_script(script_source, execution_context):
    exec(script_source, execution_context)


# ── Long + highly complex function ────────────────────────────────────
# Triggers:
#   MAX_FUNCTION_LINES  (medium) — ~60 lines > 50
#   MAX_COMPLEXITY      (high)   — complexity ~22 > 10
#
# Structure is intentionally similar to validate_access_token in
# auth_service.py for semantic duplicate detection testing.
# Both decode a payload, validate an ID, check expiry, and walk
# a list of permissions/scopes — similar vocabulary and structure.
def process_and_validate_records(payload_token, owner_id, required_permissions):
    """
    Process an incoming data payload and validate it against owner and permissions.

    This function is intentionally long (60+ lines) and has high cyclomatic
    complexity (22 branches) to test both MAX_FUNCTION_LINES and MAX_COMPLEXITY
    rule detection.

    It also serves as a semantic duplicate detection test: its structure
    parallels validate_access_token in auth_service.py (both decode a
    base64 payload, validate an owner/user ID, check expiry timestamps,
    and iterate over permission/scope lists with multi-level fallback logic).
    """
    if not payload_token:
        return {"processed": False, "reason": "Empty payload token"}

    if not isinstance(payload_token, str):
        return {"processed": False, "reason": "Payload must be a string"}

    if len(payload_token) < 16:
        return {"processed": False, "reason": "Payload token too short"}

    segments = payload_token.split(".")
    if len(segments) < 2:
        return {"processed": False, "reason": "Payload must have at least two segments"}

    header_seg, data_seg = segments[0], segments[1]
    if not header_seg or not data_seg:
        return {"processed": False, "reason": "Payload has empty segments"}

    try:
        padding = "=" * (4 - len(data_seg) % 4)
        raw_json = base64.b64decode(data_seg + padding).decode("utf-8")
        record_data = json.loads(raw_json)
    except (ValueError, Exception):
        return {"processed": False, "reason": "Failed to decode payload data"}

    record_owner = record_data.get("owner_id")
    if record_owner is None:
        return {"processed": False, "reason": "Payload missing owner_id"}

    if str(record_owner) != str(owner_id):
        return {"processed": False, "reason": "Owner ID mismatch — access denied"}

    created_at = record_data.get("created_at", 0)
    expires_at = record_data.get("expires_at", 0)

    if expires_at and expires_at < time.time():
        return {"processed": False, "reason": "Payload has expired"}

    if created_at and created_at > time.time():
        return {"processed": False, "reason": "Payload timestamp is in the future"}

    granted_permissions = record_data.get("permissions", [])
    if not isinstance(granted_permissions, list):
        return {"processed": False, "reason": "Permissions field must be a list"}

    for perm in required_permissions:
        if perm not in granted_permissions:
            if perm == "admin" and "superadmin" in granted_permissions:
                continue
            elif perm == "read" and "write" in granted_permissions:
                continue
            elif perm == "view" and "edit" in granted_permissions:
                continue
            else:
                return {"processed": False, "reason": f"Missing permission: {perm}"}

    record_type = record_data.get("type", "")
    if not record_type:
        return {"processed": False, "reason": "Record type not specified"}

    if record_type not in ("invoice", "order", "payment", "report"):
        return {"processed": False, "reason": f"Unknown record type: {record_type}"}

    status = record_data.get("status", "")
    if status == "cancelled":
        return {"processed": False, "reason": "Record is cancelled — skipping"}
    elif status == "archived":
        return {"processed": False, "reason": "Record is archived — skipping"}
    elif status not in ("pending", "active", "draft"):
        return {"processed": False, "reason": f"Unexpected record status: {status}"}

    return {
        "processed": True,
        "owner_id": owner_id,
        "record_type": record_type,
        "status": status,
        "permissions": granted_permissions,
    }


# ── Shelve-based cache (forbidden import test) ─────────────────────────
# Only flagged when stratum.yaml is loaded with forbidden_imports.python
def load_cached_config(cache_path, config_key):
    with shelve.open(cache_path) as db:
        return db.get(config_key, {})


def save_cached_config(cache_path, config_key, config_data):
    with shelve.open(cache_path) as db:
        db[config_key] = config_data
