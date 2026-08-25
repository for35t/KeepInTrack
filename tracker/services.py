from datetime import timedelta
import requests
from django.utils import timezone
from django.core.cache import cache

from . import tmdb
from .models import Season, Show
from .models import Episode, Season, Show

EPISODE_STALE_AFTER = timedelta(hours=12)
CAST_LIMIT = 15
STALE_AFTER = timedelta(hours=12)
GENRE_CACHE_KEY = "tmdb_tv_genres"
GENRE_CACHE_SECONDS = 60 * 60 * 24 * 7


def get_genre_map():
    genres = cache.get(GENRE_CACHE_KEY)
    if genres is None:
        try:
            data = tmdb.get_tv_genres()
        except requests.RequestException:
            return {}
        genres = {g["id"]: g["name"] for g in data.get("genres") or []}
        cache.set(GENRE_CACHE_KEY, genres, GENRE_CACHE_SECONDS)
    return genres

def get_genre_name_to_id():
    return {name: gid for gid, name in get_genre_map().items()}

def _extract_cast(data):
    credits = data.get("aggregate_credits") or {}
    people = []
    for person in (credits.get("cast") or [])[:CAST_LIMIT]:
        roles = person.get("roles") or []
        people.append({
            "name": person.get("name") or "",
            "character": roles[0].get("character") if roles else "",
            "profile_path": person.get("profile_path") or "",
            "episodes": person.get("total_episode_count") or 0,
        })
    return people

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
            "cast": _extract_cast(data),
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
    if show is not None and timezone.now() - show.synced_at <= STALE_AFTER:
        return show
    try:
        return sync_show(tmdb_id)
    except requests.RequestException:
        if show is not None:
            return show
        raise


def sync_episodes(season):
    data = tmdb.get_season(season.show.tmdb_id, season.season_number)

    for ep in data.get("episodes") or []:
        Episode.objects.update_or_create(
            season=season,
            episode_number=ep["episode_number"],
            defaults={
                "name": ep.get("name") or "",
                "overview": ep.get("overview") or "",
                "air_date": _date_or_none(ep.get("air_date")),
                "runtime": ep.get("runtime"),
                "still_path": ep.get("still_path") or "",
            },
        )

    season.episodes_synced_at = timezone.now()
    season.save(update_fields=["episodes_synced_at"])
    return season.episodes.all()


def get_or_sync_episodes(season):
    if season.episodes_synced_at is None:
        return sync_episodes(season)
    if not season.has_unaired_episodes:
        return season.episodes.all()
    if timezone.now() - season.episodes_synced_at > EPISODE_STALE_AFTER:
        try:
            return sync_episodes(season)
        except requests.RequestException:
            pass
    return season.episodes.all()