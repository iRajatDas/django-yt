import os
import tempfile
import logging
import re  # For sanitizing filenames
from celery import shared_task
from pytubefix import YouTube
from pytubefix.exceptions import (
    VideoUnavailable,
    AgeRestrictedError,
    VideoPrivate,
    LiveStreamError,
    MembersOnly,
    VideoRegionBlocked,
    UnknownVideoError,
    RecordingUnavailable,
    PytubeFixError,
    RegexMatchError,
)
from django.core.files import File
from .models import DownloadTask
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.signing import TimestampSigner
from django.conf import settings
import urllib.parse
import subprocess
import boto3
from botocore.exceptions import NoCredentialsError
from django.db import connection
from contextlib import contextmanager
from boto3.s3.transfer import TransferConfig

logger = logging.getLogger(__name__)

signer = TimestampSigner()


class ProgressPercentage:
    def __init__(self, filename, task_id, channel_layer, metadata):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self.task_id = task_id
        self.channel_layer = channel_layer
        self.metadata = metadata

    def __call__(self, bytes_amount):
        self._seen_so_far += bytes_amount
        percentage = (self._seen_so_far / self._size) * 100
        notify_progress_update(
            "upload_in_progress",
            self.task_id,
            self.channel_layer,
            self.metadata,
            progress=percentage,
        )


def sanitize_filename(filename):
    """Sanitize the filename to remove any invalid characters."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)


def upload_file_with_progress(
    file_path, bucket_name, key_name, storage_options, task_id, channel_layer, metadata
):
    """
    Upload a file to S3 with progress tracking.
    """
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=storage_options["access_key"],
        aws_secret_access_key=storage_options["secret_key"],
        endpoint_url=storage_options["endpoint_url"],
    )

    # Transfer configuration for progress tracking
    config = TransferConfig(
        multipart_threshold=1024 * 25, max_concurrency=10, multipart_chunksize=1024 * 25
    )

    # Initialize the progress tracker
    progress = ProgressPercentage(file_path, task_id, channel_layer, metadata)

    # Upload the file with the progress tracker
    s3_client.upload_file(
        file_path, bucket_name, key_name, Config=config, Callback=progress
    )


def generate_signed_url(filename: str) -> str:
    """Generate a signed URL for local storage."""
    logger.debug("Generating signed URL for local storage")
    file_name_only = os.path.basename(filename)
    signed_filename = signer.sign(file_name_only)
    signed_filename = urllib.parse.quote(signed_filename)
    return f"{settings.DOMAIN}/download/{signed_filename}"


def generate_s3_signed_url(file_name: str) -> str:
    """Generate a pre-signed URL for S3 storage that forces a download."""
    try:
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.CLOUDFLARE_R2_CONFIG_OPTIONS["endpoint_url"],
            aws_access_key_id=settings.CLOUDFLARE_R2_CONFIG_OPTIONS["access_key"],
            aws_secret_access_key=settings.CLOUDFLARE_R2_CONFIG_OPTIONS["secret_key"],
            config=boto3.session.Config(signature_version="s3v4"),
        )
        bucket_name = settings.CLOUDFLARE_R2_CONFIG_OPTIONS["bucket_name"]
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket_name,
                "Key": file_name,
                "ResponseContentDisposition": f'attachment; filename="{os.path.basename(file_name)}"',
            },
            ExpiresIn=3600,
        )
        return presigned_url
    except NoCredentialsError:
        logger.debug("Credentials not available for S3.")
        return None


def notify_progress_update(
    stage,
    task_id,
    channel_layer,
    metadata=None,
    progress=None,
    download_url=None,
    error_message=None,
):
    """
    Send real-time progress updates with metadata.
    """

    # Construct the message payload
    message = {
        "type": "progress.update",
        "stage": stage,
        "task_id": str(task_id),
        "progress": progress,
        "download_url": download_url,
        "error_message": error_message,
        "metadata": metadata or {},  # Avoid passing None as metadata
    }

    # Log the message before sending
    logger.debug(
        f"Sending WebSocket update for task {task_id}: {message}", exc_info=True
    )

    try:
        # Send the message to the WebSocket group
        async_to_sync(channel_layer.group_send)(
            f"task_{task_id}",
            {
                "type": "progress.update",  # This type is used by the consumer
                "message": message,  # Pass the message payload
            },
        )
        logger.debug(
            f"Message successfully sent to WebSocket group task_{task_id}",
            exc_info=True,
        )

    except Exception as e:
        logger.error(
            f"Failed to send WebSocket message for task {task_id}: {e}", exc_info=True
        )


def run_ffmpeg_with_progress(cmd, task, channel_layer, metadata):
    """
    Run FFmpeg to merge video and audio while sending progress updates.
    """
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        total_duration = None
        for line in process.stderr:
            if "Duration:" in line:
                time_str = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = time_str.split(":")
                total_duration = int(h) * 3600 + int(m) * 60 + float(s)
            if "time=" in line:
                time_str = line.split("time=")[1].split(" ")[0].strip()
                h, m, s = time_str.split(":")
                current_time = int(h) * 3600 + int(m) * 60 + float(s)
                if total_duration:
                    progress = (current_time / total_duration) * 100
                    task.progress = progress
                    task.save()
                    notify_progress_update(
                        "merging_in_progress",
                        task.id,
                        channel_layer,
                        metadata,
                        progress=progress,
                    )

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
        return process.returncode
    except Exception as e:
        logger.debug(f"Error running ffmpeg: {str(e)}")
        task.status = "Failed"
        task.save()
        notify_progress_update(
            "error", task.id, channel_layer, metadata, error_message=str(e)
        )
        raise


@shared_task(bind=True)
def download_video(self, task_id, original_payload):
    """
    Celery task for downloading video and audio from YouTube, merging, and uploading.
    """
    task = DownloadTask.objects.get(id=task_id)
    channel_layer = get_channel_layer()

    video_metadata = {}

    yt = YouTube(
        task.url,
        use_oauth=True,
        allow_oauth_cache=True,
        token_file=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tokens.json",
        ),
    )
    try:
        # Fetch video metadata
        video_metadata = {
            "title": yt.title,
            "views": yt.views,
            "channel_name": yt.author,
            "thumbnail": yt.thumbnail_url,
            "duration": yt.length,
            "original_payload": original_payload,
        }
    # Handle all relevant pytubefix exceptions with personalized error messages
    except (
        VideoUnavailable,
        AgeRestrictedError,
        VideoPrivate,
        LiveStreamError,
        MembersOnly,
        VideoRegionBlocked,
        UnknownVideoError,
        RecordingUnavailable,
    ) as e:
        # Mapping each exception to a personalized error message
        error_messages = {
            VideoUnavailable: "Video is unavailable.",
            AgeRestrictedError: "Video is age-restricted.",
            VideoPrivate: "Video is private.",
            LiveStreamError: "Video is a live stream.",
            MembersOnly: "Video is members-only.",
            VideoRegionBlocked: "Video is blocked in your region.",
            UnknownVideoError: "An unknown video error occurred.",
            RecordingUnavailable: "Recording of live stream is unavailable.",
        }

        error_message = error_messages.get(type(e), "An error occurred.")

        logger.error(f"{error_message}: {str(e)}", exc_info=True)
        task.status = "Failed"
        task.save()

        # Send personalized error message to the user
        notify_progress_update(
            "error", task_id, channel_layer, {}, error_message=error_message
        )

    # Handle other pytubefix and general errors
    except (RegexMatchError, PytubeFixError, Exception) as e:
        logger.error(f"Error downloading video: {str(e)}", exc_info=True)
        task.status = "Failed"
        task.save()
        notify_progress_update(
            "error", task_id, channel_layer, video_metadata or {}, error_message=str(e)
        )

    else:
        resolution = original_payload["resolution"]

        # Determine the video stream
        if resolution == "highest-available":
            video_stream = (
                yt.streams.filter(adaptive=True, file_extension="mp4")
                .order_by("resolution")
                .desc()
                .first()
            )
        elif resolution == "360p":
            video_stream = yt.streams.filter(
                progressive=True, file_extension="mp4", res="360p"
            ).first()
        else:
            video_stream = yt.streams.filter(
                adaptive=True, file_extension="mp4", res=resolution
            ).first()

        if not video_stream:
            raise ValueError(f"No video stream found for resolution {resolution}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as video_file:
            # Download the video
            yt.register_on_progress_callback(
                lambda stream, chunk, bytes_remaining: notify_progress_update(
                    "downloading_video",
                    task_id,
                    channel_layer,
                    video_metadata,
                    progress=(
                        100 * (stream.filesize - bytes_remaining) / stream.filesize
                    ),
                )
            )
            video_stream.download(filename=video_file.name)

            # If 360p (progressive), no need to download audio or merge
            if resolution == "360p":
                output_filename = video_file.name
            else:
                if task.include_audio:
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".mp3"
                    ) as audio_file:
                        # Download audio
                        audio_stream = yt.streams.get_audio_only()
                        yt.register_on_progress_callback(
                            lambda stream, chunk, bytes_remaining: notify_progress_update(
                                "downloading_audio",
                                task_id,
                                channel_layer,
                                video_metadata,
                                progress=(
                                    100
                                    * (stream.filesize - bytes_remaining)
                                    / stream.filesize
                                ),
                            )
                        )
                        audio_stream.download(filename=audio_file.name)

                        # Merge video and audio
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=".mp4"
                        ) as output_file:
                            output_filename = output_file.name
                            merge_cmd = f"ffmpeg -y -i '{video_file.name}' -i '{audio_file.name}' -c:v copy -map 0:v:0 -map 1:a:0 -shortest '{output_file.name}'"
                            run_ffmpeg_with_progress(
                                merge_cmd, task, channel_layer, video_metadata
                            )
                else:
                    output_filename = video_file.name

            # Generate sanitized filename
            sanitized_title = sanitize_filename(yt.title)
            key_name = f"{sanitized_title}_{resolution}.mp4"

            # Upload the file with progress
            bucket_name = settings.CLOUDFLARE_R2_CONFIG_OPTIONS["bucket_name"]
            storage_options = settings.CLOUDFLARE_R2_CONFIG_OPTIONS

            upload_file_with_progress(
                output_filename,
                bucket_name,
                key_name,
                storage_options,
                task_id,
                channel_layer,
                video_metadata,
            )

            # Generate signed URL
            download_url = generate_s3_signed_url(key_name)
            file_size = os.path.getsize(output_filename)

            # Complete the process
            task.status = "Completed"
            task.progress = 100.0
            task.save()

            video_metadata.update(
                {
                    "download_url": download_url,
                    "download_size": file_size,
                }
            )

            notify_progress_update(
                "ready_to_serve",
                task_id,
                channel_layer,
                video_metadata,
                progress=100,
                download_url=download_url,
            )

    finally:
        # Automatically clean up temporary files
        for file_var in ["output_filename", "video_file", "audio_file"]:
            if file_var in locals() and os.path.exists(locals()[file_var]):
                try:
                    os.remove(locals()[file_var])
                except Exception as cleanup_error:
                    logger.warning(
                        f"Error cleaning up file {locals()[file_var]}: {cleanup_error}"
                    )
