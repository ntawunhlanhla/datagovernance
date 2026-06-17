"""Mock catalog adapter: writes JSON payloads to ./alation_sync/ (kept name for back-compat)."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

from .base import BaseCatalogClient

logger = logging.getLogger(__name__)


class MockCatalogClient(BaseCatalogClient):
    provider = "mock"

    def __init__(self):
        self.dir = Path(settings.ALATION["MOCK_DIR"])
        self.dir.mkdir(parents=True, exist_ok=True)

    def publish_data_product(self, dp: dict) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in dp.get("name", "data_product"))
        path = self.dir / f"{ts}_{safe}.json"
        path.write_text(json.dumps({
            "provider": "mock",
            "captured_at": ts,
            "payload": dp,
        }, indent=2, default=str))
        logger.info("[MOCK CATALOG] Wrote payload to %s", path)
        return {"external_id": f"mock-{ts}", "status": "mocked", "file": str(path)}
