import uuid

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class Repository(models.Model):
    class AnalysisStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    github_repo_id = models.IntegerField(unique=True)
    owner = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    full_name = models.CharField(max_length=511)
    is_private = models.BooleanField(default=True)
    default_branch = models.CharField(max_length=255, default='main')
    github_app_installation_id = models.IntegerField(null=True, blank=True)
    last_analyzed_commit = models.CharField(max_length=40, null=True, blank=True)
    analysis_status = models.CharField(
        max_length=20,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'repositories'
        ordering = ['-created_at']

    def __str__(self):
        return self.full_name


class UserRepository(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        VIEWER = 'viewer', 'Viewer'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_repositories')
    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name='user_repositories'
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        unique_together = [('user', 'repository')]

    def __str__(self):
        return f'{self.user} → {self.repository} ({self.role})'
