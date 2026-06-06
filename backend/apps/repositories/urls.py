from django.urls import path

from . import views

app_name = 'repositories'

urlpatterns = [
    path('me/', views.current_user, name='current-user'),
    path('', views.list_repositories, name='list'),
    path('connect/', views.connect_repository, name='connect'),
    path('<uuid:repo_id>/analyze/', views.trigger_analysis, name='trigger-analysis'),
    path('<uuid:repo_id>/branches/', views.list_branches, name='list-branches'),
    path('<uuid:repo_id>/toggle-pr-review/', views.toggle_pr_review, name='toggle-pr-review'),
    path('<uuid:repo_id>/disconnect/', views.disconnect_repository, name='disconnect'),
]
