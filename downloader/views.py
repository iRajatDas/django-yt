from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from .models import DownloadTask
from .tasks import download_video
from django.views.decorators.csrf import csrf_exempt
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.conf import settings
import json
import os
import re
import urllib.parse
import logging

logger = logging.getLogger(__name__)
signer = TimestampSigner()


# Utility function to validate YouTube URL
def validate_youtube_url(url):
    youtube_regex = (
        r"(https?://)?(www\.)?"
        r"(youtube|youtu|youtube-nocookie)\.(com|be)/"
        r"(watch\?v=|embed/|v/|.+\?v=|shorts/)?([^&=%\?]{11})"
    )
    return re.match(youtube_regex, url) is not None


@csrf_exempt
def start_download(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        data = json.loads(request.body)
        url = data.get("url")
        resolution = data.get("resolution", "highest-available")
        include_audio = data.get("include_audio", True)

        if not url:
            return JsonResponse({"error": "URL is required"}, status=400)

        try:
            URLValidator()(url)
            if not validate_youtube_url(url):
                raise ValidationError("Invalid YouTube URL format.")
        except ValidationError:
            return JsonResponse({"error": "Invalid URL"}, status=400)

        # Check for existing task to prevent duplication
        existing_task = DownloadTask.objects.filter(
            url=url, status="in_progress"
        ).first()
        if existing_task:
            return JsonResponse(
                {
                    "error": "A download task for this video is already in progress.",
                    "task_id": str(existing_task.id),
                    "status": existing_task.status,
                    "callback_url": existing_task.callback_url,
                }
            )

        task = DownloadTask.objects.create(
            url=url,
            resolution=resolution,
            include_audio=include_audio,
            status="pending",
            stage="queued",
        )

        task.callback_url = (
            f"{request.scheme}://{request.get_host()}/ws/download/{task.id}"
        )
        task.save()

        original_payload = {
            "url": url,
            "resolution": resolution,
            "include_audio": include_audio,
        }

        download_video.delay(str(task.id), original_payload)

        return JsonResponse(
            {
                "task_id": str(task.id),
                "status": task.status,
                "callback_url": task.callback_url,
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format"}, status=400)
    except Exception as e:
        logger.error(f"Error starting download: {e}", exc_info=True)
        return JsonResponse({"error": "Internal server error"}, status=500)


def check_status(request, task_id):
    """Check the status and progress of a specific download task."""
    logger.info(f"Fetching status for task_id: {task_id}")
    task = DownloadTask.objects.filter(id=task_id).first()
    if not task:
        logger.error(f"Task with id {task_id} not found")
        return JsonResponse({"error": "Task not found"}, status=404)

    return JsonResponse(
        task.to_dict(),
    )


def download_file(request, signed_filename):
    try:
        signed_filename = urllib.parse.unquote(signed_filename)
        filename = signer.unsign(signed_filename, max_age=86400)
        file_path = os.path.join(settings.MEDIA_ROOT, "downloads", filename)

        if not os.path.exists(file_path):
            raise Http404("File not found")

        return HttpResponse(
            open(file_path, "rb").read(), content_type="application/octet-stream"
        )

    except SignatureExpired:
        return HttpResponse("Link expired", status=410)
    except BadSignature:
        return HttpResponse("Invalid link", status=400)
    except Exception as e:
        logger.error(f"Error downloading file: {e}", exc_info=True)
        return HttpResponse("Error serving file", status=500)


def index(request):
    return render(request, "downloader/index.html")
