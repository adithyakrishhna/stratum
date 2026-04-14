"""
Security anti-pattern detectors.

Each detector:
- Declares which languages it supports.
- Implements detect(file_path, content, language) → list[SecurityFinding].
- Is AST-aware where AST gives clear value (missing auth, decorator analysis).
- Falls back to regex for patterns where regex is reliable and precise.
- Never raises — errors are surfaced as log warnings in scanner.scan_file().
"""
import io
import math
import re
from abc import ABC, abstractmethod

import structlog

from apps.security.scanner import SecurityFinding

logger = structlog.get_logger(__name__)

_ALL = frozenset({"python", "javascript", "typescript", "tsx", "java", "go", "rust", "c", "cpp", "ruby", "php"})
_WEB = frozenset({"python", "javascript", "typescript", "tsx", "php", "ruby"})
_SQL = frozenset({"python", "java", "php", "ruby", "go"})


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BaseDetector(ABC):
    @property
    @abstractmethod
    def supported_languages(self) -> frozenset:
        ...

    def supports_language(self, language: str) -> bool:
        return language in self.supported_languages

    @abstractmethod
    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        ...

    def _finding(
        self, *,
        detector: str,
        severity: str,
        title: str,
        description: str,
        file_path: str,
        line_number: int,
        language: str,
        code_snippet: str = "",
    ) -> SecurityFinding:
        return SecurityFinding(
            detector=detector,
            severity=severity,
            title=title,
            description=description,
            file_path=file_path,
            line_number=line_number,
            language=language,
            code_snippet=code_snippet[:400],
        )


# ---------------------------------------------------------------------------
# Detector 1: Hardcoded Secrets
# ---------------------------------------------------------------------------

# Regex patterns: (compiled_pattern, human_label)
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*["\'][^"\']{6,}["\']'), "Hardcoded password"),
    (re.compile(r'(?i)(api_key|apikey|api[-_]key)\s*[:=]\s*["\'][^"\']{8,}["\']'), "Hardcoded API key"),
    (re.compile(r'(?i)(secret_key|secretkey|secret)\s*[:=]\s*["\'][^"\']{8,}["\']'), "Hardcoded secret key"),
    (re.compile(r'(?i)(auth_token|access_token|refresh_token)\s*[:=]\s*["\'][^"\']{8,}["\']'), "Hardcoded token"),
    (re.compile(r'(?i)(private_key|privatekey)\s*[:=]\s*["\'][^"\']{8,}["\']'), "Hardcoded private key"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "AWS Access Key ID"),
    (re.compile(r'(?i)aws_secret_access_key\s*[:=]\s*["\'][A-Za-z0-9/+=]{40}["\']'), "AWS Secret Access Key"),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), "GitHub Personal Access Token"),
    (re.compile(r'gho_[a-zA-Z0-9]{36}'), "GitHub OAuth Token"),
    (re.compile(r'sk-[a-zA-Z0-9]{48}'), "OpenAI API Key"),
    (re.compile(r'(?i)(database_url|db_url)\s*[:=]\s*["\'][^"\']*:[^"\']+@[^"\']+["\']'), "Database URL with credentials"),
]

# Skip these — they're placeholders, not real secrets
_PLACEHOLDER_PATTERN = re.compile(
    r'(?i)(example|placeholder|test|fake|dummy|todo|fixme|change[-_]?me|replace|your[-_]|<[A-Z_]+>|\$\{|\$[A-Z_]+)'
)

# High-entropy string patterns (candidates for secrets)
_HEX_STRING = re.compile(r'["\']([A-Fa-f0-9]{32,64})["\']')
_B64_STRING = re.compile(r'["\']([A-Za-z0-9+/]{40,}={0,2})["\']')
_ENTROPY_THRESHOLD = 4.5


def _shannon_entropy(data: str) -> float:
    if not data:
        return 0.0
    freq = {c: data.count(c) for c in set(data)}
    total = len(data)
    return -sum((count / total) * math.log2(count / total) for count in freq.values())


def _run_detect_secrets(content: str, file_path: str) -> list[tuple[int, str]]:
    """
    Run detect-secrets plugins on file content.
    Returns list of (line_number, description). Silently no-ops if unavailable.
    """
    try:
        from detect_secrets.plugins.high_entropy_strings import (
            HexHighEntropyString,
            Base64HighEntropyString,
        )
        from detect_secrets.plugins.keyword import KeywordDetector

        results = []
        plugins = [
            HexHighEntropyString(3.0),
            Base64HighEntropyString(4.5),
            KeywordDetector(),
        ]
        for plugin in plugins:
            file_obj = io.StringIO(content)
            for secret in plugin.analyze(file_obj, file_path):
                results.append((secret.line_number, f"Possible {secret.type}"))
        return results
    except Exception as exc:
        logger.debug("detect_secrets_plugin_error", error=str(exc))
        return []


class HardcodedSecretDetector(BaseDetector):
    """
    Detects hardcoded credentials, API keys, and high-entropy strings.
    Uses detect-secrets for entropy analysis + regex for explicit patterns.
    """

    supported_languages = _ALL

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        lines = content.splitlines()

        # Pass 1 — explicit regex patterns (line by line)
        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "<!--")):
                continue  # skip comment lines

            for pattern, label in _SECRET_PATTERNS:
                match = pattern.search(line)
                if match and not _PLACEHOLDER_PATTERN.search(match.group(0)):
                    findings.append(self._finding(
                        detector="HARDCODED_SECRET",
                        severity="critical",
                        title=f"{label} detected",
                        description=(
                            f"{label} appears to be hardcoded at line {line_num}. "
                            "Store credentials in environment variables, never in source code."
                        ),
                        file_path=file_path,
                        line_number=line_num,
                        language=language,
                        code_snippet=stripped[:200],
                    ))
                    break  # one finding per line max

        # Pass 2 — high-entropy strings (potential tokens/keys)
        for line_num, line in enumerate(lines, start=1):
            for hex_match in _HEX_STRING.finditer(line):
                candidate = hex_match.group(1)
                if _shannon_entropy(candidate) >= _ENTROPY_THRESHOLD:
                    if not _PLACEHOLDER_PATTERN.search(candidate):
                        findings.append(self._finding(
                            detector="HARDCODED_SECRET",
                            severity="high",
                            title="High-entropy string (possible secret)",
                            description=(
                                f"High-entropy hex string at line {line_num} may be a hardcoded secret or key. "
                                "Verify it is not a credential."
                            ),
                            file_path=file_path,
                            line_number=line_num,
                            language=language,
                            code_snippet=line.strip()[:200],
                        ))

        # Pass 3 — detect-secrets library (keyword + entropy plugins)
        seen_lines = {f.line_number for f in findings}
        for line_num, description in _run_detect_secrets(content, file_path):
            if line_num not in seen_lines:
                findings.append(self._finding(
                    detector="HARDCODED_SECRET",
                    severity="high",
                    title=description,
                    description=(
                        f"{description} at line {line_num}. "
                        "Verify no credentials are hardcoded in this file."
                    ),
                    file_path=file_path,
                    line_number=line_num,
                    language=language,
                    code_snippet=lines[line_num - 1].strip()[:200] if line_num <= len(lines) else "",
                ))

        return findings


# ---------------------------------------------------------------------------
# Detector 2: SQL Injection
# ---------------------------------------------------------------------------

_SQL_PATTERNS: dict[str, list[re.Pattern]] = {
    "python": [
        re.compile(r'(?i)(execute|executemany)\s*\(\s*[f"\'](SELECT|INSERT|UPDATE|DELETE|DROP)[^)]*\+'),
        re.compile(r'(?i)(execute|executemany)\s*\(\s*"[^"]*"\s*%\s*\('),
        re.compile(r'(?i)f["\'].*?\b(SELECT|INSERT|UPDATE|DELETE|DROP)\b.*?\{[^}]+\}'),
        re.compile(r'(?i)["\'].*?(SELECT|INSERT|UPDATE|DELETE|DROP).*["\']\.format\s*\('),
        re.compile(r'(?i)(sql|query)\s*\+=\s*["\']'),
        re.compile(r'(?i)["\'].*(SELECT|INSERT|UPDATE|DELETE|DROP).*["\']\s*\+\s*\w'),
    ],
    "java": [
        re.compile(r'(?i)(execute|executeQuery|executeUpdate)\s*\(\s*"[^"]*"\s*\+'),
        re.compile(r'(?i)(execute|executeQuery|executeUpdate)\s*\(\s*new\s+StringBuilder'),
        re.compile(r'(?i)String\s+\w*(sql|query|SQL|Query)\s*=\s*"[^"]*"\s*\+'),
    ],
    "php": [
        re.compile(r'(?i)(mysql_query|mysqli_query|query)\s*\(\s*["\'].*["\']\s*\.\s*\$'),
        re.compile(r'(?i)(mysql_query|mysqli_query|query)\s*\([^)]*\$_(GET|POST|REQUEST)'),
        re.compile(r'(?i)\$sql\s*=\s*["\'].*["\']\s*\.\s*\$'),
    ],
    "ruby": [
        re.compile(r'(?i)(execute|find_by_sql)\s*\(\s*["\'].*["\']\s*\+'),
        re.compile(r'(?i)(execute|find_by_sql)\s*\(\s*"[^"]*#\{'),
        re.compile(r'(?i)where\s*\(\s*"[^"]*#\{'),
        re.compile(r'(?i)where\s*\(\s*"[^"]*"\s*\+'),
    ],
    "go": [
        re.compile(r'(?i)(Query|Exec|QueryRow)\s*\(\s*fmt\.(Sprintf|Sprint)\s*\('),
        re.compile(r'(?i)(Query|Exec|QueryRow)\s*\(\s*"[^"]*"\s*\+'),
    ],
}


class SqlInjectionDetector(BaseDetector):
    supported_languages = _SQL

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        patterns = _SQL_PATTERNS.get(language, [])
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            for pattern in patterns:
                if pattern.search(line):
                    findings.append(self._finding(
                        detector="SQL_INJECTION",
                        severity="critical",
                        title="Potential SQL injection vulnerability",
                        description=(
                            f"Line {line_num} appears to construct a SQL query using string "
                            "concatenation or formatting with potentially unsanitized input. "
                            "Use parameterized queries or prepared statements instead."
                        ),
                        file_path=file_path,
                        line_number=line_num,
                        language=language,
                        code_snippet=line.strip()[:300],
                    ))
                    break  # one finding per line

        return findings


# ---------------------------------------------------------------------------
# Detector 3: Dangerous Functions
# ---------------------------------------------------------------------------

# (pattern, title, severity)
_DANGEROUS: dict[str, list[tuple[re.Pattern, str, str]]] = {
    "python": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'\bexec\s*\('), "Use of exec()", "high"),  # nosec
        (re.compile(r'\bpickle\s*\.\s*loads?\s*\('), "Insecure deserialization via pickle", "high"),
        (re.compile(r'\byaml\s*\.\s*load\s*\((?!.*Loader\s*=\s*yaml\.SafeLoader)(?!.*Loader\s*=\s*yaml\.FullLoader)'), "yaml.load() without SafeLoader", "high"),  # nosec
        (re.compile(r'\bmarshal\s*\.\s*loads?\s*\('), "Use of marshal.loads()", "high"),  # nosec
        (re.compile(r'\bos\s*\.\s*system\s*\('), "Use of os.system()", "medium"),
        (re.compile(r'\bsubprocess\s*\.\s*(call|run|Popen)\s*\([^)]*shell\s*=\s*True'), "subprocess with shell=True", "high"),
        (re.compile(r'\b__import__\s*\('), "Dynamic __import__() call", "medium"),
    ],
    "javascript": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'\bnew\s+Function\s*\('), "Use of new Function()", "high"),
        (re.compile(r'\bdocument\.write\s*\('), "Use of document.write()", "medium"),
        (re.compile(r'\.innerHTML\s*=(?!=)'), "Direct innerHTML assignment", "medium"),
        (re.compile(r'\.outerHTML\s*=(?!=)'), "Direct outerHTML assignment", "medium"),
    ],
    "typescript": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'\bnew\s+Function\s*\('), "Use of new Function()", "high"),
        (re.compile(r'\.innerHTML\s*=(?!=)'), "Direct innerHTML assignment", "medium"),
        (re.compile(r'\.outerHTML\s*=(?!=)'), "Direct outerHTML assignment", "medium"),
    ],
    "tsx": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'dangerouslySetInnerHTML'), "dangerouslySetInnerHTML usage", "medium"),
    ],
    "php": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'\bassert\s*\(\s*["\']'), "assert() with string argument", "high"),
        (re.compile(r'\b(exec|system|shell_exec|passthru|popen)\s*\('), "Dangerous system call", "high"),
        (re.compile(r'\bunserialize\s*\('), "Insecure unserialize()", "high"),
        (re.compile(r'\bpreg_replace\s*\([^,]*\/e'), "preg_replace with /e modifier (code execution)", "critical"),
    ],
    "ruby": [
        (re.compile(r'\beval\s*\('), "Use of eval()", "critical"),  # nosec
        (re.compile(r'\binstance_eval\s*\('), "Use of instance_eval()", "high"),
        (re.compile(r'\bclass_eval\s*\('), "Use of class_eval()", "high"),
        (re.compile(r'\bmodule_eval\s*\('), "Use of module_eval()", "high"),
        (re.compile(r'\bsystem\s*\('), "Use of system()", "medium"),
        (re.compile(r'\bMarshal\.load\s*\('), "Insecure Marshal.load()", "high"),
    ],
    "java": [
        (re.compile(r'Runtime\.getRuntime\(\)\.exec\('), "Runtime.exec() — command injection risk", "high"),  # nosec
        (re.compile(r'\bnew\s+ProcessBuilder\s*\('), "ProcessBuilder — verify input sanitization", "medium"),
        (re.compile(r'\bObjectInputStream\b'), "ObjectInputStream — insecure Java deserialization", "high"),
        (re.compile(r'\.forName\s*\('), "Class.forName() dynamic class loading", "medium"),
    ],
    "go": [
        (re.compile(r'\bexec\.Command\s*\('), "exec.Command() — verify input is not user-controlled", "medium"),
    ],
    "c": [
        (re.compile(r'\bgets\s*\('), "Use of gets() — unsafe, use fgets() instead", "critical"),
        (re.compile(r'\bsprintf\s*\('), "sprintf() — prefer snprintf() with explicit size", "medium"),
        (re.compile(r'\bstrcpy\s*\('), "strcpy() — prefer strncpy() or strlcpy()", "medium"),
        (re.compile(r'\bstrcat\s*\('), "strcat() — prefer strncat()", "medium"),
        (re.compile(r'\bsystem\s*\('), "system() — command injection risk", "high"),
    ],
    "cpp": [
        (re.compile(r'\bgets\s*\('), "Use of gets() — unsafe, use fgets() instead", "critical"),
        (re.compile(r'\bsystem\s*\('), "system() — command injection risk", "high"),
        (re.compile(r'\bsprintf\s*\('), "sprintf() — prefer snprintf()", "medium"),
    ],
    "rust": [],  # Rust's type system prevents most of these at compile time
}

_DANGEROUS_DESCRIPTIONS = {
    "critical": (
        "This function allows execution of arbitrary code and is a common attack vector. "
        "Refactor to avoid it entirely."
    ),
    "high": (
        "This function has well-known security risks. "
        "Ensure input is strictly validated and consider a safer alternative."
    ),
    "medium": (
        "This function can be dangerous when used with unsanitized input. "
        "Review usage carefully."
    ),
}


class DangerousFunctionDetector(BaseDetector):
    supported_languages = _ALL

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        patterns = _DANGEROUS.get(language, [])
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "<!--")):
                continue
            if '# nosec' in line:  # inline suppression (follows bandit convention)
                continue
            for pattern, title, severity in patterns:
                if pattern.search(line):
                    findings.append(self._finding(
                        detector="DANGEROUS_FUNCTION",
                        severity=severity,
                        title=title,
                        description=_DANGEROUS_DESCRIPTIONS.get(severity, ""),
                        file_path=file_path,
                        line_number=line_num,
                        language=language,
                        code_snippet=stripped[:300],
                    ))
                    break

        return findings


# ---------------------------------------------------------------------------
# Detector 4: Missing Authentication on Endpoints (AST-aware, Python)
# ---------------------------------------------------------------------------

_ROUTE_DECORATORS = frozenset({
    "route", "get", "post", "put", "patch", "delete", "head",
    "api_view", "action",
})
_AUTH_DECORATORS = frozenset({
    "login_required", "auth_required", "jwt_required", "requires_auth",
    "permission_required", "token_required", "authenticate", "protected",
    "require_http_methods", "staff_member_required", "user_passes_test",
    "authentication_required",
})


def _extract_decorator_names(node) -> set[str]:
    """Extract identifier names from a decorated_definition node's decorators."""
    names: set[str] = set()
    for child in node.children:
        if child.type != "decorator":
            continue
        raw = child.text.decode("utf-8", errors="replace").lstrip("@")
        # @app.route(...) → parts = ["app", "route", ...]
        # @login_required → parts = ["login_required"]
        parts = re.split(r'[\s.(]', raw)
        names.update(p for p in parts if p)
    return names


class MissingAuthDetector(BaseDetector):
    """
    Detects route/endpoint functions that have no authentication decorator.
    Uses tree-sitter AST for reliable decorator analysis (Python only).
    """

    supported_languages = frozenset({"python"})

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        try:
            return self._detect_python(file_path, content)
        except Exception as exc:
            logger.debug("missing_auth_ast_error", file_path=file_path, error=str(exc))
            return []

    def _detect_python(self, file_path: str, content: str) -> list[SecurityFinding]:
        from apps.parsing.language_router import get_parser

        parser = get_parser("python")
        if not parser:
            return []

        tree = parser.parse(content.encode("utf-8", errors="replace"))
        findings: list[SecurityFinding] = []

        def walk(node):
            if node.type == "decorated_definition":
                dec_names = _extract_decorator_names(node)
                if dec_names & _ROUTE_DECORATORS:
                    if not (dec_names & _AUTH_DECORATORS):
                        func_name = "unknown"
                        func_line = node.start_point[0] + 1
                        for child in node.children:
                            if child.type in ("function_definition", "async_function_definition"):
                                for c in child.children:
                                    if c.type == "identifier":
                                        func_name = c.text.decode("utf-8", errors="replace")
                                        break
                                break
                        findings.append(self._finding(
                            detector="MISSING_AUTH",
                            severity="high",
                            title=f"Endpoint '{func_name}' has no authentication decorator",
                            description=(
                                f"Function '{func_name}' is exposed as an HTTP endpoint "
                                "but has no authentication/authorization decorator. "
                                "Add @login_required, @permission_required, or equivalent."
                            ),
                            file_path=file_path,
                            line_number=func_line,
                            language="python",
                        ))
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return findings


# ---------------------------------------------------------------------------
# Detector 5: Insecure Random Number Generation
# ---------------------------------------------------------------------------

_INSECURE_RANDOM: dict[str, list[tuple[re.Pattern, str]]] = {
    "python": [
        (
            re.compile(r'\brandom\s*\.\s*(random|randint|randrange|choice|choices|shuffle|uniform|sample)\s*\('),
            "random module is not cryptographically secure — use the secrets module for tokens, passwords, or keys",
        ),
    ],
    "javascript": [
        (
            re.compile(r'\bMath\.random\s*\('),
            "Math.random() is not cryptographically secure — use crypto.getRandomValues() or crypto.randomUUID()",
        ),
    ],
    "typescript": [
        (
            re.compile(r'\bMath\.random\s*\('),
            "Math.random() is not cryptographically secure — use crypto.getRandomValues() or crypto.randomUUID()",
        ),
    ],
    "tsx": [
        (
            re.compile(r'\bMath\.random\s*\('),
            "Math.random() is not cryptographically secure",
        ),
    ],
    "java": [
        (
            re.compile(r'\bnew\s+Random\s*\(\)'),
            "java.util.Random is not cryptographically secure — use java.security.SecureRandom",
        ),
    ],
    "php": [
        (
            re.compile(r'\b(rand|mt_rand|array_rand)\s*\('),
            "rand()/mt_rand() are not cryptographically secure — use random_bytes() or random_int()",
        ),
    ],
    "ruby": [
        (
            re.compile(r'\bRandom\s*\.\s*rand\s*\('),
            "Random.rand is not cryptographically secure — use SecureRandom",
        ),
        (
            re.compile(r'\brand\s*\('),
            "rand() is not cryptographically secure — use SecureRandom for security-sensitive values",
        ),
    ],
}


class InsecureRandomDetector(BaseDetector):
    supported_languages = frozenset(_INSECURE_RANDOM.keys())

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        patterns = _INSECURE_RANDOM.get(language, [])
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")):
                continue
            for pattern, description in patterns:
                if pattern.search(line):
                    findings.append(self._finding(
                        detector="INSECURE_RANDOM",
                        severity="medium",
                        title="Insecure random number generation",
                        description=description,
                        file_path=file_path,
                        line_number=line_num,
                        language=language,
                        code_snippet=stripped[:200],
                    ))
                    break

        return findings


# ---------------------------------------------------------------------------
# Detector 6: Open Redirect
# ---------------------------------------------------------------------------

_OPEN_REDIRECT: dict[str, list[re.Pattern]] = {
    "python": [
        # Django: redirect(request.GET.get('next')) etc.
        re.compile(r'redirect\s*\(\s*request\.(GET|POST|args|query_params)[\[.]'),
        re.compile(r'redirect\s*\(\s*request\.(GET|POST|args|query_params)\.get\s*\('),
        re.compile(r'HttpResponseRedirect\s*\(\s*request\.(GET|POST)'),
        # Flask
        re.compile(r'return\s+redirect\s*\(\s*request\.args'),
    ],
    "php": [
        re.compile(r'header\s*\(\s*["\']Location:.*\$_(GET|POST|REQUEST|SERVER)'),
        re.compile(r'header\s*\(\s*["\']Location:\s*["\']\s*\.\s*\$_(GET|POST|REQUEST)'),
    ],
    "javascript": [
        re.compile(r'res\.redirect\s*\(\s*req\.(query|params|body)'),
        re.compile(r'window\.location(?:\.href)?\s*=\s*(?:location\.search|new URLSearchParams|req\.|request\.)'),
    ],
    "typescript": [
        re.compile(r'res\.redirect\s*\(\s*req\.(query|params|body)'),
    ],
    "ruby": [
        re.compile(r'redirect_to\s+params\['),
        re.compile(r'redirect_to\s+request\.(params|query_parameters|GET)'),
    ],
}


class OpenRedirectDetector(BaseDetector):
    supported_languages = frozenset(_OPEN_REDIRECT.keys())

    def detect(self, file_path: str, content: str, language: str) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        patterns = _OPEN_REDIRECT.get(language, [])
        lines = content.splitlines()

        for line_num, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")):
                continue
            for pattern in patterns:
                if pattern.search(line):
                    findings.append(self._finding(
                        detector="OPEN_REDIRECT",
                        severity="high",
                        title="Potential open redirect vulnerability",
                        description=(
                            f"Line {line_num} redirects to a URL derived from user-supplied input "
                            "without validation. An attacker can redirect users to malicious sites. "
                            "Validate the redirect target against an allowlist of permitted URLs."
                        ),
                        file_path=file_path,
                        line_number=line_num,
                        language=language,
                        code_snippet=stripped[:300],
                    ))
                    break

        return findings
