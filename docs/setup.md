# Setup Guide

Get Stratum running from zero. The GitHub App creation is a one-time ~10 minute process. After that, starting Stratum is a single command.

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

You will fill in `.env` after the next step.

---

## Step 2 — Create Your GitHub App

Stratum uses a GitHub App to receive webhook events (PR opened, updated) and post review comments. This is a one-time setup.

### 2a. Create the App

- Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
- For an organization: **Org Settings → Developer settings → GitHub Apps → New GitHub App**

### 2b. Fill in the details

| Field | Value |
|---|---|
| GitHub App name | `Stratum Local` (or any name) |
| Homepage URL | `http://localhost:8000` |
| Webhook URL | If running locally, put `https://placeholder.example.com/api/webhooks/github/` for now — you **must** update this with your real tunnel URL before PR reviews will work (see [Receiving Webhooks](#receiving-webhooks)) |
| Webhook secret | A random string of your choice — paste it into `.env` as `GITHUB_WEBHOOK_SECRET` |

### 2c. Permissions

Under **Repository permissions**:

| Permission | Access |
|---|---|
| Contents | Read |
| Issues | Read |
| Metadata | Read |
| Pull requests | Read & Write |
| Webhooks | Read & Write |

### 2d. Subscribe to events

Check: **Pull request** and **Push**

### 2e. Finalize

- **Where can this GitHub App be installed?** → `Only on this account` (personal) or `Any account` (teams)
- Click **Create GitHub App**

### 2f. Get your credentials

1. Copy the **App ID** → paste into `.env` as `GITHUB_APP_ID`
2. Scroll to **Private keys** → click **Generate a private key**
3. Move the downloaded `.pem` file to the `secrets/` folder inside Stratum and rename it:

```
stratum/
  secrets/
    stratum-app.private-key.pem
```

### 2g. Create a GitHub OAuth App (for dashboard login)

Stratum's dashboard login uses GitHub OAuth — **there is no username/password for the dashboard**. Users log in with their GitHub account.

- Go to **GitHub → Settings → Developer settings → OAuth Apps → New OAuth App**
- Homepage URL: `http://localhost:8000`
- Authorization callback URL: `http://localhost:8000/accounts/github/login/callback/`
- Copy **Client ID** and **Client Secret** into `.env`

### 2h. Your .env should now have

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-random-secret-here
GITHUB_OAUTH_CLIENT_ID=abc123
GITHUB_OAUTH_CLIENT_SECRET=def456
```

Everything else in `.env` can stay at its default value to start.

> **Fix suggestions on PR comments:** If you want Stratum to suggest how to fix each issue (powered by Groq), add a free API key from [console.groq.com](https://console.groq.com) as `GROQ_API_KEY=...` in `.env`. Without it, findings are still posted — just without the suggested fix text.

---

## Step 3 — Start Stratum

```bash
docker compose up -d
```

This starts everything: PostgreSQL, Redis, Django, the FastAPI embedding microservice, and 5 Celery workers.

Check all services are up:

```bash
docker compose ps
```

All services should show `Up` or `Up (healthy)`. The embedding service takes the longest — it downloads the CodeBERT model (~400MB) on first start. Wait 2–3 minutes if it shows `starting`.

Open **http://localhost:8000** — you will see a login page. Click **Login with GitHub** and authorize Stratum.

> **Important:** All `manage.py` commands must be run through Docker, not from your local terminal. Your local terminal does not have a database connection. Use:
> ```bash
> docker compose exec django python manage.py <command>
> ```

> **Data warning:** `docker compose down` is safe — your data is preserved. `docker compose down -v` permanently deletes all database data (repositories, embeddings, PR history). There is no undo.

---

## Step 4 — Add stratum.yaml to Your Repository

`stratum.yaml` goes in the **root of the repository you want to review** — not inside Stratum. It tells Stratum which rules to apply.

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
3. Enter your repo in `owner/repo` format (e.g. `yourname/my-project`)
4. Click **Connect**, select a branch, and click **Analyze**

Stratum will walk your entire git history. Progress is visible on the **Pipeline Monitor** page in real time. For a large repo (1000+ commits), this can take 30–60 minutes on first run. Subsequent runs are incremental and much faster.

**Install the GitHub App on that repository:**
- Go to your GitHub App page → **Install App** → select the repository

---

## Step 6 — Receive Your First PR Review

**Before you open a PR, your webhook tunnel must be running.** Without it, GitHub fires the event but Stratum never receives it, and no review appears.

See [Receiving Webhooks](#receiving-webhooks) below for setup options. The quickest is ngrok:

```bash
ngrok http 8000
# Copy the https://... URL and paste it into your GitHub App → Webhook URL as:
# https://abc123.ngrok-free.app/api/webhooks/github/
```

Once the tunnel is set up:

1. Open a pull request on the connected repository
2. Wait ~30–60 seconds
3. Stratum will post a review comment directly on the GitHub PR with a health score and inline findings

If no comment appears within 2 minutes, check the troubleshooting section below.

---

## Receiving Webhooks

GitHub webhooks need a publicly reachable URL to deliver events. `http://localhost:8000` is not reachable from the internet.

| Setup | Approach |
|---|---|
| **Solo, local laptop** | ngrok free — URL changes each restart, update webhook URL each session |
| **Solo, permanent URL** | Deploy to a VPS or cloud server — set once, never touch again |
| **Team** | Deploy to a shared server — one URL, everyone uses the same Stratum instance |

### Option A — ngrok (quickest)

1. Install from [ngrok.com/download](https://ngrok.com/download) and create a free account.

2. Start a tunnel (keep this terminal open — closing it stops webhooks):
   ```bash
   ngrok http 8000
   ```

3. Copy the `https://...ngrok-free.app` URL. Update your **GitHub App → Edit → Webhook URL**:
   ```
   https://abc123def456.ngrok-free.app/api/webhooks/github/
   ```

4. Repeat steps 2–3 each time you restart ngrok (the URL changes every time on the free tier).

**Missed a webhook?** If you opened a PR while ngrok wasn't running, the event was never delivered. GitHub will not retry. To replay it: **GitHub App → Advanced → Recent Deliveries** → find the failed event → **Redeliver**.

---

### Option B — Cloudflare Tunnel (free alternative to ngrok)

```bash
cloudflared tunnel --url http://localhost:8000
```

Same URL-changes-on-restart limitation as ngrok free.

---

### Option C — Deploy to a VPS (permanent, recommended for teams)

The only option where you set the webhook URL once and never update it again. Stratum runs 24/7.

**Recommended providers:** DigitalOcean ($6/mo), Hetzner CX22 (€4/mo), any Linux VPS with 2GB+ RAM.

#### C.1 — Install Docker on the server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

#### C.2 — Point a domain at your server

Add an A record in your DNS:
```
Type: A  |  Name: stratum  |  Value: <server IP>  |  TTL: 300
```

#### C.3 — Install Caddy (handles HTTPS automatically)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

Create `/etc/caddy/Caddyfile`:
```
stratum.yourdomain.com {
    reverse_proxy localhost:8000
}
```

```bash
sudo systemctl enable caddy && sudo systemctl start caddy
```

#### C.4 — Clone, configure, and start

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
# Edit .env — set ALLOWED_HOSTS=stratum.yourdomain.com and DEBUG=false
# Copy your .pem file to secrets/stratum-app.private-key.pem
docker compose up -d
```

#### C.5 — Update GitHub App URLs

| Field | Value |
|---|---|
| Homepage URL | `https://stratum.yourdomain.com` |
| Webhook URL | `https://stratum.yourdomain.com/api/webhooks/github/` |
| OAuth Callback URL | `https://stratum.yourdomain.com/accounts/github/login/callback/` |

All services restart automatically if the server reboots (`restart: unless-stopped` is set on every container).

**If the server goes down:** GitHub retries webhook delivery 3 times over 5 minutes. For events missed beyond that: **GitHub App → Advanced → Recent Deliveries → Redeliver**.

---

## Admin Panel

The Django admin panel at `/admin/` is for database inspection and user management. You do not need it for normal Stratum usage.

**Two login methods exist and they are separate accounts:**

| Method | Used for |
|---|---|
| **GitHub OAuth** | Dashboard login — this is what all users do |
| **Django superuser** | `/admin/` panel only |

If you need admin access, create a superuser:
```bash
docker compose exec django python manage.py createsuperuser
```

**To use your GitHub account for `/admin/` as well** (optional convenience):
```bash
# First, find your username
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
[print(u.id, u.username, '| staff:', u.is_staff) for u in get_user_model().objects.all()]
"

# Then promote it (replace your_github_username)
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username='your_github_username')
u.is_staff = True; u.is_superuser = True; u.save()
print('Done')
"
```

---

## Updating Stratum

```bash
docker compose pull && docker compose up -d
```

Your database is preserved between updates.

---

## Known Limitations

Before using Stratum, be aware of what is and isn't available:

| Feature | Status |
|---|---|
| PR Review (security, rules, duplicate detection) | ✅ Fully working |
| PR Review Center dashboard | ✅ Fully working |
| Pipeline Monitor | ✅ Fully working |
| Repository Overview | ✅ Working — health score and file list populate after first analysis |
| Debt Timeline | ✅ Working — requires a completed full analysis to show history |
| Semantic Cluster Map | ⚠️ Partially implemented — clustering runs but the interactive timeline slider is not yet built |
| Velocity Heatmap | ⚠️ Partially implemented — scores are calculated but the file-tree visualization is not yet built |
| Blame Report | ⚠️ Partially implemented — ranking is calculated but the CSV export is not yet built |
| PR Debt Impact Prediction | 🚧 Not yet implemented — the warning "this PR accelerates Cluster #8 by 35%" is planned for a future release |
| Multi-repo support | ✅ You can connect multiple repositories |
| First analysis of large repos (1000+ commits) | ⏳ Can take 30–90 minutes — subsequent runs are incremental |
| pgvector limit | ~1 million embedded functions per Stratum instance — sufficient for most codebases |
| Groq fix suggestions limit | 14,400 suggestions/day on the free tier |
| GitHub API limit | 5,000 requests/hour per GitHub App installation |

---

## Local Development (Contributors Only)

> **If you are a regular user, stop at Step 3.** The section below is for developers contributing to Stratum itself.

Run Django, Celery, and the embedding service directly on your machine for fast iteration.

### Start infrastructure only

```bash
docker compose -f docker-compose.dev.yml up -d
```

This starts only PostgreSQL (port 5433) and Redis (port 6380).

### Update .env for local dev

```env
DB_HOST=localhost
DB_PORT=5433
REDIS_URL=redis://localhost:6380/0
CELERY_BROKER_URL=redis://localhost:6380/0
CELERY_RESULT_BACKEND=redis://localhost:6380/1
EMBEDDING_SERVICE_URL=http://localhost:8001
GITHUB_APP_PRIVATE_KEY_PATH=C:\Users\you\stratum\secrets\stratum-app.private-key.pem
```

### Start all services (separate terminals)

```bash
# Terminal 1 — Django
cd backend && python manage.py migrate && python manage.py runserver

# Terminal 2 — Celery
celery -A config.celery worker --queues ingestion,parsing,embedding,intelligence,pr_priority --concurrency 2 --loglevel INFO

# Terminal 3 — Embedding microservice
cd embedding_service && uvicorn main:app --port 8001 --reload

# Terminal 4 — Frontend (hot reload)
cd frontend && npm install && npm run dev
```

Frontend dev server is at `http://localhost:5173`. It proxies `/api/` and `/ws/` to Django at port 8000.

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

The PR priority queue never shares workers with history ingestion — PR reviews complete in under 60 seconds even during a large analysis.

---

## Troubleshooting

**No PR review comment appeared after opening a PR**
1. Is your webhook tunnel running? (`ngrok http 8000`)
2. Does the URL in your GitHub App → Webhook URL match the current ngrok URL?
3. Check Django received the event: `docker compose logs django --tail 50` — look for a `POST /api/webhooks/github/`
4. If no POST appears, the event never arrived. Go to **GitHub App → Advanced → Recent Deliveries** and redeliver it.
5. If a POST appears but no review followed: `docker compose logs celery-pr-priority --tail 30`

**"Embedding service not healthy" on first start**
CodeBERT downloads on first start (~400MB). Wait 2–3 minutes:
```bash
docker compose logs embedding --tail 20
```

**"Analysis queued" but nothing happens**
```bash
docker compose ps                                      # all workers should be Up
docker compose logs celery-ingestion --tail 30        # check for errors
```

**manage.py command fails with "connection refused"**
You are running it from your local terminal. Run it through Docker instead:
```bash
docker compose exec django python manage.py <command>
```

**Private key error on startup**
- File must be at `./secrets/stratum-app.private-key.pem`
- `.env` must have `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem`

**Visiting /admin/ redirects me to the dashboard**
You are logged in via GitHub OAuth, which is a regular (non-staff) user. See [Admin Panel](#admin-panel) to grant your GitHub account staff access.

**I ran `docker compose down -v` and lost all my data**
The `-v` flag deletes named volumes (database, Redis, repo clones). Data cannot be recovered. Re-connect your repositories and run analysis again — Stratum will re-walk the git history and rebuild all embeddings.

**Port 8000 already in use**
Change the host port in `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"
```
Then access Stratum at `http://localhost:8080`. Update your GitHub App URLs accordingly.
