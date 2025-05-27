import asyncio
import logging
from typing import Any, Dict, Optional

from celery import Task
from celery_worker import celery_worker
from core.config import settings
from elasticsearch import AsyncElasticsearch
from services.minio_service import MinIOManager
from services.smart_sync_service import (get_all_telegram_channels,
                                         smart_sync_channel)
from telethon import TelegramClient
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)


class SmartSyncTask(Task):
    """Custom task class with progress tracking"""

    def update_progress(self, current: int, total: int, status: str):
        """Update smart sync task progress with current status.

        This method updates the Celery task state with progress information
        for smart sync operations including channel processing status.

        Args:
            current: Current number of processed channels.
            total: Total number of channels to process.
            status: Current status message describing the operation.

        Example:
            self.update_progress(5, 20, "Processing channel 123")
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
    name="sync.smart_sync", bind=True, base=SmartSyncTask, serializer="json"
)
def smart_sync_task(
    self,
    channel_id: Optional[int] = None,
    sync_images: bool = False,
    max_parallel: int = 5,
) -> Dict[str, Any]:
    """Intelligent sync that determines optimal sync strategy per channel.

    This Celery task analyzes channels and applies the most efficient sync
    strategy based on message count differences between Telegram and Elasticsearch.

    Args:
        channel_id: Optional specific channel to sync (syncs all if None).
        sync_images: Whether to download and store images to MinIO.
        max_parallel: Maximum number of channels to process concurrently.

    Example:
        smart_sync_task.delay(channel_id=123, sync_images=True, max_parallel=3)
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting smart sync")

    async def run_smart_sync():
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

            # Determine channels to process
            if channel_id:
                channel_ids = [channel_id]
            else:
                channel_ids = await get_all_telegram_channels(telethon_client)

            if not channel_ids:
                return {
                    "success": False,
                    "message": "No channels found to sync",
                    "results": [],
                }

            total_channels = len(channel_ids)
            self.update_progress(
                0, total_channels, f"Processing {total_channels} channels"
            )

            # Process channels with controlled parallelism
            semaphore = asyncio.Semaphore(max_parallel)

            async def process_channel_with_semaphore(ch_id):
                async with semaphore:
                    return await smart_sync_channel(
                        ch_id,
                        telethon_client,
                        es_client,
                        sync_images,
                        minio_manager,
                    )

            # Create tasks for all channels
            tasks = [
                process_channel_with_semaphore(ch_id) for ch_id in channel_ids
            ]

            # Process with progress updates
            results = []
            completed = 0

            for coro in asyncio.as_completed(tasks):
                result = await coro
                results.append(result)
                completed += 1

                self.update_progress(
                    completed,
                    total_channels,
                    f"Completed {completed}/{total_channels} channels",
                )

                logger.info(
                    f"[{task_id}] Completed channel {result['channel_id']}: {result['action']}"
                )

            # Aggregate statistics
            successful = sum(1 for r in results if r["success"])
            total_messages = sum(
                r.get("messages_processed", 0) for r in results
            )
            total_images = sum(r.get("images_downloaded", 0) for r in results)

            actions_summary = {}
            for result in results:
                action = result["action"]
                actions_summary[action] = actions_summary.get(action, 0) + 1

            return {
                "success": True,
                "task_id": task_id,
                "channels_processed": total_channels,
                "channels_successful": successful,
                "channels_failed": total_channels - successful,
                "total_messages_processed": total_messages,
                "total_images_downloaded": total_images,
                "actions_summary": actions_summary,
                "results": results,
            }

        finally:
            await es_client.close()
            await telethon_client.disconnect()

    try:
        return asyncio.run(run_smart_sync())
    except Exception as e:
        logger.error(f"[{task_id}] Error during smart sync: {e}")
        raise
