import logging
from typing import List

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Query

from core.models import SyncStatusResponse, SyncTaskResponse
from services.dependancies import CurrentUserDep
from tasks.sync_tasks import (
    sync_channel_messages_task,
    sync_multiple_channels_task,
)

router = APIRouter()
logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends

from services.dependancies import require_role


@router.post(
    "/sync/channel/{channel_id}",
    response_model=SyncTaskResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def sync_channel_async(
    channel_id: int,
    sync_chat: bool = Query(
        True, description="Sync chat messages to Elasticsearch"
    ),
    sync_images: bool = Query(
        False, description="Download and store images to MinIO"
    ),
    size: int = Query(
        100, ge=1, le=500, description="Number of messages to process"
    ),
    offset: int = Query(0, ge=0, description="Number of messages to skip"),
    batch_size: int = Query(
        50, ge=10, le=100, description="Batch size for processing"
    ),
):
    """Start async sync of messages from Telegram channel using Celery.

    This endpoint initiates a background task to synchronize messages from a specific
    Telegram channel to Elasticsearch with optional image downloading.

    Args:
        channel_id: The Telegram channel ID to synchronize.
        sync_chat: Whether to sync chat messages to Elasticsearch.
        sync_images: Whether to download and store images to MinIO.
        size: Number of messages to process (1-500).
        offset: Number of messages to skip for pagination.
        batch_size: Batch size for processing (10-100).

    Example:
        POST /sync/channel/123?sync_chat=true&sync_images=false&size=100
        Syncs 100 messages from channel 123 without images.
    """
    try:
        # Validate parameters
        if channel_id <= 0:
            raise ValueError("Channel ID must be a positive integer")

        if not sync_chat and not sync_images:
            raise ValueError(
                "At least one of sync_chat or sync_images must be True"
            )

        # Start Celery task
        task = sync_channel_messages_task.delay(
            channel_id=channel_id,
            sync_chat=sync_chat,
            sync_images=sync_images,
            size=size,
            offset=offset,
            batch_size=batch_size,
        )

        logger.info(f"Started sync task {task.id} for channel {channel_id}")

        return SyncTaskResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Sync task started for channel {channel_id}",
            channel_id=channel_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting sync for channel {channel_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start sync: {str(e)}"
        )


@router.post(
    "/sync/channels/batch",
    response_model=SyncTaskResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def sync_multiple_channels_async(
    channel_ids: List[int],
    sync_chat: bool = Query(True, description="Sync chat messages"),
    sync_images: bool = Query(False, description="Download images"),
    size_per_channel: int = Query(
        100, ge=1, le=500, description="Messages per channel"
    ),
):
    """Start async sync of multiple channels using Celery group pattern.

    This endpoint initiates batch synchronization of multiple channels
    with parallel processing for improved performance.

    Args:
        channel_ids: List of Telegram channel IDs to synchronize.
        sync_chat: Whether to sync chat messages to Elasticsearch.
        sync_images: Whether to download and store images to MinIO.
        size_per_channel: Number of messages to process per channel (1-500).

    Example:
        POST /sync/channels/batch with body [123, 456, 789]?sync_chat=true
        Syncs messages from three channels simultaneously.
    """

    try:
        if not channel_ids:
            raise ValueError("At least one channel ID must be provided")

        if not sync_chat and not sync_images:
            raise ValueError(
                "At least one of sync_chat or sync_images must be True"
            )

        # Start batch sync task
        task = sync_multiple_channels_task.delay(
            channel_ids=channel_ids,
            sync_chat=sync_chat,
            sync_images=sync_images,
            size_per_channel=size_per_channel,
        )

        logger.info(
            f"Started batch sync task {task.id} for {len(channel_ids)} channels"
        )

        return SyncTaskResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Batch sync task started for {len(channel_ids)} channels",
            channels=channel_ids,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting batch sync: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start batch sync: {str(e)}"
        )


@router.get("/sync/task/{task_id}/status", response_model=SyncStatusResponse)
async def get_sync_task_status(user: CurrentUserDep, task_id: str):
    """Get the status and progress of a sync task.

    This endpoint returns detailed status information including progress metrics
    and results for sync operations.

    Args:
        task_id: The unique identifier of the sync task.

    Example:
        GET /sync/task/abc123/status
        Returns status and progress of sync task abc123.
    """
    try:
        task_result = AsyncResult(task_id)

        response = SyncStatusResponse(
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
        logger.error(f"Error getting task status for {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get task status: {str(e)}"
        )


@router.delete(
    "/sync/task/{task_id}", dependencies=[Depends(require_role("admin"))]
)
async def cancel_sync_task(task_id: str):
    """Cancel a running sync task.

    This endpoint terminates a running sync task and cleans up resources.

    Args:
        task_id: The unique identifier of the sync task to cancel.

    Example:
        DELETE /sync/task/abc123
        Cancels the running sync task abc123.
    """
    try:
        task_result = AsyncResult(task_id)
        task_result.revoke(terminate=True)

        return {"message": f"Task {task_id} has been cancelled"}

    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel task: {str(e)}"
        )
