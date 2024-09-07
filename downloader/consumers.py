import json
from channels.generic.websocket import AsyncWebsocketConsumer
import logging

logger = logging.getLogger(__name__)


class DownloadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope["url_route"]["kwargs"]["task_id"]
        self.task_group_name = f"task_{self.task_id}"

        # Join the group for task-specific updates
        await self.channel_layer.group_add(self.task_group_name, self.channel_name)
        await self.accept()
        logger.info(f"WebSocket connection established for task {self.task_id}")

    async def disconnect(self, close_code):
        # Leave the group when WebSocket disconnects
        await self.channel_layer.group_discard(self.task_group_name, self.channel_name)
        logger.info(f"WebSocket connection closed for task {self.task_id}")

    async def progress_update(self, event):
        try:
            logger.info(f"Status update received for task {self.task_id}: {event.get('status')}")
            await self.send(text_data=json.dumps(event))

            # Close socket on completion/failure
            if event["status"] in ["Completed", "Failed"] or event["stage"] in ["error"]:
                logger.info(f"Closing WebSocket for task {self.task_id} due to completion or error.")
                await self.close()
        except Exception as e:
            logger.error(f"Error sending status update for task {self.task_id}: {e}")
            await self.close(code=1001)  # Explicitly send a close frame


    async def websocket_close(self, event):
        try:
            logger.info(f"WebSocket close requested for task {self.task_id}")
            await self.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket for task {self.task_id}: {e}")
