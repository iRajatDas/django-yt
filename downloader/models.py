import uuid
from django.db import models

class DownloadTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    url = models.URLField()
    resolution = models.CharField(max_length=18)
    include_audio = models.BooleanField(default=True)
    status = models.CharField(max_length=50)
    progress = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='downloads/', null=True, blank=True)
