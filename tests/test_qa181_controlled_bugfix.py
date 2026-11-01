from urllib.parse import parse_qs, unquote, urlparse

from django.test import TestCase
from django.urls import reverse

from apps.clientes_agenda.models import Cliente
from apps.kanban_projetos.models import ProjetoKanban


class QA181ControlledBugfixTests(TestCase):
    def test_favicon_route_serves_local_svg(self):
        response = self.client.get("/favicon.ico")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", b"".join(response.streaming_content))

    def test_customer_index_uses_aria_label_for_action_header(self):
        Cliente.objects.create(nome="Cliente QA181", whatsapp="8190000101")

        response = self.client.get(reverse("clientes_agenda:clientes"))
        html = response.content.decode()

        self.assertContains(response, 'aria-label="Ação"')
        self.assertNotIn(
            '<th scope="col"><span class="visually-hidden">Ação</span></th>',
            html,
        )

    def test_whatsapp_link_contract_is_verified_without_requesting_external_host(self):
        cliente = Cliente.objects.create(
            nome="Cliente QA181",
            whatsapp="(81) 90000-1010",
        )
        projeto = ProjetoKanban.objects.create(
            cliente=cliente,
            titulo_servico="Armário QA181",
            etapa="1_CONTATO",
        )

        parsed = urlparse(projeto.get_whatsapp_url())

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "wa.me")
        self.assertEqual(parsed.path, "/5581900001010")
        self.assertIn("text", parse_qs(parsed.query))
        self.assertIn("Armário QA181", unquote(parse_qs(parsed.query)["text"][0]))
