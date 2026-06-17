from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django.utils.html import format_html

from .models import (
    SourceConnection,
    GenerationRun,
    DataProduct,
    Dataset,
    Column,
    LineageEdge,
    QualityRule,
    DataProductUpload,
    CatalogSyncLog,
)

admin.site.site_header = "Metadata Governance Platform"
admin.site.site_title = "Metadata Governance"
admin.site.index_title = "Governance Console"


class ColumnInline(admin.TabularInline):
    model = Column
    extra = 0
    fields = ("name", "data_type", "nullable", "pii", "business_glossary_term", "ordinal")


class DatasetInline(admin.TabularInline):
    model = Dataset
    extra = 0
    fields = ("name", "minio_path", "format", "row_count", "pii_flag")
    show_change_link = True


class LineageEdgeInline(admin.TabularInline):
    model = LineageEdge
    extra = 0


class QualityRuleInline(admin.TabularInline):
    model = QualityRule
    extra = 0


@admin.register(SourceConnection)
class SourceConnectionAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "enabled", "created_at")
    list_filter = ("kind", "enabled")
    search_fields = ("name",)


@admin.register(GenerationRun)
class GenerationRunAdmin(admin.ModelAdmin):
    change_list_template = "admin/governance/generationrun_changelist.html"
    list_display = ("id", "domain", "chosen_instance", "size", "status", "progress_pct", "created_at", "duration_seconds")
    list_filter = ("size", "status")
    search_fields = ("domain", "chosen_instance")
    readonly_fields = ("status", "progress_pct", "spec", "excel_object_key", "error", "started_at", "finished_at", "chosen_instance", "row_count_per_dataset")

    def get_urls(self):
        urls = super().get_urls()
        return [
            path("generator/", self.admin_site.admin_view(self.generator_view), name="governance_generator"),
        ] + urls

    def generator_view(self, request):
        from .tasks import generate_data_product
        if request.method == "POST":
            domain = request.POST.get("domain", "school").strip() or "school"
            size = request.POST.get("size", "small")
            if size not in {"small", "medium", "large"}:
                size = "small"
            run = GenerationRun.objects.create(domain=domain, size=size, status="pending")
            generate_data_product.delay(run.id)
            messages.success(request, f"Triggered {size} dataset generation for '{domain}' (Run #{run.id}).")
            return redirect("admin:governance_generationrun_changelist")
        runs = GenerationRun.objects.all()[:20]
        return render(request, "admin/governance/generator.html", {
            "title": "Data Generator",
            "runs": runs,
            "opts": GenerationRun._meta,
        })


@admin.register(DataProduct)
class DataProductAdmin(admin.ModelAdmin):
    list_display = ("name", "domain", "tier", "status", "owner_email", "catalog_link", "published_at")
    list_filter = ("status", "tier", "domain", "catalog_provider")
    search_fields = ("name", "domain", "owner_email")
    inlines = [DatasetInline, LineageEdgeInline]
    readonly_fields = ("status", "catalog_provider", "external_id", "external_url", "contract_object_key", "error", "published_at")

    def catalog_link(self, obj):
        if not obj.external_id:
            return "—"
        if obj.external_url:
            return format_html('<a href="{}" target="_blank"><code>{}</code></a>', obj.external_url, obj.external_id[:18])
        return format_html('<code>{}</code>', obj.external_id[:18])
    catalog_link.short_description = "Catalog ID"


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "data_product", "format", "row_count", "minio_path", "schema_subject", "schema_version")
    list_filter = ("format", "pii_flag")
    search_fields = ("name", "minio_path", "schema_subject")
    inlines = [ColumnInline, QualityRuleInline]


@admin.register(DataProductUpload)
class DataProductUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "file", "status", "data_product", "uploaded_by", "created_at")
    list_filter = ("status",)
    readonly_fields = ("status", "error", "data_product", "uploaded_by")

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(CatalogSyncLog)
class CatalogSyncLogAdmin(admin.ModelAdmin):
    list_display = ("id", "data_product", "provider", "success", "created_at")
    list_filter = ("provider", "success")
    readonly_fields = [f.name for f in CatalogSyncLog._meta.fields]
