import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from celery import Task
from celery_worker import celery_worker
from core.config import settings
from services.listener_service import (add_monitored_channel,
                                       discover_channels, get_listener_status,
                                       get_monitored_channels,
                                       process_single_message_enhanced,
                                       remove_monitored_channel,
                                       set_listener_status,
                                       store_messages_elasticsearch)
from services.minio_service import MinIOManager
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (MessageMediaDocument, MessageMediaPhoto,
                               PeerChannel)

logger = logging.getLogger(__name__)


class ListenerTask(Task):
    """Custom task class for listener operations"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure and update listener status.

        This method is called when a listener task fails and updates
        the Redis status to reflect the stopped state.

        Args:
            exc: Exception that caused the failure.
            task_id: Unique identifier of the failed task.
            args: Positional arguments passed to the task.
            kwargs: Keyword arguments passed to the task.
            einfo: Exception information object.

        Example:
            Called automatically by Celery on task failure.
        """
        logger.error(f"Listener task {task_id} failed: {exc}")
        # Update status to stopped on failure
        set_listener_status(
            {
                "is_running": False,
                "download_images": False,
                "monitored_channels": 0,
                "channels": [],
                "error": str(exc),
                "stopped_at": datetime.now().isoformat(),
            }
        )


@celery_worker.task(
    name="listener.start", bind=True, base=ListenerTask, serializer="json"
)
def start_listener_task(self, download_images: bool = True) -> Dict[str, Any]:
    """Start the real-time message listener with event handling.

    This Celery task initializes the Telegram listener to monitor channels
    for new messages and process them in real-time.

    Args:
        download_images: Whether to download and store images from messages.

    Example:
        start_listener_task.delay(download_images=True)
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting message listener")

    async def run_listener():
        # Create Telegram client
        client = TelegramClient(
            StringSession(settings.telegram.string_session),
            settings.telegram.api_id,
            settings.telegram.api_hash,
        )

        try:
            await client.start()

            # Discover channels first
            channels = await discover_channels(client)

            # Update status
            set_listener_status(
                {
                    "is_running": True,
                    "download_images": download_images,
                    "monitored_channels": len(channels),
                    "channels": channels,
                    "started_at": datetime.now().isoformat(),
                    "task_id": task_id,
                }
            )

            # Enhanced message handler with better event filtering
            @client.on(events.NewMessage())
            async def handle_new_message(event):
                try:
                    message = event.message
                    logger.info(
                        f"Received message {message.id} from {type(message.peer_id)}"
                    )

                    # Check if message is from a channel
                    if hasattr(message.peer_id, "channel_id"):
                        channel_id = message.peer_id.channel_id
                        monitored = get_monitored_channels()

                        logger.info(
                            f"Message {message.id} from channel {channel_id}"
                        )

                        if channel_id not in monitored:
                            # New channel detected, add it
                            add_monitored_channel(channel_id)
                            logger.info(
                                f"Added new channel {channel_id} to monitoring"
                            )

                        # Skip messages without images if download_images is False
                        if not download_images and message.media:
                            if isinstance(
                                message.media,
                                (MessageMediaPhoto, MessageMediaDocument),
                            ):
                                logger.debug(
                                    f"Skipping message {message.id} (has media, download_images=False)"
                                )
                                return

                        # Create simplified message data
                        message_data = {
                            "id": message.id,
                            "text": message.text or "",
                            "date": (
                                message.date.isoformat()
                                if message.date
                                else None
                            ),
                            "media_type": (
                                type(message.media).__name__
                                if message.media
                                else None
                            ),
                            "sender_id": getattr(message, "sender_id", None),
                        }

                        # Process message in background
                        logger.info(
                            f"Queuing message {message.id} for processing"
                        )
                        process_message_task.delay(
                            message_data=message_data,
                            channel_id=channel_id,
                            download_images=download_images,
                        )

                    else:
                        logger.debug(
                            f"Ignoring non-channel message {message.id}"
                        )

                except Exception as e:
                    logger.error(f"Error handling new message: {e}")

            logger.info(
                f"Listener started, monitoring {len(channels)} channels"
            )
            logger.info("Event handler registered, waiting for messages...")

            # Keep the listener running and handle updates
            while True:
                # Check if we should stop
                current_status = get_listener_status()
                if not current_status.get("is_running", False):
                    break

                # Process any pending updates
                await client.catch_up()
                await asyncio.sleep(1)

            logger.info("Listener stopped")

        finally:
            await client.disconnect()

    try:
        asyncio.run(run_listener())
        return {"status": "stopped", "message": "Listener stopped normally"}
    except Exception as e:
        logger.error(f"[{task_id}] Error in listener: {e}")
        raise


@celery_worker.task(name="listener.stop", serializer="json")
def stop_listener_task() -> Dict[str, Any]:
    """Stop the message listener and update status.

    This task gracefully stops the message listener by updating
    the Redis status flag that the listener monitors.

    Example:
        stop_listener_task.delay()
    """
    try:
        status = get_listener_status()

        if not status.get("is_running", False):
            return {
                "status": "not_running",
                "message": "Listener is not running",
            }

        # Update status to stop the listener
        set_listener_status(
            {
                "is_running": False,
                "download_images": status.get("download_images", True),
                "monitored_channels": 0,
                "channels": [],
                "stopped_at": datetime.now().isoformat(),
            }
        )

        logger.info("Listener stop requested")
        return {"status": "stopping", "message": "Listener stop requested"}

    except Exception as e:
        logger.error(f"Error stopping listener: {e}")
        raise


@celery_worker.task(name="listener.process_message", serializer="json")
def process_message_task(
    message_data: Dict[str, Any], channel_id: int, download_images: bool = True
) -> Dict[str, Any]:
    """Process a single message with proper entity handling.

    This task processes individual messages from the listener queue,
    handling entity resolution and storing results in Elasticsearch.

    Args:
        message_data: Dictionary containing message metadata.
        channel_id: The channel ID containing the message.
        download_images: Whether to download and store images.

    Example:
        process_message_task.delay(msg_data, 123456, download_images=True)
    """

    async def process_message():
        # Create fresh client
        client = TelegramClient(
            StringSession(settings.telegram.string_session),
            settings.telegram.api_id,
            settings.telegram.api_hash,
        )

        minio_manager = None
        if download_images:
            minio_manager = MinIOManager()

        try:
            await client.start()

            # Get the actual message object with better error handling
            try:
                # First, try to get the channel entity to ensure it's cached
                try:
                    channel_entity = await client.get_entity(
                        PeerChannel(channel_id)
                    )
                except Exception:
                    # If PeerChannel fails, try to get it from dialogs
                    await client.get_dialogs()
                    channel_entity = await client.get_entity(channel_id)

                # Now get the message
                message = await client.get_messages(
                    channel_entity, ids=message_data["id"]
                )
                if not message:
                    return {"status": "message_not_found"}

            except Exception as e:
                logger.error(
                    f"Error fetching message {message_data['id']}: {e}"
                )
                return {"status": "error", "error": str(e)}

            # Process the message with enhanced sender handling
            message_info = await process_single_message_enhanced(
                message, channel_id, client, download_images, minio_manager
            )

            if message_info:
                # Store in Elasticsearch
                success, failed = await store_messages_elasticsearch(
                    [message_info]
                )

                return {
                    "status": "processed",
                    "message_id": message_data["id"],
                    "channel_id": channel_id,
                    "elasticsearch_success": success,
                    "elasticsearch_failed": failed,
                    "has_media": bool(message_info.image_urls),
                }
            else:
                return {"status": "processing_failed"}

        finally:
            await client.disconnect()

    try:
        return asyncio.run(process_message())
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {"status": "error", "error": str(e)}


@celery_worker.task(name="listener.add_channel", serializer="json")
def add_channel_task(channel_id: int) -> Dict[str, Any]:
    """Add a channel to the monitoring list.

    This task adds a channel ID to the Redis set of monitored channels
    and updates the listener status.

    Args:
        channel_id: The Telegram channel ID to add to monitoring.

    Example:
        add_channel_task.delay(123456)
    """
    try:
        add_monitored_channel(channel_id)

        # Update status
        status = get_listener_status()
        channels = list(get_monitored_channels())
        status.update(
            {"monitored_channels": len(channels), "channels": channels}
        )
        set_listener_status(status)

        return {
            "status": "added",
            "channel_id": channel_id,
            "total_channels": len(channels),
        }
    except Exception as e:
        logger.error(f"Error adding channel {channel_id}: {e}")
        return {"status": "error", "error": str(e)}


@celery_worker.task(name="listener.remove_channel", serializer="json")
def remove_channel_task(channel_id: int) -> Dict[str, Any]:
    """Remove a channel from the monitoring list.

    This task removes a channel ID from the Redis monitored channels
    set and updates the listener status.

    Args:
        channel_id: The Telegram channel ID to remove from monitoring.

    Example:
        remove_channel_task.delay(123456)
    """
    try:
        remove_monitored_channel(channel_id)

        # Update status
        status = get_listener_status()
        channels = list(get_monitored_channels())
        status.update(
            {"monitored_channels": len(channels), "channels": channels}
        )
        set_listener_status(status)

        return {
            "status": "removed",
            "channel_id": channel_id,
            "total_channels": len(channels),
        }
    except Exception as e:
        logger.error(f"Error removing channel {channel_id}: {e}")
        return {"status": "error", "error": str(e)}


@celery_worker.task(name="listener.get_stats", serializer="json")
def get_listener_stats() -> Dict[str, Any]:
    """Get comprehensive listener statistics and status.

    This task retrieves current listener status, monitored channels,
    and operational statistics from Redis.

    Example:
        get_listener_stats.delay()
    """
    try:
        status = get_listener_status()
        channels = get_monitored_channels()

        return {
            "status": status,
            "monitored_channels": list(channels),
            "total_channels": len(channels),
        }
    except Exception as e:
        logger.error(f"Error getting listener stats: {e}")
        return {"status": "error", "error": str(e)}
