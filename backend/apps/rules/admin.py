from django.contrib import admin
from .models import RuleViolation

@admin.register(RuleViolation)
class RuleViolationAdmin(admin.ModelAdmin):
    list_display = ('rule_name', 'severity', 'language', 'file_path', 'line_number', 'created_at')
    list_filter = ('severity', 'language', 'rule_name')
    search_fields = ('rule_name', 'file_path', 'message')
    readonly_fields = ('id', 'created_at')
