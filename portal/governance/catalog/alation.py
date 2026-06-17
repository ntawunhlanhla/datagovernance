"""Alation adapter (real API). For mock-mode, use MockCatalogClient."""
import logging
import time
from typing import Any

import requests
from django.conf import settings

from .base import BaseCatalogClient

logger = logging.getLogger(__name__)


class AlationError(Exception):
    pass


class AlationClient(BaseCatalogClient):
    provider = "alation"

    def __init__(self):
        self.cfg = settings.ALATION
        self._access_token: str | None = None
        self._access_token_expiry: float = 0

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expiry:
            return self._access_token
        base = self.cfg["BASE_URL"].rstrip("/")
        r = requests.post(
            f"{base}/integration/v1/createAPIAccessToken/",
            json={
                "refresh_token": self.cfg["REFRESH_TOKEN"],
                "user_id": int(self.cfg["USER_ID"]) if self.cfg["USER_ID"] else None,
            },
            timeout=30,
        )
        if not r.ok:
            raise AlationError(f"Failed to mint access token: {r.status_code} {r.text}")
        self._access_token = r.json()["api_access_token"]
        self._access_token_expiry = time.time() + 50 * 60
        return self._access_token

    def _headers(self) -> dict:
        return {"Token": self._get_access_token(), "Content-Type": "application/json", "Accept": "application/json"}

    def _build_payload(self, dp: dict) -> dict[str, Any]:
        return {
            "data_source_id": self.cfg.get("DATA_SOURCE_ID") or None,
            "folder_id": self.cfg.get("FOLDER_ID") or None,
            "object_type": "data_product",
            "title": dp.get("name"),
            "description": dp.get("description", ""),
            "custom_fields": {
                "domain": dp.get("domain"),
                "owner_email": dp.get("owner_email"),
                "tier": dp.get("tier"),
                "tags": dp.get("tags", []),
                "contract_url": dp.get("contract_url"),
            },
            "datasets": [{
                "name": d["name"],
                "physical_path": d.get("minio_path"),
                "format": d.get("format", "parquet"),
                "columns": [{
                    "name": c["name"],
                    "type": c["data_type"],
                    "nullable": c.get("nullable", True),
                    "description": c.get("description", ""),
                    "pii": c.get("pii", False),
                    "glossary_term": c.get("business_glossary_term", ""),
                } for c in d.get("columns", [])],
            } for d in dp.get("datasets", [])],
            "lineage": [{"upstream": e["upstream"], "downstream": e["downstream"], "transformation": e.get("transformation", "")}
                        for e in dp.get("lineage", [])],
        }

    def publish_data_product(self, dp: dict) -> dict[str, Any]:
        base = self.cfg["BASE_URL"].rstrip("/")
        payload = self._build_payload(dp)
        r = requests.post(f"{base}/integration/v2/custom_object/", json=payload, headers=self._headers(), timeout=60)
        if not r.ok:
            raise AlationError(f"Alation publish failed: {r.status_code} {r.text}")
        data = r.json()
        return {
            "external_id": str(data.get("id") or data.get("oid") or ""),
            "status": "published",
            "response": data,
        }
