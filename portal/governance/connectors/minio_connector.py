"""MinIO connector — full implementation (reads Parquet directly)."""
import io
import logging
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from django.conf import settings

from .base import BaseConnector
from ..services.minio_client import MinIOService

logger = logging.getLogger(__name__)


class MinIOConnector(BaseConnector):
    kind = "minio"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.minio = MinIOService()
        self.bucket_key = (config or {}).get("bucket_key", "raw")

    def discover_datasets(self, prefix: str = "") -> list[dict]:
        out: dict[str, dict] = {}
        for obj in self.minio.list_objects(self.bucket_key, prefix=prefix):
            if not obj.endswith(".parquet"):
                continue
            # raw/<product>/<dataset>/data.parquet  => dataset = third segment
            parts = obj.split("/")
            if len(parts) >= 3:
                ds_name = parts[-2]
                out[ds_name] = {"name": ds_name, "path": f"{self.minio.bucket(self.bucket_key)}/{obj}", "format": "parquet"}
        return list(out.values())

    def _find_parquet(self, dataset_name: str) -> str | None:
        for obj in self.minio.list_objects(self.bucket_key):
            if obj.endswith(".parquet") and f"/{dataset_name}/" in f"/{obj}":
                return obj
        return None

    def read_schema(self, dataset_name: str) -> list[dict]:
        obj = self._find_parquet(dataset_name)
        if not obj:
            return []
        data = self.minio.get_object_bytes(self.bucket_key, obj)
        table = pq.read_table(io.BytesIO(data))
        return [{"name": f.name, "data_type": str(f.type), "nullable": f.nullable} for f in table.schema]

    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        obj = self._find_parquet(dataset_name)
        if not obj:
            return []
        data = self.minio.get_object_bytes(self.bucket_key, obj)
        df = pd.read_parquet(io.BytesIO(data))
        return df.head(n).to_dict(orient="records")

    def health(self) -> dict[str, Any]:
        try:
            list(self.minio.list_objects(self.bucket_key))
            return {"kind": self.kind, "status": "ok", "endpoint": settings.MINIO_ENDPOINT}
        except Exception as e:
            return {"kind": self.kind, "status": "error", "error": str(e)}
