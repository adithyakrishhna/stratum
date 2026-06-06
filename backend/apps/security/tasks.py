"""
Security scanning Celery task.

scan_file_security — runs all detectors on one file and stores results in
RuleViolation (for historical/commit-level analysis).

The PR review orchestrator (Phase 2, Feature 3) calls scanner.scan_file()
directly and stores results in PrFinding — it does not go through this task.
"""
import time

import structlog

from config.celery import app as celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    queue="parsing",
    name="apps.security.tasks.scan_file_security",
)
def scan_file_security(
    self,
    repo_id: str,
    commit_id: str,
    file_path: str,
    file_content: str,
    language: str,
) -> None:
    """
    Run security detection on a file and persist findings as RuleViolation records.

    Idempotent — uses get_or_create with (repo, commit, file_path, rule_name, line_number)
    as the natural key so re-running on the same input is safe.
    """
    from apps.security.scanner import scan_file
    from apps.rules.models import RuleViolation
    from apps.repositories.models import Repository
    from apps.ingestion.models import Commit

    start_time = time.monotonic()

    logger.info(
        "security_scan_started",
        repo_id=repo_id,
        commit_id=commit_id,
        file_path=file_path,
        language=language,
    )

    try:
        repo = Repository.objects.get(id=repo_id)
        commit = Commit.objects.get(id=commit_id)
    except (Repository.DoesNotExist, Commit.DoesNotExist) as exc:
        logger.warning(
            "security_scan_record_not_found",
            repo_id=repo_id,
            commit_id=commit_id,
            error=str(exc),
        )
        return

    findings = scan_file(file_path, file_content, language)

    if not findings:
        logger.info(
            "security_scan_done",
            repo_id=repo_id,
            file_path=file_path,
            findings=0,
            duration_ms=int((time.monotonic() - start_time) * 1000),
        )
        return

    # Principle 1: idempotency — get_or_create per unique (repo, commit, file, rule, line)
    created_count = 0
    for finding in findings:
        _, created = RuleViolation.objects.get_or_create(
            repo=repo,
            commit=commit,
            file_path=finding.file_path,
            rule_name=finding.detector,
            line_number=finding.line_number,
            defaults={
                "language": finding.language,
                "severity": finding.severity,
                "message": f"{finding.title} — {finding.description}",
            },
        )
        if created:
            created_count += 1

    duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "security_scan_done",
        repo_id=repo_id,
        file_path=file_path,
        language=language,
        findings_total=len(findings),
        findings_new=created_count,
        duration_ms=duration_ms,
    )
