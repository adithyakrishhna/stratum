"""
Stratum Embedding Microservice
-------------------------------
FastAPI service wrapping CodeBERT (microsoft/codebert-base) for batch
embedding inference. Isolated from the Django monolith so it can be
independently scaled and restarted without affecting PR review.

Design decisions
----------------
- Model loaded once at startup, held in module-level variable
- Batch size 64: optimal for CodeBERT on CPU (Optimization 1)
- /embed accepts up to 512 texts per request; caller batches beyond that
- All embeddings are L2-normalised before returning so cosine similarity
  equals dot product — pgvector cosine_ops benefits from this
- /health verifies the model is actually loaded (not just that the process
  is alive) — Docker healthcheck depends on this
"""
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import structlog
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Model — loaded once at startup, never reloaded
# ---------------------------------------------------------------------------

_model = None
_MODEL_NAME = "microsoft/codebert-base"
_EMBEDDING_DIM = 768  # CodeBERT base hidden size; sentence-transformers pools to this
_BATCH_SIZE = 64      # Optimization 1: 64 chunks per batch inference call


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load CodeBERT on startup. Fast because Dockerfile pre-downloads it."""
    global _model

    logger.info("embedding_service_startup", model=_MODEL_NAME)
    start_ts = time.monotonic()

    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
        # Warm-up pass so first real request isn't slow
        _model.encode(["warmup"], batch_size=1, show_progress_bar=False)
        elapsed_ms = int((time.monotonic() - start_ts) * 1000)
        logger.info(
            "embedding_model_loaded",
            model=_MODEL_NAME,
            dimensions=_model.get_sentence_embedding_dimension(),
            load_ms=elapsed_ms,
        )
    except Exception as exc:
        logger.error("embedding_model_load_failed", model=_MODEL_NAME, error=str(exc))
        raise

    yield  # application runs here

    logger.info("embedding_service_shutdown")
    _model = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Stratum Embedding Service",
    description="CodeBERT batch embedding inference for Stratum",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EmbedRequest(BaseModel):
    texts: list[str] = Field(
        ...,
        min_length=1,
        max_length=512,
        description="List of code strings to embed (max 512 per request)",
    )


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    count: int
    model: str
    dimensions: int


class HealthResponse(BaseModel):
    status: str
    model: str
    dimensions: int
    model_loaded: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    """
    Liveness + readiness check.

    Returns 200 only when the model is fully loaded.
    Docker healthcheck and pybreaker health probe both call this.
    """
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not loaded yet",
        )
    return HealthResponse(
        status="ok",
        model=_MODEL_NAME,
        dimensions=_model.get_sentence_embedding_dimension(),
        model_loaded=True,
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """
    Embed a batch of code strings using CodeBERT.

    Accepts up to 512 texts per call. Internally processes them in
    sub-batches of 64 (optimal for CPU inference).

    Returns 384-dimensional embedding vectors (one per input text).
    Vectors are L2-normalised so cosine similarity = dot product.
    """
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model not loaded",
        )

    start_ts = time.monotonic()

    texts = request.texts
    all_embeddings: list[list[float]] = []

    # Process in sub-batches of 64 (Optimization 1)
    for batch_start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[batch_start : batch_start + _BATCH_SIZE]
        batch_vecs = _model.encode(
            batch,
            batch_size=_BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True,   # L2-normalise → cosine = dot product
            convert_to_numpy=True,
        )
        all_embeddings.extend(batch_vecs.tolist())

    elapsed_ms = int((time.monotonic() - start_ts) * 1000)
    dims = _model.get_sentence_embedding_dimension()

    logger.info(
        "embed_batch_complete",
        input_count=len(texts),
        dimensions=dims,
        duration_ms=elapsed_ms,
    )

    return EmbedResponse(
        embeddings=all_embeddings,
        count=len(all_embeddings),
        model=_MODEL_NAME,
        dimensions=dims,
    )
