import inspect
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import common


class TestWorkflowRuntimeGuardDialog(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.env["workflow.approval.category"].sudo().create(
            {
                "name": "Runtime Guard Dialog Test",
                "res_model": request_model.id,
            }
        )
        cls.version = cls.env["workflow.approval.category.version"].sudo().create(
            {
                "name": "v_guard_dialog",
                "category_id": cls.category.id,
                "is_active": True,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})
        cls.task = cls.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Review",
                "node_id": "Task_Review",
                "node_type": "userTask",
            }
        )
        cls.end_task = cls.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Done",
                "node_id": "Event_Done",
                "node_type": "endEvent",
            }
        )
        cls.action = cls.env["workflow.category.version.meta.task.action"].sudo().create(
            {
                "name": "Approve",
                "meta_task_id": cls.task.id,
                "version_id": cls.version.id,
                "node_id": "Flow_Review_Done",
                "source_id": cls.task.node_id,
                "source_name": cls.task.name,
                "source_node_type": cls.task.node_type,
                "target_id": cls.end_task.node_id,
                "target_name": cls.end_task.name,
                "target_node_type": cls.end_task.node_type,
                "domain": "[('name', '=', 'DOES_NOT_MATCH')]",
            }
        )
        cls.request = cls.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_GUARD_DIALOG",
                "category_id": cls.category.id,
                "request_owner_id": cls.env.user.id,
                "current_node_id": cls.task.node_id,
                "current_iteration_no": 1,
            }
        )

    def test_guard_dialog_is_read_only_and_has_no_side_effects(self):
        self.action.sudo().write(
            {
                "show_validation_dialog": True,
                "validation_message": "<p><strong>Morning work shift only.</strong></p>",
            }
        )
        current_node_id = self.request.current_node_id

        with patch.object(type(self.request), "_run_engine", autospec=True) as run_engine:
            result = self.request._workflow_action_execution_guard_failure_action(
                self.action,
                show_dialog=True,
            )

        validation_view = self.env.ref(
            "workflow_engine.view_workflow_validation_dialog_form"
        )
        self.assertEqual(result["type"], "ir.actions.act_window")
        self.assertEqual(result["res_model"], "workflow.confirm.wizard")
        self.assertEqual(result["view_id"], validation_view.id)
        self.assertEqual(result["views"], [(validation_view.id, "form")])
        self.assertEqual(result["name"], "Validation Message")
        self.assertIn(
            "<strong>Morning work shift only.</strong>",
            str(result["context"]["default_confirm_message"]),
        )
        self.assertNotIn("meta_action_id", result["context"])
        self.assertNotIn("default_res_id", result["context"])
        self.assertFalse(run_engine.called)
        self.request.invalidate_recordset(["current_node_id"])
        self.assertEqual(self.request.current_node_id, current_node_id)

    def test_guard_dialog_does_not_weaken_non_ui_enforcement(self):
        self.action.sudo().write(
            {
                "show_validation_dialog": True,
                "validation_message": "<p><strong>Morning work shift only.</strong></p>",
            }
        )

        with self.assertRaisesRegex(UserError, "Morning work shift only"):
            self.request._workflow_action_execution_guard_failure_action(
                self.action,
                show_dialog=False,
            )
        with self.assertRaisesRegex(UserError, "Morning work shift only"):
            self.request._workflow_validate_action_execution_guard(self.action)

    def test_guard_dialog_is_opt_in(self):
        defaults = self.env[
            "workflow.category.version.meta.task.action"
        ].default_get(["show_validation_dialog"])
        self.assertFalse(defaults.get("show_validation_dialog"))

        self.action.sudo().write(
            {"validation_message": "<p>Configured but not opted in.</p>"}
        )
        with self.assertRaisesRegex(UserError, "Configured but not opted in"):
            self.request._workflow_action_execution_guard_failure_action(
                self.action,
                show_dialog=True,
            )

    def test_interactive_transition_uses_guard_failure_handler_first(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import (
            ApprovalChildMixin,
        )

        source = inspect.getsource(ApprovalChildMixin.action_do_transition)
        guard_index = source.find("_workflow_action_execution_guard_failure_action")
        confirm_index = source.find("_workflow_should_open_confirmation_dialog")
        twofa_index = source.find("action_requires_twofactor")
        run_index = source.find("._run_engine(")

        self.assertGreaterEqual(guard_index, 0)
        self.assertGreaterEqual(confirm_index, 0)
        self.assertGreaterEqual(twofa_index, 0)
        self.assertGreaterEqual(run_index, 0)
        self.assertLess(guard_index, confirm_index)
        self.assertLess(guard_index, twofa_index)
        self.assertLess(guard_index, run_index)

    def test_validation_message_is_sanitized(self):
        self.action.sudo().write(
            {
                "validation_message": (
                    '<p class="custom" style="color: blue" onclick="alert(1)">'
                    "<strong>Safe text</strong><script>alert(2)</script></p>"
                )
            }
        )
        stored = str(self.action.validation_message)
        self.assertIn("<strong>Safe text</strong>", stored)
        self.assertNotIn("onclick", stored)
        self.assertNotIn("style=", stored)
        self.assertNotIn("class=", stored)
        self.assertNotIn("<script", stored)

    def test_validation_dialog_view_has_close_only(self):
        view = self.env.ref("workflow_engine.view_workflow_validation_dialog_form")
        arch = etree.fromstring(view.arch_db.encode())
        self.assertEqual(arch.get("string"), "Validation Message")
        self.assertFalse(arch.xpath(".//button[@name='action_confirm']"))
        self.assertTrue(arch.xpath(".//button[@special='cancel']"))
