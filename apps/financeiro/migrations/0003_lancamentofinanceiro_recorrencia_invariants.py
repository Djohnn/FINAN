from django.db import migrations, models


DROP_PHASE7_TRIGGERS = (
    'DROP TRIGGER IF EXISTS financeiro_despesa_rec_criado_em_guard;',
    'DROP TRIGGER IF EXISTS financeiro_lanc_recorrente_origin_guard;',
    'DROP TRIGGER IF EXISTS financeiro_lanc_competencia_insert_guard;',
    'DROP TRIGGER IF EXISTS financeiro_lanc_competencia_update_guard;',
    'DROP TRIGGER IF EXISTS financeiro_lanc_identity_guard;',
    'DROP TRIGGER IF EXISTS financeiro_lanc_recorrente_delete_guard;',
)

CREATE_PHASE7_TRIGGERS = (
    """
    CREATE TRIGGER financeiro_despesa_rec_criado_em_guard
    BEFORE UPDATE OF criado_em ON financeiro_despesarecorrente
    FOR EACH ROW
    WHEN OLD.criado_em IS NOT NEW.criado_em
    BEGIN
        SELECT RAISE(ABORT, 'recurring expense created_at is immutable');
    END;
    """,
    """
    CREATE TRIGGER financeiro_lanc_recorrente_origin_guard
    BEFORE INSERT ON financeiro_lancamentofinanceiro
    FOR EACH ROW
    WHEN NEW.recorrencia_id IS NOT NULL
     AND (
         NEW.tipo IS NOT 'SAIDA'
         OR NEW.status IS NOT 'PENDENTE'
         OR NEW.projeto_id IS NOT NULL
         OR NEW.funcionario_id IS NOT NULL
         OR NEW.data_pagamento IS NOT NULL
     )
    BEGIN
        SELECT RAISE(ABORT, 'recurring ledger origin is invalid');
    END;
    """,
    """
    CREATE TRIGGER financeiro_lanc_competencia_insert_guard
    BEFORE INSERT ON financeiro_lancamentofinanceiro
    FOR EACH ROW
    WHEN NOT (
        (NEW.recorrencia_id IS NULL AND NEW.competencia IS NULL)
        OR (
            NEW.recorrencia_id IS NOT NULL
            AND NEW.competencia IS NOT NULL
            AND length(NEW.competencia) = 10
            AND NEW.competencia GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'
            AND substr(NEW.competencia, 1, 4) BETWEEN '0001' AND '9999'
            AND strftime('%Y-%m-%d', NEW.competencia) = NEW.competencia
            AND date(NEW.competencia, 'start of month', '+0 days') = NEW.competencia
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'competencia must be canonical');
    END;
    """,
    """
    CREATE TRIGGER financeiro_lanc_competencia_update_guard
    BEFORE UPDATE OF recorrencia_id, competencia
    ON financeiro_lancamentofinanceiro
    FOR EACH ROW
    WHEN NOT (
        (NEW.recorrencia_id IS NULL AND NEW.competencia IS NULL)
        OR (
            NEW.recorrencia_id IS NOT NULL
            AND NEW.competencia IS NOT NULL
            AND length(NEW.competencia) = 10
            AND NEW.competencia GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'
            AND substr(NEW.competencia, 1, 4) BETWEEN '0001' AND '9999'
            AND strftime('%Y-%m-%d', NEW.competencia) = NEW.competencia
            AND date(NEW.competencia, 'start of month', '+0 days') = NEW.competencia
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'competencia must be canonical');
    END;
    """,
    """
    CREATE TRIGGER financeiro_lanc_identity_guard
    BEFORE UPDATE OF recorrencia_id, competencia
    ON financeiro_lancamentofinanceiro
    FOR EACH ROW
    WHEN OLD.recorrencia_id IS NOT NEW.recorrencia_id
      OR OLD.competencia IS NOT NEW.competencia
    BEGIN
        SELECT RAISE(ABORT, 'recorrencia identity is immutable');
    END;
    """,
    """
    CREATE TRIGGER financeiro_lanc_recorrente_delete_guard
    BEFORE DELETE ON financeiro_lancamentofinanceiro
    FOR EACH ROW
    WHEN OLD.recorrencia_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'recurring ledger rows cannot be deleted');
    END;
    """,
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ('financeiro', '0002_lancamentofinanceiro_competencia_despesarecorrente_and_more'),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.RunSQL(
            sql=DROP_PHASE7_TRIGGERS,
            reverse_sql=CREATE_PHASE7_TRIGGERS,
        ),
        migrations.AddConstraint(
            model_name='lancamentofinanceiro',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(recorrencia__isnull=True)
                    | models.Q(
                        tipo='SAIDA',
                        projeto__isnull=True,
                        funcionario__isnull=True,
                    )
                ),
                name='financeiro_lanc_recorrencia_invariants',
            ),
        ),
        migrations.RunSQL(
            sql=CREATE_PHASE7_TRIGGERS,
            reverse_sql=DROP_PHASE7_TRIGGERS,
        ),
    ]
