from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import sincronizar_saldo_projeto
from .models import ProjetoKanban


@transaction.atomic
def aprovar_orcamento_service(
    projeto_id: int,
    valor_total: Decimal | float | str,
    valor_entrada: Decimal | float | str,
    forma_pagamento_entrada: str,
    data_inicio_producao,
    data_entrega_prevista,
    forma_pagamento_restante: str = 'PIX',
    qtd_parcelas_restante: int = 1,
) -> ProjetoKanban:
    """
    Aprova um orçamento no Kanban, atualizando o card para 3_APROVADO e
    gerando os lançamentos financeiros de entrada e parcelas restantes.
    """
    try:
        valor_total = Decimal(str(valor_total)).quantize(Decimal('0.01'))
        valor_entrada = Decimal(str(valor_entrada)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Os valores do orçamento devem ser números válidos com até 2 casas decimais.") from exc

    if valor_total <= Decimal('0.00'):
        raise ValidationError("O valor total do projeto deve ser maior que zero.")

    if valor_entrada < Decimal('0.00'):
        raise ValidationError("O valor de entrada não pode ser negativo.")

    if valor_entrada > valor_total:
        raise ValidationError("O valor de entrada não pode ser maior que o valor total do projeto.")

    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    hoje = timezone.localdate()

    formas_validas = {value for value, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES}
    if forma_pagamento_entrada not in formas_validas:
        raise ValidationError("A forma de pagamento da entrada é inválida.")
    if forma_pagamento_restante not in formas_validas:
        raise ValidationError("A forma de pagamento do saldo é inválida.")
    if not isinstance(data_inicio_producao, date) or not isinstance(data_entrega_prevista, date):
        raise ValidationError("As datas de início e de entrega são obrigatórias e válidas.")
    if data_inicio_producao > data_entrega_prevista:
        raise ValidationError("A data de início não pode ser posterior à data de entrega.")
    try:
        qtd_parcelas_restante = int(qtd_parcelas_restante)
    except (TypeError, ValueError) as exc:
        raise ValidationError("A quantidade de parcelas deve ser um número inteiro positivo.") from exc
    if qtd_parcelas_restante < 1:
        raise ValidationError("A quantidade de parcelas deve ser um número inteiro positivo.")

    # O lock do card torna a operação idempotente mesmo com duas requisições
    # concorrentes: a segunda chamada observa que o orçamento já foi aprovado.
    if projeto.etapa != '2_ORCAMENTO':
        if projeto.etapa == '3_APROVADO' and projeto.lancamentos.filter(
            categoria='SERVICO_CLIENTE'
        ).exists():
            return projeto
        raise ValidationError("Somente orçamentos na etapa 2 podem ser aprovados.")

    saldo_restante = valor_total - valor_entrada
    saldo_centavos = int(saldo_restante * 100)
    if saldo_restante > Decimal('0.00') and qtd_parcelas_restante > saldo_centavos:
        raise ValidationError("Cada parcela do saldo deve ter pelo menos R$ 0,01.")

    # 1. Atualiza dados do projeto
    projeto.etapa = '3_APROVADO'
    projeto.valor_total = valor_total
    projeto.valor_entrada = valor_entrada
    projeto.data_inicio_producao = data_inicio_producao
    projeto.data_entrega_prevista = data_entrega_prevista
    projeto.saldo_restante = projeto.valor_total - projeto.valor_entrada
    projeto.save(update_fields=[
        'etapa', 'valor_total', 'valor_entrada', 'saldo_restante',
        'data_inicio_producao', 'data_entrega_prevista', 'atualizado_em',
    ])

    # 2. Registra Entrada (se houver valor de entrada > 0)
    if valor_entrada > Decimal('0.00'):
        LancamentoFinanceiro.objects.create(
            tipo='ENTRADA',
            categoria='SERVICO_CLIENTE',
            projeto=projeto,
            descricao=f"Entrada de projeto - {projeto.titulo_servico} ({projeto.cliente.nome})",
            valor=valor_entrada,
            forma_pagamento=forma_pagamento_entrada,
            data_vencimento=hoje,
            data_pagamento=hoje,
            status='PAGO',
        )

    # 3. Registra Parcelas do Saldo Restante (se saldo > 0)
    saldo_restante = projeto.saldo_restante
    if saldo_restante > Decimal('0.00'):
        data_base_vencimento = data_entrega_prevista or hoje

        # Distribui os centavos restantes, um por parcela, em ordem estável.
        centavos_base, centavos_residuais = divmod(saldo_centavos, qtd_parcelas_restante)

        for i in range(qtd_parcelas_restante):
            valor_parcela = Decimal(centavos_base + (1 if i < centavos_residuais else 0)) / 100
            vencimento_parcela = data_base_vencimento + timedelta(days=30 * i)

            descricao_parcela = (
                f"Saldo restante ({i + 1}/{qtd_parcelas_restante}) - "
                f"{projeto.titulo_servico} ({projeto.cliente.nome})"
            )

            LancamentoFinanceiro.objects.create(
                tipo='ENTRADA',
                categoria='SERVICO_CLIENTE',
                projeto=projeto,
                descricao=descricao_parcela,
                valor=valor_parcela,
                forma_pagamento=forma_pagamento_restante,
                data_vencimento=vencimento_parcela,
                data_pagamento=None,
                status='PENDENTE',
            )

    return projeto


@transaction.atomic
def arquivar_orcamento_service(
    projeto_id: int,
    motivo_arquivamento: str,
    observacao: str = '',
    dias_lembrete_retorno: Optional[int] = None,
) -> ProjetoKanban:
    """
    Move o projeto para a geladeira (9_ARQUIVADO), registrando o motivo
    e opcionalmente agendando um retorno futuro no calendário de contatos.
    """
    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    projeto.etapa = '9_ARQUIVADO'
    projeto.motivo_arquivamento = motivo_arquivamento
    projeto.observacao_arquivamento = observacao or ''
    projeto.save()

    if dias_lembrete_retorno and int(dias_lembrete_retorno) > 0:
        hoje = timezone.localdate()
        data_retorno = hoje + timedelta(days=int(dias_lembrete_retorno))
        AgendaContato.objects.create(
            cliente=projeto.cliente,
            projeto=projeto,
            tipo='RETORNO_ORCAMENTO',
            data_agendada=data_retorno,
            realizado=False,
            feedback_cliente=f"Lembrete de retorno para orçamento arquivado: {projeto.titulo_servico}",
        )

    return projeto


@transaction.atomic
def reativar_orcamento_service(
    projeto_id: int,
    nova_etapa: str = '2_ORCAMENTO',
) -> ProjetoKanban:
    """
    Reativa um orçamento arquivado da geladeira devolvendo para o Kanban ativo.
    """
    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    projeto.etapa = nova_etapa
    projeto.motivo_arquivamento = ''
    projeto.save()
    return projeto


@transaction.atomic
def finalizar_projeto_service(
    projeto_id: int,
    quitar_pendencias: bool = False,
    forma_pagamento_quitacao: Optional[str] = None,
) -> ProjetoKanban:
    """
    Finaliza o projeto (6_FINALIZADO), registra data de entrega realizada,
    opcionalmente quita parcelas pendentes e cria o gatilho automático
    de Pós-Venda para daqui a 30 dias.
    """
    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    hoje = timezone.localdate()

    if quitar_pendencias and forma_pagamento_quitacao:
        formas_validas = {value for value, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES}
        if forma_pagamento_quitacao not in formas_validas:
            raise ValidationError("A forma de pagamento da quitação é inválida.")

    projeto.etapa = '6_FINALIZADO'
    projeto.data_entrega_realizada = hoje
    projeto.save()

    # 1. Se o cliente quitou na entrega, baixa os lançamentos pendentes
    if quitar_pendencias:
        lancamentos_pendentes = LancamentoFinanceiro.objects.filter(
            projeto=projeto,
            tipo='ENTRADA',
            status='PENDENTE'
        )
        for lancamento in lancamentos_pendentes:
            lancamento.status = 'PAGO'
            lancamento.data_pagamento = hoje
            if forma_pagamento_quitacao:
                lancamento.forma_pagamento = forma_pagamento_quitacao
            lancamento.save()
        projeto.saldo_restante = sincronizar_saldo_projeto(projeto.pk)

    # 2. Gatilho automático de Pós-Venda (hoje + 30 dias) se ainda não existir
    ja_existe_pos_venda = AgendaContato.objects.filter(
        projeto=projeto,
        tipo='POS_VENDA_30_DIAS'
    ).exists()

    if not ja_existe_pos_venda:
        AgendaContato.objects.create(
            cliente=projeto.cliente,
            projeto=projeto,
            tipo='POS_VENDA_30_DIAS',
            data_agendada=hoje + timedelta(days=30),
            realizado=False,
        )

    return projeto
