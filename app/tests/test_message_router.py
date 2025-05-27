from unittest.mock import patch

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_get_messages_from_elasticsearch_success(
    async_client, token_headers
):
    """Test successful message retrieval from Elasticsearch"""
    with patch(
        "routers.message_router.fetch_messages_from_elasticsearch"
    ) as mock_fetch:
        mock_fetch.return_value = {
            "messages": [
                {
                    "message_id": 1,
                    "text": "Test message",
                    "sender_name": "test_user",
                    "channel_id": 123,
                    "timestamp": "2025-05-26T18:40:00Z",
                }
            ],
            "messages_count": 1,
            "total_messages": 100,
            "has_more": True,
            "channel_id": 123,
        }

        response = await async_client.get(
            "/messages/elasticsearch?channel_id=123&size=10&offset=0",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["messages_count"] == 1


@pytest.mark.asyncio
async def test_get_messages_with_filters(async_client, token_headers):
    """Test message retrieval with various filters"""
    with patch(
        "routers.message_router.fetch_messages_from_elasticsearch"
    ) as mock_fetch:
        mock_fetch.return_value = {
            "messages": [],
            "messages_count": 0,
            "total_messages": 0,
            "has_more": False,
            "channel_id": 123,
        }

        response = await async_client.get(
            "/messages/elasticsearch?"
            "channel_id=123&"
            "has_media=true&"
            "title_contains=test&"
            "sender_name=user123&"
            "size=50",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_telegram_messages_success(async_client, token_headers):
    """Test successful message retrieval from Telegram"""
    with patch(
        "routers.message_router.fetch_messages_from_telegram"
    ) as mock_fetch:
        mock_fetch.return_value = {
            "messages": [
                {
                    "message_id": 1,
                    "text": "Telegram message",
                    "sender_name": "telegram_user",
                    "channel_id": 456,
                }
            ],
            "messages_count": 1,
            "channel_info": {"name": "Test Channel"},
            "channel_id": 456,
            "has_more": False,
        }

        response = await async_client.get(
            "/messages/telegram/456?size=100&offset=0&batch_size=1000",
            headers=token_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["messages_count"] == 1


@pytest.mark.asyncio
async def test_telegram_messages_validation_error(async_client, token_headers):
    """Test validation errors for Telegram message retrieval"""
    response = await async_client.get(
        "/messages/telegram/456?size=0", headers=token_headers
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_elasticsearch_messages_empty_result(
    async_client, token_headers
):
    """Test empty result from Elasticsearch"""
    with patch(
        "routers.message_router.fetch_messages_from_elasticsearch"
    ) as mock_fetch:
        mock_fetch.return_value = {
            "messages": [],
            "messages_count": 0,
            "total_messages": 0,
            "has_more": False,
            "channel_id": 0,
        }

        response = await async_client.get(
            "/messages/elasticsearch", headers=token_headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["messages_count"] == 0
