from datetime import timedelta
import requests
from django.utils import timezone
from django.core.cache import cache

from . import tmdb
from .models import Episode, Follow, Notification, Season, Show, ShowEvent

EPISODE_STALE_AFTER = timedelta(hours=12)
CAST_LIMIT = 15
STALE_AFTER = timedelta(hours=12)
GENRE_CACHE_KEY = "tmdb_tv_genres"
GENRE_CACHE_SECONDS = 60 * 60 * 24 * 7
REGION_CACHE_KEY = "tmdb_watch_regions"
PROVIDER_CACHE_SECONDS = 60 * 60 * 24
STREAMING_KEYS = ("flatrate", "free", "ads")
EVENT_RETENTION = timedelta(days=30)
VIDEO_LIMIT = 3
RECOMMENDATION_LIMIT = 8
TRAILER_TYPES = ("Trailer", "Teaser")

def get_watch_regions():
    regions = cache.get(REGION_CACHE_KEY)
    if regions is None:
        try:
            data = tmdb.get_watch_regions()
        except requests.RequestException:
            return []
        regions = sorted(
            ((r["iso_3166_1"], r["english_name"]) for r in data.get("results") or []),
            key=lambda pair: pair[1],
        )
        cache.set(REGION_CACHE_KEY, regions, GENRE_CACHE_SECONDS)
    return regions


def get_providers(tmdb_id, region):
    key = f"providers:{tmdb_id}:{region}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        data = tmdb.get_watch_providers(tmdb_id)
    except requests.RequestException:
        return [], ""

    region_data = (data.get("results") or {}).get(region) or {}
    seen = {}
    for bucket in STREAMING_KEYS:
        for provider in region_data.get(bucket) or []:
            seen.setdefault(provider["provider_id"], provider)

    providers = sorted(seen.values(), key=lambda p: p.get("display_priority", 999))
    result = (providers, region_data.get("link", ""))
    cache.set(key, result, PROVIDER_CACHE_SECONDS)
    return result


def suggest_region(request):
    header = request.headers.get("Accept-Language", "")
    for part in header.split(","):
        tag = part.split(";")[0].strip()
        if "-" in tag:
            return tag.rsplit("-", 1)[-1].upper()
    return ""

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

def _extract_videos(data):
    videos = (data.get("videos") or {}).get("results") or []
    picked = [
        {
            "key": v["key"],
            "name": v.get("name") or "",
            "type": v.get("type") or "",
            "published_at": v.get("published_at") or "",
        }
        for v in videos
        if v.get("site") == "YouTube"
        and v.get("official")
        and v.get("type") in TRAILER_TYPES
    ]
    picked.sort(key=lambda v: v["published_at"], reverse=True)
    return picked[:VIDEO_LIMIT]


def _extract_recommendations(data):
    recs = (data.get("recommendations") or {}).get("results") or []
    return [
        {
            "tmdb_id": r["id"],
            "name": r.get("name") or "",
            "poster_path": r.get("poster_path") or "",
        }
        for r in recs[:RECOMMENDATION_LIMIT]
    ]

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
            "videos": _extract_videos(data),
            "recommendations": _extract_recommendations(data),
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


READ_RETENTION = timedelta(days=1)


def _record_event(show, kind, message):
    event = ShowEvent.objects.create(show=show, kind=kind, message=message)
    user_ids = Follow.objects.filter(show=show).values_list("user_id", flat=True)
    Notification.objects.bulk_create([
        Notification(user_id=uid, show=show, event=event, kind=kind, message=message)
        for uid in user_ids
    ])
    return event


def purge_old_events():
    cutoff = timezone.now() - EVENT_RETENTION
    deleted, _ = ShowEvent.objects.filter(created_at__lt=cutoff).delete()
    return deleted

def detect_changes(before, show):
    if before is None:
        return

    if show.next_air_date and not before["next_air_date"]:
        _record_event(
            show, Notification.DATE_ANNOUNCED,
            f"{show.name} — S{show.next_season_number}E{show.next_episode_number} "
            f"airs {show.next_air_date:%b %d, %Y}",
        )
    elif show.next_air_date and show.next_air_date != before["next_air_date"]:
        _record_event(
            show, Notification.DATE_CHANGED,
            f"{show.name} — next episode moved to {show.next_air_date:%b %d, %Y}",
        )

    if show.number_of_seasons > before["number_of_seasons"]:
        _record_event(
            show, Notification.SEASON_ADDED,
            f"{show.name} — season {show.number_of_seasons} added",
        )

    if show.status != before["status"]:
        _record_event(
            show, Notification.STATUS_CHANGED,
            f"{show.name} — status is now {show.status}",
        )


def purge_old_notifications():
    cutoff = timezone.now() - READ_RETENTION
    deleted, _ = Notification.objects.filter(read_at__lt=cutoff).delete()
    return deleted