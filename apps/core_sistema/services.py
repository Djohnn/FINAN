import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ConfiguracaoSistema


@contextmanager
def _backup_lock(source_path: Path):
    """Lock de processo cruzado sem dependência externa, inclusive no Windows."""
    lock_path = source_path.with_name(f'{source_path.name}.backup.lock')
    handle = None
    try:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            yield False
            return
        os.write(handle, str(os.getpid()).encode('ascii', errors='ignore'))
        yield True
    finally:
        if handle is not None:
            os.close(handle)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass


def _registrar_falha(config, mensagem: str) -> tuple[bool, str]:
    with transaction.atomic():
        config.ultimo_backup_sucesso = False
        config.mensagem_erro_backup = mensagem[:255]
        config.save(update_fields=['ultimo_backup_sucesso', 'mensagem_erro_backup'])
    return False, mensagem


def executar_backup_pendrive() -> tuple[bool, str]:
    """Cria um backup SQLite íntegro e aplica retenção só aos seus arquivos."""
    config = ConfiguracaoSistema.get_solo()
    pasta_destino = (config.caminho_backup_pendrive or '').strip()
    if not pasta_destino:
        return _registrar_falha(config, 'Destino de backup não configurado.')

    source_name = settings.DATABASES.get('default', {}).get('NAME')
    if not source_name:
        return _registrar_falha(config, 'Arquivo SQLite de origem não configurado.')
    source_path = Path(source_name)
    if not source_path.exists():
        return _registrar_falha(config, f'Arquivo SQLite de origem não encontrado: {source_path}')

    destination = Path(pasta_destino)
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _registrar_falha(config, f'Não foi possível acessar o destino de backup: {exc}')

    with _backup_lock(source_path) as acquired:
        if not acquired:
            return _registrar_falha(config, 'Backup já está em execução por outro processo.')

        date_text = timezone.localdate().strftime('%Y-%m-%d')
        final_path = destination / f'backup_marcenaria_{date_text}.sqlite3'
        temp_path = destination / f'.{final_path.name}.{uuid.uuid4().hex}.tmp'
        source_conn = destination_conn = None
        try:
            source_conn = sqlite3.connect(str(source_path))
            destination_conn = sqlite3.connect(str(temp_path))
            with destination_conn:
                source_conn.backup(destination_conn)
                integrity = destination_conn.execute('PRAGMA integrity_check').fetchone()
            if not integrity or integrity[0] != 'ok':
                raise sqlite3.DatabaseError('integrity_check do backup não retornou ok')
            destination_conn.close()
            source_conn.close()
            destination_conn = source_conn = None
            os.replace(temp_path, final_path)
        except Exception as exc:
            if destination_conn is not None:
                destination_conn.close()
            if source_conn is not None:
                source_conn.close()
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            return _registrar_falha(config, f'Erro ao realizar backup do SQLite: {exc}')

    limite_data = timezone.localdate() - timedelta(days=config.dias_retencao_backup or 30)
    backup_pattern = re.compile(r'^backup_marcenaria_(\d{4}-\d{2}-\d{2})\.sqlite3$')
    try:
        for item in destination.iterdir():
            match = backup_pattern.fullmatch(item.name)
            if not match or not item.is_file():
                continue
            try:
                data_arquivo = datetime.strptime(match.group(1), '%Y-%m-%d').date()
            except ValueError:
                continue
            if data_arquivo < limite_data:
                item.unlink()
    except OSError:
        pass

    with transaction.atomic():
        config.ultimo_backup_em = timezone.now()
        config.ultimo_backup_sucesso = True
        config.mensagem_erro_backup = ''
        config.save(update_fields=[
            'ultimo_backup_em', 'ultimo_backup_sucesso', 'mensagem_erro_backup',
        ])
    return True, f"Backup realizado com sucesso em '{final_path}'!"
