from django.contrib import admin
from .models import Commit, PipelineEvent, FailedTask

@admin.register(Commit)
class CommitAdmin(admin.ModelAdmin):
    list_display = ('sha_short', 'repo', 'author_name', 'committed_at', 'is_processed', 'files_changed')
    list_filter = ('is_processed', 'repo')
    search_fields = ('sha', 'author_name', 'author_email', 'message')
    readonly_fields = ('id',)
    def sha_short(self, obj): return obj.sha[:8]
    sha_short.short_description = 'SHA'

@admin.register(PipelineEvent)
class PipelineEventAdmin(admin.ModelAdmin):
    list_display = ('stage', 'status', 'repo', 'items_processed', 'duration_ms', 'created_at')
    list_filter = ('stage', 'status')
    readonly_fields = ('id', 'created_at')

@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ('task_name', 'repo', 'retry_count', 'created_at')
    list_filter = ('task_name',)
    readonly_fields = ('id', 'created_at')
