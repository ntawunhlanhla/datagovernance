"""Data generator: turn an LLM spec into Parquet rows in MinIO."""
import logging
import random
import string
import uuid
from datetime import datetime, timedelta, date
from typing import Iterator

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

logger = logging.getLogger(__name__)

CHUNK_ROWS = 100_000  # rows per Parquet row-group for streaming writes


def _faker_value(fk: Faker, method: str):
    fn = getattr(fk, method, None) or fk.word
    val = fn()
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _gen_value(spec: dict, fk: Faker, seq_state: dict, fk_refs: dict, col_name: str):
    t = spec.get("type", "faker")
    if t == "sequence":
        seq_state[col_name] = seq_state.get(col_name, spec.get("start", 1) - 1) + 1
        return seq_state[col_name]
    if t == "uuid":
        return str(uuid.uuid4())
    if t == "email":
        return fk.email()
    if t == "faker":
        return _faker_value(fk, spec.get("method", "word"))
    if t == "choices":
        return random.choice(spec.get("values", [""]))
    if t == "int_range":
        return random.randint(int(spec.get("min", 0)), int(spec.get("max", 100)))
    if t == "float_range":
        v = random.uniform(float(spec.get("min", 0.0)), float(spec.get("max", 1.0)))
        return round(v, int(spec.get("decimals", 2)))
    if t == "date_range":
        start = datetime.fromisoformat(spec.get("start", "2020-01-01"))
        end = datetime.fromisoformat(spec.get("end", "2024-12-31"))
        delta = (end - start).days
        return (start + timedelta(days=random.randint(0, max(delta, 0)))).date().isoformat()
    if t == "foreign_key":
        ref = spec.get("references", "")
        if ref in fk_refs and fk_refs[ref]:
            return random.choice(fk_refs[ref])
        return random.randint(1, 1000)
    # default
    return "".join(random.choices(string.ascii_lowercase, k=8))


def _pa_schema(columns: list[dict]) -> pa.Schema:
    fields = []
    for c in columns:
        dt = c.get("data_type", "string").lower()
        if dt in ("int", "long", "bigint"):
            t = pa.int64()
        elif dt in ("float", "double", "decimal"):
            t = pa.float64()
        elif dt in ("bool", "boolean"):
            t = pa.bool_()
        elif dt == "date":
            t = pa.string()  # ISO date string for portability
        elif dt in ("datetime", "timestamp"):
            t = pa.string()
        else:
            t = pa.string()
        fields.append(pa.field(c["name"], t, nullable=c.get("nullable", True)))
    return pa.schema(fields)


def generate_dataset_to_parquet_stream(
    columns: list[dict],
    row_count: int,
    fk_refs: dict[str, list],
    chunk_size: int = CHUNK_ROWS,
) -> Iterator[bytes]:
    """Yields Parquet file bytes built in chunks (single-file, streamed via BufferedWriter).

    Note: for simplicity we collect all chunks into one in-memory bytes object. For
    100M-row Large generation we write to a temp file then yield its bytes.
    """
    import io
    import tempfile
    import os

    fk = Faker()
    Faker.seed(random.randint(0, 10_000))
    seq_state: dict[str, int] = {}
    schema = _pa_schema(columns)

    # For very large sets, write to a temp file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".parquet")
    tmp.close()
    writer = pq.ParquetWriter(tmp.name, schema, compression="snappy")

    pk_col = columns[0]["name"]
    pk_values: list = []

    try:
        remaining = row_count
        while remaining > 0:
            n = min(chunk_size, remaining)
            cols: dict[str, list] = {c["name"]: [] for c in columns}
            for _ in range(n):
                for c in columns:
                    val = _gen_value(c.get("generator", {"type": "faker", "method": "word"}), fk, seq_state, fk_refs, c["name"])
                    cols[c["name"]].append(val)
            # cast types
            data = {}
            for c in columns:
                vals = cols[c["name"]]
                dt = c.get("data_type", "string").lower()
                if dt in ("int", "long", "bigint"):
                    data[c["name"]] = pd.array(vals, dtype="Int64")
                elif dt in ("float", "double", "decimal"):
                    data[c["name"]] = pd.array(vals, dtype="Float64")
                elif dt in ("bool", "boolean"):
                    data[c["name"]] = pd.array(vals, dtype="boolean")
                else:
                    data[c["name"]] = pd.array([str(v) if v is not None else None for v in vals], dtype="string")
            df = pd.DataFrame(data)
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
            writer.write_table(table)
            pk_values.extend(df[pk_col].dropna().tolist())
            remaining -= n
        writer.close()
        with open(tmp.name, "rb") as f:
            yield f.read()
        # Keep PK refs for downstream FK lookups (only return last batch)
        fk_refs.setdefault("_last_pk_values", []).extend(pk_values[:5000])
    finally:
        os.unlink(tmp.name)


def generate_dataset_bytes(columns: list[dict], row_count: int, fk_refs: dict) -> tuple[bytes, list]:
    """Returns (parquet_bytes, pk_values_sample)."""
    chunks = list(generate_dataset_to_parquet_stream(columns, row_count, fk_refs))
    return chunks[0], fk_refs.get("_last_pk_values", [])
