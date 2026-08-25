from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("explore/", views.explore, name="explore"),
    path("my-shows/", views.my_shows, name="my_shows"),
    path("profile/", views.profile, name="profile"),
    path("show/<int:tmdb_id>/", views.show_detail, name="show_detail"),
    path("show/<int:tmdb_id>/follow/", views.toggle_follow, name="toggle_follow"),
    path("signup/", views.signup, name="signup"),
    path("show/<int:tmdb_id>/season/<int:season_number>/", views.season_episodes, name="season_episodes"),
]