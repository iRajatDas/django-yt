import subprocess
from celery import shared_task
from pytubefix import YouTube
import tempfile
import os
from django.core.files import File
from .models import DownloadTask
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.signing import TimestampSigner
from django.conf import settings
import urllib.parse
import logging
import boto3
from botocore.exceptions import NoCredentialsError

logger = logging.getLogger(__name__)

signer = TimestampSigner()

def generate_signed_url(filename: str) -> str:
    """Generate a signed URL for local storage."""
    logger.info("Generating signed URL for local storage")
    file_name_only = os.path.basename(filename)  # Extract only the filename
    signed_filename = signer.sign(file_name_only)
    signed_filename = urllib.parse.quote(signed_filename)  # URL-encode the signed filename
    return f"{settings.DOMAIN}/download/{signed_filename}"

def generate_s3_signed_url(file_name: str) -> str:
    """Generate a pre-signed URL for S3 storage that forces a download."""
    try:
        s3_client = boto3.client(
            's3',
            endpoint_url=settings.CLOUDFLARE_R2_CONFIG_OPTIONS['endpoint_url'],
            aws_access_key_id=settings.CLOUDFLARE_R2_CONFIG_OPTIONS['access_key'],
            aws_secret_access_key=settings.CLOUDFLARE_R2_CONFIG_OPTIONS['secret_key'],
            config=boto3.session.Config(signature_version='s3v4')            
        )
        bucket_name = settings.CLOUDFLARE_R2_CONFIG_OPTIONS['bucket_name']
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': bucket_name,
                'Key': file_name,
                'ResponseContentDisposition': f'attachment; filename="{os.path.basename(file_name)}"'
            },
            ExpiresIn=3600  # URL expires in 1 hour
        )
        return presigned_url
    except NoCredentialsError:
        logger.error("Credentials not available for S3.")
        return None


def run_ffmpeg_with_progress(cmd, task, channel_layer):
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        total_duration = None
        for line in process.stderr:
            if 'Duration:' in line:
                time_str = line.split('Duration:')[1].split(',')[0].strip()
                h, m, s = time_str.split(':')
                total_duration = int(h) * 3600 + int(m) * 60 + float(s)
            if 'time=' in line:
                time_str = line.split('time=')[1].split(' ')[0].strip()
                h, m, s = time_str.split(':')
                current_time = int(h) * 3600 + int(m) * 60 + float(s)
                if total_duration:
                    progress = (current_time / total_duration) * 100
                    task.progress = progress
                    task.save()
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "progress.update", "progress": task.progress}
                    )

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)
        return process.returncode
    except Exception as e:
        logger.error(f"Error running ffmpeg: {str(e)}")
        task.status = 'Failed'
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "status.update", "status": task.status, "error": str(e)}
        )
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "websocket.close"}
        )
        raise

@shared_task
def download_video(task_id):
    task = DownloadTask.objects.get(id=task_id)
    channel_layer = get_channel_layer()

    def on_progress(stream, chunk, bytes_remaining):
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = (bytes_downloaded / total_size) * 100
        task.progress = percentage
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "progress.update", "progress": task.progress}
        )

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as video_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file, \
             tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as output_file:

            video_filename = video_file.name
            audio_filename = audio_file.name
            output_video = output_file.name

            yt = YouTube(task.url)
            yt.register_on_progress_callback(on_progress)
            video = yt.streams.filter(adaptive=True, file_extension='mp4').order_by('resolution').desc().first()

            task.status = 'Video download started'
            task.save()
            async_to_sync(channel_layer.group_send)(
                f"task_{task.id}",
                {"type": "status.update", "status": task.status}
            )

            video.download(filename=video_filename)

            if task.include_audio:
                task.status = 'Audio download started'
                task.save()
                async_to_sync(channel_layer.group_send)(
                    f"task_{task.id}",
                    {"type": "status.update", "status": task.status}
                )

                audio = yt.streams.filter(only_audio=True).order_by('abr').desc().first()
                audio.download(filename=audio_filename)

                task.status = 'Merging video and audio'
                task.save()
                async_to_sync(channel_layer.group_send)(
                    f"task_{task.id}",
                    {"type": "status.update", "status": task.status}
                )

                merge_cmd = f"ffmpeg -y -i '{video_filename}' -i '{audio_filename}' -c:v copy -map 0:v:0 -map 1:a:0 -shortest '{output_video}'"
                run_ffmpeg_with_progress(merge_cmd, task, channel_layer)

                try:
                    with open(output_video, 'rb') as f:
                        task.file.save(f'{yt.title}.mp4', File(f))
                except Exception as e:
                    logger.error(f"File saving failed: {str(e)}")
                    task.status = 'Failed'
                    task.save()
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "status.update", "status": task.status, "error": f"File saving failed: {str(e)}"}
                    )
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "websocket.close"}
                    )
                    raise

            else:
                try:
                    with open(video_filename, 'rb') as f:
                        task.file.save(f'{yt.title}.mp4', File(f))
                except Exception as e:
                    logger.error(f"File saving failed: {str(e)}")
                    task.status = 'Failed'
                    task.save()
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "status.update", "status": task.status, "error": f"File saving failed: {str(e)}"}
                    )
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "websocket.close"}
                    )
                    raise

            # Conditionally generate URL based on storage backend
            if settings.STORAGES['default']['BACKEND'] == 'storages.backends.s3boto3.S3Boto3Storage':
                download_url = generate_s3_signed_url(task.file.name)
            else:
                download_url = generate_signed_url(task.file.name)

            task.status = 'Completed'
            task.progress = 100.0
            task.save()
            async_to_sync(channel_layer.group_send)(
                f"task_{task.id}",
                {"type": "status.update", "status": task.status, "progress": task.progress, "download_url": download_url}
            )
            async_to_sync(channel_layer.group_send)(
                f"task_{task.id}",
                {"type": "websocket.close"}
            )

    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        task.status = 'Failed'
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "status.update", "status": task.status, "error": str(e)}
        )
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "websocket.close"}
        )
    finally:
        try:
            os.remove(video_filename)
            os.remove(audio_filename)
            os.remove(output_video)
        except Exception as cleanup_error:
            logger.error(f"Cleanup failed: {str(cleanup_error)}")
