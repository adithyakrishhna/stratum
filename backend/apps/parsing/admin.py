from django.contrib import admin
from .models import CodeChunk

@admin.register(CodeChunk)
class CodeChunkAdmin(admin.ModelAdmin):
    list_display = ('chunk_name', 'chunk_type', 'language', 'file_path', 'complexity_score', 'created_at')
    list_filter = ('chunk_type', 'language')
    search_fields = ('chunk_name', 'file_path')
    readonly_fields = ('id', 'created_at', 'embedding')
