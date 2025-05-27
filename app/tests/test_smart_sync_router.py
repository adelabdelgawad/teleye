from unittest.mock import Mock, patch

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_smart_sync_single_channel(async_client, token_headers):
    """Test smart sync for a single channel"""
    with patch("routers.smart_sync_router.smart_sync_task") as mock_task:
        mock_task_result = Mock()
        mock_task_result.id = "smart-sync-123"
        mock_task.delay.return_value = mock_task_result

        response = await async_client.post(
            "/smart_sync/sync/smart?"
            "channel_id=123&"
            "sync_images=true&"
            "max_parallel=3",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "smart-sync-123"


@pytest.mark.asyncio
async def test_smart_sync_all_channels(async_client, token_headers):
    """Test smart sync for all channels"""
    with patch("routers.smart_sync_router.smart_sync_task") as mock_task:
        mock_task_result = Mock()
        mock_task_result.id = "smart-sync-all-456"
        mock_task.delay.return_value = mock_task_result

        response = await async_client.post(
            "/smart_sync/sync/smart?sync_images=false&max_parallel=10",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "smart-sync-all-456"


@pytest.mark.asyncio
async def test_get_smart_sync_status_progress(async_client, token_headers):
    """Test getting smart sync status with progress"""
    with patch("routers.smart_sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "PROGRESS"
        mock_task.state = "PROGRESS"
        mock_task.info = {
            "current_channel": 123,
            "processed_channels": 5,
            "total_channels": 20,
            "progress_percentage": 25,
        }
        mock_task.ready.return_value = False
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/smart_sync/sync/smart/test-task-123/status",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "PROGRESS"


@pytest.mark.asyncio
async def test_smart_sync_preview(async_client, token_headers):
    """Test smart sync preview functionality"""
    with patch(
        "services.smart_sync_service.get_all_telegram_channels"
    ) as mock_get_channels, patch(
        "services.smart_sync_service.get_telegram_channel_stats"
    ) as mock_tg_stats, patch(
        "services.smart_sync_service.get_elasticsearch_channel_stats"
    ) as mock_es_stats:

        mock_get_channels.return_value = [123, 456, 789]

        mock_tg_stats.side_effect = [
            {"last_message_id": 100, "total_messages": 100},
            {"last_message_id": 200, "total_messages": 200},
            None,  # Channel not accessible
        ]

        mock_es_stats.side_effect = [
            {"last_message_id": 90, "total_messages": 90},
            {"last_message_id": 200, "total_messages": 200},
            {"last_message_id": None, "total_messages": 0},
        ]

        response = await async_client.get(
            "/smart_sync/sync/smart/preview", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["channels"]) == 3


@pytest.mark.asyncio
async def test_smart_sync_status_success(async_client, token_headers):
    """Test getting successful smart sync status"""
    with patch("routers.smart_sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "SUCCESS"
        mock_task.state = "SUCCESS"
        mock_task.ready.return_value = True
        mock_task.successful.return_value = True
        mock_task.result = {
            "processed_channels": 10,
            "total_messages_synced": 5000,
            "completion_time": "2025-05-26T20:15:00Z",
        }
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/smart_sync/sync/smart/success-task-456/status",
            headers=token_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_smart_sync_status_failure(async_client, token_headers):
    """Test getting failed smart sync status"""
    with patch("routers.smart_sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "FAILURE"
        mock_task.state = "FAILURE"
        mock_task.ready.return_value = True
        mock_task.successful.return_value = False
        mock_task.failed.return_value = True
        mock_task.result = Exception("Smart sync failed")
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/smart_sync/sync/smart/failed-task-789/status",
            headers=token_headers,
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "FAILURE"


@pytest.mark.asyncio
async def test_smart_sync_with_validation_error(async_client, token_headers):
    """Test smart sync with invalid parameters"""
    response = await async_client.post(
        "/smart_sync/sync/smart?max_parallel=0", headers=token_headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_smart_sync_preview_empty_channels(async_client, token_headers):
    """Test smart sync preview with no channels"""
    with patch(
        "services.smart_sync_service.get_all_telegram_channels"
    ) as mock_get_channels:
        mock_get_channels.return_value = []

        response = await async_client.get(
            "/smart_sync/sync/smart/preview", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["channels"]) == 0
