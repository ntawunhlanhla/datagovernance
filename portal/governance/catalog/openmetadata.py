"""OpenMetadata catalog adapter.

Publishes a Data Product via OpenMetadata REST API. Bot JWT token auth.

The JWT can be supplied explicitly via OPENMETADATA_JWT_TOKEN, OR it will be
auto-fetched at runtime by logging into the OpenMetadata admin account
(default: admin@open-metadata.org / admin) and reading the ingestion-bot's
authentication mechanism. The auto-fetched token is cached in memory.

Pipeline performed for each upload:
  1. ensure Database Service ("MetadataGovernancePlatform", type "CustomDatabase")
  2. ensure Database ("default")
  3. ensure DatabaseSchema (== data product domain)
  4. for each dataset: create/upsert Table with columns + tags
  5. create/upsert Domain (== dp.domain)
  6. create/upsert DataProduct linking the tables
  7. POST lineage edges between tables
"""
import base64
import logging
import time
from typing import Any

import requests
from django.conf import settings

from .base import BaseCatalogClient

logger = logging.getLogger(__name__)


class OpenMetadataError(Exception):
    pass


# Endpoint suffixes to try for fetching the ingestion-bot JWT (varies by OM version)
_BOT_JWT_ENDPOINTS = [
    "/api/v1/users/auth-mechanism/ingestion-bot",
    "/api/v1/users/name/ingestion-bot?fields=authenticationMechanism",
    "/api/v1/bots/name/ingestion-bot",
]


def _extract_jwt(payload: dict) -> str | None:
    """Walk the response structure for a JWTToken value (OM API shape differs by version)."""
    if not isinstance(payload, dict):
        return None
    # Direct
    if payload.get("JWTToken"):
        return payload["JWTToken"]
    # config.JWTToken
    cfg = payload.get("config")
    if isinstance(cfg, dict) and cfg.get("JWTToken"):
        return cfg["JWTToken"]
    # authenticationMechanism.config.JWTToken (user-name endpoint)
    am = payload.get("authenticationMechanism")
    if isinstance(am, dict):
        c = am.get("config") or {}
        if c.get("JWTToken"):
            return c["JWTToken"]
    # Recurse one level (covers nested wrappers)
    for v in payload.values():
        if isinstance(v, dict):
            t = _extract_jwt(v)
            if t:
                return t
    return None


class OpenMetadataClient(BaseCatalogClient):
    provider = "openmetadata"

    DEFAULT_SERVICE_NAME = "MetadataGovernancePlatform"
    DEFAULT_DATABASE_NAME = "default"
    SERVICE_TYPE = "CustomDatabase"

    # Class-level cache so multiple instances share the bootstrapped JWT
    _cached_jwt: str | None = None
    _cached_jwt_expires_at: float = 0

    def __init__(self):
        cfg = settings.OPENMETADATA
        self.base = cfg["BASE_URL"].rstrip("/")
        self.service_name = cfg.get("SERVICE_NAME") or self.DEFAULT_SERVICE_NAME
        self.admin_email = cfg.get("ADMIN_EMAIL", "admin@open-metadata.org")
        self.admin_password = cfg.get("ADMIN_PASSWORD", "admin")

        explicit_token = cfg.get("JWT_TOKEN") or ""
        self.jwt = explicit_token.strip() or self._bootstrap_jwt()
        if not self.jwt:
            raise OpenMetadataError(
                "Could not obtain an OpenMetadata JWT. Provide OPENMETADATA_JWT_TOKEN explicitly "
                "OR ensure OPENMETADATA_ADMIN_EMAIL/OPENMETADATA_ADMIN_PASSWORD can log in."
            )
        self.headers = {
            "Authorization": f"Bearer {self.jwt}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ---------------------- JWT auto-bootstrap ----------------------
    def _bootstrap_jwt(self) -> str:
        """Log in as admin → fetch the ingestion-bot's permanent JWT. Cached for 50 min."""
        cls = type(self)
        if cls._cached_jwt and time.time() < cls._cached_jwt_expires_at:
            return cls._cached_jwt

        logger.info("OpenMetadata: bootstrapping bot JWT by logging in as %s", self.admin_email)
        b64_pw = base64.b64encode(self.admin_password.encode()).decode()
        try:
            r = requests.post(
                f"{self.base}/api/v1/users/login",
                json={"email": self.admin_email, "password": b64_pw},
                timeout=15,
            )
            if not r.ok:
                logger.warning("OpenMetadata admin login failed: %s %s", r.status_code, r.text[:300])
                return ""
            admin_token = r.json().get("accessToken")
            if not admin_token:
                logger.warning("OpenMetadata login returned no accessToken: %s", r.text[:300])
                return ""
        except Exception as e:
            logger.warning("OpenMetadata login HTTP error: %s", e)
            return ""

        auth_headers = {"Authorization": f"Bearer {admin_token}", "Accept": "application/json"}
        for suffix in _BOT_JWT_ENDPOINTS:
            try:
                br = requests.get(f"{self.base}{suffix}", headers=auth_headers, timeout=15)
                if not br.ok:
                    logger.debug("Bot JWT endpoint %s -> %s", suffix, br.status_code)
                    continue
                jwt = _extract_jwt(br.json())
                if jwt:
                    cls._cached_jwt = jwt
                    cls._cached_jwt_expires_at = time.time() + 50 * 60
                    logger.info("OpenMetadata bot JWT bootstrapped successfully (from %s)", suffix)
                    return jwt
            except Exception as e:
                logger.debug("Bot JWT fetch error on %s: %s", suffix, e)

        logger.warning("OpenMetadata: exhausted all bot JWT endpoints, no token found")
        return ""

    def _refresh_jwt_if_needed(self) -> None:
        """Re-run bootstrap if cached token is about to expire."""
        cls = type(self)
        if cls._cached_jwt and time.time() >= cls._cached_jwt_expires_at:
            cls._cached_jwt = None
            new_token = self._bootstrap_jwt()
            if new_token:
                self.jwt = new_token
                self.headers["Authorization"] = f"Bearer {new_token}"

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
