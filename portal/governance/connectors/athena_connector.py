"""AWS Athena connector — discovers tables/columns via Glue Catalog + can run queries."""
import logging
import time
from typing import Any

import boto3
from django.conf import settings

from .base import BaseConnector

logger = logging.getLogger(__name__)


class AthenaConnector(BaseConnector):
    kind = "athena"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        cfg = config or {}
        self.database = cfg.get("database") or settings.AWS["GLUE_DATABASE"]
        self.output = cfg.get("output_location") or settings.AWS["ATHENA_OUTPUT"]
        self.athena = boto3.client(
            "athena",
            region_name=settings.AWS["REGION"],
            aws_access_key_id=settings.AWS["ACCESS_KEY_ID"] or None,
            aws_secret_access_key=settings.AWS["SECRET_ACCESS_KEY"] or None,
        )
        self.glue = boto3.client(
            "glue",
            region_name=settings.AWS["REGION"],
            aws_access_key_id=settings.AWS["ACCESS_KEY_ID"] or None,
            aws_secret_access_key=settings.AWS["SECRET_ACCESS_KEY"] or None,
        )

    def discover_datasets(self, prefix: str = "") -> list[dict]:
        if not self.database:
            return []
        out = []
        paginator = self.glue.get_paginator("get_tables")
        for page in paginator.paginate(DatabaseName=self.database):
            for t in page.get("TableList", []):
                if prefix and not t["Name"].startswith(prefix):
                    continue
                out.append({"name": t["Name"], "path": t.get("StorageDescriptor", {}).get("Location"), "format": "athena"})
        return out

    def read_schema(self, dataset_name: str) -> list[dict]:
        if not self.database:
            return []
        t = self.glue.get_table(DatabaseName=self.database, Name=dataset_name)["Table"]
        cols = t.get("StorageDescriptor", {}).get("Columns", []) + t.get("PartitionKeys", [])
        return [{"name": c["Name"], "data_type": c["Type"], "nullable": True} for c in cols]

    def _run_query(self, sql: str) -> list[dict]:
        if not self.output:
            return []
        q = self.athena.start_query_execution(QueryString=sql, QueryExecutionContext={"Database": self.database}, ResultConfiguration={"OutputLocation": self.output})
        qid = q["QueryExecutionId"]
        for _ in range(60):
            s = self.athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
            if s in ("SUCCEEDED", "FAILED", "CANCELLED"):
                if s != "SUCCEEDED":
                    return []
                break
            time.sleep(1)
        res = self.athena.get_query_results(QueryExecutionId=qid)
        rows = res["ResultSet"]["Rows"]
        if not rows:
            return []
        header = [c["VarCharValue"] for c in rows[0]["Data"]]
        return [dict(zip(header, [c.get("VarCharValue") for c in r["Data"]])) for r in rows[1:]]

    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        return self._run_query(f'SELECT * FROM "{self.database}"."{dataset_name}" LIMIT {n}')

    def health(self) -> dict[str, Any]:
        if not self.database or not settings.AWS["ACCESS_KEY_ID"]:
            return {"kind": self.kind, "status": "not_configured"}
        try:
            self.glue.get_database(Name=self.database)
            return {"kind": self.kind, "status": "ok", "database": self.database}
        except Exception as e:
            return {"kind": self.kind, "status": "error", "error": str(e)}
