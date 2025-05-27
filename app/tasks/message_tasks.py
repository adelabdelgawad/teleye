import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import pytz
from core.models import MessageInfo
from elasticsearch import AsyncElasticsearch
from services.elasticsearch import build_message_query
from telethon import TelegramClient
from telethon.tl.types import (Message, MessageMediaDocument,
                               MessageMediaPhoto, PeerChannel)

logger = logging.getLogger(__name__)
cairo_tz = pytz.timezone("Africa/Cairo")


async def fetch_messages_from_elasticsearch(
    es_client: AsyncElasticsearch,
    channel_id: Optional[int] = None,
    message_id: Optional[int] = None,
    has_media: Optional[bool] = None,
    title_contains: Optional[str] = None,
    sender_name: Optional[str] = None,
    size: int = 100,
    offset: int = 0,
    index_name: str = "messages",
) -> dict:
    """Fetch messages from Elasticsearch with filtering and pagination.

    This function searches Elasticsearch for messages based on various filter
    criteria and returns them in MessagesResponse format with pagination support.

    Args:
        es_client: Elasticsearch client for database operations.
        channel_id: Optional channel ID to filter messages.
        message_id: Optional specific message ID to fetch.
        has_media: Optional filter for messages with/without media.
        title_contains: Optional text search within message content.
        sender_name: Optional filter by sender name.
        size: Number of messages to return.
        offset: Number of messages to skip for pagination.
        index_name: Elasticsearch index name to search.

    Example:
        messages = await fetch_messages_from_elasticsearch(es_client, channel_id=123, size=50)
    """
    try:
        query = build_message_query(
            channel_id=channel_id,
            message_id=message_id,
            has_media=has_media,
            title_contains=title_contains,
            sender_name=sender_name,
            size=size,
            offset=offset,
        )

        response = await es_client.search(index=index_name, body=query)

        messages = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]

            time = None
            if source.get("time"):
                if isinstance(source["time"], str):
                    time = datetime.fromisoformat(
                        source["time"].replace("Z", "+00:00")
                    )
                else:
                    time = source["time"]

            indexed_at = None
            if source.get("indexed_at"):
                if isinstance(source["indexed_at"], str):
                    indexed_at = datetime.fromisoformat(
                        source["indexed_at"].replace("Z", "+00:00")
                    )
                else:
                    indexed_at = source["indexed_at"]

            message = MessageInfo(
                channel_id=source.get("channel_id"),
                message_id=source.get("message_id"),
                sender_name=source.get("sender_name", ""),
                time=time,
                text=source.get("text", ""),
                images=source.get("images", []),
                image_urls=source.get("image_urls", []),
                images_data=source.get("images_data", []),
                indexed_at=indexed_at,
            )
            messages.append(message)

        # Get total hits count
        total_hits = response["hits"]["total"]
        if isinstance(total_hits, dict):
            total = total_hits.get("value", 0)
        else:
            total = total_hits

        # Calculate if there are more messages
        has_more = (offset + size) < total

        response_channel_id = channel_id if channel_id is not None else 0

        return {
            "messages_count": len(messages),
            "messages": messages,
            "has_more": has_more,
            "channel_id": response_channel_id,
        }

    except Exception as e:
        import logging

        logging.error(f"Error fetching messages from Elasticsearch: {str(e)}")
        raise


async def fetch_messages_from_telegram(
    telethon_client: TelegramClient,
    channel_id: Optional[int] = None,
    message_id: Optional[int] = None,
    has_media: Optional[bool] = None,
    title_contains: Optional[str] = None,
    sender_name: Optional[str] = None,
    size: int = 100,
    offset: int = 0,
    batch_size: int = 1000,
) -> Dict[str, Any]:
    """Fetch messages from Telegram with filtering and pagination.

    This function retrieves messages directly from Telegram using Telethon
    with client-side filtering and pagination support.

    Args:
        telethon_client: Telegram client for message retrieval.
        channel_id: Optional channel ID to fetch messages from.
        message_id: Optional specific message ID to fetch.
        has_media: Optional filter for messages with/without media.
        title_contains: Optional text search within message content.
        sender_name: Optional filter by sender name.
        size: Number of messages to return.
        offset: Number of messages to skip for pagination.
        batch_size: Internal batch size for processing.

    Example:
        messages = await fetch_messages_from_telegram(client, channel_id=123, size=100)
    """
    # Validate parameters
    if not channel_id or channel_id <= 0:
        raise ValueError("channel_id must be a positive integer")
    if size <= 0:
        raise ValueError("size must be positive")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if batch_size <= 0 or batch_size > 1000:
        raise ValueError("batch_size must be between 1 and 1000")

    peer = PeerChannel(channel_id)

    try:
        # Handle specific message ID request
        if message_id is not None:
            try:
                telegram_message = await telethon_client.get_messages(
                    peer, ids=message_id
                )
                if telegram_message:
                    processed_message = convert_telegram_message(
                        telegram_message, channel_id
                    )
                    if processed_message and _message_matches_filters(
                        processed_message,
                        has_media,
                        title_contains,
                        sender_name,
                    ):
                        return {
                            "messages_count": 1,
                            "messages": [processed_message],
                            "has_more": False,
                            "channel_id": channel_id,
                        }

                return {
                    "messages_count": 0,
                    "messages": [],
                    "has_more": False,
                    "channel_id": channel_id,
                }
            except Exception as e:
                logger.error(
                    f"Error fetching specific message {message_id}: {e}"
                )
                raise

        # Fetch messages with pagination and filtering
        all_messages = []
        current_offset = 0
        messages_processed = 0
        messages_skipped = 0

        while len(all_messages) < size:
            messages_to_fetch = min(
                batch_size, size * 3
            )

            telegram_messages = await telethon_client.get_messages(
                peer, limit=messages_to_fetch, offset_id=current_offset
            )

            if not telegram_messages:
                logger.info(
                    f"No more messages available for channel {channel_id}"
                )
                break

            # Process and filter messages
            for tg_msg in telegram_messages:
                processed_message = convert_telegram_message(
                    tg_msg, channel_id
                )
                if not processed_message:
                    continue

                # Apply filters
                if not _message_matches_filters(
                    processed_message, has_media, title_contains, sender_name
                ):
                    continue

                # Handle offset (skip messages)
                if messages_processed < offset:
                    messages_processed += 1
                    messages_skipped += 1
                    continue

                # Add to results if we haven't reached the size limit
                if len(all_messages) < size:
                    all_messages.append(processed_message)
                    messages_processed += 1
                else:
                    break

            # Update offset for next batch
            current_offset = telegram_messages[-1].id

            logger.info(
                f"Processed batch: {len(telegram_messages)} fetched, "
                f"total filtered: {len(all_messages)}, "
                f"skipped: {messages_skipped}"
            )

            # If we got fewer messages than requested, we've reached the end
            if len(telegram_messages) < messages_to_fetch:
                logger.info(
                    f"Reached end of messages for channel {channel_id}"
                )
                break

            # Rate limiting
            await asyncio.sleep(0.1)

        # Check if there are more messages by trying to fetch one more
        has_more = False
        if len(all_messages) == size:
            try:
                next_messages = await telethon_client.get_messages(
                    peer, limit=1, offset_id=current_offset
                )
                has_more = bool(next_messages)
            except:
                has_more = False

        logger.info(
            f"Retrieved {len(all_messages)} messages from channel {channel_id}, "
            f"has_more: {has_more}"
        )

        return {
            "messages_count": len(all_messages),
            "messages": all_messages,
            "has_more": has_more,
            "channel_id": channel_id,
        }

    except Exception as e:
        logger.error(
            f"Error fetching messages from Telegram channel {channel_id}: {e}"
        )
        raise


def convert_telegram_message(
    tg_msg: Message, channel_id: int
) -> Optional[MessageInfo]:
    """Convert Telegram message to MessageInfo format.

    This function transforms a Telegram message object into the standardized
    MessageInfo format used throughout the application.

    Args:
        tg_msg: Telegram message object to convert.
        channel_id: The channel ID containing the message.

    Example:
        msg_info = convert_telegram_message(telegram_message, 123456)
    """
    try:
        # Extract media information
        image_urls = []
        images = []

        if tg_msg.media:
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

        return MessageInfo(
            channel_id=channel_id,
            message_id=tg_msg.id,
            sender_name=sender_name,
            time=tg_msg.date,
            text=tg_msg.text or "",
            images=images,
            image_urls=image_urls,
            images_data=[],
            indexed_at=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Error converting message {tg_msg.id}: {e}")
        return None


def _message_matches_filters(
    message: MessageInfo,
    has_media: Optional[bool] = None,
    title_contains: Optional[str] = None,
    sender_name: Optional[str] = None,
) -> bool:
    """Check if a message matches the given filter criteria.

    This function validates whether a MessageInfo object satisfies
    the specified filter conditions for content and metadata.

    Args:
        message: MessageInfo object to check against filters.
        has_media: Optional filter for messages with/without media.
        title_contains: Optional text search within message content.
        sender_name: Optional filter by sender name.

    Example:
        matches = _message_matches_filters(msg, has_media=True, title_contains="news")
    """
    # Check media filter
    if has_media is not None:
        message_has_media = bool(
            message.image_urls and len(message.image_urls) > 0
        )
        if has_media != message_has_media:
            return False

    # Check text content filter
    if title_contains is not None:
        if (
            not message.text
            or title_contains.lower() not in message.text.lower()
        ):
            return False

    # Check sender name filter
    if sender_name is not None:
        if (
            not message.sender_name
            or sender_name.lower() not in message.sender_name.lower()
        ):
            return False

    return True
