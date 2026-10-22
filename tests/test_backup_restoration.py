import hashlib
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase

from apps.core_sistema import services
from apps.core_sistema.models import ConfiguracaoSistema, EventoSistema


class RestoreServiceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_dir = tempfile.TemporaryDirectory(
            prefix='restore template ',
            dir=Path.cwd(),
        )
        cls.template = Path(cls.template_dir.name) / 'template.sqlite3'
        connection.ensure_connection()
        with closing(sqlite3.connect(cls.template)) as destination:
            connection.connection.backup(destination)
        cls.addClassCleanup(cls.template_dir.cleanup)

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix='restore test ', dir=Path.cwd())
        self.addCleanup(self.tempdir.cleanup)
        self.folder = Path(self.tempdir.name)
        self.live = self.folder / 'live database.sqlite3'
        self.source = self.folder / 'backup source.sqlite3'
        shutil.copyfile(self.template, self.live)
        shutil.copyfile(self.live, self.source)
        self.close_connections_patch = patch.object(services.connections, 'close_all')
        self.close_connections_patch.start()
        self.addCleanup(self.close_connections_patch.stop)

    def _service(self, source, **kwargs):
        return services.restore_backup(source, live_db_path=self.live, **kwargs)

    def _restore(self, **kwargs):
        return services.restore_backup(
            self.source,
            live_db_path=self.live,
            confirm_restore=True,
            expected_live_db=self.live,
            **kwargs,
        )

    def _digest(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _replace_source(self, callback):
        with closing(sqlite3.connect(self.source)) as database:
            callback(database)
            database.commit()

    def _assert_successful_preflight(self, **kwargs):
        result = self._service(self.source, **kwargs)
        self.assertTrue(result.success, result.message)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.category, services.RESTORE_SUCCESS)
        return result

    def test_valid_exact_state_source_preflight(self):
        result = self._assert_successful_preflight()
        self.assertEqual(result.source_path, str(self.source))
        self.assertEqual(result.live_db_path, str(self.live))

    def test_source_alone_is_non_mutating_preflight(self):
        before = self._digest(self.live)
        result = self._assert_successful_preflight()
        self.assertEqual(before, self._digest(self.live))
        self.assertEqual(list(self.folder.glob('*.backup.lock')), [])
        self.assertIsNone(result.safety_copy_path)

    def test_explicit_dry_run_is_non_mutating(self):
        before = self._digest(self.live)
        result = self._assert_successful_preflight(dry_run=True)
        self.assertEqual(before, self._digest(self.live))
        self.assertEqual(list(self.folder.glob('*.pre-restore-*')), [])
        self.assertEqual(list(self.folder.glob('*.restore-stage-*')), [])
        self.assertIsNone(result.failed_restore_path)

    def test_nonexistent_and_relative_sources_are_rejected(self):
        cases = (
            (self.folder / 'missing.sqlite3', 'INVALID_SOURCE'),
            (Path('relative.sqlite3'), 'INVALID_SOURCE'),
        )
        for candidate, category in cases:
            with self.subTest(candidate=candidate):
                result = self._service(candidate)
                self.assertFalse(result.success)
                self.assertEqual(result.category, category)

    def test_network_unc_source_is_rejected(self):
        result = self._service(r'\\server\share\backup.sqlite3')
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INVALID_SOURCE')

    def test_symlink_or_reparse_source_is_rejected(self):
        with patch.object(services, '_is_symlink_or_reparse', return_value=True):
            result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INVALID_SOURCE')

    def test_non_sqlite_and_corrupt_sqlite_sources_are_rejected(self):
        not_sqlite = self.folder / 'plain text.sqlite3'
        not_sqlite.write_text('not sqlite', encoding='utf-8')
        corrupt = self.folder / 'corrupt.sqlite3'
        corrupt.write_bytes(b'SQLite format 3\x00' + b'broken')
        for candidate, expected in (
            (not_sqlite, 'NOT_SQLITE'),
            (corrupt, 'CORRUPT_SQLITE'),
        ):
            with self.subTest(candidate=candidate):
                result = self._service(candidate)
                self.assertFalse(result.success)
                self.assertEqual(result.category, expected)

    def test_foreign_schema_is_rejected(self):
        candidate = self.folder / 'foreign.sqlite3'
        with closing(sqlite3.connect(candidate)) as database:
            database.execute('CREATE TABLE unrelated (id INTEGER PRIMARY KEY)')
            database.commit()
        result = self._service(candidate)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'NOT_FINANPE_DATABASE')

    def test_source_equal_live_database_is_rejected(self):
        result = self._service(self.live)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'LIVE_DATABASE_AS_SOURCE')

    def test_older_newer_and_missing_migration_sets_are_rejected(self):
        cases = (
            ('older', 'DELETE FROM django_migrations WHERE rowid IN (SELECT rowid FROM django_migrations LIMIT 1)'),
            ('newer', "INSERT INTO django_migrations (app, name, applied) VALUES ('future', '9999_new', CURRENT_TIMESTAMP)"),
            ('missing', 'DROP TABLE django_migrations'),
        )
        for label, statement in cases:
            with self.subTest(label=label):
                shutil.copyfile(self.live, self.source)
                with closing(sqlite3.connect(self.source)) as database:
                    database.execute(statement)
                    database.commit()
                result = self._service(self.source)
                self.assertFalse(result.success)
                self.assertIn(result.category, {'INCOMPATIBLE_SCHEMA', 'NOT_FINANPE_DATABASE'})

    def test_unrelated_extra_table_is_allowed(self):
        self._replace_source(
            lambda database: database.execute('CREATE TABLE operator_note (id INTEGER PRIMARY KEY)'),
        )
        result = self._assert_successful_preflight()
        self.assertTrue(result.success)

    def test_live_and_source_sidecars_are_rejected(self):
        for path, expected in (
            (self.live.with_name(self.live.name + '-wal'), 'live'),
            (self.source.with_name(self.source.name + '-shm'), 'source'),
        ):
            with self.subTest(path=path):
                path.write_bytes(b'sidecar')
                result = self._service(self.source)
                self.assertFalse(result.success)
                self.assertEqual(result.category, 'SERVER_OR_DATABASE_IN_USE')
                path.unlink()

    def test_maintenance_lock_conflict_is_refused(self):
        lock = self.live.with_name(self.live.name + '.backup.lock')
        lock.write_text(
            'pid=123\noperation=RESTORE\ncreated_at=now\nprocess_start_identity=unknown\n',
            encoding='utf-8',
        )
        result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'MAINTENANCE_LOCKED')
        self.assertIn('manual', result.message.lower())

    def test_restore_vs_restore_lock_conflict_is_refused(self):
        with services._maintenance_lock(self.live, 'RESTORE') as acquired:
            self.assertTrue(acquired)
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'MAINTENANCE_LOCKED')

    def test_backup_vs_restore_uses_the_shared_lock(self):
        with services._maintenance_lock(self.live, 'BACKUP') as acquired:
            self.assertTrue(acquired)
            result = self._restore()
            self.assertFalse(result.success)
            self.assertEqual(result.category, 'MAINTENANCE_LOCKED')
        self.assertFalse(self.live.with_name(self.live.name + '.backup.lock').exists())

    def test_forensic_preservation_failure_stops_rollback_and_keeps_rejected_live_db(self):
        self._replace_source(
            lambda database: database.execute(
                'CREATE TABLE rejected_restore_marker (value TEXT)',
            ),
        )
        original_live_digest = self._digest(self.live)
        rejected_live_digest = self._digest(self.source)
        original_validate = services._validate_candidate
        original_replace = services.os.replace
        original_copy = services._copy_file_verified
        replaced = False
        post_failure_pending = True

        def mark_replace(source, destination):
            nonlocal replaced
            if '.restore-stage-' in Path(source).name and Path(destination) == self.live:
                replaced = True
            return original_replace(source, destination)

        def fail_post(path, live, expected, *, reject_live):
            nonlocal post_failure_pending
            if replaced and post_failure_pending and Path(path) == self.live:
                post_failure_pending = False
                return services._validation(False, 'CORRUPT_SQLITE', 'post invalid')
            return original_validate(path, live, expected, reject_live=reject_live)

        def fail_forensic_copy(source, destination):
            if '.failed-restore-' in destination.name:
                raise OSError('forensic preservation failure')
            return original_copy(source, destination)

        with patch.object(services.os, 'replace', side_effect=mark_replace):
            with patch.object(services, '_validate_candidate', side_effect=fail_post):
                with patch.object(
                    services,
                    '_copy_file_verified',
                    side_effect=fail_forensic_copy,
                ):
                    result = self._restore()

        self.assertFalse(result.success)
        self.assertEqual(result.category, 'POST_VALIDATION_FAILED_ROLLBACK_FAILED')
        self.assertFalse(result.rollback_performed)
        self.assertIsNone(result.failed_restore_path)
        self.assertEqual(self._digest(self.live), rejected_live_digest)
        self.assertNotEqual(self._digest(self.live), original_live_digest)
        self.assertTrue(Path(result.safety_copy_path).exists())
        self.assertEqual(self._digest(Path(result.safety_copy_path)), original_live_digest)
        self.assertIn('forense', result.message.lower())
        self.assertIn('rollback', result.message.lower())

    def test_backup_restore_lock_refusal_does_not_read_or_mutate_existing_config(self):
        destination = self.folder / 'backup destination'
        config = ConfiguracaoSistema.get_solo()
        config.caminho_backup_pendrive = str(destination)
        config.ultimo_backup_sucesso = True
        config.mensagem_erro_backup = 'sentinel error'
        config.save(update_fields=[
            'caminho_backup_pendrive', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
        ])
        before = tuple(
            ConfiguracaoSistema.objects.values_list(
                'caminho_backup_pendrive', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
            ).get(pk=1),
        )

        with patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': str(self.live)}},
        ):
            with services._maintenance_lock(self.live, 'RESTORE') as acquired:
                self.assertTrue(acquired)
                with patch.object(
                    services.ConfiguracaoSistema,
                    'get_solo',
                    side_effect=AssertionError('lock refusal must precede ORM access'),
                ) as get_solo:
                    with patch.object(
                        services,
                        '_registrar_falha',
                        side_effect=AssertionError('lock refusal must not persist status'),
                    ) as registrar_falha:
                        result = services.executar_backup_pendrive()

        self.assertFalse(result[0])
        self.assertIn('manutenção', result[1].lower())
        get_solo.assert_not_called()
        registrar_falha.assert_not_called()
        after = tuple(
            ConfiguracaoSistema.objects.values_list(
                'caminho_backup_pendrive', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
            ).get(pk=1),
        )
        self.assertEqual(before, after)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.folder.glob('backup_marcenaria_*.sqlite3')), [])

    def test_backup_restore_lock_refusal_does_not_create_missing_config(self):
        ConfiguracaoSistema.objects.all().delete()
        destination = self.folder / 'backup destination'

        with patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': str(self.live)}},
        ):
            with services._maintenance_lock(self.live, 'RESTORE') as acquired:
                self.assertTrue(acquired)
                with patch.object(
                    services.ConfiguracaoSistema,
                    'get_solo',
                    side_effect=AssertionError('lock refusal must precede singleton creation'),
                ) as get_solo:
                    result = services.executar_backup_pendrive()

        self.assertFalse(result[0])
        self.assertIn('manutenção', result[1].lower())
        get_solo.assert_not_called()
        self.assertFalse(ConfiguracaoSistema.objects.exists())
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.folder.glob('backup_marcenaria_*.sqlite3')), [])

    def test_backup_failure_after_lock_acquisition_still_records_failure_status(self):
        destination = self.folder / 'backup destination'
        config = ConfiguracaoSistema.get_solo()
        config.caminho_backup_pendrive = str(destination)
        config.ultimo_backup_sucesso = True
        config.mensagem_erro_backup = ''
        config.save(update_fields=[
            'caminho_backup_pendrive', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
        ])

        with patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': str(self.live)}},
        ):
            with patch.object(
                services.sqlite3,
                'connect',
                side_effect=OSError('simulated backup failure'),
            ):
                result = services.executar_backup_pendrive()

        self.assertFalse(result[0])
        self.assertIn('simulated backup failure', result[1])
        persisted = ConfiguracaoSistema.objects.get(pk=1)
        self.assertFalse(persisted.ultimo_backup_sucesso)
        self.assertIn('simulated backup failure', persisted.mensagem_erro_backup)
        self.assertFalse(self.live.with_name(self.live.name + '.backup.lock').exists())

    def test_stale_or_uncertain_lock_is_not_removed_automatically(self):
        lock = self.live.with_name(self.live.name + '.backup.lock')
        lock.write_text('pid=999999\noperation=BACKUP\nprocess_start_identity=unavailable', encoding='utf-8')
        result = self._restore()
        self.assertEqual(result.category, 'MAINTENANCE_LOCKED')
        self.assertTrue(lock.exists())

    def test_safety_copy_is_created_and_retained(self):
        result = self._restore()
        self.assertTrue(result.success, result.message)
        safety = Path(result.safety_copy_path)
        self.assertTrue(safety.exists())
        self.assertNotEqual(safety, self.live)
        self.assertEqual(self._digest(safety), self._digest(self.live))

    def test_safety_copy_validation_failure_blocks_staging(self):
        with patch.object(services, '_validated_copy', side_effect=OSError('safety failure')):
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'SAFETY_COPY_FAILED')
        self.assertEqual(list(self.folder.glob('*.restore-stage-*')), [])

    def test_stage_copy_failure_preserves_live_and_safety_copy(self):
        original = services._copy_file_verified

        def fail_stage(source, destination):
            if '.restore-stage-' in destination.name:
                raise OSError('stage failure')
            return original(source, destination)

        before = self._digest(self.live)
        with patch.object(services, '_copy_file_verified', side_effect=fail_stage):
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'STAGING_FAILED')
        self.assertEqual(before, self._digest(self.live))
        self.assertTrue(Path(result.safety_copy_path).exists())

    def test_staged_validation_failure_preserves_live(self):
        original = services._validate_candidate

        def fail_stage(path, live, expected, *, reject_live):
            if '.restore-stage-' in path.name:
                return services._validation(False, 'CORRUPT_SQLITE', 'stage invalid')
            return original(path, live, expected, reject_live=reject_live)

        before = self._digest(self.live)
        with patch.object(services, '_validate_candidate', side_effect=fail_stage):
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'STAGING_FAILED')
        self.assertEqual(before, self._digest(self.live))

    def test_os_replace_failure_keeps_live_authoritative(self):
        original_replace = services.os.replace

        def fail_stage_replace(source, destination):
            if '.restore-stage-' in Path(source).name and Path(destination) == self.live:
                raise OSError('replace failure')
            return original_replace(source, destination)

        before = self._digest(self.live)
        with patch.object(services.os, 'replace', side_effect=fail_stage_replace):
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'REPLACEMENT_FAILED')
        self.assertEqual(before, self._digest(self.live))
        self.assertTrue(Path(result.staging_path).exists())

    def test_successful_restore_replaces_live_atomically(self):
        self._replace_source(
            lambda database: database.execute('CREATE TABLE restored_marker (value TEXT)'),
        )
        result = self._restore()
        self.assertTrue(result.success, result.message)
        with closing(sqlite3.connect(self.live)) as database:
            self.assertIsNotNone(database.execute(
                "SELECT name FROM sqlite_master WHERE name = 'restored_marker'",
            ).fetchone())

    def test_source_is_unchanged_after_success(self):
        before = self._digest(self.source)
        result = self._restore()
        self.assertTrue(result.success, result.message)
        self.assertEqual(before, self._digest(self.source))

    def test_source_is_unchanged_after_failure(self):
        before = self._digest(self.source)
        with patch.object(services, '_validated_copy', side_effect=OSError('copy failure')):
            result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(before, self._digest(self.source))

    def test_post_validation_failure_rolls_back_and_preserves_forensics(self):
        original_validate = services._validate_candidate
        replaced = False
        post_failure_pending = True

        def mark_replace(source, destination):
            nonlocal replaced
            if '.restore-stage-' in Path(source).name and Path(destination) == self.live:
                replaced = True
            return original_replace(source, destination)

        original_replace = services.os.replace

        def fail_post(path, live, expected, *, reject_live):
            nonlocal post_failure_pending
            if replaced and post_failure_pending and Path(path) == self.live:
                post_failure_pending = False
                return services._validation(False, 'CORRUPT_SQLITE', 'post invalid')
            return original_validate(path, live, expected, reject_live=reject_live)

        with patch.object(services.os, 'replace', side_effect=mark_replace):
            with patch.object(services, '_validate_candidate', side_effect=fail_post):
                result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'POST_VALIDATION_FAILED_ROLLBACK_OK')
        self.assertTrue(result.rollback_performed)
        self.assertTrue(result.rollback_success)
        self.assertTrue(Path(result.safety_copy_path).exists())
        self.assertTrue(Path(result.failed_restore_path).exists())

    def test_post_validation_failure_with_rollback_failure_preserves_artifacts(self):
        original_validate = services._validate_candidate
        original_replace = services.os.replace
        replaced = False

        def fail_post(path, live, expected, *, reject_live):
            if replaced and Path(path) == self.live:
                return services._validation(False, 'CORRUPT_SQLITE', 'post invalid')
            return original_validate(path, live, expected, reject_live=reject_live)

        def fail_rollback(source, destination):
            nonlocal replaced
            if '.restore-stage-' in Path(source).name and Path(destination) == self.live:
                replaced = True
                return original_replace(source, destination)
            if '.rollback-stage-' in Path(source).name and Path(destination) == self.live:
                raise OSError('rollback replace failure')
            return original_replace(source, destination)

        with patch.object(services.os, 'replace', side_effect=fail_rollback):
            with patch.object(services, '_validate_candidate', side_effect=fail_post):
                result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'POST_VALIDATION_FAILED_ROLLBACK_FAILED')
        self.assertFalse(result.rollback_success)
        self.assertTrue(Path(result.safety_copy_path).exists())
        self.assertTrue(Path(result.failed_restore_path).exists())
        self.assertTrue(Path(result.staging_path).exists())

    def test_repeated_restore_creates_a_new_safety_copy(self):
        first = self._restore()
        second = self._restore()
        self.assertTrue(first.success, first.message)
        self.assertTrue(second.success, second.message)
        self.assertNotEqual(first.safety_copy_path, second.safety_copy_path)
        self.assertEqual(len(list(self.folder.glob('*.pre-restore-*.sqlite3'))), 2)

    def test_confirmation_requires_expected_live_database(self):
        result = self._service(self.source, confirm_restore=True)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INVALID_CONFIRMATION')

    def test_expected_live_database_mismatch_is_rejected(self):
        result = self._service(
            self.source,
            confirm_restore=True,
            expected_live_db=self.folder / 'other.sqlite3',
        )
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INVALID_CONFIRMATION')

    def test_dry_run_and_confirmation_cannot_be_combined(self):
        result = self._service(
            self.source,
            confirm_restore=True,
            expected_live_db=self.live,
            dry_run=True,
        )
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INVALID_CONFIRMATION')

    def test_backup_configuration_status_is_not_reused_or_mutated(self):
        config = ConfiguracaoSistema.get_solo()
        config.ultimo_backup_sucesso = True
        config.mensagem_erro_backup = 'preserve'
        config.save(update_fields=['ultimo_backup_sucesso', 'mensagem_erro_backup'])
        before = tuple(
            ConfiguracaoSistema.objects.values_list(
                'ultimo_backup_em', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
            ).get(pk=1),
        )
        result = self._restore()
        self.assertTrue(result.success, result.message)
        after = tuple(
            ConfiguracaoSistema.objects.values_list(
                'ultimo_backup_em', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
            ).get(pk=1),
        )
        self.assertEqual(before, after)

    def test_paths_with_spaces_are_supported(self):
        result = self._restore()
        self.assertTrue(result.success, result.message)
        self.assertIn(' ', result.live_db_path)
        self.assertIn(' ', result.source_path)

    def test_new_schema_requires_event_history_table(self):
        self._replace_source(
            lambda database: database.execute('DROP TABLE core_sistema_eventosistema'),
        )
        result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'NOT_FINANPE_DATABASE')

    def test_valid_pre_history_schema_is_incompatible_with_current_executable(self):
        def make_pre_history(database):
            database.execute('DROP TABLE core_sistema_eventosistema')
            database.execute(
                "DELETE FROM django_migrations "
                "WHERE app = 'core_sistema' AND name = '0002_eventosistema'",
            )

        self._replace_source(make_pre_history)
        result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'INCOMPATIBLE_SCHEMA')

    def test_current_migrations_with_event_table_missing_are_not_finanpe(self):
        self._replace_source(
            lambda database: database.execute('DROP TABLE core_sistema_eventosistema'),
        )
        result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'NOT_FINANPE_DATABASE')

    def test_current_migrations_with_event_column_missing_are_not_finanpe(self):
        def remove_event_metadata(database):
            database.execute('DROP TABLE core_sistema_eventosistema')
            database.execute(
                '''
                CREATE TABLE core_sistema_eventosistema (
                    id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                    tipo varchar(50) NOT NULL,
                    dominio varchar(15) NOT NULL,
                    entidade_tipo varchar(60),
                    entidade_id varchar(64),
                    descricao varchar(255) NOT NULL,
                    criado_em datetime NOT NULL
                )
                ''',
            )

        self._replace_source(remove_event_metadata)
        result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'NOT_FINANPE_DATABASE')

    def test_missing_legacy_finanpe_table_is_not_finanpe(self):
        self._replace_source(
            lambda database: database.execute('DROP TABLE clientes_agenda_cliente'),
        )
        result = self._service(self.source)
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'NOT_FINANPE_DATABASE')

    def test_current_schema_with_event_history_is_eligible(self):
        result = self._service(self.source)
        self.assertTrue(result.success, result.message)
        self.assertTrue(result.dry_run)

    def test_restore_dry_run_does_not_create_history_event(self):
        result = self._service(self.source, dry_run=True)
        self.assertTrue(result.success, result.message)
        self.assertEqual(EventoSistema.objects.count(), 0)

    def test_successful_restore_records_history(self):
        result = self._restore()
        self.assertTrue(result.success, result.message)
        self.assertEqual(
            EventoSistema.objects.filter(tipo='RESTAURACAO_CONCLUIDA').count(),
            1,
        )

    def test_restore_history_failure_does_not_rollback_valid_restore(self):
        before = self._digest(self.live)
        with patch.object(
            services,
            'registrar_evento',
            side_effect=RuntimeError('history failure'),
        ):
            result = self._restore()
        self.assertTrue(result.success, result.message)
        self.assertFalse(result.rollback_performed)
        self.assertIn(
            'Aviso: a restauração foi concluída e validada, mas o histórico operacional não pôde ser registrado.',
            result.message,
        )
        self.assertEqual(self._digest(self.live), before)

    def _force_post_validation_failure(self):
        original_validate = services._validate_candidate
        original_replace = services.os.replace
        replaced = False
        post_failure_pending = True

        def mark_replace(source, destination):
            nonlocal replaced
            if '.restore-stage-' in Path(source).name and Path(destination) == self.live:
                replaced = True
            return original_replace(source, destination)

        def fail_post(path, live, expected, *, reject_live):
            nonlocal post_failure_pending
            if replaced and post_failure_pending and Path(path) == self.live:
                post_failure_pending = False
                return services._validation(False, 'CORRUPT_SQLITE', 'post invalid')
            return original_validate(path, live, expected, reject_live=reject_live)

        return mark_replace, fail_post

    def test_rollback_ok_records_failure_history(self):
        mark_replace, fail_post = self._force_post_validation_failure()
        with patch.object(services.os, 'replace', side_effect=mark_replace):
            with patch.object(services, '_validate_candidate', side_effect=fail_post):
                result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'POST_VALIDATION_FAILED_ROLLBACK_OK')
        self.assertEqual(
            EventoSistema.objects.filter(
                tipo='RESTAURACAO_FALHOU_ROLLBACK_OK',
            ).count(),
            1,
        )

    def test_rollback_ok_history_failure_preserves_rollback_and_warns(self):
        mark_replace, fail_post = self._force_post_validation_failure()
        with patch.object(
            services,
            'registrar_evento',
            side_effect=RuntimeError('history failure'),
        ):
            with patch.object(services.os, 'replace', side_effect=mark_replace):
                with patch.object(services, '_validate_candidate', side_effect=fail_post):
                    result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'POST_VALIDATION_FAILED_ROLLBACK_OK')
        self.assertTrue(result.rollback_success)
        self.assertIn(
            'Aviso: o rollback foi concluído e validado, mas o histórico operacional não pôde ser registrado.',
            result.message,
        )

    def test_lock_refusal_does_not_write_restore_history(self):
        with services._maintenance_lock(self.live, 'RESTORE') as acquired:
            self.assertTrue(acquired)
            with patch.object(services, 'registrar_evento') as registrar:
                result = self._restore()
        self.assertFalse(result.success)
        self.assertEqual(result.category, 'MAINTENANCE_LOCKED')
        registrar.assert_not_called()


class RestoreCommandAndScriptTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template_dir = tempfile.TemporaryDirectory(
            prefix='command template ',
            dir=Path.cwd(),
        )
        cls.template = Path(cls.template_dir.name) / 'template.sqlite3'
        connection.ensure_connection()
        with closing(sqlite3.connect(cls.template)) as destination:
            connection.connection.backup(destination)
        cls.addClassCleanup(cls.template_dir.cleanup)

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix='command restore ', dir=Path.cwd())
        self.addCleanup(self.tempdir.cleanup)
        self.folder = Path(self.tempdir.name)
        self.live = self.folder / 'command live.sqlite3'
        self.source = self.folder / 'command source.sqlite3'
        shutil.copyfile(self.template, self.live)
        shutil.copyfile(self.live, self.source)
        self.database_patch = patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': str(self.live)}},
        )
        self.database_patch.start()
        self.addCleanup(connection.close)
        self.addCleanup(self.database_patch.stop)
        self.close_connections_patch = patch.object(services.connections, 'close_all')
        self.close_connections_patch.start()
        self.addCleanup(self.close_connections_patch.stop)

    def test_command_failure_becomes_command_error(self):
        with self.assertRaises(CommandError):
            call_command('restaurar_backup', '--source', str(self.folder / 'missing.sqlite3'))

    def test_command_requires_expected_live_db_for_confirmation(self):
        with self.assertRaises(CommandError):
            call_command(
                'restaurar_backup',
                '--source', str(self.source),
                '--confirm-restore',
            )

    def test_command_rejects_dry_run_confirmation_combination(self):
        with self.assertRaises(CommandError):
            call_command(
                'restaurar_backup',
                '--source', str(self.source),
                '--dry-run',
                '--confirm-restore',
                '--expected-live-db', str(self.live),
            )


class RestorePowerShellContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = Path('scripts_windows/Restaurar_Backup_Guiado.ps1').read_text(encoding='utf-8')
        cls.normalized = cls.script.lower().replace('/', '\\')

    def test_powershell_uses_root_venv_and_manage(self):
        self.assertIn('$psscriptroot', self.normalized)
        self.assertIn('venv\\scripts\\python.exe', self.normalized)
        self.assertIn("join-path $repositoryroot 'manage.py'", self.normalized)
        self.assertIn('db.sqlite3', self.normalized)

    def test_powershell_runs_dry_run_before_destructive_command(self):
        dry_run = self.normalized.index('--dry-run')
        destructive = self.normalized.index('--confirm-restore')
        self.assertLess(dry_run, destructive)
        self.assertIn('if ($lastexitcode -ne 0)', self.normalized)

    def test_powershell_requires_literal_confirmation(self):
        self.assertIn("'restaurar finanpe'", self.normalized)
        self.assertIn("-cne 'restaurar finanpe'", self.normalized)

    def test_powershell_is_secret_safe_and_has_no_automatic_restore(self):
        self.assertNotIn('setenvironmentvariable', self.normalized)
        self.assertNotIn('latest', self.normalized)
        self.assertNotIn('scheduledtask', self.normalized)
        self.assertNotIn('on boot', self.normalized)
        self.assertNotRegex(self.normalized, r'django_secret_key\s*=\s*[\'\"]')
        self.assertIn("getenvironmentvariable('django_secret_key', 'user')", self.normalized)
        self.assertIn("getenvironmentvariable('django_secret_key', 'machine')", self.normalized)

    def test_powershell_detects_runserver_without_killing_it(self):
        self.assertIn('get-ciminstance win32_process', self.normalized)
        self.assertIn('manage\\.py.*runserver', self.normalized)
        self.assertNotIn('stop-process', self.normalized)

    def test_powershell_quotes_paths_by_argument_values(self):
        self.assertIn('& $python $manage restaurar_backup --source $source --dry-run', self.normalized)
        self.assertIn('--expected-live-db $livedatabase', self.normalized)
