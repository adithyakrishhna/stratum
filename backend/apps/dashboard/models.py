import uuid

from django.db import models


class PipelineEvent(models.Model):
    """
    Records one start or completion event per pipeline stage per run.

    Written by every Celery task on stage start AND stage end (Principle 4).
    Displayed on Page 7 (Pipeline Monitor) via WebSockets.
    """
    class Status(models.TextChoices):
        STARTED   = 'started',   'Started'
        COMPLETED = 'completed', 'Completed'
        FAILED    = 'failed',    'Failed'

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_id         = models.UUIDField(db_index=True)
    task_id         = models.CharField(max_length=255, blank=True)
    stage           = models.CharField(max_length=100)
    status          = models.CharField(max_length=20, choices=Status.choices)
    items_processed = models.IntegerField(default=0)
    duration_ms     = models.IntegerField(default=0)
    error_message   = models.TextField(blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['repo_id', 'stage']),
            models.Index(fields=['repo_id', 'created_at']),
        ]

    def __str__(self):
        return f'[{self.stage}] {self.status} @ {self.created_at}'


class FailedTask(models.Model):
    """
    Dead-letter queue for Celery tasks that exhausted all retries.

    Displayed on Page 7 (Pipeline Monitor) with retry / dismiss options.
    The payload JSONB field stores enough context to re-enqueue the task.
    """
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_id       = models.UUIDField(db_index=True)
    task_name     = models.CharField(max_length=255)
    task_id       = models.CharField(max_length=255, blank=True)
    error_message = models.TextField()
    payload       = models.JSONField(default=dict)
    retry_count   = models.IntegerField(default=0)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['repo_id']),
        ]

    def __str__(self):
        return f'FAILED: {self.task_name} ({self.created_at})'
