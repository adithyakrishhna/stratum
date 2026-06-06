"""
Celery tasks for semantic clustering.

Two tasks matching the two-speed design in services.py:

  cluster_new_chunks   — fast path, called by embed_chunks after embeddings stored
  rebuild_clusters     — slow path, full DBSCAN, called after ingestion batch completes
"""
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
    name="apps.clustering.tasks.cluster_new_chunks",
)
def cluster_new_chunks(self, repo_id: str, language: str, chunk_ids: list[str]):
    """
    Fast-path clustering: assign newly embedded chunks to existing clusters.

    Called by embed_chunks after bulk_update of embeddings.
    Handles 95% of new chunks without running DBSCAN (Optimization 8).

    Args:
        repo_id:   Repository UUID string
        language:  Language of the chunks (clustering is per-language)
        chunk_ids: List of CodeChunk UUID strings that were just embedded
    """
    from apps.clustering.services import assign_chunks_to_clusters

    logger.info(
        "cluster_new_chunks_started",
        repo_id=repo_id,
        language=language,
        chunk_count=len(chunk_ids),
    )

    created = assign_chunks_to_clusters(
        repo_id=repo_id,
        language=language,
        chunk_ids=chunk_ids,
    )

    logger.info(
        "cluster_new_chunks_done",
        repo_id=repo_id,
        language=language,
        memberships_created=created,
    )
    return {"memberships_created": created}


@celery_app.task(
    bind=True,
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    queue="intelligence",
    name="apps.clustering.tasks.rebuild_clusters",
)
def rebuild_clusters(self, repo_id: str, language: str):
    """
    Slow-path clustering: full DBSCAN re-clustering for a repo+language.

    Triggered by the ingestion engine after processing a batch of commits.
    Discovers new clusters, updates existing ones, flags spreading patterns.

    Design:
    - Runs per-language to keep numpy matrix manageable
    - Stable cluster IDs via centroid hash — never renumbers
    - max_retries=2 (shorter than normal — DBSCAN is idempotent but expensive)

    Args:
        repo_id:  Repository UUID string
        language: Language to cluster (one task per language)
    """
    from apps.clustering.services import run_full_clustering
    from apps.ingestion.models import FailedTask
    from apps.repositories.models import Repository

    logger.info(
        "rebuild_clusters_started",
        repo_id=repo_id,
        language=language,
        task_id=self.request.id,
    )

    try:
        summary = run_full_clustering(
            repo_id=repo_id,
            language=language,
            task_id=self.request.id or "",
        )
        logger.info(
            "rebuild_clusters_done",
            repo_id=repo_id,
            language=language,
            **summary,
        )
        return summary

    except Exception as exc:
        if self.request.retries >= self.max_retries:
            try:
                repo = Repository.objects.get(id=repo_id)
                FailedTask.objects.create(
                    repo=repo,
                    task_name="apps.clustering.tasks.rebuild_clusters",
                    task_id=self.request.id or "",
                    error_message=str(exc),
                    payload={"repo_id": repo_id, "language": language},
                    retry_count=self.request.retries,
                )
            except Exception:
                pass  # never let dead-letter logging crash the task
        raise
