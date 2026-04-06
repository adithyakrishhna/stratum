"""
Stratum Embedding Microservice
-------------------------------
FastAPI service that wraps CodeBERT (microsoft/codebert-base) for
batch embedding inference. Isolated from the Django monolith so it
can be independently scaled and restarted without affecting PR review.

Endpoints
---------
POST /embed   — batch encode a list of code strings, return 384-dim vectors
GET  /health  — liveness check (also verifies model is loaded)
"""
from fastapi import FastAPI

app = FastAPI(
    title='Stratum Embedding Service',
    description='CodeBERT batch embedding inference for Stratum',
    version='0.1.0',
)


@app.get('/health')
async def health():
    return {'status': 'ok', 'model': 'microsoft/codebert-base'}


@app.post('/embed')
async def embed(payload: dict):
    """
    Placeholder — full implementation in Phase 3.
    Expects: {"texts": ["code snippet 1", ...]}
    Returns: {"embeddings": [[0.1, ...], ...]}
    """
    return {'embeddings': []}
