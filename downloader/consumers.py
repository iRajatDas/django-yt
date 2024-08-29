import json
from channels.generic.websocket import AsyncWebsocketConsumer
import logging

logger = logging.getLogger(__name__)


class DownloadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope["url_route"]["kwargs"]["task_id"]
        self.task_group_name = f"task_{self.task_id}"

        await self.channel_layer.group_add(self.task_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.task_group_name, self.channel_name)

    async def status_update(self, event):
        try:
            # Send the entire event dictionary directly as the response
            await self.send(text_data=json.dumps(event))
            if event["status"] in ["Completed", "Failed"]:
                # Close the WebSocket connection if the task is done
                await self.close()
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
            await self.close()

    async def progress_update(self, event):
        try:
            # Send the entire event dictionary directly as the response
            await self.send(text_data=json.dumps(event))
        except Exception as e:
            logger.error(f"Error sending progress update: {e}")
            await self.close()

    async def websocket_close(self, event):
        try:
            await self.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket: {e}")
