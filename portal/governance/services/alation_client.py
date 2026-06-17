"""Alation client with real & mock modes.

Real mode: exchanges Refresh Token for an API Access Token (cached in-memory),
then creates a Custom Field "Data Product" or registers a Data Product object.

Mock mode: writes the exact JSON payloads to /app/alation_sync/<timestamp>.json
so the user can verify the pipeline without an Alation tenant.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AlationError(Exception):
    pass


class AlationClient:
    def __init__(self):
        self.cfg = settings.ALATION
        self.mode = self.cfg.get("MODE", "mock")
        self._access_token: str | None = None
        self._access_token_expiry: float = 0
        if self.mode == "mock":
            Path(self.cfg["MOCK_DIR"]).mkdir(parents=True, exist_ok=True)

    # ----------------------- auth -----------------------
    def _get_access_token(self) -> str:
        """Exchange refresh token for API access token. Cached for 50 minutes."""
        if self._access_token and time.time() < self._access_token_expiry:
            return self._access_token

        base = self.cfg["BASE_URL"].rstrip("/")
        url = f"{base}/integration/v1/createAPIAccessToken/"
        payload = {
            "refresh_token": self.cfg["REFRESH_TOKEN"],
            "user_id": int(self.cfg["USER_ID"]) if self.cfg["USER_ID"] else None,
        }
        r = requests.post(url, json=payload, timeout=30)
        if not r.ok:
            raise AlationError(f"Failed to mint access token: {r.status_code} {r.text}")
        data = r.json()
        self._access_token = data["api_access_token"]
        self._access_token_expiry = time.time() + 50 * 60  # ~ 1h validity
        return self._access_token

    def _headers(self) -> dict:
        return {
            "Token": self._get_access_token(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ----------------------- Data Product publish -----------------------
    def publish_data_product(self, data_product: dict) -> dict:
        """
        data_product schema (internal):
        {
          "name", "description", "domain", "owner_email", "tier", "tags",
          "datasets": [{"name", "columns": [...], "minio_path", ...}],
          "lineage": [{"upstream", "downstream", "transformation"}],
          "contract_url": "...",
        }
        """
        if self.mode == "mock":
            return self._mock_publish(data_product)
        return self._real_publish(data_product)

    # ----------------------- mock -----------------------
    def _mock_publish(self, dp: dict) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_name = "".join(c if c.isalnum() else "_" for c in dp.get("name", "data_product"))
        path = Path(self.cfg["MOCK_DIR"]) / f"{ts}_{safe_name}.json"
        payload = {
            "alation_mode": "mock",
            "endpoint": "/integration/v2/data_product/",
            "method": "POST",
            "captured_at": ts,
            "payload": self._build_alation_payload(dp),
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("[ALATION MOCK] Wrote payload to %s", path)
        return {
            "alation_id": f"mock-{ts}",
            "status": "mocked",
            "file": str(path),
        }

    # ----------------------- real -----------------------
    def _real_publish(self, dp: dict) -> dict:
        base = self.cfg["BASE_URL"].rstrip("/")
        payload = self._build_alation_payload(dp)
        # Use Alation Custom Object API for Data Products (v2)
        url = f"{base}/integration/v2/custom_object/"
        r = requests.post(url, json=payload, headers=self._headers(), timeout=60)
        if not r.ok:
            raise AlationError(f"Alation publish failed: {r.status_code} {r.text}")
        data = r.json()
        alation_id = str(data.get("id") or data.get("oid") or "")
        logger.info("[ALATION] Published data product %s -> id=%s", dp.get("name"), alation_id)
        return {
            "alation_id": alation_id,
            "status": "published",
            "response": data,
        }

    # ----------------------- payload builder -----------------------
    def _build_alation_payload(self, dp: dict) -> dict[str, Any]:
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
            "datasets": [
                {
                    "name": d["name"],
                    "physical_path": d.get("minio_path"),
                    "format": d.get("format", "parquet"),
                    "columns": [
                        {
                            "name": c["name"],
                            "type": c["data_type"],
                            "nullable": c.get("nullable", True),
                            "description": c.get("description", ""),
                            "pii": c.get("pii", False),
                            "glossary_term": c.get("business_glossary_term", ""),
                        }
                        for c in d.get("columns", [])
                    ],
                }
                for d in dp.get("datasets", [])
            ],
            "lineage": [
                {"upstream": e["upstream"], "downstream": e["downstream"], "transformation": e.get("transformation", "")}
                for e in dp.get("lineage", [])
            ],
        }
