"""
Security scanner orchestrator.

scan_file() is a pure function — no DB access — that runs every applicable
detector on a file and returns SecurityFinding dataclasses. Callers decide
where to persist the results (PrFinding for PR review, RuleViolation for
historical analysis).
"""
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SecurityFinding:
    detector: str        # "HARDCODED_SECRET", "SQL_INJECTION", etc.
    severity: str        # "critical" / "high" / "medium" / "low"
    title: str
    description: str
    file_path: str
    line_number: int
    language: str
    code_snippet: str = field(default="")


def scan_file(file_path: str, content: str, language: str) -> list[SecurityFinding]:
    """
    Run all applicable security detectors on a single file.

    Returns a list of SecurityFinding dataclasses, sorted critical-first.
    Never raises — detector errors are caught and logged individually so a
    single bad detector never silences the others.
    """
    from apps.security.detectors import (
        HardcodedSecretDetector,
        SqlInjectionDetector,
        DangerousFunctionDetector,
        MissingAuthDetector,
        InsecureRandomDetector,
        OpenRedirectDetector,
    )

    detectors = [
        HardcodedSecretDetector(),
        SqlInjectionDetector(),
        DangerousFunctionDetector(),
        MissingAuthDetector(),
        InsecureRandomDetector(),
        OpenRedirectDetector(),
    ]

    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    findings: list[SecurityFinding] = []
    for detector in detectors:
        if not detector.supports_language(language):
            continue
        try:
            results = detector.detect(file_path, content, language)
            findings.extend(results)
        except Exception as exc:
            logger.warning(
                "detector_error",
                detector=detector.__class__.__name__,
                file_path=file_path,
                language=language,
                error=str(exc),
            )

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))
    return findings
