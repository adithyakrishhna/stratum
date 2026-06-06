"""
PR Debt Impact Prediction — The Killer Feature (CLAUDE.md Feature 12)

"When PR opened, compares new chunks against all existing clusters,
 calculates which clusters this PR will join and growth impact,
 posts warning: 'This PR introduces 2 functions similar to Cluster #8,
 currently in 5 files. Merging accelerates cluster growth by ~35%.
 Consider consolidating before merging.'"

"No existing tool does this — they review in isolation.
 Stratum reviews in context of entire codebase history."

Algorithm
─────────
1. Embed all PR chunks in one batch call (Optimization 1 + cache)
2. For each chunk: find nearest cluster centroid via pgvector CosineDistance
   (same HNSW index used by fast-path clustering — Optimization 6)
3. Tally: how many PR chunks would join each cluster
4. Compute growth_rate = new_chunks_joining / current_cluster.chunk_count
5. Filter to clusters where growth_rate >= IMPACT_THRESHOLD
6. Sort by growth_rate descending — biggest impact first

Output
──────
List of ClusterImpact objects, one per affected cluster.
The orchestrator converts these to _FileFinding objects (DEBT_IMPACT type)
and posts them as a prominent section in the PR summary.

debt_impact_score on PullRequest
─────────────────────────────────
  sum of all growth_rates, clamped to [0, 1]
  0.0  = PR introduces no functions similar to existing clusters
  1.0+ = PR would at least double one or more existing clusters
"""
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

_ASSIGNMENT_THRESHOLD = 0.15   # cosine distance — matches clustering fast path
_IMPACT_THRESHOLD     = 0.05   # minimum growth rate (5%) to surface a warning
_TOP_CLUSTERS         = 5      # max clusters to report per PR


@dataclass
class ClusterImpact:
    """One cluster that this PR would significantly grow."""
    cluster_id:               str
    language:                 str
    current_chunk_count:      int    # cluster size before this PR
    current_file_count:       int    # files in cluster before this PR
    new_chunks_joining:       int    # PR functions that would join
    growth_rate:              float  # new_chunks / current_chunk_count (e.g. 0.35 = 35%)
    representative_chunk:     str    # sample function name from existing cluster
    origin_commit_sha:        str    # commit where this cluster first appeared


def predict_debt_impact(
    chunks: list,
    repo_id: str,
    impact_threshold: float = _IMPACT_THRESHOLD,
) -> list[ClusterImpact]:
    """
    Predict which existing clusters this PR would accelerate.

    Args:
        chunks:           _SimpleChunk objects with raw_code (from orchestrator)
        repo_id:          Repository UUID string
        impact_threshold: Minimum growth rate [0.0, 1.0] to surface a warning

    Returns:
        Sorted list of ClusterImpact (highest growth_rate first).
        Empty list if circuit open, no clusters, or no significant impact.

    Never raises — all errors are caught and logged.
    """
    from apps.parsing.embedding_client import get_embeddings_batch
    from apps.clustering.models import SemanticCluster, ClusterMembership
    from pgvector.django import CosineDistance

    # Only embed chunks that have code
    embeddable = [c for c in chunks if getattr(c, 'raw_code', None) and c.raw_code.strip()]
    if not embeddable:
        return []

    # Check clusters exist at all — skip early if repo has no clusters yet
    if not SemanticCluster.objects.filter(repo_id=repo_id, centroid__isnull=False).exists():
        logger.debug("debt_impact_no_clusters", repo_id=repo_id)
        return []

    # -----------------------------------------------------------------------
    # Step 1: Batch embed all PR chunks — Optimization 1 + cache (Optimization 5)
    # -----------------------------------------------------------------------
    texts   = [c.raw_code for c in embeddable]
    vectors = get_embeddings_batch(texts)

    embedded_pairs = [
        (chunk, vec)
        for chunk, vec in zip(embeddable, vectors)
        if vec is not None
    ]

    if not embedded_pairs:
        return []

    # -----------------------------------------------------------------------
    # Step 2: For each chunk, find the nearest cluster centroid (HNSW)
    # -----------------------------------------------------------------------
    cluster_hits: dict[str, int] = {}   # cluster_id -> count of PR chunks matching

    for chunk, vector in embedded_pairs:
        try:
            nearest = (
                SemanticCluster.objects
                .filter(
                    repo_id=repo_id,
                    language=chunk.language,
                    centroid__isnull=False,
                )
                .annotate(dist=CosineDistance('centroid', vector))
                .filter(dist__lte=_ASSIGNMENT_THRESHOLD)
                .order_by('dist')
                .values('id')
                .first()
            )
            if nearest:
                cid = str(nearest['id'])
                cluster_hits[cid] = cluster_hits.get(cid, 0) + 1

        except Exception as exc:
            logger.warning(
                "debt_impact_chunk_query_failed",
                chunk=chunk.chunk_name,
                error=str(exc),
            )
            continue

    if not cluster_hits:
        return []

    # -----------------------------------------------------------------------
    # Step 3: Fetch cluster details + compute growth rates
    # -----------------------------------------------------------------------
    clusters = list(
        SemanticCluster.objects
        .filter(id__in=list(cluster_hits.keys()))
        .select_related('origin_commit')
    )

    impacts: list[ClusterImpact] = []

    for cluster in clusters:
        new_count = cluster_hits[str(cluster.id)]
        current   = cluster.chunk_count or 1   # avoid division by zero

        growth_rate = round(new_count / current, 4)
        if growth_rate < impact_threshold:
            continue

        # Representative function from the existing cluster (highest sim)
        sample = (
            ClusterMembership.objects
            .filter(cluster=cluster)
            .select_related('chunk')
            .order_by('-similarity_score')
            .first()
        )
        representative = sample.chunk.chunk_name if sample else "unknown function"

        origin_sha = (
            cluster.origin_commit.sha[:8]
            if cluster.origin_commit else "unknown commit"
        )

        impacts.append(ClusterImpact(
            cluster_id=str(cluster.id),
            language=cluster.language,
            current_chunk_count=cluster.chunk_count,
            current_file_count=cluster.file_count,
            new_chunks_joining=new_count,
            growth_rate=growth_rate,
            representative_chunk=representative,
            origin_commit_sha=origin_sha,
        ))

    # Sort by growth_rate descending — biggest impact first
    impacts.sort(key=lambda x: x.growth_rate, reverse=True)
    top_impacts = impacts[:_TOP_CLUSTERS]

    logger.info(
        "debt_impact_predicted",
        repo_id=repo_id,
        clusters_affected=len(top_impacts),
        total_growth=round(sum(i.growth_rate for i in top_impacts), 4),
    )

    return top_impacts


def compute_debt_impact_score(impacts: list[ClusterImpact]) -> float:
    """
    Aggregate debt_impact_score for the PullRequest record.
    Sum of growth rates, clamped to [0.0, 1.0].
    """
    if not impacts:
        return 0.0
    return round(min(1.0, sum(i.growth_rate for i in impacts)), 4)
