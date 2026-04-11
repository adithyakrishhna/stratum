# Stratum

**AI-powered code review and technical debt tracking — fully self-hosted.**

Stratum watches your Pull Requests and your entire git history, then tells you two things most tools can't:

1. **What's wrong with this PR right now** — security vulnerabilities, dangerous functions, SQL injection, duplicate logic, complexity violations, and your custom rules — posted as inline GitHub comments within 60 seconds of opening a PR.

2. **How your codebase is decaying over time** — which files are getting worse, which patterns are spreading, which commits caused the most damage, and — before you merge — whether this PR will accelerate a spreading bad pattern.

> Self-hosted alternative to CodeRabbit + SonarQube. Your code never leaves your servers.  
> Supports: Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, Ruby, PHP.

---

## Quick Start

**You need:** Docker Desktop, a GitHub account, and about 15 minutes.

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
```

Fill in `.env` — the only required values to get started are your GitHub App credentials. See [Setup Guide](docs/setup.md) for a step-by-step walkthrough of creating the GitHub App (takes about 10 minutes).

```bash
docker compose up -d
```

Open **http://localhost:8000**, log in with GitHub, connect a repository, and click **Analyze**.

That's it. Stratum will walk your entire git history and start reviewing your next PR automatically.

**Full setup guide (GitHub App, ngrok, local dev, troubleshooting): [docs/setup.md](docs/setup.md)**

---

## What Stratum Does

### Automatic PR Review

Every time a Pull Request is opened or updated, Stratum posts a review automatically — no manual triggers needed. It checks for:

| Category | What it catches |
|---|---|
| Hardcoded secrets | API keys, tokens, passwords, database URLs in source code |
| SQL injection | String-concatenated queries, f-string queries with user input |
| Dangerous functions | `eval()`, `exec()`, `pickle.loads()`, `unsafe.Pointer` |
| Missing authentication | HTTP endpoints without `@login_required` or equivalent |
| Insecure randomness | `Math.random()` for tokens, `random.randint()` for passwords |
| Code complexity | Functions with cyclomatic complexity above your configured limit |
| Function length | Functions longer than your configured line limit |
| Duplicate logic | Functions semantically similar to existing code (AI-powered) |
| Custom rules | Whatever you define in `stratum.yaml` in your own repo |

Every finding includes the exact file and line number, an explanation, and a plain-English suggested fix (powered by Groq AI, free tier).

### Technical Debt Intelligence

This is where Stratum goes beyond any existing tool. After analyzing your git history, it gives you:

**Debt Timeline** — Pick any file. See its debt score for every single commit in your history. See exactly which commits made it worse and which cleaned it up.

**Velocity Heatmap** — Your entire codebase shown as a color-coded file tree. Red means a file is deteriorating fast. Green means it's improving. Grey means it's stable. Filter by language, directory, or time range.

**Semantic Cluster Map** — Stratum groups similar functions across your codebase into clusters. Each cluster represents a pattern that has been duplicated. You can see which clusters are growing (spreading anti-patterns) and trace them back to their origin commit.

**Blame Report** — Every commit in your history ranked by how much technical debt it introduced. Not by lines changed — by patterns started and how far those patterns eventually spread.

**PR Impact Prediction** — Before you merge, Stratum tells you: "This PR introduces 2 functions similar to Cluster #8, currently in 5 files. Merging accelerates that cluster's growth by ~35%. Consider consolidating before merging." No other tool does this.

---

## The 7 Dashboard Screens

| Screen | One-line description |
|---|---|
| Repository Overview | Current health score, top deteriorating files, spreading pattern count |
| PR Review Center | All PR reviews, findings by severity, debt impact per PR |
| Debt Timeline | Any file's debt score plotted commit-by-commit with inflection points |
| Semantic Cluster Map | Bubble chart of recurring code patterns, colored by growth rate |
| Velocity Heatmap | Full codebase as a color-coded file tree — see where debt is spreading |
| Blame Report | Commits ranked by debt introduced, exportable to CSV |
| Pipeline Monitor | Live ingestion progress, WebSocket updates, failed task retry |

**Not sure what "debt score," "velocity," or "semantic cluster" means? Start here: [Feature Guide](docs/features.md)**

---

## Who Is Stratum For?

### Individual developers
- Get consistent PR review without paying for SaaS tools
- Understand which areas of your own codebase are drifting
- See the long-term consequences of shortcuts before they compound

### Engineering teams
- Standardize review quality — every PR gets the same checks regardless of who reviews it
- Track which features or sprints introduced the most debt
- Give engineers visibility into the long-term impact of their changes before they merge
- Identify which files need refactoring attention most urgently

### Organizations
- **Full data privacy** — code stays inside your infrastructure, always
- No per-seat pricing — connect as many repos as your hardware supports
- Audit your entire engineering history: which patterns spread, which engineers introduced them, which areas are deteriorating
- HMAC-verified webhooks, no credentials in code, all secrets in `.env`

---

## How It Works

```
GitHub PR opened
      ↓
Webhook received (HMAC verified)
      ↓
PR files fetched from GitHub API
      ↓  ← runs in under 60 seconds
AST parsing (Tree-sitter, all 10 languages)
      ↓
Security detection + rule checking
      ↓
AI duplicate detection (CodeBERT embeddings + pgvector search)
      ↓
GitHub comment posted (inline findings + summary)
      ↓
Debt impact prediction (compared against full history)
```

For full git history analysis:

```
Connect repo → Analyze clicked
      ↓
Git history walked (50 commits per batch)
      ↓
Changed files only (sha256 fingerprint per file — unchanged files skipped)
      ↓
AST parsing → embeddings → pgvector storage
      ↓
Semantic clustering (DBSCAN) → debt scoring → blame mapping
      ↓
Dashboard populated, WebSocket progress updates
```

---

## Security Guarantees

- Code never leaves your infrastructure
- Only external calls: GitHub API (required) + Groq API (optional, disable with `ENABLE_LLM_SUGGESTIONS=false`)
- Raw source code not stored by default (`STORE_RAW_CODE=false`)
- Every GitHub webhook verified with HMAC-SHA256
- All credentials in `.env` only — never in source code

**Full security details: [docs/security.md](docs/security.md)**

---

## Documentation

| Guide | What's in it |
|---|---|
| [Setup Guide](docs/setup.md) | GitHub App creation, Docker setup, ngrok, local dev, troubleshooting |
| [Feature Guide](docs/features.md) | Every screen explained — what each term means and why it matters |
| [Configuration](docs/configuration.md) | Complete `stratum.yaml` and `.env` reference |
| [Security](docs/security.md) | Data flow, privacy guarantees, credential handling |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5, Celery, PostgreSQL 16 + pgvector |
| AI / Embeddings | CodeBERT (microsoft/codebert-base) via FastAPI microservice |
| Code Parsing | Tree-sitter (all 10 languages) |
| Real-time | Django Channels (WebSockets) + Redis |
| Frontend | React 18 + Vite + Tailwind CSS |
| Clustering | scikit-learn DBSCAN |
| Fix suggestions | Groq API (free tier) |
| Infrastructure | Docker Compose |
