from django.contrib import admin
from .models import PullRequest, PrFinding

@admin.register(PullRequest)
class PullRequestAdmin(admin.ModelAdmin):
    list_display = ('github_pr_number', 'title_short', 'repo', 'status', 'health_score', 'opened_at')
    list_filter = ('status', 'repo')
    search_fields = ('title', 'author')
    readonly_fields = ('id',)
    def title_short(self, obj): return obj.title[:60]
    title_short.short_description = 'Title'

@admin.register(PrFinding)
class PrFindingAdmin(admin.ModelAdmin):
    list_display = ('title', 'finding_type', 'severity', 'file_path', 'line_number', 'created_at')
    list_filter = ('severity', 'finding_type')
    search_fields = ('title', 'file_path')
    readonly_fields = ('id', 'created_at')
