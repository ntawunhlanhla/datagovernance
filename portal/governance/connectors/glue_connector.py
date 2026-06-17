"""AWS Glue Data Catalog connector."""
import logging
from typing import Any

import boto3
from django.conf import settings

from .base import BaseConnector

logger = logging.getLogger(__name__)


class GlueConnector(BaseConnector):
    kind = "glue"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.database = (config or {}).get("database") or settings.AWS["GLUE_DATABASE"]
        self.client = boto3.client(
            "glue",
            region_name=settings.AWS["REGION"],
            aws_access_key_id=settings.AWS["ACCESS_KEY_ID"] or None,
            aws_secret_access_key=settings.AWS["SECRET_ACCESS_KEY"] or None,
        )

    def discover_datasets(self, prefix: str = "") -> list[dict]:
        if not self.database:
            return []
        out = []
        paginator = self.client.get_paginator("get_tables")
        for page in paginator.paginate(DatabaseName=self.database):
            for t in page.get("TableList", []):
                if prefix and not t["Name"].startswith(prefix):
                    continue
                out.append({
                    "name": t["Name"],
                    "path": t.get("StorageDescriptor", {}).get("Location"),
                    "format": t.get("Parameters", {}).get("classification", "unknown"),
                })
        return out

    def read_schema(self, dataset_name: str) -> list[dict]:
        if not self.database:
            return []
        t = self.client.get_table(DatabaseName=self.database, Name=dataset_name)["Table"]
        cols = t.get("StorageDescriptor", {}).get("Columns", []) + t.get("PartitionKeys", [])
        return [{"name": c["Name"], "data_type": c["Type"], "nullable": True, "description": c.get("Comment", "")} for c in cols]

    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        return []

    def health(self) -> dict[str, Any]:
        if not self.database or not settings.AWS["ACCESS_KEY_ID"]:
            return {"kind": self.kind, "status": "not_configured"}
        try:
            self.client.get_database(Name=self.database)
            return {"kind": self.kind, "status": "ok", "database": self.database}
        except Exception as e:
            return {"kind": self.kind, "status": "error", "error": str(e)}
