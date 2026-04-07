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
    queue="ingestion",
    name="apps.ingestion.tasks.ingest_repository",
)
def ingest_repository(self, repo_id: str):
    """
    Celery entry point: walk the full git history for a repository.

    Delegates all logic to engine.ingest_repository so the engine
    can be tested independently of Celery.
    """
    from apps.ingestion.engine import ingest_repository as run_ingestion
    from apps.ingestion.models import FailedTask
    from apps.repositories.models import Repository

    logger.info("ingest_task_started", repo_id=repo_id, task_id=self.request.id)

    try:
        summary = run_ingestion(repo_id=repo_id, task_id=self.request.id or "")
        logger.info("ingest_task_done", repo_id=repo_id, **summary)
        return summary
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                repo = Repository.objects.get(id=repo_id)
                FailedTask.objects.create(
                    repo=repo,
                    task_name="apps.ingestion.tasks.ingest_repository",
                    task_id=self.request.id or "",
                    error_message=str(exc),
                    payload={"repo_id": repo_id},
                    retry_count=self.request.retries,
                )
                logger.error(
                    "ingest_task_dead_lettered",
                    repo_id=repo_id,
                    error=str(exc),
                    retries=self.request.retries,
                )
            except Exception as inner:
                logger.error(
                    "ingest_task_dead_letter_failed",
                    repo_id=repo_id,
                    error=str(inner),
                )
        raise
