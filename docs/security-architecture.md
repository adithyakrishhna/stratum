# Security

Stratum is designed from the ground up for self-hosted deployment where your code never leaves your infrastructure. This document explains exactly what data flows where, what is stored, and how every external touchpoint is secured.

---

## What Leaves Your Infrastructure

Stratum makes external calls to exactly two services. Both are optional in different ways.

### 1. GitHub API (required)

**What is sent:** Repository metadata, PR file diffs, PR comments (posted back to GitHub).

**What is NOT sent:** Raw source code files are never sent to GitHub's API beyond what GitHub itself serves you. Stratum fetches the diff of a PR (which GitHub already has) and posts comment text back — no full file contents are transmitted.

**Why it's required:** Without GitHub API access, Stratum cannot receive PR events or post review comments.

**How it's secured:** All calls use your GitHub App's private key (JWT authentication) or your Personal Access Token. The private key never leaves your server — it's used locally to sign JWTs.

### 2. Groq API (optional)

**What is sent:** A short code snippet (the specific line with a finding) plus a prompt asking for a fix suggestion.

**What is NOT sent:** Full file contents, commit history, embeddings, or any other data.

**Why it's optional:** Fix suggestions are a convenience feature. All security findings, rule violations, and duplicate detection work without Groq. Set `ENABLE_LLM_SUGGESTIONS=false` in `.env` to disable all Groq calls entirely — no data leaves your infra for LLM purposes.

**Groq's data policy:** Groq states that API inputs are not used for model training. See [groq.com/privacy](https://groq.com/privacy) for their current policy.

---

## What's Stored

All data is stored in **your PostgreSQL database** running in your Docker environment.

| Data type | Stored? | Notes |
|---|---|---|
| Repository metadata | Yes | Name, owner, default branch, analysis status |
| Commit metadata | Yes | SHA, author, date, message, files changed |
| Function-level code structure | Yes | File path, function name, start/end line, complexity score |
| Code embeddings | Yes | 384-dimensional vectors — mathematical representations of function meaning. These are not human-readable. Reconstructing source code from embeddings alone is not feasible. |
| Raw source code | Configurable | `STORE_RAW_CODE=false` by default — raw code is NOT stored. Set to `true` only if you explicitly want it. |
| PR findings | Yes | File path, line number, finding type, severity, description, suggestion |
| Pipeline events | Yes | Stage progress, duration, errors |

**The key point:** With `STORE_RAW_CODE=false` (the default), no one with database access can read your source code. They would see embeddings (opaque vectors), metadata, and finding descriptions — but not the actual code.

---

## Webhook Security (HMAC-SHA256)

Every request from GitHub to your Stratum webhook endpoint (`/api/webhooks/github/`) is verified before any processing begins.

**How it works:**
1. When you set up your GitHub App, you generate a webhook secret and store it in `.env` as `GITHUB_WEBHOOK_SECRET`
2. GitHub signs every webhook payload using HMAC-SHA256 with that secret
3. Stratum verifies the signature on every incoming request before reading any payload data
4. Requests with missing or invalid signatures are rejected with HTTP 403

**What this prevents:** Anyone who discovers your webhook URL cannot send fake PR events or trigger analysis on arbitrary code. Only genuine events from GitHub (signed with your secret) are processed.

---

## Credential Handling

**GitHub App private key:**
- Stored only at `./secrets/stratum-app.private-key.pem` on your host
- The `secrets/` directory is in `.gitignore` — it will never be accidentally committed
- Mounted read-only into the Docker container at `/secrets/`
- Never transmitted anywhere — used locally to sign authentication JWTs

**All other credentials (API keys, passwords, OAuth secrets):**
- Stored only in `.env` on your host
- `.env` is in `.gitignore` — it will never be accidentally committed
- Passed to Docker containers via `env_file: .env` — never hardcoded in any source file

**Django secret key:**
- Used for cryptographic signing of sessions and CSRF tokens
- Must be a unique, random string per installation
- Generate with: `python -c "import secrets; print(secrets.token_urlsafe(50))"`

---

## Private Repository Access

For private repositories, Stratum needs permission to clone and read code. Two options:

**Option A — GitHub App (recommended):**
When you install your GitHub App on a repository, GitHub grants it the permissions you configured (Contents: Read). The App's private key (stored only on your server) is used to authenticate. No passwords, no OAuth tokens stored.

**Option B — Personal Access Token:**
Set `GITHUB_PERSONAL_ACCESS_TOKEN` in `.env`. Requires the `repo` scope. Simpler to set up but less granular — the token has access to all repos under your account. Use a fine-grained PAT and restrict it to specific repositories.

---

## Deleting a Repository

When you disconnect a repository from Stratum, all associated data is deleted:
- All code chunks and embeddings
- All commit records
- All debt scores and cluster memberships
- All PR findings
- All pipeline events

Embeddings for that repository are permanently removed from pgvector. Nothing is retained.

---

## Network Security

**In Docker Compose (default):**
- PostgreSQL and Redis are not exposed to the host network — they're only accessible to other containers in the same Compose network
- Only Django (port 8000) and the embedding service (port 8001) are exposed
- In production, put an Nginx or Caddy reverse proxy in front of Django and expose only port 443

**Recommended production setup:**
```
Internet → Nginx (HTTPS, port 443) → Django (port 8000, internal)
                                    → embedding (port 8001, internal only)
```

The embedding service should never be publicly accessible — it processes code and has no authentication.

---

## Security Checklist for Production

Before deploying Stratum to a production server:

- [ ] `DEBUG=False` in `.env`
- [ ] `DJANGO_SECRET_KEY` is a unique, random 50+ character string
- [ ] `DB_PASSWORD` is changed from the default `postgres123`
- [ ] `ALLOWED_HOSTS` contains only your actual domain(s)
- [ ] HTTPS is enabled (via Nginx/Caddy reverse proxy)
- [ ] Embedding service (port 8001) is NOT exposed to the internet
- [ ] PostgreSQL and Redis ports are NOT exposed to the internet
- [ ] `.env` file permissions: `chmod 600 .env`
- [ ] `secrets/` directory permissions: `chmod 700 secrets/`
- [ ] Regular backups of the PostgreSQL volume

---

## Reporting Security Issues

If you discover a security vulnerability in Stratum, please report it privately by opening a GitHub Security Advisory rather than a public issue. This allows time to prepare a fix before the vulnerability is disclosed.
