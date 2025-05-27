import asyncio
import logging
from typing import Annotated, AsyncGenerator, Optional

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from telethon import TelegramClient
from telethon.sessions import StringSession

from core.config import settings
from core.models import User
from services.minio_service import MinIOManager

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


async def get_elasticsearch_client() -> (
    AsyncGenerator[AsyncElasticsearch, None]
):
    """Provide an async Elasticsearch client with automatic cleanup.

    This dependency function creates and yields an Elasticsearch client,
    ensuring proper cleanup when the request is completed.

    Example:
        Used as FastAPI dependency: ElasticsearchDep = Annotated[AsyncElasticsearch, Depends(get_elasticsearch_client)]
    """
    elasticsearch = AsyncElasticsearch(settings.elasticsearch_connection_url)
    try:
        yield elasticsearch
    finally:
        await elasticsearch.close()


class TelegramClientManager:
    def __init__(self):
        self._client = None
        self._lock = asyncio.Lock()

    async def get_client(self):
        """Get or create a singleton Telegram client instance.

        This method ensures only one Telegram client exists per manager instance
        using async locking for thread safety.

        Example:
            client = await telegram_manager.get_client()
        """
        async with self._lock:
            if self._client is None:
                self._client = TelegramClient(
                    StringSession(settings.telegram.string_session),
                    settings.telegram.api_id,
                    settings.telegram.api_hash,
                )
                await self._client.start()
            return self._client

    async def close(self):
        """Close and cleanup the Telegram client connection.

        This method safely disconnects the Telegram client and resets
        the internal client reference.

        Example:
            await telegram_manager.close()
        """
        if self._client:
            await self._client.disconnect()
            self._client = None


# Global instance
telegram_manager = TelegramClientManager()


async def get_telegram_client() -> TelegramClient:
    """Provide a Telegram client instance.

    This dependency function returns a managed Telegram client
    for use in FastAPI endpoints.

    Example:
        Used as FastAPI dependency: TelethonDep = Annotated[TelegramClient, Depends(get_telegram_client)]
    """
    return await telegram_manager.get_client()


def get_minio_manager() -> Optional[MinIOManager]:
    """Dependency to provide MinIO manager with updated credentials"""
    try:
        return MinIOManager(
            endpoint=settings.minio.endpoint,
            access_key=settings.minio.root_user,
            secret_key=settings.minio.root_password,
            secure=settings.minio.secure,
        )
    except Exception as e:
        logger.warning(f"MinIO not available: {e}")
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    es: AsyncElasticsearch = Depends(get_elasticsearch_client),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.security.secret_key,
            algorithms=[settings.security.algorithm],
        )
        username: str = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Fetch user from Elasticsearch
    resp = await es.options(ignore_status=[404]).get(
        index="users", id=username
    )
    if not resp.get("found"):
        raise credentials_exception
    return resp["_source"]


def require_role(role: str):
    async def checker(user=Depends(get_current_user)):
        if user.get("role") != role:
            raise HTTPException(status_code=403, detail="Operation forbidden")
        return user

    return checker


# Dependency annotations
TelethonDep = Annotated[TelegramClient, Depends(get_telegram_client)]
ElasticsearchDep = Annotated[
    AsyncElasticsearch, Depends(get_elasticsearch_client)
]
MinioDep = Annotated[Optional[MinIOManager], Depends(get_minio_manager)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
