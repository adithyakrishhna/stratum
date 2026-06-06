from django.contrib import admin
from .models import SemanticCluster, ClusterMembership

@admin.register(SemanticCluster)
class SemanticClusterAdmin(admin.ModelAdmin):
    list_display = ('centroid_short', 'language', 'repo', 'chunk_count', 'file_count', 'growth_rate', 'is_flagged')
    list_filter = ('language', 'is_flagged')
    readonly_fields = ('id',)
    def centroid_short(self, obj): return obj.centroid_hash[:12]
    centroid_short.short_description = 'Centroid Hash'

@admin.register(ClusterMembership)
class ClusterMembershipAdmin(admin.ModelAdmin):
    list_display = ('cluster', 'chunk', 'similarity_score', 'joined_at')
    readonly_fields = ('id', 'joined_at')
