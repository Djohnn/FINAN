from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from apps.core_sistema.services import executar_backup_pendrive


class Command(BaseCommand):
    help = "Executa o backup do banco de dados SQLite oficial no pendrive configurado."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando rotina de backup no pendrive...")
        sucesso, mensagem = executar_backup_pendrive()
        if sucesso:
            self.stdout.write(self.style.SUCCESS(f"[OK] {mensagem}"))
        else:
            self.stderr.write(self.style.ERROR(f"[ERRO] {mensagem}"))
            raise CommandError(mensagem)
