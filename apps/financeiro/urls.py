from django.urls import path

from . import views

app_name = "financeiro"

urlpatterns = [
    path(
        "rentabilidade-projetos/",
        views.rentabilidade_projetos_view,
        name="rentabilidade_projetos",
    ),
    path(
        "rentabilidade-projetos/<int:projeto_id>/",
        views.rentabilidade_projeto_view,
        name="rentabilidade_projeto",
    ),
    path(
        "contas-a-receber/",
        views.central_contas_receber_view,
        name="central_contas_receber",
    ),
]
