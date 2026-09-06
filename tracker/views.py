from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from urllib.parse import urlencode
from . import services, tmdb
from datetime import timedelta
from collections import Counter
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import (
    Episode, Follow, Notification, Profile, Season, Show, ShowEvent,
    WatchProgress, get_profile,
)
import requests
from django.http import Http404, HttpResponse
from concurrent.futures import ThreadPoolExecutor
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.contrib import messages
from django import forms
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from .tokens import email_verification_token

COUNTRIES = [
    ("US", "United States"), ("GB", "United Kingdom"), ("JP", "Japan"),
    ("KR", "South Korea"), ("CA", "Canada"), ("AU", "Australia"),
    ("FR", "France"), ("DE", "Germany"), ("ES", "Spain"), ("IT", "Italy"),
    ("SE", "Sweden"), ("DK", "Denmark"), ("NO", "Norway"), ("BE", "Belgium"),
    ("BR", "Brazil"), ("MX", "Mexico"), ("AR", "Argentina"),
    ("IN", "India"), ("CN", "China"), ("TW", "Taiwan"), ("TH", "Thailand"),
    ("TR", "Turkey"), ("IL", "Israel"), ("RU", "Russia"),
]

STATUSES = [
    ("0", "Returning"), ("2", "In production"),
    ("1", "Planned"), ("3", "Ended"), ("4", "Cancelled"),
]

PILL_CLASSES = {
    "genre": "bg-violet-500/15 text-violet-300 border-violet-500/40",
    "year": "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
    "country": "bg-sky-500/15 text-sky-300 border-sky-500/40",
    "status": "bg-amber-500/15 text-amber-300 border-amber-500/40",
    "provider": "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
}

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

def _watch_context(request, tmdb_id, media_type="tv"):
    region = _get_region(request)
    providers, watch_link = ([], "")
    if region:
        providers, watch_link = services.get_providers(tmdb_id, region, media_type)
    regions = services.get_watch_regions()
    return {
        "tmdb_id": tmdb_id,
        "media_type": media_type,
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

def _progress_bounds(season_number, progress):
    if progress is None:
        return 0, -1
    if progress.season_number > season_number:
        return 10000, -1
    if progress.season_number == season_number:
        return progress.episode_number, progress.episode_number
    return 0, -1

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

class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

def _send_verification_email(request, user):
    if not user.email:
        return
    context = {
        "username": user.username,
        "uid": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": email_verification_token.make_token(user),
        "domain": request.get_host(),
        "protocol": "https" if request.is_secure() else "http",
    }
    send_mail(
        "Confirm your KeepInTrack email",
        render_to_string("email/verify_email.txt", context),
        None,
        [user.email],
        using="quiet",
    )

def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            _send_verification_email(request, user)
            login(request, user)
            return redirect("home")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})

def home(request):
    popular = services.get_popular_shows()

    if not request.user.is_authenticated:
        return render(request, "home.html", {
            "popular": popular[:12],
            "image_base": tmdb.IMAGE_BASE,
        })
    now = timezone.now()
    today = timezone.localdate()
    followed = list(Show.objects.filter(followers__user=request.user))
    followed_ids = {show.tmdb_id for show in followed}

    airing_qs = (
        Episode.objects
        .filter(
            season__show__followers__user=request.user,
            air_date__gte=today,
            air_date__lte=today + timedelta(days=7),
        )
        .select_related("season", "season__show")
        .order_by("air_date")
    )
    airing_count = airing_qs.count()
    airing = list(airing_qs[:10])

    events = list(
        ShowEvent.objects
        .filter(show__followers__user=request.user)
        .select_related("show")[:8]
    )

    cutoff = (now - timedelta(days=365)).isoformat()
    trailers = [
        {"show": show, "video": video}
        for show in followed
        for video in show.videos
        if (video.get("published_at") or "") >= cutoff
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
        "airing_count": airing_count,
        "events": events,
        "trailers": trailers[:8],
        "recommendations": list(seen.values())[:12],
        "popular": [s for s in popular if s["tmdb_id"] not in followed_ids][:12],
        "image_base": tmdb.IMAGE_BASE,
        "still_base": tmdb.STILL_BASE,
    })

def _normalise_results(raw, tv_genres, movie_genres, force_type=None):
    items = []
    for entry in raw:
        media = force_type or entry.get("media_type")
        if media not in ("tv", "movie"):
            continue
        is_movie = media == "movie"
        gmap = movie_genres if is_movie else tv_genres
        items.append({
            "tmdb_id": entry["id"],
            "media_type": media,
            "name": (entry.get("title") if is_movie else entry.get("name")) or "",
            "poster_path": entry.get("poster_path") or "",
            "date": (entry.get("release_date") if is_movie else entry.get("first_air_date")) or "",
            "genre_names": [gmap[g] for g in entry.get("genre_ids") or [] if g in gmap],
        })
    return items

def _annotate_availability(results, provider, region):
    if not (provider and region and results):
        return

    def check(item):
        providers, _ = services.get_providers(item["tmdb_id"], region, item["media_type"])
        return any(str(p["provider_id"]) == provider for p in providers)

    with ThreadPoolExecutor(max_workers=8) as pool:
        flags = list(pool.map(check, results))
    for item, flag in zip(results, flags):
        item["on_provider"] = flag

def explore(request):
    query = request.GET.get("q", "").strip()
    browse_movies = request.GET.get("browse") == "movie"
    genres = request.GET.getlist("genre")
    year = request.GET.get("year", "").strip()
    country = request.GET.get("country", "").strip()
    status = "" if browse_movies else request.GET.get("status", "").strip()
    provider = request.GET.get("provider", "").strip()

    all_regions = services.get_watch_regions()
    region_param = request.GET.get("region", "").strip().upper()
    if region_param and region_param in {code for code, _ in all_regions}:
        _save_region(request, region_param)
    region = _get_region(request)

    region_providers = services.get_region_providers(region)
    provider_map = {str(pid): name for pid, name in region_providers}
    if provider not in provider_map:
        provider = ""

    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    tv_genre_map = services.get_genre_map()
    movie_genre_map = services.get_movie_genre_map()
    active_genre_map = movie_genre_map if browse_movies else tv_genre_map

    results = []
    has_next = False
    error = None
    filtering = bool(genres or year or country or status or provider)

    try:
        if query:
            raw, has_next = _paged(lambda p: tmdb.search_multi(query, page=p), page)
            results = _normalise_results(raw, tv_genre_map, movie_genre_map)
            _annotate_availability(results, provider, region)
        elif browse_movies:
            raw, has_next = _paged(
                lambda p: tmdb.discover_movie(
                    page=p,
                    with_genres=",".join(genres),
                    primary_release_year=year if year.isdigit() else "",
                    with_origin_country=country,
                    with_watch_providers=provider,
                    watch_region=region if provider else "",
                ),
                page,
            )
            results = _normalise_results(raw, tv_genre_map, movie_genre_map, force_type="movie")
        else:
            raw, has_next = _paged(
                lambda p: tmdb.discover_tv(
                    page=p,
                    with_genres=",".join(genres),
                    first_air_date_year=year if year.isdigit() else "",
                    with_origin_country=country,
                    with_status=status,
                    with_watch_providers=provider,
                    watch_region=region if provider else "",
                ),
                page,
            )
            results = _normalise_results(raw, tv_genre_map, movie_genre_map, force_type="tv")
    except requests.RequestException:
        error = "Search is unavailable right now. Try again in a moment."

    genre_chips = [
        {
            "label": name,
            "active": str(gid) in genres,
            "url": _param_url(request, "genre", gid, add=str(gid) not in genres),
        }
        for gid, name in sorted(active_genre_map.items(), key=lambda pair: pair[1])
    ]

    region_options = [
        {"label": name, "active": code == region,
         "url": _param_url(request, "region", code, add=True)}
        for code, name in all_regions
    ]

    toggle = request.GET.copy()
    toggle.pop("page", None)
    toggle.pop("status", None)
    toggle.setlist("genre", [])
    if browse_movies:
        toggle.pop("browse", None)
    else:
        toggle["browse"] = "movie"

    context = {
        "query": query,
        "browse_movies": browse_movies,
        "browse_toggle_url": f"?{toggle.urlencode()}" if toggle else "?",
        "genres": genres,
        "year": year,
        "country": country,
        "status": status,
        "provider": provider,
        "provider_name": provider_map.get(provider, ""),
        "region": region,
        "region_name": dict(all_regions).get(region, ""),
        "region_options": region_options,
        "suggested_region": services.suggest_region(request),
        "genre_chips": genre_chips,
        "applied": _applied_filters(request, active_genre_map, genres, year, country, status, provider, provider_map),
        "year_options": _single_options(request, "year", [(y, y) for y in range(timezone.localdate().year + 1, 1959, -1)], year),
        "country_options": _single_options(request, "country", COUNTRIES, country),
        "status_options": _single_options(request, "status", STATUSES, status),
        "provider_options": _single_options(request, "provider", region_providers, provider),
        "results": results,
        "error": error,
        "page": page,
        "has_next": has_next,
        "prev_url": _page_url(request, page - 1) if page > 1 else None,
        "next_url": _page_url(request, page + 1) if has_next else None,
        "image_base": tmdb.IMAGE_BASE,
    }
    if request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request"):
        return render(request, "partials/explore_results.html", context)
    return render(request, "explore.html", context)

def _param_url(request, key, value, add):
    params = request.GET.copy()
    if key == "genre":
        values = params.getlist("genre")
        if add and str(value) not in values:
            values.append(str(value))
        elif not add:
            values = [v for v in values if v != str(value)]
        params.setlist("genre", values)
    elif add:
        params[key] = value
    else:
        params.pop(key, None)
    params.pop("page", None)
    return f"?{params.urlencode()}" if params else "?"

def _single_options(request, param, choices, current):
    options = []
    for value, label in choices:
        value = str(value)
        active = value == current
        options.append({
            "label": label,
            "active": active,
            "url": _param_url(request, param, value, add=not active),
        })
    return options

def _applied_filters(request, genre_map, genres, year, country, status, provider="", provider_map=None):
    applied = []
    for gid in genres:
        if gid.isdigit() and int(gid) in genre_map:
            applied.append({
                "label": genre_map[int(gid)],
                "classes": PILL_CLASSES["genre"],
                "remove": _param_url(request, "genre", gid, add=False),
            })
    if year:
        applied.append({
            "label": year, "classes": PILL_CLASSES["year"],
            "remove": _param_url(request, "year", year, add=False),
        })
    if country:
        applied.append({
            "label": dict(COUNTRIES).get(country, country),
            "classes": PILL_CLASSES["country"],
            "remove": _param_url(request, "country", country, add=False),
        })
    if status:
        applied.append({
            "label": dict(STATUSES).get(status, status),
            "classes": PILL_CLASSES["status"],
            "remove": _param_url(request, "status", status, add=False),
        })
    if provider:
        applied.append({
            "label": (provider_map or {}).get(provider, "Service"),
            "classes": PILL_CLASSES["provider"],
            "remove": _param_url(request, "provider", provider, add=False),
        })
    return applied

def _library_pills(request, genres, year, country, status):
    applied = []
    for genre in genres:
        applied.append({
            "label": genre, "classes": PILL_CLASSES["genre"],
            "remove": _param_url(request, "genre", genre, add=False),
        })
    if year:
        applied.append({
            "label": year, "classes": PILL_CLASSES["year"],
            "remove": _param_url(request, "year", year, add=False),
        })
    if country:
        applied.append({
            "label": dict(COUNTRIES).get(country, country),
            "classes": PILL_CLASSES["country"],
            "remove": _param_url(request, "country", country, add=False),
        })
    if status:
        applied.append({
            "label": status, "classes": PILL_CLASSES["status"],
            "remove": _param_url(request, "status", status, add=False),
        })
    return applied


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
        "still_base": tmdb.STILL_BASE,
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
    genres = request.GET.getlist("genre")
    year = request.GET.get("year", "").strip()
    country = request.GET.get("country", "").strip()
    status = request.GET.get("status", "").strip()

    shows = list(
        Show.objects.filter(followers__user=request.user).order_by(
            F("next_air_date").asc(nulls_last=True), "name"
        )
    )

    progress_map = {p.show_id: p for p in WatchProgress.objects.filter(user=request.user)}
    for show in shows:
        show.progress = progress_map.get(show.id)

    available_genres = sorted({g for s in shows for g in s.all_genres})
    available_years = sorted(
        {s.first_air_date.year for s in shows if s.first_air_date}, reverse=True
    )
    available_countries = sorted({c for s in shows for c in s.origin_country})
    available_statuses = sorted({s.status for s in shows if s.status})

    if genres:
        shows = [s for s in shows if set(genres) <= set(s.all_genres)]
    if year.isdigit():
        shows = [s for s in shows if s.first_air_date and s.first_air_date.year == int(year)]
    if country:
        shows = [s for s in shows if country in s.origin_country]
    if status:
        shows = [s for s in shows if s.status == status]

    genre_chips = [
        {
            "label": genre,
            "active": genre in genres,
            "url": _param_url(request, "genre", genre, add=genre not in genres),
        }
        for genre in available_genres
    ]

    return render(request, "my_shows.html", {
        "shows": shows,
        "genres": genres,
        "year_options": _single_options(request, "year", [(y, y) for y in available_years], year),
        "country_options": _single_options(request, "country", [(c, dict(COUNTRIES).get(c, c)) for c in available_countries], country),
        "status_options": _single_options(request, "status", [(s, s) for s in available_statuses], status),
        "genre_chips": genre_chips,
        "applied": _library_pills(request, genres, year, country, status),
        "years": available_years,
        "countries": [(c, dict(COUNTRIES).get(c, c)) for c in available_countries],
        "statuses": available_statuses,
        "image_base": tmdb.IMAGE_BASE,
    })


@login_required
def profile(request):
    region = _get_region(request)
    shows = list(Show.objects.filter(followers__user=request.user))
    progress_map = {p.show_id: p for p in WatchProgress.objects.filter(user=request.user)}

    genre_counts = Counter(g for show in shows for g in show.all_genres)
    top_genre = genre_counts.most_common(1)[0][0] if genre_counts else "—"

    continue_watching = [
        show for show in shows
        if show.id in progress_map and show.status in Show.RETURNING_STATUSES
    ][:6]

    return render(request, "profile.html", {
        "region": region,
        "region_name": dict(services.get_watch_regions()).get(region, ""),
        "regions": services.get_watch_regions(),
        "suggested_region": services.suggest_region(request),
        "stat_following": len(shows),
        "stat_airing": sum(1 for s in shows if s.release_state == "scheduled"),
        "stat_waiting": sum(1 for s in shows if s.release_state == "undated"),
        "stat_finished": sum(1 for s in shows if s.release_state == "finished"),
        "stat_tracked": len(progress_map),
        "top_genre": top_genre,
        "continue_watching": continue_watching,
        "image_base": tmdb.IMAGE_BASE,
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
    through, current = _progress_bounds(season_number, progress)

    return render(request, "partials/episodes.html", {
        "episodes": episodes,
        "tmdb_id": tmdb_id,
        "season_number": season_number,
        "watched_through": through,
        "current_ep": current,
        "still_base": tmdb.STILL_BASE,
    })

@require_POST
def set_region(request):
    region = request.POST.get("region", "").strip().upper()
    valid = {code for code, _ in services.get_watch_regions()}
    if region in valid:
        _save_region(request, region)

    tmdb_id = request.POST.get("tmdb_id")
    media_type = request.POST.get("media_type", "tv")
    if media_type not in ("tv", "movie"):
        media_type = "tv"
    has_item = bool(tmdb_id and tmdb_id.isdigit())

    if request.headers.get("HX-Request") and has_item:
        return render(request, "partials/watch.html", _watch_context(request, int(tmdb_id), media_type))
    if has_item:
        view = "movie_detail" if media_type == "movie" else "show_detail"
        return redirect(view, tmdb_id=int(tmdb_id))

    next_view = request.POST.get("next_view", "")
    if next_view in {"explore", "my_shows"}:
        return redirect(next_view)
    return redirect("profile")

@login_required
@require_POST
def set_progress(request, tmdb_id, season_number, episode_number):
    show = get_object_or_404(Show, tmdb_id=tmdb_id)
    progress = WatchProgress.objects.filter(user=request.user, show=show).first()

    if progress and (progress.season_number, progress.episode_number) == (season_number, episode_number):
        progress.delete()
    else:
        WatchProgress.objects.update_or_create(
            user=request.user, show=show,
            defaults={"season_number": season_number, "episode_number": episode_number},
        )
    return HttpResponse(status=204)

def movie_detail(request, tmdb_id):
    try:
        movie = services.get_movie(tmdb_id)
    except requests.RequestException:
        raise Http404("Couldn't load that movie.")

    context = {
        "movie": movie,
        "image_base": tmdb.IMAGE_BASE,
        "backdrop_base": tmdb.BACKDROP_BASE,
        "profile_base": tmdb.PROFILE_BASE,
    }
    context.update(_watch_context(request, tmdb_id, "movie"))
    return render(request, "movie_detail.html", context)

@staff_member_required
def admin_users(request):
    User = get_user_model()
    users = (
        User.objects
        .annotate(follow_count=Count("follows", distinct=True))
        .order_by("-date_joined")
    )
    now = timezone.now()
    return render(request, "admin_users.html", {
        "users": users,
        "total_users": users.count(),
        "staff_count": sum(1 for u in users if u.is_staff),
        "active_30d": sum(
            1 for u in users
            if u.last_login and (now - u.last_login).days <= 30
        ),
        "never_logged_in": sum(1 for u in users if u.last_login is None),
    })


@staff_member_required
@require_POST
def admin_delete_user(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)

    if target.pk == request.user.pk:
        messages.error(request, "You can't delete your own account.")
    elif target.is_staff or target.is_superuser:
        messages.error(request, "Staff accounts can only be removed from the terminal.")
    else:
        username = target.username
        target.delete()
        messages.success(request, f"Deleted {username}.")

    return redirect("admin_users")

def verify_email(request, uidb64, token):
    User = get_user_model()
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user and email_verification_token.check_token(user, token):
        profile = get_profile(user)
        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=["email_verified"])
        messages.success(request, "Email confirmed — thanks.")
    else:
        messages.error(request, "That confirmation link is invalid or has expired.")
    return redirect("home")


@login_required
@require_POST
def resend_verification(request):
    _send_verification_email(request, request.user)
    messages.success(request, "Confirmation email sent.")
    return redirect("profile")