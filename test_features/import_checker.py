"""
Import checker — validates module imports against a banned list.

This module is used to test Stratum's semantic duplicate detection.
The function below intentionally mirrors the structure of
_check_forbidden_imports in backend/apps/rules/evaluator.py.

DO NOT USE IN PRODUCTION.
"""
import re


# Per-language regex patterns to extract the imported module name.
# Mirrors _IMPORT_PATTERNS in backend/apps/rules/evaluator.py.
_LANG_IMPORT_PATTERNS = {
    "python": re.compile(
        r"^\s*(?:import|from)\s+([\w.]+)"
    ),
    "javascript": re.compile(
        r"""^\s*(?:import\s+|require\s*\(\s*)['"]([^'"]+)['"]"""
    ),
    "typescript": re.compile(
        r"""^\s*(?:import\s+|require\s*\(\s*)['"]([^'"]+)['"]"""
    ),
    "java": re.compile(
        r"^\s*import\s+([\w.]+)"
    ),
    "go": re.compile(
        r'^\s*"([^"]+)"'
    ),
    "ruby": re.compile(
        r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]"""
    ),
    "php": re.compile(
        r"""^\s*(?:use|require|include)\s+['"]?([^\s;'"(]+)"""
    ),
    "rust": re.compile(
        r"^\s*use\s+([\w:]+)"
    ),
}


def check_banned_imports(
    file_path: str,
    content: str,
    language: str,
    rules_config: dict,
) -> list[dict]:
    """
    Scan source code for imports of forbidden (banned) packages and
    return a list of violation dictionaries, one per offending import line.

    Deduplicates results so the same (banned_package, line_number) pair is
    never reported twice — important when one import line matches multiple
    patterns.

    Args:
        file_path:    Path to the file being scanned (used in violation output).
        content:      Raw source code of the file as a single string.
        language:     Language identifier, e.g. 'python', 'javascript'.
        rules_config: Parsed rules dict; expects a 'banned_imports' key whose
                      value is a dict mapping language → list[str].

    Returns:
        List of violation dicts with keys: rule_name, severity, message,
        line_number, file_path, language.
    """
    banned_map = rules_config.get("banned_imports", {})
    banned_list: list[str] = banned_map.get(language, [])
    if not banned_list:
        return []

    extractor = _LANG_IMPORT_PATTERNS.get(language)
    if not extractor:
        return []

    violations: list[dict] = []
    seen: set[tuple] = set()   # deduplicate (forbidden_pkg, line_num) pairs

    for line_num, line in enumerate(content.splitlines(), start=1):
        match = extractor.search(line)
        if not match:
            continue
        imported = match.group(1)

        for banned_pkg in banned_list:
            is_match = (
                imported == banned_pkg
                or imported.startswith(banned_pkg + ".")
                or imported.startswith(banned_pkg + "/")
                or imported.startswith(banned_pkg + ":")  # Rust use paths
            )
            if is_match and (banned_pkg, line_num) not in seen:
                seen.add((banned_pkg, line_num))
                violations.append({
                    "rule_name": "BANNED_IMPORT",
                    "severity": "high",
                    "message": (
                        f"Import of '{imported}' is forbidden for {language} "
                        f"(banned package: '{banned_pkg}'). "
                        "Replace with an approved alternative."
                    ),
                    "line_number": line_num,
                    "file_path": file_path,
                    "language": language,
                })

    return violations
