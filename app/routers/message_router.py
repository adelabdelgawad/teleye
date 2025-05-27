import logging

import redis
from fastapi import APIRouter, HTTPException, Query

from core.models import MessagesResponse
from services.dependancies import CurrentUserDep, ElasticsearchDep, TelethonDep
from tasks.message_tasks import (
    fetch_messages_from_elasticsearch,
    fetch_messages_from_telegram,
)

logger = logging.getLogger(__name__)

router = APIRouter()
redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)


@router.get("/elasticsearch", response_model=MessagesResponse)
async def get_messages_from_elasticsearch(
    user: CurrentUserDep,
    es_client: ElasticsearchDep,
    channel_id: int | None = Query(
        None, description="Channel ID to filter messages"
    ),
    message_id: int | None = Query(
        None, description="Specific message ID to fetch"
    ),
    has_media: bool | None = Query(
        None, description="Filter messages with/without media"
    ),
    title_contains: str | None = Query(
        None, description="Search text within message content", max_length=200
    ),
    sender_name: str | None = Query(
        None, description="Filter by sender name", max_length=100
    ),
    size: int = Query(
        100, ge=1, le=1000, description="Number of messages to return"
    ),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
):
    """Retrieve messages from Elasticsearch with filtering and pagination.

    This endpoint searches for messages in Elasticsearch based on various filter criteria
    with support for pagination and full-text search.

    Args:
        es_client: Elasticsearch client dependency for database operations.
        channel_id: Optional channel ID to filter messages.
        message_id: Optional specific message ID to fetch.
        has_media: Optional filter for messages with/without media.
        title_contains: Optional text search within message content.
        sender_name: Optional filter by sender name.
        size: Number of messages to return (1-1000).
        offset: Number of messages to skip for pagination.

    Example:
        GET /elasticsearch?channel_id=123&has_media=true&size=50
        Returns 50 messages with media from channel 123.
    """
    try:
        # Fetch messages
        result = await fetch_messages_from_elasticsearch(
            es_client,
            channel_id=channel_id,
            message_id=message_id,
            has_media=has_media,
            title_contains=title_contains,
            sender_name=sender_name,
            size=size,
            offset=offset,
        )

        logger.info(
            f"Retrieved {result["messages_count"]} messages from Elasticsearch"
        )

        return MessagesResponse(**result)

    except ValueError as e:
        logger.error(f"Validation error in Elasticsearch query: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving messages from Elasticsearch: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve messages: {e}"
        )


@router.get("/telegram/{channel_id}", response_model=MessagesResponse)
async def get_channel_messages_from_telegram(
    user: CurrentUserDep,
    telethon_client: TelethonDep,
    channel_id: int,
    size: int | None = Query(
        100, ge=1, le=1000, description="Number of messages to return"
    ),
    offset: int | None = Query(
        0, ge=0, description="Number of messages to skip"
    ),
    batch_size: int | None = Query(
        1000, ge=100, le=5000, description="Internal batch processing size"
    ),
):
    """Retrieve messages from a specific Telegram channel using Telethon.

    This endpoint fetches messages directly from Telegram using the Telethon client
    with pagination and batch processing support.

    Args:
        telethon_client: Telethon client dependency for Telegram operations.
        channel_id: The Telegram channel ID to fetch messages from.
        size: Number of messages to return (1-1000).
        offset: Number of messages to skip for pagination.
        batch_size: Internal batch size for processing (100-5000).

    Example:
        GET /telegram/123456?size=100&offset=0&batch_size=1000
        Returns 100 messages from channel 123456.
    """
    try:
        # Validate parameters
        if size is None:
            size = 100
        if offset is None:
            offset = 0
        if batch_size is None:
            batch_size = 1000

        if size <= 0:
            raise ValueError("Size must be greater than 0")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        if batch_size < 100:
            raise ValueError("Batch size must be at least 100")

        logger.info(
            f"Fetching messages from Telegram channel {channel_id}: "
            f"size={size}, offset={offset}, batch_size={batch_size}"
        )

        # Fetch messages using Telethon
        result = await fetch_messages_from_telegram(
            telethon_client=telethon_client,
            channel_id=channel_id,
            size=size,
            offset=offset,
            batch_size=batch_size,
        )

        logger.info(
            f"Successfully retrieved {result['messages_count']} messages "
            f"from Telegram channel {channel_id}"
        )

        return MessagesResponse(**result)

    except ValueError as e:
        logger.error(f"Validation error for channel {channel_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"Error retrieving messages from Telegram channel {channel_id}: {e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve messages from Telegram channel {channel_id}: {str(e)}",
        )
