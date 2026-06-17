from django.apps import AppConfig


class GovernanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "governance"
    verbose_name = "Metadata Governance"

    def ready(self):
        from . import signals  # noqa: F401
