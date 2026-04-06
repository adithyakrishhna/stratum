import uuid

from django.db import models


class Commit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='commits',
    )
    sha = models.CharField(max_length=40, unique=True)
    author_name = models.CharField(max_length=255)
    author_email = models.CharField(max_length=255)
    message = models.TextField()
    committed_at = models.DateTimeField()
    files_changed = models.IntegerField(default=0)
    debt_score_delta = models.FloatField(default=0.0)
    is_processed = models.BooleanField(default=False)

    class Meta:
        ordering = ['committed_at']
        indexes = [
            models.Index(fields=['repo', 'committed_at']),
            models.Index(fields=['repo', 'is_processed']),
        ]

    def __str__(self):
        return f'{self.sha[:8]} — {self.message[:60]}'


class PipelineEvent(models.Model):
    class Status(models.TextChoices):
        STARTED = 'started', 'Started'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='pipeline_events',
    )
    task_id = models.CharField(max_length=255, blank=True)
    stage = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices)
    items_processed = models.IntegerField(default=0)
    duration_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['repo', 'stage', '-created_at']),
        ]

    def __str__(self):
        return f'{self.stage} — {self.status} ({self.repo})'


class FailedTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='failed_tasks',
    )
    task_name = models.CharField(max_length=255)
    task_id = models.CharField(max_length=255)
    error_message = models.TextField()
    payload = models.JSONField(default=dict)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.task_name} failed ({self.retry_count} retries)'
