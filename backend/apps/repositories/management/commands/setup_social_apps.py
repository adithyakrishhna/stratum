"""
Management command: setup_social_apps

Creates the GitHub OAuth SocialApp record if it doesn't exist.
Called automatically from entrypoint.sh on every container start.

Why this is needed:
    Django Allauth 65.x requires a SocialApp DB record linked to the
    current Site. The record is not auto-created from .env settings.
    Without this record, GitHub OAuth login sends an empty client_id
    and GitHub returns a 404.

Usage:
    python manage.py setup_social_apps
"""
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Create GitHub OAuth SocialApp DB record from .env credentials"

    def handle(self, *args, **options):
        client_id = getattr(settings, "GITHUB_OAUTH_CLIENT_ID", "")
        secret = getattr(settings, "GITHUB_OAUTH_CLIENT_SECRET", "")

        if not client_id or not secret:
            self.stderr.write(
                self.style.WARNING(
                    "GITHUB_OAUTH_CLIENT_ID or GITHUB_OAUTH_CLIENT_SECRET not set in .env — "
                    "skipping SocialApp setup. GitHub login will not work."
                )
            )
            return

        from django.contrib.sites.models import Site
        from allauth.socialaccount.models import SocialApp

        site = Site.objects.get(id=1)

        app, created = SocialApp.objects.get_or_create(
            provider="github",
            defaults={
                "name": "GitHub",
                "client_id": client_id,
                "secret": secret,
            },
        )

        # Always keep credentials in sync with .env in case they changed
        if not created:
            updated = False
            if app.client_id != client_id:
                app.client_id = client_id
                updated = True
            if app.secret != secret:
                app.secret = secret
                updated = True
            if updated:
                app.save(update_fields=["client_id", "secret"])
                self.stdout.write(self.style.SUCCESS("GitHub SocialApp credentials updated from .env"))

        # Ensure linked to the current site
        if not app.sites.filter(id=site.id).exists():
            app.sites.add(site)

        status = "created" if created else "already exists"
        self.stdout.write(
            self.style.SUCCESS(
                f"GitHub SocialApp {status} — client_id={client_id[:8]}... linked to {site.domain}"
            )
        )
