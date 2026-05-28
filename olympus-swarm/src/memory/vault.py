# vault.py - Cloudflare R2 File Vault Client
import asyncio
import logging
from typing import Any

import boto3
from botocore.config import Config

logger = logging.getLogger("olympus.memory.vault")

class FileVault:
    """Async Cloudflare R2 File Vault wrapper running blocking boto3 operations in non-blocking threadpools."""

    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket_name: str):
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com" if account_id else ""
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket_name = bucket_name
        self.s3_client: Any = None

        if self.endpoint_url and self.access_key and self.secret_key:
            # Configure boto3 with optimized timeouts
            config = Config(
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 3}
            )
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=config
            )
            logger.info("Cloudflare R2 File Vault client successfully created.")
        else:
            logger.warning("Cloudflare R2 credentials missing. File Vault disabled.")

    def _sync_upload(self, data: bytes, key: str) -> None:
        """Synchronous boto3 upload_fileobj implementation."""
        if not self.s3_client:
            return
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=data
        )

    def _sync_download(self, key: str) -> bytes | None:
        """Synchronous boto3 get_object implementation."""
        if not self.s3_client:
            return None
        response = self.s3_client.get_object(
            Bucket=self.bucket_name,
            Key=key
        )
        return response["Body"].read()

    async def upload_file(self, data: bytes, key: str) -> bool:
        """Uploads a byte stream to R2 asynchronously in a non-blocking thread executor."""
        if not self.s3_client:
            return False

        try:
            await asyncio.to_thread(self._sync_upload, data, key)
            logger.info(f"Successfully uploaded snapshot to R2 vault path: {key}.")
            return True
        except Exception as e:
            logger.error(f"Failed to upload file to R2: {e}")
            return False

    async def download_file(self, key: str) -> bytes | None:
        """Downloads a byte stream from R2 asynchronously in a non-blocking thread executor."""
        if not self.s3_client:
            return None

        try:
            return await asyncio.to_thread(self._sync_download, key)
        except Exception as e:
            logger.error(f"Failed to download file from R2: {e}")
            return None
