from django.urls import path

from . import views

app_name = 'repositories'

urlpatterns = [
    path('me/', views.current_user, name='current-user'),
]
