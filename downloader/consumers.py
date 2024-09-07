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

    async def status_update(self, event):
        try:
            # Log the status update before sending
            logger.info(
                f"Status update received for task {self.task_id}: {event.get('status')}"
            )

            # Send the entire event dictionary as the response to the client
            await self.send(text_data=json.dumps(event))

            # Automatically close WebSocket if task is completed or failed
            if event["status"] in ["Completed", "Failed"] or event["stage"] in [
                "error",
            ]:
                logger.info(
                    f"Closing WebSocket for task {self.task_id} as it is {event['status']}"
                )
                await self.close()
        except Exception as e:
            logger.error(f"Error sending status update for task {self.task_id}: {e}")
            await self.close()

    async def progress_update(self, event):
        try:
            # Log progress update details
            logger.info(
                f"Progress update received for task {self.task_id}: {event.get('progress')}%"
            )

            logger.info(f"Current status: {event.get('status')}")

            # Send the entire event dictionary as the response
            await self.send(text_data=json.dumps(event))

            # Automatically close WebSocket if task is completed or failed
            if event["status"] in ["Completed", "Failed"] or event["stage"] in [
                "error"
            ]:
                logger.info(
                    f"Closing WebSocket for task {self.task_id} as it is {event['stage']}"
                )
                await self.close()
        except Exception as e:
            logger.error(f"Error sending progress update for task {self.task_id}: {e}")
            await self.close()

    async def websocket_close(self, event):
        try:
            logger.info(f"WebSocket close requested for task {self.task_id}")
            await self.close()
        except Exception as e:
            logger.error(f"Error closing WebSocket for task {self.task_id}: {e}")
