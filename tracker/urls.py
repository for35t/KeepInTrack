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
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:pk>/read/", views.read_notification, name="read_notification"),
    path("notifications/<int:pk>/delete/", views.delete_notification, name="delete_notification"),
    path("notifications/clear-read/", views.clear_read_notifications, name="clear_read_notifications"),
    path("set-region/", views.set_region, name="set_region"),
    path("show/<int:tmdb_id>/progress/<int:season_number>/<int:episode_number>/",
         views.set_progress, name="set_progress"),
]