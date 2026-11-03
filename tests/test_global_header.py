import re
from pathlib import Path

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse

ROOT = Path(__file__).resolve().parents[1]


class GlobalHeaderTests(TestCase):
    def render_for_path(self, path):
        request = RequestFactory().get(path)
        request.resolver_match = resolve(path)
        return render_to_string("base.html", request=request)

    def test_header_exposes_only_the_approved_global_routes(self):
        html = self.render_for_path(reverse("clientes_agenda:clientes"))

        approved_routes = {
            "clientes": reverse("clientes_agenda:clientes"),
            "projetos": reverse("kanban_projetos:kanban_readonly"),
            "a_receber": reverse("financeiro:central_contas_receber"),
            "rentabilidade": reverse("financeiro:rentabilidade_projetos"),
        }
        for href in approved_routes.values():
            self.assertIn(f'href="{href}"', html)

        for forbidden_fragment in (
            "despesas-recorrentes",
            "equipe",
            "calendario",
            "fechamento",
            "backup",
            "export",
            "propostas",
            "dashboard",
        ):
            self.assertNotIn(forbidden_fragment, html.lower())

    def test_approved_routes_resolve_without_a_404(self):
        for path in (
            reverse("clientes_agenda:clientes"),
            reverse("kanban_projetos:kanban_readonly"),
            reverse("financeiro:central_contas_receber"),
            reverse("financeiro:rentabilidade_projetos"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_active_state_uses_resolved_route_names_for_each_area(self):
        cases = (
            (reverse("clientes_agenda:clientes"), reverse("clientes_agenda:clientes")),
            (
                reverse("kanban_projetos:kanban_readonly"),
                reverse("kanban_projetos:kanban_readonly"),
            ),
            (
                reverse("financeiro:central_contas_receber"),
                reverse("financeiro:central_contas_receber"),
            ),
            (
                reverse("financeiro:rentabilidade_projetos"),
                reverse("financeiro:rentabilidade_projetos"),
            ),
        )
        for path, active_href in cases:
            html = self.render_for_path(path)
            active_link = f'href="{active_href}"'
            self.assertRegex(
                html,
                rf'{re.escape(active_link)}[^>]*aria-current="page"',
            )

    def test_rentabilidade_detail_keeps_financeiro_context_active(self):
        path = reverse("financeiro:rentabilidade_projeto", kwargs={"projeto_id": 42})
        html = self.render_for_path(path)

        self.assertRegex(
            html,
            rf'href="{re.escape(reverse("financeiro:rentabilidade_projetos"))}"[^>]*aria-current="page"',
        )
        self.assertIn('data-global-finance-active="true"', html)

    def test_mobile_menu_contract_has_semantic_controls_and_keyboard_close(self):
        html = self.render_for_path(reverse("clientes_agenda:clientes"))

        self.assertIn('id="global-navigation"', html)
        self.assertIn('aria-controls="global-navigation"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("NAVEGAÇÃO GLOBAL", html)
        self.assertIn('type="button"', html)
        self.assertIn('global_header.js', html)

    def test_mobile_button_accessible_name_contains_visible_label(self):
        html = self.render_for_path(reverse("clientes_agenda:clientes"))
        button = re.search(r"<button\b[\s\S]*?</button>", html)

        self.assertIsNotNone(button)
        self.assertNotIn("aria-label=", button.group(0))
        self.assertIn(">Menu</span>", button.group(0))

    def test_escape_closes_desktop_finance_and_returns_focus(self):
        javascript = (ROOT / "static/core_sistema/global_header.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('if (finance?.open)', javascript)
        self.assertIn("finance.open = false", javascript)
        self.assertIn("financeTrigger?.focus()", javascript)
        self.assertIn("toggle.focus()", javascript)

    def test_profitability_detail_preserves_context_and_back_link(self):
        detail = (ROOT / "templates/financeiro/rentabilidade_projeto.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("Voltar para todos os projetos", detail)
        self.assertIn("financeiro:rentabilidade_projetos", detail)

    def test_legacy_header_nav_overrides_are_removed(self):
        legacy_templates = (
            "templates/clientes_agenda/cliente_360.html",
            "templates/clientes_agenda/clientes.html",
            "templates/financeiro/rentabilidade_projeto.html",
            "templates/financeiro/rentabilidade_projetos.html",
            "templates/kanban_projetos/kanban_readonly.html",
        )

        for template_path in legacy_templates:
            template = (ROOT / template_path).read_text(encoding="utf-8")
            self.assertNotIn("{% block header_nav %}", template_path + template)

    def test_header_css_prevents_header_sourced_horizontal_overflow(self):
        css = (ROOT / "static/core_sistema/global_header.css").read_text(encoding="utf-8")

        self.assertNotIn("width: 100vw", css)
        self.assertIn("overflow-x: clip", css)
