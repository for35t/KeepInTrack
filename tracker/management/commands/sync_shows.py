import time

import requests
from django.core.management.base import BaseCommand

from tracker.models import Show
from tracker.services import sync_show


class Command(BaseCommand):
    help = "Re-sync followed shows from TMDB."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Sync every show, not just followed ones.",
        )

    def handle(self, *args, **options):
        shows = Show.objects.all()
        if not options["all"]:
            shows = shows.filter(followers__isnull=False).distinct()

        total = shows.count()
        if not total:
            self.stdout.write("Nothing to sync.")
            return

        self.stdout.write(f"Syncing {total} show(s)…")
        failed = 0

        for show in shows:
            old_date = show.next_air_date
            try:
                updated = sync_show(show.tmdb_id)
            except requests.RequestException as exc:
                failed += 1
                self.stderr.write(f"  {show.name}: {exc}")
                continue

            if updated.next_air_date != old_date:
                self.stdout.write(self.style.SUCCESS(
                    f"  {updated.name}: {old_date or 'TBA'} → {updated.next_air_date or 'TBA'}"
                ))
            time.sleep(0.25)

        self.stdout.write(f"Done. {total - failed} synced, {failed} failed.")