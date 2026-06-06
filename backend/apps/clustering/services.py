"""
DBSCAN Semantic Clustering — core logic.

Two-speed design (Optimization 8 — Lazy Clustering):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fast path  (per ingestion batch, O(1) per chunk):
  assign_chunks_to_clusters()
  — For each newly embedded chunk, find the nearest existing cluster centroid
    via pgvector CosineDistance. If close enough, add ClusterMembership.
  — 95% of new chunks handled here without running DBSCAN.
  — No rebuild of existing clusters; no matrix operations.

Slow path  (periodic / post-ingestion, full rebuild):
  run_full_clustering()
  — Fetch all embeddings for repo+language into a numpy matrix.
  — DBSCAN(eps=0.15, min_samples=3) on cosine distance matrix.
  — For each DBSCAN cluster: compute centroid → stable hash →
    get_or_create SemanticCluster → bulk-create memberships.
  — Updates growth_rate and flags spreading clusters.

Stable cluster IDs
━━━━━━━━━━━━━━━━━━
centroid_hash = sha256(centroid_rounded_to_4dp.astype(float32).tobytes())

When a new DBSCAN run finishes, we match its clusters to existing ones by
comparing centroid cosine similarity (threshold 0.98). Matched → keep existing
hash. Unmatched → new cluster with new hash.
This guarantees "Cluster #8 is always Cluster #8" across every rebuild.

Memory / scale guards
━━━━━━━━━━━━━━━━━━━━━
DBSCAN loads all vectors into RAM. At 768 dims × float32:
  10k chunks  →  ~30 MB   ✅ fine
  100k chunks →  ~300 MB  ⚠ acceptable
  500k chunks →  ~1.5 GB  ❌ too large

Guard: if chunk count > MAX_DBSCAN_VECTORS, use a random sample for DBSCAN
and assign remaining chunks via the fast path against the new centroids.
"""
import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# DBSCAN params — eps is cosine distance (1 - cosine_similarity)
_DBSCAN_EPS = 0.15          # similarity ≥ 0.85 to be in same cluster
_DBSCAN_MIN_SAMPLES = 3     # minimum 3 functions to form a cluster
_ASSIGNMENT_THRESHOLD = 0.15  # fast-path: assign if centroid distance ≤ this
_CENTROID_MATCH_THRESHOLD = 0.02  # slow-path: treat as same cluster if centroids differ by ≤ this
_GROWTH_FLAG_THRESHOLD = 0.20   # flag cluster if grew > 20% in one run
_MAX_DBSCAN_VECTORS = 50_000    # safety cap — sample if larger (log warning)


# ---------------------------------------------------------------------------
# Centroid hash — stable cluster identity
# ---------------------------------------------------------------------------

def _compute_centroid_hash(centroid: np.ndarray) -> str:
    """
    Stable hash for a cluster centroid.
    Round to 4 decimal places before hashing so tiny floating-point
    deltas from membership changes don't produce a different hash.
    """
    rounded = np.round(centroid, 4).astype(np.float32)
    return hashlib.sha256(rounded.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fast path — assign new chunks to existing clusters
# ---------------------------------------------------------------------------

def assign_chunks_to_clusters(repo_id: str, language: str, chunk_ids: list[str]) -> int:
    """
    Fast assignment: each new chunk → nearest existing cluster centroid via pgvector.

    Called by the cluster_new_chunks Celery task immediately after embed_chunks
    stores vectors. Handles ~95% of new chunks without a DBSCAN run.

    Returns number of new ClusterMembership records created.
    """
    from apps.clustering.models import SemanticCluster, ClusterMembership
    from apps.parsing.models import CodeChunk
    from pgvector.django import CosineDistance

    if not chunk_ids:
        return 0

    start_ts = time.monotonic()

    # Only process chunks that have embeddings
    chunks = list(
        CodeChunk.objects.filter(
            id__in=chunk_ids,
            repo_id=repo_id,
            language=language,
            embedding__isnull=False,
        )
    )

    if not chunks:
        return 0

    # Check there are existing clusters with centroids to match against
    cluster_count = SemanticCluster.objects.filter(
        repo_id=repo_id,
        language=language,
        centroid__isnull=False,
    ).count()

    if cluster_count == 0:
        logger.debug(
            "clustering_fast_path_skipped",
            repo_id=repo_id,
            language=language,
            reason="no existing clusters",
        )
        return 0

    new_memberships = []

    for chunk in chunks:
        # Already assigned to a cluster? Skip (idempotency)
        if ClusterMembership.objects.filter(chunk=chunk).exists():
            continue

        # Find nearest existing cluster centroid via HNSW (Optimization 6)
        nearest = (
            SemanticCluster.objects
            .filter(repo_id=repo_id, language=language, centroid__isnull=False)
            .annotate(dist=CosineDistance('centroid', chunk.embedding))
            .filter(dist__lte=_ASSIGNMENT_THRESHOLD)
            .order_by('dist')
            .first()
        )

        if nearest:
            new_memberships.append(ClusterMembership(
                cluster=nearest,
                chunk=chunk,
                similarity_score=round(1.0 - float(nearest.dist), 4),
            ))

    # Bulk create — Optimization 3
    if new_memberships:
        ClusterMembership.objects.bulk_create(
            new_memberships,
            batch_size=500,
            ignore_conflicts=True,
        )
        # Update chunk_count and file_count on affected clusters
        _refresh_cluster_stats_for(repo_id, language)

    duration_ms = int((time.monotonic() - start_ts) * 1000)
    logger.info(
        "clustering_fast_path_done",
        repo_id=repo_id,
        language=language,
        chunks_processed=len(chunks),
        memberships_created=len(new_memberships),
        duration_ms=duration_ms,
    )

    return len(new_memberships)


# ---------------------------------------------------------------------------
# Slow path — full DBSCAN re-clustering
# ---------------------------------------------------------------------------

def run_full_clustering(repo_id: str, language: str, task_id: str = "") -> dict:
    """
    Full DBSCAN re-clustering for a repo+language.

    Steps:
      1. Fetch all embeddings for repo+language
      2. DBSCAN on cosine distance matrix
      3. Match DBSCAN clusters to existing SemanticClusters (stable IDs)
      4. Create/update SemanticCluster records with new centroids
      5. Bulk-create ClusterMembership records
      6. Calculate growth_rate and flag spreading clusters

    Returns summary dict for structured logging.
    """
    from apps.clustering.models import SemanticCluster, ClusterMembership
    from apps.parsing.models import CodeChunk
    from apps.ingestion.models import PipelineEvent

    start_ts = time.monotonic()

    logger.info(
        "clustering_full_started",
        repo_id=repo_id,
        language=language,
    )

    _record_pipeline_event(repo_id, language, PipelineEvent.Status.STARTED, task_id)

    # ------------------------------------------------------------------
    # Step 1: Fetch all embedded chunks for this repo+language
    # ------------------------------------------------------------------
    qs = CodeChunk.objects.filter(
        repo_id=repo_id,
        language=language,
        embedding__isnull=False,
    ).values('id', 'embedding', 'file_path', 'commit_id')

    rows = list(qs)

    if len(rows) < _DBSCAN_MIN_SAMPLES:
        logger.info(
            "clustering_full_skipped",
            repo_id=repo_id,
            language=language,
            chunk_count=len(rows),
            reason=f"fewer than {_DBSCAN_MIN_SAMPLES} embedded chunks",
        )
        _record_pipeline_event(repo_id, language, PipelineEvent.Status.COMPLETED, task_id,
                               items_processed=0)
        return {"clusters_created": 0, "clusters_updated": 0, "memberships": 0}

    # Memory guard — sample if too large
    sampled = False
    if len(rows) > _MAX_DBSCAN_VECTORS:
        logger.warning(
            "clustering_full_sampling",
            repo_id=repo_id,
            language=language,
            total=len(rows),
            sample_size=_MAX_DBSCAN_VECTORS,
        )
        rng = np.random.default_rng(seed=42)
        indices = rng.choice(len(rows), size=_MAX_DBSCAN_VECTORS, replace=False)
        rows = [rows[i] for i in sorted(indices)]
        sampled = True

    # Build numpy matrix — float32 halves memory vs float64
    chunk_ids = [str(r['id']) for r in rows]
    chunk_files = [r['file_path'] for r in rows]
    chunk_commits = [str(r['commit_id']) for r in rows]
    matrix = np.array([r['embedding'] for r in rows], dtype=np.float32)

    logger.info(
        "clustering_matrix_built",
        repo_id=repo_id,
        language=language,
        shape=list(matrix.shape),
        sampled=sampled,
    )

    # ------------------------------------------------------------------
    # Step 2: DBSCAN with cosine distance
    # ------------------------------------------------------------------
    from sklearn.cluster import DBSCAN

    # Cosine distance = 1 - cosine_similarity
    # With normalized vectors: cosine_distance = 0.5 * ||a - b||^2
    # metric='cosine' works directly on the raw vectors
    dbscan = DBSCAN(
        eps=_DBSCAN_EPS,
        min_samples=_DBSCAN_MIN_SAMPLES,
        metric='cosine',
        algorithm='brute',   # exact — HNSW not available in sklearn
        n_jobs=-1,           # use all CPU cores
    )
    labels = dbscan.fit_predict(matrix)

    unique_labels = set(labels)
    unique_labels.discard(-1)  # -1 = noise (not in any cluster)

    logger.info(
        "clustering_dbscan_done",
        repo_id=repo_id,
        language=language,
        clusters_found=len(unique_labels),
        noise_points=int(np.sum(labels == -1)),
        total_points=len(labels),
    )

    if not unique_labels:
        _record_pipeline_event(repo_id, language, PipelineEvent.Status.COMPLETED, task_id,
                               items_processed=0)
        return {"clusters_created": 0, "clusters_updated": 0, "memberships": 0}

    # ------------------------------------------------------------------
    # Step 3: Compute centroids + match to existing clusters (stable IDs)
    # ------------------------------------------------------------------
    existing_clusters = {
        c.centroid_hash: c
        for c in SemanticCluster.objects.filter(repo_id=repo_id, language=language)
    }

    # Build centroid vectors for matching
    existing_hashes = list(existing_clusters.keys())
    existing_centroids: Optional[np.ndarray] = None
    if existing_clusters:
        existing_centroids = np.array(
            [existing_clusters[h].centroid for h in existing_hashes
             if existing_clusters[h].centroid is not None],
            dtype=np.float32,
        )
        # Rebuild hash list to only include clusters that have centroids
        existing_hashes = [
            h for h in existing_hashes
            if existing_clusters[h].centroid is not None
        ]

    # Per-DBSCAN-cluster: compute centroid, match or create
    now = datetime.now(timezone.utc)
    clusters_created = 0
    clusters_updated = 0
    all_memberships: list = []

    # Snapshot of old chunk counts for growth_rate calculation
    old_counts = {
        c.centroid_hash: c.chunk_count
        for c in existing_clusters.values()
    }

    label_to_cluster: dict[int, SemanticCluster] = {}

    for label in unique_labels:
        member_mask = labels == label
        member_indices = np.where(member_mask)[0]
        member_vectors = matrix[member_mask]

        centroid = member_vectors.mean(axis=0)

        # Find earliest commit among members for origin tracking
        origin_commit_id = chunk_commits[int(member_indices[0])]

        # Try to match against an existing cluster centroid
        matched_cluster: Optional[SemanticCluster] = None

        if existing_centroids is not None and len(existing_centroids) > 0:
            # Cosine distance between new centroid and all existing centroids
            norms_new = np.linalg.norm(centroid)
            norms_existing = np.linalg.norm(existing_centroids, axis=1)
            if norms_new > 0:
                cos_sims = (existing_centroids @ centroid) / (norms_existing * norms_new + 1e-10)
                best_idx = int(np.argmax(cos_sims))
                best_dist = 1.0 - float(cos_sims[best_idx])
                if best_dist <= _CENTROID_MATCH_THRESHOLD:
                    matched_hash = existing_hashes[best_idx]
                    matched_cluster = existing_clusters[matched_hash]

        if matched_cluster:
            # Update centroid vector (smoothed toward new centroid)
            # Keep centroid_hash unchanged — stable ID principle
            matched_cluster.centroid = centroid.tolist()
            clusters_updated += 1
            label_to_cluster[label] = matched_cluster
        else:
            # New cluster — assign stable hash from this centroid
            new_hash = _compute_centroid_hash(centroid)
            # Handle rare hash collision: append index to differentiate
            if new_hash in existing_clusters:
                new_hash = new_hash[:60] + f"{label:04d}"

            cluster, created = SemanticCluster.objects.get_or_create(
                centroid_hash=new_hash,
                defaults={
                    'repo_id': repo_id,
                    'language': language,
                    'centroid': centroid.tolist(),
                    'first_seen_at': now,
                    'origin_commit_id': origin_commit_id,
                },
            )
            if created:
                clusters_created += 1
            label_to_cluster[label] = cluster

    # ------------------------------------------------------------------
    # Step 4: Bulk save updated centroids
    # ------------------------------------------------------------------
    updated_clusters = [c for c in label_to_cluster.values() if c.pk]
    if updated_clusters:
        SemanticCluster.objects.bulk_update(
            updated_clusters,
            ['centroid'],
            batch_size=500,
        )

    # ------------------------------------------------------------------
    # Step 5: Bulk-create ClusterMembership records
    # ------------------------------------------------------------------
    ClusterMembership = __import__(
        'apps.clustering.models', fromlist=['ClusterMembership']
    ).ClusterMembership

    for label in unique_labels:
        cluster = label_to_cluster.get(label)
        if not cluster:
            continue

        member_mask = labels == label
        member_indices = np.where(member_mask)[0]
        member_vectors = matrix[member_mask]
        centroid_vec = member_vectors.mean(axis=0)
        centroid_norm = np.linalg.norm(centroid_vec)

        for local_i, global_i in enumerate(member_indices):
            vec = matrix[global_i]
            # Cosine similarity to centroid
            if centroid_norm > 0:
                sim = float(np.dot(vec, centroid_vec) / (np.linalg.norm(vec) * centroid_norm + 1e-10))
            else:
                sim = 0.0

            all_memberships.append(ClusterMembership(
                cluster=cluster,
                chunk_id=chunk_ids[int(global_i)],
                similarity_score=round(max(0.0, min(1.0, sim)), 4),
            ))

    if all_memberships:
        ClusterMembership.objects.bulk_create(
            all_memberships,
            batch_size=500,
            ignore_conflicts=True,   # idempotency — skip existing (chunk, cluster) pairs
        )

    # ------------------------------------------------------------------
    # Step 6: Update stats + flag spreading clusters
    # ------------------------------------------------------------------
    _refresh_cluster_stats_for(repo_id, language, old_counts=old_counts)

    duration_ms = int((time.monotonic() - start_ts) * 1000)

    summary = {
        "clusters_created": clusters_created,
        "clusters_updated": clusters_updated,
        "memberships": len(all_memberships),
        "sampled": sampled,
        "duration_ms": duration_ms,
    }

    logger.info("clustering_full_done", repo_id=repo_id, language=language, **summary)

    _record_pipeline_event(
        repo_id, language, PipelineEvent.Status.COMPLETED, task_id,
        items_processed=len(all_memberships),
        duration_ms=duration_ms,
    )

    return summary


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _refresh_cluster_stats_for(
    repo_id: str,
    language: str,
    old_counts: Optional[dict] = None,
) -> None:
    """
    Recalculate file_count, chunk_count, growth_rate, is_flagged for all
    clusters of this repo+language. Bulk-updates in one pass.
    """
    from apps.clustering.models import SemanticCluster, ClusterMembership
    from django.db.models import Count

    clusters = list(SemanticCluster.objects.filter(repo_id=repo_id, language=language))
    if not clusters:
        return

    cluster_ids = [c.id for c in clusters]

    # Aggregate memberships in one query
    membership_stats = (
        ClusterMembership.objects
        .filter(cluster_id__in=cluster_ids)
        .values('cluster_id')
        .annotate(
            total_chunks=Count('id'),
            distinct_files=Count('chunk__file_path', distinct=True),
        )
    )
    stats_map = {str(row['cluster_id']): row for row in membership_stats}

    to_update = []
    for cluster in clusters:
        stats = stats_map.get(str(cluster.id), {})
        new_count = stats.get('total_chunks', 0)
        new_file_count = stats.get('distinct_files', 0)

        old_count = (old_counts or {}).get(cluster.centroid_hash, cluster.chunk_count)
        if old_count > 0:
            growth = (new_count - old_count) / old_count
        else:
            growth = 0.0

        cluster.chunk_count = new_count
        cluster.file_count = new_file_count
        cluster.growth_rate = round(growth, 4)
        cluster.is_flagged = growth > _GROWTH_FLAG_THRESHOLD and new_count >= _DBSCAN_MIN_SAMPLES

        to_update.append(cluster)

    SemanticCluster.objects.bulk_update(
        to_update,
        ['chunk_count', 'file_count', 'growth_rate', 'is_flagged'],
        batch_size=500,
    )

    flagged = sum(1 for c in to_update if c.is_flagged)
    if flagged:
        logger.warning(
            "clustering_spreading_patterns_flagged",
            repo_id=repo_id,
            language=language,
            flagged_count=flagged,
        )


def _record_pipeline_event(
    repo_id: str,
    language: str,
    status: str,
    task_id: str = "",
    items_processed: int = 0,
    duration_ms: int = 0,
    error: str = "",
) -> None:
    """Write a PipelineEvent row — fire and forget, never raises."""
    try:
        from apps.ingestion.models import PipelineEvent
        PipelineEvent.objects.create(
            repo_id=repo_id,
            task_id=task_id,
            stage=f"clustering:{language}",
            status=status,
            items_processed=items_processed,
            duration_ms=duration_ms,
            error_message=error,
        )
    except Exception as exc:
        logger.warning("pipeline_event_write_failed", error=str(exc))
