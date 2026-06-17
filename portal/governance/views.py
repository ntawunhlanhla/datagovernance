from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import GenerationRun, DataProduct
from .tasks import generate_data_product
from .services.minio_client import MinIOService


def home(request):
    recent_runs = GenerationRun.objects.all()[:10]
    recent_products = DataProduct.objects.all()[:10]
    return render(request, "governance/home.html", {
        "recent_runs": recent_runs,
        "recent_products": recent_products,
    })


@login_required
def generator_page(request):
    runs = GenerationRun.objects.all()[:20]
    return render(request, "governance/generator.html", {"runs": runs})


@login_required
@require_POST
def trigger_generation(request):
    domain = (request.POST.get("domain") or "school").strip()
    size = request.POST.get("size", "small")
    if size not in {"small", "medium", "large"}:
        return JsonResponse({"error": "invalid size"}, status=400)
    run = GenerationRun.objects.create(domain=domain, size=size, status="pending")
    generate_data_product.delay(run.id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"run_id": run.id, "status": run.status})
    return HttpResponseRedirect(reverse("governance:generator"))


@login_required
def run_status(request, run_id: int):
    run = get_object_or_404(GenerationRun, pk=run_id)
    return JsonResponse({
        "id": run.id,
        "domain": run.domain,
        "chosen_instance": run.chosen_instance,
        "size": run.size,
        "status": run.status,
        "progress_pct": run.progress_pct,
        "error": run.error,
        "excel_object_key": run.excel_object_key,
        "datasets": [
            {"name": d.name, "rows": d.row_count, "path": d.minio_path}
            for d in run.datasets.all()
        ],
    })


@login_required
def download_excel(request, run_id: int):
    run = get_object_or_404(GenerationRun, pk=run_id)
    if not run.excel_object_key:
        raise Http404("Excel not generated yet")
    minio = MinIOService()
    data = minio.get_object_bytes("excel", run.excel_object_key)
    response = HttpResponse(data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    filename = run.excel_object_key.rsplit("/", 1)[-1]
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
