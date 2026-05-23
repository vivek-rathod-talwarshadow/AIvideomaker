from pathlib import Path
import os

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_or_default(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-dev-key")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "studio",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / os.getenv("MEDIA_ROOT", "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "True").lower() == "true"
SCHEDULER_POLL_SECONDS = int(os.getenv("SCHEDULER_POLL_SECONDS", "120"))
MAX_VIDEOS_PER_DAY = int(os.getenv("MAX_VIDEOS_PER_DAY", "2"))
JOB_LOCK_TTL_SECONDS = int(os.getenv("JOB_LOCK_TTL_SECONDS", "7200"))
FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
PEXELS_API_KEY = env_or_default("PEXELS_API_KEY", "")
PIXABAY_API_KEY = env_or_default("PIXABAY_API_KEY", "")
GEMINI_API_KEY = env_or_default("GEMINI_API_KEY", "")
AUTOMATION_WEBHOOK_TOKEN = os.getenv("AUTOMATION_WEBHOOK_TOKEN", SECRET_KEY)
YOUTUBE_CLIENT_ID = env_or_default("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = env_or_default("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = env_or_default("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_API_KEY = env_or_default("YOUTUBE_API_KEY", "")
YOUTUBE_PRIVACY_STATUS = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
YOUTUBE_MAX_UPLOADS_PER_DAY = int(os.getenv("YOUTUBE_MAX_UPLOADS_PER_DAY", "2"))
INSTAGRAM_USERNAME = env_or_default("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = env_or_default("INSTAGRAM_PASSWORD", "")
PINTEREST_ACCESS_TOKEN = env_or_default("PINTEREST_ACCESS_TOKEN", "")
PINTEREST_BOARD_ID = env_or_default("PINTEREST_BOARD_ID", "")
ENABLE_YOUTUBE_UPLOAD = os.getenv("ENABLE_YOUTUBE_UPLOAD", "True").lower() == "true"
ENABLE_INSTAGRAM_UPLOAD = os.getenv("ENABLE_INSTAGRAM_UPLOAD", "False").lower() == "true"
ENABLE_PINTEREST_UPLOAD = os.getenv("ENABLE_PINTEREST_UPLOAD", "False").lower() == "true"
CHANNEL_BRAND_NAME = os.getenv("CHANNEL_BRAND_NAME", "DarkBrainScroll")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "en-US-AnaNeural")
AUTOMATION_RETRY_LIMIT = int(os.getenv("AUTOMATION_RETRY_LIMIT", "3"))
AUTOMATION_RETRY_DELAY_SECONDS = int(os.getenv("AUTOMATION_RETRY_DELAY_SECONDS", "60"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
