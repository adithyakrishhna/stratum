# Contributing to Stratum

Thank you for your interest in contributing.

---

## Development Setup

See [docs/setup.md — Local Development](docs/setup.md#local-development-setup-without-full-docker) for full instructions on running Stratum locally without Docker.

Quick version:

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
# Fill in GitHub credentials in .env

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

Examples:
```
feat: add debt inflection point detection
fix: eliminate duplicate detection false positives from stop-word names
docs: add setup guide and feature explanations
test: add security anti-pattern test files
```

---

## Pull Request Rules

- All PRs target `develop`, never `main`
- One feature or fix per PR — avoid mixing unrelated changes
- No `TODO` comments in any committed code
- No half-built features — a PR either fully works or is not merged
- Every PR is reviewed by Stratum itself (it runs on its own webhook)

---

## Module Boundaries

Stratum is a modular monolith. Each Django app in `backend/apps/` owns its own models and logic. The rules:

- Never import models or internal functions from another app directly
- Communicate between apps through defined service interfaces only
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

All new code must follow the system design principles in `CLAUDE.md`:

1. **Idempotency** — every Celery task must be safe to run twice
2. **Fault tolerance** — tasks retry with exponential backoff, failed tasks go to the `failed_tasks` table
3. **Observability** — structured logging (`structlog`) on every pipeline stage with `repo_id`, `stage`, `duration_ms`
4. **Batch processing** — never process one item at a time; use `bulk_create(batch_size=500)` for DB writes
5. **API consistency** — every response follows the `{success, data, meta, error}` envelope

---

## Questions

Open an issue on GitHub for bugs or feature requests.
