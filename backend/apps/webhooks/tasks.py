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
)
def handle_pull_request_event(self, payload: dict):
    """
    Process a GitHub pull_request webhook event.

    Validates the repo exists in our DB and logs the event.
    Phase 2 will trigger the full PR review pipeline from here.
    """
    repo_data = payload.get("repository", {})
    pr_data = payload.get("pull_request", {})
    github_repo_id = repo_data.get("id")
    repo_full_name = repo_data.get("full_name", "unknown")
    pr_number = pr_data.get("number", 0)
    action = payload.get("action", "")

    logger.info(
        "pr_task_started",
        repo=repo_full_name,
        pr_number=pr_number,
        action=action,
    )

    from apps.repositories.models import Repository

    try:
        repo = Repository.objects.get(github_repo_id=github_repo_id)
    except Repository.DoesNotExist:
        logger.warning(
            "pr_task_repo_not_registered",
            github_repo_id=github_repo_id,
            repo=repo_full_name,
        )
        return

    logger.info(
        "pr_task_repo_found",
        repo_id=str(repo.id),
        repo=repo_full_name,
        pr_number=pr_number,
        action=action,
    )
    # Phase 2: pr_review orchestration task will be dispatched here.


@celery_app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def handle_push_event(self, payload: dict):
    """
    Process a GitHub push webhook event.

    Validates the repo, checks if the push is to the default branch,
    and queues an incremental ingestion task.
    Phase 1 ingestion engine will be dispatched from here.
    """
    repo_data = payload.get("repository", {})
    github_repo_id = repo_data.get("id")
    repo_full_name = repo_data.get("full_name", "unknown")
    ref = payload.get("ref", "")
    after_sha = payload.get("after", "")

    logger.info(
        "push_task_started",
        repo=repo_full_name,
        ref=ref,
        after_sha=after_sha,
    )

    from apps.repositories.models import Repository

    try:
        repo = Repository.objects.get(github_repo_id=github_repo_id)
    except Repository.DoesNotExist:
        logger.warning(
            "push_task_repo_not_registered",
            github_repo_id=github_repo_id,
            repo=repo_full_name,
        )
        return

    # Only process pushes to the default branch
    default_branch_ref = f"refs/heads/{repo.default_branch}"
    if ref != default_branch_ref:
        logger.info(
            "push_task_skipped_non_default_branch",
            repo_id=str(repo.id),
            ref=ref,
            default_branch_ref=default_branch_ref,
        )
        return

    logger.info(
        "push_task_repo_found",
        repo_id=str(repo.id),
        repo=repo_full_name,
        after_sha=after_sha,
    )
    # Phase 1: incremental git ingestion task will be dispatched here.


@celery_app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def handle_installation_event(self, payload: dict, event_type: str):
    """
    Handle GitHub App installation and uninstallation events.

    On install: stores the installation_id on any matching Repository records.
    On uninstall: logs the event for awareness.
    """
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")

    logger.info(
        "installation_task_started",
        event_type=event_type,
        action=action,
        installation_id=installation_id,
    )

    if action == "created":
        from apps.repositories.models import Repository

        repositories = payload.get("repositories", [])
        for repo_data in repositories:
            github_repo_id = repo_data.get("id")
            repo_full_name = repo_data.get("full_name", "")

            # Idempotent: update only if the repo is already registered in Stratum
            updated_count = Repository.objects.filter(
                github_repo_id=github_repo_id
            ).update(github_app_installation_id=installation_id)

            if updated_count:
                logger.info(
                    "installation_id_stored",
                    github_repo_id=github_repo_id,
                    repo=repo_full_name,
                    installation_id=installation_id,
                )
            else:
                logger.info(
                    "installation_repo_not_yet_registered",
                    github_repo_id=github_repo_id,
                    repo=repo_full_name,
                )

    elif action == "deleted":
        logger.warning(
            "app_uninstalled",
            installation_id=installation_id,
        )

    else:
        logger.info(
            "installation_action_ignored",
            action=action,
            event_type=event_type,
        )
