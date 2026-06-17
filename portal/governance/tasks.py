"""Celery tasks: data generation + Excel ingestion pipeline."""
import json
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
    AlationSyncLog,
)

logger = logging.getLogger(__name__)


# ============================================================
# Helper to update run status
# ============================================================
def _set_status(run: GenerationRun, status: str, pct: int | None = None, error: str = ""):
    run.status = status
    if pct is not None:
        run.progress_pct = pct
    if error:
        run.error = error
    run.save(update_fields=["status", "progress_pct", "error", "updated_at"])


# ============================================================
# TASK 1: Data Generator — runs on `generator` queue (data-generator service)
# ============================================================
@shared_task(bind=True, name="governance.tasks.generate_data_product")
def generate_data_product(self, run_id: int):
    """Full data generation pipeline: LLM design -> generate -> MinIO -> Schema Registry -> Marquez -> Excel."""
    from .services.llm_designer import design_data_product
    from .services.data_generator import generate_dataset_bytes
    from .services.minio_client import MinIOService
    from .services.schema_registry import SchemaRegistryClient, build_avro_schema
    from .services.marquez_client import MarquezClient

    run = GenerationRun.objects.get(pk=run_id)
    run.started_at = datetime.now(timezone.utc)
    run.save(update_fields=["started_at"])

    row_count = settings.DATASET_SIZES[run.size]
    logger.info("Run #%s: generating %s (%d rows/dataset) for domain '%s'", run.id, run.size, row_count, run.domain)

    try:
        # ---------- 1. LLM design ----------
        _set_status(run, "designing", 5)
        spec = design_data_product(run.domain)
        run.spec = spec
        run.chosen_instance = spec.get("instance_name", "")
        run.row_count_per_dataset = row_count
        run.save(update_fields=["spec", "chosen_instance", "row_count_per_dataset"])

        product_name = spec.get("product_name") or run.chosen_instance.lower().replace(" ", "_")

        # ---------- 2. Generate datasets ----------
        minio = MinIOService()
        minio.ensure_buckets()
        sr = SchemaRegistryClient()
        mq = MarquezClient()
        mq.ensure_namespace()

        fk_refs: dict[str, list] = {}
        dataset_descriptors = []
        total_ds = len(spec["datasets"])
        for idx, ds_spec in enumerate(spec["datasets"]):
            ds_name = ds_spec["name"]
            _set_status(run, "generating", 10 + int(50 * idx / total_ds))
            logger.info("Run #%s: generating dataset %s (%d rows)", run.id, ds_name, row_count)

            data_bytes, pk_sample = generate_dataset_bytes(ds_spec["columns"], row_count, fk_refs)
            # store PK refs by qualified column name for FK lookups
            pk_col = ds_spec["columns"][0]["name"]
            fk_refs[f"{ds_name}.{pk_col}"] = pk_sample

            # ---------- 3. Upload to MinIO ----------
            _set_status(run, "uploading", 60 + int(15 * idx / total_ds))
            object_name = f"{product_name}/{ds_name}/data.parquet"
            minio_path = minio.put_bytes("raw", object_name, data_bytes, content_type="application/octet-stream")

            ds_obj, _ = Dataset.objects.update_or_create(
                generation_run=run,
                name=ds_name,
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

            # ---------- 4. Register Avro schema ----------
            _set_status(run, "registering", 75 + int(10 * idx / total_ds))
            subject = f"{product_name}.{ds_name}-value"
            avro = build_avro_schema(ds_name, f"governance.{product_name}", ds_spec["columns"])
            try:
                sr_info = sr.register(subject, avro)
                ds_obj.schema_subject = subject
                ds_obj.schema_version = sr_info.get("version")
                ds_obj.save(update_fields=["schema_subject", "schema_version"])
            except Exception as e:
                logger.warning("Schema registry failed for %s: %s", subject, e)

            # ---------- 5. Build OL dataset descriptor ----------
            dataset_descriptors.append(mq.dataset_descriptor(
                name=f"{product_name}.{ds_name}",
                columns=ds_spec["columns"],
                description=ds_spec.get("description", ""),
                source_uri=f"s3a://{minio_path}",
            ))
            ds_obj.marquez_dataset = f"{product_name}.{ds_name}"
            ds_obj.save(update_fields=["marquez_dataset"])

        # ---------- 6. Emit Marquez lineage ----------
        _set_status(run, "lineage", 88)
        job_name = f"data-generator.{product_name}"
        mq.emit_run(job_name=job_name, outputs=dataset_descriptors)

        # Emit per-edge lineage
        for edge in spec.get("lineage", []):
            up = edge["upstream"]
            down = edge["downstream"]
            inputs = [d for d in dataset_descriptors if d["name"].endswith(f".{up}")]
            outputs = [d for d in dataset_descriptors if d["name"].endswith(f".{down}")]
            if inputs and outputs:
                mq.emit_run(
                    job_name=f"transform.{product_name}.{up}_to_{down}",
                    inputs=inputs,
                    outputs=outputs,
                )

        # ---------- 7. Generate Excel definition (separate concern) ----------
        _set_status(run, "excel", 95)
        excel_key = generate_excel_definition_sync(run.id)
        run.excel_object_key = excel_key
        run.save(update_fields=["excel_object_key"])

        # ---------- 8. Done ----------
        run.finished_at = datetime.now(timezone.utc)
        _set_status(run, "completed", 100)
        run.save(update_fields=["finished_at"])
        logger.info("Run #%s: COMPLETED", run.id)

    except Exception as e:
        logger.exception("Run #%s failed", run.id)
        _set_status(run, "failed", error=str(e))
        run.finished_at = datetime.now(timezone.utc)
        run.save(update_fields=["finished_at"])
        raise


# ============================================================
# TASK 2: Excel definition generator (callable separately too)
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
# TASK 3: Ingest uploaded Excel → create Data Product in Alation
# ============================================================
@shared_task(bind=True, name="governance.tasks.ingest_data_product_excel")
def ingest_data_product_excel(self, upload_id: int):
    """Triggered by signal when a DataProductUpload is created."""
    from .services.excel_service import parse_excel
    from .services.contract_generator import build_contract
    from .services.minio_client import MinIOService
    from .services.alation_client import AlationClient

    upload = DataProductUpload.objects.get(pk=upload_id)
    upload.status = "processing"
    upload.save(update_fields=["status"])

    try:
        # ---------- 1. Parse ----------
        with upload.file.open("rb") as fh:
            file_bytes = fh.read()
        parsed = parse_excel(file_bytes)

        # ---------- 2. Persist Data Product ----------
        with transaction.atomic():
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
            for d in parsed["datasets"]:
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
            for e in parsed.get("lineage", []):
                LineageEdge.objects.create(
                    data_product=dp,
                    upstream_dataset=e.get("upstream", ""),
                    downstream_dataset=e.get("downstream", ""),
                    transformation=e.get("transformation", ""),
                )

        # ---------- 3. Generate Data Contract ----------
        contract_yaml = build_contract(parsed)
        minio = MinIOService()
        minio.ensure_buckets()
        contract_key = f"{dp.name}/contract.yaml"
        minio.put_bytes("contracts", contract_key, contract_yaml.encode("utf-8"), content_type="application/x-yaml")
        dp.contract_object_key = f"{settings.MINIO_BUCKETS['contracts']}/{contract_key}"
        dp.save(update_fields=["contract_object_key"])

        # ---------- 4. Publish to Alation ----------
        alation = AlationClient()
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
        sync_log = AlationSyncLog.objects.create(
            data_product=dp,
            mode=alation.mode,
            request_payload=payload,
        )
        try:
            result = alation.publish_data_product(payload)
            dp.alation_id = result.get("alation_id", "")
            sync_log.response_payload = result
            sync_log.success = True
            sync_log.save()
        except Exception as e:
            sync_log.error = str(e)
            sync_log.success = False
            sync_log.save()
            raise

        # ---------- 5. Mark done ----------
        dp.status = "published"
        dp.published_at = datetime.now(timezone.utc)
        dp.save(update_fields=["status", "alation_id", "published_at"])

        upload.data_product = dp
        upload.status = "done"
        upload.save(update_fields=["data_product", "status"])
        logger.info("Upload #%s -> DataProduct '%s' published (alation_id=%s)", upload.id, dp.name, dp.alation_id)

    except Exception as e:
        logger.exception("Excel ingestion failed for upload #%s", upload.id)
        upload.status = "failed"
        upload.error = str(e)
        upload.save(update_fields=["status", "error"])
        raise


# ============================================================
# TASK 4: Periodic Alation re-sync (called by celery-beat)
# ============================================================
@shared_task(name="governance.tasks.sync_alation")
def sync_alation():
    """Re-push any data products whose Alation sync failed or are stale."""
    from .services.alation_client import AlationClient
    alation = AlationClient()
    products = DataProduct.objects.filter(status__in=["draft", "failed"])
    for dp in products:
        logger.info("Re-syncing %s to Alation", dp.name)
        # build payload from DB
        payload = {
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
            "lineage": [{"upstream": le.upstream_dataset, "downstream": le.downstream_dataset, "transformation": le.transformation} for le in dp.lineage_edges.all()],
        }
        try:
            result = alation.publish_data_product(payload)
            dp.alation_id = result.get("alation_id", "")
            dp.status = "published"
            dp.published_at = datetime.now(timezone.utc)
            dp.save()
        except Exception as e:
            dp.status = "failed"
            dp.error = str(e)
            dp.save()
