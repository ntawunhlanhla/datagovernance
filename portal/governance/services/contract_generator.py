"""Data contract generator (Open Data Contract Specification-inspired YAML)."""
from datetime import datetime, timezone
import yaml


def build_contract(parsed: dict) -> str:
    """Build a YAML data contract from a parsed Excel definition (or LLM spec)."""
    now = datetime.now(timezone.utc).isoformat()
    schemas = []
    for d in parsed.get("datasets", []):
        schemas.append({
            "name": d["name"],
            "physicalName": d.get("minio_path"),
            "physicalType": d.get("format", "parquet"),
            "description": d.get("description", ""),
            "tags": ["pii"] if d.get("pii_flag") else [],
            "properties": [
                {
                    "name": c["name"],
                    "logicalType": c["data_type"],
                    "physicalType": c["data_type"],
                    "required": not c.get("nullable", True),
                    "description": c.get("description", ""),
                    "tags": (["pii"] if c.get("pii") else []) + ([c["business_glossary_term"]] if c.get("business_glossary_term") else []),
                }
                for c in d.get("columns", [])
            ],
            "quality": [
                {"rule": qr["rule_type"], "column": qr.get("column_name", ""), "expression": qr.get("expression", "")}
                for qr in d.get("quality_rules", [])
            ],
        })

    contract = {
        "dataContractSpecification": "0.9.3",
        "id": parsed["name"],
        "info": {
            "title": parsed["name"],
            "version": "1.0.0",
            "description": parsed.get("description", ""),
            "owner": parsed.get("owner_email", ""),
            "status": "active",
        },
        "tags": parsed.get("tags", []),
        "domain": parsed.get("domain", ""),
        "servers": {
            "production": {
                "type": "minio",
                "endpoint": "${MINIO_PUBLIC_ENDPOINT}",
                "format": "parquet",
            }
        },
        "schema": schemas,
        "lineage": parsed.get("lineage", []),
        "x-generated-at": now,
        "x-generator": "metadata-governance-platform",
    }
    return yaml.safe_dump(contract, sort_keys=False)
