from django.contrib import admin
from .models import DebtScore

@admin.register(DebtScore)
class DebtScoreAdmin(admin.ModelAdmin):
    list_display = ('file_path', 'repo', 'total_score', 'velocity', 'language', 'recorded_at')
    list_filter = ('language',)
    search_fields = ('file_path',)
    readonly_fields = ('id', 'recorded_at')
