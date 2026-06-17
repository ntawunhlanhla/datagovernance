"""Marquez OpenLineage client (HTTP)."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class MarquezClient:
    def __init__(self, base_url: str | None = None, namespace: str | None = None):
        self.base_url = (base_url or settings.MARQUEZ_URL).rstrip("/")
        self.namespace = namespace or settings.MARQUEZ_NAMESPACE

    # ---------- namespace ----------
    def ensure_namespace(self) -> None:
        url = f"{self.base_url}/api/v1/namespaces/{self.namespace}"
        r = requests.put(url, json={"ownerName": "metadata-governance", "description": "auto-created"}, timeout=15)
        if not r.ok:
            logger.warning("Marquez namespace put failed: %s", r.text)

    # ---------- OpenLineage events ----------
    def emit_run(self, job_name: str, outputs: Iterable[dict], inputs: Iterable[dict] = (), facets: dict | None = None) -> str:
        """Emit START + COMPLETE OpenLineage events for a job that produced 'outputs'."""
        run_id = str(uuid.uuid4())
        base = {
            "eventTime": _now_iso(),
            "producer": "https://github.com/metadata-governance-platform",
            "job": {"namespace": self.namespace, "name": job_name, "facets": facets or {}},
            "run": {"runId": run_id},
            "inputs": list(inputs),
            "outputs": list(outputs),
        }
        url = f"{self.base_url}/api/v1/lineage"
        for et in ("START", "COMPLETE"):
            event = {**base, "eventType": et, "eventTime": _now_iso()}
            r = requests.post(url, json=event, timeout=30)
            if not r.ok:
                logger.warning("Marquez %s event failed: %s %s", et, r.status_code, r.text)
        return run_id

    @staticmethod
    def dataset_descriptor(name: str, columns: list[dict], description: str = "", source_uri: str = "") -> dict:
        """Build an OpenLineage dataset descriptor with schema facet."""
        return {
            "namespace": settings.MARQUEZ_NAMESPACE,
            "name": name,
            "facets": {
                "schema": {
                    "_producer": "https://github.com/metadata-governance-platform",
                    "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/SchemaDatasetFacet.json",
                    "fields": [
                        {"name": c["name"], "type": c.get("data_type", "string"), "description": c.get("description", "")}
                        for c in columns
                    ],
                },
                "documentation": {
                    "_producer": "https://github.com/metadata-governance-platform",
                    "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/DocumentationDatasetFacet.json",
                    "description": description or name,
                },
                **({"dataSource": {
                    "_producer": "https://github.com/metadata-governance-platform",
                    "_schemaURL": "https://openlineage.io/spec/facets/1-0-0/DatasourceDatasetFacet.json",
                    "name": "minio",
                    "uri": source_uri,
                }} if source_uri else {}),
            },
        }
