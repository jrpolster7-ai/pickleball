"""Django settings for the Pickleball Tournament App.

All configuration comes from environment variables (see .env.example),
so the app can move to any managed host without code changes.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .env import env_bool, env_list, env_str, load_dotenv, parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file if one exists. Real environment variables win.
load_dotenv(BASE_DIR / ".env")


# --- Core -----------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = env_str("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # Local development only. Never used when DEBUG is off.
        SECRET_KEY = "dev-only-insecure-key-change-me"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Render sets this to the site's onrender.com host name. Trust it automatically.
RENDER_EXTERNAL_HOSTNAME = env_str("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")


# The name shown in the header and browser tabs. Also hard-coded in templates/500.html.
SITE_NAME = "Dinkology"


# --- Applications ---------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # Serve static files with whitenoise in development too, so dev matches prod.
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    # Project apps
    "core",
    "accounts",
    "events",
    "scheduling",
    "scoring",
    "standings",
    "brackets",
    "chat",
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
                "core.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database -------------------------------------------------------------
# PostgreSQL in production via DATABASE_URL. SQLite locally when unset.

DATABASES = {
    "default": parse_database_url(
        env_str("DATABASE_URL", default="sqlite:///db.sqlite3"),
        BASE_DIR,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Auth -----------------------------------------------------------------
# Custom user model from the start (CLAUDE.md section 3). Fields come in Phase 1.

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Long-lived sessions so players stay signed in at the courts. ASSUMED: one year.
SESSION_COOKIE_AGE = int(env_str("SESSION_COOKIE_AGE", default=str(60 * 60 * 24 * 365)))


# --- Time and language ----------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Chicago"
USE_I18N = True
USE_TZ = True


# --- Static files ---------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}


# A friendly page instead of Django's "CSRF verification failed".
CSRF_FAILURE_VIEW = "core.views.csrf_failure"


# --- Logging ----------------------------------------------------------------
# Warnings and errors go to the console, which Render shows under Logs.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    # Replaces Django's default, which prints nothing when debug is off.
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}


# --- Security for production ----------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env_str("DJANGO_HSTS_SECONDS", default="0"))
    SECURE_CONTENT_TYPE_NOSNIFF = True
