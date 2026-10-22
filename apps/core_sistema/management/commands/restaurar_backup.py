from django.core.management.base import BaseCommand, CommandError

from apps.core_sistema.services import restore_backup


class Command(BaseCommand):
    help = 'Valida ou restaura um backup SQLite local do FinanPE.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            required=True,
            help='Caminho absoluto do arquivo SQLite local a ser validado/restaurado.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Executa somente a pré-validação, sem criar lock ou arquivos.',
        )
        parser.add_argument(
            '--confirm-restore',
            action='store_true',
            help='Autoriza a substituição destrutiva após a pré-validação.',
        )
        parser.add_argument(
            '--expected-live-db',
            help='Caminho absoluto esperado do banco SQLite ativo.',
        )

    def handle(self, *args, **options):
        result = restore_backup(
            options['source'],
            confirm_restore=options['confirm_restore'],
            expected_live_db=options['expected_live_db'],
            dry_run=options['dry_run'],
        )
        if not result.success:
            raise CommandError(f'[{result.category}] {result.message}')

        if result.dry_run:
            self.stdout.write(self.style.SUCCESS(f'[OK] {result.message}'))
            self.stdout.write(f'Origem validada: {result.source_path}')
            self.stdout.write(f'Banco ativo: {result.live_db_path}')
            return

        self.stdout.write(self.style.SUCCESS(f'[OK] {result.message}'))
        if result.safety_copy_path:
            self.stdout.write(f'Cópia de segurança preservada: {result.safety_copy_path}')
