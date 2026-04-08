from django.contrib import admin
from django.urls import path, include, re_path
from django.http import JsonResponse, FileResponse, Http404
from django.conf import settings
import os


def health(request):
    return JsonResponse({"status": "ok"})


def serve_spa(request, path=''):
    """
    Catch-all: serve the React SPA index.html for any non-API route.
    In production (docker compose), Django serves the built bundle via WhiteNoise.
    In dev, Vite serves the SPA on port 5173 — this view is never reached.
    """
    index = os.path.join(settings.BASE_DIR, 'static', 'frontend', 'index.html')
    if not os.path.exists(index):
        raise Http404(
            "React bundle not found. Run: cd frontend && npm run build"
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
    path('webhooks/', include('apps.webhooks.urls')),

    # Catch-all — must be last. Serves React SPA for all non-API routes.
    re_path(r'^.*$', serve_spa),
]
