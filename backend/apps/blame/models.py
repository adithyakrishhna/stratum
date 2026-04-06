import uuid

from django.db import models


class BlameMap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='blame_maps',
    )
    commit = models.OneToOneField(
        'ingestion.Commit',
        on_delete=models.CASCADE,
        related_name='blame_map',
    )
    debt_introduced_score = models.FloatField(default=0.0)
    patterns_originated = models.IntegerField(default=0)
    files_eventually_affected = models.IntegerField(default=0)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['repo', '-debt_introduced_score']),
        ]

    def __str__(self):
        return f'Blame {self.commit.sha[:8]} — score={self.debt_introduced_score:.2f}'
