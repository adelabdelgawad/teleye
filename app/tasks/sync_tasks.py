import asyncio
import logging
from typing import Any, Dict, List

from celery import Task
from celery_worker import celery_worker
from core.config import settings
from elasticsearch import AsyncElasticsearch
from services.elasticsearch import execute_elasticsearch_bulk_insert
from services.minio_service import MinIOManager
from services.sync_service import process_message
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

logger = logging.getLogger(__name__)


class SyncTask(Task):
    """Custom task class with progress tracking"""

    def update_progress(self, current: int, total: int, status: str):
        """Update task progress with current status and percentage.

        This method updates the Celery task state with progress information
        including current position, total items, and status message.

        Args:
            current: Current number of processed items.
            total: Total number of items to process.
            status: Current status message describing the operation.

        Example:
            self.update_progress(50, 100, "Processing messages")
        """
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "status": status,
                "percentage": int((current / total) * 100) if total > 0 else 0,
            },
        )


@celery_worker.task(
    name="sync.channel_messages", bind=True, base=SyncTask, serializer="json"
)
def sync_channel_messages_task(
    self,
    channel_id: int,
    sync_chat: bool = True,
    sync_images: bool = False,
    size: int = 100,
    offset: int = 0,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """Sync messages from Telegram channel with progress tracking.

    This Celery task fetches messages from a Telegram channel and stores them
    in Elasticsearch with optional image downloading to MinIO storage.

    Args:
        channel_id: The Telegram channel ID to synchronize.
        sync_chat: Whether to sync chat messages to Elasticsearch.
        sync_images: Whether to download and store images to MinIO.
        size: Number of messages to process.
        offset: Number of messages to skip for pagination.
        batch_size: Batch size for processing messages.

    Example:
        sync_channel_messages_task.delay(123456, sync_chat=True, size=100)
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting sync for channel {channel_id}")

    async def run_sync():
        # Create fresh client instances
        es_client = AsyncElasticsearch(settings.elasticsearch_connection_url)
        telethon_client = TelegramClient(
            StringSession(settings.telegram.string_session),
            settings.telegram.api_id,
            settings.telegram.api_hash,
        )

        # Initialize MinIO if needed
        minio_manager = None
        if sync_images:
            minio_manager = MinIOManager(
                endpoint=settings.minio.endpoint,
                access_key=settings.minio.root_user,
                secret_key=settings.minio.root_password,
                secure=settings.minio.secure,
            )

        try:
            await telethon_client.start()

            # Validate parameters
            if not sync_chat and not sync_images:
                raise ValueError(
                    "At least one of sync_chat or sync_images must be True"
                )

            peer = PeerChannel(channel_id)
            processed_messages = []
            images_downloaded = 0
            images_failed = 0
            current_offset = 0

            # Update initial progress
            self.update_progress(
                0, size, f"Starting sync for channel {channel_id}"
            )

            # Skip messages based on offset
            if offset > 0:
                skip_messages = await telethon_client.get_messages(
                    peer, limit=offset
                )
                if skip_messages:
                    current_offset = skip_messages[-1].id
                self.update_progress(0, size, f"Skipped {offset} messages")

            # Process messages in batches
            while len(processed_messages) < size:
                messages_to_fetch = min(
                    batch_size, size - len(processed_messages)
                )

                telegram_messages = await telethon_client.get_messages(
                    peer, limit=messages_to_fetch, offset_id=current_offset
                )

                if not telegram_messages:
                    logger.info(f"[{task_id}] No more messages available")
                    break

                # Process each message
                for tg_msg in telegram_messages:
                    if len(processed_messages) >= size:
                        break

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
                                images_downloaded += len(
                                    message_info.image_urls
                                )

                        # Update progress
                        current_progress = len(processed_messages)
                        self.update_progress(
                            current_progress,
                            size,
                            f"Processed {current_progress}/{size} messages",
                        )

                    except Exception as e:
                        logger.error(
                            f"[{task_id}] Error processing message {tg_msg.id}: {e}"
                        )
                        if sync_images:
                            images_failed += 1
                        continue

                # Update offset
                if telegram_messages:
                    current_offset = telegram_messages[-1].id

                # Rate limiting
                await asyncio.sleep(0.2)

                # Break if fewer messages than requested
                if len(telegram_messages) < messages_to_fetch:
                    break

            # Bulk insert to Elasticsearch if sync_chat is enabled
            elasticsearch_success = 0
            elasticsearch_failed = 0

            if sync_chat and processed_messages:
                actions = []
                for message in processed_messages:
                    # Create a copy of the message data without images_data
                    message_dict = message.model_dump()
                    # Remove binary data before storing in Elasticsearch
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
                logger.info(
                    f"[{task_id}] Elasticsearch: {elasticsearch_success} succeeded, "
                    f"{elasticsearch_failed} failed"
                )

            # Final progress update
            self.update_progress(
                len(processed_messages), size, "Sync completed successfully"
            )

            return {
                "channel_id": channel_id,
                "sync_chat": sync_chat,
                "sync_images": sync_images,
                "messages_processed": len(processed_messages),
                "chat_messages_stored": (
                    elasticsearch_success if sync_chat else 0
                ),
                "images_downloaded": images_downloaded if sync_images else 0,
                "images_failed": images_failed if sync_images else 0,
                "elasticsearch_success": elasticsearch_success,
                "elasticsearch_failed": elasticsearch_failed,
                "has_more": len(processed_messages) == size,
                "task_id": task_id,
            }

        finally:
            await es_client.close()
            await telethon_client.disconnect()

    try:
        return asyncio.run(run_sync())
    except Exception as e:
        logger.error(f"[{task_id}] Error during sync: {e}")
        raise


def sync_multiple_channels_task(
    self,
    channel_ids: List[int],
    sync_chat: bool = True,
    sync_images: bool = False,
    size_per_channel: int = 100,
) -> Dict[str, Any]:
    """Sync multiple channels using Celery group pattern.

    This task creates parallel sync jobs for multiple channels and aggregates
    the results for batch processing efficiency.

    Args:
        channel_ids: List of Telegram channel IDs to synchronize.
        sync_chat: Whether to sync chat messages to Elasticsearch.
        sync_images: Whether to download and store images to MinIO.
        size_per_channel: Number of messages to process per channel.

    Example:
        sync_multiple_channels_task.delay([123, 456, 789], sync_chat=True)
    """
    from celery import group

    task_id = self.request.id
    logger.info(
        f"[{task_id}] Starting batch sync for {len(channel_ids)} channels"
    )

    # Create a group of sync tasks
    job = group(
        sync_channel_messages_task.s(
            channel_id=channel_id,
            sync_chat=sync_chat,
            sync_images=sync_images,
            size=size_per_channel,
        )
        for channel_id in channel_ids
    )

    # Execute the group
    result = job.apply_async()

    # Wait for all tasks to complete
    results = result.get()

    # Aggregate results
    total_messages = sum(r["messages_processed"] for r in results)
    total_images = sum(r["images_downloaded"] for r in results)
    total_es_success = sum(r["elasticsearch_success"] for r in results)

    return {
        "batch_task_id": task_id,
        "channels_processed": len(channel_ids),
        "total_messages_processed": total_messages,
        "total_images_downloaded": total_images,
        "total_elasticsearch_success": total_es_success,
        "individual_results": results,
    }
