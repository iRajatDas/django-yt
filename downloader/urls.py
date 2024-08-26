from django.urls import path
from .views import start_download, check_status
from .views import index

urlpatterns = [
    path('', index, name='index'),  # Home page that renders the HTML template
    path('start_download/', start_download, name='start_download'),
    path('check_status/<uuid:task_id>/', check_status, name='check_status'),
]
