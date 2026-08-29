from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from urllib.parse import urlencode
from . import services, tmdb
from .models import Follow, Show

from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Follow, Season, Show

import requests
from django.http import Http404

PER_PAGE = 30
TMDB_PAGE_SIZE = 20
TMDB_MAX_RESULTS = 10000


def _paged(fetch, page):
    start = (page - 1) * PER_PAGE
    first_page = start // TMDB_PAGE_SIZE + 1
    offset = start % TMDB_PAGE_SIZE

    items = []
    total = 0
    for tmdb_page in (first_page, first_page + 1):
        if tmdb_page > 500:
            break
        data = fetch(tmdb_page)
        total = data.get("total_results") or 0
        results = data.get("results") or []
        items.extend(results)
        if len(results) < TMDB_PAGE_SIZE:
            break

    window = items[offset:offset + PER_PAGE]
    has_next = (start + PER_PAGE) < min(total, TMDB_MAX_RESULTS)
    return window, has_next


def _page_url(request, page):
    params = request.GET.copy()
    params["page"] = page
    return f"?{params.urlencode()}"

def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})

def home(request):
    upcoming = []
    if request.user.is_authenticated:
        upcoming = (
            Show.objects
            .filter(followers__user=request.user)
            .filter(Q(next_air_date__isnull=False) | Q(status__in=Show.RETURNING_STATUSES))
            .order_by(F("next_air_date").asc(nulls_last=True), "name")
        )
    return render(request, "home.html", {
        "upcoming": upcoming,
        "image_base": tmdb.IMAGE_BASE,
    })


def explore(request):
    query = request.GET.get("q", "").strip()
    selected = request.GET.getlist("genre")
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    genre_map = services.get_genre_map()
    results = []
    has_next = False
    error = None

    try:
        if selected:
            results, has_next = _paged(
                lambda p: tmdb.discover_tv(",".join(selected), page=p), page
            )
        elif query:
            results, has_next = _paged(
                lambda p: tmdb.search_tv(query, page=p), page
            )
    except requests.RequestException:
        error = "Search is unavailable right now. Try again in a moment."

    for show in results:
        show["genre_names"] = [
            genre_map[gid] for gid in show.get("genre_ids") or [] if gid in genre_map
        ]

    options = sorted(genre_map.items(), key=lambda pair: pair[1])
    chips = _genre_chips(options, selected, [("q", query)] if query else None)
    selected_names = [
        genre_map[int(g)] for g in selected if g.isdigit() and int(g) in genre_map
    ]

    context = {
        "query": query,
        "chips": chips,
        "selected_names": selected_names,
        "results": results,
        "error": error,
        "page": page,
        "has_next": has_next,
        "prev_url": _page_url(request, page - 1) if page > 1 else None,
        "next_url": _page_url(request, page + 1) if has_next else None,
        "image_base": tmdb.IMAGE_BASE,
    }
    if request.headers.get("HX-Request"):
        return render(request, "partials/explore_results.html", context)
    return render(request, "explore.html", context)

def _genre_chips(options, selected, extra_params=None):
    chips = []
    for value, label in options:
        value = str(value)
        active = value in selected
        remaining = [v for v in selected if v != value] if active else selected + [value]
        params = [("genre", v) for v in remaining]
        if extra_params:
            params.extend(extra_params)
        chips.append({
            "label": label,
            "active": active,
            "url": f"?{urlencode(params)}" if params else "?",
        })
    return chips

def show_detail(request, tmdb_id):
    try:
        show = services.get_or_sync_show(tmdb_id)
    except requests.RequestException:
        raise Http404("Couldn't load that show.")
    Show.objects.filter(pk=show.pk).update(last_viewed_at=timezone.now())
    is_following = (
        request.user.is_authenticated
        and Follow.objects.filter(user=request.user, show=show).exists()
    )
    name_to_id = services.get_genre_name_to_id()
    genre_links = [{"name": g, "id": name_to_id.get(g)} for g in show.all_genres]
    return render(request, "show_detail.html", {
        "show": show,
        "is_following": is_following,
        "image_base": tmdb.IMAGE_BASE,
        "backdrop_base": tmdb.BACKDROP_BASE,
        "profile_base": tmdb.PROFILE_BASE,
        "genre_links": genre_links,
    })


@login_required
@require_POST
def toggle_follow(request, tmdb_id):
    try:
        show = services.get_or_sync_show(tmdb_id)
    except requests.RequestException:
        raise Http404("Couldn't load that show.")
    follow, created = Follow.objects.get_or_create(user=request.user, show=show)
    if not created:
        follow.delete()
    return redirect("show_detail", tmdb_id=tmdb_id)

@login_required
def my_shows(request):
    selected = request.GET.getlist("genre")
    shows = list(
        Show.objects.filter(followers__user=request.user).order_by(
            F("next_air_date").asc(nulls_last=True), "name"
        )
    )

    available = sorted({genre for show in shows for genre in show.all_genres})
    if selected:
        shows = [s for s in shows if set(selected) <= set(s.all_genres)]

    return render(request, "my_shows.html", {
        "shows": shows,
        "chips": _genre_chips([(g, g) for g in available], selected),
        "image_base": tmdb.IMAGE_BASE,
    })


@login_required
def profile(request):
    return render(request, "profile.html")

def season_episodes(request, tmdb_id, season_number):
    show = get_object_or_404(Show, tmdb_id=tmdb_id)
    season = get_object_or_404(Season, show=show, season_number=season_number)
    try:
        episodes = services.get_or_sync_episodes(season)
    except requests.RequestException:
        episodes = season.episodes.all()
    return render(request, "partials/episodes.html", {
        "episodes": episodes,
        "still_base": tmdb.STILL_BASE,
    })