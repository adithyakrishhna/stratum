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
def ingest_repository(self, repo_id: str, user_id: str = ""):
    """
    Celery entry point: walk the full git history for a repository.

    Args:
        repo_id:  Stratum Repository UUID string
        user_id:  Stratum user ID string — used to release the rate-limit
                  slot on completion. Passed by trigger_analysis view.
                  Empty string when triggered by webhook (no slot to release).
    """
    from apps.ingestion.engine import ingest_repository as run_ingestion
    from apps.ingestion.models import FailedTask
    from apps.repositories.models import Repository

    logger.info("ingest_task_started", repo_id=repo_id, task_id=self.request.id)

    try:
        summary = run_ingestion(repo_id=repo_id, task_id=self.request.id or "")
        logger.info("ingest_task_done", repo_id=repo_id, **summary)

        # Dispatch full DBSCAN rebuild per language — Stage 5 (Intelligence queue).
        # countdown=300: give embedding workers ~5 min to finish storing vectors
        # before DBSCAN tries to read them. Simple and effective without Celery chords.
        if summary.get("files_queued", 0) > 0:
            _dispatch_rebuild_clusters(repo_id)
            _dispatch_score_debt(repo_id)

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
    finally:
        # Release the analysis slot acquired by trigger_analysis view.
        # Only release if a user_id was provided (API-triggered, not webhook).
        if user_id:
            from apps.repositories.rate_limiter import release_analysis_slot
            release_analysis_slot(user_id)


def _dispatch_rebuild_clusters(repo_id: str) -> None:
    """
    Dispatch one rebuild_clusters task per language present in the repo.
    countdown=300 gives embedding workers ~5 min to finish storing vectors.
    Never raises — dispatch failure must not crash the ingestion task.
    """
    try:
        from apps.parsing.models import CodeChunk
        from apps.clustering.tasks import rebuild_clusters

        languages = (
            CodeChunk.objects
            .filter(repo_id=repo_id, embedding__isnull=False)
            .values_list('language', flat=True)
            .distinct()
        )

        for lang in languages:
            rebuild_clusters.apply_async(
                kwargs={"repo_id": repo_id, "language": lang},
                queue="intelligence",
                countdown=300,
            )
            logger.info(
                "rebuild_clusters_dispatched",
                repo_id=repo_id,
                language=lang,
                countdown_seconds=300,
            )
    except Exception as exc:
        logger.warning("rebuild_clusters_dispatch_failed", repo_id=repo_id, error=str(exc))


def _dispatch_score_debt(repo_id: str) -> None:
    """
    Dispatch score_repo_debt with countdown=360 — fires 1 minute after
    rebuild_clusters (countdown=300), giving clustering time to finish.
    Never raises.
    """
    try:
        from apps.debt.tasks import score_repo_debt
        score_repo_debt.apply_async(
            kwargs={"repo_id": repo_id},
            queue="intelligence",
            countdown=360,
        )
        logger.info("score_repo_debt_dispatched", repo_id=repo_id, countdown_seconds=360)
    except Exception as exc:
        logger.warning("score_repo_debt_dispatch_failed", repo_id=repo_id, error=str(exc))
