from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('<uuid:repo_id>/overview/',                          views.overview,            name='overview'),
    path('<uuid:repo_id>/prs/',                               views.pr_list,             name='pr-list'),
    path('<uuid:repo_id>/debt/timeline/',                     views.debt_timeline,       name='debt-timeline'),
    path('<uuid:repo_id>/clusters/',                          views.cluster_map,         name='cluster-map'),
    path('<uuid:repo_id>/heatmap/',                           views.velocity_heatmap,    name='velocity-heatmap'),
    path('<uuid:repo_id>/blame/',                             views.blame_report,        name='blame-report'),
    path('<uuid:repo_id>/pipeline/',                          views.pipeline_monitor,    name='pipeline-monitor'),
    path('<uuid:repo_id>/failed-tasks/<uuid:task_id>/retry/', views.retry_failed_task,   name='retry-task'),
    path('<uuid:repo_id>/failed-tasks/<uuid:task_id>/dismiss/', views.dismiss_failed_task, name='dismiss-task'),
]
