import logging
from typing import Optional

from celery.result import AsyncResult
from core.models import ChannelsResponse, TaskResponse, TaskStatusResponse
from fastapi import APIRouter, Depends, HTTPException, Query
from services.dependancies import (CurrentUserDep, ElasticsearchDep,
                                   TelethonDep, require_role)
from tasks.channel_tasks import (get_channels_from_es, read_and_store_channels,
                                 read_channels_from_telegram)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/elasticsearch", response_model=ChannelsResponse)
async def get_channels_from_elasticsearch(
    es_client: ElasticsearchDep,
    user: CurrentUserDep,
    title_contains: Optional[str] = Query(
        None, description="Filter channels by title content", max_length=100
    ),
    username: Optional[str] = Query(
        None, description="Filter channels by username", max_length=50
    ),
    size: Optional[int] = Query(
        None, ge=1, le=1000, description="Number of channels to return"
    ),
    offset: int = Query(
        0, ge=0, description="Number of channels to skip for pagination"
    ),
):
    """Retrieve channels from Elasticsearch with optional filtering.

    This endpoint searches for channels in Elasticsearch based on the provided
    filter criteria. Results can be paginated using size and offset parameters.

    Args:
        es_client: Elasticsearch client dependency for database operations.
        title_contains: Optional string to filter channels by title content.
        username: Optional string to filter channels by username.
        size: Optional integer specifying the maximum number of channels to return.
        offset: Integer specifying the number of channels to skip for pagination.

    Example:
        GET /elasticsearch?title_contains=news&size=10&offset=0
        Returns up to 10 channels with "news" in their title.
    """
    try:
        logger.info("Fetching channels with filters:")
        print(user)
        channels = await get_channels_from_es(
            es_client, title_contains, username, size, offset
        )

        logger.info(f"Successfully retrieved {len(channels)} channels")

        return ChannelsResponse(
            channels_count=len(channels), channels=channels
        )

    except Exception as e:
        logger.error(f"Error retrieving channels: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error occurred while retrieving channels",
        )


@router.get("/telegram", response_model=ChannelsResponse)
async def get_channels_from_telegram(
    telethon_client: TelethonDep, user: CurrentUserDep
):
    """Retrieve all channels from Telegram.

    This endpoint fetches all accessible channels from Telegram using Telethon client.

    Args:
        telethon_client: Telethon client dependency for Telegram operations.

    Example:
        GET /telegram
        Returns all accessible Telegram channels.
    """
    try:
        logger.info("Fetching channels from Telegram")

        # Get channels from Telegram
        channels = await read_channels_from_telegram(telethon_client)

        logger.info(f"Successfully retrieved {len(channels)} channels")

        return ChannelsResponse(
            channels_count=len(channels), channels=channels
        )

    except Exception as e:
        logger.error(f"Error retrieving channels: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error occurred while retrieving channels",
        )


@router.post(
    "/sync",
    response_model=TaskResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def beginner_sync_add_channels_without_counter():
    """Start beginner sync of all Telegram channels to Elasticsearch.

    This endpoint initiates a background task to sync all Telegram channels
    to Elasticsearch for the first time.

    Example:
        POST /sync
        Starts full channel synchronization task.
    """
    try:
        task = read_and_store_channels.delay()
        return TaskResponse(
            task_id=task.id,
            status="PENDING",
            message="Beginner sync of all channels started.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start full sync: {str(e)}"
        )


@router.get(
    "/task/status/{task_id}",
    response_model=TaskStatusResponse,
    dependencies=[Depends(require_role("admin"))],
)
async def get_full_sync_status(task_id: str):
    """Get the status of the full sync task.

    This endpoint returns the current status and progress of a channel sync task.

    Args:
        task_id: The unique identifier of the sync task.

    Example:
        GET /task/status/abc123
        Returns status of task with ID abc123.
    """
    try:
        task_result = AsyncResult(task_id)
        return TaskStatusResponse(
            task_id=task_id,
            status=task_result.status,
            result=task_result.result if task_result.ready() else None,
            progress=(
                task_result.info if task_result.state == "PROGRESS" else None
            ),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get status: {str(e)}"
        )
