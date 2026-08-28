# -*- coding: utf-8 -*-

from unittest.mock import patch
from uuid import uuid4

from odoo.tests import common
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.workflow_engine.utils.util import RequestDataContext


class TestWorkflowAccessRules(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.MetaAction = cls.env["workflow.category.version.meta.task.action"]
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.Attachment = cls.env["ir.attachment"]
        cls.group_workflow_user = cls.env.ref("workflow_engine.group_workflow_approval_user")
        cls.group_workflow_admin = cls.env.ref("workflow_engine.group_workflow_approval_admin")
        cls.group_workflow_technical_admin = cls.env.ref("workflow_engine.group_workflow_technical_admin")
        cls.group_workflow_technical_support = cls.env.ref("workflow_engine.group_workflow_technical_support")
        cls.group_internal_user = cls.env.ref("base.group_user")
        unique = uuid4().hex[:8]
        cls.group_category_admin = cls.env["res.groups"].create({
            "name": f"Workflow Category Admin {unique}",
        })

        user_vals = {
            "group_ids": [(6, 0, [cls.group_workflow_user.id])],
        }
        cls.user_hod = cls.User.with_context(no_reset_password=True).create({
            **user_vals,
            "name": "Workflow HOD User",
            "login": f"wf_hod_{unique}",
            "email": f"wf_hod_{unique}@example.com",
        })
        cls.user_outsider = cls.User.with_context(no_reset_password=True).create({
            **user_vals,
            "name": "Workflow Outsider User",
            "login": f"wf_out_{unique}",
            "email": f"wf_out_{unique}@example.com",
        })
        cls.user_category_admin = cls.User.with_context(no_reset_password=True).create({
            "group_ids": [(6, 0, [cls.group_workflow_user.id, cls.group_category_admin.id])],
            "name": "Workflow Category Admin User",
            "login": f"wf_cat_admin_{unique}",
            "email": f"wf_cat_admin_{unique}@example.com",
        })
        cls.user_approval_admin = cls.User.with_context(no_reset_password=True).create({
            "group_ids": [(6, 0, [cls.group_workflow_admin.id])],
            "name": "Workflow Approval Admin User",
            "login": f"wf_approval_admin_{unique}",
            "email": f"wf_approval_admin_{unique}@example.com",
        })
        cls.user_technical_admin = cls.User.with_context(no_reset_password=True).create({
            "group_ids": [(6, 0, [cls.group_workflow_technical_admin.id])],
            "name": "Workflow Technical Admin User",
            "login": f"wf_tech_admin_{unique}",
            "email": f"wf_tech_admin_{unique}@example.com",
        })
        cls.user_technical_support = cls.User.with_context(no_reset_password=True).create({
            "group_ids": [(6, 0, [cls.group_workflow_technical_support.id])],
            "name": "Workflow Technical Support User",
            "login": f"wf_tech_support_{unique}",
            "email": f"wf_tech_support_{unique}@example.com",
        })

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.base_request_model = base_request_model
        cls.category = cls.Category.sudo().create({
            "name": "Access Rule Category",
            "res_model": base_request_model.id,
            "zero_trust_enforced": False,
            "admin_group_ids": [(6, 0, [cls.group_category_admin.id])],
        })
        cls.version = cls.Version.sudo().create({
            "name": "v_access_rule",
            "category_id": cls.category.id,
            "is_active": True,
        })
        cls.category.sudo().write({"active_version_id": cls.version.id})

        cls.meta_submission = cls.MetaTask.sudo().create({
            "version_id": cls.version.id,
            "name": "Submission",
            "node_id": "Task_Submission",
            "node_type": "userTask",
        })
        cls.meta_hod = cls.MetaTask.sudo().create({
            "version_id": cls.version.id,
            "name": "HOD",
            "node_id": "Task_HOD",
            "node_type": "userTask",
        })

        cls.request = cls.Request.sudo().create({
            "name": "REQ_ACCESS_001",
            "category_id": cls.category.id,
            "request_owner_id": cls.env.user.id,
            "current_node_id": cls.meta_hod.node_id,
            "previous_node_id": cls.meta_submission.node_id,
        })
        cls.Approver.sudo().create({
            "user_id": cls.user_hod.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })
        cls.MetaAction.sudo().create({
            "version_id": cls.version.id,
            "meta_task_id": cls.meta_hod.id,
            "node_id": "Flow_HOD_Approve",
            "source_id": cls.meta_hod.node_id,
            "source_name": cls.meta_hod.name,
            "source_node_type": "userTask",
            "target_id": "Event_Approved",
            "target_name": "Approved",
            "target_node_type": "endEvent",
            "name": "Approve",
            "attr_label": "Approve",
            "invisible_domain": "[]",
        })

    def _create_waiting_request(self, approver_user=None):
        approver_user = approver_user or self.user_hod
        request = self.Request.sudo().create({
            "name": f"REQ_ACCESS_DELEGATE_{uuid4().hex[:8]}",
            "category_id": self.category.id,
            "request_owner_id": self.env.user.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "state": "waiting",
        })
        self.Approver.sudo().create({
            "user_id": approver_user.id,
            "request_id": request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })
        return request

    def test_dynamic_assignee_gets_workflow_group_and_access(self):
        unique = uuid4().hex[:8]
        user_without_workflow = self.User.with_context(no_reset_password=True).create({
            "name": "Workflow Dynamic User",
            "login": f"wf_dyn_{unique}",
            "email": f"wf_dyn_{unique}@example.com",
            "group_ids": [(6, 0, [self.group_internal_user.id])],
        })

        self.assertNotIn(self.group_workflow_user, user_without_workflow.group_ids)
        self.Approver.sudo().create({
            "user_id": user_without_workflow.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })
        user_without_workflow.invalidate_recordset(["group_ids"])
        self.assertIn(
            self.group_workflow_user,
            user_without_workflow.group_ids,
            "Dynamic approver assignment must auto-grant workflow user group.",
        )
        self.assertTrue(
            self.Request.with_user(user_without_workflow).search([("id", "=", self.request.id)]),
            "Dynamic approver must see assigned request after auto-grant.",
        )
        self.assertTrue(
            self.Category.with_user(user_without_workflow).search([("id", "=", self.category.id)]),
            "Dynamic approver must see category after auto-grant.",
        )

    def test_assigned_approver_can_see_request(self):
        req = self.Request.with_user(self.user_hod).search([("id", "=", self.request.id)])
        self.assertTrue(req, "Assigned approver must see request to review/decide.")

    def test_category_admin_group_can_execute_current_activity_on_behalf(self):
        request = self.request.sudo()
        request.write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        request_as_category_admin = request.with_user(self.user_category_admin)

        self.assertFalse(
            request_as_category_admin._workflow_get_open_actor_node_ids(user=self.user_category_admin),
            "Category admin override must not require an approver assignment row.",
        )
        self.assertTrue(
            request_as_category_admin._workflow_user_is_on_behalf_admin(user=self.user_category_admin),
        )
        self.assertTrue(
            request_as_category_admin._workflow_can_execute_actor_node(
                self.meta_hod.node_id,
                user=self.user_category_admin,
            ),
        )
        self.assertEqual(
            [button["label"] for button in request_as_category_admin.workflow_get_visible_buttons_snapshot({})],
            ["Approve"],
        )

    def test_category_admin_confirm_wizard_persists_comment_and_attachment_on_behalf(self):
        request = self.request.sudo()
        request.write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        action = self.MetaAction.sudo().search(
            [("version_id", "=", self.version.id), ("source_id", "=", self.meta_hod.node_id)],
            limit=1,
        )

        with self.assertRaises(UserError):
            request.with_user(self.user_category_admin).write({"comment": "blocked direct edit"})

        attachment = self.Attachment.with_user(self.user_category_admin).create(
            {
                "name": "category-admin-note.txt",
                "type": "binary",
                "datas": "V29ya2Zsb3c=",
                "mimetype": "text/plain",
            }
        )
        wizard = self.env["workflow.confirm.wizard"].with_user(self.user_category_admin).with_context(
            default_res_model=request._name,
            default_res_id=request.id,
            meta_action_id=action.id,
            workflow_action_key=action.name,
            workflow_task_node_id=action.source_id,
            action_type=action.name,
        ).create(
            {
                "comment": "Category admin on-behalf note",
                "attachment_ids": [(6, 0, [attachment.id])],
            }
        )

        with patch.object(type(request), "_run_engine", autospec=True, return_value=True) as run_engine:
            result = wizard.action_confirm()
        request.invalidate_recordset(["comment"])
        attachment = attachment.sudo()
        attachment.invalidate_recordset(["res_model", "res_id"])
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(run_engine.call_count, 1)
        self.assertEqual(attachment.res_model, request._name)
        self.assertEqual(attachment.res_id, request.id)
        self.assertEqual(request.comment, "Category admin on-behalf note")

    def test_unrelated_user_cannot_execute_current_activity_on_behalf(self):
        request = self.request.sudo()
        request.write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        request_as_outsider = request.with_user(self.user_outsider)

        self.assertFalse(
            request_as_outsider._workflow_can_execute_actor_node(
                self.meta_hod.node_id,
                user=self.user_outsider,
            ),
        )
        self.assertEqual(request_as_outsider.workflow_get_visible_buttons_snapshot({}), [])

    def test_workflow_approval_admin_group_is_not_task_execution_override(self):
        request = self.request.sudo()
        request.write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        request_as_approval_admin = request.with_user(self.user_approval_admin)

        self.assertTrue(
            self.user_approval_admin.has_group("workflow_engine.group_workflow_approval_admin"),
            "Test setup requires the workflow approval admin group.",
        )
        self.assertFalse(
            request_as_approval_admin._workflow_user_is_on_behalf_admin(
                user=self.user_approval_admin,
            ),
            "Workflow Approval Admin is a configuration/access role, not an on-behalf task executor.",
        )
        self.assertFalse(
            request_as_approval_admin._workflow_can_execute_actor_node(
                self.meta_hod.node_id,
                user=self.user_approval_admin,
            ),
        )
        self.assertEqual(request_as_approval_admin.workflow_get_visible_buttons_snapshot({}), [])

    def test_assigned_approver_can_delegate_current_activity(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_hod)

        self.assertTrue(request.check_if_user_can_delegate(request))
        self.assertTrue(request.is_user_can_delegate)

    def test_category_admin_cannot_delegate_without_assignment(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_category_admin)

        self.assertFalse(request.check_if_user_can_delegate(request))
        self.assertFalse(request.is_user_can_delegate)

    def test_workflow_approval_admin_cannot_delegate_without_assignment(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_approval_admin)

        self.assertFalse(request.check_if_user_can_delegate(request))
        self.assertFalse(request.is_user_can_delegate)

    def test_technical_admin_can_delegate_without_assignment(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_technical_admin)

        self.assertTrue(request.check_if_user_can_delegate(request))
        self.assertTrue(request.is_user_can_delegate)

    def test_technical_support_can_delegate_without_assignment(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_technical_support)

        self.assertTrue(request.check_if_user_can_delegate(request))
        self.assertTrue(request.is_user_can_delegate)

    def test_technical_support_confirm_wizard_cannot_approve_on_behalf(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        action = self.MetaAction.sudo().search(
            [("version_id", "=", self.version.id), ("source_id", "=", self.meta_hod.node_id)],
            limit=1,
        )
        wizard = self.env["workflow.confirm.wizard"].with_user(self.user_technical_support).with_context(
            default_res_model=request._name,
            default_res_id=request.id,
            meta_action_id=action.id,
            workflow_action_key=action.name,
            workflow_task_node_id=action.source_id,
            action_type=action.name,
        ).create({"comment": "Technical support cannot approve"})

        with patch.object(type(request), "_run_engine", autospec=True, return_value=True) as run_engine:
            try:
                wizard.action_confirm()
            except (AccessError, ValidationError, UserError):
                pass
            else:
                self.fail("Technical support must not be able to approve on behalf.")
        self.assertFalse(run_engine.called)

    def test_technical_admin_can_run_stale_approver_repair_action(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_technical_admin)

        result = request.action_repair_stale_approvers()

        self.assertEqual(result.get("tag"), "display_notification")
        self.assertEqual(result.get("params", {}).get("type"), "success")
        self.assertEqual(result.get("params", {}).get("next", {}).get("tag"), "reload")

    def test_technical_support_cannot_run_stale_approver_repair_action(self):
        request = self._create_waiting_request(approver_user=self.user_hod).with_user(self.user_technical_support)

        with self.assertRaises(AccessError):
            request.action_repair_stale_approvers()

    def test_technical_admin_unlink_archives_request(self):
        request = self._create_waiting_request(approver_user=self.user_hod)

        request.with_user(self.user_technical_admin).unlink()

        archived_request = self.Request.with_user(self.user_technical_admin).with_context(active_test=False).search(
            [("id", "=", request.id)]
        )
        self.assertTrue(archived_request.exists())
        self.assertFalse(archived_request.active)
        self.assertFalse(
            self.Request.with_user(self.user_hod).search([("id", "=", request.id)]),
            "Archived requests must stay hidden from normal active searches.",
        )

    def test_technical_admin_can_reactivate_archived_request(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        request.with_user(self.user_technical_admin).unlink()

        archived_request = self.Request.with_user(self.user_technical_admin).with_context(active_test=False).search(
            [("id", "=", request.id)]
        )
        archived_request.action_unarchive()

        request.invalidate_recordset(["active"])
        self.assertTrue(request.active)
        self.assertTrue(
            self.Request.with_user(self.user_hod).search([("id", "=", request.id)]),
            "Reactivated requests must return to the normal request list.",
        )
        self.assertTrue(
            self.Request.with_user(self.user_technical_admin).search([("id", "=", request.id)]),
            "Technical admin must be able to find reactivated requests from the request report.",
        )

    def test_archived_request_hides_workflow_action_buttons(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        request.with_user(self.user_technical_admin).unlink()

        archived_request = self.Request.with_user(self.user_hod).with_context(active_test=False).search([("id", "=", request.id)])
        self.assertEqual(
            archived_request.workflow_get_visible_buttons_snapshot({}),
            [],
            "Archived requests must not expose workflow decision buttons.",
        )

    def test_delegate_wizard_blocks_non_actor_without_override(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        wizard = self.env["delegate_wizard"].with_user(self.user_outsider).create({
            "res_model": "workflow.base.approval.request",
            "res_id": request.id,
            "delegate_type": "shared",
            "selected_user_id": self.user_hod.id,
            "comment": "Support handoff",
        })

        with self.assertRaises(UserError):
            wizard.action_server_delegate()

    def test_delegate_wizard_allows_technical_support_override(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        wizard = self.env["delegate_wizard"].with_user(self.user_technical_support).create({
            "res_model": "workflow.base.approval.request",
            "res_id": request.id,
            "delegate_type": "redirected",
            "selected_user_id": self.user_outsider.id,
            "comment": "Technical support redirect",
        })

        result = wizard.action_server_delegate()

        self.assertEqual(result.get("tag"), "reload")
        redirected_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.user_outsider.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        original_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.user_hod.id),
            ],
            order="id desc",
            limit=1,
        )

        self.assertTrue(redirected_row)
        self.assertEqual(redirected_row.comment, "Technical support redirect")
        self.assertEqual(redirected_row.delegation_mode, "redirected")
        self.assertEqual(redirected_row.delegated_from_user_id, self.user_hod)
        self.assertEqual(redirected_row.delegated_to_user_id, self.user_outsider)
        self.assertEqual(redirected_row.delegated_by_user_id, self.user_technical_support)
        self.assertEqual(original_row.status, "closed")
        self.assertEqual(original_row.user_decision, "Redirected")
        self.assertEqual(original_row.comment, "Technical support redirect")
        self.assertFalse(original_row.counts_as_decided_user)
        self.assertTrue(original_row.show_in_decision_history)
        self.assertEqual(original_row.delegated_from_user_id, self.user_hod)
        self.assertEqual(original_row.delegated_from_approver_id, original_row)
        self.assertEqual(original_row.delegated_to_user_id, self.user_outsider)
        self.assertGreater(original_row.event_order, redirected_row.event_order)

        event = self.env["workflow.request.task.event"].sudo().search(
            [("request_id", "=", request.id), ("event_type", "=", "delegation")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(event)
        self.assertEqual(event.actor_user_id, self.user_technical_support)
        self.assertEqual(event.on_behalf_of_user_id, self.user_hod)
        self.assertEqual(event.target_user_id, self.user_outsider)
        self.assertEqual((event.payload_json or {}).get("mode"), "redirected")

    def test_delegate_wizard_share_allows_multiple_users(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        recipients = self.user_outsider | self.user_category_admin
        wizard = self.env["delegate_wizard"].with_user(self.user_hod).create({
            "res_model": "workflow.base.approval.request",
            "res_id": request.id,
            "delegate_type": "shared",
            "selected_user_ids": [(6, 0, recipients.ids)],
            "comment": "Share with the backup approvers",
        })

        result = wizard.action_server_delegate()

        self.assertEqual(result.get("tag"), "reload")
        open_recipient_rows = self.Approver.sudo().search([
            ("request_id", "=", request.id),
            ("current_meta_id", "=", self.meta_hod.id),
            ("user_id", "in", recipients.ids),
            ("status", "=", "new"),
        ])
        self.assertEqual(set(open_recipient_rows.user_id.ids), set(recipients.ids))
        source_row = self.Approver.sudo().search([
            ("request_id", "=", request.id),
            ("current_meta_id", "=", self.meta_hod.id),
            ("user_id", "=", self.user_hod.id),
            ("status", "=", "new"),
        ], limit=1)
        self.assertTrue(source_row, "Share must preserve the source approver's right.")
        events = self.env["workflow.request.task.event"].sudo().search([
            ("request_id", "=", request.id),
            ("event_type", "=", "delegation"),
            ("target_user_id", "in", recipients.ids),
        ])
        self.assertEqual(set(events.target_user_id.ids), set(recipients.ids))

    def test_delegate_wizard_redirect_still_requires_one_user(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        wizard = self.env["delegate_wizard"].with_user(self.user_hod).create({
            "res_model": "workflow.base.approval.request",
            "res_id": request.id,
            "delegate_type": "redirected",
            "selected_user_ids": [(6, 0, [self.user_outsider.id, self.user_category_admin.id])],
            "comment": "Invalid multi-user redirect",
        })

        with self.assertRaises(UserError):
            wizard.action_server_delegate()

    def test_delegate_wizard_admin_override_requires_source_approver_selection_when_multiple_exist(self):
        request = self._create_waiting_request(approver_user=self.user_hod)
        second_row = self.Approver.sudo().create(
            {
                "user_id": self.user_category_admin.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "required": True,
                "status": "new",
                "iteration_no": 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.user_technical_support).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "redirected",
                "selected_user_id": self.user_outsider.id,
                "comment": "Technical support redirect",
            }
        )

        self.assertTrue(wizard.show_source_approver_selection)
        self.assertEqual(set(wizard.available_source_approver_ids.ids), set(request.approver_ids.ids))

        with self.assertRaises(UserError):
            wizard.action_server_delegate()

        wizard.source_approver_id = second_row
        result = wizard.action_server_delegate()

        self.assertEqual(result.get("tag"), "reload")
        redirected_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.user_outsider.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(redirected_row)
        self.assertEqual(redirected_row.delegated_from_user_id, self.user_category_admin)
        self.assertEqual(redirected_row.delegated_to_user_id, self.user_outsider)
        hod_row = request.approver_ids.filtered(lambda row: row.user_id == self.user_hod)
        self.assertEqual(hod_row.status, "new")

    def test_assigned_approver_can_see_category(self):
        cat = self.Category.with_user(self.user_hod).search([("id", "=", self.category.id)])
        self.assertTrue(cat, "Assigned approver must see category on dashboard.")

    def test_non_zero_trust_category_is_readable_by_workflow_reader(self):
        req = self.Request.with_user(self.user_outsider).search([("id", "=", self.request.id)])
        cat = self.Category.with_user(self.user_outsider).search([("id", "=", self.category.id)])
        self.assertTrue(req, "Non-zero-trust requests should be readable by workflow readers.")
        self.assertTrue(cat, "Non-zero-trust category should be visible to workflow readers.")

    def test_unrelated_user_cannot_see_private_request_or_category(self):
        private_category = self.Category.sudo().create({
            "name": "Private Access Rule Category",
            "res_model": self.base_request_model.id,
            "zero_trust_enforced": True,
            "create_access_mode": "restricted",
            "admin_group_ids": [(6, 0, [self.group_category_admin.id])],
        })
        private_request = self.Request.sudo().create({
            "name": "REQ_ACCESS_PRIVATE_001",
            "category_id": private_category.id,
            "request_owner_id": self.env.user.id,
            "state": "new",
            "request_status": "new",
        })

        req = self.Request.with_user(self.user_outsider).search([("id", "=", private_request.id)])
        cat = self.Category.with_user(self.user_outsider).search([("id", "=", private_category.id)])
        self.assertFalse(req, "Unrelated user must not see private request.")
        self.assertFalse(cat, "Unrelated user must not see private category.")

    def test_reviewer_menu_points_to_request_action(self):
        menu_to_review = self.env.ref("workflow_engine.workflow_approvals_approval_menu_to_review")
        menu_all = self.env.ref("workflow_engine.workflow_approvals_approval_menu_all")
        xmlid_to_review = menu_to_review.action.get_external_id().get(menu_to_review.action.id)
        xmlid_all = menu_all.action.get_external_id().get(menu_all.action.id)

        self.assertEqual(
            xmlid_to_review,
            "workflow_engine.my_work_list_action_window",
            "My Work List menu must open the workflow work-list action.",
        )
        self.assertEqual(
            xmlid_all,
            "workflow_engine.my_contribute_list_action_window",
            "My Contribute List menu must open the contribution request list action.",
        )

    def test_repair_stale_approvers_server_action_is_bound_to_request_list(self):
        action = self.env.ref("workflow_engine.action_server_repair_stale_approvers")

        self.assertEqual(action.binding_model_id.model, "workflow.base.approval.request")
        self.assertEqual(action.binding_type, "action")
        self.assertEqual(action.binding_view_types, "list")

    def test_category_review_open_requests_uses_unified_request_view(self):
        action = self.category.with_context(filter=RequestDataContext.MY_REVIEWS.value).action_approval_category()
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertIn(("category_id", "=", self.category.id), action.get("domain", []))

    def test_category_my_requests_open_requests_uses_unified_request_view(self):
        action = self.category.with_context(filter=RequestDataContext.MY_REQUESTS.value).action_approval_category()
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertIn(("category_id", "=", self.category.id), action.get("domain", []))

    def test_category_my_requests_review_card_uses_review_action_context(self):
        action = self.category.with_context(
            filter=RequestDataContext.MY_REQUESTS.value,
            state="reviewed",
        ).action_approval_category()
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertIn(("category_id", "=", self.category.id), action.get("domain", []))
        self.assertEqual(action.get("context", {}).get("search_default_filter_my_work_list"), 1)
        self.assertFalse(action.get("context", {}).get("search_default_filter_my_request_owner"))

    def test_category_review_card_with_child_model_uses_base_work_list(self):
        self.request.sudo().write({"state": "waiting"})
        self.category.sudo().write({
            "res_model": self.env["ir.model"]._get("res.users").id,
        })

        action = self.category.with_user(self.user_hod).with_context(
            filter=RequestDataContext.MY_REQUESTS.value,
            state="reviewed",
        ).action_approval_category()

        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertIn(
            self.request,
            self.Request.with_user(self.user_hod).search(action.get("domain", [])),
        )
        self.assertEqual(action.get("context", {}).get("search_default_filter_my_work_list"), 1)

    def test_dashboard_review_header_uses_review_action_context(self):
        action = self.Category.with_context(
            filter=RequestDataContext.MY_REQUESTS.value
        ).action_open_dashboard_requests("reviewed")
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertEqual(action.get("context", {}).get("search_default_filter_my_work_list"), 1)
        self.assertFalse(action.get("context", {}).get("search_default_filter_my_request_owner"))

    def test_request_form_header_prioritizes_action_before_view_flow(self):
        form_arch = self.env.ref("workflow_engine.approval_base_request_view_form").arch_db
        self.assertLess(
            form_arch.find('widget name="approval_buttons"'),
            form_arch.find('widget name="bpmn_button"'),
            "Mobile form header should expose workflow actions before View Flow.",
        )

    def test_request_views_expose_done_state_and_pending_activity_labels(self):
        form_arch = self.env.ref("workflow_engine.approval_base_request_view_form").arch_db
        list_arch = self.env.ref("workflow_engine.approval_base_request_view_list").arch_db
        search_arch = self.env.ref("workflow_engine.approval_base_search_view_search").arch_db
        self.assertIn('statusbar_visible="draft,new,waiting,done,completed"', form_arch)
        self.assertRegex(
            form_arch,
            r'name="latest_transition_summary"\s+class="wf-request-overview__value"',
        )
        self.assertRegex(
            form_arch,
            r'name="pending_approver_summary"\s+class="wf-request-overview__value"',
        )
        self.assertIn('string="Pending Activity"', list_arch)
        self.assertIn('name="filter_done"', search_arch)

    def test_request_report_kanban_opens_child_request_and_marks_success_states_green(self):
        kanban_arch = self.env.ref("workflow_engine.approval_base_request_view_kanban_mobile").arch_db
        self.assertIn('action="action_open_child"', kanban_arch)
        self.assertIn('type="object"', kanban_arch)
        self.assertIn("'done': 'success'", kanban_arch)
        self.assertIn("'auto_approved': 'success'", kanban_arch)

    def test_action_open_child_defaults_to_inline_current_and_base_fallback(self):
        action = self.request.action_open_child()
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertEqual(action.get("res_id"), self.request.id)
        self.assertEqual(action.get("target"), "current")
        self.assertEqual(action.get("views"), [[False, "form"]])

        popup_action = self.request.with_context(wf_open_target="new").action_open_child()
        self.assertEqual(popup_action.get("target"), "new")

    def test_category_dashboard_compact_count_formatter(self):
        self.assertEqual(self.Category._format_compact_count(999), "999")
        self.assertEqual(self.Category._format_compact_count(1_255), "1.2K")
        self.assertEqual(self.Category._format_compact_count(12_550), "12.5K")
        self.assertEqual(self.Category._format_compact_count(213_999), "213K")
        self.assertEqual(self.Category._format_compact_count(1_255_000), "1.2M+")

    def test_category_dashboard_kanban_uses_compact_display_fields(self):
        kanban_arch = self.env.ref("workflow_engine.workflow_approval_category_view_kanban").arch_db
        self.assertIn('name="request_tosubmit_count_display"', kanban_arch)
        self.assertIn('name="request_waiting_count_display"', kanban_arch)
        self.assertIn('name="request_reviewed_count_display"', kanban_arch)
        self.assertIn('name="request_completed_count_display"', kanban_arch)
        self.assertIn('name="request_to_validate_count_display"', kanban_arch)

    def test_category_order_is_shared_by_dashboard_and_category_report(self):
        dashboard_list_arch = self.env.ref(
            "workflow_engine.workflow_approval_category_view_list_dashboard"
        ).arch_db
        dashboard_kanban_arch = self.env.ref(
            "workflow_engine.workflow_approval_category_view_kanban"
        ).arch_db
        report_action = self.env.ref("workflow_engine.approval_report_action_window")

        self.assertEqual(self.Category._order, "sequence, create_date, id")
        self.assertIn('default_order="sequence, create_date, id"', dashboard_list_arch)
        self.assertIn('default_order="sequence, create_date, id"', dashboard_kanban_arch)
        self.assertEqual(report_action.res_model, self.Category._name)

    def test_category_resequence_uses_standard_write_access(self):
        other_category = self.Category.sudo().create(
            {
                "name": f"Resequence Category {uuid4().hex[:8]}",
                "automated_sequence": False,
            }
        )
        ordered_categories = self.Category.with_user(self.user_approval_admin).browse(
            [other_category.id, self.category.id]
        )
        ordered_categories.web_resequence({}, field_name="sequence", offset=20)
        ordered_categories.invalidate_recordset(["sequence"])

        self.assertEqual(other_category.sequence, 20)
        self.assertEqual(self.category.sequence, 21)

    def test_new_category_sequence_is_after_existing_categories(self):
        current_sequences = self.Category.sudo().search([]).mapped("sequence")
        expected_sequence = max(current_sequences or [0]) + 10
        category = self.Category.sudo().create(
            {
                "name": f"Ordered Category {uuid4().hex[:8]}",
                "automated_sequence": False,
            }
        )

        self.assertEqual(category.sequence, expected_sequence)

    def test_done_state_is_informational_but_open_for_active_actor(self):
        request = self._create_waiting_request()
        request.write({"state": "done"})

        self.assertEqual(request.request_status, "done")
        self.assertEqual(request.pending_approver_summary, "No pending activity")
        self.assertFalse(request.to_approve_res_user_ids)

        request_as_hod = request.with_user(self.user_hod)
        self.assertFalse(request_as_hod.is_finished)
        self.assertTrue(request_as_hod.is_user_has_permission)
        self.assertFalse(request_as_hod.check_if_user_can_delegate(request_as_hod))
        self.assertEqual(
            [button["label"] for button in request_as_hod.workflow_get_visible_buttons_snapshot({})],
            ["Approve"],
        )

        request_as_outsider = request.with_user(self.user_outsider)
        self.assertTrue(request_as_outsider.is_finished)
        self.assertFalse(request_as_outsider.is_user_has_permission)
        self.assertEqual(request_as_outsider.workflow_get_visible_buttons_snapshot({}), [])

        request_as_category_admin = request.with_user(self.user_category_admin)
        self.assertFalse(request_as_category_admin.is_finished)
        self.assertTrue(request_as_category_admin.is_user_has_permission)
        self.assertTrue(request_as_category_admin.check_if_user_can_delegate(request_as_category_admin))
        self.assertEqual(
            [button["label"] for button in request_as_category_admin.workflow_get_visible_buttons_snapshot({})],
            ["Approve"],
        )

    def test_action_set_done_requires_admin_override(self):
        request = self._create_waiting_request()
        with self.assertRaises(AccessError):
            request.with_user(self.user_hod).with_context(
                workflow_silent_done_action=True
            ).action_set_done()

    def test_action_set_done_marks_waiting_request_done(self):
        request = self._create_waiting_request()
        result = request.with_user(self.user_category_admin).with_context(
            workflow_silent_done_action=True
        ).action_set_done()

        request.invalidate_recordset(["state", "request_status"])
        self.assertTrue(result)
        self.assertEqual(request.state, "done")
        self.assertEqual(request.request_status, "done")

    def test_my_workflow_dashboard_waiting_scope_uses_request_owner_or_creator(self):
        action = self.category.with_user(self.user_hod).with_context(
            filter=RequestDataContext.MY_REQUESTS.value,
            state=["waiting"],
        ).action_approval_category()
        self.assertEqual(action.get("res_model"), "workflow.base.approval.request")
        self.assertIn(("request_owner_id", "=", self.user_hod.id), action.get("domain", []))
        self.assertIn(("create_uid", "=", self.user_hod.id), action.get("domain", []))

    def test_my_workflow_dashboard_waiting_count_includes_owner_and_creator_requests(self):
        owner_waiting = self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_OWNER_WAITING",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "state": "waiting",
        })
        created_on_behalf_waiting = self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_ON_BEHALF_WAITING",
            "category_id": self.category.id,
            "request_owner_id": self.user_outsider.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "state": "waiting",
        })

        data = self.Category.with_user(self.user_hod).with_context(
            filter=RequestDataContext.MY_REQUESTS.value
        ).retrieve_dashboard_header_data()

        self.assertEqual(data.get("waiting_count"), 2)
        waiting_reqs = self.Request.with_user(self.user_hod).search([
            "|",
            ("request_owner_id", "=", self.user_hod.id),
            ("create_uid", "=", self.user_hod.id),
            ("state", "=", "waiting"),
        ])
        self.assertIn(owner_waiting, waiting_reqs)
        self.assertIn(created_on_behalf_waiting, waiting_reqs)

    def test_my_workflow_dashboard_new_and_done_counts_include_owner_and_creator_requests(self):
        self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_OWNER_NEW",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "state": "new",
        })
        self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_CREATOR_NEW",
            "category_id": self.category.id,
            "request_owner_id": self.user_outsider.id,
            "state": "new",
        })
        self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_OWNER_DONE",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "state": "completed",
        })
        self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_CREATOR_DONE",
            "category_id": self.category.id,
            "request_owner_id": self.user_outsider.id,
            "state": "completed",
        })

        data = self.Category.with_user(self.user_hod).with_context(
            filter=RequestDataContext.MY_REQUESTS.value
        ).retrieve_dashboard_header_data()

        self.assertGreaterEqual(data.get("tosubmit_count"), 2)
        self.assertGreaterEqual(data.get("completed_count"), 2)

    def test_my_workflow_dashboard_card_actions_include_owner_and_creator_domain(self):
        for state in ("new", "waiting", "completed"):
            action = self.Category.with_user(self.user_hod).with_context(
                filter=RequestDataContext.MY_REQUESTS.value
            ).action_open_dashboard_requests(state)
            self.assertIn(("request_owner_id", "=", self.user_hod.id), action.get("domain", []))
            self.assertIn(("create_uid", "=", self.user_hod.id), action.get("domain", []))

    def test_legacy_review_actions_are_request_level(self):
        # to_review_action = self.env.ref("workflow_engine.requests_to_review_action_window")
        all_action = self.env.ref("workflow_engine.all_requests_action_window")
        # self.assertEqual(to_review_action.res_model, "workflow.base.approval.request")
        self.assertEqual(all_action.res_model, "workflow.base.approval.request")

    def test_my_work_list_includes_open_assignee_work_even_when_owned(self):
        self.request.sudo().write({"state": "waiting"})
        owned_request = self.Request.sudo().create({
            "name": "REQ_ACCESS_OWNER_WORK",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "state": "waiting",
        })
        self.Approver.sudo().create({
            "user_id": self.user_hod.id,
            "request_id": owned_request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })

        work = self.Request.with_user(self.user_hod).search([("is_my_work_item", "=", True)])

        self.assertIn(self.request, work)
        self.assertIn(
            owned_request,
            work,
            "My Work List must include requests that are still pending for the same user, even when they also own or created the request.",
        )

    def test_my_work_list_includes_open_assignee_work_when_created_on_behalf(self):
        delegated_request = self.Request.with_user(self.user_hod).create({
            "name": "REQ_ACCESS_CREATED_ON_BEHALF",
            "category_id": self.category.id,
            "request_owner_id": self.user_outsider.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "state": "waiting",
        })
        self.Approver.sudo().create({
            "user_id": self.user_hod.id,
            "request_id": delegated_request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })

        work = self.Request.with_user(self.user_hod).search([("is_my_work_item", "=", True)])

        self.assertIn(
            delegated_request,
            work,
            "My Work List must include requests created on behalf of someone else when the creator is also the pending approver.",
        )

    def test_my_contribute_list_is_historical_involvement_not_pending_work_or_owned(self):
        self.request.sudo().write({"state": "waiting"})
        self.assertIn(
            self.request,
            self.Request.with_user(self.user_hod).search([("is_my_work_item", "=", True)]),
        )
        self.assertNotIn(
            self.request,
            self.Request.with_user(self.user_hod).search([("is_my_contribution", "=", True)]),
            "Active pending work must stay in My Work List, not My Contribute List.",
        )

        self.request.approver_ids.filtered(lambda a: a.user_id == self.user_hod).sudo().write({
            "status": "approved",
            "user_decision": "Approve",
        })

        self.assertIn(
            self.request,
            self.Request.with_user(self.user_hod).search([("is_my_contribution", "=", True)]),
            "Historical approver involvement must appear in My Contribute List after the action is no longer pending.",
        )

    def test_my_work_list_does_not_mix_closed_user_row_with_other_user_open_row(self):
        self.request.sudo().write({"state": "waiting"})
        self.request.approver_ids.filtered(lambda a: a.user_id == self.user_hod).sudo().write({
            "status": "approved",
            "user_decision": "Approve",
        })
        self.Approver.sudo().create({
            "user_id": self.user_outsider.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": True,
            "status": "new",
            "iteration_no": 1,
        })

        hod_scope = self.Request.with_user(self.user_hod)
        outsider_scope = self.Request.with_user(self.user_outsider)

        self.assertNotIn(
            self.request,
            hod_scope.search([("is_my_work_item", "=", True)]),
            "A user's closed decision row must not match another user's current open assignment.",
        )
        self.assertIn(
            self.request,
            outsider_scope.search([("is_my_work_item", "=", True)]),
            "The user with the actual open assignment must still see the work item.",
        )
        self.assertIn(
            self.request,
            hod_scope.search([("is_my_contribution", "=", True)]),
            "The previous approver must move to My Contribute List when no longer pending.",
        )

    def test_duplicate_request_policy_allows_by_default(self):
        duplicate = self.Request.sudo().create({
            "name": "REQ_ACCESS_DUP_DEFAULT",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "state": "waiting",
        })

        found = self.Request.action_find_existing_requests_by_request_owner_id(
            self.category.id,
            self.user_hod.id,
        )

        self.assertTrue(duplicate)
        self.assertEqual(found, [], "Categories must allow duplicate requester records by default.")

    def test_duplicate_request_policy_blocks_matching_existing_request(self):
        self.category.sudo().write({
            "allowed_duplicate": False,
            "allow_duplicate_domain": "[('state', '=', 'waiting')]",
        })
        blocker = self.Request.sudo().create({
            "name": "REQ_ACCESS_DUP_BLOCK",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "state": "waiting",
        })

        found = self.Request.action_find_existing_requests_by_request_owner_id(
            self.category.id,
            self.user_hod.id,
        )

        self.assertIn(blocker.id, [item["id"] for item in found])

    def test_duplicate_request_policy_ignores_non_matching_domain(self):
        self.category.sudo().write({
            "allowed_duplicate": False,
            "allow_duplicate_domain": "[('state', '=', 'completed')]",
        })
        self.Request.sudo().create({
            "name": "REQ_ACCESS_DUP_OPEN",
            "category_id": self.category.id,
            "request_owner_id": self.user_hod.id,
            "state": "waiting",
        })

        found = self.Request.action_find_existing_requests_by_request_owner_id(
            self.category.id,
            self.user_hod.id,
        )

        self.assertEqual(found, [])

    def test_history_group_exists_for_manual_assignment(self):
        history_group = self.env.ref("workflow_engine.group_workflow_view_history_user")
        self.assertTrue(history_group.exists())
        self.assertEqual(history_group.name, "WF: View History User")

    def test_category_form_exposes_history_toggle_and_domain_builder(self):
        view = self.env.ref("workflow_engine.workflow_approval_category_view_form")
        arch = self.Category.get_view(view_id=view.id, view_type="form")["arch"]

        self.assertIn('name="enable_request_history"', arch)
        self.assertIn('name="request_history_domain"', arch)
        self.assertIn("History Domain", arch)
        self.assertIn("widget=\"domain\"", arch)

    def test_request_model_exposes_request_owner_position_field(self):
        self.assertIn("request_owner_position", self.Request._fields)

    def test_child_request_model_exposes_history_count_field(self):
        self.assertIn("wf_history_count", self.env["approval.child.mixin"]._fields)

    def test_child_request_model_exposes_history_detail_action(self):
        self.assertTrue(
            hasattr(self.env["approval.child.mixin"], "action_open_workflow_history_detail")
        )
