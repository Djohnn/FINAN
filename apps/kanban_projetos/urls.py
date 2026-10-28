from django.urls import path

from . import views

app_name = "kanban_projetos"

urlpatterns = [
    path("kanban/", views.kanban_readonly_view, name="kanban_readonly"),
    path(
        "kanban/etapas/<str:codigo_interno>/label/",
        views.stage_label_update,
        name="stage_label_update",
    ),
]
