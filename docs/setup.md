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
- **Docker / production with a real domain:** `https://yourdomain.com/api/webhooks/github/`
- **Local development (your laptop):** You need a tunnel — see [Receiving Webhooks Locally](#receiving-webhooks-locally-ngrok). For now, put a placeholder like `https://placeholder.example.com/api/webhooks/github/` and update it after ngrok is running.

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

This single command starts everything: PostgreSQL, Redis, Django, the FastAPI embedding microservice, and 5 Celery workers.

> **You do not need to run `python manage.py runserver` or any other command.**  
> Docker Compose manages all services. `manage.py` is only used by contributors developing Stratum itself — see [Local Development](#local-development-setup-without-full-docker) at the bottom of this guide.

First run takes a few minutes as Docker pulls images and builds containers. Check that everything started:

```bash
docker compose ps
```

All services should show `Up` or `Up (healthy)`. The embedding service takes the longest to become healthy — it downloads the CodeBERT model (~400MB) on first start.

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

## Receiving Webhooks Locally

GitHub webhooks are sent to the URL you configure in your GitHub App. When Stratum runs on your laptop, that URL must be reachable from the internet — `http://localhost:8000` is not.

**The key point:** The webhook URL in your GitHub App is one global setting. It is not per-developer. Webhooks go to whichever machine is behind that URL. If that machine is offline or the tunnel is not running, GitHub fires the webhook but nothing receives it — and GitHub does not retry automatically. You must redeliver missed events manually from the GitHub App's Advanced tab.

| Setup | Recommended approach |
|---|---|
| **Solo developer, local machine** | ngrok free — URL changes each restart, update webhook URL each session |
| **Solo developer, wants permanent URL** | Deploy to a free server (Railway, Render) — set once, always on |
| **Team** | Deploy to a shared server — one URL, everyone uses the same instance |

---

### Option A — ngrok (free, simplest to start)

The quickest way to get webhooks working locally. The URL changes every time you restart ngrok, so you need to update the GitHub App webhook URL each session.

1. Install ngrok from [ngrok.com/download](https://ngrok.com/download) and create a free account.

2. Start a tunnel:
   ```bash
   ngrok http 8000
   ```
   ngrok prints a URL like `https://abc123def456.ngrok-free.app`.

3. Update your GitHub App's webhook URL:
   - Go to **GitHub App → Edit → Webhook URL** and paste the ngrok URL:
   ```
   https://abc123def456.ngrok-free.app/api/webhooks/github/
   ```

4. That's it. Repeat step 2–3 each time you restart ngrok.

> You do not need to change `ALLOWED_HOSTS` in `.env` while `DEBUG=True` — Stratum accepts all hosts in debug mode.

**Missed a webhook?** If you opened a PR while ngrok was not running, GitHub will not automatically resend it. To trigger a review: go to **GitHub App → Advanced → Recent Deliveries**, find the missed event, and click **Redeliver**.

---

### Option B — Cloudflare Tunnel (free, URL changes on restart)

An alternative to ngrok. The quick tunnel URL also changes between restarts.

1. Install `cloudflared`: [developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads)

2. Start a tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   It prints a URL like `https://random-name.trycloudflare.com`.

3. Update your GitHub App webhook URL to that URL.

Same limitation as ngrok free: update the webhook URL each session.

---

### Option C — Deploy to a VPS (permanent, recommended for teams)

The only option where you set the webhook URL once and never touch it again. Stratum runs 24/7 on a server — PR reviews trigger automatically without anyone's laptop needing to be open.

**Recommended providers:** DigitalOcean ($6/mo Droplet), Hetzner CX22 (€4/mo), Linode, Vultr — any Linux VPS with 2GB+ RAM and Docker support works.

#### C.1 — Provision a server

Create a fresh Ubuntu 22.04 or 24.04 server. SSH in as root or a sudo user.

#### C.2 — Install Docker and Docker Compose

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
docker --version        # verify
docker compose version  # verify
```

#### C.3 — Point a domain at the server

In your domain registrar's DNS settings, add an **A record**:

```
Type: A
Name: stratum        (or @ for root domain)
Value: <your server IP>
TTL: 300
```

After DNS propagates (usually 1–5 minutes), `ping stratum.yourdomain.com` should reach your server. You need a real domain for HTTPS (required by GitHub for webhooks).

#### C.4 — Install Caddy (automatic HTTPS)

Caddy automatically obtains and renews SSL certificates from Let's Encrypt — no manual certificate management needed.

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

Create `/etc/caddy/Caddyfile`:

```
stratum.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Start Caddy:

```bash
sudo systemctl enable caddy
sudo systemctl start caddy
```

Caddy will immediately obtain an SSL certificate. Your server is now reachable at `https://stratum.yourdomain.com`.

#### C.5 — Clone and configure Stratum

```bash
git clone https://github.com/adithyakrishhna/stratum
cd stratum
cp .env.example .env
nano .env   # or vim .env
```

Fill in the same credentials as you would locally — GitHub App ID, private key path, webhook secret, OAuth client ID/secret. Set `ALLOWED_HOSTS` to your domain:

```env
ALLOWED_HOSTS=stratum.yourdomain.com
DEBUG=false
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/stratum-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-random-secret
GITHUB_OAUTH_CLIENT_ID=abc123
GITHUB_OAUTH_CLIENT_SECRET=def456
```

Copy your GitHub App private key to the server:

```bash
# From your local machine:
scp secrets/stratum-app.private-key.pem user@your-server-ip:~/stratum/secrets/
```

#### C.6 — Update your GitHub App URLs

In your GitHub App settings, update:

| Field | Value |
|---|---|
| Homepage URL | `https://stratum.yourdomain.com` |
| Webhook URL | `https://stratum.yourdomain.com/api/webhooks/github/` |
| Callback URL (OAuth) | `https://stratum.yourdomain.com/accounts/github/login/callback/` |

#### C.7 — Start Stratum

```bash
docker compose up -d
docker compose ps    # all services should show Up or Up (healthy)
```

Open `https://stratum.yourdomain.com` — log in with GitHub and connect your first repository.

#### C.8 — Auto-restart on server reboot

Docker Compose services already have `restart: unless-stopped` — they start automatically when the server reboots. Caddy is managed by systemd and also starts automatically.

#### What happens if the server goes down?

GitHub retries a failed webhook delivery **3 times over 5 minutes**. If the server was down longer than that, GitHub stops retrying. To recover missed events after the server comes back up:

1. Go to **GitHub App → Advanced → Recent Deliveries**
2. Find events that show a failed status (red ✗)
3. Click **Redeliver** on each one

There is no limit on how many events you can redeliver — you can redeliver events from up to 3 days ago.

#### Scaling for larger teams

The default `docker-compose.yml` works well for teams of up to ~20 developers with moderate PR volume. For higher load:

- Increase `--concurrency` on the `celery-parsing` worker (it's CPU-bound — set it to the number of server CPUs)
- Increase `--concurrency` on `celery-pr-priority` if reviews are queuing
- Add more RAM if the embedding service becomes the bottleneck (CodeBERT uses ~800MB)

Stagger analysis of very large repositories — run one at a time to avoid saturating embedding workers.

---

## Updating Stratum

```bash
docker compose pull
docker compose up -d
```

That's it. Your data (PostgreSQL volume) is preserved between updates.

---

## Admin Panel

Stratum's Django admin panel is available at `/admin/`. It is intended for database inspection and user management — regular Stratum usage only requires the dashboard at `/dashboard/`.

### Two separate login methods

Stratum has two ways to log in:

| Method | Used for |
|---|---|
| **GitHub OAuth** (`/accounts/github/login/`) | Normal dashboard login — what every user does |
| **Django superuser** (`/admin/` login form) | Admin panel access only |

These are **two separate accounts** in Django's database. Logging into `/admin/` with superuser credentials does not affect your GitHub OAuth session, and vice versa.

If you log into `/admin/` and then visit `/dashboard/`, Django's session cookie keeps you signed in as the superuser — you will appear logged in on the dashboard too. Sign out from the dashboard to switch back to your GitHub account.

### Create a superuser (first-time setup)

Always run management commands through Docker — running them directly from your local terminal connects to `localhost:5433` (dev database port) instead of the container:

```bash
docker compose exec django python manage.py createsuperuser
```

### Grant your GitHub account admin access

By default, your GitHub OAuth account is a regular (non-staff) user. Visiting `/admin/` while logged in via GitHub redirects you back to the dashboard.

To grant your GitHub account full admin access — so you can use either login method for `/admin/`:

**Step 1** — List all users to find your GitHub username:

```bash
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
for u in User.objects.all().order_by('date_joined'):
    print(u.id, u.username, u.email, '| staff:', u.is_staff, '| super:', u.is_superuser)
"
```

**Step 2** — Promote your GitHub account (replace `your_github_username`):

```bash
docker compose exec django python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
u = User.objects.get(username='your_github_username')
u.is_staff = True
u.is_superuser = True
u.save()
print('Done —', u.username, 'is now superuser')
"
```

After this, logging in via GitHub OAuth grants full `/admin/` access.

---

## Local Development Setup (Without Full Docker)

> **This section is for contributors developing Stratum itself.**  
> If you are a regular user, stop at Step 3 (`docker compose up -d`). Do not run `manage.py` — it will fail unless `docker-compose.dev.yml` is also running and your `.env` is switched to local dev settings.

For contributors — runs Django, Celery, and the embedding service directly on your machine for fast iteration.

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
