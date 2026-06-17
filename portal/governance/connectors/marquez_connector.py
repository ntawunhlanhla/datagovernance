"""Marquez connector — reads lineage / datasets already registered in Marquez."""
import logging
from typing import Any

import requests
from django.conf import settings

from .base import BaseConnector

logger = logging.getLogger(__name__)


class MarquezConnector(BaseConnector):
    kind = "marquez"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.base = (config or {}).get("url") or settings.MARQUEZ_URL
        self.namespace = (config or {}).get("namespace") or settings.MARQUEZ_NAMESPACE

    def discover_datasets(self, prefix: str = "") -> list[dict]:
        try:
            r = requests.get(f"{self.base}/api/v1/namespaces/{self.namespace}/datasets", timeout=15)
            r.raise_for_status()
            data = r.json().get("datasets", [])
            return [{"name": d["name"], "path": d.get("physicalName"), "format": "marquez"} for d in data if not prefix or d["name"].startswith(prefix)]
        except Exception as e:
            logger.warning("Marquez discover failed: %s", e)
            return []

    def read_schema(self, dataset_name: str) -> list[dict]:
        try:
            r = requests.get(f"{self.base}/api/v1/namespaces/{self.namespace}/datasets/{dataset_name}", timeout=15)
            r.raise_for_status()
            d = r.json()
            fields = (d.get("facets", {}).get("schema") or {}).get("fields", [])
            return [{"name": f["name"], "data_type": f.get("type", "string"), "description": f.get("description", "")} for f in fields]
        except Exception as e:
            logger.warning("Marquez read_schema failed: %s", e)
            return []

    def read_sample(self, dataset_name: str, n: int = 10) -> list[dict]:
        return []

    def health(self) -> dict[str, Any]:
        try:
            r = requests.get(f"{self.base}/api/v1/namespaces", timeout=10)
            return {"kind": self.kind, "status": "ok" if r.ok else "error"}
        except Exception as e:
            return {"kind": self.kind, "status": "error", "error": str(e)}
