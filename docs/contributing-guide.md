# Contributing to Stratum

Thank you for your interest in contributing.

---

## Development Setup

See [setup.md — Local Development](setup.md#local-development-setup-without-full-docker) for full instructions.

Quick start:

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
# Fill in GitHub credentials

docker compose -f docker-compose.dev.yml up -d   # start DB + Redis only
cd backend && pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

---

## Branch and Commit Convention

```
main      → stable, tagged releases only
develop   → active development, all PRs target this
feature/  → individual features, merged into develop via PR
```

Commit format:

```
feat:   new feature added
fix:    bug fixed
chore:  config, deps, tooling changes
docs:   documentation only
test:   tests added or updated
```

---

## Pull Request Rules

- All PRs target `develop`, never `main`
- One feature or fix per PR — no mixing unrelated changes
- No `TODO` comments in committed code
- Features must be complete before merging — no partial implementations

---

## Module Boundaries

Stratum is a modular monolith. Each Django app in `backend/apps/` owns its own models and logic.

- Never import models or internal functions from another app directly
- Communicate between apps through service interfaces only
- The `pr_review` app orchestrates other apps — it calls service functions, not models

```
apps/
  repositories/   ← repo management
  ingestion/      ← git walking, checkpoints
  parsing/        ← tree-sitter, language router
  security/       ← anti-pattern detection
  rules/          ← YAML rule engine
  clustering/     ← DBSCAN, cluster tracking
  debt/           ← scoring, velocity, timeline
  blame/          ← blame mapper
  pr_review/      ← PR orchestration (calls the above)
  dashboard/      ← views, charts, WebSockets
  webhooks/       ← receiver, HMAC verification
```

---

## Code Standards

New code should follow the same patterns already in the codebase:

- **Idempotency** — every Celery task safe to run twice (use `get_or_create`)
- **Fault tolerance** — tasks retry with exponential backoff; exhausted tasks go to `failed_tasks`
- **Observability** — structured logging (`structlog`) on every pipeline stage with `repo_id`, `stage`, `duration_ms`
- **Batch processing** — `bulk_create(batch_size=500)` for DB writes, never `.save()` in a loop
- **API consistency** — every response uses the `{success, data, meta, error}` envelope

---

## Feedback & Contributions

If you encounter any bugs or have feature requests, please feel free to open an issue on GitHub.