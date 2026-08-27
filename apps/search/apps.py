from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.search"
    label = "search"

    def ready(self):
        from . import signals  # noqa: F401  (registers post_save/post_delete handlers)
