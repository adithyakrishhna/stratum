from django.urls import path

from . import views

app_name = 'repositories'

urlpatterns = [
    path('me/', views.current_user, name='current-user'),
    path('', views.list_repositories, name='list'),
    path('<uuid:repo_id>/analyze/', views.trigger_analysis, name='trigger-analysis'),
]
