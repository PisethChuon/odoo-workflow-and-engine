# -*- coding: utf-8 -*-

from datetime import timedelta
import unittest
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.tests import common
from odoo.exceptions import ValidationError


class TestWorkflowFieldRenderLogic(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.MetaAction = cls.env["workflow.category.version.meta.task.action"]
        cls.MetaField = cls.env["workflow.category.version.meta.field"]
        cls.View = cls.env["ir.ui.view"]
        cls.DefaultVisibleField = cls.env["workflow.default.visible.field"]

        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        unique = uuid4().hex[:8]

        def _new_user(name_prefix):
            return cls.User.with_context(no_reset_password=True).create(
                {
                    "name": f"{name_prefix} {unique}",
                    "login": f"{name_prefix.lower()}_{unique}",
                    "email": f"{name_prefix.lower()}_{unique}@example.com",
                    "group_ids": [(6, 0, [workflow_group.id])],
                }
            )

        cls.runtime_user = _new_user("runtime")
        cls.other_user = _new_user("other")
        cls.it_department = cls.env["hr.department"].create({"name": f"IT {unique}"})
        cls.env["hr.employee"].sudo().create(
            {
                "name": cls.runtime_user.name,
                "user_id": cls.runtime_user.id,
                "department_id": cls.it_department.id,
            }
        )
        cls.runtime_user.write({"department_id": cls.it_department.id})

        model_ref = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.sudo().create(
            {
                "name": f"WF Field Logic {unique}",
                "res_model": model_ref.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [(6, 0, [cls.runtime_user.id, cls.other_user.id])],
            }
        )
        cls.version = cls.Version.sudo().create(
            {
                "name": f"v_{unique}",
                "category_id": cls.category.id,
                "is_active": True,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})

        cls.meta_task = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Review",
                "node_id": "Task_Review",
                "node_type": "userTask",
            }
        )
        cls.meta_task_branch_a = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Branch A",
                "node_id": "Task_Branch_A",
                "node_type": "userTask",
            }
        )
        cls.meta_task_branch_b = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Branch B",
                "node_id": "Task_Branch_B",
                "node_type": "userTask",
            }
        )
        cls.meta_task_end = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Done",
                "node_id": "Task_End",
                "node_type": "endEvent",
            }
        )
        cls.meta_action_submit = cls.MetaAction.sudo().create(
            {
                "name": "Submit",
                "meta_task_id": cls.meta_task.id,
                "source_id": cls.meta_task.node_id,
                "source_name": cls.meta_task.name,
                "source_node_type": cls.meta_task.node_type,
                "target_id": "Task_End",
                "target_name": "Done",
                "target_node_type": "endEvent",
                "node_id": f"Flow_Submit_{unique}",
                "version_id": cls.version.id,
            }
        )

        request_model_fields = cls.env["ir.model.fields"]
        cls.name_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "name")],
            limit=1,
        )
        note_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )
        cls.note_field = note_field
        readonly_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "request_owner_id")],
            limit=1,
        )
        cls.request_owner_field = readonly_field
        visible_field_names = [
            "name",
            "note",
            "comment",
            "request_owner_id",
            "approval_type",
            "category_id",
        ]
        visible_fields = request_model_fields.search(
            [
                ("model", "=", "workflow.base.approval.request"),
                ("name", "in", visible_field_names),
            ]
        )
        for field in visible_fields:
            cls.MetaField.sudo().create(
                {
                    "meta_id": cls.meta_task.id,
                    "field_id": field.id,
                    "field_type": "visible",
                }
            )
        cls.MetaField.sudo().create(
            {
                "meta_id": cls.meta_task.id,
                "field_id": note_field.id,
                "field_type": "required",
                "activity_action_ids": [(6, 0, [cls.meta_action_submit.id])],
            }
        )
        cls.MetaField.sudo().create(
            {
                "meta_id": cls.meta_task.id,
                "field_id": readonly_field.id,
                "field_type": "readonly",
            }
        )

        cls.request = cls.Request.sudo().create(
            {
                "name": "REQ Visible",
                "category_id": cls.category.id,
                "request_owner_id": cls.runtime_user.id,
                "current_node_id": cls.meta_task.node_id,
                "comment": "baseline",
            }
        )

        cls.runtime_form_view = cls.View.sudo().create(
            {
                "name": f"wf.runtime.policy.{unique}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Runtime Policy" js_class="wf_form">
    <sheet>
        <group>
            <field name="name" options="{'wf_visible_domain': &quot;[('name', 'ilike', 'REQ')]&quot;}"/>
            <field name="note" options="{'wf_required_domain': &quot;[('wf_action_key', 'ilike', 'submit')]&quot;}"/>
            <field name="comment" options="{'wf_required_domain': &quot;[('wf_current_node_id', '!=', False)]&quot;}"/>
            <field name="request_owner_id" options="{'wf_readonly_domain': &quot;[('wf_actor_department_name', 'ilike', 'it')]&quot;}"/>
            <field name="approval_type" widget="wf_field" options="{'wf_visible_domain': &quot;[('wf_current_node_id', '=', 'Task_Review')]&quot;}"/>
            <field name="category_id" widget="wf_field" options="{'wf_visible_domain': &quot;[('wf_current_node_id', '=', 'Task_Review')]&quot;, 'wf_readonly_domain': &quot;[('wf_actor_department_name', 'ilike', 'it')]&quot;}"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )

        cls.runtime_form_view_db = cls.View.sudo().create(
            {
                "name": f"wf.runtime.policy.db.{unique}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Runtime Policy DB" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="category_id" widget="wf_field"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )

    def setUp(self):
        super().setUp()
        self.request = self.request.with_context(workflow_skip_edit_scope=True)
        self.request.approver_ids.sudo().unlink()
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "name": "REQ Visible",
                "comment": "baseline",
                "note": False,
                "request_owner_id": self.runtime_user.id,
                "current_node_id": self.meta_task.node_id,
                "active_branch_node_ids": [],
            }
        )

    def _runtime_payload(self, action_key, view=False):
        payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
            action_key=action_key,
            task_node_id=self.meta_task.node_id,
            view_id=(view.id if view else self.runtime_form_view.id),
            meta_action_id=self.meta_action_submit.id,
        )
        return payload

    def _runtime_payload_for_user(self, user, action_key, view):
        return self.env["workflow.engine.field.rule.service"].sudo().evaluate_runtime_field_state_map(
            target_record=self.request.sudo(),
            request_record=self.request.sudo(),
            action_key=action_key,
            task_node_id=self.meta_task.node_id,
            view_id=view.id,
            user=user,
        )

    def _grant_runtime_edit_access(self, meta_task=False):
        meta_task = meta_task or self.meta_task
        return self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": meta_task.id,
                "previous_meta_id": meta_task.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

    def _assert_runtime_field_state_contract(self, payload, field_names=None):
        field_map = payload.get("field_state_map") or {}
        required_fields = set(payload.get("required_fields") or [])
        readonly_fields = set(payload.get("readonly_fields") or [])
        invisible_fields = set(payload.get("invisible_fields") or [])
        checked_names = set(field_names or field_map.keys())

        for field_name in checked_names:
            self.assertIn(field_name, field_map)
            state = field_map[field_name]
            is_invisible = bool(state.get("invisible"))
            is_readonly = bool(state.get("readonly"))
            is_required = bool(state.get("required"))

            self.assertEqual(field_name in invisible_fields, is_invisible)
            self.assertEqual(field_name in readonly_fields, is_readonly)
            self.assertEqual(field_name in required_fields, is_required)

            if is_invisible:
                self.assertTrue(
                    is_readonly,
                    "%s is invisible, so it must also be readonly for safe form rendering." % field_name,
                )
                self.assertFalse(
                    is_required,
                    "%s is invisible, so it must not remain required." % field_name,
                )
            if is_readonly:
                self.assertFalse(
                    is_required,
                    "%s is readonly, so it must not remain required." % field_name,
                )

    def test_meta_visible_fields_make_current_view_fields_hidden_by_default(self):
        request_model_fields = self.env["ir.model.fields"]
        name_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "name")],
            limit=1,
        )
        note_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )

        created_fields = self.env["workflow.category.version.meta.field"]
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.allowlist.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
            <field name="request_owner_id"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": name_field.id,
                    "field_type": "visible",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": note_field.id,
                    "field_type": "visible",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": note_field.id,
                    "field_type": "required",
                }
            )

            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_a.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertFalse(field_map["name"]["invisible"])
            self.assertFalse(field_map["note"]["invisible"])
            self.assertTrue(field_map["note"]["required"])
            self.assertNotIn("comment", field_map)
            self.assertNotIn("request_owner_id", field_map)
            self.assertNotIn("comment", payload.get("invisible_fields") or [])
            self.assertNotIn("request_owner_id", payload.get("invisible_fields") or [])
        finally:
            created_fields.unlink()
            allowlist_view.unlink()

    def test_meta_visible_allowlist_empty_node_hides_current_view_fields_by_default(self):
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.empty.allowlist.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Empty Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertTrue(field_map["name"]["invisible"])
            self.assertTrue(field_map["note"]["invisible"])
            self.assertNotIn("comment", field_map)
            self.assertIn("name", payload.get("invisible_fields") or [])
            self.assertIn("note", payload.get("invisible_fields") or [])
            self.assertNotIn("comment", payload.get("invisible_fields") or [])
        finally:
            allowlist_view.unlink()

    def test_terminal_end_node_meta_fields_show_configured_fields_readonly(self):
        end_rules = self.MetaField.sudo().create(
            [
                {
                    "meta_id": self.meta_task_end.id,
                    "field_id": self.name_field.id,
                    "field_type": "visible",
                },
                {
                    "meta_id": self.meta_task_end.id,
                    "field_id": self.name_field.id,
                    "field_type": "readonly",
                },
            ]
        )
        try:
            self.request.with_context(workflow_skip_field_policy=True).sudo().write(
                {
                    "current_node_id": self.meta_task_end.node_id,
                    "state": "completed",
                    "request_status": "approved",
                    "active_branch_node_ids": [],
                }
            )

            payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
                action_key=False,
                task_node_id=False,
                view_id=self.runtime_form_view_db.id,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertEqual(payload.get("meta", {}).get("task_node_id"), self.meta_task_end.node_id)
            self.assertIn("name", field_map)
            self.assertFalse(
                field_map["name"]["invisible"],
                "Explicit end-node visible config should keep the field visible after completion.",
            )
            self.assertTrue(
                field_map["name"]["readonly"],
                "Completed end-node forms must expose configured fields as readonly.",
            )
            self.assertNotIn("name", payload.get("invisible_fields") or [])
            self.assertIn("name", payload.get("readonly_fields") or [])
        finally:
            end_rules.unlink()

    def test_terminal_end_node_without_meta_visible_config_keeps_strict_allowlist(self):
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "current_node_id": self.meta_task_end.node_id,
                "state": "completed",
                "request_status": "approved",
                "active_branch_node_ids": [],
            }
        )

        payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
            action_key=False,
            task_node_id=False,
            view_id=self.runtime_form_view_db.id,
        )
        field_map = payload.get("field_state_map") or {}

        self.assertEqual(payload.get("meta", {}).get("task_node_id"), self.meta_task_end.node_id)
        self.assertIn("name", field_map)
        self.assertTrue(
            field_map["name"]["invisible"],
            "End nodes without explicit visible config must keep strict allowlist behavior.",
        )
        self.assertIn("name", payload.get("invisible_fields") or [])

    def test_meta_visible_allowlist_preserves_workflow_progress_fields(self):
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.progress.allowlist.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Progress Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
        </group>
        <group name="request_status" string="Workflow Progress">
            <group>
                <field name="previous_activity_name" invisible="0"/>
                <field name="current_activity_name"/>
                <field name="wf_block_badge" invisible="not wf_is_blocked"/>
                <field name="wf_block_reason" invisible="not wf_is_blocked"/>
                <field name="branch_mode" invisible="not active_branch_node_ids"/>
            </group>
            <group>
                <field name="request_status"/>
                <field name="branch_progress_summary" invisible="not active_branch_node_ids"/>
                <field name="branch_active_count" invisible="not active_branch_node_ids"/>
            </group>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}
            invisible_fields = set(payload.get("invisible_fields") or [])
            progress_fields = {
                "previous_activity_name",
                "current_activity_name",
                "wf_block_badge",
                "wf_block_reason",
                "branch_mode",
                "request_status",
                "branch_progress_summary",
                "branch_active_count",
            }

            self.assertTrue(field_map["name"]["invisible"])
            self.assertFalse(progress_fields & set(field_map))
            self.assertFalse(progress_fields & invisible_fields)
        finally:
            allowlist_view.unlink()

    def test_configured_default_visible_field_is_not_hidden_by_allowlist(self):
        note_field = self.env["ir.model.fields"].search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )
        configured_field = self.DefaultVisibleField.sudo().create({"field_id": note_field.id})
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.configured.allowlist.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Configured Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}
            invisible_fields = set(payload.get("invisible_fields") or [])

            self.assertTrue(field_map["name"]["invisible"])
            self.assertNotIn("note", field_map)
            self.assertNotIn("comment", field_map)
            self.assertNotIn("note", invisible_fields)
            self.assertNotIn("comment", invisible_fields)
        finally:
            configured_field.unlink()
            allowlist_view.unlink()

    def test_configured_default_visible_field_is_model_specific(self):
        partner_name_field = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "=", "name")],
            limit=1,
        )
        configured_field = self.DefaultVisibleField.sudo().create(
            {"field_id": partner_name_field.id}
        )
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.model.specific.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Model Specific Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="comment"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertTrue(field_map["name"]["invisible"])
            self.assertNotIn("comment", field_map)
        finally:
            configured_field.unlink()
            allowlist_view.unlink()

    def test_explicit_invisible_rule_hides_configured_default_visible_field(self):
        note_field = self.env["ir.model.fields"].search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )
        configured_field = self.DefaultVisibleField.sudo().create({"field_id": note_field.id})
        invisible_rule = self.MetaField.sudo().create(
            {
                "meta_id": self.meta_task_branch_b.id,
                "field_id": note_field.id,
                "field_type": "invisible",
            }
        )
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.configured.invisible.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Configured Invisible Override" js_class="wf_form">
    <sheet>
        <group>
            <field name="note"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=allowlist_view.id,
                user=self.runtime_user,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertTrue(field_map["note"]["invisible"])
            self.assertIn("note", payload.get("invisible_fields") or [])
        finally:
            invisible_rule.unlink()
            configured_field.unlink()
            allowlist_view.unlink()

    def test_predefined_default_visible_fields_are_created_idempotently(self):
        predefined_names = set(
            self.DefaultVisibleField._PREDEFINED_DEFAULT_VISIBLE_FIELDS[
                "workflow.base.approval.request"
            ]
        )
        self.DefaultVisibleField.sudo().ensure_predefined_default_visible_fields()
        records = self.DefaultVisibleField.sudo().with_context(active_test=False).search(
            [
                ("model", "=", "workflow.base.approval.request"),
                ("field_name", "in", list(predefined_names)),
            ]
        )
        found_names = set(records.mapped("field_name"))

        self.assertEqual(predefined_names, found_names)
        self.assertTrue(all(records.mapped("is_predefined")))

        count_before = self.DefaultVisibleField.sudo().with_context(active_test=False).search_count(
            [
                ("model", "=", "workflow.base.approval.request"),
                ("field_name", "in", list(predefined_names)),
            ]
        )
        self.DefaultVisibleField.sudo().ensure_predefined_default_visible_fields()
        count_after = self.DefaultVisibleField.sudo().with_context(active_test=False).search_count(
            [
                ("model", "=", "workflow.base.approval.request"),
                ("field_name", "in", list(predefined_names)),
            ]
        )
        self.assertEqual(count_before, count_after)

    def test_meta_visible_allowlist_applies_to_draft_before_current_node(self):
        request_model_fields = self.env["ir.model.fields"]
        name_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "name")],
            limit=1,
        )
        note_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )

        created_fields = self.env["workflow.category.version.meta.field"]
        allowlist_view = self.View.sudo().create(
            {
                "name": f"wf.visible.draft.allowlist.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Draft Visible Allowlist" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task.id,
                    "field_id": name_field.id,
                    "field_type": "visible",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task.id,
                    "field_id": note_field.id,
                    "field_type": "visible",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task.id,
                    "field_id": note_field.id,
                    "field_type": "required",
                }
            )
            self.request.with_context(
                workflow_skip_edit_scope=True,
                workflow_skip_field_policy=True,
            ).sudo().write(
                {
                    "state": "draft",
                    "current_node_id": False,
                    "active_branch_node_ids": [],
                }
            )

            payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
                view_id=allowlist_view.id,
                task_node_id=False,
                meta_action_id=False,
                action_key=False,
            )
            field_map = payload.get("field_state_map") or {}

            self.assertEqual(payload.get("meta", {}).get("task_node_id"), self.meta_task.node_id)
            self.assertFalse(field_map["name"]["invisible"])
            self.assertFalse(field_map["note"]["invisible"])
            self.assertTrue(field_map["note"]["required"])
            self.assertFalse(
                field_map["comment"]["invisible"],
                "The shared fixture explicitly configures comment as visible on the main user task.",
            )

            request_as_actor = self.request.with_user(self.runtime_user)
            request_as_actor.invalidate_recordset(["required_fields", "readonly_fields", "invisible_fields"])
            self.assertIn(
                "note",
                request_as_actor.required_fields or [],
                "Initial draft render should use the first user-action node for computed field lists.",
            )
        finally:
            created_fields.unlink()
            allowlist_view.unlink()

    def test_meta_field_domains_apply_from_snapshot_and_actor_context(self):
        request_model_fields = self.env["ir.model.fields"]
        name_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "name")],
            limit=1,
        )
        note_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )
        request_owner_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "request_owner_id")],
            limit=1,
        )

        created_fields = self.env["workflow.category.version.meta.field"]
        domain_view = self.View.sudo().create(
            {
                "name": f"wf.meta.domain.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Meta Domains" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
            <field name="request_owner_id"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": name_field.id,
                    "field_type": "visible",
                    "domain": "[('comment', '=', 'Casino Application')]",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": note_field.id,
                    "field_type": "visible",
                    "domain": "[]",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": note_field.id,
                    "field_type": "invisible",
                    "domain": "[('comment', '=', 'Office Application')]",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": note_field.id,
                    "field_type": "required",
                    "domain": "[('comment', '=', 'Casino Application')]",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": request_owner_field.id,
                    "field_type": "visible",
                    "domain": "[]",
                }
            )
            created_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": request_owner_field.id,
                    "field_type": "readonly",
                    "domain": "[('wf_actor_uid', '=', %s)]" % self.runtime_user.id,
                }
            )

            service = self.env["workflow.engine.field.rule.service"].with_user(self.runtime_user)
            non_matching_payload = service.evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_a.node_id,
                action_key="submit",
                view_id=domain_view.id,
                user=self.runtime_user,
                snapshot_values={"comment": "Office Application"},
            )
            matching_payload = service.evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_a.node_id,
                action_key="submit",
                view_id=domain_view.id,
                user=self.runtime_user,
                snapshot_values={"comment": "Casino Application"},
            )

            self.assertTrue(non_matching_payload["field_state_map"]["name"]["invisible"])
            self.assertTrue(non_matching_payload["field_state_map"]["note"]["invisible"])
            self.assertFalse(non_matching_payload["field_state_map"]["note"]["required"])
            self.assertFalse(matching_payload["field_state_map"]["name"]["invisible"])
            self.assertFalse(matching_payload["field_state_map"]["note"]["invisible"])
            self.assertTrue(matching_payload["field_state_map"]["note"]["required"])
            self.assertTrue(matching_payload["field_state_map"]["request_owner_id"]["readonly"])
        finally:
            created_fields.unlink()
            domain_view.unlink()

    def test_runtime_map_changes_per_action_key(self):
        submit_payload = self._runtime_payload("submit")
        reject_payload = self._runtime_payload("reject")

        submit_states = submit_payload["field_state_map"]
        reject_states = reject_payload["field_state_map"]

        self.assertFalse(submit_states["name"]["invisible"], "Name should be visible when name-domain matches.")
        self.assertTrue(
            submit_states["note"]["required"],
            "Submit action must require note via action-scoped workflow rules.",
        )
        self.assertFalse(
            reject_states["note"]["required"],
            "Reject action must not require submit-only note policy.",
        )
        self.assertTrue(
            submit_states["request_owner_id"]["readonly"],
            "IT actor should receive readonly policy on request owner.",
        )
        self._assert_runtime_field_state_contract(submit_payload)
        self._assert_runtime_field_state_contract(reject_payload)

    def test_runtime_field_state_contract_normalizes_conflicting_meta_rules(self):
        comment_field = self.env["ir.model.fields"].search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "comment")],
            limit=1,
        )
        date_start_field = self.env["ir.model.fields"].search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "date_start")],
            limit=1,
        )
        contract_view = self.View.sudo().create(
            {
                "name": f"wf.runtime.contract.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Runtime Contract" js_class="wf_form">
    <sheet>
        <group>
            <field name="name"/>
            <field name="note"/>
            <field name="comment"/>
            <field name="date_start"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        created_fields = self.env["workflow.category.version.meta.field"]
        try:
            created_fields |= self.MetaField.sudo().create(
                [
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": self.name_field.id,
                        "field_type": "visible",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": self.name_field.id,
                        "field_type": "required",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": self.note_field.id,
                        "field_type": "visible",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": self.note_field.id,
                        "field_type": "required",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": self.note_field.id,
                        "field_type": "readonly",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": comment_field.id,
                        "field_type": "visible",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": comment_field.id,
                        "field_type": "required",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": comment_field.id,
                        "field_type": "invisible",
                    },
                    {
                        "meta_id": self.meta_task_branch_b.id,
                        "field_id": date_start_field.id,
                        "field_type": "required",
                    },
                ]
            )

            payload = self.env["workflow.engine.field.rule.service"].with_user(
                self.runtime_user
            ).evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                task_node_id=self.meta_task_branch_b.node_id,
                view_id=contract_view.id,
                user=self.runtime_user,
            )
            states = payload["field_state_map"]

            self.assertFalse(states["name"]["invisible"])
            self.assertFalse(states["name"]["readonly"])
            self.assertTrue(states["name"]["required"])
            self.assertFalse(states["note"]["invisible"])
            self.assertTrue(states["note"]["readonly"])
            self.assertFalse(states["note"]["required"])
            self.assertTrue(states["comment"]["invisible"])
            self.assertTrue(states["comment"]["readonly"])
            self.assertFalse(states["comment"]["required"])
            self.assertTrue(states["date_start"]["invisible"])
            self.assertTrue(states["date_start"]["readonly"])
            self.assertFalse(states["date_start"]["required"])
            self._assert_runtime_field_state_contract(
                payload,
                field_names={"name", "note", "comment", "date_start"},
            )
        finally:
            created_fields.unlink()
            contract_view.unlink()

    def test_virtual_and_saved_runtime_maps_share_field_state_contract(self):
        self._grant_runtime_edit_access()
        common_kwargs = {
            "action_key": "submit",
            "task_node_id": self.meta_task.node_id,
            "view_id": self.runtime_form_view.id,
        }
        saved_payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
            **common_kwargs
        )
        virtual_payload = self.Request.with_user(self.runtime_user).workflow_get_runtime_field_state_map_virtual(
            **common_kwargs,
            snapshot_values={
                "name": self.request.name,
                "category_id": {"id": self.category.id, "display_name": self.category.name},
                "version_id": {"id": self.version.id, "display_name": self.version.name},
                "request_owner_id": {
                    "id": self.runtime_user.id,
                    "display_name": self.runtime_user.name,
                },
                "current_node_id": self.meta_task.node_id,
                "wf_current_node_id": self.meta_task.node_id,
                "comment": self.request.comment,
            },
        )
        checked_fields = {"name", "note", "request_owner_id", "category_id"}

        self._assert_runtime_field_state_contract(saved_payload, checked_fields)
        self._assert_runtime_field_state_contract(virtual_payload, checked_fields)
        for field_name in checked_fields:
            self.assertEqual(
                saved_payload["field_state_map"][field_name],
                virtual_payload["field_state_map"][field_name],
                "%s runtime state must match between saved and unsaved forms." % field_name,
            )

    def test_runtime_cache_invalidation_with_write_date(self):
        self._grant_runtime_edit_access()
        before = self._runtime_payload("reject")["field_state_map"]
        self.assertFalse(before["name"]["invisible"])

        self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
            {"name": "Changed Visible Flag"}
        )
        after = self._runtime_payload("reject")["field_state_map"]
        self.assertFalse(
            after["name"]["invisible"],
            "Write-date cache invalidation must not make view-level domains affect Meta Field rendering.",
        )

    def test_server_enforcement_blocks_readonly_write(self):
        with self.assertRaises(ValidationError):
            self.request.with_user(self.runtime_user).with_context(
                view_id=self.runtime_form_view.id
            ).write({"request_owner_id": self.other_user.id})

    def test_server_enforcement_ignores_runtime_tracking_fields_in_user_write(self):
        approver = self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_task.id,
                "previous_meta_id": self.meta_task.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "active_branch_node_ids": [self.meta_task_branch_a.node_id],
                "branch_mode": "parallel",
            }
        )

        result = self.request.with_user(self.runtime_user).with_context(
            view_id=self.runtime_form_view.id
        ).write(
            {
                "name": "REQ Duplicate Submit",
                "active_branch_node_ids": [],
                "branch_mode": False,
                "approver_ids": [(5, 0, 0)],
            }
        )

        self.assertTrue(result)
        self.request.invalidate_recordset(["name", "active_branch_node_ids", "branch_mode", "approver_ids"])
        self.assertEqual(self.request.name, "REQ Duplicate Submit")
        self.assertEqual(
            self.request.active_branch_node_ids,
            [self.meta_task_branch_a.node_id],
            "User writes must ignore stale duplicated runtime branch payload.",
        )
        self.assertEqual(
            self.request.branch_mode,
            "parallel",
            "Engine-owned branch mode must not be overwritten by ordinary form saves.",
        )
        self.assertIn(
            approver,
            self.request.approver_ids,
            "Engine-owned approver rows must not be cleared by duplicated form payload.",
        )

    def test_stage_age_is_live_for_active_stage_and_frozen_after_close(self):
        approver = self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_task.id,
                "previous_meta_id": self.meta_task.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "current_node_id": self.meta_task.node_id,
                "current_iteration_no": approver.iteration_no or 1,
            }
        )

        entered_at = fields.Datetime.to_datetime(approver.create_date)

        with patch("odoo.fields.Datetime.now", return_value=entered_at + timedelta(minutes=5)):
            approver.invalidate_recordset(["stage_age_minutes", "stage_age_display"])
            self.assertEqual(
                approver.stage_age_minutes,
                5,
                "Open active stages must age forward from the current time.",
            )
            self.assertEqual(approver.stage_age_display, "5m")

        with patch("odoo.fields.Datetime.now", return_value=entered_at + timedelta(minutes=125)):
            approver.invalidate_recordset(["stage_age_minutes", "stage_age_display"])
            self.assertEqual(
                approver.stage_age_minutes,
                125,
                "Open active stages must recompute on subsequent reads.",
            )
            self.assertEqual(approver.stage_age_display, "2h 5m")

        approver.sudo().write({"user_decision": "Approve", "status": "closed"})
        closed_at = entered_at + timedelta(minutes=12)
        self.env.cr.execute(
            "UPDATE workflow_approval_approver SET write_date = %s WHERE id = %s",
            [closed_at, approver.id],
        )
        approver.invalidate_recordset(["write_date", "stage_age_minutes", "stage_age_display"])

        with patch("odoo.fields.Datetime.now", return_value=entered_at + timedelta(minutes=240)):
            approver.invalidate_recordset(["stage_age_minutes", "stage_age_display"])
            self.assertEqual(
                approver.stage_age_minutes,
                12,
                "Closed stages must keep the age reached at stage exit.",
            )
            self.assertEqual(approver.stage_age_display, "12m")

    def test_stage_age_domain_helpers_support_current_and_parallel_nodes(self):
        request = self.Request.sudo().create(
            {
                "name": "REQ Stage Age Domain",
                "category_id": self.category.id,
                "request_owner_id": self.runtime_user.id,
                "current_node_id": self.meta_task.node_id,
                "current_iteration_no": 1,
            }
        )
        current_row = self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.runtime_user.id,
                "request_id": request.id,
                "current_meta_id": self.meta_task.id,
                "previous_meta_id": self.meta_task.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": 1,
            }
        )
        branch_row = self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.runtime_user.id,
                "request_id": request.id,
                "current_meta_id": self.meta_task_branch_a.id,
                "previous_meta_id": self.meta_task_branch_a.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": 1,
            }
        )
        now = fields.Datetime.now()
        current_entered_at = fields.Datetime.to_datetime(now) - timedelta(minutes=90)
        branch_entered_at = fields.Datetime.to_datetime(now) - timedelta(days=2)
        self.env.cr.execute(
            "UPDATE workflow_approval_approver SET create_date = %s WHERE id = %s",
            [current_entered_at, current_row.id],
        )
        self.env.cr.execute(
            "UPDATE workflow_approval_approver SET create_date = %s WHERE id = %s",
            [branch_entered_at, branch_row.id],
        )
        request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "current_node_id": self.meta_task.node_id,
                "active_branch_node_ids": [self.meta_task_branch_a.node_id],
                "branch_mode": "parallel",
            }
        )
        request.invalidate_recordset(["approver_ids", "current_node_id", "active_branch_node_ids"])
        current_row.invalidate_recordset(["create_date"])
        branch_row.invalidate_recordset(["create_date"])

        with patch("odoo.fields.Datetime.now", return_value=fields.Datetime.to_datetime(now)):
            self.assertTrue(
                request.check_domain(
                    "[('wf_current_stage_age_minutes', '>=', 60)]",
                    task_node_id=self.meta_task.node_id,
                    user=self.runtime_user,
                )
            )
            self.assertFalse(
                request.check_domain(
                    "[('wf_current_stage_age_minutes', '>=', 1440)]",
                    task_node_id=self.meta_task.node_id,
                    user=self.runtime_user,
                )
            )
            self.assertTrue(
                request.check_domain(
                    "wf_has_active_node('Task_Branch_A') and wf_node_age_minutes('Task_Branch_A') >= 1440",
                    task_node_id=self.meta_task.node_id,
                    user=self.runtime_user,
                )
            )
            self.assertFalse(
                request.check_domain(
                    "wf_has_active_node('Task_Branch_B') and wf_node_age_minutes('Task_Branch_B') >= 1",
                    task_node_id=self.meta_task.node_id,
                    user=self.runtime_user,
                )
            )

    def test_server_enforcement_blocks_missing_required(self):
        self._grant_runtime_edit_access()
        required_rule = self.MetaField.sudo().create(
            {
                "meta_id": self.meta_task.id,
                "field_id": self.env["ir.model.fields"].search(
                    [("model", "=", "workflow.base.approval.request"), ("name", "=", "comment")],
                    limit=1,
                ).id,
                "field_type": "required",
            }
        )
        self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
            {"comment": False}
        )
        try:
            with self.assertRaises(ValidationError):
                self.request.with_user(self.runtime_user).with_context(
                    view_id=self.runtime_form_view.id
                ).write({"name": "REQ Something"})
        finally:
            required_rule.unlink()

    def test_server_enforcement_blocks_invisible_write(self):
        invisible_rule = self.MetaField.sudo().create(
            {
                "meta_id": self.meta_task.id,
                "field_id": self.note_field.id,
                "field_type": "invisible",
            }
        )
        try:
            with self.assertRaises(ValidationError):
                self.request.with_user(self.runtime_user).with_context(
                    view_id=self.runtime_form_view_db.id
                ).write({"note": "salary-should-stay-hidden"})
        finally:
            invisible_rule.unlink()

    def test_runtime_map_uses_actor_primary_branch_node_by_default(self):
        approver_model = self.env["workflow.approval.approver"].sudo()
        iteration_no = self.request.current_iteration_no or 1
        approver_model.create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_task_branch_b.id,
                "previous_meta_id": self.meta_task_branch_b.id,
                "status": "new",
                "sequence": 20,
                "iteration_no": iteration_no,
            }
        )
        approver_model.create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_task_branch_a.id,
                "previous_meta_id": self.meta_task_branch_a.id,
                "status": "new",
                "sequence": 5,
                "iteration_no": iteration_no,
            }
        )
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "current_node_id": self.meta_task.node_id,
                "active_branch_node_ids": [self.meta_task_branch_a.node_id, self.meta_task_branch_b.node_id],
            }
        )
        branch_visible_rule = self.MetaField.sudo().create(
            [
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": self.name_field.id,
                    "field_type": "visible",
                },
                {
                    "meta_id": self.meta_task_branch_a.id,
                    "field_id": self.name_field.id,
                    "field_type": "required",
                    "domain": f"[('wf_current_node_id', '=', '{self.meta_task_branch_a.node_id}')]",
                },
            ]
        )

        try:
            payload = self.request.with_user(self.runtime_user).workflow_get_runtime_field_state_map(
                action_key="submit",
                view_id=self.runtime_form_view_db.id,
                meta_action_id=False,
                task_node_id=False,
            )
        finally:
            branch_visible_rule.unlink()

        self.assertEqual(payload.get("meta", {}).get("task_node_id"), self.meta_task_branch_a.node_id)
        self.assertTrue(
            payload["field_state_map"]["name"]["required"],
            "Runtime map should evaluate wf_current_node_id from actor branch node, not base current_node_id.",
        )

    def test_actor_primary_falls_back_to_current_node_when_open_rows_are_stale(self):
        approver_model = self.env["workflow.approval.approver"].sudo()
        iteration_no = self.request.current_iteration_no or 1
        approver_model.create(
            {
                "user_id": self.runtime_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_task_branch_b.id,
                "previous_meta_id": self.meta_task_branch_b.id,
                "status": "new",
                "sequence": 1,
                "iteration_no": iteration_no,
            }
        )
        self.request.with_context(workflow_skip_field_policy=True).sudo().write(
            {
                "current_node_id": self.meta_task.node_id,
                "active_branch_node_ids": [],
            }
        )

        request_as_actor = self.request.with_user(self.runtime_user)
        self.assertFalse(
            request_as_actor._workflow_get_open_actor_node_ids(),
            "Stale node rows must not override action resolution.",
        )
        self.assertEqual(
            request_as_actor._workflow_get_actor_primary_node_id(),
            self.meta_task.node_id,
            "Actor node must fall back to runtime current_node_id when open rows are stale.",
        )

    def test_virtual_runtime_map_for_unsaved_snapshot(self):
        payload = self.Request.with_user(self.runtime_user).workflow_get_runtime_field_state_map_virtual(
            action_key="reject",
            task_node_id=self.meta_task.node_id,
            view_id=self.runtime_form_view.id,
            snapshot_values={
                "name": "REQ Visible",
                "category_id": {"id": self.category.id, "display_name": self.category.name},
                "version_id": {"id": self.version.id, "display_name": self.version.name},
                "wf_current_node_id": self.meta_task.node_id,
                "current_node_id": self.meta_task.node_id,
                "request_owner_id": {"id": self.runtime_user.id, "display_name": self.runtime_user.name},
            },
        )
        states = payload["field_state_map"]
        self.assertIn("name", states)
        self.assertFalse(states["name"]["invisible"])
        self.assertIn("note", states)
        self.assertFalse(
            states["note"]["required"],
            "Inline workflow view-domain options must not drive runtime rendering.",
        )

    def test_virtual_actor_ui_snapshot_for_unsaved_snapshot(self):
        payload = self.Request.with_user(self.runtime_user).workflow_get_actor_ui_snapshot_virtual(
            snapshot_values={
                "name": "REQ Visible",
                "category_id": {"id": self.category.id, "display_name": self.category.name},
                "version_id": {"id": self.version.id, "display_name": self.version.name},
                "wf_current_node_id": self.meta_task.node_id,
                "current_node_id": self.meta_task.node_id,
                "request_owner_id": {"id": self.runtime_user.id, "display_name": self.runtime_user.name},
            },
            task_node_id=self.meta_task.node_id,
        )
        self.assertIsInstance(payload, dict)
        self.assertIn("visible_buttons", payload)
        self.assertIn("is_user_has_permission", payload)
        self.assertIn("is_user_can_delegate", payload)

    def test_skip_context_alone_does_not_allow_runtime_tracking_write(self):
        stripped = self.request.with_user(self.runtime_user).with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
        )._workflow_strip_runtime_tracking_fields(
            {
                "current_node_id": self.meta_task_branch_a.node_id,
                "comment": "keep me",
            }
        )
        self.assertEqual(
            stripped,
            {"comment": "keep me"},
            "Leaked workflow skip context must not turn runtime fields into normal user writes.",
        )

    def test_explicit_runtime_tracking_flag_keeps_engine_owned_runtime_fields(self):
        stripped = self.request.with_user(self.runtime_user).with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_allow_runtime_tracking_write=True,
        )._workflow_strip_runtime_tracking_fields(
            {
                "current_node_id": self.meta_task_branch_a.node_id,
                "comment": "keep me",
            }
        )
        self.assertEqual(
            stripped,
            {
                "current_node_id": self.meta_task_branch_a.node_id,
                "comment": "keep me",
            },
        )

    def test_inline_required_domain_in_view_is_ignored(self):
        submit_states = self._runtime_payload("submit")["field_state_map"]
        reject_states = self._runtime_payload("reject")["field_state_map"]

        self.assertTrue(
            bool((submit_states.get("note") or {}).get("required")),
            "Meta Field action-scoped required rule should drive submit required state.",
        )
        self.assertFalse(
            bool((reject_states.get("note") or {}).get("required")),
            "Meta Field action scoping should stay false when the action does not match.",
        )
        self.assertFalse(
            bool((submit_states.get("comment") or {}).get("required")),
            "Inline wf_required_domain in the view must not drive runtime rendering.",
        )
        self.assertFalse(
            bool((reject_states.get("comment") or {}).get("required")),
            "Inline wf_required_domain in the view must not drive runtime rendering.",
        )

    def test_wf_field_widget_default_hidden_and_default_readonly_policy(self):
        submit_states = self._runtime_payload("submit")["field_state_map"]
        reject_states = self._runtime_payload("reject")["field_state_map"]

        self.assertIn("category_id", submit_states)
        self.assertFalse(submit_states["category_id"]["invisible"])
        self.assertFalse(
            submit_states["category_id"]["readonly"],
            "wf_field view readonly domains are ignored; Meta Field readonly rows are required.",
        )

        self.assertIn("category_id", reject_states)
        self.assertFalse(
            reject_states["category_id"]["invisible"],
            "wf_field visibility should be stable across workflow actions.",
        )
        self.assertFalse(
            reject_states["category_id"]["readonly"],
            "wf_field view readonly domains are ignored; Meta Field readonly rows are required.",
        )

        self.assertIn("approval_type", submit_states)
        self.assertFalse(submit_states["approval_type"]["invisible"])
        self.assertFalse(
            submit_states["approval_type"]["readonly"],
            "wf_field without wf_readonly_domain should be editable when visible.",
        )

        self.assertIn("approval_type", reject_states)
        self.assertFalse(
            reject_states["approval_type"]["invisible"],
            "wf_field visibility should not depend on submit/reject action keys.",
        )

    def test_runtime_map_from_db_policy_reference(self):
        submit_states = self._runtime_payload("submit", view=self.runtime_form_view_db)["field_state_map"]
        reject_states = self._runtime_payload("reject", view=self.runtime_form_view_db)["field_state_map"]

        self.assertIn("name", submit_states)
        self.assertFalse(submit_states["name"]["invisible"])

        self.assertIn("category_id", submit_states)
        self.assertFalse(submit_states["category_id"]["invisible"])
        self.assertFalse(submit_states["category_id"]["readonly"])

        self.assertIn("category_id", reject_states)
        self.assertFalse(reject_states["category_id"]["invisible"])
        self.assertFalse(reject_states["category_id"]["readonly"])

    def test_action_specific_required_fields_scoped_by_activity_and_action(self):
        self._grant_runtime_edit_access()
        request_model_fields = self.env["ir.model.fields"].sudo()
        note_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "note")],
            limit=1,
        )
        date_start_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "date_start")],
            limit=1,
        )
        date_end_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "date_end")],
            limit=1,
        )
        comment_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "comment")],
            limit=1,
        )

        suffix = uuid4().hex[:8]
        approve_action = self.MetaAction.sudo().create(
            {
                "name": "Approve",
                "meta_task_id": self.meta_task.id,
                "source_id": self.meta_task.node_id,
                "source_name": self.meta_task.name,
                "source_node_type": self.meta_task.node_type,
                "target_id": f"Task_Done_{suffix}",
                "target_name": "Done",
                "target_node_type": "endEvent",
                "node_id": f"Flow_Approve_{suffix}",
                "version_id": self.version.id,
            }
        )
        rework_action = self.MetaAction.sudo().create(
            {
                "name": "Rework",
                "meta_task_id": self.meta_task.id,
                "source_id": self.meta_task.node_id,
                "source_name": self.meta_task.name,
                "source_node_type": self.meta_task.node_type,
                "target_id": f"Task_Rework_{suffix}",
                "target_name": "Rework",
                "target_node_type": "userTask",
                "node_id": f"Flow_Rework_{suffix}",
                "version_id": self.version.id,
            }
        )
        scoped_required_fields = self.MetaField.sudo().create(
            [
                {
                    "meta_id": self.meta_task.id,
                    "field_id": note_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [approve_action.id])],
                },
                {
                    "meta_id": self.meta_task.id,
                    "field_id": date_start_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [approve_action.id])],
                },
                {
                    "meta_id": self.meta_task.id,
                    "field_id": date_end_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [approve_action.id])],
                },
                {
                    "meta_id": self.meta_task.id,
                    "field_id": comment_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [rework_action.id])],
                },
            ]
        )
        field_rule_service = self.env["workflow.engine.field.rule.service"].with_user(self.runtime_user)

        try:
            approve_payload = field_rule_service.evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                action_key="Approve",
                task_node_id=self.meta_task.node_id,
                view_id=self.runtime_form_view_db.id,
                user=self.runtime_user,
            )
            approve_required = set(approve_payload.get("required_fields") or [])
            self.assertIn("note", approve_required)
            self.assertIn("date_start", approve_required)
            self.assertIn("date_end", approve_required)
            self.assertNotIn("comment", approve_required)

            rework_payload = field_rule_service.evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                action_key="Rework",
                task_node_id=self.meta_task.node_id,
                view_id=self.runtime_form_view_db.id,
                user=self.runtime_user,
            )
            rework_required = set(rework_payload.get("required_fields") or [])
            self.assertIn("comment", rework_required)
            self.assertNotIn("note", rework_required)
            self.assertNotIn("date_start", rework_required)
            self.assertNotIn("date_end", rework_required)

            branch_payload = field_rule_service.evaluate_runtime_field_state_map(
                target_record=self.request.sudo(),
                request_record=self.request.sudo(),
                action_key="Approve",
                task_node_id=self.meta_task_branch_a.node_id,
                view_id=self.runtime_form_view_db.id,
                user=self.runtime_user,
            )
            branch_required = set(branch_payload.get("required_fields") or [])
            self.assertFalse(
                {"note", "date_start", "date_end", "comment"} & branch_required,
                "Action-scoped required fields must not leak to other activity nodes.",
            )

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {
                    "note": False,
                    "date_start": False,
                    "date_end": False,
                    "comment": False,
                }
            )
            with self.assertRaises(ValidationError):
                field_rule_service.validate_action_required_fields(
                    request_record=self.request.with_user(self.runtime_user),
                    action_key="Approve",
                    task_node_id=self.meta_task.node_id,
                )

            now_value = fields.Datetime.now()
            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {
                    "note": "<p>approval note</p>",
                    "date_start": now_value,
                    "date_end": now_value,
                    "comment": False,
                }
            )
            field_rule_service.validate_action_required_fields(
                request_record=self.request.with_user(self.runtime_user),
                action_key="Approve",
                task_node_id=self.meta_task.node_id,
            )

            with self.assertRaises(ValidationError):
                field_rule_service.validate_action_required_fields(
                    request_record=self.request.with_user(self.runtime_user),
                    action_key="Rework",
                    task_node_id=self.meta_task.node_id,
                )

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {"comment": "please revise"}
            )
            field_rule_service.validate_action_required_fields(
                request_record=self.request.with_user(self.runtime_user),
                action_key="Rework",
                task_node_id=self.meta_task.node_id,
            )
        finally:
            scoped_required_fields.sudo().unlink()
            rework_action.sudo().unlink()
            approve_action.sudo().unlink()

    def test_visible_button_required_fields_evaluate_conditional_domains(self):
        self._grant_runtime_edit_access()
        date_start_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "date_start")],
            limit=1,
        )
        conditional_required = self.MetaField.sudo().create(
            {
                "meta_id": self.meta_task.id,
                "field_id": date_start_field.id,
                "field_type": "required",
                "domain": "[('comment', '=', 'need-date')]",
                "activity_action_ids": [(6, 0, [self.meta_action_submit.id])],
            }
        )
        request_as_actor = self.request.with_user(self.runtime_user)
        try:
            request_as_actor.with_context(workflow_skip_field_policy=True).write(
                {
                    "comment": "baseline",
                    "date_start": False,
                }
            )

            buttons = request_as_actor.workflow_get_visible_buttons_snapshot(snapshot_values={})
            submit_button = next(
                button for button in buttons
                if button["action_key"] == self.meta_action_submit.name
            )
            self.assertTrue(submit_button["has_conditional_required_fields"])
            self.assertIn("date_start", submit_button["all_require_fields"])
            self.assertNotIn("date_start", submit_button["required_fields"])
            self.assertIn("note", submit_button["required_fields"])

            snapshot_buttons = request_as_actor.workflow_get_visible_buttons_snapshot(
                snapshot_values={"comment": "need-date"}
            )
            snapshot_submit_button = next(
                button for button in snapshot_buttons
                if button["action_key"] == self.meta_action_submit.name
            )
            self.assertTrue(snapshot_submit_button["has_conditional_required_fields"])
            self.assertIn("date_start", snapshot_submit_button["required_fields"])
            self.assertIn("note", snapshot_submit_button["required_fields"])
        finally:
            conditional_required.sudo().unlink()

    def test_validate_action_required_fields_skips_hidden_or_absent_view_fields(self):
        self._grant_runtime_edit_access()
        request_model_fields = self.env["ir.model.fields"]
        comment_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "comment")],
            limit=1,
        )
        date_start_field = request_model_fields.search(
            [("model", "=", "workflow.base.approval.request"), ("name", "=", "date_start")],
            limit=1,
        )

        scoped_fields = self.env["workflow.category.version.meta.field"]
        hidden_view = self.env["ir.ui.view"]
        try:
            scoped_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task.id,
                    "field_id": comment_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [self.meta_action_submit.id])],
                }
            )
            scoped_fields |= self.MetaField.sudo().create(
                {
                    "meta_id": self.meta_task.id,
                    "field_id": date_start_field.id,
                    "field_type": "required",
                    "activity_action_ids": [(6, 0, [self.meta_action_submit.id])],
                }
            )
            hidden_view = self.View.sudo().create(
                {
                    "name": f"wf.hidden.required.{uuid4().hex[:8]}",
                    "model": "workflow.base.approval.request",
                    "type": "form",
                    "mode": "primary",
                    "arch_base": """
<form string="WF Hidden Required" js_class="wf_form">
    <sheet>
        <group>
            <field name="note"/>
            <field name="comment" invisible="1"/>
        </group>
    </sheet>
</form>
                    """.strip(),
                }
            )

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {
                    "note": False,
                    "comment": False,
                    "date_start": False,
                }
            )

            field_rule_service = self.env["workflow.engine.field.rule.service"].with_user(self.runtime_user)
            with self.assertRaises(ValidationError) as exc:
                field_rule_service.validate_action_required_fields(
                    request_record=self.request.with_user(self.runtime_user),
                    action_key="Submit",
                    task_node_id=self.meta_task.node_id,
                    view_id=hidden_view.id,
                )

            error_message = str(exc.exception)
            self.assertIn(self.request._fields["note"].string, error_message)
            self.assertNotIn(self.request._fields["comment"].string, error_message)
            self.assertNotIn(self.request._fields["date_start"].string, error_message)

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {"note": "ready"}
            )
            field_rule_service.validate_action_required_fields(
                request_record=self.request.with_user(self.runtime_user),
                action_key="Submit",
                task_node_id=self.meta_task.node_id,
                view_id=hidden_view.id,
            )
        finally:
            scoped_fields.sudo().unlink()
            hidden_view.sudo().unlink()

    def test_validate_action_required_fields_honors_visible_legacy_required_one2many(self):
        self._grant_runtime_edit_access()
        conditional_view = self.View.sudo().create(
            {
                "name": f"wf.legacy.required.o2m.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Conditional O2M" js_class="wf_form">
    <sheet>
        <group>
            <field name="note"/>
            <field name="comment"/>
            <field name="child_ids" required="comment == 'need-child'"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {
                    "note": "ready",
                    "comment": "need-child",
                }
            )

            field_rule_service = self.env["workflow.engine.field.rule.service"].with_user(self.runtime_user)
            with self.assertRaises(ValidationError) as exc:
                field_rule_service.validate_action_required_fields(
                    request_record=self.request.with_user(self.runtime_user),
                    action_key="Submit",
                    task_node_id=self.meta_task.node_id,
                    view_id=conditional_view.id,
                )

            self.assertIn(self.request._fields["child_ids"].string, str(exc.exception))

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {"comment": "optional"}
            )
            field_rule_service.validate_action_required_fields(
                request_record=self.request.with_user(self.runtime_user),
                action_key="Submit",
                task_node_id=self.meta_task.node_id,
                view_id=conditional_view.id,
            )
        finally:
            conditional_view.sudo().unlink()

    def test_validate_action_required_fields_honors_meta_required_one2many(self):
        self._grant_runtime_edit_access()
        policy_view = self.View.sudo().create(
            {
                "name": f"wf.policy.required.o2m.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Policy O2M" js_class="wf_form">
    <sheet>
        <group>
            <field name="note"/>
            <field name="comment"/>
            <field name="child_ids" widget="wf_field"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        meta_rules = self.env["workflow.category.version.meta.field"]
        try:
            child_field = self.env["ir.model.fields"].search(
                [("model", "=", "workflow.base.approval.request"), ("name", "=", "child_ids")],
                limit=1,
            )
            meta_rules = self.MetaField.sudo().create(
                [
                    {
                        "meta_id": self.meta_task.id,
                        "field_id": child_field.id,
                        "field_type": "visible",
                    },
                    {
                        "meta_id": self.meta_task.id,
                        "field_id": child_field.id,
                        "field_type": "required",
                        "domain": "[('comment', '=', 'need-child')]",
                    },
                ]
            )
            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {
                    "note": "ready",
                    "comment": "need-child",
                }
            )

            field_rule_service = self.env["workflow.engine.field.rule.service"].with_user(self.runtime_user)
            with self.assertRaises(ValidationError) as exc:
                field_rule_service.validate_action_required_fields(
                    request_record=self.request.with_user(self.runtime_user),
                    action_key="Submit",
                    task_node_id=self.meta_task.node_id,
                    view_id=policy_view.id,
                )

            self.assertIn(self.request._fields["child_ids"].string, str(exc.exception))

            self.request.with_context(workflow_skip_field_policy=True).with_user(self.runtime_user).write(
                {"comment": "optional"}
            )
            field_rule_service.validate_action_required_fields(
                request_record=self.request.with_user(self.runtime_user),
                action_key="Submit",
                task_node_id=self.meta_task.node_id,
                view_id=policy_view.id,
            )
        finally:
            meta_rules.unlink()
            policy_view.sudo().unlink()

    def test_write_enforces_conditional_required_with_snapshot_values(self):
        self._grant_runtime_edit_access()
        conditional_view = self.View.sudo().create(
            {
                "name": f"wf.write.conditional.required.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Write Conditional Required" js_class="wf_form">
    <sheet>
        <group>
            <field name="comment"/>
            <field name="note" required="comment == 'need-note'"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            self.request.with_context(
                workflow_skip_field_policy=True,
                workflow_skip_edit_scope=True,
            ).with_user(self.runtime_user).write(
                {"comment": "optional", "note": "seed"}
            )

            with self.assertRaises(ValidationError) as exc:
                self.request.with_context(
                    workflow_skip_edit_scope=True,
                    view_id=conditional_view.id,
                    workflow_action_key="Submit",
                    workflow_task_node_id=self.meta_task.node_id,
                    meta_action_id=self.meta_action_submit.id,
                ).with_user(self.runtime_user).write(
                    {
                        "comment": "need-note",
                        "note": False,
                    }
                )

            self.assertIn(self.request._fields["note"].string, str(exc.exception))
        finally:
            conditional_view.sudo().unlink()

    def test_write_enforces_conditional_required_one2many_with_params_view_id(self):
        self._grant_runtime_edit_access()
        conditional_view = self.View.sudo().create(
            {
                "name": f"wf.write.conditional.required.o2m.{uuid4().hex[:8]}",
                "model": "workflow.base.approval.request",
                "type": "form",
                "mode": "primary",
                "arch_base": """
<form string="WF Write Conditional O2M" js_class="wf_form">
    <sheet>
        <group>
            <field name="comment"/>
            <field name="child_ids" required="comment == 'need-child'"/>
        </group>
    </sheet>
</form>
                """.strip(),
            }
        )
        try:
            self.request.with_context(
                workflow_skip_field_policy=True,
                workflow_skip_edit_scope=True,
            ).with_user(self.runtime_user).write(
                {"comment": "optional"}
            )

            with self.assertRaises(ValidationError) as exc:
                self.request.with_context(
                    workflow_skip_edit_scope=True,
                    params={"view_id": conditional_view.id},
                    workflow_action_key="Submit",
                    workflow_task_node_id=self.meta_task.node_id,
                    meta_action_id=self.meta_action_submit.id,
                ).with_user(self.runtime_user).write(
                    {
                        "comment": "need-child",
                    }
                )

            self.assertIn(self.request._fields["child_ids"].string, str(exc.exception))
        finally:
            conditional_view.sudo().unlink()
