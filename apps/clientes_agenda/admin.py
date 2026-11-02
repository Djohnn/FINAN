from django.contrib import admin

from .models import AgendaContato, Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nome', 'whatsapp', 'endereco', 'criado_em')
    search_fields = ('nome', 'whatsapp', 'endereco')
    ordering = ('nome',)


@admin.register(AgendaContato)
class AgendaContatoAdmin(admin.ModelAdmin):
    list_display = (
        'cliente',
        'projeto',
        'tipo',
        'data_agendada',
        'realizado',
        'nivel_satisfacao',
        'realizado_em',
    )
    list_filter = ('realizado', 'tipo', 'nivel_satisfacao', 'data_agendada')
    search_fields = ('cliente__nome', 'feedback_cliente')
    date_hierarchy = 'data_agendada'
