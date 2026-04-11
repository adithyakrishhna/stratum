# Setup Guide

This guide walks you through getting Stratum running from zero. Most of the time is spent on creating the GitHub App (a one-time ~10 minute process). After that, starting Stratum is a single command.

---

## Prerequisites

- **Docker Desktop** installed and running
- A **GitHub account**
- A terminal (PowerShell, bash, or any shell)

---

## Step 1 — Clone and Configure

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
```

You will come back to fill in `.env` after the next step.

---

## Step 2 — Create Your GitHub App

Stratum uses a GitHub App to receive webhook events (PR opened, updated) and post review comments. This is a one-time setup per GitHub account or organization.

### 2a. Open GitHub App settings

- Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
- Or for an organization: **Organization Settings → Developer settings → GitHub Apps → New GitHub App**

### 2b. Fill in the app details

| Field | Value |
|---|---|
| GitHub App name | `Stratum Local` (or any name you like) |
| Homepage URL | `http://localhost:8000` |
| Webhook URL | See note below |
| Webhook secret | Generate a random string — paste it in `.env` as `GITHUB_WEBHOOK_SECRET` |

**Webhook URL:**
- **Docker / production with a real domain:** `https://yourdomain.com/webhooks/github/`
- **Local development (your laptop):** You need a tunnel — see [Receiving Webhooks Locally](#receiving-webhooks-locally-ngrok). For now, put a placeholder like `https://placeholder.example.com/webhooks/github/` and update it after ngrok is running.

### 2c. Set permissions

Under **Repository permissions**, grant:

| Permission | Access |
|---|---|
| Contents | Read |
| Issues | Read |
| Metadata | Read |
| Pull requests | Read & Write |
| Webhooks | Read & Write |

### 2d. Subscribe to events

Check these events under **Subscribe to events**:

- Pull request
- Push

### 2e. Finalize

- Set **Where can this GitHub App be installed?** to **Only on this account** (for personal use) or **Any account** (for teams)
- Click **Create GitHub App**

### 2f. Collect your credentials

After creating the app:

1. Copy the **App ID** → paste into `.env` as `GITHUB_APP_ID`
2. Scroll down to **Private keys** → click **Generate a private key**
3. A `.pem` file will download. **Move it to the `secrets/` folder** inside your Stratum directory and rename it to `stratum-app.private-key.pem`

```
stratum/
  secrets/
    stratum-app.private-key.pem   ← put the downloaded .pem here
```

### 2g. Create GitHub OAuth app (for dashboard login)

Stratum's dashboard uses GitHub OAuth so you can log in with your GitHub account.

- Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App**
- Homepage URL: `http://localhost:8000`
- Authorization callback URL: `http://localhost:8000/accounts/github/login/callback/`
- Copy **Client ID** and **Client Secret** into `.env`

### 2h. Your .env should now look like this

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-random-secret-here
GITHUB_OAUTH_CLIENT_ID=abc123
GITHUB_OAUTH_CLIENT_SECRET=def456
```

Everything else in `.env` can stay at its default value to start.

---

## Step 3 — Start Stratum

```bash
docker compose up -d
```

This starts 9 services: PostgreSQL, Redis, Django, the FastAPI embedding microservice, and 5 Celery workers. First run takes a few minutes as Docker pulls images and builds containers.

Check that everything started:

```bash
docker compose ps
```

All services should show `Up` or `Up (healthy)`. The embedding service takes the longest to become healthy (it downloads the CodeBERT model on first start, ~400MB).

Open **http://localhost:8000** and log in with GitHub.

---

## Step 4 — Add stratum.yaml to Your Repository

`stratum.yaml` goes in the **root of the repository you want to review** — not inside the Stratum repo itself. It tells Stratum which rules to apply to that repo.

Copy `stratum.yaml.example` from the Stratum directory as a starting point:

```yaml
# stratum.yaml — place this in YOUR repo root
rules:
  max_function_lines: 50
  max_complexity: 10
  forbidden_imports:
    python: ["pickle", "shelve"]
    javascript: ["eval"]
  naming_conventions:
    python: snake_case

scoring_weights:
  complexity: 0.3
  duplication: 0.3
  violations: 0.2
  cluster_membership: 0.2
```

Commit and push this file to your repo. Stratum reads it on every PR review.

Full reference: [configuration.md](configuration.md)

---

## Step 5 — Connect a Repository

1. Open Stratum at `http://localhost:8000`
2. Go to **Connect Repository**
3. Enter your repo in `owner/repo` format (e.g. `adithyakrishhna/my-project`)
4. Click **Connect**, then select a branch and click **Analyze**

Stratum will walk your entire git history. Progress is visible on the **Pipeline Monitor** page in real time.

**Then install the GitHub App on that repository:**
- Go to your GitHub App's page → **Install App** → select the repository

From now on, every time a PR is opened or updated on that repo, Stratum will post a review automatically.

---

## Receiving Webhooks Locally (ngrok)

When running Stratum on your laptop, GitHub cannot reach `http://localhost:8000` to send webhook events. You need a tunnel that gives your localhost a public URL.

### Using ngrok

1. Install ngrok from [ngrok.com/download](https://ngrok.com/download) and create a free account.

2. Start a tunnel:
   ```bash
   ngrok http 8000
   ```
   ngrok will show a URL like `https://abc123def456.ngrok-free.app`.

3. Update your GitHub App's webhook URL:
   - Go to your GitHub App → **Edit** → change Webhook URL to:
   ```
   https://abc123def456.ngrok-free.app/webhooks/github/
   ```

4. You do not need to change `ALLOWED_HOSTS` in `.env` while `DEBUG=True` — Stratum accepts all hosts automatically in debug mode.

**Note:** Your ngrok URL changes every time you restart ngrok (free plan). Update the webhook URL in your GitHub App each time.

**For a stable URL:** Use ngrok's paid plan with a fixed domain, or use a Cloudflare Tunnel (free). Both work the same way — just use a permanent URL in the GitHub App webhook settings.

---

## Updating Stratum

```bash
docker compose pull
docker compose up -d
```

That's it. Your data (PostgreSQL volume) is preserved between updates.

---

## Local Development Setup (Without Full Docker)

For contributors developing Stratum itself — runs Django, Celery, and the embedding service directly on your machine for fast iteration.

### Start infrastructure only

```bash
docker compose -f docker-compose.dev.yml up -d
```

This starts only PostgreSQL (on port 5433) and Redis (on port 6380).

### Update .env for local dev

```env
DB_HOST=localhost
DB_PORT=5433
REDIS_URL=redis://localhost:6380/0
CELERY_BROKER_URL=redis://localhost:6380/0
CELERY_RESULT_BACKEND=redis://localhost:6380/1
EMBEDDING_SERVICE_URL=http://localhost:8001
# Local dev path for the .pem file:
GITHUB_APP_PRIVATE_KEY_PATH=C:\Users\you\stratum\secrets\stratum-app.private-key.pem
```

### Install dependencies

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
```

### Start all services (in separate terminals)

```bash
# Terminal 1 — Django
python manage.py runserver

# Terminal 2 — Celery (all queues for dev convenience)
celery -A config.celery worker --queues ingestion,parsing,embedding,intelligence,pr_priority --concurrency 2 --loglevel INFO

# Terminal 3 — Embedding microservice
cd ../embedding_service
pip install -r requirements.txt
uvicorn main:app --port 8001 --reload

# Terminal 4 — Frontend dev server (hot reload)
cd ../frontend
npm install
npm run dev
```

Frontend is at `http://localhost:5173`. It proxies `/api/` and `/ws/` to Django at port 8000.

---

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              Docker Compose              │
                         │                                          │
GitHub Webhook ──────────┤─► Django (port 8000)                    │
                         │       │                                  │
Browser Dashboard ───────┤─► Django (HTTP + WebSockets)            │
                         │       │                                  │
                         │       ▼                                  │
                         │   Redis (message broker)                 │
                         │       │                                  │
                         │       ├──► Celery: ingestion (1 worker)  │
                         │       ├──► Celery: parsing (4 workers)   │
                         │       ├──► Celery: embedding (2 workers) │
                         │       ├──► Celery: intelligence (1)      │
                         │       └──► Celery: pr_priority (2)       │
                         │                   │                      │
                         │                   ▼                      │
                         │   FastAPI embedding service (CodeBERT)   │
                         │                   │                      │
                         │                   ▼                      │
                         │   PostgreSQL 16 + pgvector               │
                         └─────────────────────────────────────────┘
```

The PR priority queue is dedicated and never shares workers with history ingestion — PR reviews always complete in under 60 seconds regardless of whether a large repo analysis is running.

---

## Troubleshooting

**"Embedding service not healthy" on first start**
The CodeBERT model downloads on first start (~400MB). Wait 2-3 minutes and check again:
```bash
docker compose logs embedding --tail 20
```

**Webhook events not arriving**
- Check ngrok is running and the URL in your GitHub App matches
- Check Django logs: `docker compose logs django --tail 50`
- Verify the webhook secret in `.env` matches what's set in your GitHub App

**"Analysis queued" but nothing happens**
- Check Celery workers are running: `docker compose ps`
- Check Celery logs: `docker compose logs celery-ingestion --tail 30`

**Private key error on startup**
- Confirm the `.pem` file is at `./secrets/stratum-app.private-key.pem`
- Confirm `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem` in `.env`

**Database connection error**
- Postgres might still be initializing. Wait 30 seconds and retry:
  ```bash
  docker compose restart django
  ```

**Port 8000 already in use**
Change the port in `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"   # host port 8080 → container port 8000
```
Then access Stratum at `http://localhost:8080`.
