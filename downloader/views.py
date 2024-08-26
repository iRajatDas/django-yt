from django.shortcuts import render
from django.http import JsonResponse
from .models import DownloadTask
from .tasks import download_video
from django.views.decorators.csrf import csrf_exempt
import json
import os
from django.conf import settings
from django.http import HttpResponse, Http404
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
import urllib.parse


@csrf_exempt  # Make sure to remove this in production if CSRF protection is re-enabled
def start_download(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            url = data.get('url')
            resolution = data.get('resolution', 'highest-available')
            include_audio = data.get('include_audio', True)

            if not url:
                return JsonResponse({'error': 'URL is required'}, status=400)

            task = DownloadTask.objects.create(
                url=url,
                resolution=resolution,
                include_audio=include_audio,
                status='Pending',
            )

            download_video.delay(str(task.id))

            return JsonResponse({'task_id': str(task.id), 'status': task.status})

        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': 'Invalid request method'}, status=405)

def check_status(request, task_id):
    task = DownloadTask.objects.get(id=task_id)
    return JsonResponse({
        'status': task.status,
        'progress': task.progress,
        'download_url': task.file.url if task.file else None,
    })


def index(request):
    return render(request, 'downloader/index.html')

signer = TimestampSigner()

signer = TimestampSigner()

def download_file(request, signed_filename):
    try:
        # URL-decode the signed filename
        signed_filename = urllib.parse.unquote(signed_filename)

        # Validate the signed value and ensure it hasn't expired (e.g., 24 hours)
        filename = signer.unsign(signed_filename, max_age=86400)  # 24 hours expiration
        file_path = os.path.join(settings.MEDIA_ROOT, 'downloads', filename)  # Prepend downloads directory

        if not os.path.exists(file_path):
            raise Http404("File not found")

        # Serve the file for download
        with open(file_path, 'rb') as file:
            response = HttpResponse(file.read(), content_type="application/octet-stream")
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(filename)}"'
            return response

    except SignatureExpired:
        return HttpResponse("Link expired", status=410)
    except BadSignature:
        return HttpResponse("Invalid link", status=400)