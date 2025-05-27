from unittest.mock import Mock, patch

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_start_listener_success(async_client, token_headers):
    """Test successful listener start"""
    with patch(
        "services.listener_service.get_listener_status"
    ) as mock_status, patch(
        "tasks.listener_tasks.start_listener_task"
    ) as mock_task:

        # Mock listener not running
        mock_status.return_value = {"is_running": False}

        # Mock task creation
        mock_task_result = Mock()
        mock_task_result.id = "test-task-123"
        mock_task.delay.return_value = mock_task_result

        response = await async_client.post(
            "/listener/start?download_images=true", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "task_id" in data


@pytest.mark.asyncio
async def test_start_listener_already_running(async_client, token_headers):
    """Test starting listener when already running"""
    with patch("services.listener_service.get_listener_status") as mock_status:
        mock_status.return_value = {
            "is_running": True,
            "task_id": "existing-task-456",
        }

        response = await async_client.post(
            "/listener/start", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_stop_listener_success(async_client, token_headers):
    """Test successful listener stop"""
    with patch("routers.listener_router.stop_listener_task") as mock_task:
        mock_result = Mock()
        mock_result.get.return_value = {
            "status": "stopped",
            "message": "Listener stopped successfully",
        }
        mock_task.delay.return_value = mock_result

        response = await async_client.post(
            "/listener/stop", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_listener_status(async_client, token_headers):
    """Test getting listener status"""
    with patch("services.listener_service.get_listener_status") as mock_status:
        mock_status.return_value = {
            "is_running": True,
            "download_images": True,
            "monitored_channels": 5,
            "channels": [123, 456, 789],
            "started_at": "2025-05-26T18:40:00Z",
            "task_id": "task-123",
        }

        response = await async_client.get(
            "/listener/status", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "is_running" in data


@pytest.mark.asyncio
async def test_add_channel_success(async_client, token_headers):
    """Test adding a channel"""
    with patch("routers.listener_router.add_channel_task") as mock_task:
        mock_result = Mock()
        mock_result.get.return_value = {
            "status": "added",
            "channel_id": 123,
            "message": "Channel added successfully",
        }
        mock_task.delay.return_value = mock_result

        response = await async_client.post(
            "/listener/channels/123/add", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_task_status(async_client, token_headers):
    """Test getting task status"""
    with patch("celery.result.AsyncResult") as mock_async_result:
        mock_task = Mock()
        mock_task.status = "SUCCESS"
        mock_task.result = {"completed": True}
        mock_task.ready.return_value = True
        mock_task.state = "SUCCESS"
        mock_async_result.return_value = mock_task

        response = await async_client.get(
            "/listener/task/test-task-123/status", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "task_id" in data


@pytest.mark.asyncio
async def test_stop_listener_with_proper_mocking(async_client, token_headers):
    """Test stop listener with comprehensive mocking"""
    with patch("tasks.listener_tasks.stop_listener_task.delay") as mock_delay:
        # Mock the delay method directly
        mock_result = Mock()
        mock_result.get.return_value = {
            "status": "stopped",
            "message": "Listener stopped successfully",
        }
        mock_delay.return_value = mock_result

        response = await async_client.post(
            "/listener/stop", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_add_channel_with_proper_mocking(async_client, token_headers):
    """Test add channel with comprehensive mocking"""
    with patch("tasks.listener_tasks.add_channel_task.delay") as mock_delay:
        # Mock the delay method directly
        mock_result = Mock()
        mock_result.get.return_value = {
            "status": "added",
            "channel_id": 123,
            "message": "Channel added successfully",
        }
        mock_delay.return_value = mock_result

        response = await async_client.post(
            "/listener/channels/123/add", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
