from django.contrib import admin

from .models import ProjetoKanban


@admin.register(ProjetoKanban)
class ProjetoKanbanAdmin(admin.ModelAdmin):
    list_display = (
        'titulo_servico',
        'cliente',
        'etapa',
        'valor_total',
        'valor_entrada',
        'saldo_restante',
        'data_entrega_prevista',
        'atualizado_em',
    )
    list_filter = ('etapa', 'motivo_arquivamento', 'data_entrega_prevista')
    search_fields = ('titulo_servico', 'cliente__nome', 'cliente__whatsapp')
    readonly_fields = ('criado_em', 'atualizado_em')
