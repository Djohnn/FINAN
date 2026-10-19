import re
from decimal import Decimal
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ProjetoKanban(models.Model):
    """
    Card principal do fluxo operacional do Kanban na marcenaria.
    Gerencia do primeiro contato até o pós-venda ou arquivamento.
    """
    ETAPA_CHOICES = [
        ('1_CONTATO', 'Novo Contato'),
        ('2_ORCAMENTO', 'Em Orçamento'),
        ('3_APROVADO', 'Aprovado / Aguardando Produção'),
        ('4_PRODUCAO', 'Em Produção'),
        ('5_ENTREGA', 'Pronto para Entrega'),
        ('6_FINALIZADO', 'Entregue / Finalizado'),
        ('9_ARQUIVADO', 'Arquivado (Geladeira)'),
    ]

    MOTIVO_ARQUIVAMENTO_CHOICES = [
        ('PRECO_ALTO', 'Achou Caro'),
        ('ADIOU_OBRA', 'Adiou Obra'),
        ('FECHOU_CONCORRENTE', 'Fechou com Concorrente'),
        ('SEM_RETORNO', 'Sem Retorno'),
        ('OUTRO', 'Outro'),
    ]

    cliente = models.ForeignKey(
        'clientes_agenda.Cliente',
        on_delete=models.CASCADE,
        related_name="projetos",
        verbose_name="Cliente"
    )
    titulo_servico = models.CharField(
        max_length=200,
        verbose_name="Título do Serviço"
    )
    descricao_medidas = models.TextField(
        blank=True,
        verbose_name="Descrição e Medidas"
    )
    etapa = models.CharField(
        max_length=20,
        choices=ETAPA_CHOICES,
        default='1_CONTATO',
        db_index=True,
        verbose_name="Etapa Atual"
    )
    data_limite_orcamento = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data Limite do Orçamento"
    )
    data_inicio_producao = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Início da Produção"
    )
    data_entrega_prevista = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data Prevista de Entrega"
    )
    data_entrega_realizada = models.DateField(
        null=True,
        blank=True,
        verbose_name="Data de Entrega Realizada"
    )
    valor_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor Total (R$)"
    )
    valor_entrada = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Valor de Entrada (R$)"
    )
    saldo_restante = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Saldo Restante (R$)"
    )
    motivo_arquivamento = models.CharField(
        max_length=30,
        choices=MOTIVO_ARQUIVAMENTO_CHOICES,
        blank=True,
        verbose_name="Motivo do Arquivamento"
    )
    observacao_arquivamento = models.TextField(
        blank=True,
        verbose_name="Observações do Arquivamento"
    )
    criado_em = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    atualizado_em = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Projeto no Kanban"
        verbose_name_plural = "Projetos no Kanban"
        ordering = ["-atualizado_em"]

    def __str__(self):
        return f"{self.titulo_servico} - {self.cliente.nome} ({self.get_etapa_display()})"

    def clean(self):
        super().clean()
        if self.etapa == '2_ORCAMENTO' and self.data_limite_orcamento is None:
            raise ValidationError({
                'data_limite_orcamento': (
                    'A etapa 2_ORCAMENTO exige uma data limite do orçamento.'
                ),
            })

    def save(self, *args, **kwargs):
        """Persiste o card sem alterar o valor contratado ou o saldo financeiro.

        O saldo em aberto é mantido pelos services a partir de
        LancamentoFinanceiro. Recalcular aqui a partir de
        valor_total - valor_entrada apagaria pagamentos efetivos quando um
        card fosse salvo por outro fluxo.
        """
        self.clean()
        super().save(*args, **kwargs)

    @property
    def saldo_em_aberto(self) -> Decimal:
        """Retorna o saldo efetivamente devido, ignorando lançamentos cancelados."""
        from django.db.models import Sum

        from apps.financeiro.models import LancamentoFinanceiro

        total = LancamentoFinanceiro.objects.filter(
            projeto=self,
            tipo='ENTRADA',
            status='PENDENTE',
        ).aggregate(total=Sum('valor'))['total']
        return total or Decimal('0.00')

    @property
    def is_orcamento_vencido(self) -> bool:
        """
        Retorna True se estiver na etapa '2_ORCAMENTO' e a data limite for menor ou igual a hoje.
        """
        if self.etapa == '2_ORCAMENTO' and self.data_limite_orcamento:
            return self.data_limite_orcamento <= timezone.localdate()
        return False

    @property
    def is_entrega_atrasada(self) -> bool:
        """
        Retorna True se o projeto estiver em andamento (3_APROVADO, 4_PRODUCAO, 5_ENTREGA)
        e a data prevista de entrega for anterior a hoje.
        """
        etapas_ativas = ('3_APROVADO', '4_PRODUCAO', '5_ENTREGA')
        if self.etapa in etapas_ativas and self.data_entrega_prevista:
            return self.data_entrega_prevista < timezone.localdate()
        return False

    def get_whatsapp_url(self) -> str:
        """
        Limpa o número de telefone do cliente, garante DDI 55 e gera
        o link https://wa.me/55... com mensagem personalizada para a etapa do Kanban.
        """
        if not self.cliente or not self.cliente.whatsapp:
            return ""

        # Remove caracteres não numéricos
        telefone_limpo = re.sub(r'\D', '', self.cliente.whatsapp)
        if not telefone_limpo:
            return ""

        # Garante DDI 55
        if telefone_limpo.startswith('55') and len(telefone_limpo) in (12, 13):
            numero = telefone_limpo
        else:
            numero = f"55{telefone_limpo}"

        # Obtém nome da marcenaria da configuração
        try:
            from apps.core_sistema.models import ConfiguracaoSistema
            config = ConfiguracaoSistema.get_solo()
            nome_marcenaria = config.nome_marcenaria or "Marcenaria"
        except Exception:
            nome_marcenaria = "Marcenaria"

        nome_cliente = self.cliente.nome.split()[0] if self.cliente.nome else "Cliente"
        servico = self.titulo_servico

        mensagens = {
            '1_CONTATO': (
                f"Olá, {nome_cliente}! Tudo bem? Aqui é da {nome_marcenaria}. "
                f"Recebemos seu contato referente ao projeto '{servico}'. "
                f"Como podemos te ajudar com os detalhes e medidas?"
            ),
            '2_ORCAMENTO': (
                f"Olá, {nome_cliente}! Aqui é da {nome_marcenaria}. "
                f"Estamos finalizando a proposta para o projeto '{servico}'. "
                f"Ficou com alguma dúvida ou gostaria de agendar uma conversa?"
            ),
            '3_APROVADO': (
                f"Olá, {nome_cliente}! Parabéns! Seu projeto '{servico}' foi aprovado "
                f"na {nome_marcenaria}. Já estamos organizando os preparativos para produção!"
            ),
            '4_PRODUCAO': (
                f"Olá, {nome_cliente}! Passando para avisar que o seu projeto '{servico}' "
                f"já entrou em produção na {nome_marcenaria}. Estamos caprichando em cada detalhe!"
            ),
            '5_ENTREGA': (
                f"Olá, {nome_cliente}! Boas notícias: o projeto '{servico}' está pronto para "
                f"entrega/instalação! Podemos agendar o melhor dia e horário para você?"
            ),
            '6_FINALIZADO': (
                f"Olá, {nome_cliente}! Agradecemos imensamente pela confiança na {nome_marcenaria} "
                f"para a realização do projeto '{servico}'. Esperamos que tenha superado as expectativas!"
            ),
            '9_ARQUIVADO': (
                f"Olá, {nome_cliente}, tudo bem? Aqui é da {nome_marcenaria}. "
                f"Passando para saber se ainda tem planos para o projeto '{servico}'. "
                f"Quando quiser retomar, estamos à disposição!"
            ),
        }

        mensagem = mensagens.get(
            self.etapa,
            f"Olá, {nome_cliente}! Aqui é da {nome_marcenaria} a respeito do projeto '{servico}'."
        )

        return f"https://wa.me/{numero}?text={quote(mensagem)}"

    @property
    def whatsapp_url(self) -> str:
        """Property wrapper para get_whatsapp_url()."""
        return self.get_whatsapp_url()
