from django.apps import AppConfig
import sys


class StudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "studio"
    verbose_name = "Viral Studio"

    def ready(self) -> None:
        blocked_commands = {"collectstatic", "makemigrations", "migrate", "shell", "test"}
        if any(command in sys.argv for command in blocked_commands):
            return

        from .scheduler import boot_scheduler

        boot_scheduler()
