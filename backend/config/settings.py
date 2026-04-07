import os
import sys
from pathlib import Path

import structlog
from dotenv import load_dotenv

# Load .env from project root (one level above backend/)
load_dotenv(Path(__file__).resolve().parent.parent.parent / '.env')

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-insecure-change-me-in-production-!!!!')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
]

THIRD_PARTY_APPS = [
    'corsheaders',
    'rest_framework',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.github',
    'channels',
]

LOCAL_APPS = [
    'apps.repositories',
    'apps.ingestion',
    'apps.parsing',
    'apps.security',
    'apps.rules',
    'apps.clustering',
    'apps.debt',
    'apps.blame',
    'apps.pr_review',
    'apps.dashboard',
    'apps.webhooks',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',   # must be before CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ---------------------------------------------------------------------------
# Database — PostgreSQL 16 with pgvector
# ---------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'stratum'),
        'USER': os.environ.get('DB_USER', 'stratum'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres123'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'CONN_MAX_AGE': 60,  # Optimization 10: connection pooling
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# ---------------------------------------------------------------------------
# Django Channels — WebSockets
# ---------------------------------------------------------------------------

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [REDIS_URL],
            'capacity': 1500,
            'expiry': 10,
        },
    },
}

# ---------------------------------------------------------------------------
# Celery — distributed async task queue
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', os.environ.get('REDIS_URL', 'redis://localhost:6379/1'))
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 3600       # 1 hour hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55 min soft — triggers SoftTimeLimitExceeded
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # fair distribution, no task hoarding

# Dedicated queues per pipeline stage (Optimization 7)
from kombu import Queue, Exchange

_default_exchange = Exchange('default', type='direct')

CELERY_TASK_QUEUES = (
    Queue('ingestion',    _default_exchange, routing_key='ingestion'),
    Queue('parsing',      _default_exchange, routing_key='parsing'),
    Queue('embedding',    _default_exchange, routing_key='embedding'),
    Queue('intelligence', _default_exchange, routing_key='intelligence'),
    Queue('pr_priority',  _default_exchange, routing_key='pr_priority'),
    Queue('default',      _default_exchange, routing_key='default'),
)
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_DEFAULT_EXCHANGE = 'default'
CELERY_TASK_DEFAULT_ROUTING_KEY = 'default'

# Embedding queue rate limit: 10 tasks/sec (Principle 3)
CELERY_TASK_ANNOTATIONS = {
    'apps.ingestion.*':   {'queue': 'ingestion'},
    'apps.parsing.*':     {'queue': 'parsing'},
    'apps.pr_review.*':   {'queue': 'pr_priority'},
    'apps.clustering.*':  {'queue': 'intelligence'},
    'apps.debt.*':        {'queue': 'intelligence'},
    'apps.blame.*':       {'queue': 'intelligence'},
}

# ---------------------------------------------------------------------------
# Cache — Redis
# ---------------------------------------------------------------------------

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'max_entries': 10000,
        },
    }
}

# ---------------------------------------------------------------------------
# Authentication — Django Allauth + GitHub OAuth
# ---------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = 1

ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = 'http'       # http for local dev; override to https in prod
ACCOUNT_USERNAME_REQUIRED = False            # log in via GitHub only — no username/password
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_AUTHENTICATION_METHOD = 'email'      # consistent with no-username setup

SOCIALACCOUNT_LOGIN_ON_GET = True            # allow GET-based GitHub redirect (OAuth flow)
SOCIALACCOUNT_AUTO_SIGNUP = True             # auto-create user on first GitHub login
SOCIALACCOUNT_STORE_TOKENS = False           # don't persist OAuth tokens — not needed yet

SOCIALACCOUNT_PROVIDERS = {
    'github': {
        'APP': {
            'client_id': os.environ.get('GITHUB_OAUTH_CLIENT_ID', ''),
            'secret': os.environ.get('GITHUB_OAUTH_CLIENT_SECRET', ''),
            'key': '',
        },
        'SCOPE': ['repo', 'read:user', 'user:email'],
        'AUTH_PARAMS': {'allow_signup': 'true'},
    }
}

LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# ---------------------------------------------------------------------------
# Static and media files
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# ---------------------------------------------------------------------------
# CORS — Vite dev server (5173) → Django (8000)
# In production, React is served by Django itself so CORS is not needed.
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True   # required to pass Django session cookie
CORS_URLS_REGEX = r'^/api/.*$'  # only API routes need CORS headers

# ---------------------------------------------------------------------------
# Structured logging — structlog
# ---------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': structlog.stdlib.ProcessorFormatter,
            'processor': structlog.processors.JSONRenderer(),
            'foreign_pre_chain': [
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt='iso'),
            ],
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt='iso'),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

# ---------------------------------------------------------------------------
# GitHub App credentials
# ---------------------------------------------------------------------------

GITHUB_APP_ID = os.environ.get('GITHUB_APP_ID', '')
GITHUB_APP_PRIVATE_KEY_PATH = os.environ.get('GITHUB_APP_PRIVATE_KEY_PATH', '')
GITHUB_WEBHOOK_SECRET = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
GITHUB_OAUTH_CLIENT_ID = os.environ.get('GITHUB_OAUTH_CLIENT_ID', '')
GITHUB_OAUTH_CLIENT_SECRET = os.environ.get('GITHUB_OAUTH_CLIENT_SECRET', '')

# ---------------------------------------------------------------------------
# Groq API (LLM fix suggestions)
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
ENABLE_LLM_SUGGESTIONS = os.environ.get('ENABLE_LLM_SUGGESTIONS', 'true').lower() == 'true'

# ---------------------------------------------------------------------------
# Embedding microservice
# ---------------------------------------------------------------------------

EMBEDDING_SERVICE_URL = os.environ.get('EMBEDDING_SERVICE_URL', 'http://localhost:8001')

# ---------------------------------------------------------------------------
# Pipeline & analysis constants
# ---------------------------------------------------------------------------

STORE_RAW_CODE = os.environ.get('STORE_RAW_CODE', 'false').lower() == 'true'
MAX_CONCURRENT_ANALYSES_PER_USER = 2
EMBEDDING_BATCH_SIZE = 64        # Optimization 1
COMMIT_BATCH_SIZE = 50           # batch git history walks
DB_BULK_CREATE_BATCH_SIZE = 500  # Optimization 3
AST_PARSER_WORKERS = 4           # Optimization 2

# Local directory where repos are cloned for analysis
# In prod this should be a persistent volume mount.
REPO_CLONE_BASE_DIR = os.environ.get(
    'REPO_CLONE_BASE_DIR',
    str(BASE_DIR.parent / 'repo_clones'),
)

# ---------------------------------------------------------------------------
# Miscellaneous Django settings
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Required environment variable validation (Principle 7 — Security)
# Raises at startup if missing in production; logs a warning in development.
# ---------------------------------------------------------------------------

_REQUIRED_PROD_VARS = [
    'DJANGO_SECRET_KEY',
    'GITHUB_APP_ID',
    'GITHUB_WEBHOOK_SECRET',
    'GITHUB_OAUTH_CLIENT_ID',
    'GITHUB_OAUTH_CLIENT_SECRET',
    'DB_PASSWORD',
]

if not DEBUG:
    _missing = [v for v in _REQUIRED_PROD_VARS if not os.environ.get(v)]
    if _missing:
        raise RuntimeError(
            f"Missing required environment variables for production: {', '.join(_missing)}"
        )
