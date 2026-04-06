from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('api/repositories/', include('apps.repositories.urls')),
    path('api/ingestion/', include('apps.ingestion.urls')),
    path('api/pr/', include('apps.pr_review.urls')),
    path('api/debt/', include('apps.debt.urls')),
    path('api/clusters/', include('apps.clustering.urls')),
    path('api/blame/', include('apps.blame.urls')),
    path('webhooks/', include('apps.webhooks.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
]
