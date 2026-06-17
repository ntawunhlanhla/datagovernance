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


# ---------------------------------------------------------------------------
# BUILD
# ---------------------------------------------------------------------------
def _data_product_row(spec: dict, product_name: str, generation_run_id: int | None) -> dict:
    instance_name = spec.get("instance_name", product_name)
    return {
        "name": product_name,
        "description": f"{instance_name}: {spec.get('description', '')}",
        "domain": spec.get("domain", ""),
        "owner_email": f"data-owner@{spec.get('domain', 'example')}.example.com",
        "tier": "gold",
        "tags": ",".join([spec.get("domain", ""), "auto-generated", instance_name]),
        "generation_run_id": generation_run_id or "",
    }


def _dataset_row(d: dict, product_name: str) -> dict:
    return {
        "dataset_name": d["name"],
        "minio_path": f"raw/{product_name}/{d['name']}/data.parquet",
        "format": "parquet",
        "refresh_cadence": "daily",
        "pii_flag": bool(d.get("pii_flag", False)),
        "description": d.get("description", ""),
    }


def _column_rows(d: dict) -> list[dict]:
    return [
        {
            "dataset_name": d["name"],
            "column_name": c["name"],
            "data_type": c.get("data_type", "string"),
            "nullable": bool(c.get("nullable", True)),
            "description": c.get("description", ""),
            "pii": bool(c.get("pii", False)),
            "business_glossary_term": c.get("business_glossary_term", ""),
            "ordinal": i,
        }
        for i, c in enumerate(d.get("columns", []))
    ]


def build_excel_from_spec(spec: dict, generation_run_id: int | None = None) -> bytes:
    product_name = spec.get("product_name") or spec.get("instance_name", "data_product").lower().replace(" ", "_")

    dp_df = pd.DataFrame([_data_product_row(spec, product_name, generation_run_id)])

    ds_rows = []
    col_rows = []
    for d in spec.get("datasets", []):
        ds_rows.append(_dataset_row(d, product_name))
        col_rows.extend(_column_rows(d))

    qr_rows = [
        {
            "dataset_name": rule.get("dataset", ""),
            "column_name": rule.get("column", ""),
            "rule_type": rule.get("rule_type", ""),
            "expression": rule.get("expression", ""),
        }
        for rule in spec.get("quality_rules", [])
    ]
    ln_rows = [
        {
            "upstream_dataset": e.get("upstream", ""),
            "downstream_dataset": e.get("downstream", ""),
            "transformation": e.get("transformation", ""),
        }
        for e in spec.get("lineage", [])
    ]

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        dp_df.to_excel(writer, sheet_name="data_product", index=False)
        pd.DataFrame(ds_rows).to_excel(writer, sheet_name="datasets", index=False)
        pd.DataFrame(col_rows).to_excel(writer, sheet_name="columns", index=False)
        pd.DataFrame(ln_rows).to_excel(writer, sheet_name="lineage", index=False)
        pd.DataFrame(qr_rows).to_excel(writer, sheet_name="quality_rules", index=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PARSE
# ---------------------------------------------------------------------------
def _as_bool(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def _read_sheet(xl: pd.ExcelFile, name: str) -> pd.DataFrame:
    return xl.parse(name).fillna("") if name in xl.sheet_names else pd.DataFrame()


def _parse_columns(col_df: pd.DataFrame, dataset_name: str) -> list[dict]:
    if col_df.empty:
        return []
    rows = col_df[col_df["dataset_name"] == dataset_name]
    return [
        {
            "name": str(r["column_name"]),
            "data_type": str(r.get("data_type", "string")),
            # nullable defaults to True unless explicitly set to a false-y value
            "nullable": str(r.get("nullable", "true")).strip().lower() not in ("false", "0", "no", "n"),
            "description": str(r.get("description", "")),
            "pii": _as_bool(r.get("pii", "")),
            "business_glossary_term": str(r.get("business_glossary_term", "")),
            "ordinal": int(r.get("ordinal", 0) or 0),
        }
        for _, r in rows.iterrows()
    ]


def _parse_quality_rules(qr_df: pd.DataFrame, dataset_name: str) -> list[dict]:
    if qr_df.empty:
        return []
    rows = qr_df[qr_df["dataset_name"] == dataset_name]
    return [
        {
            "column_name": str(r.get("column_name", "")),
            "rule_type": str(r.get("rule_type", "")),
            "expression": str(r.get("expression", "")),
        }
        for _, r in rows.iterrows()
    ]


def _parse_dataset(d: pd.Series, col_df: pd.DataFrame, qr_df: pd.DataFrame) -> dict:
    name = str(d["dataset_name"])
    return {
        "name": name,
        "minio_path": str(d.get("minio_path", "")),
        "format": str(d.get("format", "parquet")),
        "refresh_cadence": str(d.get("refresh_cadence", "daily")),
        "pii_flag": _as_bool(d.get("pii_flag", "")),
        "description": str(d.get("description", "")),
        "columns": _parse_columns(col_df, name),
        "quality_rules": _parse_quality_rules(qr_df, name),
    }


def _parse_lineage(ln_df: pd.DataFrame) -> list[dict]:
    if ln_df.empty:
        return []
    return [
        {
            "upstream": str(r.get("upstream_dataset", "")),
            "downstream": str(r.get("downstream_dataset", "")),
            "transformation": str(r.get("transformation", "")),
        }
        for _, r in ln_df.iterrows()
    ]


def parse_excel(file_bytes: bytes) -> dict[str, Any]:
    """Parse an uploaded Excel into a structured dict."""
    xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    dp_df = _read_sheet(xl, "data_product")
    if dp_df.empty:
        raise ValueError("Sheet 'data_product' is missing or empty")

    dp_row = dp_df.iloc[0].to_dict()
    tags_raw = dp_row.get("tags", "")
    tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]

    ds_df = _read_sheet(xl, "datasets")
    col_df = _read_sheet(xl, "columns")
    ln_df = _read_sheet(xl, "lineage")
    qr_df = _read_sheet(xl, "quality_rules")

    datasets = [_parse_dataset(d, col_df, qr_df) for _, d in ds_df.iterrows()] if not ds_df.empty else []

    return {
        "name": str(dp_row["name"]),
        "description": str(dp_row.get("description", "")),
        "domain": str(dp_row.get("domain", "")),
        "owner_email": str(dp_row.get("owner_email", "")),
        "tier": str(dp_row.get("tier", "gold")),
        "tags": tags,
        "generation_run_id": dp_row.get("generation_run_id", "") or None,
        "datasets": datasets,
        "lineage": _parse_lineage(ln_df),
    }
