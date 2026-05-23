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


def csv_env(name: str, default: str = "") -> list[str]:
    raw = env_or_default(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

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
CONTENT_GENERATION_PROVIDER = env_or_default("CONTENT_GENERATION_PROVIDER", "auto")
CONTENT_GENERATION_MODEL = env_or_default("CONTENT_GENERATION_MODEL", "")
OPENAI_API_KEY = env_or_default("OPENAI_API_KEY", "")
OPENAI_BASE_URL = env_or_default("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_CONTENT_MODEL = env_or_default("OPENAI_CONTENT_MODEL", "chat-latest")
OPENROUTER_API_KEY = env_or_default("OPENROUTER_API_KEY", env_or_default("OPROUTER_API_KEY", ""))
OPENROUTER_BASE_URL = env_or_default("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_CONTENT_MODELS = csv_env(
    "OPENROUTER_CONTENT_MODELS",
    "x-ai/grok-beta,openai/gpt-4o-mini",
)
GROQ_API_KEY = env_or_default("GROQ_API_KEY", "")
GROQ_BASE_URL = env_or_default("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_CONTENT_MODELS = csv_env(
    "GROQ_CONTENT_MODELS",
    "llama-3.3-70b-versatile,llama-3.1-8b-instant",
)
HUGGINGFACE_TOKEN = env_or_default("HUGGINGFACE_TOKEN", "")
HUGGINGFACE_BASE_URL = env_or_default("HUGGINGFACE_BASE_URL", "https://api-inference.huggingface.co/v1")
HUGGINGFACE_CONTENT_MODELS = csv_env(
    "HUGGINGFACE_CONTENT_MODELS",
    "microsoft/Phi-3-mini-4k-instruct",
)
CONTENT_GENERATION_ALLOW_FALLBACKS = os.getenv("CONTENT_GENERATION_ALLOW_FALLBACKS", "True").lower() == "true"
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
EDGE_TTS_MAX_RETRIES = int(os.getenv("EDGE_TTS_MAX_RETRIES", "3"))
EDGE_TTS_RETRY_DELAY_SECONDS = float(os.getenv("EDGE_TTS_RETRY_DELAY_SECONDS", "2"))
AUTOMATION_RETRY_LIMIT = int(os.getenv("AUTOMATION_RETRY_LIMIT", "3"))
AUTOMATION_RETRY_DELAY_SECONDS = int(os.getenv("AUTOMATION_RETRY_DELAY_SECONDS", "60"))
YOUTUBE_MIN_UPLOAD_GAP_MINUTES = int(os.getenv("YOUTUBE_MIN_UPLOAD_GAP_MINUTES", "90"))
DEFAULT_VIDEO_WIDTH = int(os.getenv("DEFAULT_VIDEO_WIDTH", "720"))
DEFAULT_VIDEO_HEIGHT = int(os.getenv("DEFAULT_VIDEO_HEIGHT", "1280"))
DEFAULT_RENDER_FPS = int(os.getenv("DEFAULT_RENDER_FPS", "18"))
MAX_SCENES_PER_VIDEO = int(os.getenv("MAX_SCENES_PER_VIDEO", "5"))
USE_STOCK_MEDIA = os.getenv("USE_STOCK_MEDIA", "False").lower() == "true"
DASHBOARD_STATUS_ACTIVE_POLL_MS = int(os.getenv("DASHBOARD_STATUS_ACTIVE_POLL_MS", "8000"))
DASHBOARD_STATUS_IDLE_POLL_MS = int(os.getenv("DASHBOARD_STATUS_IDLE_POLL_MS", "30000"))
DASHBOARD_STATUS_HIDDEN_POLL_MS = int(os.getenv("DASHBOARD_STATUS_HIDDEN_POLL_MS", "120000"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
