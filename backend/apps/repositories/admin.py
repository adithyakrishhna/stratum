from django.contrib import admin
from .models import Repository, UserRepository

@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'owner', 'analysis_status', 'is_private', 'created_at')
    list_filter = ('analysis_status', 'is_private')
    search_fields = ('full_name', 'owner', 'name')
    readonly_fields = ('id', 'created_at', 'updated_at')

@admin.register(UserRepository)
class UserRepositoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'repository', 'role')
    list_filter = ('role',)
