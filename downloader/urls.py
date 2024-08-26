from django.urls import path
from .views import start_download, check_status

urlpatterns = [
    path('start_download/', start_download, name='start_download'),
    path('check_status/<uuid:task_id>/', check_status, name='check_status'),
]
