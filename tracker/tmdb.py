import os

import requests

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w342"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

def _get(path, **params):
    headers = {"Authorization": f"Bearer {os.environ['TMDB_READ_TOKEN']}"}
    response = requests.get(f"{BASE_URL}{path}", params=params, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def search_tv(query):
    return _get("/search/tv", query=query)["results"]


def get_tv(tmdb_id):
    return _get(f"/tv/{tmdb_id}")