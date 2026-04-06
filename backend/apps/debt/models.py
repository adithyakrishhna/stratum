import uuid

from django.db import models


class DebtScore(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='debt_scores',
    )
    commit = models.ForeignKey(
        'ingestion.Commit',
        on_delete=models.CASCADE,
        related_name='debt_scores',
    )
    file_path = models.CharField(max_length=1024)
    language = models.CharField(max_length=50)
    complexity_component = models.FloatField(default=0.0)
    duplication_component = models.FloatField(default=0.0)
    violation_component = models.FloatField(default=0.0)
    cluster_component = models.FloatField(default=0.0)
    total_score = models.FloatField(default=0.0)
    # Rate of change vs the same file's score in the previous commit
    velocity = models.FloatField(default=0.0)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('repo', 'commit', 'file_path')]
        indexes = [
            models.Index(fields=['repo', 'file_path', '-recorded_at']),
            models.Index(fields=['repo', '-total_score']),
            models.Index(fields=['repo', '-velocity']),
        ]

    def __str__(self):
        return f'{self.file_path} score={self.total_score:.2f} @ {self.commit.sha[:8]}'
