#!/bin/bash
# =============================================================================
# Stratum Django entrypoint
# Runs database migrations and collects static files before starting the server.
# =============================================================================
set -e

echo "[entrypoint] Running database migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
python manage.py collectstatic --noinput

echo "[entrypoint] Starting Daphne ASGI server on 0.0.0.0:8000..."
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application
