import json
from channels.generic.websocket import AsyncWebsocketConsumer

class DownloadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        self.task_group_name = f'task_{self.task_id}'
        
        await self.channel_layer.group_add(
            self.task_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.task_group_name,
            self.channel_name
        )

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'status': event['status'],
            'progress': event.get('progress', 0),
            'download_url': event.get('download_url', None)
        }))

    async def progress_update(self, event):
        await self.send(text_data=json.dumps({
            'progress': event['progress']
        }))
