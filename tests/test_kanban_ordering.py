from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.clientes_agenda.models import Cliente
from apps.core_sistema.models import EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos import services
from apps.kanban_projetos.models import ConfiguracaoEtapaKanban, ProjetoKanban
from apps.kanban_projetos.selectors import get_kanban_stage_labels

DEFAULT = [code for code, _ in ProjetoKanban.ETAPA_CHOICES if code != '9_ARQUIVADO']
CUSTOM = list(reversed(DEFAULT))


class KanbanOrderingTests(TestCase):
    """Given legacy stages, when visual preferences change, then identities stay stable."""

    def setUp(self):
        self.url = reverse('kanban_projetos:stage_order_update')
        self.board_url = reverse('kanban_projetos:kanban_readonly')
        self.customer = Cliente.objects.create(nome='Ordering', whatsapp='11999999999')
        self.project = ProjetoKanban.objects.create(
            cliente=self.customer, titulo_servico='Budget', etapa='2_ORCAMENTO',
            data_limite_orcamento=timezone.localdate() - timedelta(days=1),
        )

    def reorder(self, codes=None):
        return self.client.post(self.url, {'ordem': CUSTOM if codes is None else codes})

    def codes(self, response=None):
        response = response or self.client.get(self.board_url)
        return [column['code'] for column in response.context['columns']]

    def test_default_without_configuration(self):
        self.assertEqual(self.codes(), DEFAULT)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_custom_order_is_rendered(self):
        self.assertEqual(self.reorder().status_code, 302)
        response = self.client.get(self.board_url)
        self.assertEqual(self.codes(response), CUSTOM)
        html = response.content.decode()
        positions = [html.index(f'id="column-{code}"') for code in CUSTOM]
        self.assertEqual(positions, sorted(positions))

    def test_fresh_client_reload_preserves_order(self):
        self.reorder()
        self.assertEqual(self.codes(Client().get(self.board_url)), CUSTOM)

    def test_reset_returns_exact_default_and_clears_positions(self):
        self.reorder()
        response = self.client.post(self.url, {'reset': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.codes(), DEFAULT)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exclude(posicao_visual=None).exists())

    def test_order_reset_keeps_custom_labels_including_archive(self):
        for code in ('2_ORCAMENTO', '9_ARQUIVADO'):
            services.salvar_label_etapa_service(codigo_interno=code, label='Custom ' + code)
        self.reorder()
        self.client.post(self.url, {'reset': '1'})
        labels = {stage.codigo_interno: stage.label_exibido for stage in get_kanban_stage_labels()}
        self.assertEqual(labels['2_ORCAMENTO'], 'Custom 2_ORCAMENTO')
        self.assertEqual(labels['9_ARQUIVADO'], 'Custom 9_ARQUIVADO')

    def test_reorder_preserves_custom_label(self):
        services.salvar_label_etapa_service(codigo_interno='2_ORCAMENTO', label='My budget')
        self.reorder()
        self.assertContains(self.client.get(self.board_url), 'My budget')

    def test_label_reset_does_not_reset_order(self):
        self.reorder()
        services.salvar_label_etapa_service(codigo_interno='2_ORCAMENTO', restaurar_padrao=True)
        self.assertEqual(self.codes(), CUSTOM)

    def assert_rejected(self, codes):
        self.reorder()
        before = list(ConfiguracaoEtapaKanban.objects.order_by('pk').values())
        self.assertEqual(self.reorder(codes).status_code, 400)
        self.assertEqual(list(ConfiguracaoEtapaKanban.objects.order_by('pk').values()), before)
        self.assertEqual(self.codes(), CUSTOM)

    def test_unknown_code_rejected(self):
        self.assert_rejected(DEFAULT[:-1] + ['UNKNOWN'])

    def test_duplicate_code_rejected(self):
        self.assert_rejected(DEFAULT[:-1] + [DEFAULT[0]])

    def test_missing_code_rejected(self):
        self.assert_rejected(DEFAULT[:-1])

    def test_geladeira_rejected(self):
        self.assert_rejected(DEFAULT[:-1] + ['9_ARQUIVADO'])
        self.assert_rejected(DEFAULT + ['9_ARQUIVADO'])

    def test_empty_payload_rejected_without_writes(self):
        self.assertEqual(self.reorder([]).status_code, 400)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_service_rejects_arbitrary_identity_types(self):
        for payload in ('1_CONTATO', None, [1, 2, 3, 4, 5, 6], {'1_CONTATO': 0}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                services.salvar_ordem_etapas_service(codigos=payload)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_write_failure_rolls_back_all_positions(self):
        self.reorder()
        before = list(ConfiguracaoEtapaKanban.objects.order_by('pk').values())
        original = connection.execute_wrapper
        def fail_update(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith('UPDATE'):
                execute(sql, params, many, context)
                raise RuntimeError('Simulated storage failure after write')
            return execute(sql, params, many, context)
        with original(fail_update), self.assertRaises(RuntimeError):
            services.salvar_ordem_etapas_service(codigos=DEFAULT)
        self.assertEqual(list(ConfiguracaoEtapaKanban.objects.order_by('pk').values()), before)

    def test_projects_are_unchanged_by_reorder_and_reset(self):
        before = list(ProjetoKanban.objects.values())
        self.reorder()
        self.client.post(self.url, {'reset': '1'})
        self.assertEqual(list(ProjetoKanban.objects.values()), before)

    def test_no_financial_side_effects(self):
        before = list(LancamentoFinanceiro.objects.values())
        self.reorder()
        self.client.post(self.url, {'reset': '1'})
        self.assertEqual(list(LancamentoFinanceiro.objects.values()), before)

    def test_no_business_event_side_effects(self):
        before = list(EventoSistema.objects.values())
        self.reorder()
        self.client.post(self.url, {'reset': '1'})
        self.assertEqual(list(EventoSistema.objects.values()), before)

    def test_overdue_alert_uses_identity_after_reorder(self):
        self.reorder()
        response = self.client.get(self.board_url)
        budget = next(c for c in response.context['columns'] if c['code'] == '2_ORCAMENTO')
        self.assertTrue(budget['projects'][0]['is_overdue'])
        self.assertEqual(response.context['orcamentos_atrasados_count'], 1)
        self.assertContains(response, 'global-budget-alert')

    def test_geladeira_stays_separate(self):
        self.project.etapa = '9_ARQUIVADO'
        self.project.save()
        self.reorder()
        response = self.client.get(self.board_url)
        self.assertNotIn('9_ARQUIVADO', self.codes(response))
        self.assertEqual(response.context['archived_column']['projects'][0]['project'].pk, self.project.pk)

    def test_csrf_missing_rejected_for_reorder_and_reset(self):
        for data in ({'ordem': CUSTOM}, {'reset': '1'}):
            self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, data).status_code, 403)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_valid_csrf_accepts_reorder(self):
        client = Client(enforce_csrf_checks=True)
        client.get(self.board_url)
        response = client.post(self.url, {'ordem': CUSTOM}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.codes(), CUSTOM)

    def test_get_is_rejected(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(ConfiguracaoEtapaKanban.objects.exists())

    def test_partial_configuration_falls_back_without_losing_stages(self):
        ConfiguracaoEtapaKanban.objects.create(codigo_interno='6_FINALIZADO', posicao_visual=0, label_personalizado='Done')
        self.assertEqual(self.codes(), DEFAULT)
        self.assertContains(self.client.get(self.board_url), 'Done')

    def test_legacy_label_only_configuration_falls_back(self):
        services.salvar_label_etapa_service(codigo_interno='2_ORCAMENTO', label='Legacy')
        self.assertEqual(self.codes(), DEFAULT)

    def test_duplicate_or_out_of_range_stored_positions_fall_back(self):
        self.reorder()
        ConfiguracaoEtapaKanban.objects.filter(codigo_interno=DEFAULT[0]).update(posicao_visual=0)
        self.assertEqual(self.codes(), DEFAULT)
        ConfiguracaoEtapaKanban.objects.filter(codigo_interno=DEFAULT[0]).update(posicao_visual=99)
        self.assertEqual(self.codes(), DEFAULT)

    def test_query_count_constant_for_one_and_multiple_projects(self):
        self.reorder()
        def fetch():
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(self.board_url)
                self.assertEqual(self.codes(response), CUSTOM)
            return captured.captured_queries
        few = fetch()
        ProjetoKanban.objects.bulk_create([
            ProjetoKanban(cliente=self.customer, titulo_servico=f'Project {i}', etapa=DEFAULT[i % 6])
            for i in range(30)
        ])
        many = fetch()
        print(f"ORDERING_QUERIES: projects=1 queries={len(few)}; projects=31 queries={len(many)}; configuration_queries=1")
        self.assertEqual(len(few), len(many))
        for queries in (few, many):
            config_queries = [q for q in queries if 'kanban_projetos_configuracaoetapakanban' in q['sql']]
            self.assertEqual(len(config_queries), 1)

    def test_identities_and_choices_remain_exact(self):
        before = tuple(ProjetoKanban.ETAPA_CHOICES)
        self.reorder()
        self.assertEqual(tuple(ProjetoKanban.ETAPA_CHOICES), before)
        self.assertEqual([c for c, _ in before], DEFAULT + ['9_ARQUIVADO'])


    def test_arrow_forms_submit_complete_permutations_and_exclude_archive(self):
        from html.parser import HTMLParser

        class Forms(HTMLParser):
            def __init__(self):
                super().__init__()
                self.forms = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'form':
                    self.current = {'action': attrs.get('action'), 'codes': [], 'disabled': False}
                if self.current is not None and tag == 'input' and attrs.get('name') == 'ordem':
                    self.current['codes'].append(attrs['value'])
                if self.current is not None and tag == 'button' and 'disabled' in attrs:
                    self.current['disabled'] = True

            def handle_endtag(self, tag):
                if tag == 'form' and self.current is not None:
                    self.forms.append(self.current)
                    self.current = None

        response = self.client.get(self.board_url)
        parser = Forms()
        parser.feed(response.content.decode())
        reorder_forms = [form for form in parser.forms if form['action'] == self.url and form['codes']]
        self.assertEqual(len(reorder_forms), 10)
        for form in reorder_forms:
            self.assertEqual(set(form['codes']), set(DEFAULT))
            self.assertEqual(len(form['codes']), 6)
        response = self.reorder(reorder_forms[0]['codes'])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.codes(), [DEFAULT[1], DEFAULT[0], *DEFAULT[2:]])
        self.assertContains(self.client.get(self.board_url), 'Restaurar ordem padrão')


class KanbanOrderingMigrationTests(TransactionTestCase):
    """Given a legacy label, when migrating forward/backward, then its value survives."""

    def test_forward_rollback_preserves_labels_and_can_reapply(self):
        previous = [('kanban_projetos', '0002_configuracaoetapakanban')]
        current = [('kanban_projetos', '0003_configuracaoetapakanban_posicao_visual')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            old_model = executor.loader.project_state(previous).apps.get_model(
                'kanban_projetos', 'ConfiguracaoEtapaKanban',
            )
            old_model.objects.create(codigo_interno='2_ORCAMENTO', label_personalizado='Preserved')
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            new_model = executor.loader.project_state(current).apps.get_model(
                'kanban_projetos', 'ConfiguracaoEtapaKanban',
            )
            row = new_model.objects.get()
            self.assertIsNone(row.posicao_visual)
            row.posicao_visual = 4
            row.save()
            executor = MigrationExecutor(connection)
            executor.migrate(previous)
            old_model = executor.loader.project_state(previous).apps.get_model(
                'kanban_projetos', 'ConfiguracaoEtapaKanban',
            )
            self.assertEqual(old_model.objects.get().label_personalizado, 'Preserved')
            columns = connection.introspection.get_table_description(
                connection.cursor(), 'kanban_projetos_configuracaoetapakanban',
            )
            self.assertNotIn('posicao_visual', [column.name for column in columns])
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            self.assertEqual(ConfiguracaoEtapaKanban.objects.get().label_personalizado, 'Preserved')
            self.assertIsNone(ConfiguracaoEtapaKanban.objects.get().posicao_visual)
        finally:
            MigrationExecutor(connection).migrate(current)
