from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import aprovar_orcamento_service


class InstallmentCountIntegrityTests(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.cliente = Cliente.objects.create(
            nome='Integridade de Parcelas',
            whatsapp='11999999999',
        )

    def _criar_projeto(self):
        return ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico='Projeto de integridade',
            etapa='2_ORCAMENTO',
            data_limite_orcamento=self.hoje,
        )

    def _kwargs(self, projeto, **overrides):
        valores = {
            'projeto_id': projeto.pk,
            'valor_total': Decimal('100.00'),
            'valor_entrada': Decimal('25.00'),
            'forma_pagamento_entrada': 'PIX',
            'data_inicio_producao': self.hoje,
            'data_entrega_prevista': self.hoje + timedelta(days=30),
            'forma_pagamento_restante': 'BOLETO',
            'qtd_parcelas_restante': 2,
        }
        valores.update(overrides)
        return valores

    @staticmethod
    def _snapshot_projeto(projeto):
        return ProjetoKanban.objects.values(
            'etapa',
            'valor_total',
            'valor_entrada',
            'saldo_restante',
            'data_inicio_producao',
            'data_entrega_prevista',
        ).get(pk=projeto.pk)

    @staticmethod
    def _snapshot_lancamentos(projeto):
        return list(
            LancamentoFinanceiro.objects.filter(projeto=projeto)
            .order_by('pk')
            .values(
                'pk',
                'tipo',
                'categoria',
                'projeto_id',
                'funcionario_id',
                'descricao',
                'valor',
                'forma_pagamento',
                'data_vencimento',
                'data_pagamento',
                'status',
            )
        )

    def _assert_rejeitada_sem_mutacao(self, quantidade):
        projeto = self._criar_projeto()
        projeto_antes = self._snapshot_projeto(projeto)
        lancamentos_antes = self._snapshot_lancamentos(projeto)

        with self.assertRaises(ValidationError):
            aprovar_orcamento_service(**self._kwargs(
                projeto,
                qtd_parcelas_restante=quantidade,
            ))

        projeto.refresh_from_db()
        self.assertEqual(self._snapshot_projeto(projeto), projeto_antes)
        self.assertEqual(self._snapshot_lancamentos(projeto), lancamentos_antes)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(projeto=projeto).count(),
            len(lancamentos_antes),
        )

    def test_fracao_decimal_e_rejeitada_sem_mutacao(self):
        self._assert_rejeitada_sem_mutacao(Decimal('1.5'))

    def test_fracao_float_e_rejeitada_sem_mutacao(self):
        self._assert_rejeitada_sem_mutacao(1.5)

    def test_fracao_string_e_rejeitada_sem_mutacao(self):
        self._assert_rejeitada_sem_mutacao('1.5')

    def test_contagens_invalidas_sao_rejeitadas_sem_mutacao(self):
        for quantidade in (0, -1, None, 'nao-numerico', Decimal('NaN'), Decimal('Infinity')):
            with self.subTest(quantidade=quantidade):
                self._assert_rejeitada_sem_mutacao(quantidade)

    def test_representacoes_integrais_validas_sao_aceitas(self):
        casos = (
            (1, 1),
            (2, 2),
            ('2', 2),
            (Decimal(2), 2),
            (Decimal('2.0'), 2),
            (2.0, 2),
        )

        for quantidade, normalizada in casos:
            with self.subTest(quantidade=quantidade):
                projeto = self._criar_projeto()
                aprovar_orcamento_service(**self._kwargs(
                    projeto,
                    qtd_parcelas_restante=quantidade,
                ))

                projeto.refresh_from_db()
                parcelas = list(
                    LancamentoFinanceiro.objects.filter(
                        projeto=projeto,
                        status='PENDENTE',
                    )
                )
                self.assertEqual(projeto.etapa, '3_APROVADO')
                self.assertEqual(len(parcelas), normalizada)
                self.assertEqual(
                    sum((parcela.valor for parcela in parcelas), Decimal('0.00')),
                    Decimal('75.00'),
                )

    def test_aprovacao_valida_preserva_total_residuo_minimo_e_idempotencia(self):
        projeto = self._criar_projeto()
        kwargs = self._kwargs(
            projeto,
            valor_total=Decimal('1000.00'),
            valor_entrada=Decimal('250.01'),
            qtd_parcelas_restante=3,
        )

        aprovar_orcamento_service(**kwargs)

        projeto.refresh_from_db()
        lancamentos = list(
            LancamentoFinanceiro.objects.filter(projeto=projeto).order_by('pk')
        )
        entrada = [lancamento for lancamento in lancamentos if lancamento.status == 'PAGO']
        parcelas = [lancamento for lancamento in lancamentos if lancamento.status == 'PENDENTE']
        self.assertEqual(projeto.etapa, '3_APROVADO')
        self.assertEqual(len(entrada), 1)
        self.assertEqual(len(parcelas), 3)
        self.assertEqual(projeto.saldo_restante, Decimal('749.99'))
        self.assertEqual(
            sum((lancamento.valor for lancamento in lancamentos), Decimal('0.00')),
            Decimal('1000.00'),
        )
        self.assertEqual(
            [parcela.valor for parcela in parcelas],
            [Decimal('250.00'), Decimal('250.00'), Decimal('249.99')],
        )
        self.assertTrue(all(parcela.valor >= Decimal('0.01') for parcela in parcelas))

        quantidade_antes = LancamentoFinanceiro.objects.filter(projeto=projeto).count()
        aprovar_orcamento_service(**kwargs)
        self.assertEqual(
            LancamentoFinanceiro.objects.filter(projeto=projeto).count(),
            quantidade_antes,
        )

    def test_minimo_de_um_centavo_por_parcela_e_preservado(self):
        projeto = self._criar_projeto()
        aprovar_orcamento_service(**self._kwargs(
            projeto,
            valor_total=Decimal('0.03'),
            valor_entrada=Decimal('0.00'),
            qtd_parcelas_restante=3,
        ))

        parcelas = list(
            LancamentoFinanceiro.objects.filter(
                projeto=projeto,
                status='PENDENTE',
            )
        )
        self.assertEqual(len(parcelas), 3)
        self.assertEqual(
            sum((parcela.valor for parcela in parcelas), Decimal('0.00')),
            Decimal('0.03'),
        )
        self.assertTrue(all(parcela.valor >= Decimal('0.01') for parcela in parcelas))
