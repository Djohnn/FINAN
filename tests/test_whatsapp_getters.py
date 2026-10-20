from urllib.parse import unquote

from django.test import TestCase

from apps.clientes_agenda.models import AgendaContato, Cliente
from apps.core_sistema.models import ConfiguracaoSistema
from apps.kanban_projetos.models import ProjetoKanban


class WhatsAppGetterTests(TestCase):
    def _cliente(self, whatsapp="11999999999"):
        return Cliente.objects.create(
            nome="Cliente WhatsApp",
            whatsapp=whatsapp,
        )

    def _projeto(self, cliente=None, **overrides):
        return ProjetoKanban.objects.create(
            cliente=cliente or self._cliente(),
            titulo_servico="Armário da cozinha",
            **overrides,
        )

    def _agenda(self, cliente=None, projeto=None, tipo="POS_VENDA_30_DIAS"):
        return AgendaContato.objects.create(
            cliente=cliente or self._cliente(),
            projeto=projeto,
            tipo=tipo,
            data_agendada="2026-10-19",
        )

    def test_project_without_config_generates_url_without_creating_config(self):
        projeto = self._projeto()

        url = projeto.get_whatsapp_url()

        self.assertTrue(url.startswith("https://wa.me/5511999999999?text="))
        self.assertIn("Minha Marcenaria", unquote(url))
        self.assertEqual(ConfiguracaoSistema.objects.count(), 0)

    def test_agenda_without_config_generates_url_without_creating_config(self):
        agenda = self._agenda()

        url = agenda.get_whatsapp_url()

        self.assertTrue(url.startswith("https://wa.me/5511999999999?text="))
        self.assertIn("Minha Marcenaria", unquote(url))
        self.assertEqual(ConfiguracaoSistema.objects.count(), 0)

    def test_project_with_blank_config_uses_legacy_fallback_without_second_row(self):
        ConfiguracaoSistema.objects.create(nome_marcenaria="")
        projeto = self._projeto()

        url = projeto.get_whatsapp_url()

        self.assertIn("Marcenaria", unquote(url))
        self.assertNotIn("Minha Marcenaria", unquote(url))
        self.assertEqual(ConfiguracaoSistema.objects.count(), 1)

    def test_agenda_with_blank_config_uses_legacy_fallback_without_second_row(self):
        ConfiguracaoSistema.objects.create(nome_marcenaria="")
        agenda = self._agenda()

        url = agenda.get_whatsapp_url()

        self.assertIn("Marcenaria", unquote(url))
        self.assertNotIn("Minha Marcenaria", unquote(url))
        self.assertEqual(ConfiguracaoSistema.objects.count(), 1)

    def test_project_with_custom_config_preserves_custom_name(self):
        ConfiguracaoSistema.objects.create(nome_marcenaria="Marcenaria Exemplo")
        projeto = self._projeto()

        self.assertIn("Marcenaria Exemplo", unquote(projeto.get_whatsapp_url()))

    def test_agenda_with_custom_config_preserves_custom_name(self):
        ConfiguracaoSistema.objects.create(nome_marcenaria="Marcenaria Exemplo")
        agenda = self._agenda()

        self.assertIn("Marcenaria Exemplo", unquote(agenda.get_whatsapp_url()))

    def test_project_preserves_phone_normalization_and_url_encoding(self):
        projeto = self._projeto(cliente=self._cliente("(11) 99999-9999"))

        url = projeto.get_whatsapp_url()

        self.assertTrue(url.startswith("https://wa.me/5511999999999?text="))
        self.assertNotIn(" ", url)
        self.assertIn("%C3%A1", url)
        self.assertEqual(ConfiguracaoSistema.objects.count(), 0)

    def test_agenda_type_preserves_message_and_url(self):
        agenda = self._agenda(tipo="RETORNO_ORCAMENTO")

        url = agenda.get_whatsapp_url()

        self.assertTrue(url.startswith("https://wa.me/5511999999999?text="))
        self.assertIn("ainda tem planos para o projeto", unquote(url))

    def test_project_without_whatsapp_returns_empty_without_creating_config(self):
        projeto = self._projeto(cliente=self._cliente(""))

        self.assertEqual(projeto.get_whatsapp_url(), "")
        self.assertEqual(ConfiguracaoSistema.objects.count(), 0)

    def test_non_numeric_phone_returns_empty_without_creating_config(self):
        agenda = self._agenda(cliente=self._cliente("---"))

        self.assertEqual(agenda.get_whatsapp_url(), "")
        self.assertEqual(ConfiguracaoSistema.objects.count(), 0)
