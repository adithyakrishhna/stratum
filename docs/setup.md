# Setup Guide

Get Stratum running from zero. Estimated time: **15–20 minutes** (most of it is waiting for Docker to download images on first start).

---

## Before You Start

**You will create two separate things on GitHub.** Understanding this upfront prevents the most common confusion:

| What | Purpose | Where in GitHub |
|---|---|---|
| **GitHub App** | Receives webhook events when a PR is opened, reads your repo, posts review comments | Settings → Developer settings → GitHub Apps |
| **GitHub OAuth App** | Lets users log in to the Stratum dashboard with their GitHub account | Settings → Developer settings → OAuth Apps |

These are two different entries in GitHub. Both are required. You create them once and never touch them again.

---

## Prerequisites

Before starting, make sure you have:

- **Docker Desktop** — installed **and running** (look for the whale icon in your taskbar/menu bar)
- **Git** — `git --version` should return a version number
- **4 GB free RAM** — the CodeBERT embedding model is loaded into memory at startup
- A **GitHub account**

**Windows users:** Docker Desktop requires WSL 2. If Docker Desktop shows a WSL 2 error on first launch, follow the [WSL 2 installation guide](https://learn.microsoft.com/en-us/windows/wsl/install) (`wsl --install` in an administrator terminal), then restart and reopen Docker Desktop.

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
```

**Create the secrets folder** (this is where your GitHub App private key will go):

```bash
# Mac / Linux / PowerShell (Windows)
mkdir secrets

# Windows Command Prompt
mkdir secrets
```

Copy the environment file:

```bash
# Mac / Linux / PowerShell
cp .env.example .env

# Windows Command Prompt
copy .env.example .env
```

Leave `.env` open — you will fill in values during Steps 2 and 3.

---

## Step 2 — Create a GitHub App

This is used to receive PR webhook events and post review comments.

### 2a. Open the creation page

- **Personal account:** GitHub → profile photo → Settings → Developer settings → GitHub Apps → **New GitHub App**
- **Organization:** Organization page → Settings → Developer settings → GitHub Apps → **New GitHub App**

### 2b. Fill in the form

| Field | What to enter |
|---|---|
| GitHub App name | `Stratum` or any name you like |
| Homepage URL | `http://localhost:8000` |
| Webhook URL | `https://placeholder.example.com/api/webhooks/github/` — you will update this later in Step 7 |
| Webhook secret | Type any random string (e.g. `stratum-secret-2026`) — copy it, you will paste it into `.env` |

Leave all other fields at their defaults.

### 2c. Set permissions

Scroll to **Repository permissions** and set:

| Permission | Level |
|---|---|
| Contents | Read |
| Issues | Read |
| Metadata | Read |
| Pull requests | Read & Write |
| Webhooks | Read & Write |

### 2d. Subscribe to events

Check both: **Pull request** and **Push**

### 2e. Where can this app be installed?

Select **Only on this account** (for personal use) or **Any account** (for teams).

Click **Create GitHub App**.

### 2f. Get your App ID and private key

After creation, you land on the app settings page.

1. Find the **App ID** near the top — copy it.
2. Paste it into `.env`:
   ```
   GITHUB_APP_ID=123456
   ```
3. Paste the webhook secret you chose into `.env`:
   ```
   GITHUB_WEBHOOK_SECRET=stratum-secret-2026
   ```
4. Scroll down to **Private keys** → click **Generate a private key** → a `.pem` file downloads automatically.
5. Move that `.pem` file into the `secrets/` folder you created in Step 1 and rename it exactly:
   ```
   stratum/
     secrets/
       stratum-app.private-key.pem
   ```
   The filename must be exactly `stratum-app.private-key.pem`.

---

## Step 3 — Create a GitHub OAuth App

This is a **separate** app used only for dashboard login. Users log in to Stratum with their GitHub account — there is no separate username or password.

### 3a. Open the creation page

GitHub → profile photo → Settings → Developer settings → **OAuth Apps** → **New OAuth App**

### 3b. Fill in the form

| Field | What to enter |
|---|---|
| Application name | `Stratum` |
| Homepage URL | `http://localhost:8000` |
| **Authorization callback URL** | `http://localhost:8000/accounts/github/login/callback/` |

> ⚠️ **The Authorization callback URL is critical.** If this field has any other value, GitHub will block every login attempt with a "redirect_uri mismatch" error. Copy the URL above exactly.

Click **Register application**.

### 3c. Get your credentials

On the next page:

1. Copy the **Client ID** — paste into `.env`:
   ```
   GITHUB_OAUTH_CLIENT_ID=Ov23liXXXXXXXXXXX
   ```
2. Click **Generate a new client secret** — copy it immediately (it is only shown once) — paste into `.env`:
   ```
   GITHUB_OAUTH_CLIENT_SECRET=def456...
   ```

---

## Step 4 — Verify Your .env

At this point your `.env` should have these five values filled in:

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem
GITHUB_WEBHOOK_SECRET=stratum-secret-2026
GITHUB_OAUTH_CLIENT_ID=Ov23liXXXXXXXXXXX
GITHUB_OAUTH_CLIENT_SECRET=def456...
```

Everything else in `.env` is pre-configured for Docker Compose and does not need to change.

**Optional — AI fix suggestions:** Stratum can generate plain-English "how to fix this" suggestions on critical and high severity PR findings, powered by Groq's free API. Add your key to enable it:
```
GROQ_API_KEY=gsk_...
```
Get a free key at [console.groq.com](https://console.groq.com). Without it, all findings still post — just without the suggested fix text.

---

## Step 5 — Start Stratum

```bash
docker compose up -d
```

**What happens on first run:** Docker builds all images before starting. This takes **5–10 minutes** depending on your internet speed. CodeBERT (~400MB) also downloads inside the embedding container. This is a one-time process — subsequent starts take under 30 seconds.

After the command returns, check that all services started:

```bash
docker compose ps
```

You should see these services and their status:

| Service | Expected status |
|---|---|
| `stratum-postgres-1` | `Up (healthy)` |
| `stratum-redis-1` | `Up (healthy)` |
| `stratum-django-1` | `Up (healthy)` |
| `stratum-embedding-1` | `Up (healthy)` or `starting` |
| `stratum-celery-ingestion-1` | `Up` |
| `stratum-celery-parsing-1` | `Up` |
| `stratum-celery-embedding-1` | `Up` |
| `stratum-celery-intelligence-1` | `Up` |
| `stratum-celery-pr-priority-1` | `Up` |

The embedding service shows `starting` for 2–3 minutes while CodeBERT loads — this is normal. Wait until it shows `Up (healthy)` before opening the dashboard.

If any service shows `Exit` or `Restarting`, see the [Troubleshooting](#troubleshooting) section below.

---

## Step 6 — Log In

Open **http://localhost:8000** in your browser.

You will see a login page. Click **Login with GitHub** and authorize Stratum.

If you land on a GitHub error page saying "redirect_uri not associated" or "The redirect_uri ... is not associated with this application" — the Authorization callback URL in your OAuth App (Step 3b) is wrong. Go back to GitHub → OAuth Apps → your app → edit it and set it to exactly `http://localhost:8000/accounts/github/login/callback/`.

---

## Step 7 — Add stratum.yaml to Your Repository

`stratum.yaml` goes in the **root of the repository you want Stratum to review** — not inside the Stratum folder. It tells Stratum which rules to enforce on PRs.

```yaml
# stratum.yaml — place this in YOUR repo root, not in Stratum
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

## Step 8 — Connect a Repository

### 8a. Install the GitHub App on your repository

1. Go to [github.com/settings/apps](https://github.com/settings/apps) and click your app
2. Click **Install App** in the left sidebar
3. Click **Install** next to your account
4. Select the repository you want Stratum to review → click **Install**

### 8b. Connect the repository in Stratum

1. Open Stratum at `http://localhost:8000`
2. Click **Connect Repository**
3. Enter your repo in `owner/repo` format (e.g. `yourname/my-project`)
4. Click **Connect**, select the default branch, and click **Analyze**

Stratum walks your entire git history on first run. Progress is live on the **Pipeline Monitor** page. For a large repo (1,000+ commits) this takes 30–90 minutes. Subsequent runs are incremental and much faster.

---

## Step 9 — Set Up Webhook Tunnel (Required for PR Reviews)

GitHub webhooks need a publicly reachable URL. `http://localhost:8000` is only on your machine — GitHub cannot reach it.

**You must have a tunnel running before opening a PR.** Without it, GitHub fires the event but Stratum never receives it, and no review comment appears.

### Option A — ngrok (quickest for local development)

1. Download and install from [ngrok.com/download](https://ngrok.com/download). Create a free account.

2. In a new terminal, start the tunnel and keep it running (closing this terminal stops webhooks):
   ```bash
   ngrok http 8000
   ```

3. Copy the `https://...ngrok-free.app` URL from the output.

4. Go to [github.com/settings/apps](https://github.com/settings/apps) → your app → **Edit** → update the **Webhook URL** to:
   ```
   https://abc123def456.ngrok-free.app/api/webhooks/github/
   ```
   Include the trailing slash. Click **Save changes**.

5. **Every time you restart ngrok the URL changes.** Repeat steps 2–4 each session.

**Missed a webhook?** GitHub will not retry automatically. To replay: GitHub App → **Advanced** tab → **Recent Deliveries** → find the failed delivery → **Redeliver**.

### Option B — Cloudflare Tunnel (free, no account needed)

```bash
cloudflared tunnel --url http://localhost:8000
```

Same URL-changes-on-restart limitation as ngrok free.

### Option C — VPS Deployment (permanent, recommended for teams)

The only option where you set the webhook URL once and never update it. See [Deploying to a VPS](#deploying-to-a-vps) below.

---

## Step 10 — Open a PR and Receive Your First Review

With the tunnel running:

1. Open a pull request on the connected repository
2. Wait 30–60 seconds
3. Stratum posts an automated review comment on the PR with a health score and inline findings

If no comment appears within 2 minutes, check [Troubleshooting](#troubleshooting) below.

---

## Deploying to a VPS (Permanent Setup)

The only option where you set the webhook URL once and never change it. Recommended for teams.

**Recommended providers:** DigitalOcean ($6/mo), Hetzner CX22 (€4/mo), any Linux VPS with 2 GB+ RAM.

### 1. Install Docker on the server

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

### 2. Point a domain at your server

In your DNS settings, add an A record:
```
Type: A  |  Name: stratum  |  Value: <your server IP>  |  TTL: 300
```

### 3. Install Caddy (handles HTTPS automatically)

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

### 4. Clone, configure, and start

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
mkdir secrets
cp .env.example .env
# Edit .env:
#   ALLOWED_HOSTS=stratum.yourdomain.com
#   DEBUG=False
# Copy your .pem file to secrets/stratum-app.private-key.pem
docker compose up -d
```

### 5. Update GitHub App settings

| Field | Value |
|---|---|
| Homepage URL | `https://stratum.yourdomain.com` |
| Webhook URL | `https://stratum.yourdomain.com/api/webhooks/github/` |
| OAuth App Callback URL | `https://stratum.yourdomain.com/accounts/github/login/callback/` |

All containers restart automatically if the server reboots.

---

## Admin Panel

The Django admin at `/admin/` is for database inspection. You do not need it for normal use.

**There are two separate login systems:**

| Login | Used for |
|---|---|
| GitHub OAuth (Login with GitHub button) | The Stratum dashboard — this is how all users log in |
| Django superuser | The `/admin/` panel only |

To create an admin account:

```bash
docker compose exec django python manage.py createsuperuser
```

To promote your GitHub login to also access `/admin/` (so you don't need two accounts):

```bash
# Find your GitHub username in the DB
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
[print(u.id, u.username) for u in get_user_model().objects.all()]
"

# Promote it (replace adithyakrishhna with your actual username from above)
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username='adithyakrishhna')
u.is_staff = True; u.is_superuser = True; u.save()
print('Done')
"
```

---

## Updating Stratum

```bash
docker compose pull && docker compose up -d
```

Your database and analysis history are preserved between updates.

---

## Known Limitations

| Feature | Status |
|---|---|
| PR Review (security, rules, duplicate detection) | ✅ Fully working |
| PR Review Center dashboard | ✅ Fully working |
| Pipeline Monitor | ✅ Fully working |
| Repository Overview | ✅ Working — populates after first analysis completes |
| Debt Timeline | ✅ Working — requires a completed full analysis |
| Semantic Cluster Map | ⚠️ Partially implemented — clustering runs but the interactive timeline slider is not yet built |
| Velocity Heatmap | ⚠️ Partially implemented — scores are calculated but the file-tree visualization is not yet built |
| Blame Report | ⚠️ Partially implemented — ranking is calculated but CSV export is not yet built |
| PR Debt Impact Prediction | 🚧 Not yet implemented — planned for a future release |
| Multi-repo support | ✅ You can connect multiple repositories |
| First analysis of large repos (1,000+ commits) | ⏳ Takes 30–90 minutes — subsequent runs are incremental |

---

## Local Development (Contributors Only)

> **Regular users stop at Step 9.** This section is for developers working on Stratum itself.

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
# Windows absolute path example:
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

## Troubleshooting

### Docker won't start / "Docker Desktop is not running"

Open Docker Desktop from your applications. Wait for the whale icon to stop animating (this means Docker is ready). On Windows, if you see a WSL 2 error: open an administrator terminal and run `wsl --install`, then restart your computer.

### `docker compose up -d` fails immediately

```bash
docker compose logs
```

Common causes:
- **Port 8000 already in use** — something else is running on port 8000. Change it in `docker-compose.yml`: `"8080:8000"` then access Stratum at `http://localhost:8080`
- **`.env` file missing** — run `cp .env.example .env` first
- **`secrets/` folder missing** — run `mkdir secrets` and add your `.pem` file

### First `docker compose up -d` is slow

Expected. Docker is building images and downloading CodeBERT (~400MB). Wait 5–10 minutes. Run `docker compose ps` to monitor progress.

### Embedding service stuck on "starting"

```bash
docker compose logs embedding --tail 30
```

The CodeBERT model is downloading (~400MB). Normal on first start. Wait 2–3 minutes.

### "Login with GitHub" gives a redirect_uri error

The Authorization callback URL in your GitHub OAuth App is wrong. Go to GitHub → Developer settings → OAuth Apps → your app → set **Authorization callback URL** to exactly:
```
http://localhost:8000/accounts/github/login/callback/
```
No trailing spaces. No `http://` vs `https://` mismatch.

### No PR review comment after opening a PR

1. Is the webhook tunnel running? (`ngrok http 8000` in a terminal)
2. Does the Webhook URL in your GitHub App match the current ngrok URL?
3. Check if Django received the event:
   ```bash
   docker compose logs django --tail 50
   ```
   Look for a line with `POST /api/webhooks/github/`. If it's not there, the webhook never arrived.
4. If no POST — go to GitHub App → **Advanced** tab → **Recent Deliveries** → find the failed event → **Redeliver**
5. If a POST appeared but no review followed:
   ```bash
   docker compose logs celery-pr-priority --tail 30
   ```

### "Private key" error on startup

- The file must be at `./secrets/stratum-app.private-key.pem` (exact filename)
- `.env` must have `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem` (this is the path inside the container, not your machine)

### manage.py command fails with "connection refused"

You are running it from your local terminal, which has no database connection. Always run manage.py through Docker:
```bash
docker compose exec django python manage.py <command>
```

### "Analysis queued" but nothing happens

```bash
docker compose ps                                    # all workers should show Up
docker compose logs celery-ingestion --tail 30      # check for errors
```

### /admin/ redirects me to the dashboard

You are logged in via GitHub OAuth (a regular non-staff account). See [Admin Panel](#admin-panel) to promote your GitHub account to staff access.

### I ran `docker compose down -v` and lost all data

The `-v` flag deletes all database volumes permanently — there is no recovery. Re-connect your repositories and run Analyze again. Stratum will re-walk the git history and rebuild all embeddings.
