from django.urls import path

from . import views

app_name = "clientes_agenda"

urlpatterns = [
    path("", views.clientes_index_view, name="clientes"),
    path("<int:cliente_id>/", views.cliente_360_view, name="cliente_360"),
    path("<int:cliente_id>/historico/", views.cliente_history_view, name="cliente_history"),
    path(
        "<int:cliente_id>/projetos/<int:projeto_id>/whatsapp/",
        views.cliente_project_whatsapp_view,
        name="cliente_project_whatsapp",
    ),
    path(
        "<int:cliente_id>/contatos/<int:contato_id>/whatsapp/",
        views.cliente_contact_whatsapp_view,
        name="cliente_contact_whatsapp",
    ),
]
