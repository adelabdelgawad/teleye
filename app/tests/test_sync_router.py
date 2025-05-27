from unittest.mock import Mock, patch

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_sync_channel_success(async_client, token_headers):
    """Test successful channel sync"""
    with patch("routers.sync_router.sync_channel_messages_task") as mock_task:
        mock_task_result = Mock()
        mock_task_result.id = "sync-task-123"
        mock_task.delay.return_value = mock_task_result

        response = await async_client.post(
            "/sync/sync/channel/123?"
            "sync_chat=true&"
            "sync_images=false&"
            "size=100&"
            "offset=0&"
            "batch_size=50",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "sync-task-123"


@pytest.mark.asyncio
async def test_sync_channel_validation_errors(async_client, token_headers):
    """Test validation errors for channel sync"""
    # Test invalid channel ID
    response = await async_client.post(
        "/sync/sync/channel/0", headers=token_headers
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_sync_multiple_channels_success(async_client, token_headers):
    """Test successful batch channel sync"""
    with patch("routers.sync_router.sync_multiple_channels_task") as mock_task:
        mock_task_result = Mock()
        mock_task_result.id = "batch-sync-456"
        mock_task.delay.return_value = mock_task_result

        response = await async_client.post(
            "/sync/sync/channels/batch",
            json=[123, 456, 789],
            params={
                "sync_chat": True,
                "sync_images": True,
                "size_per_channel": 200,
            },
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["task_id"] == "batch-sync-456"


@pytest.mark.asyncio
async def test_get_sync_task_status_success(async_client, token_headers):
    """Test getting successful task status"""
    with patch("routers.sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "SUCCESS"
        mock_task.ready.return_value = True
        mock_task.successful.return_value = True
        mock_task.result = {
            "processed_messages": 150,
            "stored_messages": 150,
            "downloaded_images": 25,
        }
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/sync/sync/task/test-task-123/status", headers=token_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_cancel_sync_task(async_client, token_headers):
    """Test cancelling a sync task"""
    with patch("routers.sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_async_result.return_value = mock_task

        response = await async_client.delete(
            "/sync/sync/task/test-task-123", headers=token_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "cancelled" in data["message"]
        mock_task.revoke.assert_called_once_with(terminate=True)


@pytest.mark.asyncio
async def test_sync_channel_with_both_options_disabled(
    async_client, token_headers
):
    """Test sync channel with both sync options disabled"""
    response = await async_client.post(
        "/sync/sync/channel/123?sync_chat=false&sync_images=false",
        headers=token_headers,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_sync_task_status_pending(async_client, token_headers):
    """Test getting pending task status"""
    with patch("celery.result.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "PENDING"
        mock_task.ready.return_value = False
        mock_task.successful.return_value = False
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/sync/sync/task/pending-task-456/status", headers=token_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "PENDING"


@pytest.mark.asyncio
async def test_sync_task_status_failure(async_client, token_headers):
    """Test getting failed task status"""
    with patch("routers.sync_router.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "FAILURE"
        mock_task.ready.return_value = True
        mock_task.successful.return_value = False
        mock_task.failed.return_value = True
        mock_task.result = Exception("Task failed")
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/sync/sync/task/failed-task-789/status", headers=token_headers
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "FAILURE"
