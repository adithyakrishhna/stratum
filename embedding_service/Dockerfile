# =============================================================================
# Stratum — Embedding Microservice Dockerfile
# =============================================================================
FROM python:3.12-slim

# Build tools needed for torch / sentence-transformers native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY embedding_service/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download CodeBERT model weights at build time so the container starts fast
# Model is cached in ~/.cache/huggingface inside the image layer.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('microsoft/codebert-base')"

COPY embedding_service/ /app/

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
