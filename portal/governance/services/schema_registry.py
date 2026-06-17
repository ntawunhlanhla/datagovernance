"""Confluent Schema Registry REST client."""
import json
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SchemaRegistryClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.SCHEMA_REGISTRY_URL).rstrip("/")

    def register(self, subject: str, schema: dict, schema_type: str = "AVRO") -> dict:
        """Register a schema and return {'id': ..., 'version': ...}."""
        url = f"{self.base_url}/subjects/{subject}/versions"
        payload = {"schema": json.dumps(schema), "schemaType": schema_type}
        r = requests.post(url, json=payload, headers={"Content-Type": "application/vnd.schemaregistry.v1+json"}, timeout=30)
        if not r.ok:
            logger.error("Schema registry error %s: %s", r.status_code, r.text)
            r.raise_for_status()
        result = r.json()
        # Fetch latest version metadata
        v = requests.get(f"{self.base_url}/subjects/{subject}/versions/latest", timeout=30).json()
        return {"id": result.get("id"), "version": v.get("version"), "subject": subject}

    def list_subjects(self) -> list[str]:
        r = requests.get(f"{self.base_url}/subjects", timeout=15)
        r.raise_for_status()
        return r.json()

    def get_latest(self, subject: str) -> dict:
        r = requests.get(f"{self.base_url}/subjects/{subject}/versions/latest", timeout=15)
        r.raise_for_status()
        return r.json()


def pandas_dtype_to_avro(dtype_str: str) -> dict | str:
    """Map a column dtype string to an Avro type definition."""
    s = dtype_str.lower()
    if "int" in s:
        return "long"
    if "float" in s or "double" in s or "decimal" in s:
        return "double"
    if "bool" in s:
        return "boolean"
    if "datetime" in s or "timestamp" in s:
        return {"type": "long", "logicalType": "timestamp-millis"}
    if "date" in s:
        return {"type": "int", "logicalType": "date"}
    return "string"


def build_avro_schema(record_name: str, namespace: str, columns: list[dict]) -> dict:
    """columns: list of {name, data_type, nullable}."""
    fields = []
    for c in columns:
        avro_type = pandas_dtype_to_avro(c.get("data_type", "string"))
        if c.get("nullable", True):
            avro_type = ["null", avro_type]
        field = {"name": c["name"], "type": avro_type}
        if c.get("nullable", True):
            field["default"] = None
        if c.get("description"):
            field["doc"] = c["description"]
        fields.append(field)
    return {
        "type": "record",
        "name": record_name,
        "namespace": namespace,
        "fields": fields,
    }
