import shutil
import sqlite3
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.core_sistema.context_processors import alertas_globais
from apps.core_sistema.models import ConfiguracaoSistema
from apps.core_sistema.services import executar_backup_pendrive
from apps.financeiro.models import LancamentoFinanceiro
from apps.financeiro.services import registrar_pagamento_service
from apps.kanban_projetos.models import ProjetoKanban
from apps.kanban_projetos.services import aprovar_orcamento_service


class AprovacaoEFinanceiroTests(TestCase):
    def setUp(self):
        self.cliente = Cliente.objects.create(nome='Cliente Teste', whatsapp='11999999999')
        self.projeto = ProjetoKanban.objects.create(
            cliente=self.cliente,
            titulo_servico='Cozinha',
            etapa='2_ORCAMENTO',
            data_limite_orcamento=timezone.localdate(),
        )
        self.kwargs = {
            'projeto_id': self.projeto.id,
            'valor_total': Decimal('1000.00'),
            'valor_entrada': Decimal('250.00'),
            'forma_pagamento_entrada': 'PIX',
            'data_inicio_producao': timezone.localdate() + timedelta(days=1),
            'data_entrega_prevista': timezone.localdate() + timedelta(days=31),
            'forma_pagamento_restante': 'BOLETO',
            'qtd_parcelas_restante': 3,
        }

    def test_aprovacao_normal_cria_entrada_e_parcelas_com_soma_exata(self):
        projeto = aprovar_orcamento_service(**self.kwargs)
        self.assertEqual(projeto.etapa, '3_APROVADO')
        self.assertEqual(LancamentoFinanceiro.objects.filter(projeto=projeto).count(), 4)
        self.assertEqual(
            sum(LancamentoFinanceiro.objects.filter(projeto=projeto).values_list('valor', flat=True)),
            Decimal('1000.00'),
        )
        self.assertEqual(projeto.saldo_restante, Decimal('750.00'))

    def test_aprovacao_repetida_nao_duplica_lancamentos(self):
        primeira = aprovar_orcamento_service(**self.kwargs)
        primeira_count = LancamentoFinanceiro.objects.filter(projeto=primeira).count()
        segunda = aprovar_orcamento_service(**self.kwargs)
        self.assertEqual(segunda.pk, primeira.pk)
        self.assertEqual(LancamentoFinanceiro.objects.filter(projeto=primeira).count(), primeira_count)

    def test_aprovacao_rejeita_valores_datas_formas_e_parcelas_invalidos(self):
        casos = (
            {'valor_total': Decimal(0)},
            {'valor_entrada': Decimal(-1)},
            {'valor_entrada': Decimal(1001)},
            {'forma_pagamento_entrada': 'INVALIDA'},
            {'data_inicio_producao': self.kwargs['data_entrega_prevista'] + timedelta(days=1)},
            {'qtd_parcelas_restante': 0},
        )
        for alteracao in casos:
            with self.subTest(alteracao=alteracao), self.assertRaises(ValidationError):
                aprovar_orcamento_service(**{**self.kwargs, **alteracao})
        self.assertEqual(LancamentoFinanceiro.objects.count(), 0)
        self.projeto.refresh_from_db()
        self.assertEqual(self.projeto.etapa, '2_ORCAMENTO')

    def test_quitacao_atualiza_saldo_sem_alterar_valor_contratado(self):
        projeto = aprovar_orcamento_service(**self.kwargs)
        parcela = LancamentoFinanceiro.objects.filter(projeto=projeto, status='PENDENTE').first()
        registrar_pagamento_service(parcela.id, parcela.valor, 'PIX')
        projeto.refresh_from_db()
        self.assertEqual(projeto.valor_total, Decimal('1000.00'))
        self.assertEqual(projeto.saldo_restante, Decimal('500.00'))
        self.assertEqual(projeto.saldo_em_aberto, Decimal('500.00'))


class BackupEAlertasTests(TestCase):
    def test_backup_indisponivel_e_nova_tentativa_com_integridade_e_retencao(self):
        config = ConfiguracaoSistema.get_solo()
        config.caminho_backup_pendrive = ''
        config.save(update_fields=['caminho_backup_pendrive'])
        sucesso, _ = executar_backup_pendrive()
        self.assertFalse(sucesso)
        config.refresh_from_db()
        self.assertFalse(config.ultimo_backup_sucesso)

        tmp = tempfile.mkdtemp(dir=Path.cwd())
        try:
            destino = Path(tmp)
            source = destino / 'source.sqlite3'
            source_conn = sqlite3.connect(source)
            source_conn.execute('CREATE TABLE marcador (id INTEGER PRIMARY KEY)')
            source_conn.commit()
            source_conn.close()
            config.caminho_backup_pendrive = str(destino)
            config.dias_retencao_backup = 1
            config.save(update_fields=['caminho_backup_pendrive', 'dias_retencao_backup'])
            antigo = destino / 'backup_marcenaria_2000-01-01.sqlite3'
            antigo.write_bytes(b'old')
            outro = destino / 'nao_apagar.txt'
            outro.write_text('preservar', encoding='utf-8')
            with patch(
                'apps.core_sistema.services.settings.DATABASES',
                {'default': {'NAME': str(source)}},
            ):
                sucesso, _ = executar_backup_pendrive()
            self.assertTrue(sucesso)
            backup = destino / f"backup_marcenaria_{timezone.localdate():%Y-%m-%d}.sqlite3"
            self.assertTrue(backup.exists())
            conn = sqlite3.connect(backup)
            try:
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            finally:
                conn.close()
            self.assertFalse(antigo.exists())
            self.assertTrue(outro.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_alertas_filtram_orcamentos_e_contatos_pendentes(self):
        cliente = Cliente.objects.create(nome='Alertas', whatsapp='11988888888')
        ProjetoKanban.objects.create(
            cliente=cliente, titulo_servico='Atrasado', etapa='2_ORCAMENTO',
            data_limite_orcamento=timezone.localdate(),
        )
        ProjetoKanban.objects.create(
            cliente=cliente, titulo_servico='Aprovado', etapa='3_APROVADO',
            data_limite_orcamento=timezone.localdate(),
        )
        AgendaContato.objects.create(
            cliente=cliente, tipo='RETORNO_ORCAMENTO',
            data_agendada=timezone.localdate(), realizado=False,
        )
        contexto = alertas_globais(None)
        self.assertEqual(contexto['orcamentos_atrasados_count'], 1)
        self.assertEqual(contexto['contatos_pendentes_count'], 1)

    def test_conclusao_de_contato_bloqueia_feedback_curto(self):
        cliente = Cliente.objects.create(nome='Contato', whatsapp='11977777777')
        contato = AgendaContato.objects.create(
            cliente=cliente, tipo='POS_VENDA_30_DIAS',
            data_agendada=timezone.localdate(), realizado=False,
        )
        from apps.clientes_agenda.services import concluir_pos_venda_service

        with self.assertRaises(ValidationError):
            concluir_pos_venda_service(contato.id, 'curto', 'SATISFEITO')
