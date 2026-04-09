"""
Semantic Duplicate Detection for Pull Requests.

When a PR is opened, we:
  1. Embed every function/method in the PR using CodeBERT (via embedding_client)
  2. Query pgvector for existing functions in the codebase with high cosine similarity
  3. Return a DuplicateMatch per hit — the orchestrator converts these to PrFindings

Pipeline
--------
    Orchestrator collects _SimpleChunk objects (with raw_code) across all PR files
        ↓
    find_semantic_duplicates(chunks, repo_id, threshold)
        ↓ one batch embedding call for all PR chunks (Optimization 1)
    get_embeddings_batch(all_texts)  → Redis cache + embedding service
        ↓ per-chunk pgvector ANN query (HNSW — Optimization 6)
    CodeChunk.objects.annotate(dist=CosineDistance(...)).filter(dist__lte=max_dist)
        ↓
    list[DuplicateMatch]

Similarity threshold
--------------------
Default 0.85 (configurable via stratum.yaml: `similarity_threshold: 0.85`)
Cosine distance ≤ (1 - threshold) → match.
With normalize_embeddings=True (our embedding service), cosine sim = dot product.

Why per-chunk queries instead of a single batch query
------------------------------------------------------
pgvector does not support batched ANN queries in one SQL call. Each vector
needs its own ORDER BY distance query. However, the embedding step IS batched
(all PR chunks → one HTTP call), so the expensive part is still O(1) HTTP calls.
The pgvector queries are fast (HNSW index, ~1ms each for millions of vectors).
"""
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_THRESHOLD = 0.97   # CodeBERT embeddings are anisotropic — unrelated code
                            # often scores 0.90-0.95. Use 0.97 to surface only
                            # near-identical logic, not structural similarity.
_MAX_MATCHES_PER_CHUNK = 5  # top-N unique similar functions per PR chunk

# Only embed functions with at least this many lines of code.
# Short functions (React components, simple views) are dominated by
# boilerplate tokens (import, export, return, className) and produce
# near-identical CodeBERT embeddings regardless of actual logic.
_MIN_LINES = 20

# Only embed functions with at least this cyclomatic complexity.
# Trivial functions (complexity 1-2) have no meaningful logic to compare.
_MIN_COMPLEXITY = 3


@dataclass
class DuplicateMatch:
    """One semantic match between a PR chunk and an existing codebase chunk."""
    # PR side
    file_path: str       # file being reviewed
    chunk_name: str      # function name in the PR
    line_number: int     # start line of the function in the PR file

    # Codebase side
    similar_file: str    # file path in the existing codebase
    similar_chunk: str   # function name in the existing codebase
    similar_line: int    # start line in that file

    similarity: float    # 0.0–1.0, higher = more similar (rounded to 4dp)


def find_semantic_duplicates(
    chunks: list,
    repo_id: str,
    similarity_threshold: float = _DEFAULT_THRESHOLD,
) -> list[DuplicateMatch]:
    """
    Embed all PR chunks and query pgvector for similar existing functions.

    Args:
        chunks:               list of _SimpleChunk objects (must have .raw_code)
        repo_id:              UUID string of the repository being reviewed
        similarity_threshold: minimum cosine similarity [0.0, 1.0] to flag a match

    Returns:
        list of DuplicateMatch — one per match found, sorted by similarity desc.
        Empty list if circuit open, service error, or no matches.

    Never raises — all errors are caught and logged.
    """
    from apps.parsing.embedding_client import get_embeddings_batch
    from apps.parsing.models import CodeChunk
    from pgvector.django import CosineDistance

    # -----------------------------------------------------------------------
    # Step 1: Filter to chunks worth embedding.
    # Short or trivial functions are dominated by boilerplate tokens and
    # produce false positives with CodeBERT regardless of threshold.
    # -----------------------------------------------------------------------
    def _is_embeddable(c) -> bool:
        if not getattr(c, 'raw_code', None) or not c.raw_code.strip():
            return False
        line_count = getattr(c, 'end_line', 0) - getattr(c, 'start_line', 0) + 1
        if line_count < _MIN_LINES:
            return False
        if getattr(c, 'complexity_score', 1) < _MIN_COMPLEXITY:
            return False
        return True

    embeddable = [c for c in chunks if _is_embeddable(c)]

    if not embeddable:
        logger.debug("duplicate_detection_no_chunks", repo_id=repo_id)
        return []

    # -----------------------------------------------------------------------
    # Step 2: Batch embed ALL PR chunks in ONE call (Optimization 1 + cache)
    # -----------------------------------------------------------------------
    texts = [c.raw_code for c in embeddable]
    vectors = get_embeddings_batch(texts)  # returns list[list[float] | None]

    embedded_pairs = [
        (chunk, vec)
        for chunk, vec in zip(embeddable, vectors)
        if vec is not None
    ]

    if not embedded_pairs:
        logger.warning(
            "duplicate_detection_no_vectors",
            repo_id=repo_id,
            chunk_count=len(embeddable),
            reason="all embeddings unavailable",
        )
        return []

    logger.info(
        "duplicate_detection_embedded",
        repo_id=repo_id,
        total_chunks=len(embeddable),
        embedded_count=len(embedded_pairs),
    )

    # -----------------------------------------------------------------------
    # Step 3: Per-chunk pgvector ANN query via HNSW index (Optimization 6)
    # -----------------------------------------------------------------------
    max_distance = round(1.0 - similarity_threshold, 6)  # cosine dist = 1 - sim
    all_matches: list[DuplicateMatch] = []

    for chunk, vector in embedded_pairs:
        try:
            rows = (
                CodeChunk.objects
                .filter(
                    repo_id=repo_id,
                    language=chunk.language,
                    embedding__isnull=False,
                )
                # Exclude the same file — we only care about cross-file duplicates
                .exclude(file_path=chunk.file_path)
                .annotate(dist=CosineDistance('embedding', vector))
                .filter(dist__lte=max_distance)
                .order_by('dist')
                .values('file_path', 'chunk_name', 'start_line', 'dist')
            )

            # Deduplicate by (file_path, chunk_name): the same function is stored
            # once per commit it appeared in, so without deduplication the same
            # match appears N times (once per commit). Keep only the closest hit.
            seen_targets: set[tuple[str, str]] = set()
            for row in rows:
                key = (row['file_path'], row['chunk_name'])
                if key in seen_targets:
                    continue
                seen_targets.add(key)
                similarity = round(1.0 - float(row['dist']), 4)
                all_matches.append(DuplicateMatch(
                    file_path=chunk.file_path,
                    chunk_name=chunk.chunk_name,
                    line_number=chunk.start_line,
                    similar_file=row['file_path'],
                    similar_chunk=row['chunk_name'],
                    similar_line=row['start_line'],
                    similarity=similarity,
                ))
                if len(seen_targets) >= _MAX_MATCHES_PER_CHUNK:
                    break

        except Exception as exc:
            logger.warning(
                "duplicate_search_error",
                chunk_name=chunk.chunk_name,
                file_path=chunk.file_path,
                error=str(exc),
            )
            continue

    # Sort highest similarity first
    all_matches.sort(key=lambda m: m.similarity, reverse=True)

    logger.info(
        "duplicate_detection_complete",
        repo_id=repo_id,
        matches_found=len(all_matches),
        threshold=similarity_threshold,
    )

    return all_matches
