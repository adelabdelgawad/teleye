from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel
from pydantic_settings import SettingsConfigDict


class MessageRequest(BaseModel):
    receiver: str
    message: str


class ChannelInfo(BaseModel):
    id: int
    title: str | None = None
    messages_count: int | None = None
    username: str | None = None


class MessageInfo(BaseModel):
    channel_id: int
    message_id: int
    sender_name: str
    time: datetime | None = None
    text: str
    images: List[str] | None = []
    image_urls: List[str] | None = []
    images_data: List[bytes] | None = []
    indexed_at: datetime | None = None

    model_config = SettingsConfigDict(extra="allow")


class ChannelsResponse(BaseModel):
    channels_count: int
    channels: List[ChannelInfo]


class BaseTaskResponse(BaseModel):
    task_id: str
    status: str


class ChannelSyncResult(BaseModel):
    message: str
    channels_found: int | None = None
    channels_stored: int | None = None
    channels_failed: int | None = None
    new_channels: int | None = None
    channels: List[ChannelInfo] | None = None
    error: str | None = None


class SyncChannelsMessagesResult(BaseModel):
    status: str
    channels_synced: int | None = None
    messages_synced: int | None = None
    channels_processed: int | None = None


class DeletedMessageResponse(BaseModel):
    success: bool
    channel_id: int
    message_id: int
    doc_id: str
    elasticsearch_result: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Dict[str, Any] | None = None
    progress: Dict[str, Any] | None = None


class ListenerControlResponse(BaseModel):
    status: str
    message: str
    image_processing: str | None = None


class ListenerStatsResponse(BaseModel):
    total_channels: int
    total_messages: int
    today_messages: int
    listener_status: str


class RecentChannelInfo(BaseModel):
    id: int
    title: str | None = None
    username: str | None = None
    messages_count: int = 0
    indexed_at: str | None = None


class RecentChannelsResponse(BaseModel):
    channels: List[RecentChannelInfo]
    count: int


class RecentMessageInfo(BaseModel):
    channel_id: int
    message_id: int
    sender_name: str
    text: str
    time: str | None = None
    has_images: bool = False
    indexed_at: str | None = None


class RecentMessagesResponse(BaseModel):
    messages: List[RecentMessageInfo]
    count: int


class MediaUploadResponse(BaseModel):
    success: bool
    object_name: str | None = None
    url: str | None = None
    message: str


class MediaUrlResponse(BaseModel):
    object_name: str
    url: str
    expires_in_hours: int


class MediaDeleteResponse(BaseModel):
    success: bool
    object_name: str
    message: str


class MediaErrorResponse(BaseModel):
    error: str
    object_name: str | None = None
    detail: str


class StorageResult(BaseModel):
    stored_messages: int
    queued_image_tasks: int
    elasticsearch_response: Dict[str, Any] | None = None


class MessageStoreResponse(BaseModel):
    success: bool
    channel_id: int
    total_messages_processed: int
    storage_result: StorageResult | None = None
    message: str


class SyncTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    ready: bool
    result: Dict[str, Any] | None = None
    progress: Dict[str, Any] | None = None


class MessagesResponse(BaseModel):
    channel_id: int
    has_more: bool
    messages_count: int
    messages: List[MessageInfo]


class ListenerStatusResponse(BaseModel):
    is_running: bool
    download_images: bool
    monitored_channels: int
    channels: List[int]
    started_at: str | None = None
    stopped_at: str | None = None
    task_id: str | None = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    message: str


class SmartSyncResponse(BaseModel):
    task_id: str
    status: str
    message: str
    channel_id: int | None = None


class SmartSyncStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Dict[str, Any] | None = None
    result: Dict[str, Any] | None = None
    error: str | None = None


class SyncTaskResponse(BaseModel):
    task_id: str
    status: str
    message: str
    channel_id: int | None = None
    channels: List[int] | None = None


class SyncStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Dict | None = None
    result: Dict | None = None
    error: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str


class UserRead(BaseModel):
    username: str
    role: str


class User(BaseModel):
    username: str
    hashed_password: str
    role: str
