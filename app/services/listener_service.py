import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from core.config import settings
from core.models import MessageInfo
from elasticsearch import AsyncElasticsearch
from redis import Redis
from services.elasticsearch import execute_elasticsearch_bulk_insert
from services.minio_service import MinIOManager
from telethon import TelegramClient
from telethon.tl.types import Channel, MessageMediaDocument, MessageMediaPhoto

logger = logging.getLogger(__name__)

# Redis client for storing listener state
redis_client = Redis.from_url(
    settings.celery_broker_url, decode_responses=True
)

# Redis keys
LISTENER_STATUS_KEY = "listener:status"
MONITORED_CHANNELS_KEY = "listener:channels"
LISTENER_CONFIG_KEY = "listener:config"


def get_listener_status() -> Dict[str, Any]:
    """Get current listener status from Redis.

    This function retrieves the current state of the message listener
    including running status and configuration details.

    Example:
        status = get_listener_status()
        Returns {"is_running": True, "monitored_channels": 5, ...}
    """
    try:
        status_data = redis_client.get(LISTENER_STATUS_KEY)
        if status_data:
            return json.loads(status_data)
        return {
            "is_running": False,
            "download_images": True,
            "monitored_channels": 0,
            "channels": [],
            "started_at": None,
        }
    except Exception as e:
        logger.error(f"Error getting listener status: {e}")
        return {"is_running": False, "error": str(e)}


def set_listener_status(status: Dict[str, Any]):
    """Set listener status in Redis.

    This function stores the current listener state and configuration
    in Redis for persistence across restarts.

    Args:
        status: Dictionary containing listener status and configuration.

    Example:
        set_listener_status({"is_running": True, "channels": [123, 456]})
    """
    try:
        redis_client.set(LISTENER_STATUS_KEY, json.dumps(status))
    except Exception as e:
        logger.error(f"Error setting listener status: {e}")


def get_monitored_channels() -> Set[int]:
    """Get monitored channels from Redis.

    This function retrieves the set of channel IDs currently
    being monitored by the listener.

    Example:
        channels = get_monitored_channels()
        Returns {123, 456, 789}
    """
    try:
        channels = redis_client.smembers(MONITORED_CHANNELS_KEY)
        return {int(ch) for ch in channels}
    except Exception as e:
        logger.error(f"Error getting monitored channels: {e}")
        return set()


def add_monitored_channel(channel_id: int):
    """Add channel to monitoring.

    This function adds a channel ID to the set of monitored channels
    stored in Redis.

    Args:
        channel_id: The Telegram channel ID to add to monitoring.

    Example:
        add_monitored_channel(123456)
    """
    try:
        redis_client.sadd(MONITORED_CHANNELS_KEY, channel_id)
    except Exception as e:
        logger.error(f"Error adding monitored channel: {e}")


def remove_monitored_channel(channel_id: int):
    """Remove channel from monitoring.

    This function removes a channel ID from the monitored channels
    set in Redis.

    Args:
        channel_id: The Telegram channel ID to remove from monitoring.

    Example:
        remove_monitored_channel(123456)
    """
    try:
        redis_client.srem(MONITORED_CHANNELS_KEY, channel_id)
    except Exception as e:
        logger.error(f"Error removing monitored channel: {e}")


def clear_monitored_channels():
    """Clear all monitored channels.

    This function removes all channels from the monitoring list
    in Redis.

    Example:
        clear_monitored_channels()
    """
    try:
        redis_client.delete(MONITORED_CHANNELS_KEY)
    except Exception as e:
        logger.error(f"Error clearing monitored channels: {e}")


async def discover_channels(client: TelegramClient) -> List[int]:
    """Discover all accessible channels.

    This function iterates through all dialogs to find accessible
    channels and automatically adds them to monitoring.

    Args:
        client: Telegram client for accessing dialogs.

    Example:
        channels = await discover_channels(client)
        Returns [123, 456, 789]
    """
    try:
        channels = []
        async for dialog in client.iter_dialogs():
            if isinstance(dialog.entity, Channel):
                channels.append(dialog.entity.id)
                add_monitored_channel(dialog.entity.id)

        logger.info(f"Discovered {len(channels)} channels")
        return channels
    except Exception as e:
        logger.error(f"Error discovering channels: {e}")
        return []


async def process_single_message(
    message,
    channel_id: int,
    client: TelegramClient,
    download_images: bool = True,
    minio_manager: Optional[MinIOManager] = None,
) -> Optional[MessageInfo]:
    """Process a single message.

    This function processes a Telegram message, extracts metadata,
    and optionally downloads media content to MinIO storage.

    Args:
        message: Telegram message object to process.
        channel_id: The channel ID containing the message.
        client: Telegram client for media downloads.
        download_images: Whether to download and store images.
        minio_manager: Optional MinIO manager for image storage.

    Example:
        msg_info = await process_single_message(message, 123, client, True, minio)
    """
    try:
        # Get sender name
        sender_name = ""
        if message.sender:
            if hasattr(message.sender, "first_name"):
                sender_name = message.sender.first_name or ""
                if (
                    hasattr(message.sender, "last_name")
                    and message.sender.last_name
                ):
                    sender_name += f" {message.sender.last_name}"
            elif hasattr(message.sender, "title"):
                sender_name = message.sender.title or ""
            elif hasattr(message.sender, "username"):
                sender_name = message.sender.username or ""

        # Initialize media fields
        image_urls = []
        images = []

        # Process media if download_images is enabled
        if download_images and message.media and minio_manager:
            if isinstance(
                message.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                try:
                    # Download media
                    media_bytes = await client.download_media(
                        message.media, file=bytes
                    )

                    if media_bytes:
                        # Determine file extension and content type
                        file_extension = "jpg"
                        content_type = "image/jpeg"

                        if isinstance(message.media, MessageMediaDocument):
                            if message.media.document.mime_type:
                                mime_type = message.media.document.mime_type
                                if "png" in mime_type:
                                    file_extension = "png"
                                    content_type = "image/png"
                                elif "gif" in mime_type:
                                    file_extension = "gif"
                                    content_type = "image/gif"
                                elif "webp" in mime_type:
                                    file_extension = "webp"
                                    content_type = "image/webp"

                        object_name = f"channel_{channel_id}/message_{message.id}.{file_extension}"

                        # Upload to MinIO
                        minio_url = minio_manager.upload_image(
                            media_bytes, object_name, content_type
                        )

                        image_urls.append(minio_url)
                        images.append(object_name)

                        logger.debug(
                            f"Downloaded and stored media for message {message.id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error downloading media for message {message.id}: {e}"
                    )

        elif message.media:
            # Just note media presence without downloading
            if isinstance(
                message.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                if hasattr(message.media, "photo") and message.media.photo:
                    image_urls.append(
                        f"telegram_photo_{message.media.photo.id}"
                    )
                elif (
                    hasattr(message.media, "document")
                    and message.media.document
                ):
                    if (
                        message.media.document.mime_type
                        and message.media.document.mime_type.startswith(
                            "image/"
                        )
                    ):
                        image_urls.append(
                            f"telegram_document_{message.media.document.id}"
                        )

        return MessageInfo(
            channel_id=channel_id,
            message_id=message.id,
            sender_name=sender_name,
            time=message.date,
            text=message.text or "",
            images=images,
            image_urls=image_urls,
            images_data=[],
            indexed_at=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Error processing message {message.id}: {e}")
        return None


async def store_messages_elasticsearch(messages: List[MessageInfo]):
    """Store messages in Elasticsearch.

    This function performs bulk insertion of processed messages
    into Elasticsearch with proper error handling.

    Args:
        messages: List of MessageInfo objects to store.

    Example:
        success, failed = await store_messages_elasticsearch(messages)
    """
    try:
        es_client = AsyncElasticsearch(settings.elasticsearch_connection_url)

        try:
            actions = []
            for message in messages:
                message_dict = message.model_dump()
                message_dict.pop("images_data", None)

                actions.append(
                    {
                        "_index": "messages",
                        "_id": f"{message.channel_id}_{message.message_id}",
                        "_source": message_dict,
                    }
                )

            success, failed = await execute_elasticsearch_bulk_insert(
                es_client, actions
            )

            logger.info(f"Stored {success} messages, {failed} failed")
            return success, failed

        finally:
            await es_client.close()

    except Exception as e:
        logger.error(f"Error storing messages in Elasticsearch: {e}")
        return 0, len(messages)


async def process_single_message_enhanced(
    message,
    channel_id: int,
    client: TelegramClient,
    download_images: bool = True,
    minio_manager: Optional[MinIOManager] = None,
) -> Optional[MessageInfo]:
    """Process a single message with enhanced sender handling.

    This function processes messages with improved sender entity resolution
    and fallback mechanisms for better reliability.

    Args:
        message: Telegram message object to process.
        channel_id: The channel ID containing the message.
        client: Telegram client for operations.
        download_images: Whether to download and store images.
        minio_manager: Optional MinIO manager for image storage.

    Example:
        msg_info = await process_single_message_enhanced(message, 123, client)
    """
    try:
        # Get sender name with proper entity handling
        sender_name = ""

        # Try different approaches to get sender information
        try:
            # Method 1: Use message.sender if available
            if message.sender:
                if hasattr(message.sender, "first_name"):
                    sender_name = message.sender.first_name or ""
                    if (
                        hasattr(message.sender, "last_name")
                        and message.sender.last_name
                    ):
                        sender_name += f" {message.sender.last_name}"
                elif hasattr(message.sender, "title"):
                    sender_name = message.sender.title or ""
                elif hasattr(message.sender, "username"):
                    sender_name = message.sender.username or ""

            # Method 2: If sender is None, try to get it safely
            elif message.sender_id:
                try:
                    # Try to get sender entity
                    sender = await client.get_entity(message.sender_id)
                    if hasattr(sender, "first_name"):
                        sender_name = sender.first_name or ""
                        if hasattr(sender, "last_name") and sender.last_name:
                            sender_name += f" {sender.last_name}"
                    elif hasattr(sender, "title"):
                        sender_name = sender.title or ""
                    elif hasattr(sender, "username"):
                        sender_name = sender.username or ""
                except Exception as entity_error:
                    # If we can't get the sender entity, use a fallback
                    logger.warning(
                        f"Could not get sender entity for message {message.id}: {entity_error}"
                    )
                    sender_name = (
                        f"User_{message.sender_id}"
                        if message.sender_id
                        else "Unknown"
                    )
            else:
                sender_name = "Unknown"

        except Exception as sender_error:
            logger.warning(
                f"Error getting sender info for message {message.id}: {sender_error}"
            )
            sender_name = "Unknown"

        # Initialize media fields
        image_urls = []
        images = []

        # Process media if download_images is enabled
        if download_images and message.media and minio_manager:
            if isinstance(
                message.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                try:
                    # Download media
                    media_bytes = await client.download_media(
                        message.media, file=bytes
                    )

                    if media_bytes:
                        # Determine file extension and content type
                        file_extension = "jpg"
                        content_type = "image/jpeg"

                        if isinstance(message.media, MessageMediaDocument):
                            if message.media.document.mime_type:
                                mime_type = message.media.document.mime_type
                                if "png" in mime_type:
                                    file_extension = "png"
                                    content_type = "image/png"
                                elif "gif" in mime_type:
                                    file_extension = "gif"
                                    content_type = "image/gif"
                                elif "webp" in mime_type:
                                    file_extension = "webp"
                                    content_type = "image/webp"

                        object_name = f"channel_{channel_id}/message_{message.id}.{file_extension}"

                        # Upload to MinIO
                        minio_url = minio_manager.upload_image(
                            media_bytes, object_name, content_type
                        )

                        image_urls.append(minio_url)
                        images.append(object_name)

                        logger.debug(
                            f"Downloaded and stored media for message {message.id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error downloading media for message {message.id}: {e}"
                    )

        elif message.media:
            # Just note media presence without downloading
            if isinstance(
                message.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                if hasattr(message.media, "photo") and message.media.photo:
                    image_urls.append(
                        f"telegram_photo_{message.media.photo.id}"
                    )
                elif (
                    hasattr(message.media, "document")
                    and message.media.document
                ):
                    if (
                        message.media.document.mime_type
                        and message.media.document.mime_type.startswith(
                            "image/"
                        )
                    ):
                        image_urls.append(
                            f"telegram_document_{message.media.document.id}"
                        )

        return MessageInfo(
            channel_id=channel_id,
            message_id=message.id,
            sender_name=sender_name,
            time=message.date,
            text=message.text or "",
            images=images,
            image_urls=image_urls,
            images_data=[],
            indexed_at=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Error processing message {message.id}: {e}")
        return None
