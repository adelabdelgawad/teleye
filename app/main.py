import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from http.client import HTTPException

from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.instrumentator import instrumentator
from routers.auth_router import router as auth_router
from routers.channel_router import router as channels_router
from routers.image_router import router as image_router
from routers.listener_router import router as listener_router
from routers.message_router import router as messages_router
from routers.smart_sync_router import router as smart_sync_router
from routers.sync_router import router as sync_router
from services.listener_service import (
    LISTENER_STATUS_KEY,
    get_listener_status,
    redis_client,
)
from services.user_service import ensure_default_admin
from tasks.listener_tasks import start_listener_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] | [%(funcName)s] [%(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def resume_listener_if_needed():
    """
    Resume the message listener on application startup if it was running before.

    This coroutine reads the persisted listener status from Redis (under
    LISTENER_STATUS_KEY). If the status contains `"is_running": True`, it:
      1. Retrieves the saved `download_images` setting.
      2. Dispatches a new Celery task via `start_listener_task.delay(...)`.
      3. Updates the Redis record with the new `task_id` and an ISO-formatted
         `started_at` timestamp.

    If the listener was not marked as running, it simply logs and returns.

    Example:
        # Called in your FastAPI lifespan startup hook
        await resume_listener_if_needed()

    """
    status = get_listener_status()
    if status.get("is_running", True):
        download_images = status.get("download_images", True)
        logger.info(
            f"Listener was running before restart; "
            f"resuming with download_images={download_images}"
        )

        # Fire off the Celery task
        celery_task = start_listener_task.delay(
            download_images=download_images
        )

        # Update the persisted status with the new task ID and timestamp
        status.update(
            {
                "task_id": celery_task.id,
                "started_at": datetime.utcnow().isoformat(),
            }
        )
        try:
            redis_client.set(LISTENER_STATUS_KEY, json.dumps(status))
        except Exception as e:
            logger.error(f"Failed to update Redis with resumed task_id: {e}")

    else:
        logger.info("Listener is not running; nothing to resume.")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application…")
    try:
        es = AsyncElasticsearch(settings.elasticsearch_connection_url)
        await ensure_default_admin(es)
        await resume_listener_if_needed()
    except Exception as e:
        logger.error(
            f"Failed to resume listener on startup: {e}", exc_info=True
        )
        raise

    yield

    logger.info("Shutting down application…")


app = FastAPI(
    lifespan=lifespan,
    title=settings.api.title,
    description=settings.api.description,
    version=settings.api.version,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(channels_router, prefix="/channels", tags=["CHANNELS"])
app.include_router(messages_router, prefix="/messages", tags=["MESSAGES"])
app.include_router(sync_router, prefix="/sync", tags=["SYNC"])
app.include_router(
    smart_sync_router, prefix="/smart_sync", tags=["SMART SYNC"]
)
app.include_router(image_router, prefix="/image", tags=["IMAGES"])
app.include_router(listener_router, prefix="/listener", tags=["LISTENER"])
app.include_router(auth_router, prefix="/auth", tags=["SECURITY"])


# Instrument the app
instrumentator.instrument(app)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Endpoint not found",
            "path": str(request.url.path),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}
    )


# Expose metrics endpoint (do this last)
instrumentator.expose(app, endpoint="/metrics")
