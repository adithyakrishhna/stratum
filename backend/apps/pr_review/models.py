import uuid

from django.db import models


class PullRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        CLOSED = 'closed', 'Closed'
        MERGED = 'merged', 'Merged'
        ANALYZING = 'analyzing', 'Analyzing'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='pull_requests',
    )
    github_pr_number = models.IntegerField()
    title = models.CharField(max_length=1024)
    author = models.CharField(max_length=255)
    base_branch = models.CharField(max_length=255)
    head_branch = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    health_score = models.FloatField(null=True, blank=True)
    debt_impact_score = models.FloatField(null=True, blank=True)
    opened_at = models.DateTimeField()
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('repo', 'github_pr_number')]
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['repo', 'status']),
        ]

    def __str__(self):
        return f'PR #{self.github_pr_number} — {self.title[:60]}'


class PrFinding(models.Model):
    class Severity(models.TextChoices):
        CRITICAL = 'critical', 'Critical'
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'
        INFO = 'info', 'Info'

    class FindingType(models.TextChoices):
        SECURITY = 'security', 'Security'
        DUPLICATE = 'duplicate', 'Duplicate Logic'
        RULE = 'rule', 'Rule Violation'
        COMPLEXITY = 'complexity', 'Complexity'
        DEBT_IMPACT = 'debt_impact', 'Debt Impact'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pr = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name='findings')
    file_path = models.CharField(max_length=1024)
    line_number = models.IntegerField(null=True, blank=True)
    finding_type = models.CharField(max_length=20, choices=FindingType.choices)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    title = models.CharField(max_length=255)
    description = models.TextField()
    suggestion = models.TextField(blank=True)
    github_comment_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['severity', '-created_at']
        indexes = [
            models.Index(fields=['pr', 'severity']),
            models.Index(fields=['pr', 'finding_type']),
        ]

    def __str__(self):
        return f'[{self.severity}] {self.title} @ {self.file_path}'
