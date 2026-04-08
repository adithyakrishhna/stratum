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
    queue="intelligence",
    name="apps.blame.tasks.compute_blame",
)
def compute_blame(self, repo_id: str):
    """
    Compute BlameMap records for all unprocessed commits in a repository.

    Dispatched by ingest_repository with countdown=420 — fires after
    clustering (300s) and debt scoring (360s) have had time to complete.

    Incremental: only processes commits without an existing BlameMap.
    Safe to re-run — idempotent via bulk_create(ignore_conflicts=True).

    Args:
        repo_id: Repository UUID string
    """
    from apps.blame.services import compute_blame_for_repo
    from apps.ingestion.models import FailedTask
    from apps.repositories.models import Repository

    logger.info("compute_blame_started", repo_id=repo_id, task_id=self.request.id)

    try:
        summary = compute_blame_for_repo(
            repo_id=repo_id,
            task_id=self.request.id or "",
        )
        logger.info("compute_blame_done", repo_id=repo_id, **summary)
        return summary

    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                repo = Repository.objects.get(id=repo_id)
                FailedTask.objects.create(
                    repo=repo,
                    task_name="apps.blame.tasks.compute_blame",
                    task_id=self.request.id or "",
                    error_message=str(exc),
                    payload={"repo_id": repo_id},
                    retry_count=self.request.retries,
                )
            except Exception:
                pass
        raise
