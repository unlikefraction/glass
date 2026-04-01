from django.db import models


class Carbon(models.Model):
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128, blank=True, default="")
    google_sub = models.CharField(max_length=255, unique=True)
    avatar_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "carbons"

    def __str__(self):
        return self.username
