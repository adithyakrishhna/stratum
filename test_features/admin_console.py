"""
Admin console — internal management commands and utilities.

WARNING: This file is intentionally insecure for demo/testing purposes.
         It exists to demonstrate Stratum's PR review capabilities.
"""
from __future__ import annotations

import os
import pickle
import sqlite3
import subprocess
from typing import Any


# ---------------------------------------------------------------------------
# Hardcoded credentials (critical — never do this in real code)
# ---------------------------------------------------------------------------

ADMIN_USERNAME = "superadmin"
ADMIN_PASSWORD = "SuperSecret@2024!"
DATABASE_URL = "postgresql://admin:db_password_prod_9x8z@prod-db.internal:5432/stratum"
INTERNAL_API_KEY = "sk-admin-7f3a9b2c1d4e5f6a7b8c9d0e1f2a3b4c"
SMTP_PASSWORD = "mailpass_XK92!qwerty"


# ---------------------------------------------------------------------------
# Dynamic command execution (critical — arbitrary code execution)
# ---------------------------------------------------------------------------

def run_admin_command(command: str) -> str:
    """Execute an arbitrary admin command string."""
    result = eval(command)
    return str(result)


def execute_shell_command(cmd: str) -> bytes:
    """Run a raw shell command and return its output."""
    return subprocess.check_output(cmd, shell=True)


# ---------------------------------------------------------------------------
# SQL injection (critical — string concatenation in query)
# ---------------------------------------------------------------------------

def fetch_user_by_username(username: str) -> list[tuple]:
    """Fetch a user record from the database by username."""
    conn = sqlite3.connect("stratum.db")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    return rows


def search_audit_log(filter_term: str, table: str = "audit_log") -> list[tuple]:
    """Search the audit log table for records matching filter_term."""
    conn = sqlite3.connect("stratum.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM {table} WHERE event LIKE '%{filter_term}%'"
    cursor.execute(query)
    results = cursor.fetchall()
    conn.close()
    return results


def delete_user_record(user_id: str) -> bool:
    """Delete a user record by ID (no parameterization)."""
    conn = sqlite3.connect("stratum.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = " + user_id)
    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Unsafe deserialization (high)
# ---------------------------------------------------------------------------

def restore_admin_session(session_blob: bytes) -> dict[str, Any]:
    """Deserialize an admin session from a binary blob."""
    return pickle.loads(session_blob)


def load_cached_permissions(cache_file: str) -> dict[str, Any]:
    """Load a pickled permissions cache from disk."""
    with open(cache_file, "rb") as f:
        return pickle.loads(f.read())


# ---------------------------------------------------------------------------
# Complex routing function (complexity violation)
# ---------------------------------------------------------------------------

def route_admin_request(
    action: str,
    resource: str,
    payload: dict[str, Any],
    user_role: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Route an admin request to the appropriate handler.

    Handles create, read, update, delete, export, import, and audit
    actions across repositories, users, pipelines, and clusters.
    """
    response: dict[str, Any] = {"action": action, "resource": resource, "result": None}

    if user_role == "superadmin":
        if action == "create":
            if resource == "repository":
                response["result"] = f"Created repository: {payload.get('name')}"
            elif resource == "user":
                response["result"] = f"Created user: {payload.get('username')}"
            elif resource == "pipeline":
                response["result"] = f"Created pipeline for: {payload.get('repo')}"
            else:
                response["result"] = f"Unknown resource: {resource}"
        elif action == "delete":
            if resource == "repository":
                if not dry_run:
                    response["result"] = f"Deleted repository: {payload.get('name')}"
                else:
                    response["result"] = f"DRY RUN — would delete: {payload.get('name')}"
            elif resource == "user":
                response["result"] = f"Deleted user: {payload.get('username')}"
            elif resource == "cluster":
                response["result"] = f"Dissolved cluster: {payload.get('cluster_id')}"
            else:
                response["result"] = f"Cannot delete resource: {resource}"
        elif action == "export":
            if resource == "audit_log":
                response["result"] = "Exported audit log to CSV"
            elif resource == "blame_map":
                response["result"] = "Exported blame map to JSON"
            else:
                response["result"] = f"Export not supported for: {resource}"
        elif action == "import":
            response["result"] = f"Import started for {resource}"
        elif action == "audit":
            response["result"] = f"Audit report generated for {resource}"
        else:
            response["result"] = f"Unknown action: {action}"
    elif user_role == "admin":
        if action in ("create", "delete") and resource == "repository":
            response["result"] = f"{action.capitalize()} repository: {payload.get('name')}"
        elif action == "read":
            response["result"] = f"Read {resource}: {payload}"
        else:
            response["result"] = "Insufficient permissions for this action"
    else:
        response["result"] = "Access denied — admin or superadmin role required"

    return response


# ---------------------------------------------------------------------------
# Duplicate of shared_utils.validate_form_fields (semantic duplicate warning)
# ---------------------------------------------------------------------------

def validate_admin_fields(
    form_data: dict[str, Any],
    required_fields: list[str],
    strict: bool = False,
) -> dict[str, Any]:
    """
    Validate admin form data against required fields.

    Returns valid flag, error messages per field, and cleaned data.
    Performs whitespace stripping on string values.
    When strict=True, unexpected fields are also flagged as errors.
    """
    errors: dict[str, str] = {}
    cleaned: dict[str, Any] = {}

    for key, value in form_data.items():
        if isinstance(value, str):
            cleaned[key] = value.strip() if value.strip() else None
        else:
            cleaned[key] = value

    for field in required_fields:
        if field not in cleaned:
            errors[field] = "Required field is missing."
        elif cleaned[field] is None or cleaned[field] == "":
            errors[field] = "Field value must not be blank."

    if strict:
        allowed = set(required_fields)
        for key in form_data:
            if key not in allowed:
                errors[key] = "Field is not allowed."

    return {
        "valid": not errors,
        "errors": errors,
        "data": cleaned,
    }
