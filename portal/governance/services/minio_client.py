"""MinIO service: thin wrapper around the official minio client."""
import io
import logging
from typing import Iterable

from django.conf import settings
from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinIOService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.buckets = settings.MINIO_BUCKETS

    # ---------- buckets ----------
    def ensure_buckets(self):
        for key, name in self.buckets.items():
            if not self.client.bucket_exists(name):
                self.client.make_bucket(name)
                logger.info("Created MinIO bucket: %s", name)

    def bucket(self, key: str) -> str:
        return self.buckets[key]

    # ---------- objects ----------
    def put_bytes(self, bucket_key: str, object_name: str, data: bytes, content_type: str = "application/octet-stream"):
        bucket = self.bucket(bucket_key)
        self.client.put_object(bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
        return f"{bucket}/{object_name}"

    def put_stream(self, bucket_key: str, object_name: str, stream, length: int, content_type: str = "application/octet-stream"):
        bucket = self.bucket(bucket_key)
        self.client.put_object(bucket, object_name, stream, length=length, content_type=content_type)
        return f"{bucket}/{object_name}"

    def get_object_bytes(self, bucket_key: str, object_name: str) -> bytes:
        bucket = self.bucket(bucket_key)
        resp = self.client.get_object(bucket, object_name)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def list_objects(self, bucket_key: str, prefix: str = "") -> Iterable[str]:
        bucket = self.bucket(bucket_key)
        for obj in self.client.list_objects(bucket, prefix=prefix, recursive=True):
            yield obj.object_name

    def stat(self, bucket_key: str, object_name: str):
        try:
            return self.client.stat_object(self.bucket(bucket_key), object_name)
        except S3Error:
            return None
