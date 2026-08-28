import odoo

from odoo import api
from odoo.addons.workflow_studio.controllers.main import WebStudioController
from odoo.exceptions import ValidationError
from odoo.http import _request_stack
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import DotDict


@tagged("ws_patch")
class TestWorkflowStudioRequiredDomainGuardrails(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env = api.Environment(self.cr, odoo.SUPERUSER_ID, {"load_all_views": True})
        _request_stack.push(self)
        self.session = DotDict({"debug": ""})
        self.controller = WebStudioController()
        self.target_model = self.env["ir.model"]._get("res.partner")
        self.form_view = self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.guardrails.partner.form",
                "type": "form",
                "model": "res.partner",
                "arch": "<form><field name='name'/></form>",
            }
        )

    def tearDown(self):
        _request_stack.pop()
        super().tearDown()

    def update_context(self, **overrides):
        self.env = self.env(context=dict(self.env.context, **overrides))

    def _create_publish_version(self, name):
        category = self.env["workflow.approval.category"].create(
            {
                "name": name,
                "res_model": self.target_model.id,
            }
        )
        return self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
            }
        )

    def test_edit_view_strips_required_domain_in_options(self):
        required_domain = "[('wf_action_key', 'ilike', 'approve')]"
        self.controller.edit_view(
            self.form_view.id,
            "<data/>",
            operations=[
                {
                    "type": "attributes",
                    "position": "attributes",
                    "target": {"tag": "field", "attrs": {"name": "name"}},
                    "new_attrs": {
                        "widget": "wf_field",
                        "options": {
                            "wf_visible_domain": "[('wf_actor_uid', '!=', 0)]",
                            "wf_required_domain": required_domain,
                        },
                    },
                }
            ],
            model="res.partner",
        )

        studio_view = self.controller._get_studio_view(self.form_view)
        arch_db = studio_view.arch_db if studio_view else ""
        self.assertNotIn("wf_policy_id", arch_db)
        self.assertNotIn("wf_required_domain", arch_db)
        self.assertNotIn("wf_visible_domain", arch_db)

    def test_edit_view_accepts_required_domain_key_even_when_empty(self):
        self.controller.edit_view(
            self.form_view.id,
            "<data/>",
            operations=[
                {
                    "type": "attributes",
                    "position": "attributes",
                    "target": {"tag": "field", "attrs": {"name": "name"}},
                    "new_attrs": {
                        "widget": "wf_field",
                        "options": {
                            "wf_visible_domain": "[('wf_actor_uid', '!=', 0)]",
                            "wf_required_domain": "",
                        },
                    },
                }
            ],
            model="res.partner",
        )

        studio_view = self.controller._get_studio_view(self.form_view)
        arch_db = studio_view.arch_db if studio_view else ""
        self.assertNotIn("wf_required_domain", arch_db)
        self.assertNotIn("wf_visible_domain", arch_db)

    def test_edit_view_strips_required_domain_in_policy_payload(self):
        required_domain = "[('wf_action_key', 'ilike', 'approve')]"
        self.controller.edit_view(
            self.form_view.id,
            "<data/>",
            operations=[
                {
                    "type": "attributes",
                    "position": "attributes",
                    "target": {"tag": "field", "attrs": {"name": "name"}},
                    "new_attrs": {
                        "widget": "wf_field",
                        "wf_policy_domains": {
                            "visible": "[('wf_actor_uid', '!=', 0)]",
                            "required": required_domain,
                        },
                    },
                }
            ],
            model="res.partner",
        )

        studio_view = self.controller._get_studio_view(self.form_view)
        arch_db = studio_view.arch_db if studio_view else ""
        self.assertNotIn("wf_policy_domains", arch_db)
        self.assertNotIn("wf_policy_id", arch_db)

    def test_edit_view_rejects_oversized_inline_domain(self):
        huge = "x" * 1500
        with self.assertRaises(ValidationError):
            self.controller.edit_view(
                self.form_view.id,
                "<data/>",
                operations=[
                    {
                        "type": "attributes",
                        "position": "attributes",
                        "target": {"tag": "field", "attrs": {"name": "name"}},
                        "new_attrs": {
                            "widget": "wf_field",
                            "options": {
                                "wf_visible_domain": f"[('wf_actor_login', 'ilike', '{huge}')]",
                            },
                        },
                    }
                ],
                model="res.partner",
            )

    def test_publish_accepts_required_domain_in_form_arch(self):
        version = self._create_publish_version("Guardrail Publish Required Attr")
        self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.guardrails.publish.required.attr",
                "type": "form",
                "model": "res.partner",
                "arch": (
                    "<form>"
                    "<field name='name' widget='wf_field' "
                    "wf_required_domain=\"[('wf_action_key', '=', 'approve')]\"/>"
                    "</form>"
                ),
            }
        )

        version.workflow_studio_publish_version()

    def test_publish_accepts_required_domain_key_even_when_empty(self):
        version = self._create_publish_version("Guardrail Publish Required Empty Attr")
        self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.guardrails.publish.required.empty.attr",
                "type": "form",
                "model": "res.partner",
                "arch": (
                    "<form>"
                    "<field name='name' widget='wf_field' wf_required_domain=\"\"/>"
                    "</form>"
                ),
            }
        )

        version.workflow_studio_publish_version()

    def test_publish_ignores_stale_policy_id_in_form_arch(self):
        version = self._create_publish_version("Guardrail Publish Stale Policy Attr")
        self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.guardrails.publish.stale.policy.attr",
                "type": "form",
                "model": "res.partner",
                "arch": "<form><field name='name' widget='wf_field' wf_policy_id='999999'/></form>",
            }
        )

        version.workflow_studio_publish_version()

    def test_publish_rejects_oversized_inline_visible_domain(self):
        version = self._create_publish_version("Guardrail Publish Oversized Domain")
        huge = "x" * 1500
        self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.guardrails.publish.oversized",
                "type": "form",
                "model": "res.partner",
                "arch": (
                    "<form>"
                    "<field name='name' widget='wf_field' "
                    f"wf_visible_domain=\"[('wf_actor_login', 'ilike', '{huge}')]\"/>"
                    "</form>"
                ),
            }
        )

        with self.assertRaises(ValidationError):
            version.workflow_studio_publish_version()
