from django.shortcuts import render
from django.http import JsonResponse
from .models import DownloadTask
from .tasks import download_video

def start_download(request):
    url = request.GET.get('url')
    resolution = request.GET.get('resolution', 'highest-available')
    include_audio = request.GET.get('include_audio', 'true').lower() in ['true', '1']

    task = DownloadTask.objects.create(
        url=url,
        resolution=resolution,
        include_audio=include_audio,
        status='Pending',
    )
    
    download_video.delay(str(task.id))

    return JsonResponse({
        'task_id': str(task.id),
        'status': task.status,
    })

def check_status(request, task_id):
    task = DownloadTask.objects.get(id=task_id)
    return JsonResponse({
        'status': task.status,
        'progress': task.progress,
        'download_url': task.file.url if task.file else None,
    })
