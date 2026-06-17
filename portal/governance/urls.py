from django.urls import path
from . import views

app_name = "governance"

urlpatterns = [
    path("", views.home, name="home"),
    path("generator/", views.generator_page, name="generator"),
    path("generator/run/", views.trigger_generation, name="trigger_generation"),
    path("generator/status/<int:run_id>/", views.run_status, name="run_status"),
    path("generator/excel/<int:run_id>/", views.download_excel, name="download_excel"),
]
