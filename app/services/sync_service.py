import logging
from datetime import datetime
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import (Message, MessageMediaDocument,
                               MessageMediaPhoto)

from core.models import MessageInfo
from services.minio_service import MinIOManager

logger = logging.getLogger(__name__)


async def process_message(
    tg_msg: Message,
    channel_id: int,
    client: TelegramClient,
    sync_images: bool = False,
    minio_manager: MinIOManager = None,
) -> Optional[MessageInfo]:
    """Process a Telegram message with optional media download.

    This function converts a Telegram message to MessageInfo format,
    extracting metadata and optionally downloading media to MinIO storage.

    Args:
        tg_msg: Telegram message object to process.
        channel_id: The channel ID containing the message.
        client: Telegram client for media downloads.
        sync_images: Whether to download and store images.
        minio_manager: MinIO manager for image storage operations.

    Example:
        msg_info = await process_message(telegram_msg, 123, client, True, minio)
    """
    try:
        # Get sender name
        sender_name = ""
        if tg_msg.sender:
            if hasattr(tg_msg.sender, "first_name"):
                sender_name = tg_msg.sender.first_name or ""
                if (
                    hasattr(tg_msg.sender, "last_name")
                    and tg_msg.sender.last_name
                ):
                    sender_name += f" {tg_msg.sender.last_name}"
            elif hasattr(tg_msg.sender, "title"):
                sender_name = tg_msg.sender.title or ""
            elif hasattr(tg_msg.sender, "username"):
                sender_name = tg_msg.sender.username or ""

        # Initialize media fields
        image_urls = []
        images = []
        images_data = []

        # Process media if sync_images is enabled and media is present
        if sync_images and tg_msg.media and minio_manager:
            if isinstance(
                tg_msg.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                try:
                    # Download media
                    media_bytes = await client.download_media(
                        tg_msg.media, file=bytes
                    )

                    if media_bytes:
                        # Determine file extension and content type
                        file_extension = "jpg"
                        content_type = "image/jpeg"

                        if isinstance(tg_msg.media, MessageMediaDocument):
                            if tg_msg.media.document.mime_type:
                                mime_type = tg_msg.media.document.mime_type
                                if "png" in mime_type:
                                    file_extension = "png"
                                    content_type = "image/png"
                                elif "gif" in mime_type:
                                    file_extension = "gif"
                                    content_type = "image/gif"
                                elif "webp" in mime_type:
                                    file_extension = "webp"
                                    content_type = "image/webp"

                        object_name = f"channel_{channel_id}/message_{tg_msg.id}.{file_extension}"

                        # Upload to MinIO and get accessible URL
                        minio_url = minio_manager.upload_image(
                            media_bytes, object_name, content_type
                        )

                        # Store data
                        image_urls.append(minio_url)
                        images.append(object_name)
                        images_data.append(media_bytes)

                        logger.info(
                            f"Downloaded and stored media for message {tg_msg.id} at {minio_url}"
                        )

                except Exception as e:
                    logger.error(
                        f"Error downloading media for message {tg_msg.id}: {e}"
                    )
                    raise
        elif not sync_images and tg_msg.media:
            # If not syncing images but media exists, just note the media presence
            if isinstance(
                tg_msg.media, (MessageMediaPhoto, MessageMediaDocument)
            ):
                if hasattr(tg_msg.media, "photo") and tg_msg.media.photo:
                    image_urls.append(
                        f"telegram_photo_{tg_msg.media.photo.id}"
                    )
                elif (
                    hasattr(tg_msg.media, "document") and tg_msg.media.document
                ):
                    if (
                        tg_msg.media.document.mime_type
                        and tg_msg.media.document.mime_type.startswith(
                            "image/"
                        )
                    ):
                        image_urls.append(
                            f"telegram_document_{tg_msg.media.document.id}"
                        )

        return MessageInfo(
            channel_id=channel_id,
            message_id=tg_msg.id,
            sender_name=sender_name,
            time=tg_msg.date,
            text=tg_msg.text or "",
            images=images,
            image_urls=image_urls,
            images_data=images_data if sync_images else [],
            indexed_at=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Error processing message {tg_msg.id}: {e}")
        return None
