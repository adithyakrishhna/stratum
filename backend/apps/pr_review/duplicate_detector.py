"""
Semantic Duplicate Detection for Pull Requests.

Pipeline
--------
    Orchestrator collects _SimpleChunk objects (with raw_code) across all PR files
        ↓
    find_semantic_duplicates(chunks, repo_id, threshold)
        ↓ one batch embedding call (Optimization 1 — cache + embedding service)
    get_embeddings_batch(all_texts)
        ↓ per-chunk pgvector ANN query (HNSW — Optimization 6)
    CodeChunk.objects.annotate(dist=CosineDistance(...)).filter(dist__lte=max_dist)
        ↓ three secondary filters (size ratio, intra-module skip, vocabulary overlap)
    list[DuplicateMatch]

Why secondary filters are required
------------------------------------
CodeBERT (microsoft/codebert-base) is a masked-language model, not a similarity
model. Its embeddings are highly anisotropic: all Python code clusters in a narrow
cone, so structurally similar functions (Django views, React components, task
functions) score 0.95-0.99 cosine similarity even when they implement completely
different logic. A cosine threshold alone cannot eliminate false positives.

Three independent secondary signals confirm each candidate:

  1. Line-count ratio (≤ 2.5×)
     Genuinely duplicated logic has similar code length. A 30-line view cannot
     be a copy of a 200-line orchestrator.

  2. Intra-module skip
     Functions in the same Django app directory (apps/pr_review/, apps/parsing/)
     are compared separately at the design level. Cross-module duplication is the
     signal we care about for PR review.

  3. Vocabulary overlap (≥ 15% of match-context tokens)
     The PR chunk's BODY identifiers (docstrings and imports stripped) must share
     at least 15% of the matched function's name+module tokens. Completely
     different-purpose functions share zero domain vocabulary.
     Docstrings are stripped because they often reference other modules by name
     (e.g. a docstring example mentioning "orchestrator") which would otherwise
     produce false overlaps.
"""
import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_THRESHOLD  = 0.97   # cosine floor — then all three secondary filters apply
_MAX_MATCHES_PER_CHUNK = 5   # top-N unique cross-module matches per PR chunk
_MIN_LINES          = 20     # skip short boilerplate-heavy functions
_MIN_COMPLEXITY     = 3      # skip trivial functions with no branching
_MAX_LINE_RATIO     = 2.5    # skip if lengths differ > 2.5×
_MIN_VOCAB_OVERLAP  = 0.15   # require ≥ 15% of match-context tokens in PR body

# Tokens that appear in virtually every function regardless of purpose.
# Removing these prevents accidental matches via common programming vocabulary.
_STOP_TOKENS = {
    'self', 'true', 'false', 'none', 'null', 'undefined', 'async', 'await',
    'return', 'yield', 'raise', 'pass', 'with', 'import', 'from', 'class',
    'function', 'const', 'let', 'var', 'elif', 'else', 'super', 'type',
    'this', 'that', 'then', 'catch', 'throw', 'void', 'export', 'default',
    'static', 'public', 'private', 'protected', 'final', 'abstract',
    'string', 'number', 'boolean', 'object', 'array', 'list', 'dict',
    'request', 'response', 'result', 'error', 'value', 'item', 'name',
    'args', 'kwargs', 'params', 'config', 'logger', 'logging',
    'apps', 'backend', 'frontend', 'views', 'models', 'tasks', 'utils',
}


@dataclass
class DuplicateMatch:
    """One confirmed semantic match between a PR chunk and a codebase chunk."""
    file_path:     str    # PR file
    chunk_name:    str    # function name in PR
    line_number:   int    # start line in PR file
    similar_file:  str    # matched file in codebase
    similar_chunk: str    # matched function name
    similar_line:  int    # start line in matched file
    similarity:    float  # 0.0–1.0 (rounded to 4 dp)


# ---------------------------------------------------------------------------
# Secondary filter helpers
# ---------------------------------------------------------------------------

def _strip_noise(raw_code: str, language: str) -> str:
    """
    Remove docstrings, comments, and import lines from raw source code.

    Docstrings often reference other modules by name (e.g. "see orchestrator.py")
    which contaminates vocabulary extraction and produces false overlaps.
    Import lines reference every module in the codebase, so they dilute the
    function-specific vocabulary signal.
    """
    code = raw_code or ''

    if language == 'python':
        code = re.sub(r'"""[\s\S]*?"""', '', code)    # triple-quote docstrings
        code = re.sub(r"'''[\s\S]*?'''", '', code)    # single-quote docstrings
        code = re.sub(r'#[^\n]*', '', code)            # line comments
        code = '\n'.join(
            line for line in code.splitlines()
            if not re.match(r'^\s*(import |from \S+ import)', line)
        )
    elif language in ('javascript', 'typescript', 'tsx'):
        code = re.sub(r'/\*[\s\S]*?\*/', '', code)    # block comments
        code = re.sub(r'//[^\n]*', '', code)           # line comments
        code = '\n'.join(
            line for line in code.splitlines()
            if not re.match(r'^\s*import ', line)
        )
    elif language in ('java', 'go', 'rust', 'c', 'cpp', 'php'):
        code = re.sub(r'/\*[\s\S]*?\*/', '', code)
        code = re.sub(r'//[^\n]*', '', code)

    return code


def _body_tokens(chunk) -> set[str]:
    """
    Extract meaningful identifier tokens from a chunk's implementation body.
    Strips docstrings, comments, and imports first so only logic-level tokens remain.
    """
    code = _strip_noise(getattr(chunk, 'raw_code', '') or '', getattr(chunk, 'language', ''))
    tokens = {t.lower() for t in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b', code)}
    return tokens - _STOP_TOKENS


def _match_context_tokens(match_name: str, match_file: str) -> set[str]:
    """
    Derive context tokens from the matched function's name and module path.
    Splits snake_case and camelCase into individual words.
    """
    raw = ' '.join([
        re.sub(r'([a-z])([A-Z])', r'\1 \2', match_name),   # camelCase split
        match_name,                                           # snake_case split
        match_file.replace('/', ' ').replace('_', ' ').replace('.', ' '),
    ])
    tokens = {t.lower() for t in re.findall(r'[a-zA-Z]{3,}', raw)}
    return tokens - _STOP_TOKENS


def _intra_app_match(file1: str, file2: str) -> bool:
    """
    Return True if both files are in the same Django app directory.

    Functions within the same app (apps/pr_review/, apps/parsing/) share
    internal abstractions and imports, which makes CodeBERT embeddings
    similar for non-duplicate reasons. We only flag cross-app duplication.
    """
    def app_name(path: str):
        parts = path.replace('\\', '/').split('/')
        try:
            idx = parts.index('apps')
            return parts[idx + 1] if idx + 1 < len(parts) else None
        except ValueError:
            return None

    a1, a2 = app_name(file1), app_name(file2)
    return a1 is not None and a1 == a2


def _is_embeddable(chunk) -> bool:
    """Return True if the chunk is worth embedding (not trivial boilerplate)."""
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
    Three-signal secondary validation after cosine similarity passes.
    Returns True if the match should be kept; False to discard.
    """
    # Filter 1 — intra-module: same Django app → skip
    if _intra_app_match(pr_chunk.file_path, match_file):
        return False

    # Filter 2 — line-count ratio: genuinely duplicated logic has similar length
    pr_lines    = max(1, getattr(pr_chunk, 'end_line', 0) - getattr(pr_chunk, 'start_line', 0) + 1)
    match_lines = max(1, (match_end or match_start) - match_start + 1)
    if max(pr_lines, match_lines) / min(pr_lines, match_lines) > _MAX_LINE_RATIO:
        return False

    # Filter 3 — vocabulary overlap: PR body tokens must share ≥ 15% of match context
    pr_tokens  = _body_tokens(pr_chunk)
    ctx_tokens = _match_context_tokens(match_name, match_file)

    if not pr_tokens or not ctx_tokens:
        return True   # can't verify — allow through rather than silently drop

    overlap_ratio = len(pr_tokens & ctx_tokens) / len(ctx_tokens)
    return overlap_ratio >= _MIN_VOCAB_OVERLAP


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

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
        similarity_threshold: minimum cosine similarity [0.0, 1.0]

    Returns:
        list of DuplicateMatch sorted by similarity desc.
        Empty list on error, circuit open, or no confirmed matches.
    """
    from apps.parsing.embedding_client import get_embeddings_batch
    from apps.parsing.models import CodeChunk
    from pgvector.django import CosineDistance

    embeddable = [c for c in chunks if _is_embeddable(c)]
    if not embeddable:
        logger.debug("duplicate_detection_no_chunks", repo_id=repo_id)
        return []

    # Batch embed — one HTTP call for all PR chunks (Optimization 1)
    vectors = get_embeddings_batch([c.raw_code for c in embeddable])
    embedded_pairs = [(c, v) for c, v in zip(embeddable, vectors) if v is not None]

    if not embedded_pairs:
        logger.warning("duplicate_detection_no_vectors", repo_id=repo_id,
                       chunk_count=len(embeddable), reason="all embeddings unavailable")
        return []

    logger.info("duplicate_detection_embedded", repo_id=repo_id,
                total_chunks=len(embeddable), embedded_count=len(embedded_pairs))

    max_distance = round(1.0 - similarity_threshold, 6)
    all_matches: list[DuplicateMatch] = []

    for chunk, vector in embedded_pairs:
        try:
            rows = (
                CodeChunk.objects
                .filter(repo_id=repo_id, language=chunk.language, embedding__isnull=False)
                .exclude(file_path=chunk.file_path)
                .annotate(dist=CosineDistance('embedding', vector))
                .filter(dist__lte=max_distance)
                .order_by('dist')
                .values('file_path', 'chunk_name', 'start_line', 'end_line', 'dist')
            )

            # Deduplicate: same function stored once per commit → N identical rows
            seen: set[tuple[str, str]] = set()

            for row in rows:
                key = (row['file_path'], row['chunk_name'])
                if key in seen:
                    continue

                if not _passes_secondary_filters(
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
                           file_path=chunk.file_path,
                           error=str(exc))

    all_matches.sort(key=lambda m: m.similarity, reverse=True)
    logger.info("duplicate_detection_complete", repo_id=repo_id,
                matches_found=len(all_matches), threshold=similarity_threshold)
    return all_matches
