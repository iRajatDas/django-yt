import uuid
from django.db import models


class DownloadTask(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    STAGE_CHOICES = [
        ("queued", "Queued"),
        ("fetching_metadata", "Fetching Metadata"),
        ("downloading_video", "Downloading Video"),
        ("downloading_audio", "Downloading Audio"),
        ("merging", "Merging Video and Audio"),
        ("uploading", "Uploading to Storage"),
        ("completed", "Completed"),
        ("error", "Error"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    url = models.URLField()
    resolution = models.CharField(max_length=18)
    include_audio = models.BooleanField(default=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="pending")
    stage = models.CharField(max_length=50, choices=STAGE_CHOICES, default="queued")
    progress = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    callback_url = models.URLField(null=True, blank=True)
    file = models.FileField(upload_to="downloads/", null=True, blank=True)
    file_size = models.BigIntegerField(null=True, blank=True)

    def to_dict(
        self,
    ):
        # return all fields as a dictionary
        return {
            "task_id": str(self.id),
            "url": self.url,
            "resolution": self.resolution,
            "include_audio": self.include_audio,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "callback_url": self.callback_url,
            "file": self.file.name,
            "file_size": self.file_size,
        }
