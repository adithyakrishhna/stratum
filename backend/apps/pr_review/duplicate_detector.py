"""
Semantic Duplicate Detection for Pull Requests.

When a PR is opened, we:
  1. Embed every function/method in the PR using CodeBERT (via embedding_client)
  2. Query pgvector for existing functions in the codebase with high cosine similarity
  3. Apply two secondary filters to eliminate CodeBERT anisotropy false positives
  4. Return a DuplicateMatch per confirmed hit

Pipeline
--------
    Orchestrator collects _SimpleChunk objects (with raw_code) across all PR files
        ↓
    find_semantic_duplicates(chunks, repo_id, threshold)
        ↓ one batch embedding call for all PR chunks (Optimization 1)
    get_embeddings_batch(all_texts)  → Redis cache + embedding service
        ↓ per-chunk pgvector ANN query (HNSW — Optimization 6)
    CodeChunk.objects.annotate(dist=CosineDistance(...)).filter(dist__lte=max_dist)
        ↓ secondary filters: line-count ratio + vocabulary overlap
    list[DuplicateMatch]

Why secondary filters are required
------------------------------------
CodeBERT (microsoft/codebert-base) is a masked-language model pre-trained for
fill-mask tasks, not code similarity search. Its embeddings are highly anisotropic:
ALL code in the same language clusters in a narrow cone of embedding space, so
unrelated functions (Django views, React components) score 0.95–0.99 cosine
similarity simply because they share the same boilerplate tokens.

The cosine threshold alone cannot distinguish real duplicates from structural
false positives. Two independent secondary signals confirm or reject each match:

  1. Line-count ratio  — genuinely duplicated logic has similar code length.
                         Functions differing by more than 2.5x are skipped.

  2. Vocabulary overlap — the PR chunk's identifiers must overlap with the
                          matched function's name and module path tokens.
                          "list_repositories" code shares 0 tokens with
                          "cluster_map / dashboard/views" → rejected.
                          "embed_chunks" shares "embed" with "embed_batch" → kept.

This two-signal approach works without stored raw_code (STORE_RAW_CODE=false)
because it only reads the PR chunk's own code (always available) and uses
chunk_name + file_path from the DB row (always stored).

Similarity threshold
--------------------
Default 0.97 (configurable via stratum.yaml: `similarity_threshold: 0.97`)
Cosine distance ≤ (1 - threshold) → candidate match → then secondary filters.
With normalize_embeddings=True (our embedding service), cosine sim = dot product.
"""
import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_THRESHOLD = 0.97   # cosine similarity floor — then secondary filters apply
_MAX_MATCHES_PER_CHUNK = 5  # top-N unique matches per PR chunk after all filters

# Only embed functions meeting these minimums.
# Short/trivial functions are dominated by boilerplate (import, return, className)
# and produce identical CodeBERT embeddings regardless of actual logic.
_MIN_LINES = 20
_MIN_COMPLEXITY = 3

# Secondary filter constants
_MAX_LINE_RATIO = 2.5   # skip match if lengths differ by more than 2.5x
_MIN_VOCAB_OVERLAP = 1  # skip match if PR code shares 0 meaningful tokens with match context

# Common keywords that appear in virtually all code — excluded from vocabulary check
_STOP_TOKENS = {
    'self', 'true', 'false', 'none', 'null', 'undefined', 'async', 'await',
    'return', 'yield', 'import', 'from', 'class', 'function', 'const', 'let',
    'var', 'elif', 'else', 'pass', 'raise', 'with', 'super', 'type', 'this',
    'that', 'then', 'catch', 'throw', 'void', 'export', 'default', 'static',
    'public', 'private', 'protected', 'final', 'abstract', 'interface', 'enum',
    'string', 'number', 'boolean', 'object', 'array', 'list', 'dict', 'tuple',
    'request', 'response', 'data', 'result', 'error', 'value', 'item', 'name',
    'args', 'kwargs', 'params', 'config', 'settings', 'logger', 'logging',
}


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


def _is_embeddable(chunk) -> bool:
    """
    Return True if the chunk is worth embedding for duplicate detection.
    Filters out short/trivial functions that produce CodeBERT false positives.
    """
    if not getattr(chunk, 'raw_code', None) or not chunk.raw_code.strip():
        return False
    line_count = getattr(chunk, 'end_line', 0) - getattr(chunk, 'start_line', 0) + 1
    if line_count < _MIN_LINES:
        return False
    if getattr(chunk, 'complexity_score', 1) < _MIN_COMPLEXITY:
        return False
    return True


def _passes_secondary_filters(
    pr_chunk,
    match_name: str,
    match_file: str,
    match_start: int,
    match_end: int,
) -> bool:
    """
    Secondary validation after cosine similarity passes the threshold.

    Applies two independent checks to reject CodeBERT anisotropy false positives:

    1. Line-count ratio: duplicated logic has similar length. If the stored function
       is more than 2.5x longer/shorter than the PR chunk, it's a structural false
       positive (e.g., a 30-line simple view vs a 200-line complex orchestrator).

    2. Vocabulary overlap: the PR chunk's meaningful identifiers must appear in the
       matched function's name and module path. Completely different-purpose functions
       (repositories/views::list_repositories vs dashboard/views::cluster_map) share
       zero domain vocabulary → rejected. Genuine duplicates share the same variable
       names, function calls, and domain terms.

    Returns True if the match should be kept, False if it should be discarded.
    """
    # --- Filter 1: line-count ratio ---
    pr_lines = max(1, getattr(pr_chunk, 'end_line', 0) - getattr(pr_chunk, 'start_line', 0) + 1)
    match_lines = max(1, (match_end or match_start) - match_start + 1)
    line_ratio = max(pr_lines, match_lines) / min(pr_lines, match_lines)
    if line_ratio > _MAX_LINE_RATIO:
        return False

    # --- Filter 2: vocabulary overlap ---
    # Extract meaningful identifiers from PR chunk code (4+ chars, not stop words)
    pr_tokens = {
        t.lower()
        for t in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', pr_chunk.raw_code or '')
    } - _STOP_TOKENS

    if not pr_tokens:
        return True  # can't verify, allow through

    # Derive context tokens from the matched function's name and file path.
    # Split snake_case and camelCase into individual words.
    raw_ctx = ' '.join([
        re.sub(r'([a-z])([A-Z])', r'\1 \2', match_name),    # camelCase → words
        match_name.replace('_', ' '),                         # snake_case → words
        match_file.replace('/', ' ').replace('_', ' ').replace('.', ' '),
    ])
    ctx_tokens = {
        t.lower()
        for t in re.findall(r'[a-zA-Z]{3,}', raw_ctx)
    } - _STOP_TOKENS

    if not ctx_tokens:
        return True  # no context to compare against, allow through

    overlap = pr_tokens & ctx_tokens
    return len(overlap) >= _MIN_VOCAB_OVERLAP


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
        list of DuplicateMatch — one per confirmed match, sorted by similarity desc.
        Empty list if circuit open, service error, or no matches pass all filters.

    Never raises — all errors are caught and logged.
    """
    from apps.parsing.embedding_client import get_embeddings_batch
    from apps.parsing.models import CodeChunk
    from pgvector.django import CosineDistance

    # -----------------------------------------------------------------------
    # Step 1: Filter to chunks worth embedding
    # -----------------------------------------------------------------------
    embeddable = [c for c in chunks if _is_embeddable(c)]

    if not embeddable:
        logger.debug("duplicate_detection_no_chunks", repo_id=repo_id)
        return []

    # -----------------------------------------------------------------------
    # Step 2: Batch embed ALL PR chunks in ONE call (Optimization 1 + cache)
    # -----------------------------------------------------------------------
    texts = [c.raw_code for c in embeddable]
    vectors = get_embeddings_batch(texts)

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
    max_distance = round(1.0 - similarity_threshold, 6)
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
                .exclude(file_path=chunk.file_path)
                .annotate(dist=CosineDistance('embedding', vector))
                .filter(dist__lte=max_distance)
                .order_by('dist')
                .values('file_path', 'chunk_name', 'start_line', 'end_line', 'dist')
            )

            # Deduplicate by (file_path, chunk_name) — same function stored once
            # per commit produces N identical matches without this guard.
            seen_targets: set[tuple[str, str]] = set()

            for row in rows:
                key = (row['file_path'], row['chunk_name'])
                if key in seen_targets:
                    continue

                # Apply secondary filters before accepting the match
                if not _passes_secondary_filters(
                    pr_chunk=chunk,
                    match_name=row['chunk_name'],
                    match_file=row['file_path'],
                    match_start=row['start_line'],
                    match_end=row.get('end_line') or row['start_line'],
                ):
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

    all_matches.sort(key=lambda m: m.similarity, reverse=True)

    logger.info(
        "duplicate_detection_complete",
        repo_id=repo_id,
        matches_found=len(all_matches),
        threshold=similarity_threshold,
    )

    return all_matches
