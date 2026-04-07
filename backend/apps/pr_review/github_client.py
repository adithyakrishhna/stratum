"""
GitHub App client for PR review operations.

Responsibilities:
  1. Authenticate as a GitHub App using JWT + installation access token
  2. Fetch the list of changed files in a PR with their content
  3. Post a single review (inline comments grouped by severity + summary body)

Design notes:
- One installation token per call — tokens expire after 1 hour;
  PyGithub's GithubIntegration handles JWT generation automatically.
- All comments are batched into a single create_review API call
  (not one API call per finding) — respects GitHub's rate limits.
- Lines outside the PR diff cannot receive inline comments;
  those findings are appended to the summary body instead.
"""
import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog
from django.conf import settings
from github import Github, GithubIntegration, GithubException

logger = structlog.get_logger(__name__)

# Maximum inline comments per review — GitHub enforces this limit
_MAX_INLINE_COMMENTS = 50


@dataclass
class PrFile:
    """A single file changed in a PR."""
    filename: str
    status: str          # "added" | "modified" | "removed" | "renamed"
    content: str         # decoded UTF-8 source, empty string if binary or removed
    patch: str           # unified diff patch from GitHub
    additions: int = 0
    deletions: int = 0


@dataclass
class ReviewComment:
    """An inline comment to post on a specific file + line."""
    path: str
    line: int
    body: str


def _get_installation_client(installation_id: int) -> Github:
    """
    Return an authenticated Github client for the given App installation.

    Flow:
      1. Load App private key from filesystem (path set in settings)
      2. GithubIntegration signs a short-lived JWT (10 min max)
      3. Exchange JWT for an installation access token (1-hour TTL)
      4. Return a Github client using that token
    """
    app_id = int(settings.GITHUB_APP_ID)
    key_path = Path(settings.GITHUB_APP_PRIVATE_KEY_PATH)

    if not key_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at: {key_path}. "
            "Copy your .pem file there or update GITHUB_APP_PRIVATE_KEY_PATH in .env"
        )

    private_key = key_path.read_text()

    integration = GithubIntegration(
        integration_id=app_id,
        private_key=private_key,
    )
    access_token = integration.get_access_token(installation_id)
    return Github(access_token.token)


def fetch_pr_files(
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
) -> list[PrFile]:
    """
    Return the list of changed files in a PR with decoded content.

    Files that are:
    - removed (deleted in the PR)
    - binary (cannot decode as UTF-8)
    - in the skip list (handled by caller)
    are returned with empty content and should be skipped by the caller.

    Args:
        installation_id: GitHub App installation ID for the repo's owner
        repo_full_name:  "owner/repo" string
        pr_number:       GitHub PR number (integer)
        head_sha:        HEAD commit SHA of the PR branch

    Returns:
        List of PrFile objects, one per changed file.
    """
    gh = _get_installation_client(installation_id)
    repo = gh.get_repo(repo_full_name)
    pull = repo.get_pull(pr_number)

    pr_files: list[PrFile] = []

    for gh_file in pull.get_files():
        filename = gh_file.filename
        status = gh_file.status
        patch = gh_file.patch or ""

        content = ""
        if status != "removed":
            content = _fetch_file_content(repo, filename, head_sha)

        pr_files.append(PrFile(
            filename=filename,
            status=status,
            content=content,
            patch=patch,
            additions=gh_file.additions,
            deletions=gh_file.deletions,
        ))

    logger.info(
        "pr_files_fetched",
        repo=repo_full_name,
        pr_number=pr_number,
        file_count=len(pr_files),
    )
    return pr_files


def _fetch_file_content(repo, file_path: str, ref: str) -> str:
    """
    Fetch and decode file content at a specific git ref.

    Returns empty string if:
    - File doesn't exist at that ref (e.g., newly added but not yet visible)
    - File is binary (UnicodeDecodeError)
    - Any GitHub API error occurs
    """
    try:
        file_obj = repo.get_contents(file_path, ref=ref)
        # get_contents returns a list for directories; guard against that
        if isinstance(file_obj, list):
            return ""
        raw = base64.b64decode(file_obj.content)
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.debug("file_content_binary_skipped", file_path=file_path)
        return ""
    except GithubException as exc:
        logger.warning(
            "file_content_fetch_failed",
            file_path=file_path,
            ref=ref,
            status=exc.status,
        )
        return ""


def _build_diff_line_set(patch: str) -> set[int]:
    """
    Parse a unified diff patch and return the set of file-level line numbers
    that appear in the PR diff (right-hand side / new file lines only).

    These are the only lines GitHub will accept for inline review comments.
    """
    diff_lines: set[int] = set()
    current_line = 0

    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            # e.g.  @@ -10,7 +15,6 @@
            # Extract the new-file start line from "+N" part
            import re
            match = re.search(r"\+(\d+)", raw_line)
            if match:
                current_line = int(match.group(1)) - 1
        elif raw_line.startswith("-"):
            # Removed line — does not advance new-file line counter
            pass
        elif raw_line.startswith("+") or raw_line.startswith(" "):
            current_line += 1
            if raw_line.startswith("+"):
                diff_lines.add(current_line)

    return diff_lines


def post_pr_review(
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    inline_comments: list[ReviewComment],
    summary_body: str,
) -> Optional[int]:
    """
    Post a single PR review containing inline comments and a summary body.

    Only comments whose line number appears in the PR diff are posted inline.
    Comments on lines outside the diff are silently dropped (the summary body
    already contains all findings grouped by severity, so nothing is lost).

    Returns the GitHub review ID on success, None on failure.
    """
    gh = _get_installation_client(installation_id)
    repo = gh.get_repo(repo_full_name)
    pull = repo.get_pull(pr_number)

    # Build diff line sets per file so we can validate comment positions
    file_patches: dict[str, set[int]] = {}
    for gh_file in pull.get_files():
        file_patches[gh_file.filename] = _build_diff_line_set(gh_file.patch or "")

    # Filter to only comments on lines actually in the diff
    valid_comments = []
    for comment in inline_comments[:_MAX_INLINE_COMMENTS]:
        diff_lines = file_patches.get(comment.path, set())
        if comment.line in diff_lines:
            valid_comments.append({
                "path": comment.path,
                "line": comment.line,
                "side": "RIGHT",
                "body": comment.body,
            })
        else:
            logger.debug(
                "inline_comment_skipped_not_in_diff",
                path=comment.path,
                line=comment.line,
            )

    try:
        review = pull.create_review(
            commit=repo.get_commit(head_sha),
            body=summary_body,
            event="COMMENT",
            comments=valid_comments,
        )
        logger.info(
            "pr_review_posted",
            repo=repo_full_name,
            pr_number=pr_number,
            review_id=review.id,
            inline_comments=len(valid_comments),
        )
        return review.id

    except GithubException as exc:
        logger.error(
            "pr_review_post_failed",
            repo=repo_full_name,
            pr_number=pr_number,
            status=exc.status,
            data=str(exc.data),
        )
        return None
