from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from apps.core_sistema.models import ConfiguracaoSistema
from apps.core_sistema.services import executar_backup_pendrive
from apps.core_sistema.services import backup_realizado_hoje


class Command(BaseCommand):
    help = "Executa o backup do banco de dados SQLite oficial no pendrive configurado."

    def add_arguments(self, parser):
        parser.add_argument(
            '--if-due',
            action='store_true',
            help='Executa somente se ainda não houver sucesso de backup hoje.',
        )

    def handle(self, *args, **options):
        if options['if_due']:
            config = ConfiguracaoSistema.objects.filter(pk=1).first()
            if backup_realizado_hoje(config):
                self.stdout.write('Backup de hoje já está realizado.')
                return

        self.stdout.write("Iniciando rotina de backup no pendrive...")
        sucesso, mensagem = executar_backup_pendrive()
        if sucesso:
            self.stdout.write(self.style.SUCCESS(f"[OK] {mensagem}"))
        else:
            self.stderr.write(self.style.ERROR(f"[ERRO] {mensagem}"))
            raise CommandError(mensagem)
