from typing import ClassVar

from django.db import models


class TipoEventoSistema(models.TextChoices):
    ORCAMENTO_APROVADO = 'ORCAMENTO_APROVADO', 'Orçamento aprovado'
    ORCAMENTO_ARQUIVADO = 'ORCAMENTO_ARQUIVADO', 'Orçamento arquivado'
    ORCAMENTO_REATIVADO = 'ORCAMENTO_REATIVADO', 'Orçamento reativado'
    PROJETO_FINALIZADO = 'PROJETO_FINALIZADO', 'Projeto finalizado'
    PAGAMENTO_FUNCIONARIO_CRIADO = (
        'PAGAMENTO_FUNCIONARIO_CRIADO',
        'Pagamento de funcionário criado',
    )
    LANCAMENTO_QUITADO = 'LANCAMENTO_QUITADO', 'Lançamento quitado'
    CONTATO_CONCLUIDO = 'CONTATO_CONCLUIDO', 'Contato concluído'
    BACKUP_CONCLUIDO = 'BACKUP_CONCLUIDO', 'Backup concluído'
    BACKUP_FALHOU = 'BACKUP_FALHOU', 'Backup falhou'
    RESTAURACAO_CONCLUIDA = 'RESTAURACAO_CONCLUIDA', 'Restauração concluída'
    RESTAURACAO_FALHOU_ROLLBACK_OK = (
        'RESTAURACAO_FALHOU_ROLLBACK_OK',
        'Restauração falhou; rollback validado',
    )


class DominioEventoSistema(models.TextChoices):
    KANBAN = 'KANBAN', 'Kanban'
    EQUIPE = 'EQUIPE', 'Equipe'
    FINANCEIRO = 'FINANCEIRO', 'Financeiro'
    AGENDA = 'AGENDA', 'Agenda'
    BACKUP = 'BACKUP', 'Backup'
    RESTAURACAO = 'RESTAURACAO', 'Restauração'


class ConfiguracaoSistema(models.Model):
    """
    Configuração global do sistema em padrão Singleton.
    Guarda dados da marcenaria e parâmetros do backup diário em pendrive.
    """
    nome_marcenaria = models.CharField(
        max_length=100,
        default="Minha Marcenaria",
        verbose_name="Nome da Marcenaria"
    )
    caminho_backup_pendrive = models.CharField(
        max_length=255,
        default=r"E:\Backups_Marcenaria",
        verbose_name="Caminho da Pasta / Pendrive de Backup"
    )
    dias_retencao_backup = models.PositiveIntegerField(
        default=30,
        verbose_name="Dias de Retenção do Backup"
    )
    ultimo_backup_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Último Backup em"
    )
    ultimo_backup_sucesso = models.BooleanField(
        default=False,
        verbose_name="Último Backup com Sucesso"
    )
    mensagem_erro_backup = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Mensagem de Erro do Backup"
    )

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    def __str__(self):
        return self.nome_marcenaria

    def save(self, *args, **kwargs):
        # Garante que sempre existirá apenas 1 registro (Singleton)
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        """Retorna ou cria a instância única de configuração."""
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "nome_marcenaria": "Minha Marcenaria",
                "caminho_backup_pendrive": r"E:\Backups_Marcenaria",
                "dias_retencao_backup": 30,
            }
        )
        return obj


class EventoSistema(models.Model):
    tipo = models.CharField(
        max_length=50,
        choices=TipoEventoSistema.choices,
    )
    dominio = models.CharField(
        max_length=15,
        choices=DominioEventoSistema.choices,
    )
    entidade_tipo = models.CharField(
        max_length=60,
        null=True,
        blank=True,
    )
    entidade_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
    )
    descricao = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Evento do Sistema'
        verbose_name_plural = 'Eventos do Sistema'
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=[
                    'dominio',
                    'entidade_tipo',
                    'entidade_id',
                    '-criado_em',
                    '-id',
                ],
                name='evento_ent_hist_idx',
            ),
            models.Index(
                fields=['tipo', '-criado_em', '-id'],
                name='evento_tipo_data_idx',
            ),
        ]
