import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query

from core.models import ListenerStatusResponse, TaskResponse
from services.dependancies import CurrentUserDep, require_role
from services.listener_service import get_listener_status
from tasks.listener_tasks import (
    add_channel_task,
    get_listener_stats,
    remove_channel_task,
    start_listener_task,
    stop_listener_task,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/start",
    response_model=TaskResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def start_listener(
    download_images: bool = Query(
        True, description="Whether to download and store images"
    ),
):
    """Start the real-time message listener.

    This endpoint starts monitoring all accessible Telegram channels for new messages
    and processes them in real-time.

    Args:
        download_images: Whether to download and store images from messages.

    Example:
        POST /start?download_images=true
        Starts listener with image downloading enabled.
    """
    try:
        # Check current status
        status = get_listener_status()
        if status.get("is_running", False):
            return TaskResponse(
                task_id=status.get("task_id", "unknown"),
                status="already_running",
                message="Listener is already running",
            )

        # Start listener task
        task = start_listener_task.delay(download_images=download_images)

        logger.info(f"Started listener task {task.id}")

        return TaskResponse(
            task_id=task.id,
            status="starting",
            message=f"Listener is starting (download_images={download_images})",
        )

    except Exception as e:
        logger.error(f"Error starting listener: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start listener: {str(e)}"
        )


@router.post(
    "/stop",
    response_model=dict,
    dependencies=[Depends(require_role("admin"))],
)
async def stop_listener():
    """Stop the message listener.

    This endpoint gracefully stops the listener and cleans up resources.

    Example:
        POST /stop
        Stops the currently running listener.
    """
    logger.info("Stopping listener...")
    try:
        result = stop_listener_task.delay()
        task_result = result.get(timeout=10)

        return task_result

    except Exception as e:
        logger.error(f"Error stopping listener: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to stop listener: {str(e)}"
        )


@router.get("/status", response_model=ListenerStatusResponse)
async def get_status(
    user: CurrentUserDep,
):
    """Get the current status of the message listener.

    This endpoint returns comprehensive information about the listener state
    including monitored channels and configuration.

    Example:
        GET /status
        Returns current listener status and configuration.
    """
    try:
        status = get_listener_status()

        return ListenerStatusResponse(
            is_running=status.get("is_running", False),
            download_images=status.get("download_images", True),
            monitored_channels=status.get("monitored_channels", 0),
            channels=status.get("channels", []),
            started_at=status.get("started_at"),
            stopped_at=status.get("stopped_at"),
            task_id=status.get("task_id"),
        )

    except Exception as e:
        logger.error(f"Error getting listener status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get listener status: {str(e)}"
        )


@router.post(
    "/channels/{channel_id}/add", dependencies=[Depends(require_role("admin"))]
)
async def add_channel(channel_id: int):
    """Add a specific channel to monitoring.

    This endpoint adds a channel to the list of monitored channels for real-time processing.

    Args:
        channel_id: The Telegram channel ID to add to monitoring.

    Example:
        POST /channels/123456/add
        Adds channel 123456 to monitoring list.
    """
    try:
        task = add_channel_task.delay(channel_id)
        result = task.get(timeout=10)

        return result

    except Exception as e:
        logger.error(f"Error adding channel {channel_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to add channel: {str(e)}"
        )


@router.delete(
    "/channels/{channel_id}", dependencies=[Depends(require_role("admin"))]
)
async def remove_channel(channel_id: int):
    """Remove a channel from monitoring.

    This endpoint removes a channel from the monitored list.

    Args:
        channel_id: The Telegram channel ID to remove from monitoring.

    Example:
        DELETE /channels/123456
        Removes channel 123456 from monitoring.
    """
    try:
        task = remove_channel_task.delay(channel_id)
        result = task.get(timeout=10)

        return result

    except Exception as e:
        logger.error(f"Error removing channel {channel_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to remove channel: {str(e)}"
        )


@router.get(
    "/stats",
)
async def get_listener_statistics(
    user: CurrentUserDep,
):
    """Get detailed listener statistics.

    This endpoint returns comprehensive performance metrics and channel details.

    Example:
        GET /stats
        Returns detailed listener performance statistics.
    """
    try:
        task = get_listener_stats.delay()
        result = task.get(timeout=10)

        return result

    except Exception as e:
        logger.error(f"Error getting listener stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get listener statistics: {str(e)}",
        )


@router.get("/task/{task_id}/status")
async def get_task_status(user: CurrentUserDep, task_id: str):
    """Get the status of a specific listener task.

    This endpoint returns the current status of a listener-related task.

    Args:
        task_id: The unique identifier of the task.

    Example:
        GET /task/abc123/status
        Returns status of task abc123.
    """
    try:
        task_result = AsyncResult(task_id)

        return {
            "task_id": task_id,
            "status": task_result.status,
            "result": task_result.result if task_result.ready() else None,
            "info": (
                task_result.info if task_result.state == "PROGRESS" else None
            ),
        }

    except Exception as e:
        logger.error(f"Error getting task status for {task_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get task status: {str(e)}"
        )
