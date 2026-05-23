from django.core.management.base import BaseCommand

from studio.services.pipeline import process_due_work


class Command(BaseCommand):
    help = "Process one automation cycle."

    def handle(self, *args, **options):
        result = process_due_work()
        self.stdout.write(self.style.SUCCESS(str(result)))
