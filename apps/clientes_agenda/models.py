import re
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db import models


class Cliente(models.Model):
    """
    Cadastro de clientes da marcenaria.
    """
    nome = models.CharField(max_length=150, verbose_name="Nome Completo")
    whatsapp = models.CharField(max_length=20, verbose_name="WhatsApp")
    endereco = models.TextField(blank=True, verbose_name="Endereço Completo")
    observacoes = models.TextField(blank=True, verbose_name="Observações Gerais")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Cadastrado em")

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class AgendaContato(models.Model):
    """
    Agenda de contatos e pós-venda para clientes.
    Integrado com o calendário e disparador de alertas.
    """
    TIPO_CHOICES = [
        ('POS_VENDA_30_DIAS', 'Pós-Venda 30 Dias'),
        ('RETORNO_ORCAMENTO', 'Retorno de Orçamento'),
        ('LIGACAO_MANUAL', 'Ligação Manual'),
    ]

    SATISFACAO_CHOICES = [
        ('SATISFEITO', 'Satisfeito'),
        ('AJUSTE_SOLICITADO', 'Ajuste Solicitado'),
        ('INSATISFEITO', 'Insatisfeito'),
    ]

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="agendamentos",
        verbose_name="Cliente"
    )
    projeto = models.ForeignKey(
        'kanban_projetos.ProjetoKanban',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos_contato",
        verbose_name="Projeto Relacionado"
    )
    tipo = models.CharField(
        max_length=30,
        choices=TIPO_CHOICES,
        verbose_name="Tipo de Contato"
    )
    data_agendada = models.DateField(
        db_index=True,
        verbose_name="Data Agendada"
    )
    realizado = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Contato Realizado"
    )
    nivel_satisfacao = models.CharField(
        max_length=30,
        choices=SATISFACAO_CHOICES,
        blank=True,
        verbose_name="Nível de Satisfação"
    )
    feedback_cliente = models.TextField(
        blank=True,
        verbose_name="Feedback / Resposta do Cliente"
    )
    realizado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Realizado em"
    )

    class Meta:
        verbose_name = "Agenda de Contato"
        verbose_name_plural = "Agenda de Contatos"
        ordering = ["data_agendada"]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.cliente.nome} ({self.data_agendada.strftime('%d/%m/%Y')})"

    def clean(self):
        super().clean()
        if self.realizado:
            # feedback_cliente deve ter no mínimo 10 caracteres sem contar espaços
            texto_sem_espacos = "".join((self.feedback_cliente or "").split())
            if len(texto_sem_espacos) < 10:
                raise ValidationError({
                    'feedback_cliente': "O feedback do cliente deve conter no mínimo 10 caracteres explicativos (sem contar espaços)."
                })

            if self.tipo == 'POS_VENDA_30_DIAS' and not self.nivel_satisfacao:
                raise ValidationError({
                    'nivel_satisfacao': "O nível de satisfação é obrigatório para contatos de Pós-Venda de 30 Dias."
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def get_whatsapp_url(self) -> str:
        """
        Gera o link https://wa.me/55... com mensagem personalizada para Pós-Venda ou Retorno de Orçamento.
        """
        if not self.cliente or not self.cliente.whatsapp:
            return ""

        telefone_limpo = re.sub(r'\D', '', self.cliente.whatsapp)
        if not telefone_limpo:
            return ""

        if telefone_limpo.startswith('55') and len(telefone_limpo) in (12, 13):
            numero = telefone_limpo
        else:
            numero = f"55{telefone_limpo}"

        try:
            from apps.core_sistema.models import ConfiguracaoSistema
            config = ConfiguracaoSistema.get_solo()
            nome_marcenaria = config.nome_marcenaria or "Marcenaria"
        except Exception:
            nome_marcenaria = "Marcenaria"

        nome_cliente = self.cliente.nome.split()[0] if self.cliente.nome else "Cliente"
        titulo_projeto = self.projeto.titulo_servico if self.projeto else "seu serviço planejado"

        if self.tipo == 'POS_VENDA_30_DIAS':
            mensagem = (
                f"Olá, {nome_cliente}! Tudo bem? Aqui é da {nome_marcenaria}. "
                f"Já faz cerca de 30 dias que entregamos o seu projeto '{titulo_projeto}'. "
                f"Passando para saber se ficou tudo perfeito e como está sendo o uso no dia a dia!"
            )
        elif self.tipo == 'RETORNO_ORCAMENTO':
            mensagem = (
                f"Olá, {nome_cliente}! Tudo bem? Aqui é da {nome_marcenaria}. "
                f"Passando para saber se ainda tem planos para o projeto '{titulo_projeto}'. "
                f"Surgiu alguma dúvida ou gostaria de ajustar a proposta?"
            )
        else:
            mensagem = (
                f"Olá, {nome_cliente}! Tudo bem? Aqui é da {nome_marcenaria}. "
                f"Estou entrando em contato a respeito do seu projeto '{titulo_projeto}'. "
                f"Podemos conversar um momento?"
            )

        return f"https://wa.me/{numero}?text={quote(mensagem)}"

    @property
    def whatsapp_url(self) -> str:
        """Property wrapper para get_whatsapp_url()."""
        return self.get_whatsapp_url()
