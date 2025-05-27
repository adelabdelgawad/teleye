import logging
from io import BytesIO

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.dependancies import CurrentUserDep, MinioDep

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/images/list")
async def list_images(
    user: CurrentUserDep,
    minio_manager: MinioDep,
    prefix: str = Query("", description="Filter images by prefix path"),
):
    """List all images with their accessible URLs.

    This endpoint retrieves a list of all stored images with optional prefix filtering.

    Args:
        minio_manager: MinIO manager dependency for storage operations.
        prefix: Optional prefix to filter images by path.

    Example:
        GET /images/list?prefix=2025/01/
        Returns images from January 2025 folder.
    """
    try:
        images = minio_manager.list_images(prefix=prefix)
        return {"images": images}
    except Exception as e:
        logger.error(f"Error listing images: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/images/url/{object_name:path}")
async def get_image_url(
    user: CurrentUserDep,
    minio_manager: MinioDep,
    object_name: str,
    use_presigned: bool = Query(
        False, description="Use presigned URL for temporary access"
    ),
):
    """Get URL for accessing an image.

    This endpoint returns either a public or presigned URL for image access.

    Args:
        minio_manager: MinIO manager dependency for storage operations.
        object_name: The path/name of the image object.
        use_presigned: Whether to generate a temporary presigned URL.

    Example:
        GET /images/url/folder/image.jpg?use_presigned=true
        Returns presigned URL for temporary access.
    """
    try:
        if use_presigned:
            url = minio_manager.get_presigned_url(object_name)
        else:
            url = minio_manager.get_public_url(object_name)

        return {"object_name": object_name, "url": url}
    except Exception as e:
        logger.error(f"Error getting image URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/images/download/{object_name:path}")
async def download_image(
    user: CurrentUserDep, minio_manager: MinioDep, object_name: str
):
    """Download image directly through the API.

    This endpoint streams the image data directly to the client.

    Args:
        minio_manager: MinIO manager dependency for storage operations.
        object_name: The path/name of the image to download.

    Example:
        GET /images/download/folder/image.jpg
        Downloads the image file directly.
    """
    try:
        image_data = minio_manager.download_image(object_name)

        # Determine content type from file extension
        content_type = "image/jpeg"
        if object_name.endswith(".png"):
            content_type = "image/png"
        elif object_name.endswith(".gif"):
            content_type = "image/gif"
        elif object_name.endswith(".webp"):
            content_type = "image/webp"

        return StreamingResponse(
            BytesIO(image_data),
            media_type=content_type,
            headers={
                "Content-Disposition": f"inline; filename={object_name.split('/')[-1]}"
            },
        )
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        raise HTTPException(status_code=404, detail="Image not found")
