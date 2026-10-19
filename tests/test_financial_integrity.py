from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import (
    aprovar_orcamento_service,
    finalizar_projeto_service,
)


class FinancialIntegrityTests(TestCase):
    def setUp(self):
        cliente = Cliente.objects.create(nome='Integridade', whatsapp='11999999999')
        self.hoje = timezone.localdate()
        self.projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico='Projeto teste',
            etapa='2_ORCAMENTO',
            data_limite_orcamento=self.hoje,
        )
        self.kwargs = {
            'projeto_id': self.projeto.pk,
            'valor_total': Decimal('10.00'),
            'valor_entrada': Decimal('2.00'),
            'forma_pagamento_entrada': 'PIX',
            'data_inicio_producao': self.hoje,
            'data_entrega_prevista': self.hoje + timedelta(days=30),
            'qtd_parcelas_restante': 3,
        }

    def test_aprovacao_rejeita_parcelamento_com_parcela_nao_positiva(self):
        """Given saldo insuficiente; When aprovar; Then rejeitar sem mutacao."""
        for saldo, quantidade in [('0.03', 5), ('0.01', 2)]:
            with self.subTest(saldo=saldo):
                projeto = ProjetoKanban.objects.create(
                    cliente=self.projeto.cliente,
                    titulo_servico='Invalido',
                    etapa='2_ORCAMENTO',
                    data_limite_orcamento=self.hoje,
                )
                estado = ProjetoKanban.objects.values().get(pk=projeto.pk)
                with self.assertRaises(ValidationError):
                    aprovar_orcamento_service(**{
                        **self.kwargs, 'projeto_id': projeto.pk,
                        'valor_total': Decimal('2.00') + Decimal(saldo),
                        'qtd_parcelas_restante': quantidade,
                    })
                self.assertEqual(ProjetoKanban.objects.values().get(pk=projeto.pk), estado)
                self.assertEqual(projeto.lancamentos.count(), 0)

    def test_aprovacao_distribui_residuo_sem_perder_centavos(self):
        """Given saldo residual; When aprovar; Then soma exata e parcelas positivas."""
        for saldo, quantidade in [('0.08', 5), ('10.00', 3), ('0.05', 5)]:
            with self.subTest(saldo=saldo):
                projeto = ProjetoKanban.objects.create(
                    cliente=self.projeto.cliente,
                    titulo_servico='Residual',
                    etapa='2_ORCAMENTO',
                    data_limite_orcamento=self.hoje,
                )
                aprovar_orcamento_service(**{
                    **self.kwargs, 'projeto_id': projeto.pk,
                    'valor_total': Decimal(saldo), 'valor_entrada': Decimal('0.00'),
                    'qtd_parcelas_restante': quantidade,
                })
                parcelas = list(projeto.lancamentos.order_by('id'))
                valores = [parcela.valor for parcela in parcelas]
                self.assertEqual(len(valores), quantidade)
                self.assertEqual(sum(valores, Decimal('0.00')), Decimal(saldo))
                self.assertTrue(all(valor > Decimal('0.00') for valor in valores), valores)
                self.assertEqual(
                    [parcela.data_vencimento for parcela in parcelas],
                    [self.kwargs['data_entrega_prevista'] + timedelta(days=30 * i) for i in range(quantidade)],
                )

    def test_finalizacao_com_quitacao_sincroniza_saldo_persistido(self):
        """Given projeto aprovado e saldo; When quitar na entrega; Then ambos saldos zero."""
        aprovar_orcamento_service(**self.kwargs)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.saldo_restante, Decimal('8.00'))
        resultado = finalizar_projeto_service(self.projeto.pk, quitar_pendencias=True)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.lancamentos.filter(status='PENDENTE').count(), 0)
        self.assertEqual(self.projeto.saldo_em_aberto, Decimal('0.00'))
        self.assertEqual(self.projeto.valor_total, Decimal('10.00'))
        self.assertEqual(self.projeto.valor_entrada, Decimal('2.00'))
        self.assertEqual(self.projeto.etapa, '6_FINALIZADO')
        self.assertEqual(self.projeto.saldo_restante, Decimal('0.00'))
        self.assertEqual(resultado.saldo_restante, Decimal('0.00'))

    def test_finalizacao_sem_quitacao_preserva_saldo(self):
        """Given saldo pendente; When finalizar sem quitar; Then preservar divida."""
        aprovar_orcamento_service(**self.kwargs)
        finalizar_projeto_service(self.projeto.pk, quitar_pendencias=False)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.lancamentos.filter(status='PENDENTE').count(), 3)
        self.assertEqual(self.projeto.saldo_restante, Decimal('8.00'))
        self.assertEqual(self.projeto.saldo_em_aberto, Decimal('8.00'))
        self.assertEqual(self.projeto.valor_total, Decimal('10.00'))
        self.assertEqual(self.projeto.valor_entrada, Decimal('2.00'))

    def test_finalizacao_quita_entrada_mas_preserva_saida_pendente(self):
        """Given entrada e saida pendentes; When quitar; Then somente entrada paga."""
        aprovar_orcamento_service(**self.kwargs)
        saida = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='OUTROS',
            projeto=self.projeto,
            descricao='Saída pendente do projeto',
            valor=Decimal('3.00'),
            forma_pagamento='PIX',
            data_vencimento=self.hoje,
            status='PENDENTE',
        )

        finalizar_projeto_service(self.projeto.pk, quitar_pendencias=True)

        entradas = LancamentoFinanceiro.objects.filter(
            projeto=self.projeto,
            tipo='ENTRADA',
        )
        self.assertFalse(entradas.filter(status='PENDENTE').exists())
        saida.refresh_from_db()
        self.assertEqual(saida.status, 'PENDENTE')
        self.assertIsNone(saida.data_pagamento)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.saldo_restante, Decimal('0.00'))
        self.assertEqual(self.projeto.saldo_em_aberto, Decimal('0.00'))

    def test_finalizacao_rejeita_forma_invalida_sem_mutacao(self):
        """Given entrada pendente; When forma inválida; Then falhar sem mutação."""
        aprovar_orcamento_service(**self.kwargs)
        projeto_antes = ProjetoKanban.objects.values(
            'etapa', 'data_entrega_realizada', 'saldo_restante',
        ).get(pk=self.projeto.pk)
        lancamentos_antes = list(
            LancamentoFinanceiro.objects.filter(projeto=self.projeto)
            .order_by('id')
            .values()
        )
        agenda_antes = list(
            AgendaContato.objects.filter(projeto=self.projeto)
            .order_by('id')
            .values()
        )
        agenda_count_antes = AgendaContato.objects.count()

        with self.assertRaises(ValidationError):
            finalizar_projeto_service(
                self.projeto.pk,
                quitar_pendencias=True,
                forma_pagamento_quitacao='INVALIDA',
            )

        self.assertEqual(
            ProjetoKanban.objects.values(
                'etapa', 'data_entrega_realizada', 'saldo_restante',
            ).get(pk=self.projeto.pk),
            projeto_antes,
        )
        self.assertEqual(
            list(
                LancamentoFinanceiro.objects.filter(projeto=self.projeto)
                .order_by('id')
                .values()
            ),
            lancamentos_antes,
        )
        self.assertEqual(AgendaContato.objects.count(), agenda_count_antes)
        self.assertEqual(
            list(
                AgendaContato.objects.filter(projeto=self.projeto)
                .order_by('id')
                .values()
            ),
            agenda_antes,
        )

    def test_finalizacao_com_forma_valida_quita_apenas_entradas(self):
        """Given entrada e saída pendentes; When forma válida; Then preservar saída."""
        aprovar_orcamento_service(**self.kwargs)
        saida = LancamentoFinanceiro.objects.create(
            tipo='SAIDA',
            categoria='OUTROS',
            projeto=self.projeto,
            descricao='Saída pendente do projeto',
            valor=Decimal('3.00'),
            forma_pagamento='PIX',
            data_vencimento=self.hoje,
            status='PENDENTE',
        )
        pendentes_antes = list(
            LancamentoFinanceiro.objects.filter(
                projeto=self.projeto,
                tipo='ENTRADA',
                status='PENDENTE',
            ).values_list('pk', flat=True)
        )

        finalizar_projeto_service(
            self.projeto.pk,
            quitar_pendencias=True,
            forma_pagamento_quitacao='DINHEIRO',
        )

        entradas = LancamentoFinanceiro.objects.filter(
            projeto=self.projeto,
            tipo='ENTRADA',
        )
        entradas_quitadas = entradas.filter(pk__in=pendentes_antes)
        self.assertFalse(entradas_quitadas.filter(status='PENDENTE').exists())
        self.assertFalse(entradas_quitadas.exclude(forma_pagamento='DINHEIRO').exists())
        self.assertTrue(entradas_quitadas.filter(status='PAGO', data_pagamento=self.hoje).exists())
        self.assertEqual(
            entradas.exclude(pk__in=pendentes_antes).values_list('forma_pagamento', flat=True).get(),
            'PIX',
        )
        saida.refresh_from_db()
        self.assertEqual(saida.status, 'PENDENTE')
        self.assertEqual(saida.forma_pagamento, 'PIX')
        self.assertIsNone(saida.data_pagamento)

    def test_finalizacao_reverte_quitacao_se_pos_venda_falhar(self):
        """Given aprovacao; When falhar apos quitar; Then rollback integral."""
        aprovar_orcamento_service(**self.kwargs)
        estado = ProjetoKanban.objects.values().get(pk=self.projeto.pk)
        lancamentos = list(self.projeto.lancamentos.order_by('id').values())
        with patch(
            'apps.kanban_projetos.services.AgendaContato.objects.create',
            side_effect=RuntimeError('Falha controlada de teste'),
        ), self.assertRaises(RuntimeError):
            finalizar_projeto_service(self.projeto.pk, quitar_pendencias=True)
        self.assertEqual(ProjetoKanban.objects.values().get(pk=self.projeto.pk), estado)
        self.assertEqual(list(self.projeto.lancamentos.order_by('id').values()), lancamentos)
        self.assertEqual(AgendaContato.objects.count(), 0)
