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
    name="apps.debt.tasks.score_repo_debt",
)
def score_repo_debt(self, repo_id: str):
    """
    Compute debt scores for all unscored commits in a repository.

    Triggered by ingest_repository after ingestion + clustering have
    had time to complete (dispatched with countdown=360).

    Incremental: only processes commits without existing DebtScore records.
    Safe to re-run — get_or_create / ignore_conflicts throughout.

    Args:
        repo_id: Repository UUID string
    """
    from apps.debt.services import compute_debt_for_repo
    from apps.ingestion.models import FailedTask
    from apps.repositories.models import Repository

    logger.info("score_repo_debt_started", repo_id=repo_id, task_id=self.request.id)

    try:
        summary = compute_debt_for_repo(
            repo_id=repo_id,
            task_id=self.request.id or "",
        )
        logger.info("score_repo_debt_done", repo_id=repo_id, **summary)
        return summary

    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                repo = Repository.objects.get(id=repo_id)
                FailedTask.objects.create(
                    repo=repo,
                    task_name="apps.debt.tasks.score_repo_debt",
                    task_id=self.request.id or "",
                    error_message=str(exc),
                    payload={"repo_id": repo_id},
                    retry_count=self.request.retries,
                )
            except Exception:
                pass
        raise
