"""AWS S3 connector — uses boto3. Requires AWS creds in env."""
import logging
from typing import Any

import boto3
from django.conf import settings

from .base import BaseConnector

logger = logging.getLogger(__name__)


class S3Connector(BaseConnector):
    kind = "s3"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.bucket = (config or {}).get("bucket") or settings.AWS["S3_BUCKET"]
        self.client = boto3.client(
            "s3",
            region_name=settings.AWS["REGION"],
            aws_access_key_id=settings.AWS["ACCESS_KEY_ID"] or None,
            aws_secret_access_key=settings.AWS["SECRET_ACCESS_KEY"] or None,
        )

    def discover_datasets(self, prefix: str = "") -> list[dict]:
        if not self.bucket:
            return []
        out: dict[str, dict] = {}
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if not key.endswith(".parquet"):
                    continue
                parts = key.split("/")
                if len(parts) >= 2:
                    ds = parts[-2]
                    out[ds] = {"name": ds, "path": f"s3://{self.bucket}/{key}", "format": "parquet"}
        return list(out.values())

    def read_schema(self, dataset_name: str) -> list[dict]:
        # Lazy: read first object whose key contains the dataset name
        # For a real impl we'd use pyarrow + s3fs. Keeping minimal here.
        return []

    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        return []

    def health(self) -> dict[str, Any]:
        if not self.bucket or not settings.AWS["ACCESS_KEY_ID"]:
            return {"kind": self.kind, "status": "not_configured"}
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return {"kind": self.kind, "status": "ok", "bucket": self.bucket}
        except Exception as e:
            return {"kind": self.kind, "status": "error", "error": str(e)}
