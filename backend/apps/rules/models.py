import uuid

from django.db import models


class RuleViolation(models.Model):
    class Severity(models.TextChoices):
        CRITICAL = 'critical', 'Critical'
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='rule_violations',
    )
    # Nullable — violation may be from a PR review or a history scan, not both
    pr = models.ForeignKey(
        'pr_review.PullRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rule_violations',
    )
    commit = models.ForeignKey(
        'ingestion.Commit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rule_violations',
    )
    file_path = models.CharField(max_length=1024)
    rule_name = models.CharField(max_length=255)
    language = models.CharField(max_length=50)
    line_number = models.IntegerField(null=True, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['repo', 'severity', '-created_at']),
            models.Index(fields=['repo', 'rule_name']),
            models.Index(fields=['repo', 'language']),
        ]

    def __str__(self):
        return f'[{self.severity}] {self.rule_name} @ {self.file_path}:{self.line_number}'
