"""
Management command: ingest_repo

Registers a GitHub repository in Stratum and runs the full git history
ingestion synchronously (no Celery needed for local testing).

Usage:
    python manage.py ingest_repo owner/repo-name
    python manage.py ingest_repo owner/repo-name --branch main
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Register a GitHub repo and run git history ingestion (for local testing)"

    def add_arguments(self, parser):
        parser.add_argument(
            "full_name",
            type=str,
            help="GitHub repo in owner/name format  e.g. adithyakrishhna/stratum",
        )
        parser.add_argument(
            "--branch",
            type=str,
            default="main",
            help="Default branch to ingest (default: main)",
        )
        parser.add_argument(
            "--token",
            type=str,
            default="",
            help="GitHub personal access token (required for private repos). "
                 "Can also be set via GITHUB_TOKEN env var.",
        )

    def handle(self, *args, **options):
        import os
        full_name = options["full_name"]
        branch = options["branch"]
        token = options["token"] or os.environ.get("GITHUB_TOKEN", "")

        if "/" not in full_name:
            raise CommandError("Provide repo as owner/name  e.g. adithyakrishhna/stratum")

        owner, name = full_name.split("/", 1)

        # --- Fetch repo info from GitHub API ---
        self.stdout.write(f"Fetching repo info for {full_name} ...")
        try:
            from github import Auth, Github
            gh = Github(auth=Auth.Token(token)) if token else Github()
            gh_repo = gh.get_repo(full_name)
        except Exception as exc:
            raise CommandError(
                f"GitHub API error: {exc}\n"
                "For private repos, pass --token <your-github-pat> or set GITHUB_TOKEN env var.\n"
                "Create a PAT at: https://github.com/settings/tokens (needs 'repo' scope)"
            )

        # --- Create or update Repository record ---
        from apps.repositories.models import Repository

        repo, created = Repository.objects.get_or_create(
            github_repo_id=gh_repo.id,
            defaults={
                "owner": owner,
                "name": name,
                "full_name": full_name,
                "is_private": gh_repo.private,
                "default_branch": branch or gh_repo.default_branch,
                "analysis_status": Repository.AnalysisStatus.PENDING,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created repository record: {full_name}"))
        else:
            self.stdout.write(f"Repository already exists: {full_name} (id={repo.id})")

        # --- Run ingestion synchronously (bypass Celery for local testing) ---
        self.stdout.write(f"\nStarting ingestion for repo_id={repo.id} ...")
        self.stdout.write("This may take a while for large repos.\n")

        try:
            from apps.ingestion.engine import ingest_repository
            summary = ingest_repository(repo_id=str(repo.id), task_id="management-cmd")
        except Exception as exc:
            raise CommandError(f"Ingestion failed: {exc}")

        self.stdout.write(self.style.SUCCESS("\n=== Ingestion Complete ==="))
        self.stdout.write(f"  Commits processed : {summary.get('commits_processed', 0)}")
        self.stdout.write(f"  Files queued      : {summary.get('files_queued', 0)}")
        self.stdout.write(f"  Files skipped     : {summary.get('files_skipped', 0)}")
        self.stdout.write(f"\nCheck Django admin to see Commit and FileFingerprint records.")
