import ntpath
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from .models import (
    ConfiguracaoSistema,
    DominioEventoSistema,
    EventoSistema,
    TipoEventoSistema,
)


_EVENT_CONTRACTS = {
    'ORCAMENTO_APROVADO': ('KANBAN', 'ProjetoKanban'),
    'ORCAMENTO_ARQUIVADO': ('KANBAN', 'ProjetoKanban'),
    'ORCAMENTO_REATIVADO': ('KANBAN', 'ProjetoKanban'),
    'PROJETO_FINALIZADO': ('KANBAN', 'ProjetoKanban'),
    'PAGAMENTO_FUNCIONARIO_CRIADO': ('EQUIPE', 'Funcionario'),
    'LANCAMENTO_QUITADO': ('FINANCEIRO', 'LancamentoFinanceiro'),
    'CONTATO_CONCLUIDO': ('AGENDA', 'AgendaContato'),
    'BACKUP_CONCLUIDO': ('BACKUP', None),
    'BACKUP_FALHOU': ('BACKUP', None),
    'RESTAURACAO_CONCLUIDA': ('RESTAURACAO', None),
    'RESTAURACAO_FALHOU_ROLLBACK_OK': ('RESTAURACAO', None),
}

_EVENT_DESCRIPTIONS = {
    'ORCAMENTO_APROVADO': 'Orçamento aprovado (ProjetoKanban #{id})',
    'ORCAMENTO_ARQUIVADO': 'Orçamento arquivado (ProjetoKanban #{id})',
    'ORCAMENTO_REATIVADO': 'Orçamento reativado (ProjetoKanban #{id})',
    'PROJETO_FINALIZADO': 'Projeto finalizado (ProjetoKanban #{id})',
    'PAGAMENTO_FUNCIONARIO_CRIADO': 'Pagamento de funcionário criado (Funcionario #{id})',
    'LANCAMENTO_QUITADO': 'Lançamento financeiro quitado (LancamentoFinanceiro #{id})',
    'CONTATO_CONCLUIDO': 'Contato concluído (AgendaContato #{id})',
    'BACKUP_CONCLUIDO': 'Backup concluído',
    'BACKUP_FALHOU': 'Falha no backup',
    'RESTAURACAO_CONCLUIDA': 'Restauração concluída',
    'RESTAURACAO_FALHOU_ROLLBACK_OK': 'Restauração falhou; rollback validado',
}

_CANONICAL_ENTITY_ID_RE = re.compile(r'^[1-9][0-9]*$')


def _canonical_entity_id(value: Any) -> str:
    if isinstance(value, bool):
        raise ValidationError('entidade_id deve ser um identificador decimal.')
    if isinstance(value, int):
        if value <= 0:
            raise ValidationError('entidade_id deve ser um identificador decimal.')
        return str(value)
    if not isinstance(value, str) or _CANONICAL_ENTITY_ID_RE.fullmatch(value) is None:
        raise ValidationError('entidade_id deve ser um identificador decimal canônico.')
    return value


def _canonical_money(value: Any) -> str:
    if isinstance(value, (bool, float)):
        raise ValidationError('valores monetários não podem ser bool ou float.')
    from apps.financeiro.models import LancamentoFinanceiro

    try:
        decimal_value = LancamentoFinanceiro.validar_valor_monetario(value)
    except ValidationError:
        raise
    return format(decimal_value.quantize(Decimal('0.01')), 'f')


def _normalize_metadata(tipo: str, metadata: dict[str, Any] | None) -> dict[str, str]:
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValidationError('metadata deve ser um objeto JSON.')
    metadata = dict(metadata)
    allowed = {
        'ORCAMENTO_APROVADO': set(),
        'ORCAMENTO_ARQUIVADO': {'motivo_codigo'},
        'ORCAMENTO_REATIVADO': set(),
        'PROJETO_FINALIZADO': set(),
        'PAGAMENTO_FUNCIONARIO_CRIADO': {'lancamento_id', 'valor'},
        'LANCAMENTO_QUITADO': {'valor'},
        'CONTATO_CONCLUIDO': set(),
        'BACKUP_CONCLUIDO': set(),
        'BACKUP_FALHOU': {'categoria'},
        'RESTAURACAO_CONCLUIDA': set(),
        'RESTAURACAO_FALHOU_ROLLBACK_OK': set(),
    }[tipo]
    if set(metadata) != allowed:
        raise ValidationError('metadata contém chaves inválidas ou ausentes.')
    if 'motivo_codigo' in metadata:
        value = metadata['motivo_codigo']
        if not isinstance(value, str) or not value.strip():
            raise ValidationError('motivo_codigo deve ser texto não vazio.')
        metadata['motivo_codigo'] = value.strip()
    if 'lancamento_id' in metadata:
        metadata['lancamento_id'] = _canonical_entity_id(metadata['lancamento_id'])
    if 'valor' in metadata:
        metadata['valor'] = _canonical_money(metadata['valor'])
    if 'categoria' in metadata:
        categorias = {
            'DESTINO_NAO_CONFIGURADO',
            'DESTINO_INACESSIVEL',
            'ERRO_SQLITE_BACKUP',
        }
        value = metadata['categoria']
        if not isinstance(value, str) or value not in categorias:
            raise ValidationError('categoria de falha do backup inválida.')
    return metadata


def registrar_evento(
    *,
    tipo,
    dominio,
    entidade_tipo=None,
    entidade_id=None,
    metadata=None,
) -> EventoSistema:
    if not isinstance(tipo, str) or not isinstance(dominio, str):
        raise ValidationError('tipo e dominio de evento devem ser texto.')
    valid_types = {value for value, _label in TipoEventoSistema.choices}
    valid_domains = {value for value, _label in DominioEventoSistema.choices}
    if tipo not in valid_types or dominio not in valid_domains:
        raise ValidationError('tipo ou dominio de evento inválido.')
    expected_domain, expected_entity_type = _EVENT_CONTRACTS[tipo]
    if dominio != expected_domain:
        raise ValidationError('A combinação de tipo e domínio do evento é inválida.')
    if expected_entity_type is None:
        if entidade_tipo is not None or entidade_id is not None:
            raise ValidationError('Eventos de sistema não aceitam entidade.')
        normalized_entity_id = None
    else:
        if entidade_tipo != expected_entity_type:
            raise ValidationError('O tipo de entidade do evento é inválido.')
        if entidade_id is None:
            raise ValidationError('A entidade do evento é obrigatória.')
        normalized_entity_id = _canonical_entity_id(entidade_id)
    normalized_metadata = _normalize_metadata(tipo, metadata)
    descricao_template = _EVENT_DESCRIPTIONS[tipo]
    descricao = descricao_template.format(id=normalized_entity_id) if normalized_entity_id else descricao_template
    return EventoSistema.objects.create(
        tipo=tipo,
        dominio=dominio,
        entidade_tipo=expected_entity_type,
        entidade_id=normalized_entity_id,
        descricao=descricao,
        metadata=normalized_metadata,
    )


def backup_realizado_hoje(config, hoje=None) -> bool:
    """Retorna se a configuração registra um backup bem-sucedido hoje."""
    if config is None or not config.ultimo_backup_sucesso or config.ultimo_backup_em is None:
        return False
    data_hoje = hoje or timezone.localdate()
    return timezone.localdate(config.ultimo_backup_em) == data_hoje


@contextmanager
def _maintenance_lock(source_path: Path, operation: str) -> Iterator[bool]:
    """Adquire o lock exclusivo comum às operações de manutenção SQLite."""
    lock_path = source_path.with_name(f'{source_path.name}.backup.lock')
    handle = None
    try:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            yield False
            return
        metadata = (
            f'pid={os.getpid()}\n'
            f'operation={operation}\n'
            f'created_at={datetime.now(dt_timezone.utc).isoformat()}\n'
            f'process_start_identity={_process_start_identity()}\n'
        )
        os.write(handle, metadata.encode('utf-8'))
        yield True
    finally:
        if handle is not None:
            os.close(handle)
            try:
                os.remove(lock_path)
            except FileNotFoundError:
                pass


@contextmanager
def _backup_lock(source_path: Path) -> Iterator[bool]:
    """Compatibilidade do lock de backup com a exclusão de restauração."""
    with _maintenance_lock(source_path, 'BACKUP') as acquired:
        yield acquired


def _process_start_identity() -> str:
    """Identidade de início somente quando há uma fonte local confiável."""
    if os.name != 'nt':
        proc_stat = Path(f'/proc/{os.getpid()}/stat')
        try:
            fields = proc_stat.read_text(encoding='utf-8').split()
            if len(fields) > 21:
                return f'proc-start-ticks:{fields[21]}'
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    return 'unavailable'


def _registrar_falha(config, mensagem: str) -> tuple[bool, str]:
    with transaction.atomic():
        config.ultimo_backup_sucesso = False
        config.mensagem_erro_backup = mensagem[:255]
        config.save(update_fields=['ultimo_backup_sucesso', 'mensagem_erro_backup'])
    return False, mensagem


def _is_regular_source_file(source_path: Path) -> bool:
    try:
        return (
            source_path.exists()
            and source_path.is_file()
            and not _is_symlink_or_reparse(source_path)
        )
    except OSError:
        return False


def _attempt_maintenance_event(*, tipo: str, metadata=None) -> bool:
    try:
        kwargs = {
            'tipo': tipo,
            'dominio': 'BACKUP' if tipo.startswith('BACKUP_') else 'RESTAURACAO',
        }
        if metadata is not None:
            kwargs['metadata'] = metadata
        registrar_evento(**kwargs)
    except Exception:
        return False
    return True


def _backup_failure(config, mensagem: str, categoria: str) -> tuple[bool, str]:
    _registrar_falha(config, mensagem)
    history_ok = _attempt_maintenance_event(
        tipo='BACKUP_FALHOU',
        metadata={'categoria': categoria},
    )
    if not history_ok:
        mensagem += (
            ' Aviso: a falha do backup foi registrada, mas o histórico operacional '
            'não pôde ser registrado.'
        )
    return False, mensagem


def executar_backup_pendrive() -> tuple[bool, str]:
    """Cria um backup SQLite íntegro e aplica retenção só aos seus arquivos."""
    source_name = settings.DATABASES.get('default', {}).get('NAME')
    if not source_name:
        return False, 'Arquivo SQLite de origem não configurado.'
    source_path = Path(source_name)
    if not _is_regular_source_file(source_path):
        return False, 'Arquivo SQLite de origem não encontrado.'

    with _backup_lock(source_path) as acquired:
        if not acquired:
            return False, (
                'Manutenção do banco já está em execução ou o lock pode estar obsoleto. '
                'Verifique manualmente o processo registrado antes de qualquer recuperação.'
            )

        if not _is_regular_source_file(source_path):
            return False, 'Arquivo SQLite de origem não encontrado após a aquisição do lock.'

        config = ConfiguracaoSistema.get_solo()
        pasta_destino = (config.caminho_backup_pendrive or '').strip()
        if not pasta_destino:
            return _backup_failure(
                config,
                'Destino de backup não configurado.',
                'DESTINO_NAO_CONFIGURADO',
            )

        destination = Path(pasta_destino)
        try:
            destination.mkdir(parents=True, exist_ok=True)
            if not destination.is_dir():
                raise OSError('o destino não é uma pasta')
        except OSError as exc:
            return _backup_failure(
                config,
                f'Não foi possível acessar o destino de backup: {exc}',
                'DESTINO_INACESSIVEL',
            )

        date_text = timezone.localdate().strftime('%Y-%m-%d')
        final_path = destination / f'backup_marcenaria_{date_text}.sqlite3'
        temp_path = destination / f'.{final_path.name}.{uuid.uuid4().hex}.tmp'
        source_conn = destination_conn = None
        try:
            source_conn = sqlite3.connect(_sqlite_read_only_uri(source_path), uri=True)
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
            except OSError:
                pass
            return _backup_failure(
                config,
                f'Erro ao realizar backup do SQLite: {exc}',
                'ERRO_SQLITE_BACKUP',
            )

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

        message = f"Backup realizado com sucesso em '{final_path}'!"
        if not _attempt_maintenance_event(tipo='BACKUP_CONCLUIDO'):
            message += (
                ' Aviso: o backup foi concluído, mas o histórico operacional '
                'não pôde ser registrado.'
            )
        return True, message


RESTORE_SUCCESS = 'SUCCESS'
RESTORE_CATEGORIES = frozenset({
    'INVALID_SOURCE',
    'NOT_SQLITE',
    'CORRUPT_SQLITE',
    'NOT_FINANPE_DATABASE',
    'INCOMPATIBLE_SCHEMA',
    'LIVE_DATABASE_AS_SOURCE',
    'SERVER_OR_DATABASE_IN_USE',
    'MAINTENANCE_LOCKED',
    'SAFETY_COPY_FAILED',
    'STAGING_FAILED',
    'REPLACEMENT_FAILED',
    'POST_VALIDATION_FAILED_ROLLBACK_OK',
    'POST_VALIDATION_FAILED_ROLLBACK_FAILED',
    'INVALID_CONFIRMATION',
})


@dataclass(frozen=True)
class RestoreResult:
    success: bool
    category: str
    message: str
    source_path: str
    live_db_path: str
    dry_run: bool
    safety_copy_path: str | None = None
    staging_path: str | None = None
    failed_restore_path: str | None = None
    rollback_performed: bool = False
    rollback_success: bool | None = None

    @property
    def code(self) -> str:
        return self.category


@dataclass(frozen=True)
class _CandidateValidation:
    valid: bool
    category: str
    message: str


_REQUIRED_MODELS = (
    ('core_sistema', 'ConfiguracaoSistema'),
    ('core_sistema', 'EventoSistema'),
    ('clientes_agenda', 'Cliente'),
    ('clientes_agenda', 'AgendaContato'),
    ('kanban_projetos', 'ProjetoKanban'),
    ('equipe', 'Funcionario'),
    ('financeiro', 'LancamentoFinanceiro'),
)
_PRE_HISTORY_REQUIRED_MODELS = tuple(
    item for item in _REQUIRED_MODELS if item != ('core_sistema', 'EventoSistema')
)


def _configured_live_database() -> Path:
    name = settings.DATABASES.get('default', {}).get('NAME')
    if not name:
        raise ValueError('Arquivo SQLite oficial não está configurado.')
    return Path(name).expanduser()


def _is_absolute_path(value: str, path: Path) -> bool:
    return path.is_absolute() or ntpath.isabs(value)


def _is_network_path(path: Path, raw_value: str) -> bool:
    normalized = raw_value.replace('/', '\\')
    if normalized.startswith('\\\\'):
        return True
    if os.name != 'nt' or not path.drive:
        return False
    try:
        import ctypes

        drive_root = f'{path.drive}\\'
        return ctypes.windll.kernel32.GetDriveTypeW(drive_root) == 4
    except (AttributeError, OSError, TypeError):
        return False


def _is_symlink_or_reparse(path: Path) -> bool:
    if path.is_symlink() or os.path.islink(path):
        return True
    try:
        attributes = getattr(os.lstat(path), 'st_file_attributes', 0)
        return bool(attributes & 0x400)
    except OSError:
        return False


def _sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(path.with_name(path.name + suffix) for suffix in ('-wal', '-shm', '-journal'))


def _sqlite_read_only_uri(path: Path) -> str:
    return f'{path.resolve(strict=False).as_uri()}?mode=ro'


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _has_sqlite_header(path: Path) -> bool:
    try:
        with path.open('rb') as handle:
            return handle.read(16) == b'SQLite format 3\x00'
    except OSError:
        return False


def _schema_for_models(
    model_specs: tuple[tuple[str, str], ...],
) -> dict[str, set[str]]:
    required = {
        'django_migrations': {'id', 'app', 'name', 'applied'},
    }
    for app_label, model_name in model_specs:
        model = apps.get_model(app_label, model_name)
        required[model._meta.db_table] = {
            field.column for field in model._meta.local_concrete_fields
        }
    return required


def _required_schema() -> dict[str, set[str]]:
    return _schema_for_models(_REQUIRED_MODELS)


def _pre_history_required_schema() -> dict[str, set[str]]:
    return _schema_for_models(_PRE_HISTORY_REQUIRED_MODELS)


def _missing_required_schema(
    connection: sqlite3.Connection,
    required: dict[str, set[str]],
) -> str | None:
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'",
    ).fetchall()
    tables = {row[0] for row in table_rows}
    missing_tables = sorted(set(required) - tables)
    if missing_tables:
        return f'Tabelas FinanPE ausentes: {", ".join(missing_tables)}.'
    for table, columns in required.items():
        table_info = connection.execute(
            f'PRAGMA table_info({_quote_identifier(table)})',
        ).fetchall()
        available_columns = {row[1] for row in table_info}
        missing_columns = sorted(columns - available_columns)
        if missing_columns:
            return f'Colunas ausentes em {table}: {", ".join(missing_columns)}.'
    return None


def _current_migration_set() -> frozenset[tuple[str, str]]:
    loader = MigrationLoader(
        connections['default'],
        load=False,
        ignore_no_migrations=True,
    )
    loader.load_disk()
    return frozenset(loader.disk_migrations)


def _validation(
    valid: bool,
    category: str,
    message: str,
) -> _CandidateValidation:
    return _CandidateValidation(valid, category, message)


def _validate_candidate(
    candidate_path: Path,
    live_path: Path,
    expected_migrations: frozenset[tuple[str, str]],
    *,
    reject_live: bool,
) -> _CandidateValidation:
    raw_value = str(candidate_path)
    if not _is_absolute_path(raw_value, candidate_path):
        return _validation(False, 'INVALID_SOURCE', 'A origem deve ser um caminho absoluto.')
    if _is_network_path(candidate_path, raw_value):
        return _validation(False, 'INVALID_SOURCE', 'Origem de rede/UNC não é aceita.')
    try:
        resolved = candidate_path.resolve(strict=False)
        live_resolved = live_path.resolve(strict=False)
    except OSError:
        return _validation(False, 'INVALID_SOURCE', 'Não foi possível resolver o caminho informado.')
    if reject_live and resolved == live_resolved:
        return _validation(
            False,
            'LIVE_DATABASE_AS_SOURCE',
            'A origem não pode ser o banco SQLite ativo.',
        )
    if any(sidecar.exists() for sidecar in _sidecars(candidate_path)):
        return _validation(
            False,
            'SERVER_OR_DATABASE_IN_USE',
            'Há sidecar SQLite adjacente; pare o FinanPE e obtenha um arquivo standalone.',
        )
    try:
        if not candidate_path.exists() or not candidate_path.is_file():
            return _validation(False, 'INVALID_SOURCE', 'A origem deve ser um arquivo regular existente.')
        if _is_symlink_or_reparse(candidate_path):
            return _validation(False, 'INVALID_SOURCE', 'Symlink ou reparse point não é aceito como origem.')
        if candidate_path.stat().st_size == 0:
            return _validation(False, 'INVALID_SOURCE', 'A origem não pode ser um arquivo vazio.')
    except OSError:
        return _validation(False, 'INVALID_SOURCE', 'Não foi possível acessar a origem local.')

    connection = None
    try:
        connection = sqlite3.connect(_sqlite_read_only_uri(candidate_path), uri=True)
        try:
            integrity = connection.execute('PRAGMA integrity_check').fetchone()
        except sqlite3.DatabaseError:
            category = 'CORRUPT_SQLITE' if _has_sqlite_header(candidate_path) else 'NOT_SQLITE'
            return _validation(False, category, 'A integridade do SQLite não pôde ser validada.')
        if not integrity or integrity[0] != 'ok':
            return _validation(False, 'CORRUPT_SQLITE', 'PRAGMA integrity_check não retornou ok.')

        basic_schema_error = _missing_required_schema(
            connection,
            _pre_history_required_schema(),
        )
        if basic_schema_error:
            return _validation(
                False,
                'NOT_FINANPE_DATABASE',
                basic_schema_error,
            )

        applied = frozenset(
            (row[0], row[1])
            for row in connection.execute('SELECT app, name FROM django_migrations').fetchall()
        )
        if applied != expected_migrations:
            return _validation(
                False,
                'INCOMPATIBLE_SCHEMA',
                'O conjunto de migrations não é exatamente compatível com o executável atual.',
            )
        current_schema_error = _missing_required_schema(
            connection,
            _required_schema(),
        )
        if current_schema_error:
            return _validation(
                False,
                'NOT_FINANPE_DATABASE',
                current_schema_error,
            )
    except sqlite3.DatabaseError:
        category = 'CORRUPT_SQLITE' if _has_sqlite_header(candidate_path) else 'NOT_SQLITE'
        return _validation(False, category, 'A origem não é um SQLite FinanPE válido.')
    except (OSError, ValueError):
        return _validation(False, 'NOT_SQLITE', 'Não foi possível abrir a origem como SQLite.')
    finally:
        if connection is not None:
            connection.close()
    return _validation(True, RESTORE_SUCCESS, 'Arquivo SQLite FinanPE íntegro e compatível.')


def _preflight(
    source_path: Path,
    live_path: Path,
) -> tuple[_CandidateValidation, frozenset[tuple[str, str]] | None]:
    if any(sidecar.exists() for sidecar in _sidecars(live_path)):
        return (
            _validation(
                False,
                'SERVER_OR_DATABASE_IN_USE',
                'Há sidecar SQLite no banco ativo; encerre o FinanPE antes da restauração.',
            ),
            None,
        )
    try:
        expected_migrations = _current_migration_set()
    except Exception:
        return (
            _validation(False, 'INCOMPATIBLE_SCHEMA', 'Não foi possível determinar as migrations atuais.'),
            None,
        )
    live_validation = _validate_candidate(
        live_path,
        live_path,
        expected_migrations,
        reject_live=False,
    )
    if not live_validation.valid:
        return live_validation, expected_migrations
    source_validation = _validate_candidate(
        source_path,
        live_path,
        expected_migrations,
        reject_live=True,
    )
    return source_validation, expected_migrations


def _flush_and_sync(handle) -> None:
    handle.flush()
    try:
        os.fsync(handle.fileno())
    except (AttributeError, OSError):
        pass


def _copy_file_verified(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as source_handle, destination.open('xb') as destination_handle:
        while True:
            block = source_handle.read(1024 * 1024)
            if not block:
                break
            destination_handle.write(block)
        _flush_and_sync(destination_handle)
    if destination.stat().st_size == 0:
        raise OSError('A cópia resultou em arquivo vazio.')


def _artifact_path(live_path: Path, label: str, suffix: str = '.sqlite3') -> Path:
    timestamp = datetime.now(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return live_path.with_name(f'{live_path.name}.{label}-{timestamp}-{uuid.uuid4().hex}{suffix}')


def _validated_copy(
    source: Path,
    final_path: Path,
    live_path: Path,
    expected_migrations: frozenset[tuple[str, str]],
) -> Path:
    temporary = final_path.with_name(f'.{final_path.name}.{uuid.uuid4().hex}.tmp')
    try:
        _copy_file_verified(source, temporary)
        validation = _validate_candidate(
            temporary,
            live_path,
            expected_migrations,
            reject_live=False,
        )
        if not validation.valid:
            raise ValueError(validation.message)
        os.replace(temporary, final_path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return final_path


def _result(
    *,
    success: bool,
    category: str,
    message: str,
    source_path: Path,
    live_path: Path,
    dry_run: bool,
    safety_copy_path: Path | None = None,
    staging_path: Path | None = None,
    failed_restore_path: Path | None = None,
    rollback_performed: bool = False,
    rollback_success: bool | None = None,
) -> RestoreResult:
    return RestoreResult(
        success=success,
        category=category,
        message=message,
        source_path=str(source_path),
        live_db_path=str(live_path),
        dry_run=dry_run,
        safety_copy_path=str(safety_copy_path) if safety_copy_path else None,
        staging_path=str(staging_path) if staging_path else None,
        failed_restore_path=str(failed_restore_path) if failed_restore_path else None,
        rollback_performed=rollback_performed,
        rollback_success=rollback_success,
    )


def restore_backup(
    source_path: str | Path,
    *,
    live_db_path: str | Path | None = None,
    confirm_restore: bool = False,
    expected_live_db: str | Path | None = None,
    dry_run: bool = False,
) -> RestoreResult:
    """Valida ou restaura um SQLite local com cópia de segurança e rollback."""
    source = Path(source_path).expanduser()
    try:
        live = (
            Path(live_db_path).expanduser()
            if live_db_path is not None
            else _configured_live_database()
        )
    except ValueError as exc:
        return _result(
            success=False,
            category='INVALID_CONFIRMATION',
            message=str(exc),
            source_path=source,
            live_path=Path('db.sqlite3'),
            dry_run=True,
        )
    if dry_run and confirm_restore:
        return _result(
            success=False,
            category='INVALID_CONFIRMATION',
            message='--dry-run não pode ser combinado com --confirm-restore.',
            source_path=source,
            live_path=live,
            dry_run=True,
        )
    if confirm_restore:
        if expected_live_db is None:
            return _result(
                success=False,
                category='INVALID_CONFIRMATION',
                message='A restauração exige --expected-live-db.',
                source_path=source,
                live_path=live,
                dry_run=False,
            )
        expected = Path(expected_live_db).expanduser()
        if not _is_absolute_path(str(expected_live_db), expected):
            return _result(
                success=False,
                category='INVALID_CONFIRMATION',
                message='--expected-live-db deve ser um caminho absoluto.',
                source_path=source,
                live_path=live,
                dry_run=False,
            )
        try:
            if expected.resolve(strict=False) != live.resolve(strict=False):
                return _result(
                    success=False,
                    category='INVALID_CONFIRMATION',
                    message='--expected-live-db não corresponde ao banco configurado.',
                    source_path=source,
                    live_path=live,
                    dry_run=False,
                )
        except OSError:
            return _result(
                success=False,
                category='INVALID_CONFIRMATION',
                message='Não foi possível resolver --expected-live-db.',
                source_path=source,
                live_path=live,
                dry_run=False,
            )
    elif expected_live_db is not None:
        return _result(
            success=False,
            category='INVALID_CONFIRMATION',
            message='--expected-live-db só pode ser usado com --confirm-restore.',
            source_path=source,
            live_path=live,
            dry_run=True,
        )

    effective_dry_run = not confirm_restore
    if dry_run:
        effective_dry_run = True
    preflight, expected_migrations = _preflight(source, live)
    if not preflight.valid or expected_migrations is None:
        return _result(
            success=False,
            category=preflight.category,
            message=preflight.message,
            source_path=source,
            live_path=live,
            dry_run=effective_dry_run,
        )
    if effective_dry_run:
        return _result(
            success=True,
            category=RESTORE_SUCCESS,
            message='Pré-validação concluída; nenhum arquivo foi alterado.',
            source_path=source,
            live_path=live,
            dry_run=True,
        )

    with _maintenance_lock(live, 'RESTORE') as acquired:
        if not acquired:
            return _result(
                success=False,
                category='MAINTENANCE_LOCKED',
                message=(
                    'Manutenção já está em execução ou o lock pode estar obsoleto. '
                    'Verifique manualmente se o processo registrado não está mais ativo; '
                    'remoção automática não é realizada.'
                ),
                source_path=source,
                live_path=live,
                dry_run=False,
            )
        repeated_preflight, expected_migrations = _preflight(source, live)
        if not repeated_preflight.valid or expected_migrations is None:
            return _result(
                success=False,
                category=repeated_preflight.category,
                message='Pré-validação repetida falhou após o lock: ' + repeated_preflight.message,
                source_path=source,
                live_path=live,
                dry_run=False,
            )

        safety_copy = _artifact_path(live, 'pre-restore')
        try:
            _validated_copy(live, safety_copy, live, expected_migrations)
        except Exception as exc:
            return _result(
                success=False,
                category='SAFETY_COPY_FAILED',
                message=f'Não foi possível criar e validar a cópia de segurança pré-restauração: {exc}',
                source_path=source,
                live_path=live,
                dry_run=False,
            )

        staging = _artifact_path(live, 'restore-stage', '.tmp')
        try:
            _copy_file_verified(source, staging)
        except Exception as exc:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
            return _result(
                success=False,
                category='STAGING_FAILED',
                message=f'Não foi possível preparar o arquivo de restauração: {exc}',
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
                staging_path=staging,
            )
        staged_validation = _validate_candidate(
            staging,
            live,
            expected_migrations,
            reject_live=False,
        )
        if not staged_validation.valid:
            try:
                staging.unlink()
            except FileNotFoundError:
                pass
            return _result(
                success=False,
                category='STAGING_FAILED',
                message='A cópia preparada falhou na validação: ' + staged_validation.message,
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
                staging_path=staging,
            )

        connections.close_all()
        try:
            os.replace(staging, live)
        except OSError as exc:
            return _result(
                success=False,
                category='REPLACEMENT_FAILED',
                message=f'A substituição atômica não foi executada: {exc}',
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
                staging_path=staging,
            )

        post_validation = _validate_candidate(
            live,
            live,
            expected_migrations,
            reject_live=False,
        )
        if post_validation.valid:
            message = 'Restauração concluída e o banco substituído foi validado.'
            if not _attempt_maintenance_event(tipo='RESTAURACAO_CONCLUIDA'):
                message += (
                    ' Aviso: a restauração foi concluída e validada, mas o histórico '
                    'operacional não pôde ser registrado.'
                )
            return _result(
                success=True,
                category=RESTORE_SUCCESS,
                message=message,
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
            )

        failed_restore = _artifact_path(live, 'failed-restore')
        try:
            _copy_file_verified(live, failed_restore)
        except Exception as exc:
            cleanup_message = ''
            try:
                failed_restore.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_exc:
                cleanup_message = f' A limpeza do artefato parcial também falhou: {cleanup_exc}.'
            return _result(
                success=False,
                category='POST_VALIDATION_FAILED_ROLLBACK_FAILED',
                message=(
                    'A validação pós-restauração falhou e a preservação forense do banco '
                    f'rejeitado também falhou: {exc}. O rollback não foi tentado para evitar '
                    'destruir o candidato rejeitado, que permanece no banco ativo e não deve '
                    'ser considerado válido. A cópia de segurança pré-restauração validada '
                    f'permanece disponível para recuperação manual.{cleanup_message}'
                ),
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
                rollback_performed=False,
                rollback_success=None,
            )

        rollback_stage = _artifact_path(live, 'rollback-stage', '.tmp')
        try:
            _copy_file_verified(safety_copy, rollback_stage)
            rollback_validation = _validate_candidate(
                rollback_stage,
                live,
                expected_migrations,
                reject_live=False,
            )
            if not rollback_validation.valid:
                raise ValueError(rollback_validation.message)
            connections.close_all()
            os.replace(rollback_stage, live)
            restored_validation = _validate_candidate(
                live,
                live,
                expected_migrations,
                reject_live=False,
            )
            if not restored_validation.valid:
                raise ValueError(restored_validation.message)
        except Exception as exc:
            return _result(
                success=False,
                category='POST_VALIDATION_FAILED_ROLLBACK_FAILED',
                message=(
                    'A validação pós-restauração falhou e o rollback não foi confirmado: '
                    f'{exc}. O banco ativo não deve ser considerado válido.'
                ),
                source_path=source,
                live_path=live,
                dry_run=False,
                safety_copy_path=safety_copy,
                staging_path=rollback_stage,
                failed_restore_path=failed_restore,
                rollback_performed=True,
                rollback_success=False,
            )
        message = (
            'A validação pós-restauração falhou; o banco anterior foi restaurado e validado. '
            'A operação solicitada não foi considerada bem-sucedida.'
        )
        if not _attempt_maintenance_event(
            tipo='RESTAURACAO_FALHOU_ROLLBACK_OK',
        ):
            message += (
                ' Aviso: o rollback foi concluído e validado, mas o histórico operacional '
                'não pôde ser registrado.'
            )
        return _result(
            success=False,
            category='POST_VALIDATION_FAILED_ROLLBACK_OK',
            message=message,
            source_path=source,
            live_path=live,
            dry_run=False,
            safety_copy_path=safety_copy,
            failed_restore_path=failed_restore,
            rollback_performed=True,
            rollback_success=True,
        )
