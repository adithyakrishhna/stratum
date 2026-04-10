"""
Dashboard API views — read-only endpoints consumed by the React SPA.

All endpoints:
  - Require login (session cookie)
  - Verify the requesting user has access to the repo
  - Return the standard envelope: {success, data, meta, error}

URL structure (registered in config/urls.py under /api/dashboard/):
  GET  <uuid>/overview/          Page 1 — Repository Overview
  GET  <uuid>/prs/               Page 2 — PR Review Center
  GET  <uuid>/debt/timeline/     Page 3 — Debt Timeline
  GET  <uuid>/clusters/          Page 4 — Cluster Map
  GET  <uuid>/heatmap/           Page 5 — Velocity Heatmap
  GET  <uuid>/blame/             Page 6 — Blame Report
  GET  <uuid>/pipeline/          Page 7 — Pipeline Monitor
  POST <uuid>/failed-tasks/<tid>/retry/   Retry a failed task
  POST <uuid>/failed-tasks/<tid>/dismiss/ Dismiss a failed task
"""
import csv
import io

import structlog
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Max, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_repo_or_403(request, repo_id):
    """
    Return (repo, None) if the user has access, or (None, JsonResponse 403).
    """
    from apps.repositories.models import UserRepository
    try:
        ur = UserRepository.objects.select_related('repository').get(
            user=request.user,
            repository_id=repo_id,
        )
        return ur.repository, None
    except UserRepository.DoesNotExist:
        return None, JsonResponse(
            {'success': False, 'error': 'Repository not found or access denied.',
             'data': None, 'meta': {}},
            status=403,
        )


def _ok(data, meta=None):
    return JsonResponse({'success': True, 'data': data, 'meta': meta or {}, 'error': None})


# ---------------------------------------------------------------------------
# Page 1 — Repository Overview
# GET /api/dashboard/<uuid>/overview/
# ---------------------------------------------------------------------------

@login_required
@require_GET
def overview(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.debt.models import DebtScore
    from apps.clustering.models import SemanticCluster
    from apps.pr_review.models import PullRequest

    # Health score: average of last 5 reviewed PRs
    recent_prs = list(
        PullRequest.objects
        .filter(repo=repo, health_score__isnull=False)
        .order_by('-reviewed_at')
        .values('health_score')[:5]
    )
    health_score = round(
        sum(p['health_score'] for p in recent_prs) / len(recent_prs), 1
    ) if recent_prs else None

    # Debt trend: average total_score per commit, last 30 commits (chronological)
    from apps.ingestion.models import Commit
    commit_ids = list(
        Commit.objects
        .filter(repo=repo, is_processed=True)
        .order_by('-committed_at')
        .values_list('id', flat=True)[:30]
    )
    debt_trend = []
    if commit_ids:
        commit_map = {
            c.id: c for c in Commit.objects.filter(id__in=commit_ids)
        }
        agg = (
            DebtScore.objects
            .filter(repo=repo, commit_id__in=commit_ids)
            .values('commit_id')
            .annotate(avg_score=Avg('total_score'))
        )
        agg_map = {str(a['commit_id']): a['avg_score'] for a in agg}
        for cid in reversed(commit_ids):  # chronological order
            commit = commit_map.get(cid)
            if commit:
                debt_trend.append({
                    'commit_sha': commit.sha[:8],
                    'full_sha': commit.sha,
                    'committed_at': commit.committed_at.isoformat(),
                    'message': commit.message.splitlines()[0][:80],
                    'avg_debt_score': round(agg_map.get(str(cid), 0), 2),
                })

    # Top 5 deteriorating files (highest positive velocity)
    top_files = list(
        DebtScore.objects
        .filter(repo=repo, velocity__gt=0)
        .order_by('-velocity')
        .values('file_path', 'total_score', 'velocity', 'language')[:5]
    )
    for f in top_files:
        f['velocity'] = round(f['velocity'], 2)
        f['total_score'] = round(f['total_score'], 2)

    # Spreading patterns: clusters with growth_rate > 0.1 or is_flagged
    spreading = SemanticCluster.objects.filter(
        repo=repo
    ).filter(
        Q(is_flagged=True) | Q(growth_rate__gt=0.10)
    ).count()

    # Total commits and files for context
    total_commits = Commit.objects.filter(repo=repo, is_processed=True).count()
    total_files = (
        DebtScore.objects
        .filter(repo=repo)
        .values('file_path')
        .distinct()
        .count()
    )

    return _ok({
        'repo_id': str(repo.id),
        'full_name': repo.full_name,
        'analysis_status': repo.analysis_status,
        'health_score': health_score,
        'debt_trend': debt_trend,
        'top_deteriorating_files': list(top_files),
        'spreading_pattern_count': spreading,
        'total_commits': total_commits,
        'total_files': total_files,
    })


# ---------------------------------------------------------------------------
# Page 2 — PR Review Center
# GET /api/dashboard/<uuid>/prs/
# ---------------------------------------------------------------------------

@login_required
@require_GET
def pr_list(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.pr_review.models import PullRequest, PrFinding

    prs = list(
        PullRequest.objects
        .filter(repo=repo)
        .order_by('-opened_at')[:50]
    )

    severities = ['critical', 'high', 'medium', 'low', 'info']
    pr_ids = [p.id for p in prs]

    # Aggregate findings counts per PR per severity in one query
    findings_agg = (
        PrFinding.objects
        .filter(pr_id__in=pr_ids)
        .values('pr_id', 'severity')
        .annotate(count=Count('id'))
    )
    findings_map: dict = {}
    for row in findings_agg:
        pid = str(row['pr_id'])
        if pid not in findings_map:
            findings_map[pid] = {s: 0 for s in severities}
        findings_map[pid][row['severity']] = row['count']

    data = []
    for pr in prs:
        pid = str(pr.id)
        by_sev = findings_map.get(pid, {s: 0 for s in severities})
        data.append({
            'id': pid,
            'github_pr_number': pr.github_pr_number,
            'title': pr.title,
            'author': pr.author,
            'base_branch': pr.base_branch,
            'head_branch': pr.head_branch,
            'status': pr.status,
            'health_score': pr.health_score,
            'debt_impact_score': pr.debt_impact_score,
            'opened_at': pr.opened_at.isoformat() if pr.opened_at else None,
            'reviewed_at': pr.reviewed_at.isoformat() if pr.reviewed_at else None,
            'findings_by_severity': by_sev,
            'total_findings': sum(by_sev.values()),
        })

    return _ok(data, meta={'total': len(data)})


# ---------------------------------------------------------------------------
# Page 3 — Debt Timeline
# GET /api/dashboard/<uuid>/debt/timeline/?file_path=...
# ---------------------------------------------------------------------------

@login_required
@require_GET
def debt_timeline(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.debt.models import DebtScore
    from apps.ingestion.models import Commit

    # File selector list — distinct file_paths that have debt scores
    file_list = list(
        DebtScore.objects
        .filter(repo=repo)
        .values_list('file_path', flat=True)
        .distinct()
        .order_by('file_path')[:200]
    )

    file_path = request.GET.get('file_path', '')
    if not file_path and file_list:
        file_path = file_list[0]

    timeline = []
    if file_path:
        scores = (
            DebtScore.objects
            .filter(repo=repo, file_path=file_path)
            .select_related('commit')
            .order_by('commit__committed_at')
        )
        for ds in scores:
            timeline.append({
                'commit_sha': ds.commit.sha[:8],
                'full_sha': ds.commit.sha,
                'committed_at': ds.commit.committed_at.isoformat(),
                'message': ds.commit.message.splitlines()[0][:80],
                'total_score': round(ds.total_score, 2),
                'complexity_component': round(ds.complexity_component, 2),
                'duplication_component': round(ds.duplication_component, 2),
                'violation_component': round(ds.violation_component, 2),
                'cluster_component': round(ds.cluster_component, 2),
                'velocity': round(ds.velocity, 2) if ds.velocity is not None else 0,
                'is_inflection': ds.is_inflection,
            })

    return _ok({
        'file_path': file_path,
        'file_list': file_list,
        'timeline': timeline,
    })


# ---------------------------------------------------------------------------
# Page 4 — Semantic Cluster Map
# GET /api/dashboard/<uuid>/clusters/
# ---------------------------------------------------------------------------

@login_required
@require_GET
def cluster_map(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.clustering.models import SemanticCluster

    clusters = list(
        SemanticCluster.objects
        .filter(repo=repo)
        .select_related('origin_commit')
        .order_by('-chunk_count')[:100]
    )

    data = []
    for c in clusters:
        data.append({
            'id': str(c.id),
            'label': c.label or f'Cluster {str(c.id)[:8]}',
            'language': c.language,
            'file_count': c.file_count,
            'chunk_count': c.chunk_count,
            'growth_rate': round(c.growth_rate or 0, 4),
            'is_flagged': c.is_flagged,
            'first_seen_at': c.first_seen_at.isoformat() if c.first_seen_at else None,
            'origin_commit_sha': (
                c.origin_commit.sha[:8] if c.origin_commit else None
            ),
            'origin_commit_full_sha': (
                c.origin_commit.sha if c.origin_commit else None
            ),
        })

    return _ok(data, meta={'total': len(data)})


# ---------------------------------------------------------------------------
# Page 5 — Velocity Heatmap
# GET /api/dashboard/<uuid>/heatmap/?language=&directory=
# ---------------------------------------------------------------------------

@login_required
@require_GET
def velocity_heatmap(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.debt.models import DebtScore

    qs = DebtScore.objects.filter(repo=repo)

    language = request.GET.get('language', '')
    if language:
        qs = qs.filter(language=language)

    directory = request.GET.get('directory', '')
    if directory:
        qs = qs.filter(file_path__startswith=directory)

    # Latest debt score per file (most recent commit)
    latest = (
        qs
        .values('file_path', 'language')
        .annotate(
            latest_score=Max('total_score'),
            max_velocity=Max('velocity'),
        )
        .order_by('-max_velocity')[:200]
    )

    data = []
    for row in latest:
        v = row['max_velocity'] or 0
        # Status: red > 5, green < -1, grey otherwise
        if v > 5:
            status = 'deteriorating'
        elif v < -1:
            status = 'improving'
        else:
            status = 'stable'

        data.append({
            'file_path': row['file_path'],
            'language': row['language'],
            'total_score': round(row['latest_score'] or 0, 2),
            'velocity': round(v, 2),
            'status': status,
        })

    # Available filter values
    languages = list(
        DebtScore.objects
        .filter(repo=repo)
        .values_list('language', flat=True)
        .distinct()
        .order_by('language')
    )

    return _ok(data, meta={'total': len(data), 'languages': languages})


# ---------------------------------------------------------------------------
# Page 6 — Blame Report
# GET  /api/dashboard/<uuid>/blame/
# GET  /api/dashboard/<uuid>/blame/?format=csv   (CSV export)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def blame_report(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.blame.models import BlameMap
    from apps.ingestion.models import Commit

    entries = list(
        BlameMap.objects
        .filter(repo=repo)
        .select_related('commit')
        .order_by('-debt_introduced_score')[:100]
    )

    data = []
    for bm in entries:
        data.append({
            'commit_sha': bm.commit.sha[:8],
            'full_sha': bm.commit.sha,
            'author_name': bm.commit.author_name,
            'author_email': bm.commit.author_email,
            'committed_at': bm.commit.committed_at.isoformat(),
            'message': bm.commit.message.splitlines()[0][:80],
            'debt_introduced_score': round(bm.debt_introduced_score, 2),
            'patterns_originated': bm.patterns_originated,
            'files_eventually_affected': bm.files_eventually_affected,
        })

    # CSV export
    if request.GET.get('format') == 'csv':
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            'commit_sha', 'author_name', 'author_email', 'committed_at',
            'message', 'debt_introduced_score', 'patterns_originated',
            'files_eventually_affected',
        ])
        writer.writeheader()
        for row in data:
            writer.writerow({k: row[k] for k in writer.fieldnames})
        response = HttpResponse(buf.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="blame-{repo.name}.csv"'
        )
        return response

    return _ok(data, meta={'total': len(data)})


# ---------------------------------------------------------------------------
# Page 7 — Pipeline Monitor
# GET /api/dashboard/<uuid>/pipeline/
# ---------------------------------------------------------------------------

@login_required
@require_GET
def pipeline_monitor(request, repo_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.ingestion.models import PipelineEvent, FailedTask

    events = list(
        PipelineEvent.objects
        .filter(repo=repo)
        .order_by('-created_at')[:50]
    )

    failed = list(
        FailedTask.objects
        .filter(repo=repo)
        .order_by('-created_at')[:20]
    )

    events_data = [{
        'id': str(e.id),
        'stage': e.stage,
        'status': e.status,
        'items_processed': e.items_processed,
        'duration_ms': e.duration_ms,
        'error_message': e.error_message,
        'created_at': e.created_at.isoformat(),
    } for e in events]

    failed_data = [{
        'id': str(f.id),
        'task_name': f.task_name,
        'task_id': f.task_id,
        'error_message': f.error_message,
        'retry_count': f.retry_count,
        'created_at': f.created_at.isoformat(),
    } for f in failed]

    return _ok({
        'events': events_data,
        'failed_tasks': failed_data,
        'analysis_status': repo.analysis_status,
    })


# ---------------------------------------------------------------------------
# Retry / Dismiss failed tasks
# POST /api/dashboard/<uuid>/failed-tasks/<task_id>/retry/
# POST /api/dashboard/<uuid>/failed-tasks/<task_id>/dismiss/
# ---------------------------------------------------------------------------

@login_required
@require_POST
def retry_failed_task(request, repo_id, task_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.ingestion.models import FailedTask
    from celery import current_app

    try:
        ft = FailedTask.objects.get(id=task_id, repo=repo)
    except FailedTask.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'Task not found.', 'data': None, 'meta': {}},
            status=404,
        )

    try:
        import json
        payload = ft.payload or {}
        current_app.send_task(ft.task_name, kwargs=payload)
        ft.retry_count += 1
        ft.save(update_fields=['retry_count'])
        logger.info('failed_task_retried', task_id=str(task_id), repo_id=str(repo_id))
    except Exception as exc:
        logger.error('failed_task_retry_error', error=str(exc))
        return JsonResponse(
            {'success': False, 'error': str(exc), 'data': None, 'meta': {}},
            status=500,
        )

    return _ok({'status': 'queued'})


@login_required
@require_POST
def dismiss_failed_task(request, repo_id, task_id):
    repo, err = _get_repo_or_403(request, repo_id)
    if err:
        return err

    from apps.ingestion.models import FailedTask

    deleted, _ = FailedTask.objects.filter(id=task_id, repo=repo).delete()
    if not deleted:
        return JsonResponse(
            {'success': False, 'error': 'Task not found.', 'data': None, 'meta': {}},
            status=404,
        )

    return _ok({'status': 'dismissed'})
