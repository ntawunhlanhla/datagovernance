"""
Core models for the metadata governance platform.

Domain model:

  GenerationRun  --(produces)-->  Dataset(s)
                              |--> Column(s)
                              |--> Excel Definition File

  DataProductUpload  --(parsed into)-->  DataProduct
                                       |--> Dataset(s)
                                       |--> Column(s)
                                       |--> LineageEdge(s)
                                       |--> QualityRule(s)
                                       |--> ContractFile
                                       |--> AlationSyncLog
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SourceConnection(TimestampedModel):
    """Pluggable source connector configuration (MinIO, S3, Athena, Glue, Marquez, ...)."""
    KIND_CHOICES = [
        ("minio", "MinIO"),
        ("s3", "AWS S3"),
        ("athena", "AWS Athena"),
        ("glue", "AWS Glue"),
        ("marquez", "Marquez"),
        ("custom", "Custom"),
    ]
    name = models.CharField(max_length=128, unique=True)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    config = models.JSONField(default=dict, blank=True, help_text="Connector-specific config")
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.kind})"


class GenerationRun(TimestampedModel):
    SIZE_CHOICES = [("small", "Small (10K)"), ("medium", "Medium (1M)"), ("large", "Large (100M)")]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("designing", "Designing schema via LLM"),
        ("generating", "Generating data"),
        ("uploading", "Uploading to MinIO"),
        ("registering", "Registering schemas"),
        ("lineage", "Emitting lineage"),
        ("excel", "Building Excel definition"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]
    domain = models.CharField(max_length=128, help_text='e.g. "school", "restaurant", "hospital"')
    chosen_instance = models.CharField(max_length=255, blank=True, help_text="Random instance picked by LLM, e.g. 'Greenwood High School'")
    size = models.CharField(max_length=8, choices=SIZE_CHOICES)
    row_count_per_dataset = models.BigIntegerField(default=0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="pending")
    progress_pct = models.IntegerField(default=0)
    spec = models.JSONField(default=dict, blank=True, help_text="LLM-designed dataset spec")
    excel_object_key = models.CharField(max_length=512, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run#{self.pk} [{self.domain} / {self.size}] {self.status}"

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class DataProduct(TimestampedModel):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("processing", "Processing"),
        ("published", "Published"),
        ("failed", "Failed"),
    ]
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    domain = models.CharField(max_length=128, blank=True)
    owner_email = models.EmailField(blank=True)
    tier = models.CharField(max_length=32, default="gold", help_text="bronze / silver / gold")
    tags = models.JSONField(default=list, blank=True)
    source_connection = models.ForeignKey(SourceConnection, on_delete=models.SET_NULL, null=True, blank=True)
    generation_run = models.ForeignKey(GenerationRun, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="draft")
    catalog_provider = models.CharField(max_length=32, default="openmetadata", help_text="openmetadata | alation | mock")
    external_id = models.CharField(max_length=255, blank=True, help_text="ID of the published object in the catalog")
    external_url = models.URLField(max_length=512, blank=True, help_text="Direct UI link in the catalog")
    contract_object_key = models.CharField(max_length=512, blank=True)
    error = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Dataset(TimestampedModel):
    data_product = models.ForeignKey(DataProduct, on_delete=models.CASCADE, related_name="datasets", null=True, blank=True)
    generation_run = models.ForeignKey(GenerationRun, on_delete=models.CASCADE, related_name="datasets", null=True, blank=True)
    name = models.CharField(max_length=255)
    minio_path = models.CharField(max_length=512, blank=True, help_text="bucket/path inside MinIO")
    format = models.CharField(max_length=16, default="parquet")
    row_count = models.BigIntegerField(default=0)
    refresh_cadence = models.CharField(max_length=32, default="daily")
    pii_flag = models.BooleanField(default=False)
    schema_subject = models.CharField(max_length=255, blank=True)
    schema_version = models.IntegerField(null=True, blank=True)
    marquez_dataset = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("name", "data_product"), ("name", "generation_run")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Column(TimestampedModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="columns")
    name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=64)
    nullable = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    pii = models.BooleanField(default=False)
    business_glossary_term = models.CharField(max_length=255, blank=True)
    ordinal = models.IntegerField(default=0)

    class Meta:
        ordering = ["dataset", "ordinal"]
        unique_together = [("dataset", "name")]

    def __str__(self):
        return f"{self.dataset.name}.{self.name}"


class LineageEdge(TimestampedModel):
    data_product = models.ForeignKey(DataProduct, on_delete=models.CASCADE, related_name="lineage_edges", null=True, blank=True)
    upstream_dataset = models.CharField(max_length=255)
    downstream_dataset = models.CharField(max_length=255)
    transformation = models.TextField(blank=True)

    def __str__(self):
        return f"{self.upstream_dataset} -> {self.downstream_dataset}"


class QualityRule(TimestampedModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="quality_rules")
    column_name = models.CharField(max_length=255, blank=True)
    rule_type = models.CharField(max_length=64, help_text="not_null, unique, range, regex, ...")
    expression = models.CharField(max_length=512, blank=True)


class DataProductUpload(TimestampedModel):
    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]
    file = models.FileField(upload_to="excel-uploads/")
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="uploaded")
    error = models.TextField(blank=True)
    data_product = models.ForeignKey(DataProduct, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Upload#{self.pk} ({self.status})"


class CatalogSyncLog(TimestampedModel):
    PROVIDER_CHOICES = [("openmetadata", "OpenMetadata"), ("alation", "Alation"), ("mock", "Mock")]
    data_product = models.ForeignKey(DataProduct, on_delete=models.CASCADE, related_name="catalog_logs")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, default="mock")
    request_payload = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
