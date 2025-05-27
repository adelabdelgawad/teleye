import json
import logging
from io import BytesIO
from typing import Optional

from minio import Minio
from minio.error import S3Error

from core.config import settings

logger = logging.getLogger(__name__)


class MinIOManager:
    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: bool = False,
    ):
        self.endpoint = endpoint or settings.minio.endpoint
        self.access_key = access_key or settings.minio.root_user
        self.secret_key = secret_key or settings.minio.root_password
        self.secure = secure

        self.client = Minio(
            endpoint=self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )
        self.bucket_name = "telegram-images"
        self._ensure_bucket_exists()
        self._set_bucket_policy()

    def _ensure_bucket_exists(self):
        """Ensure the bucket exists, create if it doesn't.

        This method checks for bucket existence and creates it
        if not found, with proper error handling.

        Example:
            self._ensure_bucket_exists()
        """
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created MinIO bucket: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Error with MinIO bucket: {e}")
            raise

    def _set_bucket_policy(self):
        """Set bucket policy to allow public read access.

        This method configures the bucket with a public read policy
        for accessible image URLs.

        Example:
            self._set_bucket_policy()
        """
        try:
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"],
                    }
                ],
            }

            self.client.set_bucket_policy(self.bucket_name, json.dumps(policy))
            logger.info(
                f"Set public read policy for bucket: {self.bucket_name}"
            )

        except S3Error as e:
            logger.warning(f"Could not set bucket policy: {e}")

    def upload_image(
        self,
        image_data: bytes,
        object_name: str,
        content_type: str = "image/jpeg",
    ) -> str:
        """Upload image to MinIO and return the accessible URL.

        This method uploads image data to MinIO storage and returns
        a public URL for accessing the uploaded image.

        Args:
            image_data: Binary image data to upload.
            object_name: The storage path/name for the image.
            content_type: MIME type of the image.

        Example:
            url = manager.upload_image(image_bytes, "folder/image.jpg", "image/jpeg")
        """
        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=BytesIO(image_data),
                length=len(image_data),
                content_type=content_type,
            )

            protocol = "https" if self.secure else "http"
            url = f"{protocol}://{self.endpoint}/{self.bucket_name}/{object_name}"

            logger.info(f"Uploaded image to MinIO: {object_name}")
            return url

        except S3Error as e:
            logger.error(f"Error uploading image to MinIO: {e}")
            raise

    def get_public_url(self, object_name: str) -> str:
        """Generate public URL.

        This method constructs a public URL for accessing
        a stored object in MinIO.

        Args:
            object_name: The storage path/name of the object.

        Example:
            url = manager.get_public_url("folder/image.jpg")
        """
        protocol = "https" if self.secure else "http"
        return f"{protocol}://{self.endpoint}/{self.bucket_name}/{object_name}"
