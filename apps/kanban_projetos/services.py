from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato
from apps.core_sistema.services import registrar_evento
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import sincronizar_saldo_projeto

from .models import ProjetoKanban

KANBAN_LABEL_MAX_LENGTH = 100


@transaction.atomic
def salvar_label_etapa_service(
    *,
    codigo_interno: str,
    label: str | None = None,
    restaurar_padrao: bool = False,
):
    """Persiste somente o nome visual de uma identidade legada conhecida."""
    from .models import ConfiguracaoEtapaKanban
    from .selectors import get_kanban_stage_label

    get_kanban_stage_label(codigo_interno)
    if restaurar_padrao:
        normalized_label = ""
    else:
        if not isinstance(label, str):
            raise ValidationError("Informe um nome visível para a etapa.")
        normalized_label = label.strip()
        if not normalized_label:
            raise ValidationError("Informe um nome visível para a etapa.")
        if len(normalized_label) > KANBAN_LABEL_MAX_LENGTH:
            raise ValidationError(
                f"O nome visível deve ter no máximo {KANBAN_LABEL_MAX_LENGTH} caracteres."
            )

    configuration, _created = ConfiguracaoEtapaKanban.objects.select_for_update().get_or_create(
        codigo_interno=codigo_interno,
        defaults={"label_personalizado": normalized_label},
    )
    configuration.label_personalizado = normalized_label
    configuration.save(update_fields=["label_personalizado", "atualizado_em"])
    return configuration


@transaction.atomic
def salvar_ordem_etapas_service(*, codigos: list[str] | None = None, restaurar_padrao: bool = False):
    """Persist a complete visual permutation without mutating labels or projects."""
    from .models import ConfiguracaoEtapaKanban
    from .selectors import ARCHIVED_STAGE_CODE, get_kanban_stage_defaults

    default_codes = [
        stage.codigo_interno for stage in get_kanban_stage_defaults()
        if stage.codigo_interno != ARCHIVED_STAGE_CODE
    ]
    if restaurar_padrao:
        ConfiguracaoEtapaKanban.objects.filter(codigo_interno__in=default_codes).update(
            posicao_visual=None, atualizado_em=timezone.now(),
        )
        return
    if (
        not isinstance(codigos, (list, tuple))
        or any(not isinstance(code, str) for code in codigos)
        or len(codigos) != len(default_codes)
        or set(codigos) != set(default_codes)
    ):
        raise ValidationError("Informe exatamente uma vez cada uma das seis etapas do fluxo, sem a Geladeira.")

    # The first database operation is a write. SQLite serializes writers before any
    # read; every writer takes row locks in canonical order on databases with locks.
    ConfiguracaoEtapaKanban.objects.bulk_create(
        [ConfiguracaoEtapaKanban(codigo_interno=code) for code in default_codes],
        ignore_conflicts=True,
    )
    configurations = list(
        ConfiguracaoEtapaKanban.objects.select_for_update()
        .filter(codigo_interno__in=default_codes).order_by("codigo_interno")
    )
    positions = {code: index for index, code in enumerate(codigos)}
    now = timezone.now()
    for configuration in configurations:
        configuration.posicao_visual = positions[configuration.codigo_interno]
        configuration.atualizado_em = now
    ConfiguracaoEtapaKanban.objects.bulk_update(configurations, ["posicao_visual", "atualizado_em"])


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
    valor_total = LancamentoFinanceiro.validar_valor_monetario(valor_total).quantize(Decimal('0.01'))
    valor_entrada = LancamentoFinanceiro.validar_valor_monetario(
        valor_entrada, permitir_zero=True,
    ).quantize(Decimal('0.01'))

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
        qtd_parcelas_decimal = Decimal(str(qtd_parcelas_restante))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(
            "A quantidade de parcelas deve ser um número inteiro positivo."
        ) from None
    if (
        not qtd_parcelas_decimal.is_finite()
        or qtd_parcelas_decimal != qtd_parcelas_decimal.to_integral_value()
    ):
        raise ValidationError(
            "A quantidade de parcelas deve ser um número inteiro positivo."
        )
    qtd_parcelas_restante = int(qtd_parcelas_decimal)
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

    registrar_evento(
        tipo='ORCAMENTO_APROVADO',
        dominio='KANBAN',
        entidade_tipo='ProjetoKanban',
        entidade_id=projeto.pk,
    )

    return projeto


@transaction.atomic
def arquivar_orcamento_service(
    projeto_id: int,
    motivo_arquivamento: str,
    observacao: str = '',
    dias_lembrete_retorno: int | str | None = None,
) -> ProjetoKanban:
    """
    Move o projeto para a geladeira (9_ARQUIVADO), registrando o motivo
    e opcionalmente agendando um retorno futuro no calendário de contatos.
    """
    motivos_validos = {
        value for value, _label in ProjetoKanban.MOTIVO_ARQUIVAMENTO_CHOICES
    }
    if motivo_arquivamento not in motivos_validos:
        raise ValidationError('O motivo do arquivamento é inválido.')

    dias_normalizados = None
    if dias_lembrete_retorno is not None:
        if isinstance(dias_lembrete_retorno, (Decimal, float)):
            valor_numerico = Decimal(str(dias_lembrete_retorno))
            if not valor_numerico.is_finite():
                raise ValidationError(
                    'Os dias do lembrete de retorno devem ser numéricos.'
                )
            if valor_numerico < 0:
                raise ValidationError(
                    'Os dias do lembrete de retorno não podem ser negativos.'
                )
            if valor_numerico != valor_numerico.to_integral_value():
                raise ValidationError(
                    'Os dias do lembrete de retorno devem ser números inteiros.'
                )
        try:
            dias_normalizados = int(dias_lembrete_retorno)
        except (OverflowError, TypeError, ValueError):
            raise ValidationError(
                'Os dias do lembrete de retorno devem ser numéricos.'
            ) from None
        if dias_normalizados < 0:
            raise ValidationError(
                'Os dias do lembrete de retorno não podem ser negativos.'
            )

    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    etapa_anterior = projeto.etapa
    projeto.etapa = '9_ARQUIVADO'
    projeto.motivo_arquivamento = motivo_arquivamento
    projeto.observacao_arquivamento = observacao or ''
    projeto.save()

    if dias_normalizados is not None and dias_normalizados > 0:
        hoje = timezone.localdate()
        data_retorno = hoje + timedelta(days=dias_normalizados)
        AgendaContato.objects.create(
            cliente=projeto.cliente,
            projeto=projeto,
            tipo='RETORNO_ORCAMENTO',
            data_agendada=data_retorno,
            realizado=False,
            feedback_cliente=f"Lembrete de retorno para orçamento arquivado: {projeto.titulo_servico}",
        )

    if etapa_anterior != '9_ARQUIVADO':
        registrar_evento(
            tipo='ORCAMENTO_ARQUIVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id=projeto.pk,
            metadata={'motivo_codigo': motivo_arquivamento},
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

    if projeto.etapa != '9_ARQUIVADO':
        raise ValidationError(
            'Somente projetos na etapa 9_ARQUIVADO podem ser reativados.'
        )

    etapas_validas = {
        value for value, _label in ProjetoKanban.ETAPA_CHOICES
    }
    if nova_etapa not in etapas_validas:
        raise ValidationError('A nova etapa da reativação é inválida.')

    projeto.etapa = nova_etapa
    projeto.motivo_arquivamento = ''
    projeto.save()
    if nova_etapa != '9_ARQUIVADO':
        registrar_evento(
            tipo='ORCAMENTO_REATIVADO',
            dominio='KANBAN',
            entidade_tipo='ProjetoKanban',
            entidade_id=projeto.pk,
        )
    return projeto


@transaction.atomic
def finalizar_projeto_service(
    projeto_id: int,
    quitar_pendencias: bool = False,
    forma_pagamento_quitacao: str | None = None,
) -> ProjetoKanban:
    """
    Finaliza o projeto (6_FINALIZADO), registra data de entrega realizada,
    opcionalmente quita parcelas pendentes e cria o gatilho automático
    de Pós-Venda para daqui a 30 dias.
    """
    projeto = ProjetoKanban.objects.select_for_update().get(id=projeto_id)
    if projeto.etapa != '5_ENTREGA':
        raise ValidationError(
            'Somente projetos na etapa 5_ENTREGA podem ser finalizados.'
        )

    hoje = timezone.localdate()

    if quitar_pendencias and forma_pagamento_quitacao:
        formas_validas = {value for value, _ in LancamentoFinanceiro.FORMA_PAGAMENTO_CHOICES}
        if forma_pagamento_quitacao not in formas_validas:
            raise ValidationError("A forma de pagamento da quitação é inválida.")

    projeto.etapa = '6_FINALIZADO'
    if projeto.data_entrega_realizada is None:
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

    registrar_evento(
        tipo='PROJETO_FINALIZADO',
        dominio='KANBAN',
        entidade_tipo='ProjetoKanban',
        entidade_id=projeto.pk,
    )

    return projeto
