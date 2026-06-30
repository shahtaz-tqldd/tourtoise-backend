from datetime import timedelta

from app.settings.env import BASE_DIR, PROJECT_DIR, env, env_bool, env_int, env_list

APP_ENV = env("APP_ENV", "dev")
SECRET_KEY = env("APP_SECRET", "django-insecure-change-me")
DEBUG = APP_ENV == "dev" or env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
CORS_ALLOW_CREDENTIALS = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOG_LEVEL = env("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "%(levelname)s %(asctime)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "console",
        },
    },
    "loggers": {
        "app": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "trips": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=24),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# EMAILS
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@tourtoise.local")

# STATIC AND MEDIA
STATIC_URL = "/static/"
STATIC_ROOT = PROJECT_DIR / "staticfiles"
STATICFILES_DIRS = [PROJECT_DIR / "static"] if (PROJECT_DIR / "static").exists() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = PROJECT_DIR / "media"

# CELERY
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = env("CELERY_TIMEZONE", "UTC")
CELERY_RESULT_EXTENDED = True
CELERY_IMPORTS = ("accounts.tasks", "destinations.tasks")

# ADK
ADK_DB_URL = env("ADK_DB_URL")
VECTOR_DB_URL = env("VECTOR_DB_URL")

# GEMINI EMBEDDINGS
GEMINI_API_KEY = env("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = env("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
GEMINI_EMBEDDING_DIMENSIONS = env_int("GEMINI_EMBEDDING_DIMENSIONS", 1536)


# CLOUDINARY
CLOUDINARY_CLOUD_NAME = env("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = env("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = env("CLOUDINARY_API_SECRET", "")
CLOUDINARY_FOLDER = env("CLOUDINARY_FOLDER", "tourtoise")

# FRONTEND URL
USER_FRONTEND_URL = env("USER_FRONTEND_URL", "http://localhost:5173")
ADMIN_FRONTEND_URL = env("ADMIN_FRONTEND_URL", "http://localhost:5173/admin")
PASSWORD_RESET_PATH = env("PASSWORD_RESET_PATH", "/reset-password")

# FIREBASE AUTH
FIREBASE_VERIFY_ID_TOKEN = env_bool("FIREBASE_VERIFY_ID_TOKEN", False)
FIREBASE_SERVICE_ACCOUNT_JSON = env("FIREBASE_SERVICE_ACCOUNT_JSON", "")

# STRIPE
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CURRENCY = env("STRIPE_CURRENCY", "usd")
STRIPE_CHECKOUT_SUCCESS_URL = f"{USER_FRONTEND_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
STRIPE_CHECKOUT_CANCEL_URL = f"{USER_FRONTEND_URL}/checkout/cancel"

# LANGUAGE AND TIME
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
