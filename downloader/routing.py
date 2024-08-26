from django.urls import path
from .consumers import DownloadProgressConsumer

websocket_urlpatterns = [
    path('ws/download/<uuid:task_id>/', DownloadProgressConsumer.as_asgi()),
]
