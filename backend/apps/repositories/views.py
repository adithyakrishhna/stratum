import structlog
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from .rate_limiter import acquire_analysis_slot, get_active_count, MAX_CONCURRENT_ANALYSES

logger = structlog.get_logger(__name__)


@login_required
def current_user(request):
    """Return the authenticated user's profile for the React frontend."""
    user = request.user
    return JsonResponse({
        'success': True,
        'data': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'full_name': user.get_full_name(),
            'display_name': user.get_full_name() or user.username or user.email,
        },
    })


@login_required
@require_GET
def list_repositories(request):
    """
    List all repositories the authenticated user has access to.
    Includes current analysis status and active slot count for the UI.
    """
    from .models import UserRepository

    user_repos = (
        UserRepository.objects
        .filter(user=request.user)
        .select_related('repository')
        .order_by('-repository__created_at')
    )

    active_analyses = get_active_count(str(request.user.id))

    repos = []
    for ur in user_repos:
        repo = ur.repository
        repos.append({
            'id': str(repo.id),
            'full_name': repo.full_name,
            'owner': repo.owner,
            'name': repo.name,
            'is_private': repo.is_private,
            'default_branch': repo.default_branch,
            'analysis_status': repo.analysis_status,
            'last_analyzed_commit': repo.last_analyzed_commit,
            'role': ur.role,
        })

    return JsonResponse({
        'success': True,
        'data': repos,
        'meta': {
            'total': len(repos),
            'active_analyses': active_analyses,
            'max_concurrent_analyses': MAX_CONCURRENT_ANALYSES,
        },
        'error': None,
    })


@login_required
@require_POST
def trigger_analysis(request, repo_id):
    """
    Trigger a full git history analysis for a repository.

    Rate limiting: max 2 concurrent analyses per user.
    Returns HTTP 429 if the limit is already reached.

    This is the API endpoint — it checks the rate limit synchronously
    before dispatching the Celery task, giving the frontend an immediate
    429 response rather than silently dropping the job.
    """
    from .models import Repository, UserRepository

    # --- Verify the user has access to this repo ---
    try:
        ur = UserRepository.objects.select_related('repository').get(
            user=request.user,
            repository_id=repo_id,
        )
    except UserRepository.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Repository not found or access denied.',
            'data': None,
            'meta': {},
        }, status=404)

    repo = ur.repository
    user_id = str(request.user.id)

    # --- Principle 3: Rate limit check — 429 if over limit ---
    active = get_active_count(user_id)
    if active >= MAX_CONCURRENT_ANALYSES:
        logger.warning(
            "analysis_rate_limit_exceeded",
            user_id=user_id,
            repo_id=repo_id,
            active_analyses=active,
        )
        return JsonResponse({
            'success': False,
            'error': (
                f'Rate limit exceeded. You have {active} '
                f'of {MAX_CONCURRENT_ANALYSES} allowed concurrent analyses running. '
                f'Wait for one to complete before starting another.'
            ),
            'data': {
                'active_analyses': active,
                'max_concurrent_analyses': MAX_CONCURRENT_ANALYSES,
            },
            'meta': {},
        }, status=429)

    # --- Acquire slot (atomic Redis check-and-increment) ---
    if not acquire_analysis_slot(user_id):
        return JsonResponse({
            'success': False,
            'error': (
                f'Rate limit exceeded. Maximum {MAX_CONCURRENT_ANALYSES} '
                f'concurrent analyses allowed per user.'
            ),
            'data': {
                'active_analyses': MAX_CONCURRENT_ANALYSES,
                'max_concurrent_analyses': MAX_CONCURRENT_ANALYSES,
            },
            'meta': {},
        }, status=429)

    # --- Dispatch ingestion task ---
    try:
        from apps.ingestion.tasks import ingest_repository

        task = ingest_repository.apply_async(
            kwargs={'repo_id': str(repo.id), 'user_id': user_id},
            queue='ingestion',
        )
        logger.info(
            "analysis_triggered",
            user_id=user_id,
            repo_id=str(repo.id),
            task_id=task.id,
        )
    except Exception as exc:
        # Release slot if dispatch fails — analysis never started
        from .rate_limiter import release_analysis_slot
        release_analysis_slot(user_id)
        logger.error(
            "analysis_dispatch_failed",
            user_id=user_id,
            repo_id=str(repo.id),
            error=str(exc),
        )
        return JsonResponse({
            'success': False,
            'error': 'Failed to start analysis. Please try again.',
            'data': None,
            'meta': {},
        }, status=500)

    return JsonResponse({
        'success': True,
        'data': {
            'repo_id': str(repo.id),
            'task_id': task.id,
            'status': 'queued',
        },
        'meta': {},
        'error': None,
    }, status=202)
