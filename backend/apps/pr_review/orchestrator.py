"""
PR Review Orchestrator — ties together all analysis components.

Pipeline per PR:
  1.  Create/update PullRequest DB record
  2.  Check embedding service circuit breaker state
  3.  Fetch changed files via GitHub API
  4.  For each file (skip list checked):
        a. Run security scanner  → list[SecurityFinding]
        b. Load stratum.yaml rules → evaluate imports → list[RuleViolationData]
        c. Parse AST chunks       → evaluate each chunk → list[RuleViolationData]
  5.  For critical/high findings: get Groq fix suggestion (cached)
  6.  Persist all findings as PrFinding records (get_or_create — idempotent)
  7.  Calculate health score (100 minus weighted deductions)
  8.  Build inline review comments + severity-grouped summary
        (includes degradation note if semantic analysis was skipped)
  9.  Post single GitHub review (inline + summary)
  10. Update PullRequest.health_score + reviewed_at

Graceful degradation (Principle 8):
  - If embedding circuit OPEN → skip semantic duplicate detection,
    post note on PR, still deliver security + rule findings
  - If GitHub API fails to post review → findings still saved in DB
  - If Groq fails → finding posted without suggestion
  - Each file is wrapped in try/except → one bad file never stops the review
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Severity deduction weights for health score
_DEDUCTIONS = {
    "critical": 20,
    "high":      10,
    "medium":     5,
    "low":        2,
    "info":       0,
}

# Severity ordering for display (critical first)
_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


@dataclass
class _FileFinding:
    """Internal — aggregated finding before DB persistence."""
    file_path: str
    line_number: Optional[int]
    finding_type: str     # maps to PrFinding.FindingType choices
    severity: str
    title: str
    description: str
    suggestion: str = ""


def run_pr_review(
    repo_id: str,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    pr_data: dict,
) -> None:
    """
    Entry point called by the Celery task.

    Args:
        repo_id:          Stratum Repository UUID string
        installation_id:  GitHub App installation ID
        repo_full_name:   "owner/repo" string
        pr_number:        GitHub PR number (integer)
        pr_data:          Raw GitHub pull_request payload dict
    """
    start_ts = time.monotonic()

    from apps.repositories.models import Repository
    from apps.pr_review.models import PullRequest, PrFinding
    from apps.pr_review.github_client import fetch_pr_files, post_pr_review, ReviewComment
    from apps.pr_review.groq_client import get_fix_suggestion
    from apps.pr_review.circuit_breaker import is_embedding_available, get_circuit_state
    from apps.security.scanner import scan_file
    from apps.rules.loader import load_rules
    from apps.rules.evaluator import evaluate_file_imports, evaluate_chunk, RuleViolationData
    from apps.parsing.language_router import get_language, should_skip

    logger.info(
        "pr_review_started",
        repo_id=repo_id,
        repo=repo_full_name,
        pr_number=pr_number,
    )

    # ------------------------------------------------------------------
    # Step 1: Create/update PullRequest record
    # ------------------------------------------------------------------
    repo = Repository.objects.get(id=repo_id)
    head_sha = pr_data.get("head", {}).get("sha", "")
    opened_at_str = pr_data.get("created_at", "")
    try:
        opened_at = datetime.fromisoformat(opened_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        opened_at = datetime.now(timezone.utc)

    pr_record, _ = PullRequest.objects.get_or_create(
        repo=repo,
        github_pr_number=pr_number,
        defaults={
            "title": pr_data.get("title", "")[:1024],
            "author": pr_data.get("user", {}).get("login", ""),
            "base_branch": pr_data.get("base", {}).get("ref", ""),
            "head_branch": pr_data.get("head", {}).get("ref", ""),
            "status": PullRequest.Status.ANALYZING,
            "opened_at": opened_at,
        },
    )
    pr_record.status = PullRequest.Status.ANALYZING
    pr_record.save(update_fields=["status"])

    # ------------------------------------------------------------------
    # Step 2: Check embedding service circuit breaker (Principle 5 + 8)
    # ------------------------------------------------------------------
    semantic_available = is_embedding_available()

    if not semantic_available:
        logger.warning(
            "pr_review_semantic_skipped",
            repo_id=repo_id,
            pr_number=pr_number,
            circuit_state=get_circuit_state(),
            reason="embedding_circuit_open",
        )
    else:
        logger.info(
            "pr_review_semantic_available",
            repo_id=repo_id,
            pr_number=pr_number,
            circuit_state=get_circuit_state(),
        )

    # ------------------------------------------------------------------
    # Step 3: Fetch changed files
    # ------------------------------------------------------------------
    try:
        pr_files = fetch_pr_files(installation_id, repo_full_name, pr_number, head_sha)
    except Exception as exc:
        logger.error(
            "pr_review_fetch_files_failed",
            repo_id=repo_id,
            pr_number=pr_number,
            error=str(exc),
        )
        pr_record.status = PullRequest.Status.OPEN
        pr_record.save(update_fields=["status"])
        raise

    # ------------------------------------------------------------------
    # Step 4: Load rules config once — shared across all files
    # ------------------------------------------------------------------
    try:
        rules_config = load_rules(repo_id)
    except Exception as exc:
        logger.warning(
            "pr_review_rules_load_failed",
            repo_id=repo_id,
            error=str(exc),
        )
        rules_config = {}

    # ------------------------------------------------------------------
    # Step 5: Analyse each changed file
    # ------------------------------------------------------------------
    all_findings: list[_FileFinding] = []
    all_pr_chunks: list = []   # collected for semantic duplicate detection (Step 5b)

    for pr_file in pr_files:
        if pr_file.status == "removed" or not pr_file.content:
            continue

        language = get_language(pr_file.filename)
        if not language:
            continue

        if should_skip(pr_file.filename, pr_file.content):
            logger.debug("pr_review_file_skipped", filename=pr_file.filename)
            continue

        try:
            file_findings, file_chunks = _analyse_file(
                file_path=pr_file.filename,
                content=pr_file.content,
                language=language,
                rules_config=rules_config,
            )
            all_findings.extend(file_findings)
            all_pr_chunks.extend(file_chunks)
        except Exception as exc:
            logger.warning(
                "pr_review_file_analysis_failed",
                filename=pr_file.filename,
                language=language,
                error=str(exc),
            )
            continue

    logger.info(
        "pr_review_analysis_complete",
        repo_id=repo_id,
        pr_number=pr_number,
        total_findings=len(all_findings),
        pr_chunks_collected=len(all_pr_chunks),
    )

    # ------------------------------------------------------------------
    # Step 5b: Semantic duplicate detection (Principle 8 — skip if circuit open)
    # ------------------------------------------------------------------
    duplicate_matches = []

    if semantic_available and all_pr_chunks:
        try:
            from apps.pr_review.duplicate_detector import find_semantic_duplicates

            similarity_threshold = float(
                rules_config.get("similarity_threshold", 0.85)
            )
            duplicate_matches = find_semantic_duplicates(
                chunks=all_pr_chunks,
                repo_id=repo_id,
                similarity_threshold=similarity_threshold,
            )

            # Convert DuplicateMatch → _FileFinding so they flow through
            # the same persist + comment pipeline as security/rule findings
            for dm in duplicate_matches:
                pct = int(dm.similarity * 100)
                all_findings.append(_FileFinding(
                    file_path=dm.file_path,
                    line_number=dm.line_number,
                    finding_type="duplicate",
                    severity="medium",
                    title=f"Duplicate logic: {dm.chunk_name} ({pct}% match)",
                    description=(
                        f"Function `{dm.chunk_name}` is semantically similar to "
                        f"`{dm.similar_chunk}` in `{dm.similar_file}` "
                        f"(line {dm.similar_line}, {pct}% similarity). "
                        f"Consider consolidating to reduce duplication."
                    ),
                ))

            if duplicate_matches:
                logger.info(
                    "pr_review_duplicates_found",
                    repo_id=repo_id,
                    pr_number=pr_number,
                    count=len(duplicate_matches),
                )
        except Exception as exc:
            logger.warning(
                "pr_review_duplicate_detection_failed",
                repo_id=repo_id,
                pr_number=pr_number,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Step 6: Get Groq suggestions for critical + high (cached)
    # ------------------------------------------------------------------
    for f in all_findings:
        if f.severity in ("critical", "high") and not f.suggestion:
            f.suggestion = get_fix_suggestion(
                finding_type=f.finding_type,
                severity=f.severity,
                title=f.title,
                description=f.description,
                code_snippet="",
                language="",
            )

    # ------------------------------------------------------------------
    # Step 7: Persist findings (idempotent via get_or_create)
    # ------------------------------------------------------------------
    finding_type_map = {
        "security":   PrFinding.FindingType.SECURITY,
        "rule":       PrFinding.FindingType.RULE,
        "complexity": PrFinding.FindingType.COMPLEXITY,
        "duplicate":  PrFinding.FindingType.DUPLICATE,
    }

    for f in all_findings:
        db_type = finding_type_map.get(f.finding_type, PrFinding.FindingType.RULE)
        PrFinding.objects.get_or_create(
            pr=pr_record,
            file_path=f.file_path,
            line_number=f.line_number,
            finding_type=db_type,
            title=f.title,
            defaults={
                "severity": f.severity,
                "description": f.description,
                "suggestion": f.suggestion,
            },
        )

    # ------------------------------------------------------------------
    # Step 8: Calculate health score
    # ------------------------------------------------------------------
    deduction = sum(_DEDUCTIONS.get(f.severity, 0) for f in all_findings)
    health_score = max(0.0, 100.0 - deduction)

    # ------------------------------------------------------------------
    # Step 9: Build review body + inline comments
    # ------------------------------------------------------------------
    inline_comments = _build_inline_comments(all_findings)
    summary_body = _build_summary_body(
        pr_number=pr_number,
        health_score=health_score,
        findings=all_findings,
        duplicate_matches=duplicate_matches,
        semantic_skipped=not semantic_available,
    )

    # ------------------------------------------------------------------
    # Step 10: Post review to GitHub
    # ------------------------------------------------------------------
    try:
        review_id = post_pr_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            inline_comments=inline_comments,
            summary_body=summary_body,
        )
        if review_id:
            # Store the GitHub comment ID on first finding for reference
            first_finding = PrFinding.objects.filter(pr=pr_record).first()
            if first_finding and first_finding.github_comment_id is None:
                first_finding.github_comment_id = review_id
                first_finding.save(update_fields=["github_comment_id"])
    except Exception as exc:
        # Degradation: findings are saved; only GitHub posting failed
        logger.error(
            "pr_review_post_failed",
            repo_id=repo_id,
            pr_number=pr_number,
            error=str(exc),
        )

    # ------------------------------------------------------------------
    # Step 11: Update PullRequest record
    # ------------------------------------------------------------------
    pr_record.health_score = health_score
    pr_record.status = PullRequest.Status.OPEN
    pr_record.reviewed_at = datetime.now(timezone.utc)
    pr_record.save(update_fields=["health_score", "status", "reviewed_at"])

    elapsed_ms = int((time.monotonic() - start_ts) * 1000)
    logger.info(
        "pr_review_complete",
        repo_id=repo_id,
        repo=repo_full_name,
        pr_number=pr_number,
        health_score=health_score,
        findings=len(all_findings),
        duration_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _analyse_file(
    file_path: str,
    content: str,
    language: str,
    rules_config: dict,
) -> tuple[list[_FileFinding], list]:
    """
    Run all analysis passes on a single file.

    Returns:
        (findings, chunks) — findings are PrFinding-ready objects;
        chunks are _SimpleChunk objects carrying raw_code for semantic embedding.

    Passes:
      A. Security scanner (6 detectors)
      B. Forbidden import check (stratum.yaml rules)
      C. AST chunk parse → per-chunk rules (length, complexity, naming)
         Also returns the parsed chunks for semantic duplicate detection.
    """
    from apps.security.scanner import scan_file
    from apps.rules.evaluator import evaluate_file_imports, evaluate_chunk
    from apps.parsing.language_router import get_parser

    findings: list[_FileFinding] = []
    file_chunks: list = []

    # Pass A — Security detection
    try:
        sec_findings = scan_file(file_path, content, language)
        for sf in sec_findings:
            findings.append(_FileFinding(
                file_path=sf.file_path,
                line_number=sf.line_number,
                finding_type="security",
                severity=sf.severity,
                title=sf.title,
                description=sf.description,
            ))
    except Exception as exc:
        logger.warning("security_scan_error", file_path=file_path, error=str(exc))

    # Pass B — Forbidden imports
    if rules_config:
        try:
            import_violations = evaluate_file_imports(file_path, content, language, rules_config)
            for rv in import_violations:
                findings.append(_FileFinding(
                    file_path=rv.file_path,
                    line_number=rv.line_number,
                    finding_type="rule",
                    severity=rv.severity,
                    title=f"Forbidden import: {rv.rule_name}",
                    description=rv.message,
                ))
        except Exception as exc:
            logger.warning("import_check_error", file_path=file_path, error=str(exc))

    # Pass C — AST chunk rules + collect chunks for semantic embedding
    try:
        parser = get_parser(language)
        tree = parser.parse(content.encode("utf-8"))
        file_chunks = _extract_lightweight_chunks(tree, content, language, file_path)

        if rules_config:
            for chunk in file_chunks:
                chunk_violations = evaluate_chunk(chunk, rules_config)
                for rv in chunk_violations:
                    ftype = "complexity" if "complexity" in rv.rule_name else "rule"
                    findings.append(_FileFinding(
                        file_path=rv.file_path,
                        line_number=rv.line_number,
                        finding_type=ftype,
                        severity=rv.severity,
                        title=rv.message.split(".")[0],
                        description=rv.message,
                    ))
    except Exception as exc:
        logger.warning("chunk_rule_check_error", file_path=file_path, error=str(exc))

    return findings, file_chunks


def _extract_lightweight_chunks(tree, content: str, language: str, file_path: str) -> list:
    """
    Walk the tree-sitter parse tree and return lightweight chunk dicts
    compatible with evaluate_chunk().

    We reuse the same chunk shape as apps.parsing.models.CodeChunk but as
    plain objects (no DB access needed for PR-time evaluation).
    """
    from dataclasses import make_dataclass

    lines = content.splitlines()
    chunks = []

    # Node types that represent named callable units across our 10 languages
    _FUNCTION_TYPES = {
        "python":     {"function_definition", "async_function_definition"},
        "javascript": {"function_declaration", "function_expression", "arrow_function", "method_definition"},
        "typescript": {"function_declaration", "function_expression", "arrow_function", "method_definition"},
        "tsx":        {"function_declaration", "function_expression", "arrow_function", "method_definition"},
        "java":       {"method_declaration", "constructor_declaration"},
        "go":         {"function_declaration", "method_declaration"},
        "rust":       {"function_item"},
        "c":          {"function_definition"},
        "cpp":        {"function_definition"},
        "ruby":       {"method", "singleton_method"},
        "php":        {"function_definition", "method_declaration"},
    }

    target_types = _FUNCTION_TYPES.get(language, set())
    if not target_types:
        return chunks

    def _walk(node):
        if node.type in target_types:
            # Try to extract the function name
            name_node = node.child_by_field_name("name")
            chunk_name = name_node.text.decode("utf-8") if name_node else "(anonymous)"

            start_line = node.start_point[0] + 1  # tree-sitter is 0-indexed
            end_line = node.end_point[0] + 1
            raw_code = content[node.start_byte:node.end_byte]

            # Lightweight complexity: count decision keywords
            complexity = _count_complexity(raw_code, language)

            chunks.append(_SimpleChunk(
                chunk_name=chunk_name,
                start_line=start_line,
                end_line=end_line,
                complexity_score=float(complexity),
                file_path=file_path,
                language=language,
                raw_code=raw_code,   # captured above for embedding
            ))

        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return chunks


class _SimpleChunk:
    """Minimal chunk object compatible with evaluate_chunk() and duplicate_detector."""
    __slots__ = ("chunk_name", "start_line", "end_line", "complexity_score", "file_path", "language", "raw_code")

    def __init__(self, chunk_name, start_line, end_line, complexity_score, file_path, language, raw_code=""):
        self.chunk_name = chunk_name
        self.start_line = start_line
        self.end_line = end_line
        self.complexity_score = complexity_score
        self.file_path = file_path
        self.language = language
        self.raw_code = raw_code   # needed by duplicate_detector for embedding


def _count_complexity(code: str, language: str) -> int:
    """
    Estimate cyclomatic complexity by counting branching keywords.
    Returns a count ≥ 1 (a function with no branches has complexity 1).
    """
    import re
    _BRANCH_PATTERNS = {
        "python":     r"\b(if|elif|for|while|except|and|or|with)\b",
        "javascript": r"\b(if|else if|for|while|catch|&&|\|\||\?)\b",
        "typescript": r"\b(if|else if|for|while|catch|&&|\|\||\?)\b",
        "tsx":        r"\b(if|else if|for|while|catch|&&|\|\||\?)\b",
        "java":       r"\b(if|else if|for|while|catch|case|&&|\|\||\?)\b",
        "go":         r"\b(if|else if|for|select|case|&&|\|\|)\b",
        "rust":       r"\b(if|else if|for|while|match|&&|\|\||\?)\b",
        "c":          r"\b(if|else if|for|while|switch|case|&&|\|\||\?)\b",
        "cpp":        r"\b(if|else if|for|while|switch|case|catch|&&|\|\||\?)\b",
        "ruby":       r"\b(if|elsif|unless|while|until|rescue|&&|\|\|)\b",
        "php":        r"\b(if|elseif|for|foreach|while|catch|case|&&|\|\||\?)\b",
    }
    pattern = _BRANCH_PATTERNS.get(language, r"\b(if|for|while)\b")
    matches = re.findall(pattern, code)
    return 1 + len(matches)


def _build_inline_comments(findings: list[_FileFinding]):
    """
    Convert findings to ReviewComment objects for GitHub inline posting.
    Only findings with a line number are eligible.
    Sorted critical-first within each file.
    """
    from apps.pr_review.github_client import ReviewComment

    comments = []
    severity_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}

    sortable = sorted(
        [f for f in findings if f.line_number is not None],
        key=lambda f: severity_rank.get(f.severity, 99),
    )

    for f in sortable:
        emoji = _severity_emoji(f.severity)
        body_lines = [
            f"**{emoji} [{f.severity.upper()}] {f.title}**",
            "",
            f.description,
        ]
        if f.suggestion:
            body_lines += ["", "**Suggested fix:**", f.suggestion]

        comments.append(ReviewComment(
            path=f.file_path,
            line=f.line_number,
            body="\n".join(body_lines),
        ))

    return comments


def _build_summary_body(
    pr_number: int,
    health_score: float,
    findings: list[_FileFinding],
    duplicate_matches: list = None,
    semantic_skipped: bool = False,
) -> str:
    """
    Build the PR summary comment body — markdown table + severity groups.
    Posted as the review body (visible at the top of the review).

    If semantic_skipped is True (embedding circuit open), a degradation
    notice is appended so the PR author knows semantic analysis was skipped.
    """
    if duplicate_matches is None:
        duplicate_matches = []

    # Count by severity (exclude duplicate type from severity table — shown separately)
    non_dup_findings = [f for f in findings if f.finding_type != "duplicate"]
    counts: dict[str, int] = {s: 0 for s in _SEVERITY_ORDER}
    for f in non_dup_findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    score_emoji = "🟢" if health_score >= 80 else ("🟡" if health_score >= 50 else "🔴")

    lines = [
        f"## Stratum Code Review — Health Score: {score_emoji} {health_score:.0f}/100",
        "",
        "| Severity | Count |",
        "|---|---|",
    ]
    for sev in _SEVERITY_ORDER:
        emoji = _severity_emoji(sev)
        lines.append(f"| {emoji} {sev.capitalize()} | {counts[sev]} |")

    if non_dup_findings:
        critical_high = [f for f in non_dup_findings if f.severity in ("critical", "high")]
        if critical_high:
            lines += ["", "### Critical & High Priority Findings"]
            for f in sorted(critical_high, key=lambda x: x.file_path):
                loc = f"`{f.file_path}`" + (f" line {f.line_number}" if f.line_number else "")
                lines.append(f"- {_severity_emoji(f.severity)} **{f.title}** — {loc}")

    # Duplicate logic section — the unique Stratum value
    if duplicate_matches:
        lines += ["", f"### Duplicate Logic Detected ({len(duplicate_matches)} match{'es' if len(duplicate_matches) != 1 else ''})"]
        for dm in duplicate_matches[:10]:   # cap at 10 in summary
            pct = int(dm.similarity * 100)
            lines.append(
                f"- `{dm.chunk_name}` in `{dm.file_path}` line {dm.line_number} — "
                f"**{pct}% similar** to `{dm.similar_chunk}` in `{dm.similar_file}` line {dm.similar_line}"
            )
        if len(duplicate_matches) > 10:
            lines.append(f"- *(and {len(duplicate_matches) - 10} more — see inline comments)*")

    if not findings:
        lines += ["", "No issues found. Code looks clean!"]

    # Graceful degradation notice — Principle 8
    if semantic_skipped:
        lines += [
            "",
            "> **Note:** Semantic analysis unavailable (embedding service circuit open). "
            "Security and rule checks completed. Duplicate logic detection and debt impact "
            "prediction were skipped for this review.",
        ]

    lines += [
        "",
        "---",
        "*Generated by [Stratum](https://github.com/adithyakrishhna/stratum) — "
        "self-hosted AI code review*",
    ]

    return "\n".join(lines)


def _severity_emoji(severity: str) -> str:
    return {
        "critical": "🔴",
        "high":     "🟠",
        "medium":   "🟡",
        "low":      "🔵",
        "info":     "⚪",
    }.get(severity, "⚪")
