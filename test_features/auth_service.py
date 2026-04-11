"""
Authentication service — intentionally contains security vulnerabilities
and code quality issues to test Stratum PR review detection.

Expected Stratum findings when this file is in a PR
----------------------------------------------------
Security (no stratum.yaml needed):
  CRITICAL  Hardcoded API key          line  12
  CRITICAL  Hardcoded secret key       line  13
  CRITICAL  Database URL with creds    line  14
  HIGH      Missing auth decorator     get_admin_dashboard
  CRITICAL  SQL injection (concat)     find_user_by_name
  CRITICAL  SQL injection (f-string)   authenticate_user
  CRITICAL  eval usage                 execute_dynamic_filter
  HIGH      pickle.loads deserialization  authenticate_user
  MEDIUM    Insecure random (token)    generate_password_reset_token
  MEDIUM    Insecure random (session)  _create_session

Rules (default thresholds — no stratum.yaml required):
  MEDIUM    MAX_FUNCTION_LINES         authenticate_user  (~67 lines > 50)
  HIGH      MAX_COMPLEXITY             authenticate_user  (complexity ~21 > 10)
  MEDIUM    MAX_COMPLEXITY             validate_access_token (complexity ~17 > 10)

Rules (only fire when stratum.yaml is in the cloned repo):
  HIGH      FORBIDDEN_IMPORT pickle    line  17
  LOW       NAMING_CONVENTION          processUserRegistration (camelCase)

DO NOT DEPLOY — testing file only.
"""
import pickle
import random
import base64
import json
import time


# ── Hardcoded credentials ──────────────────────────────────────────────
# Triggers: HARDCODED_SECRET (critical) for all three lines
API_KEY = "sk_live_xK9mP2nR4qT7wY1vZ3uA8bC6dEf"
SECRET_KEY = "jwt_signing_secret_v2_production_2024_do_not_share"
DATABASE_URL = "postgresql://admin:Str0ngP@ss2024@db.prod.internal:5432/appdb"


# ── Missing auth on admin endpoint ────────────────────────────────────
# Triggers: MISSING_AUTH (high) — route decorator present, no @login_required
@app.route('/api/admin/dashboard')
def get_admin_dashboard():
    stats = {
        "total_users": 1500,
        "active_sessions": 42,
        "failed_logins_24h": 7,
    }
    return JsonResponse(stats)


# ── SQL injection via string concatenation ────────────────────────────
# Triggers: SQL_INJECTION (critical)
def find_user_by_name(username, cursor):
    query = "SELECT * FROM users WHERE username = '" + username + "'"
    cursor.execute(query)
    return cursor.fetchone()


# ── eval() on user-supplied expression ────────────────────────────────
# Triggers: DANGEROUS_FUNCTION eval() (critical)
def execute_dynamic_filter(filter_expr, context_vars):
    return eval(filter_expr, {"__builtins__": {}}, context_vars)


# ── Insecure random for security-sensitive token ───────────────────────
# Triggers: INSECURE_RANDOM (medium) — use secrets.token_urlsafe() instead
def generate_password_reset_token(user_id):
    token = str(random.randint(10000000, 99999999))
    return f"reset_{user_id}_{token}"


# ── Naming convention violation ────────────────────────────────────────
# Triggers: NAMING_CONVENTION (low) — camelCase function in Python file
# Only fires when stratum.yaml with naming_conventions.python = snake_case
# is present in the cloned repo directory.
def processUserRegistration(email, username, password):
    if not email or not username or not password:
        return None
    token = generate_password_reset_token(0)
    return {"email": email, "username": username, "verification_token": token}


# ── Long function + high complexity ────────────────────────────────────
# Triggers:
#   MAX_FUNCTION_LINES  (medium) — 67 lines, default max 50
#   MAX_COMPLEXITY      (high)   — complexity 21, default max 10
#   DANGEROUS_FUNCTION  (high)   — pickle.loads inside body
#   SQL_INJECTION       (critical) — f-string query inside body
def authenticate_user(username, password, ip_address, device_fingerprint, require_mfa=False):
    """
    Authenticate a user against the database with multi-step validation.

    Intentionally oversized and overcomplicated to trigger both
    MAX_FUNCTION_LINES and MAX_COMPLEXITY rule violations. Also contains
    an embedded SQL injection (f-string) and insecure pickle.loads usage.
    """
    if not username or not password or not ip_address:
        return {"success": False, "error": "All fields are required"}

    if len(username) < 3 or len(username) > 128:
        return {"success": False, "error": "Invalid username length"}

    if len(password) < 8:
        return {"success": False, "error": "Password must be at least 8 characters"}

    # SQL injection: f-string embeds username directly into query
    sql = f"SELECT * FROM users WHERE username = '{username}' AND is_active = 1"
    user_record = None  # placeholder: would be cursor.execute(sql).fetchone()

    if not user_record:
        return {"success": False, "error": "User not found"}

    if user_record.get("is_locked") or user_record.get("is_suspended"):
        return {"success": False, "error": "Account is locked or suspended"}

    if user_record.get("is_deleted"):
        return {"success": False, "error": "Account has been removed"}

    stored_hash = user_record.get("password_hash", "")
    if not stored_hash:
        return {"success": False, "error": "Account has no password configured"}

    # Insecure deserialization: pickle.loads on DB-stored data
    prefs_blob = user_record.get("preferences_blob")
    if prefs_blob:
        user_prefs = pickle.loads(prefs_blob)
    else:
        user_prefs = {}

    if not _verify_password_hash(password, stored_hash):
        attempts = _increment_failed_login(username)
        if attempts >= 5:
            _lock_user_account(username)
            return {"success": False, "error": "Account locked after too many failed attempts"}
        return {"success": False, "error": "Invalid credentials"}

    if ip_address:
        if _is_ip_blacklisted(ip_address):
            return {"success": False, "error": "Access denied from this network"}

    if device_fingerprint:
        device_type = device_fingerprint.get("type", "")
        if device_type == "mobile" and not device_fingerprint.get("trusted"):
            return {"success": False, "error": "Untrusted mobile device"}
        elif device_type == "unknown":
            return {"success": False, "error": "Unrecognized device type"}

    if require_mfa:
        if not user_record.get("mfa_enabled"):
            return {"success": False, "error": "MFA is not configured for this account"}
        challenge = _generate_mfa_challenge(user_record["id"])
        return {"success": False, "pending_mfa": True, "challenge": challenge}

    session = _create_session(user_record["id"], ip_address)
    return {"success": True, "session_token": session, "user_id": user_record["id"]}


# ── High complexity token validator ────────────────────────────────────
# Triggers: MAX_COMPLEXITY (medium) — complexity 17, default max 10
# Also embeddable (≥20 lines, complexity ≥3) for duplicate detection test.
def validate_access_token(token, expected_user_id, required_scopes):
    """
    Validate a JWT-style access token against expected user and scopes.

    Has 16 branching constructs → complexity score 17 (max: 10).
    Function length and structure are also suitable for the semantic
    duplicate detection feature test (requires embedding service running).
    """
    if not token:
        return {"valid": False, "reason": "No token provided"}
    if len(token) < 20:
        return {"valid": False, "reason": "Token too short"}

    parts = token.split(".")
    if len(parts) != 3:
        return {"valid": False, "reason": "Token must have exactly three segments"}

    header_b64, payload_b64, signature = parts
    if not header_b64 or not payload_b64 or not signature:
        return {"valid": False, "reason": "Token has empty segments"}

    try:
        padding = "=" * (4 - len(payload_b64) % 4)
        decoded = base64.b64decode(payload_b64 + padding).decode("utf-8")
        claims = json.loads(decoded)
    except Exception:
        return {"valid": False, "reason": "Failed to decode token payload"}

    if claims.get("sub") != str(expected_user_id):
        return {"valid": False, "reason": "Token subject does not match user ID"}

    if claims.get("exp", 0) < time.time():
        return {"valid": False, "reason": "Token has expired"}

    granted_scopes = claims.get("scopes", [])
    for scope in required_scopes:
        if scope not in granted_scopes:
            if scope == "admin" and "superadmin" in granted_scopes:
                continue
            elif scope == "read" and "write" in granted_scopes:
                continue
            else:
                return {"valid": False, "reason": f"Missing required scope: {scope}"}

    if len(signature) < 8:
        return {"valid": False, "reason": "Signature too short"}

    return {"valid": True, "user_id": expected_user_id, "scopes": granted_scopes}


# ── Internal helpers ───────────────────────────────────────────────────

def _verify_password_hash(password, stored_hash):
    return True


def _increment_failed_login(username):
    return 0


def _lock_user_account(username):
    pass


def _is_ip_blacklisted(ip):
    return False


def _generate_mfa_challenge(user_id):
    return random.randint(100000, 999999)


def _create_session(user_id, ip_address):
    return f"session_{user_id}_{random.randint(1000, 9999)}"
