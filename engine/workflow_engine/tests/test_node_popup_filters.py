# -*- coding: utf-8 -*-

from uuid import uuid4

from lxml import etree

from odoo.tests import common


class TestNodePopupFilters(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.MetaAction = cls.env["workflow.category.version.meta.task.action"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Request = cls.env["workflow.base.approval.request"]

        cls.user_admin = cls.env.ref("base.user_admin")
        unique = uuid4().hex[:8]
        cls.user_demo = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Popup Worker",
            "login": f"popup_worker_{unique}",
            "email": f"popup_worker_{unique}@example.com",
        })

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.create({
            "name": "Popup Filter Category",
            "res_model": base_request_model.id,
        })
        cls.version = cls.Version.create({
            "name": "v_popup",
            "category_id": cls.category.id,
            "is_active": True,
        })
        cls.category.write({"active_version_id": cls.version.id})

        cls.meta_submission = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Submission",
            "node_id": "Task_Submission",
            "node_type": "userTask",
        })
        cls.meta_hod = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "HOD",
            "node_id": "Task_HOD",
            "node_type": "userTask",
        })
        cls.meta_it = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "IT Implementation",
            "node_id": "Task_IT",
            "node_type": "userTask",
        })
        cls.action_submit = cls.MetaAction.create({
            "name": "Submit",
            "meta_task_id": cls.meta_submission.id,
            "source_id": cls.meta_submission.node_id,
            "source_name": cls.meta_submission.name,
            "source_node_type": cls.meta_submission.node_type,
            "target_id": cls.meta_hod.node_id,
            "target_name": cls.meta_hod.name,
            "target_node_type": cls.meta_hod.node_type,
            "node_id": "Flow_Submission_HOD_Submit",
            "version_id": cls.version.id,
        })
        cls.action_rework = cls.MetaAction.create({
            "name": "Rework",
            "meta_task_id": cls.meta_hod.id,
            "source_id": cls.meta_hod.node_id,
            "source_name": cls.meta_hod.name,
            "source_node_type": cls.meta_hod.node_type,
            "target_id": cls.meta_submission.node_id,
            "target_name": cls.meta_submission.name,
            "target_node_type": cls.meta_submission.node_type,
            "node_id": "Flow_HOD_Submission_Rework",
            "version_id": cls.version.id,
        })
        cls.action_approve = cls.MetaAction.create({
            "name": "Approve",
            "meta_task_id": cls.meta_hod.id,
            "source_id": cls.meta_hod.node_id,
            "source_name": cls.meta_hod.name,
            "source_node_type": cls.meta_hod.node_type,
            "target_id": cls.meta_it.node_id,
            "target_name": cls.meta_it.name,
            "target_node_type": cls.meta_it.node_type,
            "node_id": "Flow_HOD_IT_Approve",
            "version_id": cls.version.id,
        })

        # Older version metadata to ensure popup does not drop historical rows.
        cls.old_version = cls.Version.create({
            "name": "v_popup_old",
            "category_id": cls.category.id,
            "is_active": False,
        })
        cls.meta_old = cls.MetaTask.create({
            "version_id": cls.old_version.id,
            "name": "Legacy Target",
            "node_id": "Task_Old",
            "node_type": "userTask",
        })

        cls.request = cls.Request.create({
            "name": "REQ_POPUP_001",
            "category_id": cls.category.id,
            "current_node_id": cls.meta_hod.node_id,
            "previous_node_id": cls.meta_submission.node_id,
        })

        cls.row_submission_assignment = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_submission.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "closed",
            "user_decision": "Submit",
            "iteration_no": 1,
        })
        cls.row_submission_decision = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_submission.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Submit",
            "iteration_no": 1,
        })
        cls.row_hod_assignment = cls.Approver.create({
            "user_id": cls.user_demo.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "closed",
            "iteration_no": 2,
        })
        cls.row_hod_decision_rework = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Rework",
            "iteration_no": 2,
        })
        cls.row_hod_decision_approve = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Approve",
            "iteration_no": 2,
        })
        cls.row_hod_decision_legacy_target = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Escalate",
            "iteration_no": 2,
        })
        cls.row_hod_decision_written_on_assignment = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Approve",
            "iteration_no": 2,
        })
        cls.row_hod_routed_audit = cls.Approver.create({
            "user_id": cls.user_demo.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "closed",
            "user_decision": "Routed",
            "is_routed_audit": True,
            "iteration_no": 2,
        })
        cls.row_noise_current_without_required = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "new",
            "iteration_no": 2,
        })

    def _ids_from_action_domain(self, action):
        domain = action.get("domain", [])
        if not domain:
            return set()
        first = domain[0]
        if isinstance(first, tuple) and first[0] == "id" and first[1] == "in":
            return set(first[2] or [])
        return set()

    def test_submission_node_popup_rows(self):
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_submission.node_id,
            self.meta_submission.name,
            False,
        )
        ids = self._ids_from_action_domain(action)
        self.assertIn(self.row_submission_assignment.id, ids)
        self.assertIn(self.row_submission_decision.id, ids)
        self.assertNotIn(self.row_hod_assignment.id, ids)
        self.assertNotIn(self.row_hod_decision_rework.id, ids)
        self.assertNotIn(self.row_hod_decision_written_on_assignment.id, ids)
        self.assertNotIn("search_default_group_by_iteration", action.get("context", {}))

    def test_submission_actor_history_ignores_rework_rows(self):
        # Last real submitter should be reused for reassignment after rework.
        self.Approver.create({
            "user_id": self.user_demo.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_submission.id,
            "previous_meta_id": self.meta_submission.id,
            "required": False,
            "status": "closed",
            "user_decision": "Submit",
            "iteration_no": 3,
        })
        # Rework audit row is newer, but it must not replace the submit actor.
        self.Approver.create({
            "user_id": self.user_admin.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_submission.id,
            "previous_meta_id": self.meta_hod.id,
            "required": False,
            "status": "approved",
            "user_decision": "Rework",
            "iteration_no": 3,
        })

        submit_actor = self.request._get_latest_submission_actor_from_history(self.meta_submission.node_id)
        self.assertEqual(submit_actor, self.user_demo)

    def test_hod_node_popup_rows(self):
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_hod.node_id,
            self.meta_hod.name,
            True,
        )
        ids = self._ids_from_action_domain(action)
        # Required assignment on HOD node.
        self.assertIn(self.row_hod_assignment.id, ids)
        # Decision rows made on HOD node.
        self.assertIn(self.row_hod_decision_rework.id, ids)
        self.assertIn(self.row_hod_decision_approve.id, ids)
        self.assertIn(self.row_hod_routed_audit.id, ids)
        # Historical row from older metadata version must remain visible.
        self.assertIn(self.row_hod_decision_legacy_target.id, ids)
        # Noise row (not required and no decision) must stay hidden.
        self.assertNotIn(self.row_noise_current_without_required.id, ids)

    def test_popup_context_contains_node_payload(self):
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_hod.node_id,
            self.meta_hod.name,
            True,
        )
        ctx = action.get("context", {})
        self.assertTrue(ctx.get("wf_allow_dialog_view_switch"))
        self.assertEqual(ctx.get("wf_node_popup_request_id"), self.request.id)
        self.assertEqual(ctx.get("wf_node_popup_node_id"), self.meta_hod.node_id)
        self.assertEqual(ctx.get("wf_node_popup_node_name"), self.meta_hod.name)
        self.assertTrue(ctx.get("wf_node_popup_is_current_node"))
        self.assertEqual(ctx.get("wf_node_popup_default_view"), "list")
        self.assertEqual(ctx.get("search_default_decided_users_only"), 1)

    def test_force_view_kanban_prioritizes_kanban(self):
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_hod.node_id,
            self.meta_hod.name,
            True,
            "kanban",
        )
        self.assertEqual(action.get("view_mode"), "list,kanban,form")
        self.assertEqual([view[1] for view in action.get("views", [])[:2]], ["list", "kanban"])
        self.assertEqual(action.get("mobile_view_mode"), "kanban")
        self.assertEqual(action.get("context", {}).get("wf_node_popup_default_view"), "kanban")

    def test_assignment_labels_show_assigned_vs_closed(self):
        self.assertIn("Auto-closed", self.row_hod_assignment.to_activity_label)
        self.assertEqual(self.row_hod_assignment.from_activity_label, "HOD")
        self.assertIn("Submission", self.row_hod_assignment.to_activity_label)
        self.assertEqual(self.row_hod_decision_approve.to_activity_label, "IT Implementation")

    def test_decision_labels_resolve_from_action_map(self):
        self.assertEqual(self.row_hod_decision_written_on_assignment.from_activity_label, "HOD")
        self.assertEqual(self.row_hod_decision_written_on_assignment.to_activity_label, "IT Implementation")
        self.assertEqual(
            self.row_hod_decision_written_on_assignment.activity_flow,
            "HOD -> IT Implementation (Approve)",
        )

    def test_has_decision_ignores_whitespace(self):
        row = self.Approver.create({
            "user_id": self.user_admin.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": False,
            "status": "closed",
            "user_decision": "   ",
            "iteration_no": 2,
        })
        self.assertFalse(row.has_decision)

    def test_routed_audit_rows_keep_raw_decision_but_not_decided_user_flag(self):
        self.assertTrue(self.row_hod_routed_audit.has_decision)
        self.assertFalse(self.row_hod_routed_audit.counts_as_decided_user)

    def test_init_keeps_delegation_history_out_of_decided_users(self):
        shared_row = self.Approver.create({
            "user_id": self.user_admin.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": False,
            "status": "closed",
            "user_decision": "Shared",
            "iteration_no": 2,
        })
        redirected_row = self.Approver.create({
            "user_id": self.user_demo.id,
            "request_id": self.request.id,
            "current_meta_id": self.meta_hod.id,
            "previous_meta_id": self.meta_submission.id,
            "required": False,
            "status": "closed",
            "user_decision": "Redirected",
            "iteration_no": 2,
        })
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET counts_as_decided_user = TRUE
             WHERE id IN %s
            """,
            [tuple((shared_row | redirected_row).ids)],
        )

        self.Approver.init()
        rows = shared_row | redirected_row | self.row_hod_decision_approve | self.row_hod_routed_audit
        rows.invalidate_recordset([
            "counts_as_decided_user",
            "decision_history_kind",
            "show_in_decision_history",
        ])

        self.assertFalse(shared_row.counts_as_decided_user)
        self.assertFalse(redirected_row.counts_as_decided_user)
        self.assertEqual(shared_row.decision_history_kind, "delegation_decision")
        self.assertEqual(redirected_row.decision_history_kind, "delegation_decision")
        self.assertTrue(shared_row.show_in_decision_history)
        self.assertTrue(redirected_row.show_in_decision_history)
        self.assertTrue(self.row_hod_decision_approve.counts_as_decided_user)
        self.assertFalse(self.row_hod_routed_audit.counts_as_decided_user)

    def test_request_decisions_tab_excludes_routed_audit_rows(self):
        decision_ids = set(self.request.approver_decisions_ids.ids)
        self.assertIn(self.row_submission_decision.id, decision_ids)
        self.assertIn(self.row_hod_decision_approve.id, decision_ids)
        self.assertNotIn(self.row_hod_routed_audit.id, decision_ids)

    def test_approver_search_view_uses_decided_user_filter(self):
        arch = self.env.ref("workflow_engine.workflow_approval_approver_view_search").arch_db
        self.assertIn('name="decided_users_only"', arch)
        self.assertIn("counts_as_decided_user", arch)

    def test_user_facing_activity_views_hide_technical_duplicate_columns(self):
        form_arch = self.env.ref("workflow_engine.approval_base_request_view_form").arch_db
        compact_arch = self.env.ref("workflow_engine.workflow_approval_approver_view_compact_list").arch_db
        kanban_arch = self.env.ref("workflow_engine.workflow_approval_approver_view_kanban").arch_db
        mobile_kanban_arch = self.env.ref("workflow_engine.workflow_approval_approver_view_kanban_mobile").arch_db
        search_arch = self.env.ref("workflow_engine.workflow_approval_approver_view_search").arch_db
        technical_groups = "workflow_engine.group_workflow_technical_admin,base.group_system"
        form_root = etree.fromstring(form_arch.encode())
        compact_root = etree.fromstring(compact_arch.encode())
        search_root = etree.fromstring(search_arch.encode())

        self.assertIn("record.to_activity_label and record.to_activity_label.value", form_arch)
        self.assertNotIn("record.current_meta_id and record.current_meta_id.value", form_arch)

        self.assertTrue(
            form_root.xpath(
                ".//field[@name='current_meta_id' and @string='Activity (Technical)' and @groups=$groups]",
                groups=technical_groups,
            ),
            "Request form should keep current_meta_id as a technical-only field.",
        )
        self.assertTrue(
            form_root.xpath(
                ".//field[@name='previous_meta_id' and @string='From Activity (Technical)' and @groups=$groups]",
                groups=technical_groups,
            ),
            "Request form should keep previous_meta_id as a technical-only field.",
        )
        self.assertTrue(
            compact_root.xpath(
                ".//field[@name='current_meta_id' and @string='Activity (Technical)' and @groups=$groups]",
                groups=technical_groups,
            ),
            "Compact popup list should hide the technical activity column from normal users.",
        )
        self.assertTrue(
            search_root.xpath(
                ".//filter[@name='group_by_activity' and @groups=$groups and @context=\"{'group_by': 'current_meta_id'}\"]",
                groups=technical_groups,
            ),
            "Technical activity grouping should be admin-only in the approver search view.",
        )
        self.assertIn('name="work_email"', kanban_arch)
        self.assertNotIn('name="ext_phone"', kanban_arch)
        self.assertNotIn("fa-phone", kanban_arch)
        self.assertIn('name="work_email"', mobile_kanban_arch)
        self.assertNotIn('name="ext_phone"', mobile_kanban_arch)
        self.assertNotIn("fa-phone", mobile_kanban_arch)


class TestNodePopupFiltersComplex(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Request = cls.env["workflow.base.approval.request"]

        unique = uuid4().hex[:8]
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.user_nurse = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Flow Nurse",
            "login": f"flow_nurse_{unique}",
            "email": f"flow_nurse_{unique}@example.com",
        })
        cls.user_doctor = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Flow Doctor",
            "login": f"flow_doctor_{unique}",
            "email": f"flow_doctor_{unique}@example.com",
        })

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.create({
            "name": "Popup Filter Category Complex",
            "res_model": base_request_model.id,
        })
        cls.version = cls.Version.create({
            "name": "v_popup_complex",
            "category_id": cls.category.id,
            "is_active": True,
        })
        cls.category.write({"active_version_id": cls.version.id})

        cls.meta_submission = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Submission",
            "node_id": "Task_Submission",
            "node_type": "userTask",
        })
        cls.meta_hod = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "HOD Decision",
            "node_id": "Task_HOD",
            "node_type": "userTask",
        })
        cls.meta_nurse = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Nurse",
            "node_id": "Task_Nurse",
            "node_type": "userTask",
        })
        cls.meta_doctor = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Doctor",
            "node_id": "Task_Doctor",
            "node_type": "userTask",
        })
        cls.meta_verify = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Nurse Verify",
            "node_id": "Task_Verify",
            "node_type": "userTask",
        })
        cls.meta_done = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Done",
            "node_id": "Task_Done",
            "node_type": "endEvent",
        })
        cls.meta_nurse_rework = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Nurse Rework",
            "node_id": "Task_Nurse_Rework",
            "node_type": "userTask",
        })
        cls.meta_doctor_rework = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Doctor Rework",
            "node_id": "Task_Doctor_Rework",
            "node_type": "userTask",
        })
        cls.meta_rejected = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Rejected",
            "node_id": "Task_Rejected",
            "node_type": "endEvent",
        })

        cls.request = cls.Request.create({
            "name": "REQ_POPUP_COMPLEX",
            "category_id": cls.category.id,
            "current_node_id": cls.meta_verify.node_id,
            "previous_node_id": cls.meta_doctor.node_id,
        })

        cls.hod_assignment = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "closed",
            "iteration_no": 1,
        })
        cls.submission_assignment = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_submission.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": True,
            "status": "closed",
            "iteration_no": 1,
        })
        cls.submission_submit_decision_cycle_1 = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_submission.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Submit",
            "iteration_no": 1,
        })
        cls.hod_rework_decision = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Rework",
            "iteration_no": 1,
        })
        cls.hod_reject_decision = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            # Keep status non-terminal to avoid unrelated request-status recompute
            # side effects in this popup-filter focused test.
            "status": "approved",
            "user_decision": "Reject",
            "iteration_no": 2,
        })
        cls.hod_approve_decision = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_hod.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Approve",
            "iteration_no": 2,
        })
        cls.submission_submit_decision_cycle_3 = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_submission.id,
            "previous_meta_id": cls.meta_submission.id,
            "required": False,
            "status": "approved",
            "user_decision": "Submit",
            "iteration_no": 3,
        })
        cls.verify_assignment = cls.Approver.create({
            "user_id": cls.user_nurse.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_verify.id,
            "previous_meta_id": cls.meta_doctor.id,
            "required": True,
            "status": "new",
            "iteration_no": 2,
        })
        cls.verify_done_decision = cls.Approver.create({
            "user_id": cls.user_nurse.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_verify.id,
            "previous_meta_id": cls.meta_doctor.id,
            "required": False,
            "status": "approved",
            "user_decision": "Done",
            "iteration_no": 2,
        })
        cls.verify_nurse_rework_decision = cls.Approver.create({
            "user_id": cls.user_nurse.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_verify.id,
            "previous_meta_id": cls.meta_doctor.id,
            "required": False,
            "status": "approved",
            "user_decision": "Go to Nurse",
            "iteration_no": 3,
        })
        cls.verify_doctor_rework_decision = cls.Approver.create({
            "user_id": cls.user_doctor.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_verify.id,
            "previous_meta_id": cls.meta_doctor.id,
            "required": False,
            "status": "approved",
            "user_decision": "Go to Doctor",
            "iteration_no": 3,
        })
        cls.noise_current_without_required = cls.Approver.create({
            "user_id": cls.user_admin.id,
            "request_id": cls.request.id,
            "current_meta_id": cls.meta_verify.id,
            "previous_meta_id": cls.meta_doctor.id,
            "required": False,
            "status": "new",
            "iteration_no": 3,
        })

        cls.env.flush_all()

    def _ids_from_action_domain(self, action):
        domain = action.get("domain", [])
        if not domain:
            return set()
        first = domain[0]
        if isinstance(first, tuple) and first[0] == "id" and first[1] == "in":
            return set(first[2] or [])
        return set()

    def test_hod_node_shows_assignment_and_all_decisions_from_hod(self):
        self.env.flush_all()
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_hod.node_id,
            self.meta_hod.name,
            False,
        )
        ids = self._ids_from_action_domain(action)
        self.assertIn(self.hod_assignment.id, ids)
        self.assertIn(self.hod_rework_decision.id, ids)
        self.assertIn(self.hod_reject_decision.id, ids)
        self.assertIn(self.hod_approve_decision.id, ids)
        self.assertNotIn(self.verify_assignment.id, ids)

    def test_verify_node_shows_assignment_and_all_decisions_from_verify(self):
        self.env.flush_all()
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_verify.node_id,
            self.meta_verify.name,
            True,
        )
        ids = self._ids_from_action_domain(action)
        self.assertIn(self.verify_assignment.id, ids)
        self.assertIn(self.verify_done_decision.id, ids)
        self.assertIn(self.verify_nurse_rework_decision.id, ids)
        self.assertIn(self.verify_doctor_rework_decision.id, ids)
        self.assertNotIn(self.noise_current_without_required.id, ids)

    def test_submission_node_keeps_resubmit_history_across_iterations(self):
        self.env.flush_all()
        action = self.Approver.action_open_node_approvers(
            self.request.id,
            self.meta_submission.node_id,
            self.meta_submission.name,
            False,
        )
        ids = self._ids_from_action_domain(action)
        self.assertIn(self.submission_assignment.id, ids)
        self.assertIn(self.submission_submit_decision_cycle_1.id, ids)
        self.assertIn(self.submission_submit_decision_cycle_3.id, ids)
        self.assertNotIn(self.verify_assignment.id, ids)


class TestMetaTaskResolution(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.Request = cls.env["workflow.base.approval.request"]

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.create({
            "name": "Meta Resolve Category",
            "res_model": base_request_model.id,
        })
        cls.version = cls.Version.create({
            "name": "v_meta_resolve",
            "category_id": cls.category.id,
            "is_active": True,
        })
        cls.category.write({"active_version_id": cls.version.id})

        # Duplicate node_id on purpose (legacy + current naming).
        cls.meta_submission_legacy = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Task",
            "node_id": "Task_1",
            "node_type": "userTask",
        })
        cls.meta_submission = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "Submission",
            "node_id": "Task_1",
            "node_type": "userTask",
        })
        cls.meta_hod = cls.MetaTask.create({
            "version_id": cls.version.id,
            "name": "HOD",
            "node_id": "Activity_HOD",
            "node_type": "userTask",
        })

        cls.request = cls.Request.create({
            "name": "REQ_META_RESOLVE",
            "category_id": cls.category.id,
            "current_node_id": cls.meta_hod.node_id,
            "previous_node_id": cls.meta_submission.node_id,
            "current_activity_name": cls.meta_hod.name,
            "previous_activity_name": cls.meta_submission.name,
        })

    def test_resolve_meta_task_prefers_matching_node_name(self):
        resolved = self.request._resolve_meta_task_for_node("Task_1", "Submission")
        self.assertEqual(resolved.id, self.meta_submission.id)

    def test_resolve_meta_task_fallbacks_to_newest_when_name_missing(self):
        resolved = self.request._resolve_meta_task_for_node("Task_1")
        self.assertEqual(resolved.id, self.meta_submission.id)

    def test_resolve_meta_task_generic_task_name_prefers_submission(self):
        resolved = self.request._resolve_meta_task_for_node("Task_1", "Task")
        self.assertEqual(resolved.id, self.meta_submission.id)
