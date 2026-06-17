"""Celery tasks: data generation + Excel ingestion pipeline."""
import logging
from datetime import datetime, timezone

from celery import shared_task
from django.conf import settings
from django.db import transaction

from .models import (
    GenerationRun,
    DataProduct,
    Dataset,
    Column,
    LineageEdge,
    QualityRule,
    DataProductUpload,
    CatalogSyncLog,
)

logger = logging.getLogger(__name__)


# ============================================================
# Shared helpers
# ============================================================
def _set_status(run: GenerationRun, status: str, pct: int | None = None, error: str = ""):
    run.status = status
    if pct is not None:
        run.progress_pct = pct
    if error:
        run.error = error
    run.save(update_fields=["status", "progress_pct", "error", "updated_at"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# Generation pipeline helpers
# ============================================================
def _design_spec(run: GenerationRun, row_count: int) -> dict:
    """Step 1 — LLM design."""
    from .services.llm_designer import design_data_product
    _set_status(run, "designing", 5)
    spec = design_data_product(run.domain)
    run.spec = spec
    run.chosen_instance = spec.get("instance_name", "")
    run.row_count_per_dataset = row_count
    run.save(update_fields=["spec", "chosen_instance", "row_count_per_dataset"])
    return spec


def _persist_dataset(run: GenerationRun, ds_spec: dict, minio_path: str, row_count: int) -> Dataset:
    ds_obj, _ = Dataset.objects.update_or_create(
        generation_run=run,
        name=ds_spec["name"],
        defaults={
            "minio_path": minio_path,
            "format": "parquet",
            "row_count": row_count,
            "pii_flag": ds_spec.get("pii_flag", False),
        },
    )
    ds_obj.columns.all().delete()
    for i, c in enumerate(ds_spec["columns"]):
        Column.objects.create(
            dataset=ds_obj,
            name=c["name"],
            data_type=c.get("data_type", "string"),
            nullable=c.get("nullable", True),
            description=c.get("description", ""),
            pii=c.get("pii", False),
            business_glossary_term=c.get("business_glossary_term", ""),
            ordinal=i,
        )
    return ds_obj


def _register_schema(ds_obj: Dataset, ds_spec: dict, product_name: str) -> None:
    from .services.schema_registry import SchemaRegistryClient, build_avro_schema
    sr = SchemaRegistryClient()
    subject = f"{product_name}.{ds_spec['name']}-value"
    avro = build_avro_schema(ds_spec["name"], f"governance.{product_name}", ds_spec["columns"])
    try:
        info = sr.register(subject, avro)
        ds_obj.schema_subject = subject
        ds_obj.schema_version = info.get("version")
        ds_obj.save(update_fields=["schema_subject", "schema_version"])
    except Exception as e:
        logger.warning("Schema registry failed for %s: %s", subject, e)


def _process_one_dataset(run, ds_spec, idx, total, product_name, fk_refs, minio, mq):
    """Generate -> upload -> persist -> register -> build Marquez descriptor for one dataset."""
    from .services.data_generator import generate_dataset_bytes

    ds_name = ds_spec["name"]
    _set_status(run, "generating", 10 + int(50 * idx / total))
    logger.info("Run #%s: generating dataset %s (%d rows)", run.id, ds_name, run.row_count_per_dataset)

    data_bytes, pk_sample = generate_dataset_bytes(ds_spec["columns"], run.row_count_per_dataset, fk_refs)
    pk_col = ds_spec["columns"][0]["name"]
    fk_refs[f"{ds_name}.{pk_col}"] = pk_sample

    _set_status(run, "uploading", 60 + int(15 * idx / total))
    object_name = f"{product_name}/{ds_name}/data.parquet"
    minio_path = minio.put_bytes("raw", object_name, data_bytes, content_type="application/octet-stream")

    ds_obj = _persist_dataset(run, ds_spec, minio_path, run.row_count_per_dataset)

    _set_status(run, "registering", 75 + int(10 * idx / total))
    _register_schema(ds_obj, ds_spec, product_name)

    descriptor = mq.dataset_descriptor(
        name=f"{product_name}.{ds_name}",
        columns=ds_spec["columns"],
        description=ds_spec.get("description", ""),
        source_uri=f"s3a://{minio_path}",
    )
    ds_obj.marquez_dataset = f"{product_name}.{ds_name}"
    ds_obj.save(update_fields=["marquez_dataset"])
    return descriptor


def _emit_lineage(spec: dict, product_name: str, descriptors: list, mq) -> None:
    """Emit OL events for the producer job + each transformation edge."""
    mq.emit_run(job_name=f"data-generator.{product_name}", outputs=descriptors)
    for edge in spec.get("lineage", []):
        up = edge["upstream"]
        down = edge["downstream"]
        inputs = [d for d in descriptors if d["name"].endswith(f".{up}")]
        outputs = [d for d in descriptors if d["name"].endswith(f".{down}")]
        if inputs and outputs:
            mq.emit_run(
                job_name=f"transform.{product_name}.{up}_to_{down}",
                inputs=inputs,
                outputs=outputs,
            )


# ============================================================
# TASK 1: Data Generator
# ============================================================
@shared_task(bind=True, name="governance.tasks.generate_data_product")
def generate_data_product(self, run_id: int):
    """LLM design -> generate -> MinIO -> Schema Registry -> Marquez -> Excel."""
    from .services.minio_client import MinIOService
    from .services.marquez_client import MarquezClient

    run = GenerationRun.objects.get(pk=run_id)
    run.started_at = _now()
    run.save(update_fields=["started_at"])

    row_count = settings.DATASET_SIZES[run.size]
    logger.info("Run #%s: starting %s (%d rows/dataset) for '%s'", run.id, run.size, row_count, run.domain)

    try:
        spec = _design_spec(run, row_count)
        product_name = spec.get("product_name") or run.chosen_instance.lower().replace(" ", "_")

        minio = MinIOService()
        minio.ensure_buckets()
        mq = MarquezClient()
        mq.ensure_namespace()

        fk_refs: dict[str, list] = {}
        descriptors = []
        total = len(spec["datasets"])
        for idx, ds_spec in enumerate(spec["datasets"]):
            descriptors.append(_process_one_dataset(run, ds_spec, idx, total, product_name, fk_refs, minio, mq))

        _set_status(run, "lineage", 88)
        _emit_lineage(spec, product_name, descriptors, mq)

        _set_status(run, "excel", 95)
        run.excel_object_key = generate_excel_definition_sync(run.id)
        run.save(update_fields=["excel_object_key"])

        run.finished_at = _now()
        _set_status(run, "completed", 100)
        run.save(update_fields=["finished_at"])
        logger.info("Run #%s: COMPLETED", run.id)

    except Exception as e:
        logger.exception("Run #%s failed", run.id)
        _set_status(run, "failed", error=str(e))
        run.finished_at = _now()
        run.save(update_fields=["finished_at"])
        raise


# ============================================================
# TASK 2: Excel definition generator
# ============================================================
def generate_excel_definition_sync(run_id: int) -> str:
    """Build the Data Product Definition Excel and store it in MinIO."""
    from .services.excel_service import build_excel_from_spec
    from .services.minio_client import MinIOService

    run = GenerationRun.objects.get(pk=run_id)
    excel_bytes = build_excel_from_spec(run.spec, generation_run_id=run.id)
    minio = MinIOService()
    minio.ensure_buckets()
    product_name = run.spec.get("product_name") or run.chosen_instance.lower().replace(" ", "_")
    object_name = f"auto/{product_name}_{run.id}_definition.xlsx"
    minio.put_bytes(
        "excel",
        object_name,
        excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return object_name


@shared_task(name="governance.tasks.generate_excel_definition")
def generate_excel_definition(run_id: int):
    return generate_excel_definition_sync(run_id)


# ============================================================
# Ingestion pipeline helpers
# ============================================================
def _persist_data_product(parsed: dict) -> DataProduct:
    dp, _ = DataProduct.objects.update_or_create(
        name=parsed["name"],
        defaults={
            "description": parsed.get("description", ""),
            "domain": parsed.get("domain", ""),
            "owner_email": parsed.get("owner_email", ""),
            "tier": parsed.get("tier", "gold"),
            "tags": parsed.get("tags", []),
            "status": "processing",
            "error": "",
        },
    )
    dp.datasets.all().delete()
    dp.lineage_edges.all().delete()
    return dp


def _create_datasets(dp: DataProduct, datasets: list[dict]) -> None:
    for d in datasets:
        ds = Dataset.objects.create(
            data_product=dp,
            name=d["name"],
            minio_path=d.get("minio_path", ""),
            format=d.get("format", "parquet"),
            refresh_cadence=d.get("refresh_cadence", "daily"),
            pii_flag=d.get("pii_flag", False),
        )
        for i, c in enumerate(d["columns"]):
            Column.objects.create(
                dataset=ds,
                name=c["name"],
                data_type=c.get("data_type", "string"),
                nullable=c.get("nullable", True),
                description=c.get("description", ""),
                pii=c.get("pii", False),
                business_glossary_term=c.get("business_glossary_term", ""),
                ordinal=i,
            )
        for r in d.get("quality_rules", []):
            QualityRule.objects.create(
                dataset=ds,
                column_name=r.get("column_name", ""),
                rule_type=r.get("rule_type", ""),
                expression=r.get("expression", ""),
            )


def _create_lineage_edges(dp: DataProduct, edges: list[dict]) -> None:
    for e in edges:
        LineageEdge.objects.create(
            data_product=dp,
            upstream_dataset=e.get("upstream", ""),
            downstream_dataset=e.get("downstream", ""),
            transformation=e.get("transformation", ""),
        )


def _build_and_store_contract(dp: DataProduct, parsed: dict) -> None:
    from .services.contract_generator import build_contract
    from .services.minio_client import MinIOService
    minio = MinIOService()
    minio.ensure_buckets()
    contract_yaml = build_contract(parsed)
    contract_key = f"{dp.name}/contract.yaml"
    minio.put_bytes("contracts", contract_key, contract_yaml.encode("utf-8"), content_type="application/x-yaml")
    dp.contract_object_key = f"{settings.MINIO_BUCKETS['contracts']}/{contract_key}"
    dp.save(update_fields=["contract_object_key"])


def _publish_to_catalog(dp: DataProduct, parsed: dict) -> None:
    from .catalog import get_catalog_client
    catalog = get_catalog_client()
    payload = {
        "name": parsed["name"],
        "description": parsed.get("description", ""),
        "domain": parsed.get("domain", ""),
        "owner_email": parsed.get("owner_email", ""),
        "tier": parsed.get("tier", "gold"),
        "tags": parsed.get("tags", []),
        "datasets": parsed["datasets"],
        "lineage": parsed.get("lineage", []),
        "contract_url": f"{settings.MINIO_PUBLIC_ENDPOINT}/{dp.contract_object_key}",
    }
    sync_log = CatalogSyncLog.objects.create(data_product=dp, provider=catalog.provider, request_payload=payload)
    try:
        result = catalog.publish_data_product(payload)
        dp.external_id = result.get("external_id", "")
        dp.external_url = result.get("ui_url", "") or ""
        dp.catalog_provider = catalog.provider
        sync_log.response_payload = result
        sync_log.success = True
        sync_log.save()
    except Exception as e:
        sync_log.error = str(e)
        sync_log.success = False
        sync_log.save()
        raise


# ============================================================
# TASK 3: Ingest uploaded Excel → create Data Product in the catalog
# ============================================================
@shared_task(bind=True, name="governance.tasks.ingest_data_product_excel")
def ingest_data_product_excel(self, upload_id: int):
    """Triggered by signal when a DataProductUpload is created."""
    from .services.excel_service import parse_excel

    upload = DataProductUpload.objects.get(pk=upload_id)
    upload.status = "processing"
    upload.save(update_fields=["status"])

    try:
        with upload.file.open("rb") as fh:
            parsed = parse_excel(fh.read())

        with transaction.atomic():
            dp = _persist_data_product(parsed)
            _create_datasets(dp, parsed["datasets"])
            _create_lineage_edges(dp, parsed.get("lineage", []))

        _build_and_store_contract(dp, parsed)
        _publish_to_catalog(dp, parsed)

        dp.status = "published"
        dp.published_at = _now()
        dp.save(update_fields=["status", "external_id", "external_url", "catalog_provider", "published_at"])

        upload.data_product = dp
        upload.status = "done"
        upload.save(update_fields=["data_product", "status"])
        logger.info("Upload #%s -> DataProduct '%s' published via %s (external_id=%s)",
                    upload.id, dp.name, dp.catalog_provider, dp.external_id)

    except Exception as e:
        logger.exception("Excel ingestion failed for upload #%s", upload.id)
        upload.status = "failed"
        upload.error = str(e)
        upload.save(update_fields=["status", "error"])
        raise


# ============================================================
# TASK 4: Periodic catalog re-sync
# ============================================================
def _dp_to_payload(dp: DataProduct) -> dict:
    return {
        "name": dp.name,
        "description": dp.description,
        "domain": dp.domain,
        "owner_email": dp.owner_email,
        "tier": dp.tier,
        "tags": dp.tags,
        "datasets": [
            {
                "name": ds.name,
                "minio_path": ds.minio_path,
                "format": ds.format,
                "columns": list(ds.columns.values("name", "data_type", "nullable", "description", "pii", "business_glossary_term")),
            }
            for ds in dp.datasets.all()
        ],
        "lineage": [
            {"upstream": le.upstream_dataset, "downstream": le.downstream_dataset, "transformation": le.transformation}
            for le in dp.lineage_edges.all()
        ],
    }


@shared_task(name="governance.tasks.sync_alation")
def sync_alation():
    """Re-push any data products whose catalog sync failed or are stale."""
    from .catalog import get_catalog_client
    catalog = get_catalog_client()
    for dp in DataProduct.objects.filter(status__in=["draft", "failed"]):
        logger.info("Re-syncing %s via %s", dp.name, catalog.provider)
        try:
            result = catalog.publish_data_product(_dp_to_payload(dp))
            dp.external_id = result.get("external_id", "")
            dp.external_url = result.get("ui_url", "") or ""
            dp.catalog_provider = catalog.provider
            dp.status = "published"
            dp.published_at = _now()
            dp.save()
        except Exception as e:
            dp.status = "failed"
            dp.error = str(e)
            dp.save()
