from celery import shared_task
from pytubefix import YouTube
import tempfile
import os
import subprocess
from django.core.files import File
from .models import DownloadTask
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

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
                subprocess.call(merge_cmd, shell=True)

                with open(output_video, 'rb') as f:
                    task.file.save(f'{yt.title}.mp4', File(f))

            else:
                with open(video_filename, 'rb') as f:
                    task.file.save(f'{yt.title}.mp4', File(f))

            task.status = 'Completed'
            task.progress = 100.0
            task.save()
            async_to_sync(channel_layer.group_send)(
                f"task_{task.id}",
                {"type": "status.update", "status": task.status, "progress": task.progress, "download_url": task.file.url}
            )

    finally:
        os.remove(video_filename)
        os.remove(audio_filename)
        os.remove(output_video)
