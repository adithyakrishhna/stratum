# Stratum

Self-hosted AI code review and technical debt tracking for engineering teams.

Stratum does two things:

1. **Reviews Pull Requests automatically** — security vulnerabilities, dangerous functions, SQL injection, duplicate logic, complexity violations, and custom rules — posted as inline GitHub comments when a PR is opened.

2. **Tracks how technical debt evolves across your git history** — which files are getting worse, which patterns are spreading, which commits introduced the most debt, and how a PR will affect your codebase's long-term health before you merge.

Runs entirely on your own infrastructure. Code stays on your servers.

Supports: Python, JavaScript (+ JSX), TypeScript (+ TSX), Java, Go, Rust, C, C++, Ruby, PHP.

---

## Quick Start

**You need:** Docker Desktop and a GitHub account.

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
# Fill in GitHub App credentials — see docs/setup.md for a step-by-step walkthrough
docker compose up -d
```

Open **http://localhost:8000**, log in with GitHub, connect a repository, click **Analyze**.

**Full setup guide (GitHub App, ngrok, local dev): [docs/setup.md](docs/setup.md)**

---

## What Stratum Does

### Automatic PR Review

When a pull request is opened or updated, Stratum posts a review automatically:

| Category | What it checks |
|---|---|
| Hardcoded secrets | API keys, tokens, passwords, database URLs in source code |
| SQL injection | String-concatenated queries, f-string queries with user input |
| Dangerous functions | `eval()`, `exec()`, `pickle.loads()` and language equivalents |
| Missing authentication | HTTP endpoints without an auth decorator |
| Insecure randomness | `Math.random()` for tokens, `random.randint()` for passwords |
| Code complexity | Functions above your configured cyclomatic complexity limit |
| Function length | Functions longer than your configured line limit |
| Duplicate logic | Functions semantically similar to existing code (AI-powered) |
| Custom rules | Forbidden imports, naming conventions — defined in your `stratum.yaml` |

Each finding includes the exact file and line number, an explanation, and a suggested fix (via Groq API, optional).

### Technical Debt Tracking

After ingesting your git history, Stratum provides:

- **Debt Timeline** — any file's debt score plotted commit-by-commit across your full history
- **Velocity Heatmap** — your entire codebase as a color-coded file tree (red = deteriorating, green = improving)
- **Semantic Cluster Map** — groups of similar functions tracked across files and time
- **Blame Report** — commits ranked by debt introduced (by patterns spread, not lines changed)
- **PR Impact Prediction** — before you merge, see which existing patterns a PR will join and how much it accelerates their growth

---

## How It Compares

| Feature | Stratum | SonarQube (Community) | CodeClimate | GitHub Advanced Security | CodeRabbit |
|---|---|---|---|---|---|
| Self-hosted | ✅ | ✅ | ❌ SaaS | ❌ SaaS | ❌ SaaS |
| Code stays on your servers | ✅ | ✅ | ❌ | ❌ | ❌ |
| Free to use | ✅ Open source | ✅ Community edition | ❌ Paid | ❌ Paid (GitHub Enterprise) | ❌ Paid |
| Inline PR comments | ✅ | ❌ | ✅ | ✅ | ✅ |
| Security detection | ✅ | ✅ | ✅ | ✅ | ✅ |
| Custom rules (YAML) | ✅ | ✅ | ✅ | ⚠️ Limited | ⚠️ Limited |
| AI duplicate detection | ✅ | ❌ | ❌ | ❌ | ✅ |
| Debt score per commit | ✅ | ❌ | ⚠️ Score today only | ❌ | ❌ |
| Full git history analysis | ✅ | ❌ | ❌ | ❌ | ❌ |
| Semantic cluster tracking | ✅ | ❌ | ❌ | ❌ | ❌ |
| Velocity heatmap | ✅ | ❌ | ❌ | ❌ | ❌ |
| PR debt impact prediction | ✅ | ❌ | ❌ | ❌ | ❌ |
| LLM fix suggestions | ✅ (Groq, optional) | ❌ | ❌ | ❌ | ✅ |
| Supports 10+ languages | ✅ | ✅ | ✅ | ✅ | ✅ |

> Comparison reflects publicly documented features as of early 2025. Paid tiers of some tools may include features not listed here.

---

## The 7 Dashboard Screens

| Screen | What it shows |
|---|---|
| Repository Overview | Health score, top deteriorating files, spreading pattern count |
| PR Review Center | All PR reviews, findings by severity, debt impact per PR |
| Debt Timeline | Any file's debt score plotted commit-by-commit with inflection points |
| Semantic Cluster Map | Bubble chart of recurring code patterns, colored by growth rate |
| Velocity Heatmap | Full codebase as a color-coded file tree |
| Blame Report | Commits ranked by debt introduced, exportable CSV |
| Pipeline Monitor | Live ingestion progress via WebSocket, failed task retry |

**Every screen and term explained in plain English: [docs/features.md](docs/features.md)**

---

## Who Is It For?

**Individual developers** — automated PR review without a SaaS subscription, and visibility into where your codebase is drifting over time.

**Engineering teams** — consistent review quality across every PR, data to guide refactoring priorities, and long-term visibility into how technical debt accumulates across sprints.

**Organizations** — code stays on your servers, no per-seat pricing, audit your full engineering history across all repositories.

---

## Security

- Code never leaves your infrastructure
- External calls: GitHub API (required) + Groq API (optional, can be disabled)
- Raw source code not stored by default (`STORE_RAW_CODE=false`)
- HMAC-SHA256 verification on every GitHub webhook request
- All credentials in `.env` only — never in source code

**Full security details: [docs/security.md](docs/security.md)**

---

## Documentation

| | |
|---|---|
| [Setup Guide](docs/setup.md) | Docker, GitHub App, ngrok, local dev, troubleshooting |
| [Feature Guide](docs/features.md) | Every screen and term explained in plain English |
| [Configuration](docs/configuration.md) | `stratum.yaml` and `.env` reference |
| [Security](docs/security.md) | Data flow, privacy, credential handling |
| [Contributing](docs/contributing.md) | Development setup and contribution guidelines |

---

## Tech Stack

Django · Celery · PostgreSQL 16 + pgvector · Redis · FastAPI · React 18 · Vite · Tailwind CSS · Tree-sitter · CodeBERT · scikit-learn · Docker Compose
