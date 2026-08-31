import time

import requests
from django.core.management.base import BaseCommand

from tracker.models import Show
from tracker.services import (
    detect_changes,
    purge_old_events,
    purge_old_notifications,
    sync_episodes,
    sync_show,
)


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
            before = {
                "next_air_date": show.next_air_date,
                "number_of_seasons": show.number_of_seasons,
                "status": show.status,
            }
            old_date = show.next_air_date
            try:
                updated = sync_show(show.tmdb_id)
            except requests.RequestException as exc:
                failed += 1
                self.stderr.write(f"  {show.name}: {exc}")
                continue
            detect_changes(before, updated)

            for season in updated.seasons.all():
                is_current = (
                    season.season_number == updated.number_of_seasons
                    and updated.status in Show.RETURNING_STATUSES
                )
                needs_sync = (
                    season.episodes_synced_at is None and is_current
                ) or (
                    season.episodes_synced_at and season.has_unaired_episodes
                )
                if needs_sync:
                    try:
                        sync_episodes(season)
                    except requests.RequestException:
                        pass
            time.sleep(0.25)
        purged = purge_old_notifications()
        if purged:
            self.stdout.write(f"Purged {purged} read notification(s).")
        self.stdout.write(f"Done. {total - failed} synced, {failed} failed.")
        purged_events = purge_old_events()
        if purged_events:
            self.stdout.write(f"Purged {purged_events} old event(s).")