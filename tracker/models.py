from django.conf import settings
from django.db import models


class Show(models.Model):
    RETURNING_STATUSES = {"Returning Series", "In Production", "Planned"}

    tmdb_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    overview = models.TextField(blank=True)
    poster_path = models.CharField(max_length=255, blank=True)
    backdrop_path = models.CharField(max_length=255, blank=True)
    first_air_date = models.DateField(null=True, blank=True)
    last_air_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True)
    number_of_seasons = models.IntegerField(default=0)
    networks = models.JSONField(default=list, blank=True)
    extra_genres = models.JSONField(default=list, blank=True)
    genres = models.JSONField(default=list, blank=True)

    next_air_date = models.DateField(null=True, blank=True)
    next_season_number = models.IntegerField(null=True, blank=True)
    next_episode_number = models.IntegerField(null=True, blank=True)

    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def release_state(self):
        if self.next_air_date:
            return "scheduled"
        if self.status in self.RETURNING_STATUSES:
            return "undated"
        return "finished"

    @property
    def all_genres(self):
        return self.genres + [g for g in self.extra_genres if g not in self.genres]


class Season(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="seasons")
    season_number = models.IntegerField()
    name = models.CharField(max_length=255)
    overview = models.TextField(blank=True)
    poster_path = models.CharField(max_length=255, blank=True)
    air_date = models.DateField(null=True, blank=True)
    episode_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ("show", "season_number")
        ordering = ["season_number"]

    def __str__(self):
        return f"{self.show.name} — {self.name}"


class Follow(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follows"
    )
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "show")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} → {self.show}"