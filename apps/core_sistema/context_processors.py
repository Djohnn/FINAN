from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato
from apps.kanban_projetos.models import ProjetoKanban

from .models import ConfiguracaoSistema
from .services import backup_realizado_hoje


def alertas_globais(request):
    """Expõe alertas sem executar operações de disco durante uma requisição."""
    hoje = timezone.localdate()
    orcamentos_atrasados = list(ProjetoKanban.objects.filter(
        etapa='2_ORCAMENTO',
        data_limite_orcamento__lte=hoje,
    ).select_related('cliente'))
    contatos_pendentes = list(AgendaContato.objects.filter(
        tipo__in=('POS_VENDA_30_DIAS', 'RETORNO_ORCAMENTO'),
        realizado=False,
        data_agendada__lte=hoje,
    ).select_related('cliente', 'projeto'))
    config = ConfiguracaoSistema.objects.filter(pk=1).first()
    if config is None or not config.caminho_backup_pendrive:
        backup_status = 'nao_configurado'
    elif config.mensagem_erro_backup:
        backup_status = 'falha'
    elif backup_realizado_hoje(config):
        backup_status = 'ok'
    else:
        backup_status = 'pendente_hoje'

    return {
        'orcamentos_atrasados': orcamentos_atrasados,
        'orcamentos_atrasados_count': len(orcamentos_atrasados),
        'contatos_pendentes': contatos_pendentes,
        'contatos_pendentes_count': len(contatos_pendentes),
        'backup_status': backup_status,
        'backup_alerta': backup_status != 'ok',
        'configuracao_sistema': config,
    }
