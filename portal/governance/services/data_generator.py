"""Data generator: turn an LLM spec into Parquet rows in MinIO."""
import logging
import os
import random
import string
import tempfile
import uuid
from datetime import date, datetime, timedelta
from typing import Callable, Iterator

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

logger = logging.getLogger(__name__)

CHUNK_ROWS = 100_000  # rows per Parquet row-group for streaming writes


# ---------------------------------------------------------------------------
# Value-generator dispatch table  (replaces nested if/elif chain)
# ---------------------------------------------------------------------------
def _faker_value(fk: Faker, method: str):
    fn = getattr(fk, method, None) or fk.word
    val = fn()
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return val


def _gen_sequence(spec, fk, seq_state, fk_refs, col_name):
    seq_state[col_name] = seq_state.get(col_name, spec.get("start", 1) - 1) + 1
    return seq_state[col_name]


def _gen_uuid(*_args, **_kwargs):
    return str(uuid.uuid4())


def _gen_email(spec, fk, *_args, **_kwargs):
    return fk.email()


def _gen_faker(spec, fk, *_args, **_kwargs):
    return _faker_value(fk, spec.get("method", "word"))


def _gen_choices(spec, *_args, **_kwargs):
    return random.choice(spec.get("values", [""]))


def _gen_int_range(spec, *_args, **_kwargs):
    return random.randint(int(spec.get("min", 0)), int(spec.get("max", 100)))


def _gen_float_range(spec, *_args, **_kwargs):
    v = random.uniform(float(spec.get("min", 0.0)), float(spec.get("max", 1.0)))
    return round(v, int(spec.get("decimals", 2)))


def _gen_date_range(spec, *_args, **_kwargs):
    start = datetime.fromisoformat(spec.get("start", "2020-01-01"))
    end = datetime.fromisoformat(spec.get("end", "2024-12-31"))
    delta = max((end - start).days, 0)
    return (start + timedelta(days=random.randint(0, delta))).date().isoformat()


def _gen_foreign_key(spec, fk, seq_state, fk_refs, col_name):
    ref = spec.get("references", "")
    candidates = fk_refs.get(ref) or []
    return random.choice(candidates) if candidates else random.randint(1, 1000)


GENERATORS: dict[str, Callable] = {
    "sequence": _gen_sequence,
    "uuid": _gen_uuid,
    "email": _gen_email,
    "faker": _gen_faker,
    "choices": _gen_choices,
    "int_range": _gen_int_range,
    "float_range": _gen_float_range,
    "date_range": _gen_date_range,
    "foreign_key": _gen_foreign_key,
}


def _gen_value(spec: dict, fk: Faker, seq_state: dict, fk_refs: dict, col_name: str):
    gen = GENERATORS.get(spec.get("type", "faker"))
    if gen is None:
        return "".join(random.choices(string.ascii_lowercase, k=8))
    return gen(spec, fk, seq_state, fk_refs, col_name)


# ---------------------------------------------------------------------------
# Arrow schema construction  (dict mapping replaces nested if/elif)
# ---------------------------------------------------------------------------
_PA_TYPE_MAP = {
    "int": pa.int64, "integer": pa.int64, "long": pa.int64, "bigint": pa.int64,
    "float": pa.float64, "double": pa.float64, "decimal": pa.float64,
    "bool": pa.bool_, "boolean": pa.bool_,
    # date / datetime / timestamp / anything else -> string (portable)
}


def _pa_type_for(dt: str) -> pa.DataType:
    builder = _PA_TYPE_MAP.get((dt or "").lower())
    return builder() if builder else pa.string()


def _pa_schema(columns: list[dict]) -> pa.Schema:
    return pa.schema([
        pa.field(c["name"], _pa_type_for(c.get("data_type", "string")), nullable=c.get("nullable", True))
        for c in columns
    ])


# ---------------------------------------------------------------------------
# Chunked Parquet writer
# ---------------------------------------------------------------------------
def _row_chunk(columns: list[dict], n: int, fk: Faker, seq_state: dict, fk_refs: dict) -> dict[str, list]:
    cols: dict[str, list] = {c["name"]: [] for c in columns}
    for _ in range(n):
        for c in columns:
            spec = c.get("generator", {"type": "faker", "method": "word"})
            cols[c["name"]].append(_gen_value(spec, fk, seq_state, fk_refs, c["name"]))
    return cols


def _chunk_to_dataframe(columns: list[dict], cols: dict[str, list]) -> pd.DataFrame:
    data = {}
    for c in columns:
        vals = cols[c["name"]]
        dt = (c.get("data_type") or "string").lower()
        if dt in ("int", "integer", "long", "bigint"):
            data[c["name"]] = pd.array(vals, dtype="Int64")
        elif dt in ("float", "double", "decimal"):
            data[c["name"]] = pd.array(vals, dtype="Float64")
        elif dt in ("bool", "boolean"):
            data[c["name"]] = pd.array(vals, dtype="boolean")
        else:
            data[c["name"]] = pd.array([str(v) if v is not None else None for v in vals], dtype="string")
    return pd.DataFrame(data)


def _write_chunks(writer: pq.ParquetWriter, schema: pa.Schema, columns: list[dict],
                  row_count: int, fk: Faker, seq_state: dict, fk_refs: dict,
                  chunk_size: int, pk_col: str, pk_values: list) -> None:
    remaining = row_count
    while remaining > 0:
        n = min(chunk_size, remaining)
        cols = _row_chunk(columns, n, fk, seq_state, fk_refs)
        df = _chunk_to_dataframe(columns, cols)
        writer.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False))
        pk_values.extend(df[pk_col].dropna().tolist())
        remaining -= n


def generate_dataset_to_parquet_stream(
    columns: list[dict],
    row_count: int,
    fk_refs: dict[str, list],
    chunk_size: int = CHUNK_ROWS,
) -> Iterator[bytes]:
    """Generate Parquet bytes for `row_count` rows, written to a temp file then yielded once."""
    fk = Faker()
    Faker.seed(random.randint(0, 10_000))
    seq_state: dict[str, int] = {}
    schema = _pa_schema(columns)
    pk_col = columns[0]["name"]
    pk_values: list = []

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".parquet")
    tmp.close()
    writer = pq.ParquetWriter(tmp.name, schema, compression="snappy")
    try:
        _write_chunks(writer, schema, columns, row_count, fk, seq_state, fk_refs, chunk_size, pk_col, pk_values)
        writer.close()
        with open(tmp.name, "rb") as f:
            yield f.read()
        fk_refs.setdefault("_last_pk_values", []).extend(pk_values[:5000])
    finally:
        os.unlink(tmp.name)


def generate_dataset_bytes(columns: list[dict], row_count: int, fk_refs: dict) -> tuple[bytes, list]:
    """Returns (parquet_bytes, pk_values_sample)."""
    chunks = list(generate_dataset_to_parquet_stream(columns, row_count, fk_refs))
    return chunks[0], fk_refs.get("_last_pk_values", [])
