import os

import requests

BASE_URL = "https://api.themoviedb.org/3"

IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
PROFILE_BASE = "https://image.tmdb.org/t/p/w185"
STILL_BASE = "https://image.tmdb.org/t/p/w300"
LOGO_BASE = "https://image.tmdb.org/t/p/w92"


def _get(path, **params):
    headers = {"Authorization": f"Bearer {os.environ['TMDB_READ_TOKEN']}"}
    response = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


# --- Shows ---

def search_tv(query, page=1):
    return _get("/search/tv", query=query, page=page)

def search_multi(query, page=1):
    return _get("/search/multi", query=query, page=page)

def discover_tv(page=1, **filters):
    params = {"sort_by": "popularity.desc", "page": page}
    params.update({key: value for key, value in filters.items() if value})
    return _get("/discover/tv", **params)

def discover_movie(page=1, **filters):
    params = {"sort_by": "popularity.desc", "page": page}
    params.update({key: value for key, value in filters.items() if value})
    return _get("/discover/movie", **params)

def get_trending_tv():
    return _get("/trending/tv/week")

def get_tv(tmdb_id):
    return _get(
        f"/tv/{tmdb_id}",
        append_to_response="aggregate_credits,videos,recommendations",
    )


def get_season(tmdb_id, season_number):
    return _get(f"/tv/{tmdb_id}/season/{season_number}")

def get_movie(tmdb_id):
    return _get(f"/movie/{tmdb_id}", append_to_response="credits,recommendations")

# --- Reference data ---

def get_tv_genres():
    return _get("/genre/tv/list")

def get_movie_genres():
    return _get("/genre/movie/list")

def get_watch_providers(tmdb_id):
    return _get(f"/tv/{tmdb_id}/watch/providers")

def get_movie_providers(tmdb_id):
    return _get(f"/movie/{tmdb_id}/watch/providers")

def get_watch_regions():
    return _get("/watch/providers/regions")

def get_tv_providers(region):
    return _get("/watch/providers/tv", watch_region=region)