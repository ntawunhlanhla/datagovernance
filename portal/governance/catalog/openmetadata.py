"""OpenMetadata catalog adapter.

Publishes a Data Product via OpenMetadata REST API. Bot JWT token auth.

Pipeline performed for each upload:
  1. ensure Database Service ("MetadataGovernancePlatform", type "CustomDatabase")
  2. ensure Database ("default")
  3. ensure DatabaseSchema (== data product domain)
  4. for each dataset: create/upsert Table with columns + tags
  5. create/upsert Domain (== dp.domain)
  6. create/upsert DataProduct linking the tables
  7. POST lineage edges between tables
"""
import logging
from typing import Any

import requests
from django.conf import settings

from .base import BaseCatalogClient

logger = logging.getLogger(__name__)


class OpenMetadataError(Exception):
    pass


class OpenMetadataClient(BaseCatalogClient):
    provider = "openmetadata"

    DEFAULT_SERVICE_NAME = "MetadataGovernancePlatform"
    DEFAULT_DATABASE_NAME = "default"
    SERVICE_TYPE = "CustomDatabase"

    def __init__(self):
        cfg = settings.OPENMETADATA
        self.base = cfg["BASE_URL"].rstrip("/")
        self.jwt = cfg["JWT_TOKEN"]
        if not self.jwt:
            raise OpenMetadataError(
                "OPENMETADATA_JWT_TOKEN is empty. Get it from the UI: "
                "Settings → Bots → ingestion-bot → Copy Token, then paste into .env."
            )
        self.headers = {
            "Authorization": f"Bearer {self.jwt}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.service_name = cfg.get("SERVICE_NAME") or self.DEFAULT_SERVICE_NAME

    # ---------------- HTTP helpers ----------------
    def _get(self, path: str) -> requests.Response:
        return requests.get(f"{self.base}{path}", headers=self.headers, timeout=30)

    def _post(self, path: str, body: dict) -> dict:
        r = requests.post(f"{self.base}{path}", headers=self.headers, json=body, timeout=60)
        if not r.ok:
            raise OpenMetadataError(f"POST {path} -> {r.status_code}: {r.text}")
        return r.json()

    def _put(self, path: str, body: dict) -> dict:
        """OpenMetadata upsert is via PUT on collection endpoints (idempotent CreateXxx)."""
        r = requests.put(f"{self.base}{path}", headers=self.headers, json=body, timeout=60)
        if not r.ok:
            raise OpenMetadataError(f"PUT {path} -> {r.status_code}: {r.text}")
        return r.json()

    def _exists(self, path: str) -> dict | None:
        r = self._get(path)
        if r.status_code == 200:
            return r.json()
        return None

    # ---------------- ensures ----------------
    def ensure_database_service(self) -> dict:
        existing = self._exists(f"/api/v1/services/databaseServices/name/{self.service_name}")
        if existing:
            return existing
        payload = {
            "name": self.service_name,
            "displayName": "Metadata Governance Platform (MinIO)",
            "serviceType": self.SERVICE_TYPE,
            "description": "Auto-generated source for the Metadata Governance Platform pipeline.",
            "connection": {
                "config": {
                    "type": self.SERVICE_TYPE,
                    "sourcePythonClass": "metadata.ingestion.source.database.customdatabase.CustomDatabaseSource",
                    "connectionOptions": {"endpoint": settings.MINIO_PUBLIC_ENDPOINT},
                }
            },
        }
        return self._put("/api/v1/services/databaseServices", payload)

    def ensure_database(self, service_fqn: str) -> dict:
        fqn = f"{service_fqn}.{self.DEFAULT_DATABASE_NAME}"
        existing = self._exists(f"/api/v1/databases/name/{fqn}")
        if existing:
            return existing
        return self._put("/api/v1/databases", {
            "name": self.DEFAULT_DATABASE_NAME,
            "service": service_fqn,
        })

    def ensure_schema(self, database_fqn: str, schema_name: str) -> dict:
        safe = schema_name or "default"
        fqn = f"{database_fqn}.{safe}"
        existing = self._exists(f"/api/v1/databaseSchemas/name/{fqn}")
        if existing:
            return existing
        return self._put("/api/v1/databaseSchemas", {
            "name": safe,
            "database": database_fqn,
        })

    def ensure_domain(self, name: str) -> dict | None:
        if not name:
            return None
        existing = self._exists(f"/api/v1/domains/name/{name}")
        if existing:
            return existing
        return self._put("/api/v1/domains", {
            "name": name,
            "displayName": name.title(),
            "description": f"Auto-created domain '{name}' from the Metadata Governance Platform.",
            "domainType": "Aggregate",
        })

    # ---------------- table & lineage ----------------
    @staticmethod
    def _om_type(t: str) -> str:
        t = (t or "string").lower()
        if t in ("int", "integer"):
            return "INT"
        if t in ("long", "bigint"):
            return "BIGINT"
        if t in ("float",):
            return "FLOAT"
        if t in ("double", "decimal"):
            return "DOUBLE"
        if t in ("bool", "boolean"):
            return "BOOLEAN"
        if t == "date":
            return "DATE"
        if t in ("datetime", "timestamp"):
            return "TIMESTAMP"
        return "STRING"

    def upsert_table(self, schema_fqn: str, ds: dict) -> dict:
        columns = [
            {
                "name": c["name"],
                "dataType": self._om_type(c.get("data_type", "string")),
                "description": c.get("description", "") or None,
                "tags": ([{"tagFQN": "PII.Sensitive", "labelType": "Manual", "source": "Classification", "state": "Confirmed"}]
                         if c.get("pii") else []),
            }
            for c in ds.get("columns", [])
        ]
        payload = {
            "name": ds["name"],
            "databaseSchema": schema_fqn,
            "description": ds.get("description") or f"Auto-created dataset {ds['name']}.",
            "columns": columns,
            "tableType": "Regular",
        }
        return self._put("/api/v1/tables", payload)

    def add_lineage(self, from_table_id: str, to_table_id: str, transformation: str = ""):
        payload = {
            "edge": {
                "fromEntity": {"id": from_table_id, "type": "table"},
                "toEntity": {"id": to_table_id, "type": "table"},
                "lineageDetails": {
                    "description": transformation or "Auto-detected from pipeline",
                    "source": "Manual",
                },
            }
        }
        return self._put("/api/v1/lineage", payload)

    # ---------------- DataProduct ----------------
    def upsert_data_product(self, dp: dict, domain_fqn: str, table_fqns: list[str]) -> dict:
        payload = {
            "name": dp["name"],
            "displayName": dp["name"].replace("_", " ").title(),
            "description": dp.get("description") or "",
            "domain": domain_fqn,
            "owners": [],
            "assets": [{"id": None, "fullyQualifiedName": fqn, "type": "table"} for fqn in table_fqns],
            "tags": [{"tagFQN": f"Tier.{(dp.get('tier') or 'Tier3').title()}", "labelType": "Manual", "source": "Classification", "state": "Confirmed"}],
        }
        # The assets list requires either id or fqn; we send fqn. Strip None id.
        payload["assets"] = [{"fullyQualifiedName": fqn, "type": "table"} for fqn in table_fqns]
        return self._put("/api/v1/dataProducts", payload)

    # ---------------- main entrypoint ----------------
    def publish_data_product(self, dp: dict) -> dict[str, Any]:
        # 1. service + db + schema
        svc = self.ensure_database_service()
        svc_fqn = svc["fullyQualifiedName"]
        db = self.ensure_database(svc_fqn)
        db_fqn = db["fullyQualifiedName"]
        schema_name = dp.get("domain") or "default"
        schema = self.ensure_schema(db_fqn, schema_name)
        schema_fqn = schema["fullyQualifiedName"]

        # 2. domain
        domain = self.ensure_domain(schema_name)
        domain_fqn = domain["fullyQualifiedName"] if domain else schema_name

        # 3. tables
        table_fqns: list[str] = []
        table_by_name: dict[str, str] = {}
        for ds in dp.get("datasets", []):
            t = self.upsert_table(schema_fqn, ds)
            table_fqns.append(t["fullyQualifiedName"])
            table_by_name[ds["name"]] = t["id"]

        # 4. lineage edges between tables
        for edge in dp.get("lineage", []):
            up_id = table_by_name.get(edge.get("upstream"))
            dn_id = table_by_name.get(edge.get("downstream"))
            if up_id and dn_id:
                try:
                    self.add_lineage(up_id, dn_id, edge.get("transformation", ""))
                except OpenMetadataError as e:
                    logger.warning("Lineage edge failed: %s", e)

        # 5. Data Product
        result = self.upsert_data_product(dp, domain_fqn, table_fqns)
        return {
            "external_id": result.get("id", ""),
            "status": "published",
            "fqn": result.get("fullyQualifiedName"),
            "ui_url": f"{self.base}/dataProducts/{result.get('fullyQualifiedName')}",
            "response": result,
        }

    def health(self) -> dict[str, Any]:
        try:
            r = self._get("/api/v1/system/version")
            return {"provider": "openmetadata", "status": "ok" if r.ok else "error", "version": r.json().get("version") if r.ok else None}
        except Exception as e:
            return {"provider": "openmetadata", "status": "error", "error": str(e)}
