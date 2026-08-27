"""Create the factory tables from schema.sql if they aren't there yet.

`migrate` normally does this — the initial migration runs schema.sql. But a
database whose migration record says "applied" while the tables are missing
(anything previously deployed with --fake) would be skipped silently. This runs
after migrate and fills that gap, so a deploy never needs a hand on it.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Apply schema.sql if the factory tables do not exist yet."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.machines')")
            if cursor.fetchone()[0] is not None:
                self.stdout.write("Tables already present.")
                return

        schema = Path(settings.BASE_DIR) / "schema.sql"
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(schema.read_text())
        self.stdout.write(self.style.SUCCESS(f"Applied {schema.name}."))
