"""
Git Ingestion Engine

Walks a repository's entire commit history chronologically in batches of 50,
creates Commit records, fingerprints changed files, and queues them for AST parsing.

System design principles applied:
  Principle 1  — Idempotency: get_or_create for all Commit and FileFingerprint records
  Principle 2  — Fault tolerance: called from a retryable Celery task
  Principle 4  — Observability: PipelineEvent written on start and end of each stage
  Principle 6  — Data consistency: select_for_update to prevent concurrent analyses
  Principle 11 — Incremental processing: checkpoint + sha256 file fingerprinting
  Optimization 4 — Skip unchanged files (8x speedup on repeat runs)
"""

import hashlib
import shutil
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

import git as gitpython
import structlog
from django.conf import settings
from django.db import OperationalError, transaction

from apps.ingestion.github_auth import get_authenticated_clone_url
from apps.ingestion.models import Commit, FailedTask, FileFingerprint, PipelineEvent
from apps.repositories.models import Repository

logger = structlog.get_logger(__name__)

_CLONE_BASE = Path(settings.REPO_CLONE_BASE_DIR)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest_repository(repo_id: str, task_id: str = "") -> dict:
    """
    Walk the full git history for a repository and queue each changed file for parsing.

    Returns a summary dict with keys: commits_processed, files_queued, files_skipped.
    Returns an empty dict if the repo is already being analyzed (lock contention).

    Called from the ingest_repository Celery task.
    """
    # --- Principle 6: atomically claim the repo row with a brief lock ---
    try:
        with transaction.atomic():
            repo = (
                Repository.objects
                .select_for_update(nowait=True)
                .get(id=repo_id)
            )
            if repo.analysis_status == Repository.AnalysisStatus.RUNNING:
                logger.warning("ingestion_already_running", repo_id=repo_id, repo=repo.full_name)
                return {}
            repo.analysis_status = Repository.AnalysisStatus.RUNNING
            repo.save(update_fields=["analysis_status", "updated_at"])
    except OperationalError:
        logger.warning("ingestion_repo_locked_by_another_worker", repo_id=repo_id)
        return {}

    _record_event(repo, "ingestion", PipelineEvent.Status.STARTED, task_id=task_id)
    logger.info("ingestion_started", repo_id=repo_id, repo=repo.full_name)
    start_time = time.monotonic()

    try:
        git_repo = _get_or_clone(repo)
        summary = _walk_history(repo, git_repo, task_id)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        with transaction.atomic():
            Repository.objects.filter(id=repo.id).update(
                analysis_status=Repository.AnalysisStatus.COMPLETED
            )

        _record_event(
            repo, "ingestion", PipelineEvent.Status.COMPLETED,
            items_processed=summary["commits_processed"],
            duration_ms=duration_ms, task_id=task_id,
        )
        logger.info(
            "ingestion_completed",
            repo_id=repo_id, repo=repo.full_name,
            duration_ms=duration_ms, **summary,
        )
        return summary

    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        with transaction.atomic():
            Repository.objects.filter(id=repo.id).update(
                analysis_status=Repository.AnalysisStatus.FAILED
            )
        _record_event(
            repo, "ingestion", PipelineEvent.Status.FAILED,
            duration_ms=duration_ms, error_message=str(exc), task_id=task_id,
        )
        logger.error(
            "ingestion_failed",
            repo_id=repo_id, repo=repo.full_name, error=str(exc), duration_ms=duration_ms,
        )
        raise


# ---------------------------------------------------------------------------
# Clone / fetch
# ---------------------------------------------------------------------------

def _get_or_clone(repo: Repository) -> gitpython.Repo:
    """
    Return a GitPython Repo object pointing to a local clone.

    If the clone already exists: fetch latest commits.
    If not: clone using an installation token (private repos) or public HTTPS (public repos).
    """
    clone_path = _CLONE_BASE / repo.owner / repo.name

    if clone_path.exists():
        try:
            git_repo = gitpython.Repo(clone_path)
            with git_repo.git.custom_environment(GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='echo'):
                git_repo.remotes.origin.fetch()
            logger.info("repo_fetched", repo=repo.full_name, path=str(clone_path))
            return git_repo
        except Exception as exc:
            logger.warning(
                "repo_fetch_failed_recloning",
                repo=repo.full_name, error=str(exc),
            )
            shutil.rmtree(clone_path, ignore_errors=True)

    clone_path.mkdir(parents=True, exist_ok=True)

    if repo.github_app_installation_id:
        # GitHub App installation token (preferred for production)
        clone_url = get_authenticated_clone_url(repo.full_name, repo.github_app_installation_id)
    else:
        from django.conf import settings
        pat = getattr(settings, 'GITHUB_PERSONAL_ACCESS_TOKEN', '') or ''
        if pat:
            # PAT fallback — works for private repos during dev / self-hosted setups
            clone_url = f"https://x-access-token:{pat}@github.com/{repo.full_name}.git"
            logger.info("repo_clone_using_pat", repo=repo.full_name)
        else:
            # Public repos only — no credentials
            clone_url = f"https://github.com/{repo.full_name}.git"

    # Principle 7: validate URL before any network call
    if not ("github.com/" in clone_url and clone_url.startswith("https://")):
        raise ValueError(f"Refusing to clone: URL does not start with https://github.com/")

    # Disable interactive credential prompts inside Docker (no TTY available).
    # GIT_TERMINAL_PROMPT=0  → never prompt for username/password
    # GIT_ASKPASS=echo       → return empty string to any credential question
    _no_prompt_env = {
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_ASKPASS': 'echo',
    }

    logger.info("repo_cloning", repo=repo.full_name)
    git_repo = gitpython.Repo.clone_from(clone_url, clone_path, env=_no_prompt_env)
    logger.info("repo_cloned", repo=repo.full_name, path=str(clone_path))
    return git_repo


# ---------------------------------------------------------------------------
# History walk
# ---------------------------------------------------------------------------

def _walk_history(repo: Repository, git_repo: gitpython.Repo, task_id: str) -> dict:
    """
    Walk all unprocessed commits oldest-first in batches of COMMIT_BATCH_SIZE.

    Checkpoint: if repo.last_analyzed_commit is set, resumes from that SHA.
    After each batch: updates repo.last_analyzed_commit so a crash mid-walk resumes cleanly.
    """
    batch_size = settings.COMMIT_BATCH_SIZE

    all_commits = list(
        git_repo.iter_commits(f"origin/{repo.default_branch}", reverse=True)
    )

    # --- Principle 11: resume from checkpoint ---
    if repo.last_analyzed_commit:
        sha_list = [c.hexsha for c in all_commits]
        if repo.last_analyzed_commit in sha_list:
            idx = sha_list.index(repo.last_analyzed_commit) + 1
            all_commits = all_commits[idx:]
            logger.info(
                "ingestion_checkpoint_resumed",
                repo_id=str(repo.id),
                checkpoint=repo.last_analyzed_commit,
                remaining=len(all_commits),
            )

    if not all_commits:
        logger.info("ingestion_no_new_commits", repo_id=str(repo.id))
        return {"commits_processed": 0, "files_queued": 0, "files_skipped": 0}

    total_commits = 0
    total_queued = 0
    total_skipped = 0

    for batch_start in range(0, len(all_commits), batch_size):
        batch = all_commits[batch_start : batch_start + batch_size]
        batch_t = time.monotonic()

        _record_event(repo, "ingestion_batch", PipelineEvent.Status.STARTED, task_id=task_id)

        batch_queued, batch_skipped = _process_batch(repo, batch)
        total_commits += len(batch)
        total_queued += batch_queued
        total_skipped += batch_skipped

        # Save checkpoint after each batch (Principle 11)
        with transaction.atomic():
            Repository.objects.filter(id=repo.id).update(
                last_analyzed_commit=batch[-1].hexsha
            )

        duration_ms = int((time.monotonic() - batch_t) * 1000)
        _record_event(
            repo, "ingestion_batch", PipelineEvent.Status.COMPLETED,
            items_processed=batch_queued, duration_ms=duration_ms, task_id=task_id,
        )
        logger.info(
            "ingestion_batch_done",
            repo_id=str(repo.id),
            batch_commits=len(batch),
            batch_queued=batch_queued,
            batch_skipped=batch_skipped,
            duration_ms=duration_ms,
        )

    return {
        "commits_processed": total_commits,
        "files_queued": total_queued,
        "files_skipped": total_skipped,
    }


def _process_batch(repo: Repository, batch: list) -> tuple[int, int]:
    """
    Process one batch of commits. Returns (files_queued, files_skipped).

    For each commit: creates a Commit record, walks changed files,
    fingerprints each one, and queues changed files for AST parsing.
    """
    queued = 0
    skipped = 0

    for git_commit in batch:
        # Principle 1: idempotent — get_or_create so re-runs are safe
        commit_db, _ = Commit.objects.get_or_create(
            sha=git_commit.hexsha,
            defaults={
                "repo": repo,
                "author_name": git_commit.author.name or "",
                "author_email": git_commit.author.email or "",
                "message": git_commit.message or "",
                "committed_at": datetime.fromtimestamp(
                    git_commit.committed_date, tz=dt_timezone.utc
                ),
                "files_changed": len(git_commit.stats.files),
                "is_processed": False,
            },
        )

        for file_path, content in _iter_changed_files(git_commit):
            content_hash = hashlib.sha256(
                content.encode("utf-8", errors="replace")
            ).hexdigest()

            # Principle 1: get_or_create fingerprint; skip if hash unchanged
            fingerprint, created = FileFingerprint.objects.get_or_create(
                repo=repo,
                file_path=file_path,
                defaults={"content_hash": content_hash, "last_commit": commit_db},
            )

            if not created:
                if fingerprint.content_hash == content_hash:
                    skipped += 1
                    continue
                fingerprint.content_hash = content_hash
                fingerprint.last_commit = commit_db
                fingerprint.save(update_fields=["content_hash", "last_commit", "updated_at"])

            # Queue for AST parsing via string name — avoids cross-module import
            from celery import current_app
            current_app.send_task(
                "apps.parsing.tasks.parse_file",
                kwargs={
                    "repo_id": str(repo.id),
                    "commit_id": str(commit_db.id),
                    "file_path": file_path,
                    "file_content": content,
                },
                queue="parsing",
            )
            queued += 1

    return queued, skipped


# ---------------------------------------------------------------------------
# File iteration helpers
# ---------------------------------------------------------------------------

def _iter_changed_files(git_commit: gitpython.objects.Commit):
    """
    Yield (file_path, content) for each parseable, non-skipped file in the commit.

    For the initial commit (no parents), yields all tracked files.
    For subsequent commits, yields only added/modified/renamed files.
    Binary files and decode errors are silently skipped.
    """
    from apps.parsing.language_router import get_language, should_skip

    if git_commit.parents:
        diffs = git_commit.parents[0].diff(git_commit)
        changed_paths = [
            d.b_path for d in diffs
            if d.b_path and d.change_type in ("A", "M", "R")
        ]
    else:
        changed_paths = list(git_commit.stats.files.keys())

    for file_path in changed_paths:
        if not get_language(file_path):
            continue
        if should_skip(file_path):
            continue

        try:
            blob = git_commit.tree[file_path]
            content = blob.data_stream.read().decode("utf-8", errors="replace")
            if should_skip(file_path, content):  # minified check needs content
                continue
            yield file_path, content
        except (KeyError, Exception):
            continue


# ---------------------------------------------------------------------------
# PipelineEvent helper
# ---------------------------------------------------------------------------

def _record_event(
    repo: Repository,
    stage: str,
    status: str,
    items_processed: int = 0,
    duration_ms: int = None,
    error_message: str = "",
    task_id: str = "",
):
    """Write a PipelineEvent. Never raises — observability must not crash the pipeline."""
    try:
        PipelineEvent.objects.create(
            repo=repo,
            task_id=task_id,
            stage=stage,
            status=status,
            items_processed=items_processed,
            duration_ms=duration_ms,
            error_message=error_message,
        )
    except Exception as exc:
        logger.warning("pipeline_event_write_failed", stage=stage, error=str(exc))
