import uuid

from django.db import models


class SemanticCluster(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='clusters',
    )
    # Stable ID — sha256 hash of centroid embedding. Never changes between runs.
    centroid_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=255, blank=True)
    language = models.CharField(max_length=50)
    first_seen_at = models.DateTimeField()
    file_count = models.IntegerField(default=0)
    chunk_count = models.IntegerField(default=0)
    growth_rate = models.FloatField(default=0.0)
    is_flagged = models.BooleanField(default=False)
    origin_commit = models.ForeignKey(
        'ingestion.Commit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originated_clusters',
    )

    class Meta:
        indexes = [
            models.Index(fields=['repo', 'language']),
            models.Index(fields=['repo', 'is_flagged']),
            models.Index(fields=['repo', '-growth_rate']),
        ]

    def __str__(self):
        return f'Cluster {self.centroid_hash[:8]} ({self.language}, {self.chunk_count} chunks)'


class ClusterMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cluster = models.ForeignKey(
        SemanticCluster,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    chunk = models.ForeignKey(
        'parsing.CodeChunk',
        on_delete=models.CASCADE,
        related_name='cluster_memberships',
    )
    similarity_score = models.FloatField()
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('cluster', 'chunk')]
        indexes = [
            models.Index(fields=['cluster', '-similarity_score']),
        ]

    def __str__(self):
        return f'Chunk → {self.cluster} ({self.similarity_score:.2f})'
