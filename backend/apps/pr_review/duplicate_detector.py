"""
Semantic Duplicate Detection for Pull Requests.

Pipeline
--------
    Orchestrator → find_semantic_duplicates(chunks, repo_id, threshold)
        ↓ batch embed all PR chunks (Optimization 1)
        ↓ per-chunk pgvector ANN query (HNSW — Optimization 6)
        ↓ five secondary filters to eliminate CodeBERT anisotropy false positives
        → list[DuplicateMatch]

Why secondary filters are required
------------------------------------
CodeBERT (microsoft/codebert-base) is a masked-language model, not a similarity
model. Its embeddings are highly anisotropic: all Python/JS functions in the same
codebase cluster in a narrow cone, scoring 0.97–0.99 cosine similarity even when
they implement completely different logic. A cosine threshold alone cannot
distinguish structural false positives from genuine logic duplication.

Five independent secondary signals gate every candidate match:

  1. Intra-module skip  — same Django app (apps/pr_review/, apps/ingestion/)
                          → skip. Functions in the same app share imports and
                          internal abstractions; that similarity is intentional.

  2. File-role filter   ← STRUCTURAL LAYER — added to fix view-vs-task FPs
                          A function in views.py / consumers.py is an HTTP handler
                          that READS and formats data.  A function in tasks.py /
                          services.py / engine.py COMPUTES and WRITES data.
                          These are architecturally opposite roles — they can never
                          be semantic duplicates regardless of score.

                          dashboard/views.py:cluster_map vs clustering/tasks.py:cluster_new_chunks
                          → 'view' vs 'compute' → REJECTED

                          repositories/views.py:list_branches vs ingestion/views.py:list_repos
                          → 'view' vs 'view' → allowed (genuine candidate)

  3. Line-count ratio   — genuinely duplicated logic has similar code length.
                          Functions differing by more than 2.5× are skipped.

  4. Function-name token overlap  ← THE KEY FILTER
                          Split both function names on snake_case/camelCase
                          boundaries. If they share zero meaningful tokens,
                          reject immediately — the names tell us these functions
                          have different semantic purpose regardless of how
                          similar their structure looks to CodeBERT.

                          list_branches   → {list, branch}
                          ingest_repo     → {ingest, repo}
                          Intersection = ∅  → REJECTED

                          embed_chunks    → {embed}        (chunks is a stop word)
                          get_embed_batch → {embed, batch}
                          Intersection = {embed} → passes (genuine candidate)

                          If either name's token set is empty (e.g. "handle",
                          "process") the match is rejected — generic framework
                          method names carry no domain signal.

  5. Body vocabulary overlap (≥ 15%)
                          As a belt-and-suspenders check, the PR chunk's
                          implementation body (docstrings/comments stripped)
                          must share ≥ 15% of the matched function's name tokens.
                          Prevents the few cases where name overlap alone is
                          insufficient.

Blended similarity score
------------------------
The raw CodeBERT cosine similarity is NOT reported directly. Because
CodeBERT is anisotropic (same-language code scores 0.95–0.99 regardless
of logic), the raw score overestimates human-perceived similarity.

Instead, we blend two signals:
  70% CodeBERT cosine   — captures algorithmic intent and control flow
  30% token Jaccard     — captures identifier/variable surface similarity

This yields a calibrated score that aligns with developer intuition:
  - Genuine copy-paste (rename only):      ~92–96%
  - Same algorithm, different abstractions: ~82–90%
  - Similar structure, different domain:   filtered out before scoring
"""
import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_THRESHOLD  = 0.97
_MAX_MATCHES_PER_CHUNK = 5
_MIN_LINES          = 20     # skip trivial short functions
_MIN_COMPLEXITY     = 3      # skip functions with no branching
_MAX_LINE_RATIO     = 2.5    # skip if lengths differ > 2.5×
_MIN_BODY_OVERLAP   = 0.15   # ≥ 15% of match-name tokens in PR body

# Generic tokens excluded from all name/vocabulary comparisons.
# Includes domain-level tokens that appear in virtually every function
# in a repository-management codebase (repo, github, user, branch…).
_STOP = {
    # Python / JS keywords and builtins
    'self', 'true', 'false', 'none', 'null', 'undefined', 'async', 'await',
    'return', 'yield', 'raise', 'pass', 'with', 'import', 'from', 'class',
    'function', 'const', 'let', 'var', 'elif', 'else', 'super', 'this',
    'catch', 'throw', 'void', 'export', 'default', 'static', 'public',
    'private', 'protected', 'type', 'string', 'number', 'boolean',
    # Framework / project-wide ubiquitous terms
    'apps', 'backend', 'frontend', 'views', 'models', 'tasks', 'utils',
    'request', 'response', 'result', 'error', 'value', 'item', 'name',
    'args', 'kwargs', 'params', 'config', 'logger', 'logging', 'data',
    # Domain-level tokens present in almost every function of this codebase
    'repo', 'repository', 'github', 'user', 'branch', 'commit', 'file',
    'path', 'code', 'chunk', 'chunks', 'object', 'list', 'dict', 'array',
    # Ultra-generic function verbs — appear in function names AND in string
    # literals / error messages everywhere, giving zero semantic signal.
    # e.g. "Cannot process a record" puts 'process' in body_tok of ANY
    # function that returns such a message, regardless of what it does.
    'process', 'handle', 'execute', 'perform',
    # Stratum feature-domain labels — present in every function belonging to that
    # feature area (both the read-view AND the compute-task side), so sharing
    # one of these tokens means nothing about shared logic.
    # e.g. cluster_map (view) and cluster_new_chunks (task) both contain 'cluster'
    # but they are architecturally opposite operations.
    'cluster', 'blame', 'debt', 'webhook', 'finding', 'violation',
    'ingest', 'ingestion', 'embed', 'embedding', 'parse', 'parsing',
    'score', 'scores', 'velocity', 'heatmap', 'pipeline',
}


@dataclass
class DuplicateMatch:
    """One confirmed semantic match between a PR chunk and a codebase chunk."""
    file_path:     str
    chunk_name:    str
    line_number:   int
    similar_file:  str
    similar_chunk: str
    similar_line:  int
    similarity:    float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_tokens(name: str) -> set[str]:
    """
    Split a function name into meaningful tokens.
    Handles both snake_case (list_branches) and camelCase (fetchPrFiles).
    Returns lowercase tokens of ≥ 3 chars, minus generic stop words.
    """
    expanded = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)   # camelCase split
    tokens = re.findall(r'[a-zA-Z]{3,}', expanded.replace('_', ' '))
    return {t.lower() for t in tokens} - _STOP


def _strip_noise(raw_code: str, language: str) -> str:
    """Remove docstrings, comments, and import lines from source code."""
    code = raw_code or ''
    if language == 'python':
        code = re.sub(r'"""[\s\S]*?"""', '', code)
        code = re.sub(r"'''[\s\S]*?'''", '', code)
        code = re.sub(r'#[^\n]*', '', code)
        code = '\n'.join(
            l for l in code.splitlines()
            if not re.match(r'^\s*(import |from \S+ import)', l)
        )
    elif language in ('javascript', 'typescript', 'tsx', 'java', 'go',
                      'rust', 'c', 'cpp', 'php', 'ruby'):
        code = re.sub(r'/\*[\s\S]*?\*/', '', code)
        code = re.sub(r'//[^\n]*', '', code)
        if language in ('javascript', 'typescript', 'tsx'):
            code = '\n'.join(
                l for l in code.splitlines()
                if not re.match(r'^\s*import ', l)
            )
    return code


def _body_tokens(chunk) -> set[str]:
    """Meaningful identifier tokens from the function body (noise stripped)."""
    code = _strip_noise(
        getattr(chunk, 'raw_code', '') or '',
        getattr(chunk, 'language', ''),
    )
    tokens = {t.lower() for t in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', code)}
    return tokens - _STOP


def _jaccard_similarity(code1: str, code2: str, language: str) -> float | None:
    """
    Token-level Jaccard similarity between two function bodies.

    Both bodies are noise-stripped first (docstrings, comments, imports) so
    the score reflects identifier and structural token overlap only.
    Returns None when either body is empty (caller falls back to raw cosine).
    """
    clean1 = _strip_noise(code1 or '', language)
    clean2 = _strip_noise(code2 or '', language)
    toks1 = {t.lower() for t in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', clean1)} - _STOP
    toks2 = {t.lower() for t in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', clean2)} - _STOP
    if not toks1 or not toks2:
        return None
    return len(toks1 & toks2) / len(toks1 | toks2)


def _blended_similarity(
    embedding_sim: float,
    pr_raw_code: str,
    match_raw_code: str | None,
    language: str,
) -> float | None:
    """
    Blend CodeBERT cosine similarity (70%) with token Jaccard (30%).

    Returns None when match_raw_code is unavailable AND STORE_RAW_CODE=True.
    The caller treats None as "skip this match" — we cannot produce a reliable
    score without the token side, and falling back to raw CodeBERT cosine causes
    false positives (CodeBERT scores 0.97–0.99 for all same-language functions
    due to embedding anisotropy).

    When STORE_RAW_CODE=False, raw_code is never stored by design; falling back
    to the embedding score is the documented trade-off in that mode.
    """
    if not match_raw_code:
        from django.conf import settings
        if getattr(settings, 'STORE_RAW_CODE', False):
            return None  # raw_code missing despite STORE_RAW_CODE=True — skip
        return embedding_sim  # STORE_RAW_CODE=False: documented fallback
    jaccard = _jaccard_similarity(pr_raw_code or '', match_raw_code, language)
    if jaccard is None:
        return embedding_sim
    return round(0.70 * embedding_sim + 0.30 * jaccard, 4)


def _same_app(file1: str, file2: str) -> bool:
    """True if both files live in the same Django app (apps/<name>/)."""
    def app(path: str):
        parts = path.replace('\\', '/').split('/')
        try:
            i = parts.index('apps')
            return parts[i + 1] if i + 1 < len(parts) else None
        except ValueError:
            return None
    a1, a2 = app(file1), app(file2)
    return a1 is not None and a1 == a2


# File roles — based on filename suffix, not content.
# 'view'    = HTTP handlers that READ data and return responses
# 'compute' = background workers / service functions that WRITE or COMPUTE data
_VIEW_FILE_RE    = re.compile(r'(^|/)views\.py$|(^|/)consumers\.py$|(^|/)serializers\.py$')
_COMPUTE_FILE_RE = re.compile(r'(^|/)tasks\.py$|(^|/)services\.py$|(^|/)engine\.py$|(^|/)engines\.py$|(^|/)workers\.py$')


def _file_role(path: str) -> str:
    """
    Classify a file as 'view', 'compute', or 'other' based on its filename.

    'view'    — views.py / consumers.py: read-only HTTP/WebSocket handlers
    'compute' — tasks.py / services.py / engine.py: background compute workers
    'other'   — anything else (models, admin, migrations, helpers, etc.)

    A 'view' function and a 'compute' function operating on the same domain
    are architecturally opposite: one reads + formats, the other writes +
    computes.  They are never semantic duplicates of each other.
    """
    normalized = path.replace('\\', '/').lower()
    if _VIEW_FILE_RE.search(normalized):
        return 'view'
    if _COMPUTE_FILE_RE.search(normalized):
        return 'compute'
    return 'other'


def _is_embeddable(chunk) -> bool:
    if not getattr(chunk, 'raw_code', None) or not chunk.raw_code.strip():
        return False
    lines = getattr(chunk, 'end_line', 0) - getattr(chunk, 'start_line', 0) + 1
    return lines >= _MIN_LINES and getattr(chunk, 'complexity_score', 1) >= _MIN_COMPLEXITY


def _passes(pr_chunk, match_name: str, match_file: str,
            match_start: int, match_end: int) -> bool:
    """
    Five-signal secondary validation. Returns True to keep, False to discard.
    """
    # 1. Intra-module: same Django app → structural similarity is intentional
    if _same_app(pr_chunk.file_path, match_file):
        return False

    # 2. File-role: HTTP view handlers are never duplicates of compute workers.
    #    A views.py function reads and formats data; a tasks.py/services.py
    #    function computes and writes data.  They operate on the same models but
    #    in opposite directions — no amount of CodeBERT similarity makes them
    #    genuine duplicates.
    pr_role    = _file_role(pr_chunk.file_path)
    match_role = _file_role(match_file)
    if (pr_role != match_role
            and pr_role    != 'other'
            and match_role != 'other'):
        return False

    # 3. Line-count ratio
    pr_lines    = max(1, getattr(pr_chunk, 'end_line', 0) - getattr(pr_chunk, 'start_line', 0) + 1)
    match_lines = max(1, (match_end or match_start) - match_start + 1)
    if max(pr_lines, match_lines) / min(pr_lines, match_lines) > _MAX_LINE_RATIO:
        return False

    # 4. Function-name token overlap — the primary semantic discriminator
    #
    # If either name's token set is empty it means every token is a stop word
    # (e.g. "handle", "process", "Repository", "pr_list").  These names carry
    # zero domain signal — any two functions could share such a name.  Passing
    # them through causes pure-anisotropy false positives that the body-
    # vocabulary check (filter 5) cannot reliably eliminate on its own.
    pr_name_tok    = _name_tokens(pr_chunk.chunk_name)
    match_name_tok = _name_tokens(match_name)

    if not pr_name_tok:
        # PR chunk name has zero meaningful tokens — cannot discriminate.
        return False

    if not match_name_tok:
        # Match name has zero meaningful tokens — cannot discriminate.
        return False

    if not (pr_name_tok & match_name_tok):
        # Names have tokens but share none → different semantic purpose
        return False

    # 5. Body vocabulary overlap (belt-and-suspenders)
    body_tok = _body_tokens(pr_chunk)
    if body_tok and match_name_tok:
        overlap_ratio = len(body_tok & match_name_tok) / len(match_name_tok)
        if overlap_ratio < _MIN_BODY_OVERLAP:
            return False

    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_semantic_duplicates(
    chunks: list,
    repo_id: str,
    similarity_threshold: float = _DEFAULT_THRESHOLD,
) -> list[DuplicateMatch]:
    """
    Embed PR chunks and query pgvector for similar existing functions.
    Every cosine-similarity candidate passes through four secondary filters.
    """
    from apps.parsing.embedding_client import get_embeddings_batch
    from apps.parsing.models import CodeChunk
    from pgvector.django import CosineDistance

    embeddable = [c for c in chunks if _is_embeddable(c)]
    if not embeddable:
        logger.debug("duplicate_detection_no_chunks", repo_id=repo_id)
        return []

    vectors = get_embeddings_batch([c.raw_code for c in embeddable])
    embedded_pairs = [(c, v) for c, v in zip(embeddable, vectors) if v is not None]

    if not embedded_pairs:
        logger.warning("duplicate_detection_no_vectors", repo_id=repo_id,
                       chunk_count=len(embeddable))
        return []

    logger.info("duplicate_detection_embedded", repo_id=repo_id,
                total=len(embeddable), embedded=len(embedded_pairs))

    max_dist = round(1.0 - similarity_threshold, 6)
    all_matches: list[DuplicateMatch] = []

    for chunk, vector in embedded_pairs:
        try:
            rows = (
                CodeChunk.objects
                .filter(
                    repo_id=repo_id,
                    language=chunk.language,
                    embedding__isnull=False,
                    # Only match functions and methods — exclude class/module chunks
                    # that get ingested as top-level nodes (e.g. Django model classes).
                    # Matching against class definitions is never semantically meaningful.
                    chunk_type__in=['function', 'method'],
                )
                .exclude(file_path=chunk.file_path)
                .annotate(dist=CosineDistance('embedding', vector))
                .filter(dist__lte=max_dist)
                .order_by('dist')
                .values('file_path', 'chunk_name', 'start_line', 'end_line', 'dist', 'raw_code')
            )

            seen: set[tuple[str, str]] = set()
            for row in rows:
                key = (row['file_path'], row['chunk_name'])
                if key in seen:
                    continue
                if not _passes(
                    pr_chunk=chunk,
                    match_name=row['chunk_name'],
                    match_file=row['file_path'],
                    match_start=row['start_line'],
                    match_end=row.get('end_line') or row['start_line'],
                ):
                    continue
                seen.add(key)
                embedding_sim = round(1.0 - float(row['dist']), 4)
                similarity = _blended_similarity(
                    embedding_sim=embedding_sim,
                    pr_raw_code=chunk.raw_code,
                    match_raw_code=row.get('raw_code'),
                    language=chunk.language,
                )
                if similarity is None:
                    continue  # raw_code missing — cannot compute reliable score
                all_matches.append(DuplicateMatch(
                    file_path=chunk.file_path,
                    chunk_name=chunk.chunk_name,
                    line_number=chunk.start_line,
                    similar_file=row['file_path'],
                    similar_chunk=row['chunk_name'],
                    similar_line=row['start_line'],
                    similarity=similarity,
                ))
                if len(seen) >= _MAX_MATCHES_PER_CHUNK:
                    break

        except Exception as exc:
            logger.warning("duplicate_search_error",
                           chunk_name=chunk.chunk_name,
                           file_path=chunk.file_path, error=str(exc))

    all_matches.sort(key=lambda m: m.similarity, reverse=True)
    logger.info("duplicate_detection_complete", repo_id=repo_id,
                matches=len(all_matches), threshold=similarity_threshold)
    return all_matches
