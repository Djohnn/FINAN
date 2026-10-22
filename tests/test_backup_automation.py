from datetime import timedelta
from contextlib import closing
from io import StringIO
from pathlib import Path
import re
import sqlite3
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.core_sistema.context_processors import alertas_globais
from apps.core_sistema.models import ConfiguracaoSistema, EventoSistema
from apps.core_sistema import services


def backup_realizado_hoje(config):
    helper = getattr(services, 'backup_realizado_hoje', None)
    if helper is None:
        raise AssertionError('backup_realizado_hoje helper is not implemented')
    return helper(config)


def call_if_due(**kwargs):
    try:
        return call_command('realizar_backup', '--if-due', **kwargs)
    except CommandError as exc:
        raise AssertionError(str(exc)) from exc


class BackupAutomationTests(TestCase):
    def test_backup_successful_today_is_true(self):
        config = ConfiguracaoSistema(
            ultimo_backup_sucesso=True,
            ultimo_backup_em=timezone.now(),
        )

        self.assertTrue(backup_realizado_hoje(config))

    def test_backup_successful_yesterday_is_false(self):
        config = ConfiguracaoSistema(
            ultimo_backup_sucesso=True,
            ultimo_backup_em=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(backup_realizado_hoje(config))

    def test_unsuccessful_backup_is_false(self):
        config = ConfiguracaoSistema(
            ultimo_backup_sucesso=False,
            ultimo_backup_em=timezone.now(),
        )

        self.assertFalse(backup_realizado_hoje(config))

    def test_missing_config_or_timestamp_is_false(self):
        config = ConfiguracaoSistema(
            ultimo_backup_sucesso=True,
            ultimo_backup_em=None,
        )

        self.assertFalse(backup_realizado_hoje(None))
        self.assertFalse(backup_realizado_hoje(config))

    def test_if_due_skips_backup_when_today_is_successful(self):
        config = ConfiguracaoSistema.get_solo()
        config.ultimo_backup_sucesso = True
        config.ultimo_backup_em = timezone.now()
        config.save(update_fields=['ultimo_backup_sucesso', 'ultimo_backup_em'])

        stdout = StringIO()
        with patch(
            'apps.core_sistema.management.commands.realizar_backup.executar_backup_pendrive',
        ) as backup:
            call_if_due(stdout=stdout)

        backup.assert_not_called()
        self.assertIn('backup de hoje já está realizado', stdout.getvalue().lower())

    def test_if_due_executes_one_backup_when_today_is_pending(self):
        config = ConfiguracaoSistema.get_solo()
        config.ultimo_backup_sucesso = True
        config.ultimo_backup_em = timezone.now() - timedelta(days=1)
        config.save(update_fields=['ultimo_backup_sucesso', 'ultimo_backup_em'])

        with patch(
            'apps.core_sistema.management.commands.realizar_backup.executar_backup_pendrive',
            return_value=(True, 'backup concluído'),
        ) as backup:
            call_if_due(stdout=StringIO())

        backup.assert_called_once_with()

    def test_if_due_raises_command_error_when_backup_fails(self):
        with patch(
            'apps.core_sistema.management.commands.realizar_backup.executar_backup_pendrive',
            return_value=(False, 'pendrive ausente'),
        ):
            with self.assertRaisesRegex(CommandError, 'pendrive ausente'):
                call_command('realizar_backup', '--if-due', stdout=StringIO())

    def test_context_processor_marks_old_success_as_pending(self):
        config = ConfiguracaoSistema.get_solo()
        config.ultimo_backup_sucesso = True
        config.ultimo_backup_em = timezone.now() - timedelta(days=1)
        config.mensagem_erro_backup = ''
        config.save(update_fields=[
            'ultimo_backup_sucesso', 'ultimo_backup_em', 'mensagem_erro_backup',
        ])

        contexto = alertas_globais(None)

        self.assertTrue(contexto['backup_alerta'])
        self.assertEqual(contexto['backup_status'], 'pendente_hoje')

    def test_context_processor_marks_today_success_as_ok(self):
        config = ConfiguracaoSistema.get_solo()
        config.ultimo_backup_sucesso = True
        config.ultimo_backup_em = timezone.now()
        config.mensagem_erro_backup = ''
        config.save(update_fields=[
            'ultimo_backup_sucesso', 'ultimo_backup_em', 'mensagem_erro_backup',
        ])

        contexto = alertas_globais(None)

        self.assertFalse(contexto['backup_alerta'])
        self.assertEqual(contexto['backup_status'], 'ok')

    def test_windows_launcher_uses_root_venv_manage_and_if_due(self):
        launcher = Path('scripts_windows/Agendador_Backup_Pendrive.bat').read_text(
            encoding='utf-8',
        )
        normalized = launcher.lower().replace('/', '\\')

        self.assertIn('%~dp0..', normalized)
        self.assertIn(r'venv\scripts\python.exe', normalized)
        self.assertIn(r'\manage.py" realizar_backup --if-due', normalized)
        self.assertIn(r'exit \b %errorlevel%', normalized)
        self.assertNotIn('.venv', normalized)
        self.assertNotIn('django_secret_key', normalized)

    def test_task_installer_is_hourly_idempotent_and_secret_safe(self):
        installer_path = Path('scripts_windows/Instalar_Backup_Automatico.ps1')
        self.assertTrue(installer_path.exists())
        installer = installer_path.read_text(encoding='utf-8')
        normalized = installer.lower().replace('/', '\\')

        self.assertIn('finanpe_backup_automatico', normalized)
        self.assertIn('new-scheduledtasktrigger', normalized)
        self.assertIn('-repetitioninterval (new-timespan -hours 1)', normalized)
        self.assertIn('getenvironmentvariable', normalized)
        self.assertIn("'user'", normalized)
        self.assertIn("'machine'", normalized)
        self.assertIn('register-scheduledtask', normalized)
        self.assertIn('-force', normalized)
        self.assertIn('agendador_backup_pendrive.bat', normalized)
        self.assertNotIn('django_secret_key =', normalized)
        self.assertNotIn('setenvironmentvariable', normalized)
        self.assertNotIn('test-only-backup-automation-016', normalized)

    def test_task_installer_uses_supported_interactive_logon_type(self):
        installer = Path(
            'scripts_windows/Instalar_Backup_Automatico.ps1',
        ).read_text(encoding='utf-8')
        logon_types = re.findall(r'-LogonType\s+([A-Za-z]+)', installer)

        self.assertEqual(logon_types, ['Interactive'])
        self.assertNotIn('-LogonType InteractiveToken', installer)


class ImportantHistoryBackupTests(TestCase):
    def _write_source(self, folder):
        source = folder / 'live.sqlite3'
        with closing(sqlite3.connect(source)) as database:
            database.execute('CREATE TABLE marker (id INTEGER PRIMARY KEY)')
            database.commit()
        return source

    def _configure(self, source, destination):
        config = ConfiguracaoSistema.get_solo()
        config.caminho_backup_pendrive = str(destination)
        config.ultimo_backup_sucesso = False
        config.mensagem_erro_backup = ''
        config.save(update_fields=[
            'caminho_backup_pendrive',
            'ultimo_backup_sucesso',
            'mensagem_erro_backup',
        ])
        return patch.object(
            services.settings,
            'DATABASES',
            {'default': {'NAME': str(source)}},
        )

    def test_missing_source_is_rejected_before_lock_orm_and_event(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = folder / 'missing.sqlite3'
            destination = folder / 'destination'
            with self._configure(source, destination):
                with patch.object(services, '_maintenance_lock') as lock:
                    with patch.object(services.ConfiguracaoSistema, 'get_solo') as get_solo:
                        with patch.object(services, 'registrar_evento') as registrar:
                            result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            lock.assert_not_called()
            get_solo.assert_not_called()
            registrar.assert_not_called()
            self.assertFalse(source.exists())
            self.assertFalse(destination.exists())

    def test_source_missing_under_lock_recheck_has_zero_orm_and_event(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            destination = folder / 'destination'
            with self._configure(source, destination):
                with patch.object(
                    services,
                    '_is_regular_source_file',
                    side_effect=[True, False],
                ):
                    with patch.object(services.ConfiguracaoSistema, 'get_solo') as get_solo:
                        with patch.object(services, 'registrar_evento') as registrar:
                            result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            get_solo.assert_not_called()
            registrar.assert_not_called()
            self.assertFalse(destination.exists())

    def test_read_only_source_open_does_not_recreate_vanished_file(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            source = Path(raw_folder) / 'vanished.sqlite3'
            source.touch()
            source.unlink()
            with self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(services._sqlite_read_only_uri(source), uri=True)
            self.assertFalse(source.exists())

    def test_successful_backup_records_history_while_lock_is_held(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            destination = folder / 'destination'
            with self._configure(source, destination):
                lock_path = source.with_name(source.name + '.backup.lock')
                original_registrar = services.registrar_evento

                def record_event_while_locked(**kwargs):
                    self.assertTrue(lock_path.exists())
                    return original_registrar(**kwargs)

                with patch.object(
                    services,
                    'registrar_evento',
                    side_effect=record_event_while_locked,
                ) as registrar:
                    result = services.executar_backup_pendrive()
            self.assertTrue(result[0], result[1])
            registrar.assert_called_once_with(
                tipo='BACKUP_CONCLUIDO',
                dominio='BACKUP',
            )
            backup = destination / f"backup_marcenaria_{timezone.localdate():%Y-%m-%d}.sqlite3"
            self.assertTrue(backup.exists())
            self.assertFalse(lock_path.exists())
            self.assertEqual(EventoSistema.objects.filter(tipo='BACKUP_CONCLUIDO').count(), 1)

    def test_destination_not_configured_records_stable_failure_event(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            with self._configure(source, folder / 'unused'):
                config = ConfiguracaoSistema.get_solo()
                config.caminho_backup_pendrive = ''
                config.save(update_fields=['caminho_backup_pendrive'])
                result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            evento = EventoSistema.objects.get(tipo='BACKUP_FALHOU')
            self.assertEqual(evento.metadata, {'categoria': 'DESTINO_NAO_CONFIGURADO'})

    def test_inaccessible_destination_records_failure_event(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            destination = folder / 'destination-file'
            destination.write_text('not a directory', encoding='utf-8')
            with self._configure(source, destination):
                result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            evento = EventoSistema.objects.get(tipo='BACKUP_FALHOU')
            self.assertEqual(evento.metadata, {'categoria': 'DESTINO_INACESSIVEL'})

    def test_sqlite_failure_records_failure_event(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            with self._configure(source, folder / 'destination'):
                with patch.object(
                    services.sqlite3,
                    'connect',
                    side_effect=sqlite3.DatabaseError('simulated'),
                ):
                    result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            evento = EventoSistema.objects.get(tipo='BACKUP_FALHOU')
            self.assertEqual(evento.metadata, {'categoria': 'ERRO_SQLITE_BACKUP'})

    def test_success_history_failure_keeps_backup_and_status(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            destination = folder / 'destination'
            with self._configure(source, destination):
                with patch.object(
                    services,
                    'registrar_evento',
                    side_effect=RuntimeError('history failure'),
                ):
                    result = services.executar_backup_pendrive()
            self.assertTrue(result[0])
            self.assertIn(
                'Aviso: o backup foi concluído, mas o histórico operacional não pôde ser registrado.',
                result[1],
            )
            config = ConfiguracaoSistema.objects.get(pk=1)
            self.assertTrue(config.ultimo_backup_sucesso)
            self.assertTrue(list(destination.glob('backup_marcenaria_*.sqlite3')))

    def test_failure_history_failure_keeps_failure_status_and_warning(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw_folder:
            folder = Path(raw_folder)
            source = self._write_source(folder)
            destination = folder / 'destination-file'
            destination.write_text('not a directory', encoding='utf-8')
            with self._configure(source, destination):
                with patch.object(
                    services,
                    'registrar_evento',
                    side_effect=RuntimeError('history failure'),
                ):
                    result = services.executar_backup_pendrive()
            self.assertFalse(result[0])
            self.assertIn(
                'Aviso: a falha do backup foi registrada, mas o histórico operacional não pôde ser registrado.',
                result[1],
            )
            self.assertFalse(ConfiguracaoSistema.objects.get(pk=1).ultimo_backup_sucesso)
