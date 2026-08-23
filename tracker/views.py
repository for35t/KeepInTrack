from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm

from . import services, tmdb
from .models import Follow, Show


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
    results = tmdb.search_tv(query) if query else []
    return render(request, "explore.html", {
        "query": query,
        "results": results,
        "image_base": tmdb.IMAGE_BASE,
    })


def show_detail(request, tmdb_id):
    show = services.get_or_sync_show(tmdb_id)
    is_following = (
        request.user.is_authenticated
        and Follow.objects.filter(user=request.user, show=show).exists()
    )
    return render(request, "show_detail.html", {
        "show": show,
        "is_following": is_following,
        "image_base": tmdb.IMAGE_BASE,
        "backdrop_base": tmdb.BACKDROP_BASE,
    })


@login_required
@require_POST
def toggle_follow(request, tmdb_id):
    show = services.get_or_sync_show(tmdb_id)
    follow, created = Follow.objects.get_or_create(user=request.user, show=show)
    if not created:
        follow.delete()
    return redirect("show_detail", tmdb_id=tmdb_id)


@login_required
def my_shows(request):
    shows = Show.objects.filter(followers__user=request.user).order_by(
        F("next_air_date").asc(nulls_last=True), "name"
    )
    return render(request, "my_shows.html", {
        "shows": shows,
        "image_base": tmdb.IMAGE_BASE,
    })


def profile(request):
    return render(request, "profile.html")