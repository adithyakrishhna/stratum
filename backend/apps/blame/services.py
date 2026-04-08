"""
Blame Mapper — ranks every commit by the debt and patterns it introduced.

From CLAUDE.md Feature 11:
  "Ranks every commit by debt introduced — not by lines changed, but by
   patterns originated and spread. Traces current problem clusters back
   to their origin commit."

Three metrics per commit
─────────────────────────
debt_introduced_score
  Sum of POSITIVE velocity across all files changed in this commit.
  Represents how much new debt this commit added to the codebase.
  (Negative velocity = refactor = not counted — that is a good thing.)
  Also written back to Commit.debt_score_delta for dashboard queries.

patterns_originated
  Number of SemanticCluster records whose origin_commit_id = this commit.
  Represents how many new recurring anti-patterns were born here.

files_eventually_affected
  Number of distinct file_paths in ClusterMembership records for clusters
  that originated from this commit.
  Represents the eventual blast radius of patterns started here.
  "Cluster #8 originated in commit a3f92b - now in 9 files."

Dependencies
─────────────
  Requires DebtScore records  -> run after score_repo_debt
  Requires SemanticCluster.origin_commit_id -> run after rebuild_clusters
  Both are dispatched by ingest_repository; blame fires at countdown=420.

Efficiency
──────────
  All three metrics computed with aggregation queries (no Python loops).
  BlameMap records bulk-created in one pass (Optimization 3).
  Incremental: only commits without an existing BlameMap are processed.
  Commit.debt_score_delta updated via bulk_update (Optimization 3).
"""
import time

import structlog

logger = structlog.get_logger(__name__)

_BATCH_SIZE = 500


def compute_blame_for_repo(repo_id: str, task_id: str = "") -> dict:
    """
    Compute BlameMap records for all unprocessed commits in a repository.

    Incremental (Principle 11): skips commits that already have a BlameMap.
    Safe to re-run — unique OneToOne on (commit) prevents duplicates.

    Returns summary dict for structured logging.
    """
    from django.db.models import Sum, Count, Q
    from apps.ingestion.models import Commit, PipelineEvent
    from apps.debt.models import DebtScore
    from apps.clustering.models import SemanticCluster, ClusterMembership
    from apps.blame.models import BlameMap

    start_ts = time.monotonic()
    _record_pipeline_event(repo_id, PipelineEvent.Status.STARTED, task_id)

    logger.info("blame_mapper_started", repo_id=repo_id)

    # Commits that are processed but have no BlameMap yet
    processed_commit_ids = set(
        BlameMap.objects.filter(repo_id=repo_id).values_list('commit_id', flat=True)
    )

    commits = list(
        Commit.objects.filter(repo_id=repo_id, is_processed=True)
        .exclude(id__in=processed_commit_ids)
        .order_by('committed_at')
    )

    if not commits:
        logger.info("blame_mapper_nothing_to_process", repo_id=repo_id)
        _record_pipeline_event(repo_id, PipelineEvent.Status.COMPLETED, task_id,
                               items_processed=0)
        return {"commits_processed": 0, "blame_records_created": 0}

    commit_ids = [c.id for c in commits]
    commit_map = {c.id: c for c in commits}

    # -----------------------------------------------------------------------
    # Metric 1: debt_introduced_score
    # Sum of positive velocity per commit (Principle 10 — single aggregation query)
    # -----------------------------------------------------------------------
    debt_rows = (
        DebtScore.objects
        .filter(repo_id=repo_id, commit_id__in=commit_ids)
        .values('commit_id')
        .annotate(
            positive_velocity=Sum('velocity', filter=Q(velocity__gt=0)),
            total_velocity=Sum('velocity'),
        )
    )

    debt_by_commit: dict = {}
    for row in debt_rows:
        debt_by_commit[row['commit_id']] = {
            'debt_introduced': round(float(row['positive_velocity'] or 0.0), 4),
            'total_delta':     round(float(row['total_velocity']    or 0.0), 4),
        }

    # -----------------------------------------------------------------------
    # Metric 2: patterns_originated
    # Clusters whose origin_commit_id is this commit (single aggregation query)
    # -----------------------------------------------------------------------
    origin_rows = (
        SemanticCluster.objects
        .filter(repo_id=repo_id, origin_commit_id__in=commit_ids)
        .values('origin_commit_id')
        .annotate(count=Count('id'))
    )

    patterns_by_commit: dict = {
        row['origin_commit_id']: row['count']
        for row in origin_rows
    }

    # -----------------------------------------------------------------------
    # Metric 3: files_eventually_affected
    # Distinct files in ClusterMembership for clusters born in each commit
    # -----------------------------------------------------------------------
    origin_clusters = list(
        SemanticCluster.objects
        .filter(repo_id=repo_id, origin_commit_id__in=commit_ids)
        .values('id', 'origin_commit_id')
    )

    commit_to_cluster_ids: dict = {}
    for row in origin_clusters:
        cid = row['origin_commit_id']
        commit_to_cluster_ids.setdefault(cid, []).append(row['id'])

    files_by_commit: dict = {}
    for commit_id, cluster_ids in commit_to_cluster_ids.items():
        file_count = (
            ClusterMembership.objects
            .filter(cluster_id__in=cluster_ids)
            .values('chunk__file_path')
            .distinct()
            .count()
        )
        files_by_commit[commit_id] = file_count

    # -----------------------------------------------------------------------
    # Build BlameMap + update Commit.debt_score_delta (Optimization 3)
    # -----------------------------------------------------------------------
    blame_records = []
    commits_to_update = []

    for commit in commits:
        debt_info = debt_by_commit.get(
            commit.id, {'debt_introduced': 0.0, 'total_delta': 0.0}
        )

        blame_records.append(BlameMap(
            repo_id=repo_id,
            commit=commit,
            debt_introduced_score=debt_info['debt_introduced'],
            patterns_originated=patterns_by_commit.get(commit.id, 0),
            files_eventually_affected=files_by_commit.get(commit.id, 0),
        ))

        commit.debt_score_delta = debt_info['total_delta']
        commits_to_update.append(commit)

    # Bulk-create — Optimization 3
    BlameMap.objects.bulk_create(
        blame_records,
        batch_size=_BATCH_SIZE,
        ignore_conflicts=True,
    )

    # Write debt_score_delta back to Commit records — Optimization 3
    Commit.objects.bulk_update(
        commits_to_update,
        ['debt_score_delta'],
        batch_size=_BATCH_SIZE,
    )

    duration_ms = int((time.monotonic() - start_ts) * 1000)
    summary = {
        "commits_processed": len(commits),
        "blame_records_created": len(blame_records),
        "duration_ms": duration_ms,
    }

    logger.info("blame_mapper_done", repo_id=repo_id, **summary)
    _record_pipeline_event(
        repo_id, PipelineEvent.Status.COMPLETED, task_id,
        items_processed=len(blame_records), duration_ms=duration_ms,
    )

    return summary


def _record_pipeline_event(
    repo_id: str,
    status: str,
    task_id: str = "",
    items_processed: int = 0,
    duration_ms: int = 0,
) -> None:
    try:
        from apps.ingestion.models import PipelineEvent
        PipelineEvent.objects.create(
            repo_id=repo_id,
            task_id=task_id,
            stage="blame_mapper",
            status=status,
            items_processed=items_processed,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning("pipeline_event_write_failed", stage="blame_mapper", error=str(exc))
