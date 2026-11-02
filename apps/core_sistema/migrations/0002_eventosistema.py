from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ('core_sistema', '0001_initial'),
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.CreateModel(
            name='EventoSistema',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'tipo',
                    models.CharField(
                        choices=[
                            ('ORCAMENTO_APROVADO', 'Orçamento aprovado'),
                            ('ORCAMENTO_ARQUIVADO', 'Orçamento arquivado'),
                            ('ORCAMENTO_REATIVADO', 'Orçamento reativado'),
                            ('PROJETO_FINALIZADO', 'Projeto finalizado'),
                            (
                                'PAGAMENTO_FUNCIONARIO_CRIADO',
                                'Pagamento de funcionário criado',
                            ),
                            ('LANCAMENTO_QUITADO', 'Lançamento quitado'),
                            ('CONTATO_CONCLUIDO', 'Contato concluído'),
                            ('BACKUP_CONCLUIDO', 'Backup concluído'),
                            ('BACKUP_FALHOU', 'Backup falhou'),
                            ('RESTAURACAO_CONCLUIDA', 'Restauração concluída'),
                            (
                                'RESTAURACAO_FALHOU_ROLLBACK_OK',
                                'Restauração falhou; rollback validado',
                            ),
                        ],
                        max_length=50,
                    ),
                ),
                (
                    'dominio',
                    models.CharField(
                        choices=[
                            ('KANBAN', 'Kanban'),
                            ('EQUIPE', 'Equipe'),
                            ('FINANCEIRO', 'Financeiro'),
                            ('AGENDA', 'Agenda'),
                            ('BACKUP', 'Backup'),
                            ('RESTAURACAO', 'Restauração'),
                        ],
                        max_length=15,
                    ),
                ),
                ('entidade_tipo', models.CharField(blank=True, max_length=60, null=True)),
                ('entidade_id', models.CharField(blank=True, max_length=64, null=True)),
                ('descricao', models.CharField(max_length=255)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Evento do Sistema',
                'verbose_name_plural': 'Eventos do Sistema',
            },
        ),
        migrations.AddIndex(
            model_name='eventosistema',
            index=models.Index(
                fields=[
                    'dominio',
                    'entidade_tipo',
                    'entidade_id',
                    '-criado_em',
                    '-id',
                ],
                name='evento_ent_hist_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='eventosistema',
            index=models.Index(
                fields=['tipo', '-criado_em', '-id'],
                name='evento_tipo_data_idx',
            ),
        ),
    ]
