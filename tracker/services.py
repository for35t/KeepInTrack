from datetime import timedelta

from django.utils import timezone

from . import tmdb
from .models import Season, Show

STALE_AFTER = timedelta(hours=12)


def _date_or_none(value):
    return value or None


def sync_show(tmdb_id):
    data = tmdb.get_tv(tmdb_id)
    next_ep = data.get("next_episode_to_air") or {}

    show, _ = Show.objects.update_or_create(
        tmdb_id=data["id"],
        defaults={
            "name": data["name"],
            "overview": data.get("overview") or "",
            "poster_path": data.get("poster_path") or "",
            "backdrop_path": data.get("backdrop_path") or "",
            "first_air_date": _date_or_none(data.get("first_air_date")),
            "last_air_date": _date_or_none(data.get("last_air_date")),
            "status": data.get("status") or "",
            "number_of_seasons": data.get("number_of_seasons") or 0,
            "networks": [n["name"] for n in data.get("networks") or []],
            "genres": [g["name"] for g in data.get("genres") or []],
            "next_air_date": _date_or_none(next_ep.get("air_date")),
            "next_season_number": next_ep.get("season_number"),
            "next_episode_number": next_ep.get("episode_number"),
        },
    )

    for season_data in data.get("seasons") or []:
        Season.objects.update_or_create(
            show=show,
            season_number=season_data["season_number"],
            defaults={
                "name": season_data.get("name") or "",
                "overview": season_data.get("overview") or "",
                "poster_path": season_data.get("poster_path") or "",
                "air_date": _date_or_none(season_data.get("air_date")),
                "episode_count": season_data.get("episode_count") or 0,
            },
        )

    return show


def get_or_sync_show(tmdb_id):
    show = Show.objects.filter(tmdb_id=tmdb_id).first()
    if show is None or timezone.now() - show.synced_at > STALE_AFTER:
        show = sync_show(tmdb_id)
    return show