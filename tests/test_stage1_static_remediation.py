from datetime import UTC, datetime
from datetime import timezone as datetime_timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.db.utils import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone as django_timezone

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.clientes_agenda.selectors import _event_project_id, _load_events
from apps.core_sistema import services
from apps.core_sistema.models import ConfiguracaoSistema, EventoSistema
from apps.financeiro.models import LancamentoFinanceiro
from apps.kanban_projetos.models import ProjetoKanban

_NONE_INT_TYPE_ERROR = (
    "int() argument must be a string, a bytes-like object or a real number, "
    "not 'NoneType'"
)


class DatabaseNameCompatibilityTests(SimpleTestCase):
    def _database_settings(self, name):
        return patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': name}},
        )

    def test_string_and_path_database_names_are_accepted_by_both_callers(self):
        for name in ('C:/isolated/source.sqlite3', Path('C:/isolated/source.sqlite3')):
            with self.subTest(name_type=type(name).__name__), self._database_settings(name):
                expected = Path(name).expanduser()
                self.assertEqual(services._configured_live_database(), expected)
                with patch.object(services, '_is_regular_source_file', return_value=False) as is_file:
                    self.assertEqual(
                        services.executar_backup_pendrive(),
                        (False, 'Arquivo SQLite de origem não encontrado.'),
                    )
                is_file.assert_called_once_with(expected)

    def test_empty_and_none_database_names_keep_existing_results(self):
        for name in ('', None):
            with self.subTest(name=name), self._database_settings(name):
                with self.assertRaisesRegex(
                    ValueError,
                    '^Arquivo SQLite oficial não está configurado\\.$',
                ):
                    services._configured_live_database()
                with patch.object(services, '_is_regular_source_file') as is_file:
                    self.assertEqual(
                        services.executar_backup_pendrive(),
                        (False, 'Arquivo SQLite de origem não configurado.'),
                    )
                is_file.assert_not_called()

    def test_truthy_incompatible_database_name_keeps_path_type_error(self):
        invalid_name = object()
        with self._database_settings(invalid_name):
            with self.assertRaises(TypeError):
                services._configured_live_database()
            with self.assertRaises(TypeError):
                services.executar_backup_pendrive()


class _WhatsAppConfigurationFailureMixin:
    def setUp(self):
        self.customer = Cliente.objects.create(
            nome='Mariana Alves',
            whatsapp='(81) 90000-1010',
        )
        self.subject = self.make_subject()

    def make_subject(self):
        raise NotImplementedError

    def url(self):
        return self.subject.get_whatsapp_url()

    def assert_message_contains(self, url, text):
        message = parse_qs(urlparse(url).query)['text'][0]
        self.assertIn(text, message)

    def test_existing_configuration_is_read_without_writing_it(self):
        config = ConfiguracaoSistema.get_solo()
        config.nome_marcenaria = 'Oficina Stage1'
        config.save(update_fields=['nome_marcenaria'])
        before = ConfiguracaoSistema.objects.count()

        url = self.url()

        self.assertTrue(url.startswith('https://wa.me/5581900001010?'))
        self.assert_message_contains(url, 'Oficina Stage1')
        self.assertEqual(ConfiguracaoSistema.objects.count(), before)

    def test_missing_configuration_uses_model_default_without_creating_row(self):
        ConfiguracaoSistema.objects.all().delete()
        default_name = ConfiguracaoSistema._meta.get_field('nome_marcenaria').get_default()

        url = self.url()

        self.assert_message_contains(url, default_name)
        self.assertFalse(ConfiguracaoSistema.objects.exists())

    def test_database_error_uses_fallback_without_writing_configuration(self):
        with patch.object(
            ConfiguracaoSistema.objects,
            'filter',
            side_effect=DatabaseError('injected configuration read failure'),
        ):
            url = self.url()

        self.assert_message_contains(url, 'Marcenaria')
        self.assertFalse(ConfiguracaoSistema.objects.exists())

    def test_unexpected_runtime_error_uses_fallback_without_writing_configuration(self):
        with patch.object(
            ConfiguracaoSistema.objects,
            'filter',
            side_effect=RuntimeError('injected unexpected failure'),
        ):
            url = self.url()

        self.assert_message_contains(url, 'Marcenaria')
        self.assertFalse(ConfiguracaoSistema.objects.exists())

    def test_unclassified_lookup_error_propagates_without_writing_configuration(self):
        with patch.object(
            ConfiguracaoSistema.objects,
            'filter',
            side_effect=LookupError('injected unclassified configuration failure'),
        ), self.assertRaisesMessage(
            LookupError,
            'injected unclassified configuration failure',
        ):
            self.url()

        self.assertFalse(ConfiguracaoSistema.objects.exists())


class AgendaWhatsAppConfigurationFailureTests(_WhatsAppConfigurationFailureMixin, TestCase):
    def make_subject(self):
        return AgendaContato.objects.create(
            cliente=self.customer,
            tipo='POS_VENDA_30_DIAS',
            data_agendada=django_timezone.localdate(),
        )


class KanbanWhatsAppConfigurationFailureTests(_WhatsAppConfigurationFailureMixin, TestCase):
    def make_subject(self):
        return ProjetoKanban.objects.create(
            cliente=self.customer,
            titulo_servico='Projeto Stage1',
            etapa='1_CONTATO',
        )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        return self.rows[key]

    def order_by(self, *args):
        return self

    def values(self, *args):
        return self

    def values_list(self, *args):
        return self.rows


class Customer360EventIdNarrowingTests(SimpleTestCase):
    @staticmethod
    def event_row(entity_type, entity_id, *, event_id=1):
        return {
            'id': event_id,
            'tipo': 'CONTATO_CONCLUIDO' if entity_type == 'AgendaContato' else 'LANCAMENTO_QUITADO',
            'criado_em': datetime(2026, 10, 29, tzinfo=UTC),
            'entidade_tipo': entity_type,
            'entidade_id': entity_id,
            'metadata': {},
        }

    def test_project_contact_and_ledger_ids_keep_their_associations(self):
        contacts = {7: 13}
        ledger_projects = {21: 13}

        self.assertEqual(
            _event_project_id(self.event_row('ProjetoKanban', '13'), contacts, ledger_projects),
            13,
        )
        self.assertEqual(
            _event_project_id(self.event_row('AgendaContato', '7'), contacts, ledger_projects),
            13,
        )
        self.assertEqual(
            _event_project_id(
                self.event_row('LancamentoFinanceiro', '21'),
                contacts,
                ledger_projects,
            ),
            13,
        )
        self.assertIsNone(
            _event_project_id(self.event_row('AgendaContato', '8'), contacts, ledger_projects),
        )

    def test_nullable_and_malformed_entity_ids_keep_int_exception_contract(self):
        contacts = {7: 13}
        ledger_projects = {21: 13}
        for entity_type in ('ProjetoKanban', 'AgendaContato', 'LancamentoFinanceiro'):
            with self.subTest(entity_type=entity_type):
                with self.assertRaises(TypeError) as caught:
                    _event_project_id(
                        self.event_row(entity_type, None),
                        contacts,
                        ledger_projects,
                    )
                self.assertEqual(str(caught.exception), _NONE_INT_TYPE_ERROR)
                with self.assertRaises(ValueError):
                    _event_project_id(
                        self.event_row(entity_type, 'not-an-integer'),
                        contacts,
                        ledger_projects,
                    )

    def _load_one_event(self, row):
        with (
            patch.object(LancamentoFinanceiro.objects, 'filter', return_value=_Rows([])),
            patch.object(EventoSistema.objects, 'filter', return_value=_Rows([row])),
            patch.object(
                ProjetoKanban.objects,
                'filter',
                return_value=_Rows([(13, 'Projeto vinculado')]),
            ),
        ):
            return _load_events(
                project_ids=(13,),
                contact_project_ids={7: 13},
                history_page=1,
            )

    def test_load_events_keeps_valid_contact_identity_and_skips_unlinked_event(self):
        rows, has_more = self._load_one_event(
            self.event_row('AgendaContato', '7', event_id=42),
        )
        self.assertFalse(has_more)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].evento_id, 42)
        self.assertEqual(rows[0].contato_id, 7)
        self.assertEqual(rows[0].projeto_id, 13)
        self.assertEqual(rows[0].projeto_titulo, 'Projeto vinculado')

        unlinked, has_more = self._load_one_event(
            self.event_row('AgendaContato', '99', event_id=43),
        )
        self.assertFalse(has_more)
        self.assertEqual(unlinked, ())

    def test_load_events_preserves_type_and_value_errors_for_bad_contact_ids(self):
        with self.assertRaises(TypeError) as caught:
            self._load_one_event(self.event_row('AgendaContato', None))
        self.assertEqual(str(caught.exception), _NONE_INT_TYPE_ERROR)

        with self.assertRaises(ValueError):
            self._load_one_event(self.event_row('AgendaContato', 'invalid'))
