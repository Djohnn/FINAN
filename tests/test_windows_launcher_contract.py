import ntpath
import re
from pathlib import Path

from django.test import SimpleTestCase


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = REPOSITORY_ROOT / 'scripts_windows' / 'Iniciar_Sistema_Marcenaria.bat'


class WindowsLauncherContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.launcher = LAUNCHER_PATH.read_text(encoding='utf-8')
        cls.normalized = cls.launcher.lower()

    def test_root_is_the_parent_of_the_launcher_directory(self):
        self.assertRegex(
            self.normalized,
            r'for\s+%%i\s+in\s*\(\s*"%~dp0\.\."\s*\)\s+do\s+set\s+"root=%%~fi"',
        )
        self.assertRegex(self.normalized, r'cd\s+/d\s+"%root%"')
        self.assertNotRegex(self.normalized, r'cd\s+/d\s+"%~dp0"')

    def test_invokes_the_canonical_venv_interpreter(self):
        self.assertRegex(self.normalized, r'"%root%\\venv\\scripts\\python\.exe"')
        self.assertNotIn('.venv', self.normalized)
        self.assertNotRegex(self.normalized, r'(?m)^\s*python(?:\.exe)?\s+manage\.py\b')

    def test_invokes_manage_py_from_the_repository_root(self):
        self.assertRegex(self.normalized, r'"%root%\\manage\.py"')

    def test_paths_are_quoted_for_repository_paths_with_spaces(self):
        sample_root = r'C:\Users\Test User\Documents\Finan PE'
        interpreter = ntpath.normpath(ntpath.join(sample_root, r'venv\Scripts\python.exe'))
        manage_py = ntpath.normpath(ntpath.join(sample_root, 'manage.py'))

        self.assertEqual(
            interpreter,
            r'C:\Users\Test User\Documents\Finan PE\venv\Scripts\python.exe',
        )
        self.assertEqual(
            manage_py,
            r'C:\Users\Test User\Documents\Finan PE\manage.py',
        )
        self.assertRegex(
            self.normalized,
            r'"%root%\\venv\\scripts\\python\.exe"\s+"%root%\\manage\.py"',
        )

    def test_root_resolution_is_independent_of_caller_working_directory(self):
        launcher = ntpath.join(
            r'C:\Users\Test User\Documents\Finan PE',
            'scripts_windows',
            'Iniciar_Sistema_Marcenaria.bat',
        )
        launcher_directory = ntpath.dirname(launcher)
        expected_root = ntpath.normpath(ntpath.join(launcher_directory, '..'))

        for caller_cwd in (
            r'C:\\',
            r'C:\Users\Other User',
            r'C:\Temp\launcher-caller',
        ):
            self.assertEqual(expected_root, r'C:\Users\Test User\Documents\Finan PE')
            self.assertNotEqual(expected_root, ntpath.normpath(caller_cwd))

        self.assertIn('%~dp0', self.normalized)
        self.assertNotIn('%cd%', self.normalized)

    def test_browser_starts_before_runserver(self):
        browser = re.search(r'start\s+""\s+http://127\.0\.0\.1:8000', self.normalized)
        runserver = re.search(r'runserver\s+127\.0\.0\.1:8000\s+--insecure', self.normalized)

        self.assertIsNotNone(browser)
        self.assertIsNotNone(runserver)
        self.assertLess(browser.start(), runserver.start())

    def test_runserver_target_and_insecure_flag_are_preserved(self):
        self.assertRegex(
            self.normalized,
            r'runserver\s+127\.0\.0\.1:8000\s+--insecure',
        )

    def test_launcher_has_no_backup_runtime_coupling(self):
        self.assertNotIn('agendador_backup_pendrive.bat', self.normalized)
