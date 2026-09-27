"""
Django settings for HealthOPS Connect.

Everything environment-specific is read from environment variables (or a
local `.env` file). See `.env.example` for the full list.
"""

import os
from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", ".onrender.com", ".vercel.app"]),
    CSRF_TRUSTED_ORIGINS=(list, ["https://*.onrender.com", "https://*.vercel.app"]),
)
# Local development reads .env; hosted environments inject real env vars.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me" if DEBUG else environ.Env.NOTSET)
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Public base URL, used for absolute links in emails and on printed prescriptions.
SITE_URL = env("SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
SITE_NAME = "HealthOPS Connect"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "accounts",
    "clinic",
    "appointments",
    "records",
    "operations",
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

ROOT_URLCONF = "health_ops_connect.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "health_ops_connect.wsgi.application"

# --- Database -------------------------------------------------------------
# Production uses Neon serverless Postgres via DATABASE_URL (use the *pooled*
# connection string, i.e. the host containing "-pooler"). Without it we fall
# back to a local SQLite file so tests and quick hacking work offline.
# On serverless hosts (Vercel) set DB_CONN_MAX_AGE=0 so idle instances don't
# hold connections; Neon's pooler makes reconnecting cheap.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=env.int("DB_CONN_MAX_AGE", default=60),
        conn_health_checks=True,
    )
}

# --- Auth -----------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.EmailOrUsernameBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Email ----------------------------------------------------------------
# Falls back to printing emails to the console when no SMTP host is set.
EMAIL_HOST = env("EMAIL_HOST", default="")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="HealthOPS Connect <no-reply@healthops.local>")

# --- i18n / time ------------------------------------------------------------
LANGUAGE_CODE = "en-us"
# Clinic hours and slots are interpreted in this zone.
TIME_ZONE = env("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# --- Static & media -------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
# Serve uploaded media from Django itself (local development). In production
# media goes to object storage, configured below.
SERVE_MEDIA = env.bool("SERVE_MEDIA", default=True)

# --- Object storage (Neon Object Storage, S3-compatible) ---------------------
# Set AWS_STORAGE_BUCKET_NAME to store uploads (doctor photos, avatars) in a
# bucket instead of the local disk. The bucket is private: files are served
# through short-lived signed URLs. Neon requires path-style addressing + SigV4.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
if AWS_STORAGE_BUCKET_NAME:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_STORAGE_BUCKET_NAME,
            "endpoint_url": env("AWS_ENDPOINT_URL_S3"),
            "region_name": env("AWS_REGION", default="us-east-1"),
            "access_key": env("AWS_ACCESS_KEY_ID"),
            "secret_key": env("AWS_SECRET_ACCESS_KEY"),
            "addressing_style": "path",
            "signature_version": "s3v4",
            "location": env("AWS_LOCATION", default="media"),
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": env.int("AWS_QUERYSTRING_EXPIRE", default=3600),
            "file_overwrite": False,
            "object_parameters": {"CacheControl": "private, max-age=3600"},
        },
    }
    SERVE_MEDIA = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- App settings ---------------------------------------------------------
# Read directly: django-environ would treat a leading "$" as a variable reference.
CURRENCY_SYMBOL = os.environ.get("CURRENCY_SYMBOL", "$")
BOOKING_WINDOW_DAYS = env.int("BOOKING_WINDOW_DAYS", default=14)
# How early before the slot a patient may check in digitally.
CHECKIN_OPENS_MINUTES = env.int("CHECKIN_OPENS_MINUTES", default=120)
# Video visits run on Jitsi Meet unless the doctor configured their own link.
VIDEO_BASE_URL = env("VIDEO_BASE_URL", default="https://meet.jit.si")

# --- Security (production) --------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_AGE = 60 * 60 * 12

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
