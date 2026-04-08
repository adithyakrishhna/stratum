import json

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

    # --- Optional: update branch before analysis ---
    try:
        body = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        body = {}
    branch = (body.get('branch') or '').strip()
    if branch and branch != repo.default_branch:
        repo.default_branch = branch
        repo.last_analyzed_commit = None   # force full re-analysis on branch change
        repo.save(update_fields=['default_branch', 'last_analyzed_commit'])
        logger.info('analysis_branch_changed', repo_id=str(repo_id), branch=branch)

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


@login_required
@require_POST
def connect_repository(request):
    """
    Connect a GitHub repository to Stratum.

    Accepts JSON body: {"full_name": "owner/repo"}

    Flow:
      1. Parse and validate full_name
      2. Fetch repo metadata from GitHub API (public repos, no auth needed)
      3. get_or_create Repository record
      4. get_or_create UserRepository linking this user as owner
      5. Return the repo record

    The user can then trigger analysis separately via the analyze/ endpoint.
    Works for public repos without any GitHub App installation.
    For private repos the GitHub App installation_id must already exist.
    """
    from .models import Repository, UserRepository

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {'success': False, 'error': 'Invalid JSON body.', 'data': None, 'meta': {}},
            status=400,
        )

    full_name = (body.get('full_name') or '').strip().strip('/')
    if not full_name or '/' not in full_name:
        return JsonResponse(
            {'success': False, 'error': 'Provide full_name as "owner/repo".', 'data': None, 'meta': {}},
            status=400,
        )

    parts = full_name.split('/', 1)
    owner, name = parts[0].strip(), parts[1].strip()
    if not owner or not name:
        return JsonResponse(
            {'success': False, 'error': 'Invalid repository name.', 'data': None, 'meta': {}},
            status=400,
        )

    # Check if already connected to this user
    existing = UserRepository.objects.filter(
        user=request.user,
        repository__full_name__iexact=full_name,
    ).select_related('repository').first()

    if existing:
        repo = existing.repository
        return JsonResponse({
            'success': True,
            'data': _repo_dict(repo, existing.role),
            'meta': {'already_connected': True},
            'error': None,
        })

    # Fetch metadata from GitHub API
    github_repo_id = None
    is_private = False
    default_branch = 'main'

    try:
        from github import Github, GithubException
        from django.conf import settings

        gh = Github()   # unauthenticated — works for public repos
        gh_repo = gh.get_repo(f'{owner}/{name}')
        github_repo_id = gh_repo.id
        is_private = gh_repo.private
        default_branch = gh_repo.default_branch or 'main'
        # Use canonical casing from GitHub
        owner = gh_repo.owner.login
        name  = gh_repo.name
        full_name = gh_repo.full_name

        logger.info(
            'connect_repo_github_fetched',
            full_name=full_name,
            github_repo_id=github_repo_id,
            user_id=str(request.user.id),
        )
    except Exception as exc:
        logger.warning(
            'connect_repo_github_fetch_failed',
            full_name=full_name,
            error=str(exc),
        )
        # For private repos or GitHub API issues: create with a placeholder ID
        # The real ID will be updated when the GitHub App webhook fires.
        import hashlib
        github_repo_id = int(
            hashlib.sha256(full_name.lower().encode()).hexdigest()[:8], 16
        ) % 2_000_000_000

    # Idempotent: get_or_create by github_repo_id
    repo, created = Repository.objects.get_or_create(
        github_repo_id=github_repo_id,
        defaults={
            'owner': owner,
            'name': name,
            'full_name': full_name,
            'is_private': is_private,
            'default_branch': default_branch,
        },
    )

    # Link this user as owner
    user_repo, _ = UserRepository.objects.get_or_create(
        user=request.user,
        repository=repo,
        defaults={'role': UserRepository.Role.OWNER},
    )

    logger.info(
        'connect_repo_success',
        full_name=full_name,
        repo_id=str(repo.id),
        created=created,
        user_id=str(request.user.id),
    )

    return JsonResponse({
        'success': True,
        'data': _repo_dict(repo, user_repo.role),
        'meta': {'created': created},
        'error': None,
    }, status=201 if created else 200)


@login_required
@require_POST
def disconnect_repository(request, repo_id):
    """Remove the UserRepository link (does not delete the repo or its data)."""
    from .models import UserRepository

    deleted, _ = UserRepository.objects.filter(
        user=request.user,
        repository_id=repo_id,
    ).delete()

    if not deleted:
        return JsonResponse(
            {'success': False, 'error': 'Repository not found.', 'data': None, 'meta': {}},
            status=404,
        )

    logger.info('disconnect_repo', repo_id=str(repo_id), user_id=str(request.user.id))
    return JsonResponse({'success': True, 'data': None, 'meta': {}, 'error': None})


@login_required
@require_GET
def list_branches(request, repo_id):
    """
    Return a list of branch names for a connected repository.
    Calls the GitHub API — uses PAT if configured, otherwise unauthenticated
    (public repos only). Result is cached in Redis for 60 seconds to
    avoid hammering the GitHub API on rapid re-renders.
    """
    from .models import UserRepository
    from django.core.cache import cache

    try:
        ur = UserRepository.objects.select_related('repository').get(
            user=request.user,
            repository_id=repo_id,
        )
    except UserRepository.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Repository not found.', 'data': [], 'meta': {}},
            status=404,
        )

    repo = ur.repository
    cache_key = f'branches:{repo.full_name}'
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({'success': True, 'data': cached, 'meta': {'cached': True}, 'error': None})

    try:
        from github import Github
        from django.conf import settings

        pat = getattr(settings, 'GITHUB_PERSONAL_ACCESS_TOKEN', '') or ''
        gh = Github(pat) if pat else Github()
        gh_repo = gh.get_repo(repo.full_name)
        branches = [b.name for b in gh_repo.get_branches()]

        cache.set(cache_key, branches, timeout=60)
        logger.info('list_branches_ok', repo=repo.full_name, count=len(branches))
        return JsonResponse({'success': True, 'data': branches, 'meta': {}, 'error': None})

    except Exception as exc:
        logger.warning('list_branches_failed', repo=repo.full_name, error=str(exc))
        # Return the stored default branch as fallback so the UI is never empty
        return JsonResponse({
            'success': False,
            'data': [repo.default_branch] if repo.default_branch else [],
            'error': str(exc),
            'meta': {},
        }, status=502)


def _repo_dict(repo, role):
    return {
        'id': str(repo.id),
        'full_name': repo.full_name,
        'owner': repo.owner,
        'name': repo.name,
        'is_private': repo.is_private,
        'default_branch': repo.default_branch,
        'analysis_status': repo.analysis_status,
        'last_analyzed_commit': repo.last_analyzed_commit,
        'role': role,
    }
