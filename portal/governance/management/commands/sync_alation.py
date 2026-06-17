"""CLI: python manage.py sync_alation — re-push failed / draft products."""
from django.core.management.base import BaseCommand
from governance.tasks import sync_alation


class Command(BaseCommand):
    help = "Re-publish failed or draft data products to Alation."

    def handle(self, *args, **opts):
        sync_alation()
        self.stdout.write(self.style.SUCCESS("Alation sync completed."))
