# =============================================================================
# Stratum — Django Backend Dockerfile
# =============================================================================
FROM python:3.12-slim

# System deps: git (for GitPython), build tools (for psycopg2, tree-sitter)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source (layer cache)
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ /app/

# Create directories that must exist at runtime
RUN mkdir -p /app/staticfiles /app/media /repo_clones /secrets

# Default port — overridden by docker-compose
EXPOSE 8000

# Entrypoint handles migrations + static files before starting the server
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
