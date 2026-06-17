"""Excel Data Product Definition generator & parser.

Generated workbook sheets:
  - data_product   (single row: name, description, domain, owner_email, tier, tags)
  - datasets       (one row per dataset)
  - columns        (one row per column)
  - lineage        (one row per edge)
  - quality_rules  (one row per rule)
"""
import io
from typing import Any

import pandas as pd


def build_excel_from_spec(spec: dict, generation_run_id: int | None = None) -> bytes:
    """spec: the LLM-designed JSON (see llm_designer.py)."""
    product_name = spec.get("product_name") or spec.get("instance_name", "data_product").lower().replace(" ", "_")
    instance_name = spec.get("instance_name", product_name)

    dp_df = pd.DataFrame([{
        "name": product_name,
        "description": f"{instance_name}: {spec.get('description', '')}",
        "domain": spec.get("domain", ""),
        "owner_email": f"data-owner@{spec.get('domain', 'example')}.example.com",
        "tier": "gold",
        "tags": ",".join([spec.get("domain", ""), "auto-generated", instance_name]),
        "generation_run_id": generation_run_id or "",
    }])

    ds_rows = []
    col_rows = []
    qr_rows = []
    for d in spec.get("datasets", []):
        ds_rows.append({
            "dataset_name": d["name"],
            "minio_path": f"raw/{product_name}/{d['name']}/data.parquet",
            "format": "parquet",
            "refresh_cadence": "daily",
            "pii_flag": bool(d.get("pii_flag", False)),
            "description": d.get("description", ""),
        })
        for i, c in enumerate(d.get("columns", [])):
            col_rows.append({
                "dataset_name": d["name"],
                "column_name": c["name"],
                "data_type": c.get("data_type", "string"),
                "nullable": bool(c.get("nullable", True)),
                "description": c.get("description", ""),
                "pii": bool(c.get("pii", False)),
                "business_glossary_term": c.get("business_glossary_term", ""),
                "ordinal": i,
            })

    for rule in spec.get("quality_rules", []):
        qr_rows.append({
            "dataset_name": rule.get("dataset", ""),
            "column_name": rule.get("column", ""),
            "rule_type": rule.get("rule_type", ""),
            "expression": rule.get("expression", ""),
        })

    ln_rows = [{
        "upstream_dataset": e.get("upstream", ""),
        "downstream_dataset": e.get("downstream", ""),
        "transformation": e.get("transformation", ""),
    } for e in spec.get("lineage", [])]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        dp_df.to_excel(writer, sheet_name="data_product", index=False)
        pd.DataFrame(ds_rows).to_excel(writer, sheet_name="datasets", index=False)
        pd.DataFrame(col_rows).to_excel(writer, sheet_name="columns", index=False)
        pd.DataFrame(ln_rows).to_excel(writer, sheet_name="lineage", index=False)
        pd.DataFrame(qr_rows).to_excel(writer, sheet_name="quality_rules", index=False)
    return buf.getvalue()


def parse_excel(file_bytes: bytes) -> dict[str, Any]:
    """Parse an uploaded Excel into a structured dict."""
    bio = io.BytesIO(file_bytes)
    xl = pd.ExcelFile(bio, engine="openpyxl")

    def sheet(name: str) -> pd.DataFrame:
        if name in xl.sheet_names:
            return xl.parse(name).fillna("")
        return pd.DataFrame()

    dp_df = sheet("data_product")
    ds_df = sheet("datasets")
    col_df = sheet("columns")
    ln_df = sheet("lineage")
    qr_df = sheet("quality_rules")

    if dp_df.empty:
        raise ValueError("Sheet 'data_product' is missing or empty")
    dp_row = dp_df.iloc[0].to_dict()

    tags_raw = dp_row.get("tags", "")
    tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()] if tags_raw else []

    datasets = []
    for _, d in ds_df.iterrows():
        ds_name = str(d["dataset_name"])
        cols = [
            {
                "name": str(r["column_name"]),
                "data_type": str(r.get("data_type", "string")),
                "nullable": bool(r.get("nullable", True)) if str(r.get("nullable", "")).lower() not in ("false", "0") else False,
                "description": str(r.get("description", "")),
                "pii": str(r.get("pii", "")).lower() in ("true", "1", "yes"),
                "business_glossary_term": str(r.get("business_glossary_term", "")),
                "ordinal": int(r.get("ordinal", 0) or 0),
            }
            for _, r in col_df[col_df["dataset_name"] == ds_name].iterrows()
        ]
        rules = [
            {
                "column_name": str(r.get("column_name", "")),
                "rule_type": str(r.get("rule_type", "")),
                "expression": str(r.get("expression", "")),
            }
            for _, r in qr_df[qr_df["dataset_name"] == ds_name].iterrows()
        ] if not qr_df.empty else []
        datasets.append({
            "name": ds_name,
            "minio_path": str(d.get("minio_path", "")),
            "format": str(d.get("format", "parquet")),
            "refresh_cadence": str(d.get("refresh_cadence", "daily")),
            "pii_flag": str(d.get("pii_flag", "")).lower() in ("true", "1", "yes"),
            "description": str(d.get("description", "")),
            "columns": cols,
            "quality_rules": rules,
        })

    lineage = [
        {
            "upstream": str(r.get("upstream_dataset", "")),
            "downstream": str(r.get("downstream_dataset", "")),
            "transformation": str(r.get("transformation", "")),
        }
        for _, r in ln_df.iterrows()
    ] if not ln_df.empty else []

    return {
        "name": str(dp_row["name"]),
        "description": str(dp_row.get("description", "")),
        "domain": str(dp_row.get("domain", "")),
        "owner_email": str(dp_row.get("owner_email", "")),
        "tier": str(dp_row.get("tier", "gold")),
        "tags": tags,
        "generation_run_id": dp_row.get("generation_run_id", "") or None,
        "datasets": datasets,
        "lineage": lineage,
    }
