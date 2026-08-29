import os

import requests

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"
PROFILE_BASE = "https://image.tmdb.org/t/p/w185"


def get_tv(tmdb_id):
    return _get(f"/tv/{tmdb_id}", append_to_response="aggregate_credits")


def _get(path, **params):
    headers = {"Authorization": f"Bearer {os.environ['TMDB_READ_TOKEN']}"}
    response = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def search_tv(query, page=1):
    return _get("/search/tv", query=query, page=page)


def discover_tv(genre_ids, page=1):
    return _get("/discover/tv", with_genres=genre_ids, sort_by="popularity.desc", page=page)

STILL_BASE = "https://image.tmdb.org/t/p/w300"


def get_season(tmdb_id, season_number):
    return _get(f"/tv/{tmdb_id}/season/{season_number}")

def get_tv_genres():
    return _get("/genre/tv/list")

def discover_tv(genre_id, page=1):
    return _get("/discover/tv", with_genres=genre_id, sort_by="popularity.desc", page=page)