"""
Management command: sync_pr_statuses

Fetches the current state of every PR that is stuck as 'open' or 'analyzing'
from GitHub and updates the status to 'merged' or 'closed' as appropriate.

Use this once after deploying the webhook fix to clean up stale records.

Usage:
    docker compose exec django python manage.py sync_pr_statuses
    docker compose exec django python manage.py sync_pr_statuses --repo adithyakrishhna/stratum
"""
import structlog
from django.core.management.base import BaseCommand

from apps.pr_review.models import PullRequest
from apps.pr_review.github_client import _get_installation_client

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Sync stale PR statuses (open/analyzing) with current GitHub state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo",
            type=str,
            default=None,
            help="Limit sync to a specific repo full_name (e.g. owner/name)",
        )

    def handle(self, *args, **options):
        repo_filter = options.get("repo")

        stale_prs = PullRequest.objects.filter(
            status__in=[PullRequest.Status.OPEN, PullRequest.Status.ANALYZING]
        ).select_related("repo")

        if repo_filter:
            stale_prs = stale_prs.filter(repo__full_name=repo_filter)

        total = stale_prs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No stale PRs found. All statuses are up to date."))
            return

        self.stdout.write(f"Found {total} stale PR(s) to sync...")

        updated = 0
        errors = 0

        for pr in stale_prs:
            repo = pr.repo
            if not repo.github_app_installation_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Skipping PR #{pr.github_pr_number} — no installation_id for repo {repo.full_name}"
                    )
                )
                errors += 1
                continue

            try:
                gh = _get_installation_client(repo.github_app_installation_id)
                gh_repo = gh.get_repo(repo.full_name)
                gh_pr = gh_repo.get_pull(pr.github_pr_number)

                if gh_pr.state == "closed":
                    new_status = (
                        PullRequest.Status.MERGED if gh_pr.merged else PullRequest.Status.CLOSED
                    )
                    PullRequest.objects.filter(pk=pr.pk).update(status=new_status)
                    self.stdout.write(
                        f"  PR #{pr.github_pr_number} ({repo.full_name}): open → {new_status}"
                    )
                    updated += 1
                else:
                    self.stdout.write(
                        f"  PR #{pr.github_pr_number} ({repo.full_name}): still open on GitHub, no change"
                    )

            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  PR #{pr.github_pr_number} ({repo.full_name}): error — {exc}"
                    )
                )
                errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Updated: {updated} | Unchanged: {total - updated - errors} | Errors: {errors}"
            )
        )
