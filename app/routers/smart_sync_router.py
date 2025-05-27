import logging
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query

from core.models import SmartSyncResponse, SmartSyncStatusResponse
from services.dependancies import (
    CurrentUserDep,
    ElasticsearchDep,
    TelethonDep,
    require_role,
)
from tasks.smart_sync_tasks import smart_sync_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/sync/smart",
    response_model=SmartSyncResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def smart_sync(
    channel_id: Optional[int] = Query(
        None,
        description="Specific channel ID to sync (if not provided, syncs all channels)",
    ),
    sync_images: bool = Query(
        False, description="Whether to download and store images"
    ),
    max_parallel: int = Query(
        5, ge=1, le=20, description="Maximum parallel channel processing"
    ),
):
    """Smart sync that intelligently determines what needs to be synchronized.

    This endpoint compares message counts and last message IDs between Telegram and
    Elasticsearch to determine the most efficient sync strategy.

    Args:
        channel_id: Optional specific channel to sync (syncs all if not provided).
        sync_images: Whether to download images to MinIO storage.
        max_parallel: Maximum concurrent channel processing (1-20).

    Example:
        POST /sync/smart?channel_id=123&sync_images=true&max_parallel=3
        Starts smart sync for channel 123 with image downloading.
    """
    try:
        # Start smart sync task
        task = smart_sync_task.delay(
            channel_id=channel_id,
            sync_images=sync_images,
            max_parallel=max_parallel,
        )

        message = "Smart sync started"
        if channel_id:
            message += f" for channel {channel_id}"
        else:
            message += " for all channels"

        logger.info(f"Started smart sync task {task.id}")

        return SmartSyncResponse(
            task_id=task.id,
            status="PENDING",
            message=message,
            channel_id=channel_id,
        )

    except Exception as e:
        logger.error(f"Error starting smart sync: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start smart sync: {str(e)}"
        )


@router.get(
    "/sync/smart/{task_id}/status", response_model=SmartSyncStatusResponse
)
async def get_smart_sync_status(user: CurrentUserDep, task_id: str):
    """Get the status and progress of a smart sync task.

    This endpoint returns detailed status information including progress metrics
    for ongoing smart sync operations.

    Args:
        task_id: The unique identifier of the smart sync task.

    Example:
        GET /sync/smart/abc123/status
        Returns status and progress of smart sync task abc123.
    """
    try:
        task_result = AsyncResult(task_id)

        response = SmartSyncStatusResponse(
            task_id=task_id,
            status=task_result.status,
        )

        if task_result.state == "PROGRESS":
            response.progress = task_result.info
        elif task_result.ready():
            if task_result.successful():
                response.result = task_result.result
            else:
                response.error = str(task_result.info)

        return response

    except Exception as e:
        logger.error(f"Error getting smart sync status for {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get task status: {str(e)}"
        )


@router.get(
    "/sync/smart/preview", dependencies=[Depends(require_role("admin"))]
)
async def preview_smart_sync(
    es_client: ElasticsearchDep,
    telethon_client: TelethonDep,
    channel_id: Optional[int] = Query(
        None, description="Specific channel ID to preview"
    ),
):
    """Preview what smart sync would do without actually performing the sync.

    This endpoint analyzes channels and shows what actions would be taken
    during a smart sync operation without executing them.

    Args:
        es_client: Elasticsearch client dependency for database operations.
        telethon_client: Telethon client dependency for Telegram operations.
        channel_id: Optional specific channel to preview (previews all if not provided).

    Example:
        GET /sync/smart/preview?channel_id=123
        Shows what smart sync would do for channel 123.
    """
    try:
        from services.smart_sync_service import (
            get_all_telegram_channels,
            get_elasticsearch_channel_stats,
            get_telegram_channel_stats,
        )

        # Determine channels to preview
        if channel_id:
            channel_ids = [channel_id]
        else:
            channel_ids = await get_all_telegram_channels(telethon_client)
            # Limit preview to first 10 channels for performance
            channel_ids = channel_ids[:10]

        if not channel_ids:
            return {"message": "No channels found to preview", "channels": []}

        preview_results = []

        for ch_id in channel_ids:
            # Get stats from both sources
            tg_stats = await get_telegram_channel_stats(telethon_client, ch_id)
            es_stats = await get_elasticsearch_channel_stats(es_client, ch_id)

            if not tg_stats:
                action = "skip"
                reason = "Channel not accessible on Telegram"
            elif es_stats["last_message_id"] is None:
                action = "full_sync"
                reason = "No data in Elasticsearch"
            elif tg_stats["last_message_id"] == es_stats["last_message_id"]:
                action = "skip"
                reason = "Last message IDs are equal"
            elif tg_stats["last_message_id"] > es_stats["last_message_id"]:
                action = "incremental_sync"
                reason = f"Need to sync messages from {es_stats['last_message_id'] + 1} to {tg_stats['last_message_id']}"
            else:
                action = "skip"
                reason = "Elasticsearch has higher message ID than Telegram"

            preview_results.append(
                {
                    "channel_id": ch_id,
                    "action": action,
                    "reason": reason,
                    "telegram_stats": tg_stats,
                    "elasticsearch_stats": es_stats,
                }
            )

        # Summary
        actions_summary = {}
        for result in preview_results:
            action = result["action"]
            actions_summary[action] = actions_summary.get(action, 0) + 1

        return {
            "message": f"Smart sync preview for {len(channel_ids)} channels",
            "actions_summary": actions_summary,
            "channels": preview_results,
        }

    except Exception as e:
        logger.error(f"Error in smart sync preview: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to preview smart sync: {str(e)}"
        )
