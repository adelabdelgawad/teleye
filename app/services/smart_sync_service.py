import asyncio
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import AsyncElasticsearch
from services.elasticsearch import execute_elasticsearch_bulk_insert
from services.minio_service import MinIOManager
from services.sync_service import process_message
from telethon import TelegramClient
from telethon.tl.types import Channel, PeerChannel

logger = logging.getLogger(__name__)


async def get_last_message_id_telegram(
    telethon_client: TelegramClient, channel_id: int
) -> Optional[int]:
    """Get last message ID from Telegram.

    This function retrieves the most recent message ID from a Telegram
    channel to determine sync boundaries.

    Args:
        telethon_client: Telegram client for channel access.
        channel_id: The Telegram channel ID to query.

    Example:
        last_id = await get_last_message_id_telegram(client, 123456)
    """
    try:
        peer = PeerChannel(channel_id)
        latest_messages = await telethon_client.get_messages(peer, limit=1)

        if not latest_messages:
            return None

        return latest_messages[0].id

    except Exception as e:
        logger.error(
            f"Error getting last message ID from Telegram for channel {channel_id}: {e}"
        )
        return None


async def get_last_message_id_elasticsearch(
    es_client: AsyncElasticsearch, channel_id: int
) -> Optional[int]:
    """Get last message ID from Elasticsearch.

    This function retrieves the highest message ID stored in Elasticsearch
    for a specific channel.

    Args:
        es_client: Elasticsearch client for database queries.
        channel_id: The channel ID to query.

    Example:
        last_id = await get_last_message_id_elasticsearch(es_client, 123456)
    """
    try:
        query = {
            "query": {"term": {"channel_id": channel_id}},
            "sort": [{"message_id": {"order": "desc"}}],
            "size": 1,
            "_source": ["message_id"],
        }

        response = await es_client.search(index="messages", body=query)

        if response["hits"]["hits"]:
            return response["hits"]["hits"][0]["_source"]["message_id"]

        return None

    except Exception as e:
        logger.error(
            f"Error getting last message ID from Elasticsearch for channel {channel_id}: {e}"
        )
        return None


async def sync_missing_messages(
    telethon_client: TelegramClient,
    es_client: AsyncElasticsearch,
    channel_id: int,
    after_message_id: int,
    sync_images: bool = False,
    minio_manager: Optional[MinIOManager] = None,
) -> Dict[str, Any]:
    """Sync messages between after_message_id and target_message_id.

    This function fetches and processes messages from Telegram within
    a specific ID range and stores them in Elasticsearch.

    Args:
        telethon_client: Telegram client for message retrieval.
        es_client: Elasticsearch client for storage.
        channel_id: The channel ID to sync.
        after_message_id: Starting message ID (exclusive).
        sync_images: Whether to download and store images.
        minio_manager: Optional MinIO manager for image storage.

    Example:
        result = await sync_missing_messages(tg_client, es_client, 123, 100, 200)
    """
    try:
        peer = PeerChannel(channel_id)
        processed_messages = []
        images_downloaded = 0
        images_failed = 0

        # Get messages starting from target and work backwards until we reach after_message_id
        offset_id = 0
        found_cutoff = False

        while not found_cutoff:
            telegram_messages = await telethon_client.get_messages(
                peer, limit=100, offset_id=offset_id
            )

            if not telegram_messages:
                break

            for tg_msg in telegram_messages:
                if tg_msg.id <= after_message_id:
                    found_cutoff = True
                    break

                # Process this message
                try:
                    message_info = await process_message(
                        tg_msg,
                        channel_id,
                        telethon_client,
                        sync_images=sync_images,
                        minio_manager=minio_manager,
                    )

                    if message_info:
                        processed_messages.append(message_info)

                        if sync_images and message_info.image_urls:
                            images_downloaded += len(message_info.image_urls)

                except Exception as e:
                    logger.error(f"Error processing message {tg_msg.id}: {e}")
                    if sync_images:
                        images_failed += 1
                    continue

            if not found_cutoff and telegram_messages:
                offset_id = telegram_messages[-1].id

            await asyncio.sleep(0.1)

        # Bulk insert to Elasticsearch
        elasticsearch_success = 0
        elasticsearch_failed = 0

        if processed_messages:
            actions = []
            for message in processed_messages:
                message_dict = message.model_dump()
                message_dict.pop("images_data", None)

                actions.append(
                    {
                        "_index": "messages",
                        "_id": f"{message.channel_id}_{message.message_id}",
                        "_source": message_dict,
                    }
                )

            elasticsearch_success, elasticsearch_failed = (
                await execute_elasticsearch_bulk_insert(es_client, actions)
            )

        return {
            "messages_processed": len(processed_messages),
            "images_downloaded": images_downloaded,
            "images_failed": images_failed,
            "elasticsearch_success": elasticsearch_success,
            "elasticsearch_failed": elasticsearch_failed,
        }

    except Exception as e:
        logger.error(
            f"Error syncing missing messages for channel {channel_id}: {e}"
        )
        raise


async def smart_sync_channel(
    channel_id: int,
    telethon_client: TelegramClient,
    es_client: AsyncElasticsearch,
    sync_images: bool = False,
    minio_manager: Optional[MinIOManager] = None,
) -> Dict[str, Any]:
    """Simplified smart sync logic - only compare last message IDs.

    This function intelligently determines the sync strategy by comparing
    last message IDs between Telegram and Elasticsearch.

    Args:
        channel_id: The channel ID to sync.
        telethon_client: Telegram client for operations.
        es_client: Elasticsearch client for storage.
        sync_images: Whether to download and store images.
        minio_manager: Optional MinIO manager for image storage.

    Example:
        result = await smart_sync_channel(123, tg_client, es_client, True)
    """
    logger.info(f"Starting smart sync for channel {channel_id}")

    try:
        # Get last message IDs from both sources
        tg_last_id = await get_last_message_id_telegram(
            telethon_client, channel_id
        )
        es_last_id = await get_last_message_id_elasticsearch(
            es_client, channel_id
        )

        logger.info(
            f"Channel {channel_id} - TG last ID: {tg_last_id}, ES last ID: {es_last_id}"
        )

        # If Telegram channel is not accessible
        if tg_last_id is None:
            return {
                "channel_id": channel_id,
                "action": "skip",
                "reason": "Channel not accessible on Telegram",
                "success": False,
            }

        # If no data in Elasticsearch, sync from beginning
        if es_last_id is None:
            logger.info(
                f"Channel {channel_id}: No data in ES, performing sync"
            )
            sync_result = await sync_missing_messages(
                telethon_client,
                es_client,
                channel_id,
                0,
                sync_images,
                minio_manager,
            )
            return {
                "channel_id": channel_id,
                "action": "full_sync",
                "reason": "No data in Elasticsearch",
                "success": True,
                **sync_result,
            }

        # If last message IDs are equal, do nothing
        if tg_last_id == es_last_id:
            logger.info(
                f"Channel {channel_id}: Last message IDs are equal, skipping"
            )
            return {
                "channel_id": channel_id,
                "action": "skip",
                "reason": "Last message IDs are equal",
                "success": True,
                "messages_processed": 0,
            }

        # If Telegram has newer messages, sync the missing ones
        if tg_last_id > es_last_id:
            logger.info(
                f"Channel {channel_id}: Syncing messages after {es_last_id} up to {tg_last_id}"
            )
            sync_result = await sync_missing_messages(
                telethon_client,
                es_client,
                channel_id,
                es_last_id,
                sync_images,
                minio_manager,
            )
            return {
                "channel_id": channel_id,
                "action": "incremental_sync",
                "reason": f"Synced messages from {es_last_id + 1} to {tg_last_id}",
                "success": True,
                **sync_result,
            }

        # If Elasticsearch has a higher ID than Telegram (shouldn't happen normally)
        if es_last_id > tg_last_id:
            logger.warning(
                f"Channel {channel_id}: ES has higher message ID than TG, skipping"
            )
            return {
                "channel_id": channel_id,
                "action": "skip",
                "reason": "Elasticsearch has higher message ID than Telegram",
                "success": True,
                "messages_processed": 0,
            }

    except Exception as e:
        logger.error(f"Error in smart sync for channel {channel_id}: {e}")
        return {
            "channel_id": channel_id,
            "action": "error",
            "reason": str(e),
            "success": False,
        }


async def get_all_telegram_channels(
    telethon_client: TelegramClient,
) -> List[int]:
    """Get all accessible channel IDs from Telegram.

    This function discovers all channels accessible through the
    Telegram client by iterating through dialogs.

    Args:
        telethon_client: Telegram client for dialog access.

    Example:
        channels = await get_all_telegram_channels(client)
        Returns [123, 456, 789]
    """
    channel_ids = []
    try:
        async for dialog in telethon_client.iter_dialogs():
            if isinstance(dialog.entity, Channel):
                channel_ids.append(dialog.entity.id)

        logger.info(f"Found {len(channel_ids)} channels in Telegram")
        return channel_ids

    except Exception as e:
        logger.error(f"Error getting channels from Telegram: {e}")
        return []


async def get_elasticsearch_channel_stats(
    es_client: AsyncElasticsearch, channel_id: int
) -> Dict[str, Any]:
    """Get channel statistics from Elasticsearch.

    This function retrieves comprehensive statistics about a channel
    stored in Elasticsearch including message counts and last message ID.

    Args:
        es_client: Elasticsearch client for queries.
        channel_id: The channel ID to analyze.

    Example:
        stats = await get_elasticsearch_channel_stats(es_client, 123)
        Returns {"total_messages": 1000, "last_message_id": 500}
    """
    try:
        # Get total message count
        count_query = {"query": {"term": {"channel_id": channel_id}}}

        count_response = await es_client.count(
            index="messages", body=count_query
        )
        total_messages = count_response.get("count", 0)

        # Get last message ID
        last_message_query = {
            "query": {"term": {"channel_id": channel_id}},
            "sort": [{"message_id": {"order": "desc"}}],
            "size": 1,
            "_source": ["message_id"],
        }

        last_message_response = await es_client.search(
            index="messages", body=last_message_query
        )

        last_message_id = None
        if last_message_response["hits"]["hits"]:
            last_message_id = last_message_response["hits"]["hits"][0][
                "_source"
            ]["message_id"]

        return {
            "total_messages": total_messages,
            "last_message_id": last_message_id,
            "has_data": total_messages > 0,
        }

    except Exception as e:
        logger.error(
            f"Error getting Elasticsearch stats for channel {channel_id}: {e}"
        )
        return {
            "total_messages": 0,
            "last_message_id": None,
            "has_data": False,
        }


async def get_telegram_channel_stats(
    telethon_client: TelegramClient, channel_id: int
) -> Optional[Dict[str, Any]]:
    """Get channel statistics from Telegram.

    This function retrieves channel statistics directly from Telegram
    including accessibility status and message counts.

    Args:
        telethon_client: Telegram client for channel access.
        channel_id: The channel ID to analyze.

    Example:
        stats = await get_telegram_channel_stats(client, 123)
        Returns {"total_messages": 1000, "channel_accessible": True}
    """
    try:
        peer = PeerChannel(channel_id)

        # Get latest message to determine total count and last message ID
        latest_messages = await telethon_client.get_messages(peer, limit=1)

        if not latest_messages:
            return {
                "total_messages": 0,
                "last_message_id": None,
                "channel_accessible": True,
            }

        latest_message = latest_messages[0]

        return {
            "total_messages": latest_message.id,
            "last_message_id": latest_message.id,
            "channel_accessible": True,
        }

    except Exception as e:
        logger.error(
            f"Error getting Telegram stats for channel {channel_id}: {e}"
        )
        return None
