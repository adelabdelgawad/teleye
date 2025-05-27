import logging
from typing import Any, Dict, List, Optional, Tuple

from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk

logger = logging.getLogger(__name__)


async def execute_elasticsearch_bulk_insert(
    es_client: AsyncElasticsearch, actions: List[dict]
) -> Tuple[int, int]:
    """Execute async bulk insert with error handling.

    This function performs bulk operations on Elasticsearch with proper
    error handling and returns success/failure counts.

    Args:
        es_client: Elasticsearch client for database operations.
        actions: List of bulk operation dictionaries.

    Example:
        success, failed = await execute_elasticsearch_bulk_insert(es_client, actions)
    """
    try:
        success, failed = await async_bulk(
            es_client,
            actions,
            chunk_size=500,
            request_timeout=60,
            stats_only=True,
        )
        logger.info(
            f"Bulk insert completed: {success} succeeded, {failed} failed"
        )
        return success, failed
    except Exception as e:
        logger.error(f"Error in bulk ES operation: {e}")
        return 0, len(actions)


def build_channel_query(
    title_contains: Optional[str] = None, username: Optional[str] = None
) -> dict:
    """Build Elasticsearch query for channels with optional filters.

    This function constructs a query dictionary for searching channels
    based on title and username criteria.

    Args:
        title_contains: Optional string to filter channels by title content.
        username: Optional string to filter channels by username.

    Example:
        query = build_channel_query(title_contains="news", username="channel1")
    """
    must_clauses = []
    if title_contains:
        must_clauses.append({"match": {"title": title_contains}})
    if username:
        must_clauses.append({"term": {"username.keyword": username}})

    return {
        "bool": {"must": must_clauses if must_clauses else [{"match_all": {}}]}
    }


def build_message_query(
    channel_id: Optional[int] = None,
    message_id: Optional[int] = None,
    has_media: Optional[bool] = None,
    title_contains: Optional[str] = None,
    sender_name: Optional[str] = None,
    size: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """Build Elasticsearch query for messages with filtering and pagination.

    This function constructs a comprehensive query for searching messages
    with multiple filter options and pagination support.

    Args:
        channel_id: Optional channel ID to filter messages.
        message_id: Optional specific message ID to fetch.
        has_media: Optional filter for messages with/without media.
        title_contains: Optional text search within message content.
        sender_name: Optional filter by sender name.
        size: Number of messages to return.
        offset: Number of messages to skip for pagination.

    Example:
        query = build_message_query(channel_id=123, has_media=True, size=50)
    """
    query = {"bool": {"must": []}}

    if channel_id is not None:
        query["bool"]["must"].append({"term": {"channel_id": channel_id}})
    if message_id is not None:
        query["bool"]["must"].append({"term": {"message_id": message_id}})
    if sender_name is not None:
        query["bool"]["must"].append({"match": {"sender_name": sender_name}})
    if title_contains is not None:
        query["bool"]["must"].append({"match": {"text": title_contains}})
    if has_media is not None:
        if has_media:
            # has_media True means image_urls should not be empty
            query["bool"]["must"].append({"exists": {"field": "image_urls"}})
        else:
            # has_media False means image_urls should be empty or not exist
            query["bool"]["must_not"] = [{"exists": {"field": "image_urls"}}]

    return {"from": offset, "size": size, "query": query}
