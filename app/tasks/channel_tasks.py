import asyncio
import logging
from typing import List, Optional

from celery_worker import celery_worker
from core.config import settings
from core.models import ChannelInfo, ChannelSyncResult
from elasticsearch import AsyncElasticsearch
from services.elasticsearch import (build_channel_query,
                                    execute_elasticsearch_bulk_insert)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel

logger = logging.getLogger(__name__)


async def add_channel_to_es(
    es_client: AsyncElasticsearch, channel: ChannelInfo
) -> bool:
    """Add a single channel to Elasticsearch index.

    This function stores a ChannelInfo object in the Elasticsearch
    channels index with proper error handling.

    Args:
        es_client: Elasticsearch client for database operations.
        channel: ChannelInfo object containing channel data.

    Example:
        success = await add_channel_to_es(es_client, channel_info)
    """
    try:
        doc = {
            "id": channel.id,
            "title": channel.title,
            "messages_count": 0,
            "username": channel.username,
        }
        await es_client.index(index="channels", id=channel.id, body=doc)
        logger.info(f"Added channel {channel.id} to Elasticsearch")
        return True
    except Exception as e:
        logger.error(f"Error adding channel {channel.id}: {e}")
        return False


async def add_bulk_channels(
    es_client: AsyncElasticsearch, channels: List[ChannelInfo]
) -> tuple:
    """Add multiple channels to Elasticsearch using bulk operations.

    This function performs bulk insertion of channel data into Elasticsearch
    for improved performance with large datasets.

    Args:
        es_client: Elasticsearch client for database operations.
        channels: List of ChannelInfo objects to store.

    Example:
        success, failed = await add_bulk_channels(es_client, channel_list)
    """
    if not channels:
        return 0, 0

    actions = []
    for channel in channels:
        actions.append(
            {
                "_index": "channels",
                "_id": channel.id,
                "_source": {
                    "id": channel.id,
                    "title": channel.title,
                    "messages_count": 0,
                    "username": channel.username,
                },
            }
        )

    return await execute_elasticsearch_bulk_insert(es_client, actions)


async def get_channels_from_es(
    es_client: AsyncElasticsearch,
    title_contains: Optional[str] = None,
    username: Optional[str] = None,
    size: Optional[int] = None,
    offset: int = 0,
) -> List[ChannelInfo]:
    """Retrieve channels from Elasticsearch with optional filtering.

    This function searches the Elasticsearch channels index with filter
    criteria and pagination support.

    Args:
        es_client: Elasticsearch client for database operations.
        title_contains: Optional string to filter channels by title content.
        username: Optional string to filter channels by username.
        size: Optional maximum number of channels to return.
        offset: Number of channels to skip for pagination.

    Example:
        channels = await get_channels_from_es(es_client, title_contains="news", size=50)
    """
    if offset < 0:
        raise ValueError("Offset must be a non-negative integer")

    query_body = {
        "query": build_channel_query(title_contains, username),
        "sort": [{"messages_count": {"order": "desc"}}],
        "from": offset,
        "size": size if size is not None else 100,
    }

    try:
        response = await es_client.search(index="channels", body=query_body)
        channels = []

        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            try:
                channel = ChannelInfo(
                    id=source["id"],
                    title=source.get("title"),
                    messages_count=source.get("messages_count"),
                    username=source.get("username"),
                )
                channels.append(channel)
            except Exception as e:
                logger.error(
                    f"Error parsing channel {source.get('id', 'unknown')}: {e}"
                )
                continue

        logger.info(f"Retrieved {len(channels)} channels from Elasticsearch")
        return channels

    except Exception as e:
        logger.error(f"Error querying channels: {e}")
        return []


async def fetch_channel_message_count(
    client: TelegramClient, entity
) -> Optional[int]:
    """Fetch message count for a channel with fallback methods.

    This function attempts to get the total message count for a channel
    using multiple methods with graceful fallback handling.

    Args:
        client: Telegram client for channel operations.
        entity: Telegram channel entity object.

    Example:
        count = await fetch_channel_message_count(client, channel_entity)
    """
    try:
        # Primary method: get latest message ID
        messages = await client.get_messages(entity, limit=1)
        if messages:
            return messages[0].id
    except Exception as e:
        logger.warning(f"Could not get messages for {entity.title}: {e}")

    try:
        # Fallback method: use channel full info
        full_channel = await client(GetFullChannelRequest(entity))
        return full_channel.full_chat.pts
    except Exception as e:
        logger.warning(f"Fallback also failed for {entity.title}: {e}")

    return None


async def read_channels_from_telegram(
    telethon_client: TelegramClient,
) -> List[ChannelInfo]:
    """Read all accessible channels from Telegram.

    This function iterates through Telegram dialogs to discover
    all accessible channels and extract their metadata.

    Args:
        telethon_client: Telegram client for dialog access.

    Example:
        channels = await read_channels_from_telegram(client)
    """
    channels = []

    try:
        async for dialog in telethon_client.iter_dialogs():
            entity = dialog.entity

            if isinstance(entity, Channel):
                message_count = await fetch_channel_message_count(
                    telethon_client, entity
                )

                channel = ChannelInfo(
                    id=entity.id,
                    title=getattr(entity, "title", None),
                    messages_count=message_count,
                    username=getattr(entity, "username", None),
                )
                channels.append(channel)

    except Exception as e:
        logger.error(f"Error reading channels from Telegram: {e}")

    logger.info(f"Retrieved {len(channels)} channels from Telegram")
    return channels


async def sync_channels_async(
    es_client: AsyncElasticsearch,
    telethon_client: TelegramClient,
    task_id: str = "manual",
) -> ChannelSyncResult:
    """Synchronize channels between Telegram and Elasticsearch.

    This function compares channels from both sources and adds
    new channels to Elasticsearch with comprehensive result tracking.

    Args:
        es_client: Elasticsearch client for database operations.
        telethon_client: Telegram client for channel access.
        task_id: Unique identifier for tracking the sync operation.

    Example:
        result = await sync_channels_async(es_client, tg_client, "task-123")
    """
    logger.info(f"[{task_id}] Starting channel sync")

    try:
        # Fetch channels from both sources
        telegram_channels = await read_channels_from_telegram(telethon_client)
        es_channels = await get_channels_from_es(es_client)
        es_channel_ids = {c.id for c in es_channels}

        if not telegram_channels:
            logger.info(f"[{task_id}] No channels found to sync")
            return ChannelSyncResult(
                message="No channels found",
                channels_found=0,
                channels_stored=0,
                channels_failed=0,
                new_channels=0,
                channels=[],
            )

        # Identify new channels
        new_channels = []
        for channel in telegram_channels:
            if channel.id not in es_channel_ids:
                new_channels.append(channel)
                logger.info(
                    f"[{task_id}] New channel found: {channel.title} (ID: {channel.id})"
                )
            else:
                logger.info(
                    f"[{task_id}] Channel already exists: {channel.title} (ID: {channel.id})"
                )

        # Bulk insert new channels
        if new_channels:
            success, failed = await add_bulk_channels(es_client, new_channels)
            logger.info(
                f"[{task_id}] Channel sync completed: {success} succeeded, {failed} failed"
            )
        else:
            success, failed = 0, 0
            logger.info(
                f"[{task_id}] No new channels to add. All channels already exist."
            )

        result = ChannelSyncResult(
            message="Channels synced successfully",
            channels_found=len(telegram_channels),
            channels_stored=success,
            channels_failed=(
                len(failed) if isinstance(failed, list) else failed
            ),
            new_channels=len(new_channels),
            channels=telegram_channels,
        )

        return result
    except Exception as e:
        logger.error(f"[{task_id}] Error during channel sync: {e}")
        return ChannelSyncResult(
            message="Channel sync failed",
            channels_found=0,
            channels_stored=0,
            channels_failed=0,
            new_channels=0,
            channels=[],
            error=str(e),
        )


@celery_worker.task(
    name="telegram.sync_channels", bind=True, serializer="json"
)
def read_and_store_channels(self) -> dict:
    """Celery task wrapper for channel synchronization.

    This Celery task creates fresh client instances and performs
    channel synchronization between Telegram and Elasticsearch.

    Example:
        read_and_store_channels.delay()
    """
    task_id = self.request.id

    async def run_sync():
        # Create fresh client instances inside the task
        es_client = AsyncElasticsearch(settings.elasticsearch_connection_url)
        telethon_client = TelegramClient(
            StringSession(settings.telegram.string_session),
            settings.telegram.api_id,
            settings.telegram.api_hash,
        )

        try:
            # Start the Telegram client
            await telethon_client.start()

            # Run the sync operation
            result = await sync_channels_async(
                es_client, telethon_client, task_id
            )
            return result.model_dump()

        finally:
            # Clean up connections
            await es_client.close()
            await telethon_client.disconnect()

    try:
        return asyncio.run(run_sync())
    except Exception as e:
        logger.error(f"[{task_id}] Error during channel sync: {e}")
        return ChannelSyncResult(
            message="Channel sync failed",
            channels_found=0,
            channels_stored=0,
            channels_failed=0,
            new_channels=0,
            channels=[],
            error=str(e),
        ).model_dump()
