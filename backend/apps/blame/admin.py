from django.contrib import admin
from .models import BlameMap

@admin.register(BlameMap)
class BlameMapAdmin(admin.ModelAdmin):
    list_display = ('commit', 'repo', 'debt_introduced_score', 'patterns_originated', 'files_eventually_affected')
    list_filter = ('repo',)
    readonly_fields = ('id', 'calculated_at')
