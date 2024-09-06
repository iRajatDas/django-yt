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


@csrf_exempt  # Remove or secure properly in production
def start_download(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        # Load and validate input JSON
        data = json.loads(request.body)
        url = data.get("url")
        resolution = data.get("resolution", "highest-available")
        include_audio = data.get("include_audio", True)

        # Ensure URL is provided
        if not url:
            return JsonResponse({"error": "URL is required"}, status=400)

        # Validate the URL format
        try:
            URLValidator()(url)
            if not validate_youtube_url(url):
                raise ValidationError("Invalid YouTube URL format.")
        except ValidationError:
            return JsonResponse({"error": "Invalid URL"}, status=400)

        # Create the task and save initial data
        task = DownloadTask.objects.create(
            url=url,
            resolution=resolution,
            include_audio=include_audio,
            status="Pending",
        )

        # Generate WebSocket callback URL
        task.callback_url = (
            f"{request.scheme}://{request.get_host()}/ws/download/{task.id}"
        )
        task.save()

        # Prepare the original payload for traceability
        original_payload = {
            "url": url,
            "resolution": resolution,
            "include_audio": include_audio,
        }

        # Start the download task with original payload
        download_video.apply_async(str(task.id), original_payload)

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
    task = get_object_or_404(DownloadTask, id=task_id)
    return JsonResponse(
        {
            "status": task.status,
            "progress": task.progress,
            "download_url": task.file.url if task.file else None,
        }
    )


def download_file(request, signed_filename):
    """Serve a file download via signed URL."""
    try:
        # Decode and verify the signed filename
        signed_filename = urllib.parse.unquote(signed_filename)
        filename = signer.unsign(signed_filename, max_age=86400)
        file_path = os.path.join(settings.MEDIA_ROOT, "downloads", filename)

        # Check if file exists
        if not os.path.exists(file_path):
            raise Http404("File not found")

        # Serve the file for download
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
    """Render the index page for the downloader app."""
    return render(request, "downloader/index.html")
