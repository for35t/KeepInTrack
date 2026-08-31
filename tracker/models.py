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
    cast = models.JSONField(default=list, blank=True)
    videos = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)

    next_air_date = models.DateField(null=True, blank=True)
    next_season_number = models.IntegerField(null=True, blank=True)
    next_episode_number = models.IntegerField(null=True, blank=True)

    synced_at = models.DateTimeField(auto_now=True)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    
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
    episodes_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("show", "season_number")
        ordering = ["season_number"]

    def __str__(self):
        return f"{self.show.name} — {self.name}"

    @property
    def has_unaired_episodes(self):
        from django.utils import timezone
        today = timezone.localdate()
        return self.episodes.filter(
            models.Q(air_date__isnull=True) | models.Q(air_date__gte=today)
        ).exists()


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

class Episode(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="episodes")
    episode_number = models.IntegerField()
    name = models.CharField(max_length=255, blank=True)
    overview = models.TextField(blank=True)
    air_date = models.DateField(null=True, blank=True)
    runtime = models.IntegerField(null=True, blank=True)
    still_path = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("season", "episode_number")
        ordering = ["episode_number"]

    def __str__(self):
        return f"S{self.season.season_number}E{self.episode_number} — {self.name}"

class ShowEvent(models.Model):
    DATE_ANNOUNCED = "date_announced"
    DATE_CHANGED = "date_changed"
    SEASON_ADDED = "season_added"
    STATUS_CHANGED = "status_changed"

    KIND_CHOICES = [
        (DATE_ANNOUNCED, "Air date announced"),
        (DATE_CHANGED, "Air date changed"),
        (SEASON_ADDED, "New season"),
        (STATUS_CHANGED, "Status changed"),
    ]

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.show.name} — {self.message}"

class Notification(models.Model):
    DATE_ANNOUNCED = "date_announced"
    DATE_CHANGED = "date_changed"
    SEASON_ADDED = "season_added"
    STATUS_CHANGED = "status_changed"

    KIND_CHOICES = [
        (DATE_ANNOUNCED, "Air date announced"),
        (DATE_CHANGED, "Air date changed"),
        (SEASON_ADDED, "New season"),
        (STATUS_CHANGED, "Status changed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="notifications")
    event = models.ForeignKey(
        ShowEvent, on_delete=models.CASCADE, related_name="notifications",
        null=True, blank=True,
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.message}"

class WatchProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watch_progress"
    )
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="watch_progress")
    season_number = models.IntegerField()
    episode_number = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "show")

    def __str__(self):
        return f"{self.user} — {self.show.name} S{self.season_number}E{self.episode_number}"

    @property
    def label(self):
        return f"S{self.season_number}E{self.episode_number}"