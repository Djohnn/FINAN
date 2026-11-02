from django.contrib import admin

from .models import ConfiguracaoSistema, EventoSistema


@admin.register(ConfiguracaoSistema)
class ConfiguracaoSistemaAdmin(admin.ModelAdmin):
    list_display = (
        'nome_marcenaria',
        'caminho_backup_pendrive',
        'dias_retencao_backup',
        'ultimo_backup_em',
        'ultimo_backup_sucesso',
        'mensagem_erro_backup',
    )

    def has_add_permission(self, request):
        # Permite apenas 1 registro (Singleton)
        if ConfiguracaoSistema.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Evita deletar a configuração do sistema
        return False


@admin.register(EventoSistema)
class EventoSistemaAdmin(admin.ModelAdmin):
    list_display = (
        'tipo',
        'dominio',
        'entidade_tipo',
        'entidade_id',
        'descricao',
        'criado_em',
    )
    readonly_fields = (
        'tipo',
        'dominio',
        'entidade_tipo',
        'entidade_id',
        'descricao',
        'metadata',
        'criado_em',
    )
    list_filter = ('tipo', 'dominio')
    search_fields = ('descricao', 'entidade_id')
    ordering = ('-criado_em', '-id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
