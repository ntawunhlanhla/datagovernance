"""CLI: python manage.py generate_dataset --size small --domain school"""
from django.core.management.base import BaseCommand

from governance.models import GenerationRun
from governance.tasks import generate_data_product


class Command(BaseCommand):
    help = "Trigger a data-product generation run (small / medium / large)."

    def add_arguments(self, parser):
        parser.add_argument("--size", choices=["small", "medium", "large"], default="small")
        parser.add_argument("--domain", default="school")
        parser.add_argument("--sync", action="store_true", help="Run synchronously (don't dispatch to Celery)")

    def handle(self, *args, **opts):
        run = GenerationRun.objects.create(domain=opts["domain"], size=opts["size"], status="pending")
        self.stdout.write(self.style.SUCCESS(f"Created run #{run.id} ({opts['size']} / {opts['domain']})"))
        if opts["sync"]:
            generate_data_product(run.id)
            self.stdout.write(self.style.SUCCESS(f"Run #{run.id} completed synchronously."))
        else:
            generate_data_product.delay(run.id)
            self.stdout.write(self.style.SUCCESS(f"Dispatched run #{run.id} to Celery (queue: generator)."))
