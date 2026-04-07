"""
Rule evaluator — checks CodeChunk objects and file content against
a loaded stratum.yaml config. Returns RuleViolationData dataclasses
(pure Python, no DB access). The Celery task decides where to persist.

Rules enforced
--------------
1. max_function_lines  — function/method line count vs configured limit
2. max_complexity      — cyclomatic complexity score vs configured limit
3. forbidden_imports   — file-level import scan for banned packages
4. naming_conventions  — snake_case / camelCase / PascalCase enforcement
"""
import re
from dataclasses import dataclass


@dataclass
class RuleViolationData:
    rule_name: str
    severity: str    # "high" / "medium" / "low"
    message: str
    line_number: int | None
    language: str
    file_path: str


# ---------------------------------------------------------------------------
# Naming convention patterns
# ---------------------------------------------------------------------------

_NAMING_PATTERNS: dict[str, re.Pattern] = {
    "snake_case": re.compile(r"^_?[a-z][a-z0-9_]*$"),
    "camelCase": re.compile(r"^[a-z][a-zA-Z0-9]*$"),
    "PascalCase": re.compile(r"^[A-Z][a-zA-Z0-9]*$"),
    "SCREAMING_SNAKE_CASE": re.compile(r"^[A-Z][A-Z0-9_]*$"),
}

# Skip these names — dunders, well-known framework methods, single-letter vars
_SKIP_NAMES: frozenset = frozenset({
    "__init__", "__str__", "__repr__", "__len__", "__eq__", "__hash__",
    "__new__", "__del__", "__enter__", "__exit__", "__iter__", "__next__",
    "__getitem__", "__setitem__", "__contains__", "__call__", "__main__",
    "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpTestData",
    "main", "run",
})

# ---------------------------------------------------------------------------
# Import extractors per language
# ---------------------------------------------------------------------------

_IMPORT_PATTERNS: dict[str, re.Pattern] = {
    "python":     re.compile(r"^\s*(?:import|from)\s+([\w.]+)"),
    "javascript": re.compile(r"""^\s*(?:import\s|require\s*\()\s*['"]([^'"]+)['"]"""),
    "typescript": re.compile(r"""^\s*(?:import\s|require\s*\()\s*['"]([^'"]+)['"]"""),
    "tsx":        re.compile(r"""^\s*(?:import\s|require\s*\()\s*['"]([^'"]+)['"]"""),
    "java":       re.compile(r"^\s*import\s+([\w.]+)"),
    "go":         re.compile(r'^\s*"([^"]+)"'),
    "rust":       re.compile(r"^\s*use\s+([\w:]+)"),
    "ruby":       re.compile(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]"""),
    "php":        re.compile(r"""^\s*(?:use|require|include)(?:_once)?\s+['"]?([^\s;'"(]+)"""),
    "c":          re.compile(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]"),
    "cpp":        re.compile(r"^\s*#include\s+[<\"]([^>\"]+)[>\"]"),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_chunk(chunk, config: dict) -> list[RuleViolationData]:
    """
    Check a single CodeChunk against the rule config.
    Returns list of violations (may be empty).
    """
    rules = config.get("rules", {})
    violations: list[RuleViolationData] = []
    violations.extend(_check_function_length(chunk, rules))
    violations.extend(_check_complexity(chunk, rules))
    violations.extend(_check_naming_convention(chunk, rules))
    return violations


def evaluate_file_imports(
    file_path: str,
    content: str,
    language: str,
    config: dict,
) -> list[RuleViolationData]:
    """
    Scan an entire file for forbidden imports.
    Import rules are file-level, not chunk-level.
    """
    rules = config.get("rules", {})
    return _check_forbidden_imports(file_path, content, language, rules)


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------

def _check_function_length(chunk, rules: dict) -> list[RuleViolationData]:
    if chunk.chunk_type not in ("function", "method"):
        return []

    max_lines = rules.get("max_function_lines", 50)
    length = chunk.end_line - chunk.start_line + 1

    if length <= max_lines:
        return []

    return [RuleViolationData(
        rule_name="MAX_FUNCTION_LINES",
        severity="medium",
        message=(
            f"Function '{chunk.chunk_name}' is {length} lines "
            f"(max: {max_lines}). Break it into smaller, focused functions."
        ),
        line_number=chunk.start_line,
        language=chunk.language,
        file_path=chunk.file_path,
    )]


def _check_complexity(chunk, rules: dict) -> list[RuleViolationData]:
    if chunk.chunk_type not in ("function", "method"):
        return []

    max_complexity = rules.get("max_complexity", 10)
    score = int(chunk.complexity_score)

    if score <= max_complexity:
        return []

    severity = "high" if score > max_complexity * 2 else "medium"

    return [RuleViolationData(
        rule_name="MAX_COMPLEXITY",
        severity=severity,
        message=(
            f"Function '{chunk.chunk_name}' has cyclomatic complexity {score} "
            f"(max: {max_complexity}). Reduce branching to improve testability and readability."
        ),
        line_number=chunk.start_line,
        language=chunk.language,
        file_path=chunk.file_path,
    )]


def _check_naming_convention(chunk, rules: dict) -> list[RuleViolationData]:
    conventions = rules.get("naming_conventions", {})
    convention = conventions.get(chunk.language)
    if not convention:
        return []

    name = chunk.chunk_name
    # Skip magic methods, well-known framework names, and private dunders
    if name in _SKIP_NAMES or name.startswith("__"):
        return []

    pattern = _NAMING_PATTERNS.get(convention)
    if not pattern:
        return []

    if pattern.match(name):
        return []

    return [RuleViolationData(
        rule_name="NAMING_CONVENTION",
        severity="low",
        message=(
            f"'{name}' does not follow the {convention} naming convention "
            f"required for {chunk.language} in stratum.yaml."
        ),
        line_number=chunk.start_line,
        language=chunk.language,
        file_path=chunk.file_path,
    )]


def _check_forbidden_imports(
    file_path: str,
    content: str,
    language: str,
    rules: dict,
) -> list[RuleViolationData]:
    forbidden_map = rules.get("forbidden_imports", {})
    forbidden_list: list[str] = forbidden_map.get(language, [])
    if not forbidden_list:
        return []

    extractor = _IMPORT_PATTERNS.get(language)
    if not extractor:
        return []

    violations: list[RuleViolationData] = []
    seen: set[tuple] = set()  # deduplicate (package, line) pairs

    for line_num, line in enumerate(content.splitlines(), start=1):
        match = extractor.search(line)
        if not match:
            continue
        imported = match.group(1)

        for forbidden_pkg in forbidden_list:
            is_match = (
                imported == forbidden_pkg
                or imported.startswith(forbidden_pkg + ".")
                or imported.startswith(forbidden_pkg + "/")
                or imported.startswith(forbidden_pkg + ":")  # Rust use paths
            )
            if is_match and (forbidden_pkg, line_num) not in seen:
                seen.add((forbidden_pkg, line_num))
                violations.append(RuleViolationData(
                    rule_name="FORBIDDEN_IMPORT",
                    severity="high",
                    message=(
                        f"Import of '{imported}' is forbidden for {language} "
                        f"by stratum.yaml (forbidden: '{forbidden_pkg}')."
                    ),
                    line_number=line_num,
                    language=language,
                    file_path=file_path,
                ))

    return violations
