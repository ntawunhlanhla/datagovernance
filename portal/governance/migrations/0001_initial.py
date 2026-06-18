from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GenerationRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("domain", models.CharField(help_text='e.g. "school", "restaurant", "hospital"', max_length=128)),
                ("chosen_instance", models.CharField(blank=True, help_text="Random instance picked by LLM, e.g. 'Greenwood High School'", max_length=255)),
                ("size", models.CharField(choices=[("small", "Small (10K)"), ("medium", "Medium (1M)"), ("large", "Large (100M)")], max_length=8)),
                ("row_count_per_dataset", models.BigIntegerField(default=0)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("designing", "Designing schema via LLM"), ("generating", "Generating data"), ("uploading", "Uploading to MinIO"), ("registering", "Registering schemas"), ("lineage", "Emitting lineage"), ("excel", "Building Excel definition"), ("completed", "Completed"), ("failed", "Failed")], default="pending", max_length=32)),
                ("progress_pct", models.IntegerField(default=0)),
                ("spec", models.JSONField(blank=True, default=dict, help_text="LLM-designed dataset spec")),
                ("excel_object_key", models.CharField(blank=True, max_length=512)),
                ("error", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SourceConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=128, unique=True)),
                ("kind", models.CharField(choices=[("minio", "MinIO"), ("s3", "AWS S3"), ("athena", "AWS Athena"), ("glue", "AWS Glue"), ("marquez", "Marquez"), ("custom", "Custom")], max_length=32)),
                ("config", models.JSONField(blank=True, default=dict, help_text="Connector-specific config")),
                ("enabled", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="DataProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True)),
                ("domain", models.CharField(blank=True, max_length=128)),
                ("owner_email", models.EmailField(blank=True, max_length=254)),
                ("tier", models.CharField(default="gold", help_text="bronze / silver / gold", max_length=32)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("processing", "Processing"), ("published", "Published"), ("failed", "Failed")], default="draft", max_length=16)),
                ("catalog_provider", models.CharField(default="openmetadata", help_text="openmetadata | alation | mock", max_length=32)),
                ("external_id", models.CharField(blank=True, help_text="ID of the published object in the catalog", max_length=255)),
                ("external_url", models.URLField(blank=True, help_text="Direct UI link in the catalog", max_length=512)),
                ("contract_object_key", models.CharField(blank=True, max_length=512)),
                ("error", models.TextField(blank=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("generation_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="governance.generationrun")),
                ("source_connection", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="governance.sourceconnection")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="DataProductUpload",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("file", models.FileField(upload_to="excel-uploads/")),
                ("note", models.CharField(blank=True, max_length=255)),
                ("status", models.CharField(choices=[("uploaded", "Uploaded"), ("processing", "Processing"), ("done", "Done"), ("failed", "Failed")], default="uploaded", max_length=16)),
                ("error", models.TextField(blank=True)),
                ("data_product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="governance.dataproduct")),
                ("uploaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Dataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                ("minio_path", models.CharField(blank=True, help_text="bucket/path inside MinIO", max_length=512)),
                ("format", models.CharField(default="parquet", max_length=16)),
                ("row_count", models.BigIntegerField(default=0)),
                ("refresh_cadence", models.CharField(default="daily", max_length=32)),
                ("pii_flag", models.BooleanField(default=False)),
                ("schema_subject", models.CharField(blank=True, max_length=255)),
                ("schema_version", models.IntegerField(blank=True, null=True)),
                ("marquez_dataset", models.CharField(blank=True, max_length=255)),
                ("data_product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="datasets", to="governance.dataproduct")),
                ("generation_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="datasets", to="governance.generationrun")),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("name", "data_product"), ("name", "generation_run")},
            },
        ),
        migrations.CreateModel(
            name="CatalogSyncLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("provider", models.CharField(choices=[("openmetadata", "OpenMetadata"), ("alation", "Alation"), ("mock", "Mock")], default="mock", max_length=32)),
                ("request_payload", models.JSONField(default=dict)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("success", models.BooleanField(default=False)),
                ("error", models.TextField(blank=True)),
                ("data_product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="catalog_logs", to="governance.dataproduct")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="LineageEdge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("upstream_dataset", models.CharField(max_length=255)),
                ("downstream_dataset", models.CharField(max_length=255)),
                ("transformation", models.TextField(blank=True)),
                ("data_product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="lineage_edges", to="governance.dataproduct")),
            ],
        ),
        migrations.CreateModel(
            name="Column",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=255)),
                ("data_type", models.CharField(max_length=64)),
                ("nullable", models.BooleanField(default=True)),
                ("description", models.TextField(blank=True)),
                ("pii", models.BooleanField(default=False)),
                ("business_glossary_term", models.CharField(blank=True, max_length=255)),
                ("ordinal", models.IntegerField(default=0)),
                ("dataset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="columns", to="governance.dataset")),
            ],
            options={
                "ordering": ["dataset", "ordinal"],
                "unique_together": {("dataset", "name")},
            },
        ),
        migrations.CreateModel(
            name="QualityRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("column_name", models.CharField(blank=True, max_length=255)),
                ("rule_type", models.CharField(help_text="not_null, unique, range, regex, ...", max_length=64)),
                ("expression", models.CharField(blank=True, max_length=512)),
                ("dataset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quality_rules", to="governance.dataset")),
            ],
        ),
    ]