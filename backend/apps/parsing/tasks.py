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
    queue="parsing",
    name="apps.parsing.tasks.parse_file",
)
def parse_file(self, repo_id: str, commit_id: str, file_path: str, file_content: str):
    """
    AST-parse a single file and create CodeChunk records.

    Receives file content queued by the ingestion engine.
    Uses the LanguageRouter to select the correct tree-sitter parser,
    extracts all functions/methods/classes, computes cyclomatic complexity,
    and bulk-creates CodeChunk records (Optimization 3).
    """
    from apps.parsing.language_router import get_parser_for_file, should_skip
    from apps.parsing.models import CodeChunk
    from apps.ingestion.models import Commit
    from apps.repositories.models import Repository
    import time

    start_time = time.monotonic()

    logger.info(
        "parse_file_started",
        repo_id=repo_id,
        commit_id=commit_id,
        file_path=file_path,
        content_length=len(file_content),
    )

    language, parser = get_parser_for_file(file_path)
    if not parser:
        logger.info("parse_file_unsupported_language", file_path=file_path)
        return

    if should_skip(file_path, file_content):
        logger.info("parse_file_skipped", file_path=file_path)
        return

    try:
        repo = Repository.objects.get(id=repo_id)
        commit = Commit.objects.get(id=commit_id)
    except (Repository.DoesNotExist, Commit.DoesNotExist) as exc:
        logger.warning("parse_file_record_not_found", repo_id=repo_id, commit_id=commit_id, error=str(exc))
        return

    tree = parser.parse(file_content.encode("utf-8", errors="replace"))
    chunks = _extract_chunks(tree, file_content, file_path, language, repo, commit)

    if chunks:
        # Principle 1: idempotency — skip_conflicts silently skips existing rows
        CodeChunk.objects.bulk_create(chunks, batch_size=settings.DB_BULK_CREATE_BATCH_SIZE, ignore_conflicts=True)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "parse_file_done",
        repo_id=repo_id,
        commit_id=commit_id,
        file_path=file_path,
        chunks_created=len(chunks),
        language=language,
        duration_ms=duration_ms,
    )

    commit.is_processed = True
    commit.save(update_fields=["is_processed"])


def _extract_chunks(tree, file_content: str, file_path: str, language: str, repo, commit) -> list:
    """
    Walk the tree-sitter AST and extract function/method/class definitions.

    Returns a list of unsaved CodeChunk instances for bulk_create.
    """
    from django.conf import settings
    from apps.parsing.models import CodeChunk

    lines = file_content.splitlines()
    chunks = []

    # Node types that represent top-level code units across all 10 languages
    _FUNCTION_TYPES = {
        "function_definition",       # Python
        "function_declaration",      # JS, TS, Go, C, C++, Rust
        "method_definition",         # JS, TS, Ruby
        "method_declaration",        # Java
        "arrow_function",            # JS, TS
        "func_literal",              # Go
        "function_item",             # Rust
    }
    _CLASS_TYPES = {
        "class_definition",          # Python
        "class_declaration",         # JS, TS, Java, PHP
        "class_body",                # Ruby (used as outer node)
        "struct_item",               # Rust
        "type_declaration",          # Go
    }

    def walk(node):
        if node.type in _FUNCTION_TYPES:
            chunk = _node_to_chunk(
                node, lines, file_path, language,
                CodeChunk.ChunkType.FUNCTION, repo, commit,
            )
            if chunk:
                chunks.append(chunk)
            return  # don't recurse into nested functions

        if node.type in _CLASS_TYPES:
            chunk = _node_to_chunk(
                node, lines, file_path, language,
                CodeChunk.ChunkType.CLASS, repo, commit,
            )
            if chunk:
                chunks.append(chunk)

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return chunks


def _node_to_chunk(node, lines: list, file_path: str, language: str, chunk_type: str, repo, commit):
    """Convert a tree-sitter node into a CodeChunk instance."""
    from django.conf import settings
    from apps.parsing.models import CodeChunk

    start_line = node.start_point[0]   # 0-indexed
    end_line = node.end_point[0]       # 0-indexed

    chunk_name = _extract_name(node, language)
    if not chunk_name:
        return None

    raw_code = "\n".join(lines[start_line : end_line + 1])
    complexity = _cyclomatic_complexity(node)

    return CodeChunk(
        commit=commit,
        repo=repo,
        file_path=file_path,
        chunk_name=chunk_name,
        chunk_type=chunk_type,
        language=language,
        start_line=start_line + 1,   # store 1-indexed
        end_line=end_line + 1,
        complexity_score=float(complexity),
        raw_code=raw_code if settings.STORE_RAW_CODE else None,
        embedding=None,              # filled in Phase 3 by embedding microservice
    )


def _extract_name(node, language: str) -> str:
    """Extract the name identifier from a function/class node."""
    # Most languages store the name as a direct child with type 'identifier' or 'name'
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier", "type_identifier"):
            return child.text.decode("utf-8", errors="replace")
    return ""


def _cyclomatic_complexity(node) -> int:
    """
    Approximate cyclomatic complexity: 1 + number of branch points.

    Counts: if, elif, else, for, while, case, catch, and, or, &&, ||, ?
    """
    _BRANCH_TYPES = {
        "if_statement", "elif_clause", "else_clause",
        "for_statement", "while_statement", "do_statement",
        "case_clause", "catch_clause", "except_clause",
        "conditional_expression", "ternary_expression",
        "binary_expression",  # filtered below for && / ||
        "and", "or",
    }
    _BINARY_BRANCH_OPERATORS = {"&&", "||", "and", "or"}

    count = 1  # baseline

    def recurse(n):
        nonlocal count
        if n.type in _BRANCH_TYPES:
            if n.type == "binary_expression":
                op = n.children[1].text.decode("utf-8", errors="replace") if len(n.children) > 1 else ""
                if op in _BINARY_BRANCH_OPERATORS:
                    count += 1
            else:
                count += 1
        for child in n.children:
            recurse(child)

    recurse(node)
    return count
