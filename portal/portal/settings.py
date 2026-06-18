"""
Django settings for portal project.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [
    "http://localhost",
    "http://localhost:80",
    "http://127.0.0.1",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "django_celery_beat",
    "django_celery_results",
    "django_extensions",

    "governance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "portal.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "governance" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "portal.wsgi.application"
ASGI_APPLICATION = "portal.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "metadata"),
        "USER": os.environ.get("POSTGRES_USER", "metadata"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "metadata"),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "governance" / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ===== Celery =====
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "django-db")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60 * 4  # 4h for 100M-row generation
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 60 * 3
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ROUTES = {
    "governance.tasks.generate_data_product": {"queue": "generator"},
    "governance.tasks.generate_excel_definition": {"queue": "pipeline"},
    "governance.tasks.ingest_data_product_excel": {"queue": "pipeline"},
    "governance.tasks.sync_alation": {"queue": "pipeline"},
}

# ===== Service config =====
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_PUBLIC_ENDPOINT = os.environ.get("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"
MINIO_BUCKETS = {
    "raw": os.environ.get("MINIO_BUCKET_RAW", "raw"),
    "curated": os.environ.get("MINIO_BUCKET_CURATED", "curated"),
    "contracts": os.environ.get("MINIO_BUCKET_CONTRACTS", "contracts"),
    "excel": os.environ.get("MINIO_BUCKET_EXCEL", "excel-uploads"),
}

SCHEMA_REGISTRY_URL = os.environ.get("SCHEMA_REGISTRY_URL", "http://schema-registry:8081")
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")

MARQUEZ_URL = os.environ.get("MARQUEZ_URL", "http://marquez:5000")
MARQUEZ_NAMESPACE = os.environ.get("MARQUEZ_NAMESPACE", "metadata-governance")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

# ===== Catalog provider =====
# Options: "openmetadata" (default — runs in Docker), "alation", "mock"
CATALOG_PROVIDER = os.environ.get("CATALOG_PROVIDER", "openmetadata")

OPENMETADATA = {
    "BASE_URL": os.environ.get("OPENMETADATA_BASE_URL", "http://openmetadata-server:8585"),
    "PUBLIC_URL": os.environ.get("OPENMETADATA_PUBLIC_URL", "http://localhost:8585"),
    "JWT_TOKEN": os.environ.get("OPENMETADATA_JWT_TOKEN", ""),
    "SERVICE_NAME": os.environ.get("OPENMETADATA_SERVICE_NAME", "MetadataGovernancePlatform"),
    "ADMIN_EMAIL": os.environ.get("OPENMETADATA_ADMIN_EMAIL", "admin@open-metadata.org"),
    "ADMIN_PASSWORD": os.environ.get("OPENMETADATA_ADMIN_PASSWORD", "admin"),
}

ALATION = {
    "MODE": os.environ.get("ALATION_MODE", "mock"),
    "BASE_URL": os.environ.get("ALATION_BASE_URL", ""),
    "REFRESH_TOKEN": os.environ.get("ALATION_REFRESH_TOKEN", ""),
    "USER_ID": os.environ.get("ALATION_USER_ID", ""),
    "DATA_SOURCE_ID": os.environ.get("ALATION_DATA_SOURCE_ID", ""),
    "FOLDER_ID": os.environ.get("ALATION_FOLDER_ID", ""),
    "MOCK_DIR": "/app/alation_sync",
}

AWS = {
    "REGION": os.environ.get("AWS_REGION", "us-east-1"),
    "ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", ""),
    "SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
    "S3_BUCKET": os.environ.get("AWS_S3_BUCKET", ""),
    "ATHENA_OUTPUT": os.environ.get("AWS_ATHENA_OUTPUT", ""),
    "GLUE_DATABASE": os.environ.get("AWS_GLUE_DATABASE", ""),
}

# Pluggable source connectors (extensible)
CONNECTORS = {
    "minio": "governance.connectors.minio_connector.MinIOConnector",
    "s3": "governance.connectors.s3_connector.S3Connector",
    "athena": "governance.connectors.athena_connector.AthenaConnector",
    "glue": "governance.connectors.glue_connector.GlueConnector",
    "marquez": "governance.connectors.marquez_connector.MarquezConnector",
}

# Dataset size presets
DATASET_SIZES = {
    "small": 10_000,
    "medium": 1_000_000,
    "large": 100_000_000,
}

# Files
FILE_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024  # 50 MB

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "governance": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
