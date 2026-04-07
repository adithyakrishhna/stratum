"""
Ingestion service interface.

Other modules (e.g. repositories, webhooks) call these functions to trigger
or query ingestion — they never import from engine.py or tasks.py directly.
"""

import structlog

logger = structlog.get_logger(__name__)


def trigger_ingestion(repo_id: str) -> str:
    """
    Queue a full repository ingestion task.

    Returns the Celery task ID.
    Raises ValueError if the repo does not exist.
    """
    from apps.repositories.models import Repository

    try:
        Repository.objects.get(id=repo_id)
    except Repository.DoesNotExist:
        raise ValueError(f"Repository {repo_id} does not exist")

    from apps.ingestion.tasks import ingest_repository
    result = ingest_repository.apply_async(
        args=[repo_id],
        queue="ingestion",
    )
    logger.info("ingestion_queued", repo_id=repo_id, task_id=result.id)
    return result.id
