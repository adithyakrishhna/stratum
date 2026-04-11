# Configuration Reference

Stratum has two configuration files:

- **`stratum.yaml`** — lives in *your repository* (the one being reviewed). Controls what rules Stratum applies to that repo.
- **`.env`** — lives in the *Stratum installation directory*. Controls how Stratum connects to services.

---

## stratum.yaml — Your Repository's Rules

Place this file in the **root of the repository you want Stratum to review** — not inside Stratum's own directory. Copy from `stratum.yaml.example` as a starting point.

All settings are optional. Stratum uses sensible defaults when any setting is omitted.

```yaml
# stratum.yaml
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

semantic:
  similarity_threshold: 0.85
  cross_language_clustering: false

skip:
  directories:
    - vendor/
    - node_modules/
    - migrations/
  file_patterns:
    - "*.min.js"
    - "*.generated.*"
  max_line_length_threshold: 500
```

### rules.max_function_lines

Maximum number of lines a function or method may have.

Functions longer than this are flagged at **medium** severity.

```yaml
max_function_lines: 50   # default
```

| Value | Recommended for |
|---|---|
| 30 | Strict codebases, highly readable functions |
| 50 | Most teams (default) |
| 80 | Legacy codebases transitioning to smaller functions |

### rules.max_complexity

Maximum cyclomatic complexity for any function or method.

- Within the limit → no flag
- Between 1× and 2× the limit → **medium** severity
- Above 2× the limit → **high** severity

```yaml
max_complexity: 10   # default
```

Cyclomatic complexity is roughly the number of branches in a function (each `if`, `elif`, `for`, `while`, `and`, `or` adds 1, starting from 1). A function with complexity 25 has 24 branches and is extremely hard to test or reason about.

### rules.forbidden_imports

Packages that must not be imported. Specified per language.

```yaml
forbidden_imports:
  python:
    - pickle       # insecure deserialization
    - shelve       # backed by pickle
    - marshal      # insecure deserialization
  javascript:
    - eval
  typescript:
    - eval
  java:
    - sun.misc.Unsafe
```

Stratum matches both exact package names and sub-packages:
- `pickle` matches `import pickle` and `from pickle import loads`
- `com.example` matches `import com.example.Thing`

Violations are reported at **high** severity.

### rules.naming_conventions

Enforce naming style for function and variable names, by language.

```yaml
naming_conventions:
  python: snake_case       # my_function, my_variable
  java: camelCase          # myFunction, myVariable
  go: camelCase
  ruby: snake_case
```

Options: `snake_case`, `camelCase`, `PascalCase`, `SCREAMING_SNAKE_CASE`

### scoring_weights

Controls how each component contributes to a file's debt score. All four values must sum to 1.0.

```yaml
scoring_weights:
  complexity: 0.3        # cyclomatic complexity contribution
  duplication: 0.3       # semantic duplicate logic contribution
  violations: 0.2        # rule violation contribution
  cluster_membership: 0.2  # participation in growing patterns
```

Adjust these to match what your team cares about most. If security and rules compliance are top priority, increase `violations`. If duplicate logic is your biggest problem, increase `duplication`.

### semantic.similarity_threshold

The cosine similarity threshold (0.0–1.0) above which two functions are considered potential duplicates.

```yaml
semantic:
  similarity_threshold: 0.85   # default
```

Higher values = stricter, fewer (but more confident) matches.
Lower values = more matches, higher chance of false positives.

The recommended range is 0.80–0.95. Going below 0.80 typically produces noise.

### semantic.cross_language_clustering

Whether to cluster functions across different programming languages.

```yaml
cross_language_clustering: false   # default
```

When `false` (default): a Python function will only be compared against other Python functions.

When `true` (experimental): Python functions may match JavaScript or Java functions if they implement the same logic. Accuracy is lower because language differences affect the embedding. Enable only if you have a polyglot codebase and want cross-language duplicate detection.

### skip

Files and directories Stratum will not analyze.

```yaml
skip:
  directories:
    - vendor/
    - node_modules/
    - migrations/       # auto-generated Django migrations
    - .git/
    - dist/
    - build/
    - __pycache__/
  file_patterns:
    - "*.min.js"          # minified JavaScript
    - "*.pb.go"           # protobuf generated files
    - "*.generated.*"     # any generated file
  max_line_length_threshold: 500   # lines longer than this → minified/generated → skip
```

---

## .env — Stratum's Environment Variables

Full reference for every variable in `.env`. Copy from `.env.example` and fill in your values.

### Django

| Variable | Default | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | (required) | Django's cryptographic signing key. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DEBUG` | `True` | `True` for development (allows all hosts, shows full errors). Set to `False` in production. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames Django will serve. Only used when `DEBUG=False`. Add your ngrok/domain here for production. |

### Database

| Variable | Default | Description |
|---|---|---|
| `DB_NAME` | `stratum` | PostgreSQL database name |
| `DB_USER` | `stratum` | PostgreSQL username |
| `DB_PASSWORD` | `postgres123` | PostgreSQL password. Change in production. |
| `DB_HOST` | `postgres` | Docker: use service name `postgres`. Local dev: use `localhost`. |
| `DB_PORT` | `5432` | Docker: `5432`. Local dev with `docker-compose.dev.yml`: `5433`. |

### Redis

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection URL. Docker: `redis://redis:6379`. Local dev: `redis://localhost:6380`. |
| `CELERY_BROKER_URL` | same as `REDIS_URL` | Celery task broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/1` | Celery result storage (separate DB index from broker) |

### GitHub App

| Variable | Default | Description |
|---|---|---|
| `GITHUB_APP_ID` | (required) | Numeric ID shown on your GitHub App's settings page |
| `GITHUB_APP_PRIVATE_KEY_PATH` | `/secrets/stratum-app.private-key.pem` | Path to the `.pem` file. Docker: leave as-is, place file at `./secrets/`. Local dev: use absolute host path. |
| `GITHUB_WEBHOOK_SECRET` | (required) | The secret you set in your GitHub App. Used to verify webhook signatures. |

### GitHub OAuth (dashboard login)

| Variable | Default | Description |
|---|---|---|
| `GITHUB_OAUTH_CLIENT_ID` | (required) | From your GitHub OAuth App |
| `GITHUB_OAUTH_CLIENT_SECRET` | (required) | From your GitHub OAuth App |

### Optional: Personal Access Token

| Variable | Default | Description |
|---|---|---|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | (empty) | PAT for cloning private repos without a GitHub App installation. Scopes required: `repo`. |

### Groq API

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | (empty) | Free API key from [console.groq.com](https://console.groq.com). Used to generate fix suggestions on PR comments. |
| `ENABLE_LLM_SUGGESTIONS` | `true` | Set to `false` to disable all Groq calls. PR reviews still work — findings are posted without suggested fixes. |

### Embedding Service

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_SERVICE_URL` | `http://embedding:8001` | Docker: `http://embedding:8001`. Local dev: `http://localhost:8001`. |

### Storage

| Variable | Default | Description |
|---|---|---|
| `STORE_RAW_CODE` | `false` | Whether to persist raw source code in the database. `false` = only embeddings and metadata stored. `true` = raw code also stored, enables more accurate duplicate similarity scoring. |
