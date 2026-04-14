"""
Debt Timeline — per-file debt scoring across all commits.

Debt Score Formula (CLAUDE.md Feature 9)
-----------------------------------------
total_score = (complexity  × w_complexity)
            + (duplication × w_duplication)
            + (violations  × w_violation)
            + (clusters    × w_cluster)

Components per file per commit:
  complexity_component  — sum of cyclomatic complexity scores of all
                          functions in the file at that commit
  duplication_component — count of functions in this file that have
                          a ClusterMembership (appear in a pattern cluster)
  violation_component   — count of RuleViolation records for this
                          (commit, file_path) — 0 if none yet
  cluster_component     — number of *distinct* clusters this file's
                          functions belong to

Default weights (configurable via stratum.yaml debt_scoring section):
  complexity_weight:   1.0
  duplication_weight:  2.0
  violation_weight:    3.0
  cluster_weight:      1.5

Velocity
---------
velocity = total_score[this_commit] - total_score[previous_commit_for_file]
Positive  → debt increasing
Negative  → debt decreasing (refactor)
Zero      → unchanged

Inflection Points
-----------------
After computing all scores for a file, mark commits where velocity is
a statistical outlier: velocity > mean + 2*std across the file's history.
These are the commits where debt "jumped" — the ones that matter most.
Stored as is_inflection=True on the DebtScore record.

Efficiency
----------
- compute_debt_for_repo processes only commits that do NOT already have
  debt scores (incremental — Principle 11)
- Bulk-creates DebtScore records in batches of 500 (Optimization 3)
- Inflection detection runs once per file after all scores computed,
  using numpy for the statistical calculation (no per-commit DB queries)
"""
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Default scoring weights — can be overridden per repo via stratum.yaml
_DEFAULT_WEIGHTS = {
    'complexity_weight':  1.0,
    'duplication_weight': 2.0,
    'violation_weight':   3.0,
    'cluster_weight':     1.5,
}

# Inflection: velocity > mean + N * std
_INFLECTION_STD_MULTIPLIER = 2.0

# Bulk-create batch size
_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_debt_for_repo(repo_id: str, task_id: str = "") -> dict:
    """
    Compute debt scores for all unscored commits in a repository.

    Incremental (Principle 11): only processes commits that do NOT already
    have a DebtScore record, so re-running is safe and cheap.

    After all scores are computed, runs inflection point detection for every
    file that received new scores in this run.

    Returns summary dict for structured logging.
    """
    from apps.ingestion.models import Commit, PipelineEvent
    from apps.debt.models import DebtScore

    start_ts = time.monotonic()
    _record_pipeline_event(repo_id, PipelineEvent.Status.STARTED, task_id)

    logger.info("debt_scoring_started", repo_id=repo_id)

    # Load per-repo weights from stratum.yaml (falls back to defaults)
    weights = _load_weights(repo_id)

    # Commits that are processed but have no debt scores yet (incremental)
    scored_commit_ids = (
        DebtScore.objects
        .filter(repo_id=repo_id)
        .values_list('commit_id', flat=True)
        .distinct()
    )

    unscored_commits = list(
        Commit.objects
        .filter(repo_id=repo_id, is_processed=True)
        .exclude(id__in=scored_commit_ids)
        .order_by('committed_at')        # chronological — velocity needs prev commit
    )

    if not unscored_commits:
        logger.info("debt_scoring_nothing_to_score", repo_id=repo_id)
        _record_pipeline_event(repo_id, PipelineEvent.Status.COMPLETED, task_id,
                               items_processed=0)
        return {"commits_scored": 0, "scores_created": 0, "inflections_marked": 0}

    logger.info(
        "debt_scoring_commits_found",
        repo_id=repo_id,
        commit_count=len(unscored_commits),
    )

    # -----------------------------------------------------------------------
    # Score each commit — build DebtScore objects, bulk-create in batches
    # -----------------------------------------------------------------------
    all_new_scores: list = []
    files_seen: set[str] = set()   # track which files got new scores

    for commit in unscored_commits:
        commit_scores = _score_commit(repo_id, commit, weights)
        all_new_scores.extend(commit_scores)
        for s in commit_scores:
            files_seen.add(s.file_path)

    # Bulk-create all at once — Optimization 3
    created = 0
    from apps.debt.models import DebtScore
    for batch_start in range(0, len(all_new_scores), _BATCH_SIZE):
        batch = all_new_scores[batch_start : batch_start + _BATCH_SIZE]
        DebtScore.objects.bulk_create(batch, ignore_conflicts=True)
        created += len(batch)

    # -----------------------------------------------------------------------
    # Inflection point detection — once per file, across full history
    # -----------------------------------------------------------------------
    inflections_marked = 0
    for file_path in files_seen:
        inflections_marked += _mark_inflection_points(repo_id, file_path)

    duration_ms = int((time.monotonic() - start_ts) * 1000)
    summary = {
        "commits_scored": len(unscored_commits),
        "scores_created": created,
        "inflections_marked": inflections_marked,
        "duration_ms": duration_ms,
    }

    logger.info("debt_scoring_done", repo_id=repo_id, **summary)
    _record_pipeline_event(
        repo_id, PipelineEvent.Status.COMPLETED, task_id,
        items_processed=created, duration_ms=duration_ms,
    )

    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_commit(repo_id: str, commit, weights: dict) -> list:
    """
    Compute DebtScore objects for every file changed in this commit.
    Returns a list of unsaved DebtScore instances (for bulk_create).
    """
    from apps.parsing.models import CodeChunk
    from apps.clustering.models import ClusterMembership
    from apps.rules.models import RuleViolation
    from apps.debt.models import DebtScore

    # Group code chunks by file_path for this commit
    chunks = list(
        CodeChunk.objects.filter(commit_id=commit.id, repo_id=repo_id)
        .values('file_path', 'language', 'complexity_score', 'id')
    )

    if not chunks:
        return []

    # Group by file
    files: dict[str, dict] = {}
    for c in chunks:
        fp = c['file_path']
        if fp not in files:
            files[fp] = {
                'language': c['language'],
                'chunk_ids': [],
                'complexity_sum': 0.0,
            }
        files[fp]['chunk_ids'].append(str(c['id']))
        files[fp]['complexity_sum'] += float(c['complexity_score'])

    # Duplication + cluster counts — one query per file (small, indexed)
    scores = []

    for file_path, info in files.items():
        chunk_ids = info['chunk_ids']

        # Duplication: how many chunks in this file belong to any cluster
        dup_count = ClusterMembership.objects.filter(
            chunk_id__in=chunk_ids
        ).count()

        # Cluster diversity: how many distinct clusters
        cluster_count = (
            ClusterMembership.objects
            .filter(chunk_id__in=chunk_ids)
            .values('cluster_id')
            .distinct()
            .count()
        )

        # Rule violations (if any were recorded for this commit+file)
        violation_count = RuleViolation.objects.filter(
            repo_id=repo_id,
            commit_id=commit.id,
            file_path=file_path,
        ).count()

        # Weighted score
        total = (
            info['complexity_sum']  * weights['complexity_weight']
            + dup_count             * weights['duplication_weight']
            + violation_count       * weights['violation_weight']
            + cluster_count         * weights['cluster_weight']
        )

        # Velocity — difference vs same file's previous commit score
        velocity = _compute_velocity(repo_id, file_path, commit.id, total)

        scores.append(DebtScore(
            repo_id=repo_id,
            commit=commit,
            file_path=file_path,
            language=info['language'],
            complexity_component=round(info['complexity_sum'], 4),
            duplication_component=float(dup_count),
            violation_component=float(violation_count),
            cluster_component=float(cluster_count),
            total_score=round(total, 4),
            velocity=round(velocity, 4),
        ))

    return scores


def _compute_velocity(repo_id: str, file_path: str, current_commit_id, current_score: float) -> float:
    """
    Velocity = current total_score minus the most recent prior score for this file.
    Returns 0.0 if this is the first score for the file.
    """
    from apps.debt.models import DebtScore

    prev = (
        DebtScore.objects
        .filter(repo_id=repo_id, file_path=file_path)
        .exclude(commit_id=current_commit_id)
        .order_by('-recorded_at')
        .values('total_score')
        .first()
    )

    if prev is None:
        return 0.0
    return current_score - prev['total_score']


def _mark_inflection_points(repo_id: str, file_path: str) -> int:
    """
    Mark DebtScore records as inflection points where velocity is a
    statistical outlier (> mean + 2*std across the file's full history).

    Returns count of records marked.
    Uses numpy for fast vectorised statistics — no per-row Python loops.
    """
    import numpy as np
    from apps.debt.models import DebtScore

    rows = list(
        DebtScore.objects
        .filter(repo_id=repo_id, file_path=file_path)
        .values('id', 'velocity')
    )

    if len(rows) < 3:
        return 0   # not enough data for meaningful statistics

    velocities = np.array([r['velocity'] for r in rows], dtype=np.float64)
    mean = velocities.mean()
    std = velocities.std()

    if std == 0:
        return 0   # all velocities identical — no outliers possible

    threshold = mean + _INFLECTION_STD_MULTIPLIER * std

    inflection_ids = [
        str(r['id'])
        for r, v in zip(rows, velocities)
        if v > threshold and v > 0   # only positive spikes (debt increases)
    ]

    if not inflection_ids:
        return 0

    DebtScore.objects.filter(id__in=inflection_ids).update(is_inflection=True)

    logger.info(
        "debt_inflection_points_marked",
        repo_id=repo_id,
        file_path=file_path,
        count=len(inflection_ids),
        threshold=round(float(threshold), 4),
    )

    return len(inflection_ids)


def _load_weights(repo_id: str) -> dict:
    """
    Load debt scoring weights from stratum.yaml for this repo.
    Falls back to defaults if not configured.

    stratum.yaml uses:
        scoring_weights:
          complexity: 0.3
          duplication: 0.3
          violations: 0.2
          cluster_membership: 0.2
    """
    try:
        from apps.rules.loader import load_rules
        rules_config = load_rules(repo_id)
        scoring = rules_config.get('scoring_weights', {})
        return {
            'complexity_weight':  float(scoring.get('complexity',        _DEFAULT_WEIGHTS['complexity_weight'])),
            'duplication_weight': float(scoring.get('duplication',       _DEFAULT_WEIGHTS['duplication_weight'])),
            'violation_weight':   float(scoring.get('violations',        _DEFAULT_WEIGHTS['violation_weight'])),
            'cluster_weight':     float(scoring.get('cluster_membership', _DEFAULT_WEIGHTS['cluster_weight'])),
        }
    except Exception:
        return dict(_DEFAULT_WEIGHTS)


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
            stage="debt_scoring",
            status=status,
            items_processed=items_processed,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning("pipeline_event_write_failed", stage="debt_scoring", error=str(exc))
