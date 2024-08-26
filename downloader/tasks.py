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

signer = TimestampSigner()


def generate_signed_url(filename: str) -> str:
    print("Generating signed URL")
    file_name_only = os.path.basename(filename)  # Extract only the filename
    signed_filename = signer.sign(file_name_only)
    signed_filename = urllib.parse.quote(signed_filename)  # URL-encode the signed filename
    return f"{settings.DOMAIN}/download/{signed_filename}"

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
        task.status = 'Failed'
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "status.update", "status": task.status, "error": str(e)}
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
                    task.status = 'Failed'
                    task.save()
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "status.update", "status": task.status, "error": f"File saving failed: {str(e)}"}
                    )
                    raise

            else:
                try:
                    with open(video_filename, 'rb') as f:
                        task.file.save(f'{yt.title}.mp4', File(f))
                except Exception as e:
                    task.status = 'Failed'
                    task.save()
                    async_to_sync(channel_layer.group_send)(
                        f"task_{task.id}",
                        {"type": "status.update", "status": task.status, "error": f"File saving failed: {str(e)}"}
                    )
                    raise

            # Generate the signed URL
            download_url = generate_signed_url(task.file.name)

            task.status = 'Completed'
            task.progress = 100.0
            task.save()
            async_to_sync(channel_layer.group_send)(
                f"task_{task.id}",
                {"type": "status.update", "status": task.status, "progress": task.progress, "download_url": download_url}
            )

    except Exception as e:
        task.status = 'Failed'
        task.save()
        async_to_sync(channel_layer.group_send)(
            f"task_{task.id}",
            {"type": "status.update", "status": task.status, "error": str(e)}
        )
    finally:
        try:
            os.remove(video_filename)
            os.remove(audio_filename)
            os.remove(output_video)
        except Exception as cleanup_error:
            # Log the cleanup error if necessary, but do not overwrite the original failure reason
            print(f"Cleanup failed: {str(cleanup_error)}")
