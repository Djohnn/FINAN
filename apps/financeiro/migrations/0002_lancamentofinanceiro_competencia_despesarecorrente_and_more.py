import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('equipe', '0001_initial'),
        ('financeiro', '0001_initial'),
        ('kanban_projetos', '0003_configuracaoetapakanban_posicao_visual'),
    ]

    operations = [
        migrations.AddField(
            model_name='lancamentofinanceiro',
            name='competencia',
            field=models.DateField(blank=True, null=True, verbose_name='Competência'),
        ),
        migrations.CreateModel(
            name='DespesaRecorrente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('descricao', models.CharField(max_length=200, verbose_name='Descrição')),
                ('categoria', models.CharField(choices=[('SERVICO_CLIENTE', 'Serviço de Cliente'), ('FUNCIONARIO', 'Equipe / Funcionários'), ('MATERIA_PRIMA', 'Matéria-Prima'), ('CUSTO_FIXO_OFICINA', 'Custos Fixos da Oficina'), ('OUTROS', 'Outros')], max_length=30, verbose_name='Categoria')),
                ('valor', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Valor (R$)')),
                ('forma_pagamento', models.CharField(choices=[('PIX', 'PIX'), ('CARTAO_CREDITO', 'Cartão de Crédito'), ('CARTAO_DEBITO', 'Cartão de Débito'), ('DINHEIRO', 'Dinheiro'), ('BOLETO', 'Boleto')], default='PIX', max_length=20, verbose_name='Forma de Pagamento')),
                ('dia_vencimento', models.PositiveSmallIntegerField(verbose_name='Dia de Vencimento')),
                ('data_inicio', models.DateField(verbose_name='Data de Início')),
                ('data_fim', models.DateField(blank=True, null=True, verbose_name='Data de Fim')),
                ('ativo', models.BooleanField(default=True, verbose_name='Ativa')),
                ('observacao', models.TextField(blank=True, verbose_name='Observação')),
                ('criado_em', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
            ],
            options={
                'verbose_name': 'Despesa Recorrente',
                'verbose_name_plural': 'Despesas Recorrentes',
                'ordering': ['-ativo', 'dia_vencimento', 'descricao', 'id'],
                'constraints': [models.CheckConstraint(condition=models.Q(('valor__gt', 0)), name='financeiro_despesa_rec_valor_positivo'), models.CheckConstraint(condition=models.Q(('dia_vencimento__gte', 1), ('dia_vencimento__lte', 31)), name='financeiro_despesa_rec_dia_1_31'), models.CheckConstraint(condition=models.Q(('data_fim__isnull', True), ('data_fim__gte', models.F('data_inicio')), _connector='OR'), name='financeiro_despesa_rec_datas_coerentes')],
            },
        ),
        migrations.AddField(
            model_name='lancamentofinanceiro',
            name='recorrencia',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='lancamentos', to='financeiro.despesarecorrente', verbose_name='Despesa Recorrente'),
        ),
        migrations.AddConstraint(
            model_name='lancamentofinanceiro',
            constraint=models.UniqueConstraint(fields=('recorrencia', 'competencia'), name='financeiro_lanc_recorrencia_competencia_uniq'),
        ),
        migrations.AddConstraint(
            model_name='lancamentofinanceiro',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('competencia__isnull', True), ('recorrencia__isnull', True)), models.Q(('competencia__isnull', False), ('recorrencia__isnull', False)), _connector='OR'), name='financeiro_lanc_recorrencia_competencia_pair'),
        ),
        migrations.RunSQL(
            sql=[
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
            ],
            reverse_sql=[
                'DROP TRIGGER IF EXISTS financeiro_lanc_competencia_insert_guard;',
                'DROP TRIGGER IF EXISTS financeiro_lanc_competencia_update_guard;',
                'DROP TRIGGER IF EXISTS financeiro_lanc_identity_guard;',
                'DROP TRIGGER IF EXISTS financeiro_lanc_recorrente_delete_guard;',
            ],
        ),
    ]
