from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from urllib.parse import urlencode
from . import services, tmdb
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import (
    Episode, Follow, Notification, Profile, Season, Show, ShowEvent,
    WatchProgress, get_profile,
)
import requests
from django.http import Http404

PER_PAGE = 30
TMDB_PAGE_SIZE = 20
TMDB_MAX_RESULTS = 10000

def _get_region(request):
    if not request.user.is_authenticated:
        return request.session.get("region", "")

    profile = get_profile(request.user)
    session_region = request.session.get("region", "")
    if not profile.region and session_region:
        profile.region = session_region
        profile.save(update_fields=["region"])
    return profile.region


def _save_region(request, region):
    if request.user.is_authenticated:
        profile = get_profile(request.user)
        profile.region = region
        profile.save(update_fields=["region"])
    else:
        request.session["region"] = region

def _watch_context(request, tmdb_id):
    region = _get_region(request)
    providers, watch_link = ([], "")
    if region:
        providers, watch_link = services.get_providers(tmdb_id, region)
    regions = services.get_watch_regions()
    return {
        "tmdb_id": tmdb_id,
        "region": region,
        "region_name": dict(regions).get(region, region),
        "regions": regions,
        "suggested_region": services.suggest_region(request),
        "providers": providers,
        "watch_link": watch_link,
        "logo_base": tmdb.LOGO_BASE,
    }

@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user).select_related("show")
    return render(request, "notifications.html", {"items": items})


@login_required
@require_POST
def read_notification(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=["read_at"])
    return redirect("show_detail", tmdb_id=note.show.tmdb_id)


@login_required
@require_POST
def delete_notification(request, pk):
    get_object_or_404(Notification, pk=pk, user=request.user).delete()
    return redirect("notifications")


@login_required
@require_POST
def clear_read_notifications(request):
    Notification.objects.filter(user=request.user, read_at__isnull=False).delete()
    return redirect("notifications")

def _annotate_progress(episodes, season_number, progress):
    episodes = list(episodes)
    for episode in episodes:
        if progress is None:
            episode.watched = False
            episode.is_current = False
        else:
            position = (season_number, episode.episode_number)
            current = (progress.season_number, progress.episode_number)
            episode.watched = position <= current
            episode.is_current = position == current
    return episodes

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
    if not request.user.is_authenticated:
        return render(request, "home.html", {})

    today = timezone.localdate()
    followed = list(Show.objects.filter(followers__user=request.user))
    followed_ids = {show.tmdb_id for show in followed}

    airing = (
        Episode.objects
        .filter(
            season__show__followers__user=request.user,
            air_date__gte=today,
            air_date__lte=today + timedelta(days=7),
        )
        .select_related("season", "season__show")
        .order_by("air_date")
    )

    events = list(
        ShowEvent.objects
        .filter(show__followers__user=request.user)
        .select_related("show")[:8]
    )

    trailers = [
        {"show": show, "video": video}
        for show in followed
        for video in show.videos
    ]
    trailers.sort(key=lambda t: t["video"].get("published_at") or "", reverse=True)

    seen = {}
    for show in followed:
        for rec in show.recommendations:
            if rec["tmdb_id"] in followed_ids or rec["tmdb_id"] in seen:
                continue
            seen[rec["tmdb_id"]] = {**rec, "because": show.name}

    return render(request, "home.html", {
        "airing": airing,
        "events": events,
        "trailers": trailers[:8],
        "recommendations": list(seen.values())[:12],
        "image_base": tmdb.IMAGE_BASE,
        "still_base": tmdb.STILL_BASE,
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

    progress = None
    if request.user.is_authenticated:
        progress = WatchProgress.objects.filter(user=request.user, show=show).first()

    context = {
        "show": show,
        "is_following": is_following,
        "image_base": tmdb.IMAGE_BASE,
        "backdrop_base": tmdb.BACKDROP_BASE,
        "profile_base": tmdb.PROFILE_BASE,
        "genre_links": genre_links,
        "progress": progress,
    }
    context.update(_watch_context(request, tmdb_id))
    return render(request, "show_detail.html", context)

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

    progress_map = {
        p.show_id: p for p in WatchProgress.objects.filter(user=request.user)
    }
    for show in shows:
        show.progress = progress_map.get(show.id)

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
    region = _get_region(request)
    return render(request, "profile.html", {
        "region": region,
        "region_name": dict(services.get_watch_regions()).get(region, ""),
        "regions": services.get_watch_regions(),
        "suggested_region": services.suggest_region(request),
    })

def season_episodes(request, tmdb_id, season_number):
    show = get_object_or_404(Show, tmdb_id=tmdb_id)
    season = get_object_or_404(Season, show=show, season_number=season_number)
    try:
        episodes = services.get_or_sync_episodes(season)
    except requests.RequestException:
        episodes = season.episodes.all()

    progress = None
    if request.user.is_authenticated:
        progress = WatchProgress.objects.filter(user=request.user, show=show).first()

    return render(request, "partials/episodes.html", {
        "episodes": _annotate_progress(episodes, season_number, progress),
        "tmdb_id": tmdb_id,
        "season_number": season_number,
        "still_base": tmdb.STILL_BASE,
    })

@require_POST
def set_region(request):
    region = request.POST.get("region", "").strip().upper()
    valid = {code for code, _ in services.get_watch_regions()}
    if region in valid:
        _save_region(request, region)

    tmdb_id = request.POST.get("tmdb_id")
    has_show = bool(tmdb_id and tmdb_id.isdigit())

    if request.headers.get("HX-Request") and has_show:
        return render(request, "partials/watch.html", _watch_context(request, int(tmdb_id)))
    if has_show:
        return redirect("show_detail", tmdb_id=int(tmdb_id))
    return redirect("profile")

@login_required
@require_POST
def set_progress(request, tmdb_id, season_number, episode_number):
    show = get_object_or_404(Show, tmdb_id=tmdb_id)
    progress = WatchProgress.objects.filter(user=request.user, show=show).first()

    if progress and (progress.season_number, progress.episode_number) == (season_number, episode_number):
        progress.delete()
        progress = None
    else:
        progress, _ = WatchProgress.objects.update_or_create(
            user=request.user, show=show,
            defaults={"season_number": season_number, "episode_number": episode_number},
        )

    season = get_object_or_404(Season, show=show, season_number=season_number)
    return render(request, "partials/episodes.html", {
        "episodes": _annotate_progress(season.episodes.all(), season_number, progress),
        "tmdb_id": tmdb_id,
        "season_number": season_number,
        "still_base": tmdb.STILL_BASE,
    })