import os
import tempfile
import logging
from celery import shared_task
from pytubefix import YouTube
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
import redis

logger = logging.getLogger(__name__)

signer = TimestampSigner()

# Initialize Redis connection
redis_client = redis.StrictRedis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=os.getenv("REDIS_PORT", 6379),
    db=0,
)

# Check if the Redis connection is working
try:
    redis_client.ping()
except redis.exceptions.ConnectionError:
    logger.error("Redis connection error")
    raise


@contextmanager
def advisory_lock(lock_key):
    """PostgreSQL advisory lock."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT pg_try_advisory_lock({lock_key});")
        acquired = cursor.fetchone()[0]
        try:
            if acquired:
                yield True
            else:
                yield False
        finally:
            if acquired:
                cursor.execute(f"SELECT pg_advisory_unlock({lock_key});")


@contextmanager
def redis_lock(lock_name, timeout=60):
    """Context manager for Redis locking."""
    lock = redis_client.lock(lock_name, timeout=timeout)
    acquired = lock.acquire(blocking=False)
    try:
        if acquired:
            yield True
        else:
            yield False
    finally:
        if acquired:
            lock.release()


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


def run_ffmpeg_with_progress(cmd, task, channel_layer):
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
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {
                            "type": "progress.update",
                            "progress": task.progress,
                            "progress_type": "merge",
                        },
                    )

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
        return process.returncode
    except Exception as e:
        logger.debug(f"Error running ffmpeg: {str(e)}")
        task.status = "Failed"
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "status.update", "status": task.status, "error": str(e)},
        )
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}", {"type": "websocket.close"}
        )
        raise


@shared_task
def download_video(task_id):
    task = DownloadTask.objects.get(id=task_id)
    channel_layer = get_channel_layer()
    lock_name = f"download-lock-{task.id}"

    with redis_lock(lock_name) as acquired:
        if not acquired:
            logger.debug(f"Task already in progress for {task_id}")
            return

    def notify_status_update(
        status, progress=None, progress_type=None, download_url=None, error_message=None
    ):
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {
                "type": "status.update",
                "status": status,
                "progress": progress,
                "progress_type": progress_type,
                "download_url": download_url,
                "error": error_message,
            },
        )

    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".mp4"
        ) as video_file, tempfile.NamedTemporaryFile(
            delete=False, suffix=".mp3"
        ) as audio_file, tempfile.NamedTemporaryFile(
            delete=False, suffix=".mp4"
        ) as output_file:

            video_filename = video_file.name
            audio_filename = audio_file.name
            output_video = output_file.name

            yt = YouTube(
                task.url,
                use_oauth=True,
                allow_oauth_cache=True,
                token_file=os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tokens.json",
                ),
            )

            def on_progress(stream, chunk, bytes_remaining):
                total_size = stream.filesize
                bytes_downloaded = total_size - bytes_remaining
                percentage = (bytes_downloaded / total_size) * 100
                task.progress = percentage
                task.save()
                async_to_sync(channel_layer.group_send)(
                    f"task_{task.id}",
                    {
                        "type": "progress.update",
                        "progress": task.progress,
                        "progress_type": "download",
                    },
                )

            yt.register_on_progress_callback(on_progress)

            if task.resolution == "highest-available":
                video = (
                    yt.streams.filter(adaptive=True, file_extension="mp4")
                    .order_by("resolution")
                    .desc()
                    .first()
                )
            elif task.resolution == "lowest-available":
                video = (
                    yt.streams.filter(adaptive=True, file_extension="mp4")
                    .order_by("resolution")
                    .asc()
                    .first()
                )
            else:
                video = yt.streams.filter(
                    res=task.resolution, file_extension="mp4", adaptive=True
                ).first()

            if not video:
                error_message = f"No video stream found for resolution {task.resolution}. Please try a different resolution."
                logger.debug(error_message)
                task.status = "Failed"
                task.save()
                notify_status_update("Failed", error_message=error_message)
                return

            task.status = "Video download started"
            task.save()
            notify_status_update(task.status)

            video.download(filename=video_filename)

            if task.include_audio:
                task.status = "Audio download started"
                task.save()
                notify_status_update(task.status)

                audio = (
                    yt.streams.filter(only_audio=True).order_by("abr").desc().first()
                )
                audio.download(filename=audio_filename)

                task.status = "Merging video and audio"
                task.save()
                notify_status_update(task.status)

                merge_cmd = f"ffmpeg -y -i '{video_filename}' -i '{audio_filename}' -c:v copy -map 0:v:0 -map 1:a:0 -shortest '{output_video}'"
                run_ffmpeg_with_progress(merge_cmd, task, channel_layer)

                with open(output_video, "rb") as f:
                    task.file.save(f"{yt.title}.mp4", File(f))

            else:
                with open(video_filename, "rb") as f:
                    task.file.save(f"{yt.title}.mp4", File(f))

            if (
                settings.STORAGES["default"]["BACKEND"]
                == "storages.backends.s3boto3.S3Boto3Storage"
            ):
                download_url = generate_s3_signed_url(task.file.name)
            else:
                download_url = generate_signed_url(task.file.name)

            task.status = "Completed"
            task.progress = 100.0
            task.save()
            notify_status_update("Completed", task.progress, download_url)
    except Exception as e:
        logger.debug(f"Error downloading video: {str(e)}")
        task.status = "Failed"
        task.save()
        notify_status_update("Failed", error_message=str(e))
    finally:
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}", {"type": "websocket.close"}
        )
        try:
            os.remove(video_filename)
            os.remove(audio_filename)
            os.remove(output_video)
        except Exception as cleanup_error:
            logger.debug(f"Cleanup failed: {str(cleanup_error)}")
