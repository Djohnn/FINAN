from datetime import timedelta
from io import StringIO
from pathlib import Path
import re
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.core_sistema.context_processors import alertas_globais
from apps.core_sistema.models import ConfiguracaoSistema
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
