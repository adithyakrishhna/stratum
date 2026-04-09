"""
Semantic Duplicate Detection for Pull Requests.

Pipeline
--------
    Orchestrator → find_semantic_duplicates(chunks, repo_id, threshold)
        ↓ batch embed all PR chunks (Optimization 1)
        ↓ per-chunk pgvector ANN query (HNSW — Optimization 6)
        ↓ four secondary filters to eliminate CodeBERT anisotropy false positives
        → list[DuplicateMatch]

Why secondary filters are required
------------------------------------
CodeBERT (microsoft/codebert-base) is a masked-language model, not a similarity
model. Its embeddings are highly anisotropic: all Python/JS functions in the same
codebase cluster in a narrow cone, scoring 0.97–0.99 cosine similarity even when
they implement completely different logic. A cosine threshold alone cannot
distinguish structural false positives from genuine logic duplication.

Four independent secondary signals gate every candidate match:

  1. Intra-module skip  — same Django app (apps/pr_review/, apps/ingestion/)
                          → skip. Functions in the same app share imports and
                          internal abstractions; that similarity is intentional.

  2. Line-count ratio   — genuinely duplicated logic has similar code length.
                          Functions differing by more than 2.5× are skipped.

  3. Function-name token overlap  ← THE KEY FILTER
                          Split both function names on snake_case/camelCase
                          boundaries. If they share zero meaningful tokens,
                          reject immediately — the names tell us these functions
                          have different semantic purpose regardless of how
                          similar their structure looks to CodeBERT.

                          list_branches   → {list, branch}
                          ingest_repo     → {ingest, repo}
                          Intersection = ∅  → REJECTED

                          embed_chunks    → {embed, chunk}
                          get_embed_batch → {embed, batch}
                          Intersection = {embed} → passes (genuine candidate)

  4. Body vocabulary overlap (≥ 15%)
                          As a belt-and-suspenders check, the PR chunk's
                          implementation body (docstrings/comments stripped)
                          must share ≥ 15% of the matched function's name tokens.
                          Prevents the few cases where name overlap alone is
                          insufficient.
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
    'path', 'code', 'chunk', 'object', 'list', 'dict', 'array',
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


def _is_embeddable(chunk) -> bool:
    if not getattr(chunk, 'raw_code', None) or not chunk.raw_code.strip():
        return False
    lines = getattr(chunk, 'end_line', 0) - getattr(chunk, 'start_line', 0) + 1
    return lines >= _MIN_LINES and getattr(chunk, 'complexity_score', 1) >= _MIN_COMPLEXITY


def _passes(pr_chunk, match_name: str, match_file: str,
            match_start: int, match_end: int) -> bool:
    """
    Four-signal secondary validation. Returns True to keep, False to discard.
    """
    # 1. Intra-module: same Django app → structural similarity is intentional
    if _same_app(pr_chunk.file_path, match_file):
        return False

    # 2. Line-count ratio
    pr_lines    = max(1, getattr(pr_chunk, 'end_line', 0) - getattr(pr_chunk, 'start_line', 0) + 1)
    match_lines = max(1, (match_end or match_start) - match_start + 1)
    if max(pr_lines, match_lines) / min(pr_lines, match_lines) > _MAX_LINE_RATIO:
        return False

    # 3. Function-name token overlap — the primary semantic discriminator
    pr_name_tok    = _name_tokens(pr_chunk.chunk_name)
    match_name_tok = _name_tokens(match_name)
    if pr_name_tok and match_name_tok and not (pr_name_tok & match_name_tok):
        # Names share zero meaningful tokens → different semantic purpose
        return False

    # 4. Body vocabulary overlap (belt-and-suspenders)
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
                .filter(repo_id=repo_id, language=chunk.language, embedding__isnull=False)
                .exclude(file_path=chunk.file_path)
                .annotate(dist=CosineDistance('embedding', vector))
                .filter(dist__lte=max_dist)
                .order_by('dist')
                .values('file_path', 'chunk_name', 'start_line', 'end_line', 'dist')
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
                all_matches.append(DuplicateMatch(
                    file_path=chunk.file_path,
                    chunk_name=chunk.chunk_name,
                    line_number=chunk.start_line,
                    similar_file=row['file_path'],
                    similar_chunk=row['chunk_name'],
                    similar_line=row['start_line'],
                    similarity=round(1.0 - float(row['dist']), 4),
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
