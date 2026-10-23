from django.urls import path

from . import views


app_name = "financeiro"

urlpatterns = [
    path(
        "contas-a-receber/",
        views.central_contas_receber_view,
        name="central_contas_receber",
    ),
]
