import uuid

from django.db import models
from pgvector.django import HnswIndex, VectorField


class CodeChunk(models.Model):
    class ChunkType(models.TextChoices):
        FUNCTION = 'function', 'Function'
        METHOD = 'method', 'Method'
        CLASS = 'class', 'Class'
        MODULE = 'module', 'Module'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    commit = models.ForeignKey(
        'ingestion.Commit',
        on_delete=models.CASCADE,
        related_name='code_chunks',
    )
    repo = models.ForeignKey(
        'repositories.Repository',
        on_delete=models.CASCADE,
        related_name='code_chunks',
    )
    file_path = models.CharField(max_length=1024)
    chunk_name = models.CharField(max_length=255)
    chunk_type = models.CharField(max_length=20, choices=ChunkType.choices)
    language = models.CharField(max_length=50)
    start_line = models.IntegerField()
    end_line = models.IntegerField()
    complexity_score = models.FloatField(default=0.0)
    # Stored only when STORE_RAW_CODE=true; null otherwise to reduce DB size
    raw_code = models.TextField(null=True, blank=True)
    # 384-dim CodeBERT embedding — null until embedding microservice processes it
    embedding = VectorField(dimensions=384, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['repo', 'file_path']),
            models.Index(fields=['commit', 'file_path', 'chunk_name']),
            models.Index(fields=['language']),
            # HNSW approximate nearest-neighbor index (Optimization 6 — 400x speedup)
            HnswIndex(
                name='code_chunk_embedding_hnsw',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return f'{self.chunk_name} ({self.language}) @ {self.file_path}:{self.start_line}'
