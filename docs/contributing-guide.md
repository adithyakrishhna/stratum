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

cd backend
python -m venv venv
source venv/Scripts/activate    # Windows
# source venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

> Regular users running Stratum via `docker compose up -d` do not need Python or a virtual environment — Docker handles all dependencies inside containers. The venv above is only for contributors editing the backend code directly.

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

## Supported Languages

Stratum currently supports exactly these 10 languages. Support is provided by Tree-sitter (parsing), CodeBERT (embeddings), and custom detectors (security rules). Adding a new language requires changes in all three areas.

| Language | AST Parsing | Embeddings | Security Rules |
|---|---|---|---|
| Python | ✅ | ✅ Excellent | ✅ |
| JavaScript | ✅ | ✅ Excellent | ✅ |
| TypeScript | ✅ | ✅ Excellent | ✅ |
| Java | ✅ | ✅ Good | ✅ |
| Go | ✅ | ✅ Good | ✅ |
| Ruby | ✅ | ✅ Good | ✅ |
| PHP | ✅ | ✅ Good | ✅ |
| C | ✅ | ⚠️ Fair | ✅ |
| C++ | ✅ | ⚠️ Fair | ✅ |
| Rust | ✅ | ⚠️ Fair | ✅ |

**Embedding accuracy note:** CodeBERT was trained primarily on Python and Java. Embeddings for C, C++, and Rust work but produce lower semantic accuracy for duplicate detection. Cross-language embedding similarity is experimental and off by default.

To add a new language: add a Tree-sitter grammar to `apps/parsing/language_router.py`, add security patterns to `apps/security/detectors/`, and extend `apps/rules/evaluator.py` for naming/import rules.

---

## Potential Enhancements

These are known areas where contributions are welcome. Each is a self-contained addition that doesn't require changing existing functionality.

| Enhancement | Area | Complexity |
|---|---|---|
| Add Swift, Kotlin, Dart, Scala language support | `apps/parsing`, `apps/security` | Medium |
| GitLab webhook integration (mirrors GitHub flow) | `apps/webhooks`, `apps/pr_review` | Medium |
| Bitbucket webhook integration | `apps/webhooks`, `apps/pr_review` | Medium |
| VS Code extension — show debt score in editor gutter | New: `vscode-extension/` | High |
| SARIF export for GitHub Code Scanning integration | `apps/pr_review` | Low |
| Slack / Teams notification on PR review complete | `apps/pr_review` | Low |
| `stratum.yaml` per-directory rule overrides | `apps/rules` | Medium |
| Configurable DBSCAN parameters via stratum.yaml | `apps/clustering` | Low |
| Side-by-side diff view in PR Review Center | `frontend/` | Medium |
| REST API for external CI/CD pipeline integration | `apps/dashboard` | Medium |

---

## Feedback & Contributions

If you encounter any bugs or have feature requests, please feel free to open an issue on GitHub.