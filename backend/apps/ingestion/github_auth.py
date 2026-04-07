"""
GitHub App authentication — generates short-lived installation access tokens.

Used by the ingestion engine to clone private repositories via HTTPS:
    clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"

Tokens expire in 1 hour. The ingestion engine fetches a fresh token before
each clone/fetch operation.
"""

import structlog
from django.conf import settings
from github import Auth, GithubIntegration

logger = structlog.get_logger(__name__)


def get_installation_token(installation_id: int) -> str:
    """
    Generate a GitHub App installation access token.

    Authenticates as the GitHub App using the private key (RS256 JWT),
    then exchanges it for an installation token scoped to the given installation.
    """
    private_key = _load_private_key()
    auth = Auth.AppAuth(int(settings.GITHUB_APP_ID), private_key)
    integration = GithubIntegration(auth=auth)
    token = integration.get_access_token(installation_id)
    logger.info("github_installation_token_generated", installation_id=installation_id)
    return token.token


def get_authenticated_clone_url(repo_full_name: str, installation_id: int) -> str:
    """Return an authenticated HTTPS clone URL for the given repo."""
    token = get_installation_token(installation_id)
    return f"https://x-access-token:{token}@github.com/{repo_full_name}.git"


def _load_private_key() -> str:
    path = settings.GITHUB_APP_PRIVATE_KEY_PATH
    if not path:
        raise ValueError(
            "GITHUB_APP_PRIVATE_KEY_PATH is not set. "
            "Download the private key from your GitHub App settings."
        )
    with open(path, "r") as f:
        return f.read()
