"""
PR Review Celery tasks — run on the dedicated pr_priority queue.

The pr_priority queue has 2 workers and is never shared with ingestion
load, guaranteeing PR reviews complete within 60 seconds even when a
full history analysis is running in parallel.
"""
import time

import structlog

from config.celery import app as celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="apps.pr_review.tasks.review_pull_request",
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    queue="pr_priority",
)
def review_pull_request(
    self,
    repo_id: str,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    pr_data: dict,
) -> None:
    """
    Full PR review pipeline: fetch files → detect issues → post GitHub comments.

    This task is the single entry point for all PR analysis. It delegates
    to the orchestrator which handles all analysis passes and GitHub posting.

    Args:
        repo_id:         Stratum Repository UUID string
        installation_id: GitHub App installation ID
        repo_full_name:  "owner/repo" string  (e.g. "acme/backend")
        pr_number:       GitHub PR number (integer)
        pr_data:         Raw pull_request object from GitHub webhook payload
    """
    start_ts = time.monotonic()

    logger.info(
        "review_task_started",
        repo_id=repo_id,
        repo=repo_full_name,
        pr_number=pr_number,
        task_id=self.request.id,
    )

    # Write pipeline_events record — stage start (Principle 4)
    _record_pipeline_event(
        repo_id=repo_id,
        task_id=self.request.id or "",
        stage="pr_review",
        status="started",
    )

    try:
        from apps.pr_review.orchestrator import run_pr_review

        run_pr_review(
            repo_id=repo_id,
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            pr_data=pr_data,
        )

        elapsed_ms = int((time.monotonic() - start_ts) * 1000)
        logger.info(
            "review_task_complete",
            repo_id=repo_id,
            repo=repo_full_name,
            pr_number=pr_number,
            duration_ms=elapsed_ms,
        )

        _record_pipeline_event(
            repo_id=repo_id,
            task_id=self.request.id or "",
            stage="pr_review",
            status="completed",
            duration_ms=elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_ts) * 1000)
        logger.error(
            "review_task_failed",
            repo_id=repo_id,
            repo=repo_full_name,
            pr_number=pr_number,
            error=str(exc),
            duration_ms=elapsed_ms,
        )

        _record_pipeline_event(
            repo_id=repo_id,
            task_id=self.request.id or "",
            stage="pr_review",
            status="failed",
            duration_ms=elapsed_ms,
            error_message=str(exc),
        )

        # On final retry exhaustion — record in failed_tasks for dashboard visibility
        if self.request.retries >= self.max_retries:
            _record_failed_task(
                repo_id=repo_id,
                task_id=self.request.id or "",
                error=str(exc),
                pr_number=pr_number,
                repo_full_name=repo_full_name,
            )

        raise  # triggers autoretry


# ---------------------------------------------------------------------------
# Observability helpers (Principle 4)
# ---------------------------------------------------------------------------

def _record_pipeline_event(
    repo_id: str,
    task_id: str,
    stage: str,
    status: str,
    duration_ms: int = 0,
    error_message: str = "",
    items_processed: int = 0,
) -> None:
    """Write a pipeline_events row — fire and forget, never raises."""
    try:
        from apps.dashboard.models import PipelineEvent

        PipelineEvent.objects.create(
            repo_id=repo_id,
            task_id=task_id,
            stage=stage,
            status=status,
            items_processed=items_processed,
            duration_ms=duration_ms,
            error_message=error_message,
        )
    except Exception as exc:
        logger.warning("pipeline_event_write_failed", error=str(exc))


def _record_failed_task(
    repo_id: str,
    task_id: str,
    error: str,
    pr_number: int,
    repo_full_name: str,
) -> None:
    """Record permanently failed task in failed_tasks table."""
    try:
        from apps.dashboard.models import FailedTask

        FailedTask.objects.create(
            repo_id=repo_id,
            task_name="apps.pr_review.tasks.review_pull_request",
            task_id=task_id,
            error_message=error,
            payload={
                "pr_number": pr_number,
                "repo_full_name": repo_full_name,
            },
            retry_count=3,
        )
    except Exception as exc:
        logger.warning("failed_task_write_failed", error=str(exc))
