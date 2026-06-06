import mimetypes

from django.contrib import admin
from django.urls import path, include, re_path
from django.http import JsonResponse, FileResponse, Http404
from django.conf import settings
import os

_FRONTEND_DIR = None


def _frontend_dir():
    global _FRONTEND_DIR
    if _FRONTEND_DIR is None:
        _FRONTEND_DIR = os.path.join(settings.BASE_DIR, 'static', 'frontend')
    return _FRONTEND_DIR


def health(request):
    return JsonResponse({"status": "ok"})


def serve_spa(request, path=''):
    """
    Catch-all that handles two cases:

    1. Static asset request (JS, CSS, SVG, fonts, etc.)
       The Vite build outputs assets to static/frontend/assets/.
       index.html references them as /assets/... (root-relative).
       If the requested path maps to a real file in the frontend build
       directory, serve it with the correct MIME type.

    2. SPA client-side route (/dashboard, /pr-review, etc.)
       No file exists for these paths — serve index.html so React Router
       can handle the route on the client side.
    """
    frontend = _frontend_dir()
    # Strip leading slash and resolve the file path
    rel = request.path.lstrip('/')
    if rel:
        candidate = os.path.join(frontend, rel)
        # Prevent directory traversal — resolved path must stay inside frontend dir
        if os.path.commonpath([candidate, frontend]) == frontend and os.path.isfile(candidate):
            content_type, _ = mimetypes.guess_type(candidate)
            return FileResponse(
                open(candidate, 'rb'),
                content_type=content_type or 'application/octet-stream',
            )

    # Not a real file — serve index.html for SPA client-side routing
    index = os.path.join(frontend, 'index.html')
    if not os.path.exists(index):
        raise Http404(
            "React bundle not found at static/frontend/index.html. "
            "Run: cd frontend && npm run build"
        )
    return FileResponse(open(index, 'rb'), content_type='text/html')


urlpatterns = [
    path('health/', health),
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('api/repositories/', include('apps.repositories.urls')),
    path('api/ingestion/', include('apps.ingestion.urls')),
    path('api/pr/', include('apps.pr_review.urls')),
    path('api/debt/', include('apps.debt.urls')),
    path('api/clusters/', include('apps.clustering.urls')),
    path('api/blame/', include('apps.blame.urls')),
    path('api/dashboard/', include('apps.dashboard.urls')),
    path('api/webhooks/', include('apps.webhooks.urls')),

    # Catch-all — must be last. Serves React SPA for all non-API routes.
    re_path(r'^.*$', serve_spa),
]
