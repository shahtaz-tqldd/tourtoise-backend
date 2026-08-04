from django.apps import AppConfig


class DestinationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'destinations'

    def ready(self):
        import destinations.signals  # noqa: F401
