from app.settings.env import env, env_bool, env_int

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "tourtoise_db"),
        "USER": env("DB_USER", "tourtoise_db_owner"),
        "PASSWORD": env("DB_PASSWORD", "tourtoise_db_password"),
        "HOST": env("DB_HOST", "postgres"),
        "PORT": env_int("DB_PORT", 5432),
        "OPTIONS": {"sslmode": "require"} if env_bool("DB_SSL_REQUIRE", False) else {},
    }
}
