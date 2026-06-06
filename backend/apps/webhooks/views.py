import json

import structlog
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import verify_github_signature
from .tasks import handle_installation_event, handle_pull_request_event, handle_push_event

logger = structlog.get_logger(__name__)


@csrf_exempt
@require_POST
def github_webhook(request):
    """
    Receive and route GitHub App webhook events.

    Security: every request is verified with HMAC-SHA256 before any processing.
    Responds 202 immediately — processing is queued in Celery, never done in-request.
    GitHub's timeout is 10 seconds; we respond in milliseconds.
    """
    delivery_id = request.META.get("HTTP_X_GITHUB_DELIVERY", "unknown")
    event = request.META.get("HTTP_X_GITHUB_EVENT", "")
    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")

    # --- Principle 7: Verify HMAC-SHA256 on every request, no exceptions ---
    if not verify_github_signature(settings.GITHUB_WEBHOOK_SECRET, request.body, signature):
        logger.warning(
            "webhook_signature_rejected",
            delivery_id=delivery_id,
            github_event=event,
            remote_addr=request.META.get("REMOTE_ADDR"),
        )
        return HttpResponse("Forbidden", status=403)

    # --- Parse payload ---
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error("webhook_invalid_json", delivery_id=delivery_id, github_event=event)
        return HttpResponse("Bad Request", status=400)

    logger.info("webhook_received", github_event=event, delivery_id=delivery_id)

    # --- ping: GitHub sends this when the webhook is first configured ---
    if event == "ping":
        zen = payload.get("zen", "")
        hook_id = payload.get("hook_id", "")
        logger.info("webhook_ping", hook_id=hook_id, zen=zen)
        return JsonResponse({"success": True, "message": "pong"})

    # --- pull_request: queue for PR review (highest-priority queue) ---
    if event == "pull_request":
        action = payload.get("action", "")
        if action in ("opened", "reopened", "synchronize", "closed"):
            handle_pull_request_event.apply_async(
                args=[payload],
                queue="pr_priority",
            )
            logger.info(
                "webhook_pr_queued",
                delivery_id=delivery_id,
                action=action,
                repo=payload.get("repository", {}).get("full_name", ""),
                pr_number=payload.get("pull_request", {}).get("number"),
            )
        else:
            logger.info("webhook_pr_action_skipped", action=action, delivery_id=delivery_id)

    # --- push: queue for incremental ingestion ---
    elif event == "push":
        handle_push_event.apply_async(
            args=[payload],
            queue="ingestion",
        )
        logger.info(
            "webhook_push_queued",
            delivery_id=delivery_id,
            repo=payload.get("repository", {}).get("full_name", ""),
            ref=payload.get("ref", ""),
        )

    # --- installation / installation_repositories: store installation_id ---
    elif event in ("installation", "installation_repositories"):
        handle_installation_event.apply_async(
            args=[payload, event],
            queue="default",
        )
        logger.info(
            "webhook_installation_queued",
            delivery_id=delivery_id,
            github_event=event,
            action=payload.get("action", ""),
        )

    else:
        logger.info("webhook_event_ignored", github_event=event, delivery_id=delivery_id)

    # --- Optimization 9: always 202, never block GitHub ---
    return HttpResponse(status=202)
