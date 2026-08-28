# -*- coding: utf-8 -*-

import inspect
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch

from lxml import etree
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import common

from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin
from odoo.addons.workflow_engine.models.workflow_base_approval_request import ApprovalBaseRequest
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import NODE_TYPE


def _fake_node(node_id, name):
    return SimpleNamespace(attrib={"id": node_id, "name": name})


class _FakeTrackingEngine:
    def __init__(self, elements=None, next_map=None, start_ids=None, end_ids=None, start_event=None):
        self._elements = elements or {}
        self._next_map = next_map or {}
        self._start_ids = set(start_ids or [])
        self._end_ids = set(end_ids or [])
        self._start_event = start_event

    def get_element_by_id(self, node_id):
        return self._elements.get(node_id)

    def get_next_elements(self, node, form_data=None, evaluate_conditions=True):
        return self._next_map.get(node.attrib.get("id"), [])

    def is_end_event(self, node):
        return bool(node) and node.attrib.get("id") in self._end_ids

    def is_start_event(self, node):
        return bool(node) and node.attrib.get("id") in self._start_ids

    def get_start_event(self):
        return self._start_event


class _TrackingHarness:
    def __init__(
        self,
        env,
        version,
        *,
        current_node_id,
        current_activity_name,
        previous_node_id=None,
        previous_activity_name=None,
    ):
        self.env = env
        self.version_id = version
        self.id = 0
        self.current_node_id = current_node_id
        self.current_activity_name = current_activity_name
        self.previous_node_id = previous_node_id
        self.previous_activity_name = previous_activity_name
        self.next_node_id = False
        self.next_activity_name = False
        self.next_is_end_event = False
        self.state = False
        self.request_status = False
        self.active_branch_node_ids = []
        self._captured_context = {}

    def ensure_one(self):
        return None

    def with_context(self, **kwargs):
        self._captured_context.update(kwargs)
        return self

    def _resolve_meta_task_for_node(self, node_id, node_name=None, prefer_submission=None):
        return ApprovalChildMixin._resolve_meta_task_for_node(
            self,
            node_id,
            node_name=node_name,
            prefer_submission=prefer_submission,
        )

    def _is_submission_meta_task(self, meta_task):
        return ApprovalChildMixin._is_submission_meta_task(self, meta_task)

    def _should_reset_request_to_submit_on_entry(self, engine, current_node=None, next_node=None):
        return ApprovalChildMixin._should_reset_request_to_submit_on_entry(
            self,
            engine=engine,
            current_node=current_node,
            next_node=next_node,
        )

    def _resolve_terminal_status(self, next_node):
        return ApprovalChildMixin._resolve_terminal_status(self, next_node)


class _ForceTransitionHarness(_TrackingHarness):
    def __init__(self, env, version, **kwargs):
        super().__init__(env, version, **kwargs)
        self._last_message = False
        self._force_jump_called = False

    def _resolve_force_transition_meta_action(self, target_node_id):
        return False

    def _workflow_safe_message_post(self, body, message_type="comment"):
        self._last_message = {
            "body": body,
            "message_type": message_type,
        }

    def _get_form_data(self):
        return {}

    def _force_jump_without_meta_action(
        self,
        engine,
        next_node,
        re_assign_approvals,
        audit_comment=False,
    ):
        current_node = engine.get_element_by_id(self.current_node_id) if self.current_node_id else None
        if current_node is None:
            current_node = engine.get_start_event()
        ApprovalChildMixin._update_tracking_fields(
            self,
            engine=engine,
            form_data={},
            current_node=current_node,
            next_node=next_node,
            meta_action=False,
        )
        self._force_jump_called = True
        return None


class _FakeSequence:
    def __init__(self, values=None):
        self._values = list(values or [])
        self.calls = 0

    def next_by_id(self):
        self.calls += 1
        if self._values:
            return self._values.pop(0)
        return False


class _FakeCategory:
    def __init__(self, *, automated_sequence=True, sequence_id=False, name="Workflow Category"):
        self.automated_sequence = automated_sequence
        self.sequence_id = sequence_id
        self.name = name
        self.display_name = name


class _FakeMetaTask:
    def __init__(self, node_id, name):
        self.node_id = node_id
        self.name = name

    def __getitem__(self, item):
        if isinstance(item, slice):
            return self
        raise TypeError("Fake meta task only supports slicing access.")

    def __bool__(self):
        return True


class _FakeSubmissionEngine:
    def __init__(self, submission_node_id):
        self._submission_node = _fake_node(submission_node_id, "Submission")

    def get_submission_task(self):
        return self._submission_node


class _LazySequenceHarness:
    def __init__(self, env, version, category, *, name="New", approver_rows=None):
        self.env = env
        self.version_id = version
        self.category_id = category
        self.name = name
        self.id = 0
        self._captured_context = {}
        self._base_request = SimpleNamespace(approver_ids=list(approver_rows or []))

    def ensure_one(self):
        return None

    def with_context(self, **kwargs):
        self._captured_context.update(kwargs)
        return self

    def write(self, vals):
        self.name = vals.get("name", self.name)
        return True

    def _resolve_base_request_record(self):
        return self._base_request

    def _is_submission_meta_task(self, meta_task):
        return ApprovalChildMixin._is_submission_meta_task(self, meta_task)

    def _workflow_normalize_folio_name(self, value):
        return ApprovalChildMixin._workflow_normalize_folio_name(value)

    def _workflow_name_uses_draft_placeholder(self, value):
        return ApprovalChildMixin._workflow_name_uses_draft_placeholder(self, value)

    def _workflow_has_prior_submission_history(self, submission_node_id):
        return ApprovalChildMixin._workflow_has_prior_submission_history(self, submission_node_id)


class TestWorkflowBaseApprovalRequest(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.Attachment = cls.env["ir.attachment"]
        cls.User = cls.env["res.users"]

        unique = uuid4().hex[:8]
        workflow_user_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        workflow_admin_group = cls.env.ref("workflow_engine.group_workflow_approval_admin")
        cls.reviewer = cls.User.with_context(no_reset_password=True).create(
            {
                "name": "Workflow Reviewer",
                "login": f"wf_reviewer_{unique}",
                "email": f"wf_reviewer_{unique}@example.com",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, workflow_user_group.id])],
            }
        )
        cls.approval_admin = cls.User.with_context(no_reset_password=True).create(
            {
                "name": "Workflow Approval Admin",
                "login": f"wf_admin_{unique}",
                "email": f"wf_admin_{unique}@example.com",
                "group_ids": [(6, 0, [workflow_admin_group.id])],
            }
        )

        request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.sudo().create(
            {
                "name": "Workflow Request Status Category",
                "res_model": request_model.id,
                "approval_minimum": 2,
                "zero_trust_enforced": False,
            }
        )
        cls.version = cls.Version.sudo().create(
            {
                "name": "v_test_status",
                "category_id": cls.category.id,
                "is_active": True,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})

        cls.meta_submission = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Submission",
                "node_id": "Task_Submission",
                "node_type": "userTask",
            }
        )
        cls.meta_hod = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "HOD Decision",
                "node_id": "Task_HOD_Decision",
                "node_type": "userTask",
            }
        )

    def _create_request(self):
        return self.Request.sudo().create(
            {
                "name": f"REQ_STATUS_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.env.user.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_activity_name": self.meta_hod.name,
                "previous_activity_name": self.meta_submission.name,
            }
        )

    def _create_approver(self, request, user, status, required=False):
        return self.Approver.sudo().create(
            {
                "request_id": request.id,
                "user_id": user.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": status,
                "required": required,
                "iteration_no": 1,
            }
        )

    def _create_user_with_employee(self, *, work_email):
        unique = uuid4().hex[:8]
        user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Workflow Approver {unique}",
                "login": f"wf_approver_{unique}",
                "email": f"wf_approver_{unique}@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
                "company_id": self.env.company.id,
                "company_ids": [Command.set([self.env.company.id])],
            }
        )
        self.env["hr.employee"].sudo().create(
            {
                "name": f"Workflow Approver Employee {unique}",
                "user_id": user.id,
                "company_id": self.env.company.id,
                "x_emp_code": f"WFAPP{unique}",
                "work_email": work_email,
            }
        )
        return user

    def test_compute_request_status_requires_minimum_and_required(self):
        request = self._create_request()
        required_approver = self._create_approver(
            request=request,
            user=self.env.user,
            status="approved",
            required=True,
        )
        optional_approver = self._create_approver(
            request=request,
            user=self.reviewer,
            status="waiting",
        )

        request.invalidate_recordset(["request_status"])
        self.assertEqual(
            request.request_status,
            "pending",
            "Request must stay pending while minimum approvals are not met.",
        )

        optional_approver.write({"status": "approved"})
        request.invalidate_recordset(["request_status"])
        self.assertEqual(
            request.request_status,
            "approved",
            "Request must be approved when minimum and required approvals are met.",
        )

        required_approver.write({"status": "refused"})
        request.invalidate_recordset(["request_status"])
        self.assertEqual(
            request.request_status,
            "refused",
            "Refused status must take precedence over approved/pending states.",
        )

    def test_approver_work_email_only_exposes_allowed_company_domain(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.request_owner_email_domains",
            "nagaworld.com,nagworld.com",
        )
        request = self._create_request()
        user = self._create_user_with_employee(
            work_email=f"wf_approver_{uuid4().hex[:8]}@gmail.com"
        )
        approver = self._create_approver(request=request, user=user, status="approved")

        self.assertEqual(approver.work_email, "")

        user.employee_id.sudo().write(
            {"work_email": f"wf_approver_{uuid4().hex[:8]}@nagaworld.com"}
        )
        approver.invalidate_recordset(["work_email"])

        self.assertEqual(approver.work_email, user.employee_id.work_email)

    def test_workflow_reference_labels_use_category_and_active_version(self):
        request = self._create_request()

        self.assertEqual(request.workflow_category_label, self.category.display_name)
        self.assertEqual(request.workflow_version_label, self.version.display_name)

    def test_approvers_tab_is_visible_only_to_workflow_admin(self):
        view = self.env.ref("workflow_engine.approval_base_request_view_form")

        reviewer_arch = self.Request.with_user(self.reviewer).get_view(
            view_id=view.id,
            view_type="form",
        )["arch"]
        reviewer_root = etree.fromstring(reviewer_arch.encode())
        self.assertFalse(
            reviewer_root.xpath("//page[@name='approvers']"),
            "Approval users must not see the Approver(s) tab.",
        )

        admin_arch = self.Request.with_user(self.approval_admin).get_view(
            view_id=view.id,
            view_type="form",
        )["arch"]
        admin_root = etree.fromstring(admin_arch.encode())
        approver_pages = admin_root.xpath("//page[@name='approvers']")
        self.assertTrue(
            approver_pages,
            "Workflow approval admins must still see the Approver(s) tab.",
        )
        self.assertTrue(
            approver_pages[0].xpath(".//field[@name='approver_ids']"),
            "The admin-only Approver(s) tab must still render the approver list.",
        )

    def test_version_compute_is_per_request_category(self):
        other_category = self.Category.sudo().create(
            {
                "name": "Workflow Request Status Category Other",
                "res_model": self.env["ir.model"]._get("workflow.base.approval.request").id,
                "approval_minimum": 1,
                "zero_trust_enforced": False,
            }
        )
        other_version = self.Version.sudo().create(
            {
                "name": "v_test_status_other",
                "category_id": other_category.id,
                "is_active": True,
            }
        )
        other_category.sudo().write({"active_version_id": other_version.id})

        requests = self.Request.sudo().create(
            [
                {
                    "name": f"REQ_VERSION_A_{uuid4().hex[:8]}",
                    "category_id": self.category.id,
                    "request_owner_id": self.env.user.id,
                },
                {
                    "name": f"REQ_VERSION_B_{uuid4().hex[:8]}",
                    "category_id": other_category.id,
                    "request_owner_id": self.env.user.id,
                },
            ]
        )

        self.assertEqual(requests[0].version_id, self.version)
        self.assertEqual(requests[1].version_id, other_version)

    def test_unsaved_draft_creator_can_submit_after_changing_request_owner(self):
        self.env["workflow.category.version.meta.task.action"].sudo().create(
            {
                "name": "Submit",
                "attr_label": "Submit",
                "action_button_label": "Submit",
                "meta_task_id": self.meta_submission.id,
                "source_id": self.meta_submission.node_id,
                "source_name": self.meta_submission.name,
                "source_node_type": "userTask",
                "target_id": self.meta_hod.node_id,
                "target_name": self.meta_hod.name,
                "target_node_type": "userTask",
                "flow_type": "userAction",
            }
        )
        draft = self.Request.new(
            {
                "name": "New",
                "category_id": self.category.id,
                "version_id": self.version.id,
                "request_owner_id": self.reviewer.id,
                "state": "draft",
            }
        )

        actor_node_id = draft._workflow_get_initial_actor_node_id()

        self.assertEqual(actor_node_id, self.meta_submission.node_id)
        self.assertTrue(draft.check_if_user_has_permission(draft))
        self.assertTrue(draft._workflow_can_execute_actor_node(actor_node_id, user=self.env.user))
        self.assertFalse(draft._get_transition_access_block_reason())

        buttons = self.Request.workflow_get_visible_buttons_snapshot_virtual(
            snapshot_values={
                "name": "New",
                "category_id": {"id": self.category.id, "display_name": self.category.display_name},
                "version_id": {"id": self.version.id, "display_name": self.version.display_name},
                "request_owner_id": {"id": self.reviewer.id, "display_name": self.reviewer.display_name},
                "state": "draft",
            },
            task_node_id=actor_node_id,
        )
        self.assertTrue(buttons)
        self.assertFalse(buttons[0]["disabled"], buttons[0]["disabled_reason"])

    def test_visible_buttons_use_technical_action_name_as_action_key(self):
        technical_name = f"approve_internal_{uuid4().hex[:6]}"
        action = self.env["workflow.category.version.meta.task.action"].sudo().create(
            {
                "name": technical_name,
                "attr_label": "Approve Display",
                "action_button_label": "Approve Display",
                "meta_task_id": self.meta_hod.id,
                "source_id": self.meta_hod.node_id,
                "source_name": self.meta_hod.name,
                "source_node_type": "userTask",
                "target_id": "EndEvent_Approved",
                "target_name": "Approved",
                "target_node_type": "endEvent",
                "flow_type": "userAction",
            }
        )

        request = self._create_request()
        buttons = request.workflow_get_visible_buttons_snapshot(task_node_id=self.meta_hod.node_id)
        payload = next(button for button in buttons if button["meta_action_id"] == action.id)

        self.assertEqual(payload["label"], "Approve Display")
        self.assertEqual(payload["action_key"], technical_name)

    def test_compute_request_status_prioritizes_new(self):
        request = self._create_request()
        self._create_approver(
            request=request,
            user=self.env.user,
            status="approved",
        )
        self._create_approver(
            request=request,
            user=self.reviewer,
            status="new",
        )

        request.invalidate_recordset(["request_status"])
        self.assertEqual(
            request.request_status,
            "new",
            "Any pending new approver row must keep request status at new.",
        )

    def test_update_tracking_fields_resets_submission_target_to_submit(self):
        harness = _TrackingHarness(
            self.env,
            self.version,
            current_node_id=self.meta_hod.node_id,
            current_activity_name=self.meta_hod.name,
            previous_node_id=self.meta_submission.node_id,
            previous_activity_name=self.meta_submission.name,
        )
        current_node = _fake_node(self.meta_hod.node_id, self.meta_hod.name)
        next_node = _fake_node(self.meta_submission.node_id, self.meta_submission.name)
        downstream_node = _fake_node("Event_Submit", "Submit")
        engine = _FakeTrackingEngine(
            elements={
                self.meta_hod.node_id: current_node,
                self.meta_submission.node_id: next_node,
            },
            next_map={self.meta_submission.node_id: [downstream_node]},
        )

        ApprovalChildMixin._update_tracking_fields(
            harness,
            engine=engine,
            form_data={},
            current_node=current_node,
            next_node=next_node,
        )

        self.assertEqual(harness.current_node_id, self.meta_submission.node_id)
        self.assertEqual(harness.state, "new")
        self.assertEqual(harness.request_status, "new")

    def test_update_tracking_fields_resets_flagged_target_to_submit(self):
        harness = _TrackingHarness(
            self.env,
            self.version,
            current_node_id=self.meta_hod.node_id,
            current_activity_name=self.meta_hod.name,
            previous_node_id=self.meta_submission.node_id,
            previous_activity_name=self.meta_submission.name,
        )
        requestor_rework = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Requestor Rework",
                "node_id": f"Task_Requestor_Rework_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "reset_request_to_submit": True,
            }
        )
        current_node = _fake_node(self.meta_hod.node_id, self.meta_hod.name)
        next_node = _fake_node(requestor_rework.node_id, requestor_rework.name)
        downstream_node = _fake_node("Event_Resubmit", "Resubmit")
        engine = _FakeTrackingEngine(
            elements={
                self.meta_hod.node_id: current_node,
                requestor_rework.node_id: next_node,
            },
            next_map={requestor_rework.node_id: [downstream_node]},
        )

        ApprovalChildMixin._update_tracking_fields(
            harness,
            engine=engine,
            form_data={},
            current_node=current_node,
            next_node=next_node,
        )

        self.assertEqual(harness.current_node_id, requestor_rework.node_id)
        self.assertEqual(harness.state, "new")
        self.assertEqual(harness.request_status, "new")

    def test_update_tracking_fields_keeps_non_flagged_rework_waiting(self):
        harness = _TrackingHarness(
            self.env,
            self.version,
            current_node_id=self.meta_hod.node_id,
            current_activity_name=self.meta_hod.name,
            previous_node_id=self.meta_submission.node_id,
            previous_activity_name=self.meta_submission.name,
        )
        doctor_rework = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Doctor Rework",
                "node_id": f"Task_Doctor_Rework_{uuid4().hex[:6]}",
                "node_type": "userTask",
            }
        )
        current_node = _fake_node(self.meta_hod.node_id, self.meta_hod.name)
        next_node = _fake_node(doctor_rework.node_id, doctor_rework.name)
        downstream_node = _fake_node("Event_Submit_Doctor", "Submit")
        engine = _FakeTrackingEngine(
            elements={
                self.meta_hod.node_id: current_node,
                doctor_rework.node_id: next_node,
            },
            next_map={doctor_rework.node_id: [downstream_node]},
        )

        ApprovalChildMixin._update_tracking_fields(
            harness,
            engine=engine,
            form_data={},
            current_node=current_node,
            next_node=next_node,
        )

        self.assertEqual(harness.current_node_id, doctor_rework.node_id)
        self.assertEqual(harness.state, "waiting")
        self.assertEqual(harness.request_status, "pending")

    def test_force_transition_uses_submitter_rework_flag_for_new_state(self):
        harness = _ForceTransitionHarness(
            self.env,
            self.version,
            current_node_id=self.meta_hod.node_id,
            current_activity_name=self.meta_hod.name,
            previous_node_id=self.meta_submission.node_id,
            previous_activity_name=self.meta_submission.name,
        )
        requestor_rework = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Requestor Rework",
                "node_id": f"Task_Requestor_Force_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "reset_request_to_submit": True,
            }
        )
        current_node = _fake_node(self.meta_hod.node_id, self.meta_hod.name)
        next_node = _fake_node(requestor_rework.node_id, requestor_rework.name)
        downstream_node = _fake_node("Event_Resubmit", "Resubmit")
        engine = _FakeTrackingEngine(
            elements={
                self.meta_hod.node_id: current_node,
                requestor_rework.node_id: next_node,
            },
            next_map={requestor_rework.node_id: [downstream_node]},
        )

        with patch(
            "odoo.addons.workflow_engine.models.approval_child_mixin.BpmnEngine",
            return_value=engine,
        ):
            ApprovalChildMixin.action_force_transition(
                harness,
                {"code": requestor_rework.node_id, "name": requestor_rework.name},
                False,
            )

        self.assertTrue(harness._captured_context.get("re_submit"))
        self.assertTrue(harness._force_jump_called)
        self.assertEqual(harness.current_node_id, requestor_rework.node_id)
        self.assertEqual(harness.state, "new")
        self.assertEqual(harness.request_status, "new")

    def test_force_transition_includes_audit_comment_in_message_and_context(self):
        harness = _ForceTransitionHarness(
            self.env,
            self.version,
            current_node_id=self.meta_hod.node_id,
            current_activity_name=self.meta_hod.name,
            previous_node_id=self.meta_submission.node_id,
            previous_activity_name=self.meta_submission.name,
        )
        audit_comment = "Admin override after verification"
        target_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Audit Target",
                "node_id": f"Task_Audit_Force_{uuid4().hex[:6]}",
                "node_type": "userTask",
            }
        )
        current_node = _fake_node(self.meta_hod.node_id, self.meta_hod.name)
        next_node = _fake_node(target_meta.node_id, target_meta.name)
        engine = _FakeTrackingEngine(
            elements={
                self.meta_hod.node_id: current_node,
                target_meta.node_id: next_node,
            },
            next_map={target_meta.node_id: []},
        )

        with patch(
            "odoo.addons.workflow_engine.models.approval_child_mixin.BpmnEngine",
            return_value=engine,
        ):
            ApprovalChildMixin.action_force_transition(
                harness,
                {"code": target_meta.node_id, "name": target_meta.name},
                False,
                audit_comment=audit_comment,
            )

        self.assertEqual(harness._captured_context.get("force_transition_comment"), audit_comment)
        self.assertIn(audit_comment, str(harness._last_message.get("body") or ""))

    def test_unlink_request_deletes_linked_attachments(self):
        request = self._create_request()
        attachment = self.Attachment.sudo().create(
            {
                "name": "workflow_test.txt",
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "type": "binary",
                "datas": "V29ya2Zsb3cgdGVzdA==",
                "mimetype": "text/plain",
            }
        )

        request.sudo().unlink()
        self.assertFalse(
            attachment.exists(),
            "Linked attachments must be removed when request is deleted.",
        )

    def test_file_attachment_ids_refresh_immediately_after_upload(self):
        request = self._create_request()
        # Prime cache with empty value to simulate already-open form data.
        self.assertFalse(request.file_attachment_ids)

        attachment = self.Attachment.sudo().create(
            {
                "name": "workflow_live_refresh.txt",
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "type": "binary",
                "datas": "V29ya2Zsb3cgbGl2ZSByZWZyZXNo",
                "mimetype": "text/plain",
            }
        )

        self.assertIn(
            attachment,
            request.file_attachment_ids,
            "File list should include newly uploaded attachment without full record reload.",
        )

    def test_force_transition_wizard_default_target_is_preselected(self):
        request = self._create_request()
        wizard_model = self.env["workflow.force.transition.wizard"].with_context(
            default_model="workflow.base.approval.request",
            default_request_id=request.id,
            active_model="workflow.base.approval.request",
            active_id=request.id,
        )
        values = wizard_model.default_get(["model", "request_id", "target_node"])
        self.assertEqual(
            values.get("model"),
            "workflow.base.approval.request",
            "Wizard should keep requested model context for base request forms.",
        )
        self.assertEqual(
            values.get("request_id"),
            request.id,
            "Wizard must bind request_id from context so force transition can resolve the record.",
        )
        self.assertTrue(
            values.get("target_node"),
            "Wizard should preselect a force-transition target when candidates exist.",
        )

    def test_force_transition_wizard_resolves_active_request_without_request_id(self):
        request = self._create_request()
        wizard = self.env["workflow.force.transition.wizard"].with_context(
            active_model="workflow.base.approval.request",
            active_id=request.id,
        ).new(
            {
                "model": "workflow.base.approval.request",
            }
        )
        resolved = wizard._resolve_request_record()
        self.assertEqual(
            resolved.id,
            request.id,
            "Wizard should fall back to active_model/active_id when request_id is empty.",
        )

    def test_force_transition_wizard_requires_comment(self):
        request = self._create_request()
        wizard_model = self.env["workflow.force.transition.wizard"].with_context(
            default_model="workflow.base.approval.request",
            default_request_id=request.id,
            active_model="workflow.base.approval.request",
            active_id=request.id,
        )
        defaults = wizard_model.default_get(["model", "request_id", "target_node"])
        wizard = wizard_model.create(
            {
                "model": defaults.get("model"),
                "request_id": defaults.get("request_id"),
                "target_node": defaults.get("target_node"),
                "re_assign_approvals": True,
            }
        )

        with self.assertRaises(ValidationError):
            wizard.action_confirm_force()

    def test_force_transition_wizard_does_not_block_request_delete(self):
        request = self._create_request()
        wizard_model = self.env["workflow.force.transition.wizard"].with_context(
            default_model="workflow.base.approval.request",
            default_request_id=request.id,
            active_model="workflow.base.approval.request",
            active_id=request.id,
        )
        defaults = wizard_model.default_get(["model", "request_id", "target_node"])
        wizard = wizard_model.create(
            {
                "model": defaults.get("model"),
                "request_id": defaults.get("request_id"),
                "target_node": defaults.get("target_node"),
                "re_assign_approvals": True,
            }
        )

        request.unlink()

        self.assertFalse(request.exists())
        self.assertFalse(wizard.exists())

    def test_force_transition_wizard_passes_audit_comment(self):
        request = self._create_request()
        wizard_model = self.env["workflow.force.transition.wizard"].with_context(
            default_model="workflow.base.approval.request",
            default_request_id=request.id,
            active_model="workflow.base.approval.request",
            active_id=request.id,
        )
        defaults = wizard_model.default_get(["model", "request_id", "target_node"])
        wizard = wizard_model.create(
            {
                "model": defaults.get("model"),
                "request_id": defaults.get("request_id"),
                "target_node": defaults.get("target_node"),
                "re_assign_approvals": True,
                "comment": "Jump to next stage after review",
            }
        )

        class _FakeForceRequest:
            def __init__(self):
                self.calls = []

            def action_force_transition(self, target_node, re_assign_approvals, audit_comment=False):
                self.calls.append(
                    {
                        "target_node": target_node,
                        "re_assign_approvals": re_assign_approvals,
                        "audit_comment": audit_comment,
                    }
                )
                return {"type": "ir.actions.act_window_close"}

        fake_request = _FakeForceRequest()

        with patch.object(
            type(wizard),
            "_resolve_request_record",
            autospec=True,
            return_value=fake_request,
        ):
            wizard.action_confirm_force()

        self.assertEqual(
            fake_request.calls[-1]["audit_comment"],
            "Jump to next stage after review",
        )

    def test_first_submission_iteration_stays_one(self):
        class _FakeBaseRequest:
            def __init__(self, current_iteration_no):
                self.current_iteration_no = current_iteration_no

            def sudo(self):
                return self

            def write(self, vals):
                self.current_iteration_no = vals.get("current_iteration_no", self.current_iteration_no)

        class _FakeApprovalRecord:
            def __init__(self, max_iteration, current_iteration):
                self._max_iteration = max_iteration
                self._base = _FakeBaseRequest(current_iteration)

            def ensure_one(self):
                return None

            def _resolve_base_request_record(self):
                return self._base

            def _get_max_iteration_no(self):
                return self._max_iteration

        first_cycle = _FakeApprovalRecord(max_iteration=0, current_iteration=1)
        start_meta = SimpleNamespace(node_type=NODE_TYPE["START_EVENT"])
        first_iteration = ApprovalChildMixin._resolve_iteration_for_next_stage(
            first_cycle,
            is_submission_stage=True,
            previous_meta_task=start_meta,
        )
        self.assertEqual(
            first_iteration,
            1,
            "First submission stage must use round 1, not round 2.",
        )

        rework_cycle = _FakeApprovalRecord(max_iteration=1, current_iteration=1)
        user_meta = SimpleNamespace(node_type=NODE_TYPE["USER_TASK"])
        second_iteration = ApprovalChildMixin._resolve_iteration_for_next_stage(
            rework_cycle,
            is_submission_stage=True,
            previous_meta_task=user_meta,
        )
        self.assertEqual(
            second_iteration,
            2,
            "Submission after a non-start stage should advance to the next round.",
        )

    def test_rework_revisit_stage_starts_new_iteration(self):
        class _FakeBaseRequest:
            def __init__(self, current_iteration_no):
                self.current_iteration_no = current_iteration_no

            def sudo(self):
                return self

            def write(self, vals):
                self.current_iteration_no = vals.get("current_iteration_no", self.current_iteration_no)

        class _FakeRow:
            def __init__(self, node_id, iteration_no, status):
                self.current_meta_node_id = node_id
                self.iteration_no = iteration_no
                self.status = status

        class _FakeApprovalRecord:
            def __init__(self, max_iteration, current_iteration, rows=None):
                self._max_iteration = max_iteration
                self._base = _FakeBaseRequest(current_iteration)
                self.approver_ids = rows or []

            def ensure_one(self):
                return None

            def _resolve_base_request_record(self):
                return self._base

            def _get_max_iteration_no(self):
                return self._max_iteration

            def _is_iteration_revisit_loop_action(self, meta_action=False, previous_meta_task=False):
                return ApprovalChildMixin._is_iteration_revisit_loop_action(
                    self,
                    meta_action=meta_action,
                    previous_meta_task=previous_meta_task,
                )

            def _has_stage_history_in_iteration(self, target_node_id, iteration_no):
                return ApprovalChildMixin._has_stage_history_in_iteration(
                    self,
                    target_node_id=target_node_id,
                    iteration_no=iteration_no,
                )

        current_meta = SimpleNamespace(node_id="Task_NurseVerify")
        revisit_row = _FakeRow(node_id="Task_NurseVerify", iteration_no=1, status="approved")

        revisit_cycle = _FakeApprovalRecord(
            max_iteration=1,
            current_iteration=1,
            rows=[revisit_row],
        )
        rework_iteration = ApprovalChildMixin._resolve_iteration_for_next_stage(
            revisit_cycle,
            is_submission_stage=False,
            current_meta_task=current_meta,
            meta_action=SimpleNamespace(name="Rework"),
        )
        self.assertEqual(
            rework_iteration,
            2,
            "Revisit loopback to an already completed stage must open a new round.",
        )

        self.assertEqual(
            revisit_cycle._base.current_iteration_no,
            2,
            "Request current iteration should move with revisit-loop round bump.",
        )

        no_loop_cycle = _FakeApprovalRecord(
            max_iteration=1,
            current_iteration=1,
            rows=[revisit_row],
        )
        same_iteration = ApprovalChildMixin._resolve_iteration_for_next_stage(
            no_loop_cycle,
            is_submission_stage=False,
            current_meta_task=current_meta,
            meta_action=SimpleNamespace(name="Approve"),
        )
        self.assertEqual(
            same_iteration,
            1,
            "Non-loop actions should keep the active round unchanged.",
        )

    def test_required_approval_count_is_capped_by_assigned_approvers(self):
        record = SimpleNamespace()
        meta_action = SimpleNamespace(approval_require_number=3)
        assigned_approvals = [SimpleNamespace(), SimpleNamespace()]

        effective_required = ApprovalChildMixin._workflow_effective_required_approval_count(
            record,
            meta_action,
            assigned_approvals,
        )

        self.assertEqual(
            effective_required,
            2,
            "Required approvals must not exceed the number of assigned approvers.",
        )

    def test_create_defers_sequence_until_submission(self):
        source = inspect.getsource(ApprovalChildMixin.create)
        self.assertIn("request._run_engine()", source)
        self.assertNotIn(
            "next_by_id",
            source,
            "Create should not consume request folio sequence before the first submission transition.",
        )

    def test_first_submission_assigns_folio_once(self):
        sequence = _FakeSequence(["RQ0001"])
        category = _FakeCategory(sequence_id=sequence)
        harness = _LazySequenceHarness(self.env, self.version, category, name="New")

        folio = ApprovalChildMixin._workflow_assign_submission_folio_if_needed(
            harness,
            self.meta_submission,
        )

        self.assertEqual(folio, "RQ0001")
        self.assertEqual(harness.name, "RQ0001")
        self.assertEqual(sequence.calls, 1)
        self.assertTrue(harness._captured_context.get("workflow_skip_edit_scope"))
        self.assertTrue(harness._captured_context.get("workflow_skip_field_policy"))

    def test_resubmit_submission_history_does_not_regenerate_folio(self):
        sequence = _FakeSequence(["RQ0002"])
        category = _FakeCategory(sequence_id=sequence)
        history_rows = [
            SimpleNamespace(
                current_meta_node_id=self.meta_submission.node_id,
                user_decision="Send for Review",
            )
        ]
        harness = _LazySequenceHarness(
            self.env,
            self.version,
            category,
            name="New",
            approver_rows=history_rows,
        )

        folio = ApprovalChildMixin._workflow_assign_submission_folio_if_needed(
            harness,
            self.meta_submission,
        )

        self.assertFalse(folio)
        self.assertEqual(harness.name, "New")
        self.assertEqual(
            sequence.calls,
            0,
            "Submission resubmits must not consume a second sequence even when the action label is custom.",
        )

    def test_renamed_submission_stage_still_assigns_by_bpmn_mapping(self):
        sequence = _FakeSequence(["RQ0003"])
        category = _FakeCategory(sequence_id=sequence)
        harness = _LazySequenceHarness(self.env, self.version, category, name="New")
        renamed_submission = _FakeMetaTask(self.meta_submission.node_id, "Request Intake")

        with patch(
            "odoo.addons.workflow_engine.models.approval_child_mixin.BpmnEngine",
            return_value=_FakeSubmissionEngine(self.meta_submission.node_id),
        ):
            folio = ApprovalChildMixin._workflow_assign_submission_folio_if_needed(
                harness,
                renamed_submission,
            )

        self.assertEqual(folio, "RQ0003")
        self.assertEqual(harness.name, "RQ0003")
        self.assertEqual(sequence.calls, 1)

    def test_non_submission_stage_does_not_assign_folio(self):
        sequence = _FakeSequence(["RQ0004"])
        category = _FakeCategory(sequence_id=sequence)
        harness = _LazySequenceHarness(self.env, self.version, category, name="New")

        folio = ApprovalChildMixin._workflow_assign_submission_folio_if_needed(
            harness,
            self.meta_hod,
        )

        self.assertFalse(folio)
        self.assertEqual(harness.name, "New")
        self.assertEqual(sequence.calls, 0)

    def test_existing_numbered_submission_request_keeps_folio(self):
        sequence = _FakeSequence(["RQ0005"])
        category = _FakeCategory(sequence_id=sequence)
        harness = _LazySequenceHarness(self.env, self.version, category, name="RQ9999")

        folio = ApprovalChildMixin._workflow_assign_submission_folio_if_needed(
            harness,
            self.meta_submission,
        )

        self.assertFalse(folio)
        self.assertEqual(harness.name, "RQ9999")
        self.assertEqual(
            sequence.calls,
            0,
            "An already-numbered in-flight request must preserve its folio.",
        )

    def test_next_action_label_prefers_non_terminal_visible_button(self):
        class _FakeRequest:
            visible_buttons = [
                {"action_button_label": "Cancel", "disabled": False},
                {"action_button_label": "Submit", "disabled": False},
            ]
            next_activity_name = "Cancel"
            next_is_end_event = True
            state = "waiting"

            def ensure_one(self):
                return None

            def _get_next_action_label_from_visible_buttons(self):
                return ApprovalBaseRequest._get_next_action_label_from_visible_buttons(self)

            def _is_terminal_negative_action_label(self, label):
                return ApprovalBaseRequest._is_terminal_negative_action_label(label)

        fake = _FakeRequest()
        label = ApprovalBaseRequest._resolve_next_action_label_for_review_header(fake)
        self.assertEqual(
            label,
            "Submit",
            "Review header should prefer forward visible action over terminal Cancel fallback.",
        )

    def test_next_action_label_hides_terminal_cancel_when_no_visible_action(self):
        class _FakeRequest:
            visible_buttons = []
            next_activity_name = "Cancel"
            next_is_end_event = True
            state = "waiting"

            def ensure_one(self):
                return None

            def _get_next_action_label_from_visible_buttons(self):
                return ApprovalBaseRequest._get_next_action_label_from_visible_buttons(self)

            def _is_terminal_negative_action_label(self, label):
                return ApprovalBaseRequest._is_terminal_negative_action_label(label)

        fake = _FakeRequest()
        label = ApprovalBaseRequest._resolve_next_action_label_for_review_header(fake)
        self.assertEqual(
            label,
            "-",
            "Terminal Cancel should be hidden in pending stages when no clear next action is visible.",
        )
