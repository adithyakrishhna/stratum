"""
Rule enforcement Celery task.

enforce_rules_on_file — loads stratum.yaml config (Redis-cached), runs all
rule checks against a file's CodeChunk records + raw content, and stores
findings as RuleViolation records (idempotent via get_or_create).
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
    name="apps.rules.tasks.enforce_rules_on_file",
)
def enforce_rules_on_file(
    self,
    repo_id: str,
    commit_id: str,
    file_path: str,
    file_content: str,
    language: str,
) -> None:
    """
    Run all stratum.yaml rule checks on one file and store RuleViolation records.

    Steps:
      1. Load config via loader.load_rules() — Redis cache hit or disk read
      2. Check file-level forbidden imports
      3. Check chunk-level: length, complexity, naming (for already-parsed chunks)
      4. Bulk idempotent upsert into RuleViolation table
    """
    from apps.rules.loader import load_rules
    from apps.rules.evaluator import evaluate_chunk, evaluate_file_imports, RuleViolationData
    from apps.rules.models import RuleViolation
    from apps.parsing.models import CodeChunk
    from apps.repositories.models import Repository
    from apps.ingestion.models import Commit

    start_time = time.monotonic()

    logger.info(
        "rule_enforcement_started",
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
            "rule_enforcement_record_not_found",
            repo_id=repo_id,
            commit_id=commit_id,
            error=str(exc),
        )
        return

    # Load config — Redis cache hit in the common case (Optimization: Caching Strategy)
    config = load_rules(repo_id)

    all_violations: list[RuleViolationData] = []

    # 1. File-level: forbidden imports
    import_violations = evaluate_file_imports(file_path, file_content, language, config)
    all_violations.extend(import_violations)

    # 2. Chunk-level: length + complexity + naming
    # Chunks must already be created by the parsing task (this task runs after parsing)
    chunks = CodeChunk.objects.filter(
        repo_id=repo_id,
        commit_id=commit_id,
        file_path=file_path,
    )
    for chunk in chunks:
        all_violations.extend(evaluate_chunk(chunk, config))

    if not all_violations:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "rule_enforcement_done",
            repo_id=repo_id,
            file_path=file_path,
            violations=0,
            duration_ms=duration_ms,
        )
        return

    # 3. Idempotent bulk store — Principle 1: idempotency
    created_count = 0
    for v in all_violations:
        _, created = RuleViolation.objects.get_or_create(
            repo=repo,
            commit=commit,
            file_path=v.file_path,
            rule_name=v.rule_name,
            line_number=v.line_number,
            defaults={
                "language": v.language,
                "severity": v.severity,
                "message": v.message,
            },
        )
        if created:
            created_count += 1

    duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "rule_enforcement_done",
        repo_id=repo_id,
        file_path=file_path,
        language=language,
        violations_total=len(all_violations),
        violations_new=created_count,
        duration_ms=duration_ms,
    )
