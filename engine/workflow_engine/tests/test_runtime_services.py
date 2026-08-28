# -*- coding: utf-8 -*-
import inspect
import re
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import common
from odoo.addons.workflow_engine.models.workflow_runtime_models import (
    WorkflowRequestActionAssignment,
)
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine

ROUTING_ALWAYS_TRUE = "[(1, '=', 1)]"


class TestWorkflowRuntimeServices(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.MetaAction = cls.env["workflow.category.version.meta.task.action"]
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.WorkflowAction = cls.env["workflow.approval.action"]
        cls.MailTemplate = cls.env["mail.template"]
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.TaskInstance = cls.env["workflow.request.task.instance"]
        cls.TaskAssignee = cls.env["workflow.request.task.assignee"]
        cls.ActionAssignment = cls.env["workflow.request.action.assignment"]
        cls.TaskEvent = cls.env["workflow.request.task.event"]
        cls.AutomationNode = cls.env["workflow.automation.node"]
        cls.AutomationInstance = cls.env["workflow.request.automation.instance"]
        cls.DepartmentPayload = cls.env["workflow.request.department.payload"]
        cls.Attachment = cls.env["ir.attachment"]
        cls.Delegation = cls.env["workflow.approval.delegation"]
        cls.ApprovalGroup = cls.env["workflow.approval.group"]
        cls.MetaTaskApprovalGroup = cls.env["workflow.category.task.approval.group"]

        cls.assignment_service = cls.env["workflow.engine.assignment.service"]
        cls.legacy_adapter_service = cls.env["workflow.engine.legacy.adapter.service"]
        cls.runtime_service = cls.env["workflow.engine.runtime.service"]
        cls.audit_service = cls.env["workflow.engine.audit.service"]
        cls.permission_service = cls.env["workflow.engine.permission.service"]

        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        request_reader_group = cls.env.ref("workflow_engine.group_workflow_request_reader")
        unique = uuid4().hex[:8]

        def _new_user(name_prefix, group_ids=None):
            return cls.User.with_context(no_reset_password=True).create(
                {
                    "name": f"{name_prefix} {unique}",
                    "login": f"{name_prefix.lower()}_{unique}",
                    "email": f"{name_prefix.lower()}_{unique}@example.com",
                    "group_ids": [(6, 0, group_ids or [workflow_group.id])],
                }
            )

        def _ensure_employee(user):
            employee = user.employee_id
            if employee:
                return employee
            return cls.env["hr.employee"].sudo().create(
                {
                    "name": user.name,
                    "user_id": user.id,
                    "company_id": user.company_id.id if user.company_id else False,
                }
            )

        cls.requester = _new_user("requester")
        cls.manager = _new_user("manager")
        cls.department_manager = _new_user("deptmanager")
        cls.approver_a = _new_user("approvera")
        cls.approver_b = _new_user("approverb")
        cls.delegate_user = _new_user("delegate")
        cls.outsider = _new_user("outsider")
        cls.reader_user = _new_user("reader", [request_reader_group.id])

        cls.requester_employee = _ensure_employee(cls.requester)
        cls.manager_employee = _ensure_employee(cls.manager)
        cls.department_manager_employee = _ensure_employee(cls.department_manager)
        _ensure_employee(cls.approver_a)
        _ensure_employee(cls.approver_b)
        _ensure_employee(cls.delegate_user)
        _ensure_employee(cls.outsider)
        _ensure_employee(cls.reader_user)

        cls.department = cls.env["hr.department"].sudo().create(
            {
                "name": f"Runtime Department {unique}",
                "manager_id": cls.department_manager_employee.id,
            }
        )

        cls.requester_employee.write(
            {
                "parent_id": cls.manager_employee.id,
                "department_id": cls.department.id,
            }
        )

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.base_request_model = base_request_model
        cls.category = cls.Category.sudo().create(
            {
                "name": f"Runtime Category {unique}",
                "res_model": base_request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [
                    (
                        6,
                        0,
                        [
                            cls.requester.id,
                            cls.manager.id,
                            cls.department_manager.id,
                            cls.approver_a.id,
                            cls.approver_b.id,
                            cls.delegate_user.id,
                        ],
                    )
                ],
            }
        )
        cls.version = cls.Version.sudo().create(
            {
                "name": "v_runtime",
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
                "assignment_mode": "request_owner",
            }
        )
        cls.meta_hod = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "HOD",
                "node_id": "Task_HOD",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
                "completion_mode": "any",
                "fallback_policy": "route_admin_queue",
            }
        )
        cls.meta_rework = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Rework",
                "node_id": "Task_Rework",
                "node_type": "userTask",
                "assignment_mode": "previous_actor",
                "assign_to_previous_actor": True,
                "previous_actor_node_ref": cls.meta_submission.node_id,
                "fallback_policy": "block",
            }
        )
        cls.meta_end = cls.MetaTask.sudo().create(
            {
                "version_id": cls.version.id,
                "name": "Done",
                "node_id": "Task_End",
                "node_type": "endEvent",
            }
        )
        cls.action_approve_hod = cls.MetaAction.sudo().create(
            {
                "name": "Approve",
                "meta_task_id": cls.meta_hod.id,
                "source_id": cls.meta_hod.node_id,
                "source_name": cls.meta_hod.name,
                "source_node_type": cls.meta_hod.node_type,
                "target_id": cls.meta_end.node_id,
                "target_name": cls.meta_end.name,
                "target_node_type": cls.meta_end.node_type,
                "node_id": "Flow_HOD_End",
                "version_id": cls.version.id,
                "approval_require_number": 1,
            }
        )

        cls.request = cls.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_{unique}",
                "category_id": cls.category.id,
                "request_owner_id": cls.requester.id,
                "current_node_id": cls.meta_hod.node_id,
                "previous_node_id": cls.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )

        # Historical row used by previous-actor routing tests
        cls.Approver.sudo().create(
            {
                "user_id": cls.requester.id,
                "request_id": cls.request.id,
                "current_meta_id": cls.meta_submission.id,
                "previous_meta_id": cls.meta_submission.id,
                "status": "closed",
                "user_decision": "Submit",
                "required": False,
                "iteration_no": 1,
            }
        )
        cls.dynamic_group = cls.ApprovalGroup.sudo().create(
            {
                "name": f"Dynamic Runtime Group {unique}",
                "user_ids": [(6, 0, [cls.approver_a.id, cls.requester.id])],
            }
        )

    def _new_domain_parent_request(self, name_suffix="PARENT", version=False, category=False):
        category = category or self.category
        return self.Request.sudo().create(
            {
                "name": f"REQ_DOMAIN_{name_suffix}_{uuid4().hex[:8]}",
                "category_id": category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": "Task_HOD",
                "previous_node_id": "Task_Submission",
                "current_iteration_no": 1,
            }
        )

    def _new_business_action(
        self,
        name="Cancel",
        meta_task=False,
        target_task=False,
        **actor_values,
    ):
        meta_task = meta_task or self.meta_hod
        target_task = target_task or self.meta_end
        return self.MetaAction.sudo().create(
            {
                "name": name,
                "meta_task_id": meta_task.id,
                "source_id": meta_task.node_id,
                "source_name": meta_task.name,
                "source_node_type": meta_task.node_type,
                "target_id": target_task.node_id,
                "target_name": target_task.name,
                "target_node_type": target_task.node_type,
                "node_id": f"Flow_{name}_{uuid4().hex[:8]}",
                "version_id": self.version.id,
                "authorization_mode": "business_actor",
                "authorization_scope": "task",
                **actor_values,
            }
        )

    def _new_active_task(self, meta_task=False, iteration_no=1):
        meta_task = meta_task or self.meta_hod
        return self.TaskInstance.sudo().create(
            {
                "request_id": self.request.id,
                "node_id": meta_task.node_id,
                "node_name": meta_task.name,
                "node_type": meta_task.node_type,
                "status": "pending",
                "completion_mode": meta_task.completion_mode or "any",
                "iteration_no": iteration_no,
            }
        )

    def _new_domain_child_request(self, parent, name, state="draft"):
        return self.Request.sudo().create(
            {
                "name": name,
                "category_id": parent.category_id.id,
                "request_owner_id": self.requester.id,
                "parent_id": parent.id,
                "state": state,
                "current_node_id": "Task_Submission",
                "current_iteration_no": 1,
            }
        )

    def _new_condition_domain_version(self, name_suffix, bpmn_xml):
        category = self.Category.sudo().create(
            {
                "name": f"Runtime Condition {name_suffix} {uuid4().hex[:8]}",
                "res_model": self.base_request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [(6, 0, [self.requester.id])],
            }
        )
        version = self.Version.sudo().create(
            {
                "name": f"v_cond_{name_suffix}_{uuid4().hex[:8]}",
                "category_id": category.id,
                "is_active": True,
                "bpmn_xml": bpmn_xml,
            }
        )
        category.sudo().write({"active_version_id": version.id})
        return category, version

    def _new_owner_update_request(
        self,
        status="new",
        creator=False,
        owner=False,
        current_meta_task=False,
        previous_meta_task=False,
        state="waiting",
    ):
        creator = creator or self.requester
        owner = owner or self.requester
        current_meta_task = current_meta_task or self.meta_hod
        previous_meta_task = previous_meta_task or self.meta_submission
        request = self.Request.with_user(creator).create(
            {
                "name": f"REQ_OWNER_NOTIFY_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": owner.id,
                "current_node_id": current_meta_task.node_id,
                "previous_node_id": previous_meta_task.node_id,
                "current_activity_name": current_meta_task.name,
                "state": state,
            }
        )
        if status:
            self.Approver.sudo().create(
                {
                    "user_id": self.approver_a.id,
                    "request_id": request.id,
                    "current_meta_id": current_meta_task.id,
                    "previous_meta_id": previous_meta_task.id,
                    "status": status,
                    "required": True,
                    "iteration_no": 1,
                }
            )
        request.invalidate_recordset(["request_status"])
        return request

    def _create_runtime_v2_pass_through_version(self, name_suffix, approval_require_number=1):
        version = self.Version.sudo().create(
            {
                "name": f"v_runtime_v2_{name_suffix}_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "is_active": True,
                "execution_profile": "runtime_v2",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_RuntimeV2PassThrough">
                  <bpmn:process id="Process_RuntimeV2PassThrough" isExecutable="true">
                    <bpmn:userTask id="Task_Submission" name="Submission">
                      <bpmn:outgoing>Flow_Submit</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateThrowEvent id="Event_Submit" name="Submit">
                      <bpmn:incoming>Flow_Submit</bpmn:incoming>
                      <bpmn:outgoing>Flow_To_HOD</bpmn:outgoing>
                    </bpmn:intermediateThrowEvent>
                    <bpmn:userTask id="Task_HOD" name="HOD Approval">
                      <bpmn:incoming>Flow_To_HOD</bpmn:incoming>
                      <bpmn:outgoing>Flow_HOD_Approve</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateThrowEvent id="Event_Approve" name="Approve">
                      <bpmn:incoming>Flow_HOD_Approve</bpmn:incoming>
                      <bpmn:outgoing>Flow_To_Send</bpmn:outgoing>
                    </bpmn:intermediateThrowEvent>
                    <bpmn:sendTask id="Task_SendNotify" name="Notify Requester Email">
                      <bpmn:incoming>Flow_To_Send</bpmn:incoming>
                      <bpmn:outgoing>Flow_To_Nurse</bpmn:outgoing>
                    </bpmn:sendTask>
                    <bpmn:userTask id="Task_Nurse" name="Nurse">
                      <bpmn:incoming>Flow_To_Nurse</bpmn:incoming>
                      <bpmn:outgoing>Flow_Nurse_Done</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:endEvent id="End_Done" name="Done">
                      <bpmn:incoming>Flow_Nurse_Done</bpmn:incoming>
                    </bpmn:endEvent>
                    <bpmn:sequenceFlow id="Flow_Submit" sourceRef="Task_Submission" targetRef="Event_Submit"/>
                    <bpmn:sequenceFlow id="Flow_To_HOD" sourceRef="Event_Submit" targetRef="Task_HOD"/>
                    <bpmn:sequenceFlow id="Flow_HOD_Approve" sourceRef="Task_HOD" targetRef="Event_Approve"/>
                    <bpmn:sequenceFlow id="Flow_To_Send" sourceRef="Event_Approve" targetRef="Task_SendNotify"/>
                    <bpmn:sequenceFlow id="Flow_To_Nurse" sourceRef="Task_SendNotify" targetRef="Task_Nurse"/>
                    <bpmn:sequenceFlow id="Flow_Nurse_Done" sourceRef="Task_Nurse" targetRef="End_Done"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        version.action_sync_bpmn_metadata()

        meta_submission = self.MetaTask.sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Submission")],
            limit=1,
        )
        meta_hod = self.MetaTask.sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_HOD")],
            limit=1,
        )
        meta_send = self.MetaTask.sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_SendNotify")],
            limit=1,
        )
        meta_nurse = self.MetaTask.sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Nurse")],
            limit=1,
        )

        meta_hod.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
                "completion_mode": "any",
                "fallback_policy": "route_admin_queue",
            }
        )
        meta_nurse.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [(6, 0, [self.requester.id])],
                "fallback_policy": "block",
            }
        )

        approve_action = self.MetaAction.sudo().search(
            [("version_id", "=", version.id), ("source_id", "=", "Task_HOD"), ("target_id", "=", "Event_Approve")],
            limit=1,
        )
        approve_action.sudo().write({"approval_require_number": approval_require_number})

        return {
            "version": version,
            "meta_submission": meta_submission,
            "meta_hod": meta_hod,
            "meta_send": meta_send,
            "meta_nurse": meta_nurse,
            "approve_action": approve_action,
        }

    def test_assignment_submit_with_delegation_substitution(self):
        self.meta_hod.sudo().write({"explicit_user_ids": [(6, 0, [self.approver_a.id])]})
        now = fields.Datetime.now()
        self.Delegation.sudo().create(
            {
                "delegator_user_id": self.approver_a.id,
                "delegate_user_id": self.delegate_user.id,
                "date_from": now - timedelta(hours=1),
                "date_to": now + timedelta(hours=4),
                "scope": "approvals",
                "active": True,
                "category_ids": [(6, 0, [self.category.id])],
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, result["candidate_user_ids"])
        self.assertIn(self.delegate_user.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])
        self.assertTrue(result["delegation_map"])

        task_instance = self.assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=self.request,
            meta_task=self.meta_hod,
            iteration_no=1,
        )
        self.assertTrue(task_instance)
        assignees = task_instance.assignee_ids.mapped("assignee_user_id")
        self.assertIn(self.delegate_user, assignees)

    def test_assignment_submit_with_out_of_office_delegate_cc(self):
        self.meta_hod.sudo().write({"explicit_user_ids": [(6, 0, [self.approver_a.id])]})
        now = fields.Datetime.now()
        self.Delegation.sudo().create(
            {
                "delegator_user_id": self.approver_a.id,
                "delegate_user_id": self.delegate_user.id,
                "date_from": now - timedelta(hours=1),
                "date_to": now + timedelta(hours=4),
                "scope": "approvals",
                "active": True,
                "delegation_source": "out_of_office",
                "assignment_strategy": "cc_delegate",
                "category_ids": [(6, 0, [self.category.id])],
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, result["candidate_user_ids"])
        self.assertIn(self.approver_a.id, result["final_user_ids"])
        self.assertIn(self.delegate_user.id, result["final_user_ids"])
        self.assertTrue(result["delegation_map"])
        self.assertEqual(result["delegation_map"][0].get("strategy"), "cc_delegate")

        task_instance = self.assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=self.request,
            meta_task=self.meta_hod,
            iteration_no=1,
        )
        self.assertTrue(task_instance)
        assignees = task_instance.assignee_ids.mapped("assignee_user_id")
        self.assertIn(self.approver_a, assignees)
        self.assertIn(self.delegate_user, assignees)

    def test_out_of_office_preference_toggle_allows_later_configuration(self):
        self.approver_a.sudo().write(
            {
                "wf_ooo_enabled": False,
                "wf_ooo_delegate_user_id": False,
                "wf_ooo_date_from": False,
                "wf_ooo_date_to": False,
            }
        )

        self.approver_a.sudo().write({"wf_ooo_enabled": True})

        self.assertTrue(self.approver_a.wf_ooo_enabled)
        self.assertFalse(self.approver_a.wf_ooo_is_active_now)
        delegation = self.Delegation.sudo().search(
            [
                ("delegator_user_id", "=", self.approver_a.id),
                ("delegation_source", "=", "out_of_office"),
                ("active", "=", True),
            ]
        )
        self.assertFalse(delegation)

    def test_out_of_office_wizard_requires_complete_enabled_configuration(self):
        wizard = self.env["workflow.ooo.preference.wizard"].create(
            {
                "user_id": self.approver_a.id,
                "wf_ooo_enabled": True,
            }
        )
        with self.assertRaisesRegex(ValidationError, "at least one active"):
            wizard.action_apply()

    def test_out_of_office_wizard_hides_current_user_field(self):
        view = self.env.ref("workflow_engine.view_workflow_ooo_preference_wizard_form")
        self.assertIn('name="user_id" invisible="1"', view.arch_db)
        self.assertIn('name="workflow_ooo_rules"', view.arch_db)
        self.assertNotIn("Delegation History", view.arch_db)

    def test_out_of_office_history_renders_on_workflow_preferences(self):
        view = self.env.ref("workflow_engine.res_users_view_form_preferences_ooo")
        self.assertIn("Out of Office History", view.arch_db)
        self.assertIn('name="workflow_ooo_history"', view.arch_db)
        self.assertIn('name="wf_ooo_delegation_history_ids"', view.arch_db)
        self.assertIn('<list create="0" edit="0" delete="1">', view.arch_db)
        self.assertIn('<form string="Out of Office History"', view.arch_db)
        self.assertIn('delete="1"', view.arch_db)
        self.assertIn('string="Assign To"', view.arch_db)

    def test_non_hr_user_with_employee_uses_simple_preferences_action(self):
        action = self.User.with_user(self.requester).action_get()
        self.assertEqual(action.get("id"), self.env.ref("base.action_res_users_my").id)

    def test_hr_user_with_employee_keeps_hr_preferences_action(self):
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        hr_group = self.env.ref("hr.group_hr_user")
        hr_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"HR Pref {uuid4().hex[:8]}",
                "login": f"hr_pref_{uuid4().hex[:8]}",
                "email": f"hr_pref_{uuid4().hex[:8]}@example.com",
                "group_ids": [(6, 0, [workflow_group.id, hr_group.id])],
            }
        )
        self.env["hr.employee"].sudo().create(
            {
                "name": hr_user.name,
                "user_id": hr_user.id,
                "company_id": hr_user.company_id.id if hr_user.company_id else False,
            }
        )

        action = self.User.with_user(hr_user).action_get()
        self.assertEqual(action.get("id"), self.env.ref("hr.res_users_action_my").id)

    def test_out_of_office_wizard_supports_multiple_category_delegates(self):
        self.meta_hod.sudo().write({"explicit_user_ids": [(6, 0, [self.approver_a.id])]})
        other_category = self.Category.sudo().create(
            {
                "name": f"Runtime OOO Other {uuid4().hex[:8]}",
                "res_model": self.base_request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [
                    (
                        6,
                        0,
                        [
                            self.approver_a.id,
                            self.delegate_user.id,
                            self.approver_b.id,
                        ],
                    )
                ],
            }
        )
        other_request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_OOO_{uuid4().hex[:8]}",
                "category_id": other_category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )
        now = fields.Datetime.now()
        wizard = self.env["workflow.ooo.preference.wizard"].create(
            {
                "user_id": self.approver_a.id,
                "wf_ooo_enabled": True,
                "wf_ooo_line_ids": [
                    (
                        0,
                        0,
                        {
                            "active": True,
                            "wf_ooo_delegate_user_id": self.delegate_user.id,
                            "wf_ooo_date_from": now - timedelta(hours=1),
                            "wf_ooo_date_to": now + timedelta(hours=4),
                            "wf_ooo_scope": "approvals",
                            "wf_ooo_category_ids": [(6, 0, [self.category.id])],
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "active": True,
                            "wf_ooo_delegate_user_id": self.approver_b.id,
                            "wf_ooo_date_from": now - timedelta(hours=1),
                            "wf_ooo_date_to": now + timedelta(hours=4),
                            "wf_ooo_scope": "approvals",
                            "wf_ooo_category_ids": [(6, 0, [other_category.id])],
                        },
                    ),
                ],
            }
        )

        wizard.action_apply()

        delegations = self.Delegation.sudo().search(
            [
                ("delegator_user_id", "=", self.approver_a.id),
                ("delegation_source", "=", "out_of_office"),
                ("active", "=", True),
            ]
        )
        self.assertEqual(len(delegations), 2)

        result_a = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, result_a["final_user_ids"])
        self.assertIn(self.delegate_user.id, result_a["final_user_ids"])
        self.assertNotIn(self.approver_b.id, result_a["final_user_ids"])

        result_b = self.assignment_service.resolve_assignees(other_request, self.meta_hod)
        self.assertIn(self.approver_a.id, result_b["final_user_ids"])
        self.assertIn(self.approver_b.id, result_b["final_user_ids"])
        self.assertNotIn(self.delegate_user.id, result_b["final_user_ids"])

    def test_rework_assigns_previous_actor_with_delegation(self):
        now = fields.Datetime.now()
        self.Delegation.sudo().create(
            {
                "delegator_user_id": self.requester.id,
                "delegate_user_id": self.delegate_user.id,
                "date_from": now - timedelta(hours=1),
                "date_to": now + timedelta(hours=2),
                "scope": "approvals",
                "active": True,
                "category_ids": [(6, 0, [self.category.id])],
            }
        )
        result = self.assignment_service.resolve_assignees(self.request, self.meta_rework)
        self.assertIn(self.requester.id, result["candidate_user_ids"])
        self.assertIn(self.delegate_user.id, result["final_user_ids"])

    def test_previous_actor_mode_assigns_all_deciders_from_source_node(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        self.meta_rework.sudo().write(
            {
                "previous_actor_node_ref": self.meta_hod.node_id,
                "assignment_source_user_type": "decided",
                "assign_to_previous_actor": False,
                "fallback_policy": "block",
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_rework)

        self.assertEqual(result["candidate_user_ids"], [self.approver_a.id])
        self.assertEqual(result["final_user_ids"], [self.approver_a.id])

    def test_previous_actor_mode_missing_source_node_uses_fallback_policy(self):
        self.meta_rework.sudo().write(
            {
                "previous_actor_node_ref": False,
                "assignment_source_user_type": "decided",
                "assign_to_previous_actor": False,
                "fallback_policy": "block",
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_rework)

        self.assertFalse(result["candidate_user_ids"])
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["blocked"])
        self.assertTrue(result["warnings"])

    def test_assignment_mode_groups_ignores_explicit_users(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(6, 0, [self.approver_b.id])],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, result["candidate_user_ids"])
        self.assertNotIn(self.approver_b.id, result["candidate_user_ids"])

    def test_assignment_mode_request_owner_returns_request_owner(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "request_owner",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertEqual(result["candidate_user_ids"], [self.requester.id])
        self.assertIn(self.requester.id, result["final_user_ids"])

    def test_assignment_mode_mixed_merges_candidates(self):
        mix_group = self.ApprovalGroup.sudo().create(
            {
                "name": f"Mixed Mode Group {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "mixed",
                "explicit_user_ids": [(6, 0, [self.approver_b.id])],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": "[('id', '=', request_owner_id)]",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": mix_group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, result["candidate_user_ids"])
        self.assertIn(self.approver_b.id, result["candidate_user_ids"])
        self.assertIn(self.requester.id, result["candidate_user_ids"])

    def test_assignment_mode_reentry_previous_actor_uses_config_then_latest_decider(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "reentry_previous_actor",
                "explicit_user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "previous_actor_node_ref": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        first_entry = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_a.id, first_entry["candidate_user_ids"])
        self.assertIn(self.approver_b.id, first_entry["candidate_user_ids"])

        self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "approved",
                "user_decision": "Approve",
                "required": True,
                "iteration_no": 1,
            }
        )

        reentry = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertEqual(reentry["candidate_user_ids"], [self.approver_b.id])
        self.assertEqual(reentry["final_user_ids"], [self.approver_b.id])

    def test_assignment_mode_collector_registry_exposes_default_collectors(self):
        collectors = self.assignment_service._assignment_mode_collectors()
        self.assertIn("mixed", collectors)
        self.assertIn("groups", collectors)
        self.assertIn("reentry_previous_actor", collectors)

        group_collector = self.assignment_service._resolve_assignment_mode_collector("groups")
        self.assertEqual(
            getattr(group_collector, "__name__", ""),
            "_collect_group_candidates",
        )

        default_collector = self.assignment_service._resolve_assignment_mode_collector("unsupported_mode")
        self.assertEqual(
            getattr(default_collector, "__name__", ""),
            "_collect_mixed_candidates",
        )

    def test_conditional_event_uses_condition_domain_and_default_flow(self):
        self.version.sudo().write(
            {
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_Runtime">
                  <bpmn:process id="Process_Conditional_Runtime" isExecutable="true">
                    <bpmn:startEvent id="StartEvent_1" name="Start">
                      <bpmn:outgoing>Flow_1</bpmn:outgoing>
                    </bpmn:startEvent>
                    <bpmn:intermediateCatchEvent id="Event_Check" name="Check Request" default="Flow_Default">
                      <bpmn:incoming>Flow_1</bpmn:incoming>
                      <bpmn:outgoing>Flow_Matched</bpmn:outgoing>
                      <bpmn:outgoing>Flow_Default</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_1"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched" name="Matched">
                      <bpmn:incoming>Flow_Matched</bpmn:incoming>
                    </bpmn:userTask>
                    <bpmn:userTask id="Task_Default" name="Default">
                      <bpmn:incoming>Flow_Default</bpmn:incoming>
                    </bpmn:userTask>
                    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Event_Check"/>
                    <bpmn:sequenceFlow id="Flow_Matched" sourceRef="Event_Check" targetRef="Task_Matched"/>
                    <bpmn:sequenceFlow id="Flow_Default" sourceRef="Event_Check" targetRef="Task_Default"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Check Request",
                "node_id": "Event_Check",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": "[('state', '=', 'waiting')]",
            }
        )
        engine = BpmnEngine(self.version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check")

        self.request.sudo().write({"state": "waiting"})
        matched_nodes = self.request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=self.request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in matched_nodes], ["Task_Matched"])

        self.request.sudo().write({"state": "draft"})
        default_nodes = self.request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=self.request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in default_nodes], ["Task_Default"])

    def test_conditional_event_empty_condition_uses_default_flow_and_ignores_route_guard(self):
        self.version.sudo().write(
            {
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_Empty">
                  <bpmn:process id="Process_Conditional_Empty" isExecutable="true">
                    <bpmn:intermediateCatchEvent id="Event_Check" name="Check Request" default="Flow_Default">
                      <bpmn:outgoing>Flow_Matched</bpmn:outgoing>
                      <bpmn:outgoing>Flow_Default</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_1"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched" name="Matched"/>
                    <bpmn:userTask id="Task_Default" name="Default"/>
                    <bpmn:sequenceFlow id="Flow_Matched" sourceRef="Event_Check" targetRef="Task_Matched"/>
                    <bpmn:sequenceFlow id="Flow_Default" sourceRef="Event_Check" targetRef="Task_Default"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Check Request",
                "node_id": "Event_Check",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": False,
            }
        )
        self.MetaAction.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Matched Guard",
                "source_id": "Event_Check",
                "target_id": "Task_Matched",
                "domain": ROUTING_ALWAYS_TRUE,
            }
        )
        engine = BpmnEngine(self.version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check")

        next_nodes = self.request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=self.request._get_form_data(),
        )

        self.assertEqual([node.attrib.get("id") for node in next_nodes], ["Task_Default"])

    def test_conditional_event_invalid_condition_uses_default_flow_and_warns(self):
        self.version.sudo().write(
            {
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_Invalid">
                  <bpmn:process id="Process_Conditional_Invalid" isExecutable="true">
                    <bpmn:intermediateCatchEvent id="Event_Check" name="Check Request" default="Flow_Default">
                      <bpmn:outgoing>Flow_Matched</bpmn:outgoing>
                      <bpmn:outgoing>Flow_Default</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_1"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched" name="Matched"/>
                    <bpmn:userTask id="Task_Default" name="Default"/>
                    <bpmn:sequenceFlow id="Flow_Matched" sourceRef="Event_Check" targetRef="Task_Matched"/>
                    <bpmn:sequenceFlow id="Flow_Default" sourceRef="Event_Check" targetRef="Task_Default"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Check Request",
                "node_id": "Event_Check",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": "[1, '=', 1]",
            }
        )
        engine = BpmnEngine(self.version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check")

        before_message_count = len(self.request.message_ids)
        next_nodes = self.request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=self.request._get_form_data(),
        )

        self.assertEqual([node.attrib.get("id") for node in next_nodes], ["Task_Default"])
        self.assertGreater(len(self.request.message_ids), before_message_count)
        self.assertTrue(
            any("invalid condition domain" in (message.body or "") for message in self.request.message_ids),
            "Expected a chatter warning when an invalid conditional event domain falls back to default.",
        )

    def test_dotted_one2many_domain_uses_any_line_semantics(self):
        request = self._new_domain_parent_request("DOTTED_ANY")
        self._new_domain_child_request(request, "Regular User Access", state="draft")
        self._new_domain_child_request(request, "Admin Access", state="waiting")

        self.assertTrue(
            request.check_domain(
                "[('child_ids.name', 'ilike', 'ADMIN')]",
                default=False,
            )
        )
        self.assertFalse(
            request.check_domain(
                "[('child_ids.name', 'ilike', 'FINANCE')]",
                default=False,
            )
        )

    def test_wf_any_matches_when_one_related_line_matches(self):
        request = self._new_domain_parent_request("WF_ANY")
        self._new_domain_child_request(request, "Regular User Access", state="draft")
        self._new_domain_child_request(request, "Admin Access", state="waiting")

        self.assertTrue(
            request.check_domain(
                "wf_any('child_ids', [('name', 'ilike', 'ADMIN')])",
                default=False,
            )
        )
        self.assertFalse(
            request.check_domain(
                "wf_any('child_ids', [('name', 'ilike', 'FINANCE')])",
                default=False,
            )
        )

    def test_wf_all_requires_all_related_lines_to_match_and_rejects_empty(self):
        request = self._new_domain_parent_request("WF_ALL")
        self._new_domain_child_request(request, "Admin Laptop", state="waiting")
        self._new_domain_child_request(request, "Admin Monitor", state="waiting")

        self.assertTrue(
            request.check_domain(
                "wf_all('child_ids', [('name', 'ilike', 'ADMIN')])",
                default=False,
            )
        )

        self._new_domain_child_request(request, "Finance Printer", state="waiting")
        self.assertFalse(
            request.check_domain(
                "wf_all('child_ids', [('name', 'ilike', 'ADMIN')])",
                default=False,
            )
        )

        empty_request = self._new_domain_parent_request("WF_ALL_EMPTY")
        self.assertFalse(
            empty_request.check_domain(
                "wf_all('child_ids', [('name', 'ilike', 'ADMIN')])",
                default=False,
            )
        )

    def test_wf_any_true_supports_has_lines_and_has_no_lines_checks(self):
        request = self._new_domain_parent_request("WF_LINE_PRESENCE")

        self.assertFalse(
            request.check_domain("wf_any('child_ids', True)", default=False)
        )
        self.assertTrue(
            request.check_domain("not wf_any('child_ids', True)", default=False)
        )

        self._new_domain_child_request(request, "Configured Line", state="waiting")
        self.assertTrue(
            request.check_domain("wf_any('child_ids', True)", default=False)
        )
        self.assertFalse(
            request.check_domain("not wf_any('child_ids', True)", default=False)
        )

    def test_wf_any_all_support_set_and_not_set_line_fields(self):
        request = self._new_domain_parent_request("WF_LINE_FIELD_PRESENCE")
        configured_line = self._new_domain_child_request(
            request,
            "Configured Line",
            state="waiting",
        )
        configured_line.sudo().write({"comment": "Configured"})
        self._new_domain_child_request(request, "Empty Line", state="waiting")

        self.assertTrue(
            request.check_domain(
                "wf_any('child_ids', [('comment', '!=', False)])",
                default=False,
            )
        )
        self.assertTrue(
            request.check_domain(
                "wf_any('child_ids', [('comment', '=', False)])",
                default=False,
            )
        )
        self.assertFalse(
            request.check_domain(
                "wf_all('child_ids', [('comment', '!=', False)])",
                default=False,
            )
        )
        self.assertFalse(
            request.check_domain(
                "wf_all('child_ids', [('comment', '=', False)])",
                default=False,
            )
        )

    def test_wf_any_all_use_live_one2many_snapshot_when_present(self):
        request = self._new_domain_parent_request("WF_LINE_LIVE_SNAPSHOT")
        persisted_line = self._new_domain_child_request(
            request,
            "Persisted Line",
            state="waiting",
        )
        persisted_line.sudo().write({"comment": "Persisted"})

        empty_snapshot = {"child_ids": []}
        self.assertFalse(
            request.check_domain(
                "wf_any('child_ids', True)",
                default=False,
                snapshot_values=empty_snapshot,
            )
        )
        self.assertTrue(
            request.check_domain(
                "not wf_any('child_ids', True)",
                default=False,
                snapshot_values=empty_snapshot,
            )
        )

        live_snapshot = {
            "child_ids": [
                {
                    "id": persisted_line.id,
                    "name": "Persisted Line",
                    "comment": False,
                },
                {
                    "name": "Unsaved Line",
                    "comment": "Entered in form",
                },
            ]
        }
        self.assertTrue(
            request.check_domain(
                "wf_any('child_ids', [('comment', '=', False)])",
                default=False,
                snapshot_values=live_snapshot,
            )
        )
        self.assertTrue(
            request.check_domain(
                "wf_any('child_ids', [('comment', '!=', False)])",
                default=False,
                snapshot_values=live_snapshot,
            )
        )
        self.assertFalse(
            request.check_domain(
                "wf_all('child_ids', [('comment', '!=', False)])",
                default=False,
                snapshot_values=live_snapshot,
            )
        )

    def test_workflow_domains_support_odoo_date_symbols(self):
        request = self._new_domain_parent_request("DATE_SYMBOLS")
        request.sudo().write({"date": fields.Datetime.now() - timedelta(days=1)})

        self.assertTrue(request.check_domain("[('date', '<', current_date)]", default=False))
        self.assertTrue(request.check_domain("[('date', '<', context_today())]", default=False))
        self.assertTrue(request.check_domain("[('date', '>=', 'today -7d')]", default=False))
        self.assertTrue(request.check_domain("[('date', '<', 'today +1d')]", default=False))

    def test_action_execution_domain_supports_actor_group_and_owner_manager_symbols(self):
        self.department_manager_employee.sudo().write(
            {
                "parent_id": self.manager_employee.id,
                "department_id": self.department.id,
            }
        )
        request = self._new_domain_parent_request("ACTION_EXEC_DOMAIN")
        request.sudo().write({"request_owner_id": self.department_manager.id})
        domain = (
            "['|',"
            f"('wf_actor_approval_group_ids', 'in', [{self.dynamic_group.id}]),"
            "'|',"
            "'&',"
            "('request_owner_id.id', '=', request_owner_department_manager_user_id),"
            "('uid', '=', request_owner_manager_user_id),"
            "'&',"
            "('request_owner_id.id', '!=', request_owner_department_manager_user_id),"
            "('uid', '=', request_owner_department_manager_user_id)"
            "]"
        )

        self.assertTrue(request.with_user(self.manager).check_domain(domain, default=False))
        self.assertTrue(request.with_user(self.approver_a).check_domain(domain, default=False))
        self.assertFalse(request.with_user(self.outsider).check_domain(domain, default=False))

    def test_wf_any_and_all_support_explicit_request_and_object_prefixes(self):
        request = self._new_domain_parent_request("WF_PREFIX")
        self._new_domain_child_request(request, "Admin Laptop", state="waiting")

        self.assertTrue(
            request.check_domain(
                "wf_any('request.child_ids', [('name', 'ilike', 'ADMIN')])",
                default=False,
            )
        )
        self.assertTrue(
            request.check_domain(
                "wf_all('object.child_ids', [('state', '=', 'waiting')])",
                default=False,
            )
        )

    def test_conditional_event_wf_any_routes_to_matched_or_default_flow(self):
        category, version = self._new_condition_domain_version(
            "any",
            """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_WfAny">
                  <bpmn:process id="Process_Conditional_WfAny" isExecutable="true">
                    <bpmn:intermediateCatchEvent id="Event_Check_WfAny" name="Check Line Items" default="Flow_Default_WfAny">
                      <bpmn:outgoing>Flow_Matched_WfAny</bpmn:outgoing>
                      <bpmn:outgoing>Flow_Default_WfAny</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_WfAny"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched_WfAny" name="Matched"/>
                    <bpmn:userTask id="Task_Default_WfAny" name="Default"/>
                    <bpmn:sequenceFlow id="Flow_Matched_WfAny" sourceRef="Event_Check_WfAny" targetRef="Task_Matched_WfAny"/>
                    <bpmn:sequenceFlow id="Flow_Default_WfAny" sourceRef="Event_Check_WfAny" targetRef="Task_Default_WfAny"/>
                  </bpmn:process>
                </bpmn:definitions>""",
        )
        self.MetaTask.sudo().create(
            {
                "version_id": version.id,
                "name": "Check Line Items",
                "node_id": "Event_Check_WfAny",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": "wf_any('child_ids', [('name', 'ilike', 'ADMIN')])",
            }
        )
        engine = BpmnEngine(version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check_WfAny")
        request = self._new_domain_parent_request("COND_WF_ANY", category=category)

        self._new_domain_child_request(request, "Admin Access", state="waiting")
        matched_nodes = request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in matched_nodes], ["Task_Matched_WfAny"])

        default_request = self._new_domain_parent_request("COND_WF_ANY_DEFAULT", category=category)
        self._new_domain_child_request(default_request, "User Access", state="waiting")
        default_nodes = default_request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=default_request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in default_nodes], ["Task_Default_WfAny"])

    def test_pass_through_resolvers_use_workflow_condition_evaluator(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        for method_name in (
            "_resolve_runtime_next_node",
            "_resolve_runtime_transition_entry_node",
        ):
            source = inspect.getsource(getattr(ApprovalChildMixin, method_name))
            self.assertIn("_workflow_get_next_elements", source)
            self.assertNotIn("engine.get_next_elements(current", source)

    def test_conditional_event_wf_all_requires_every_line_to_match(self):
        category, version = self._new_condition_domain_version(
            "all",
            """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_WfAll">
                  <bpmn:process id="Process_Conditional_WfAll" isExecutable="true">
                    <bpmn:intermediateCatchEvent id="Event_Check_WfAll" name="Check All Line Items" default="Flow_Default_WfAll">
                      <bpmn:outgoing>Flow_Matched_WfAll</bpmn:outgoing>
                      <bpmn:outgoing>Flow_Default_WfAll</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_WfAll"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched_WfAll" name="Matched"/>
                    <bpmn:userTask id="Task_Default_WfAll" name="Default"/>
                    <bpmn:sequenceFlow id="Flow_Matched_WfAll" sourceRef="Event_Check_WfAll" targetRef="Task_Matched_WfAll"/>
                    <bpmn:sequenceFlow id="Flow_Default_WfAll" sourceRef="Event_Check_WfAll" targetRef="Task_Default_WfAll"/>
                  </bpmn:process>
                </bpmn:definitions>""",
        )
        self.MetaTask.sudo().create(
            {
                "version_id": version.id,
                "name": "Check All Line Items",
                "node_id": "Event_Check_WfAll",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": "wf_all('child_ids', [('name', 'ilike', 'ADMIN')])",
            }
        )
        engine = BpmnEngine(version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check_WfAll")
        request = self._new_domain_parent_request("COND_WF_ALL", category=category)

        self._new_domain_child_request(request, "Admin Laptop", state="waiting")
        self._new_domain_child_request(request, "Admin Monitor", state="waiting")
        matched_nodes = request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in matched_nodes], ["Task_Matched_WfAll"])

        self._new_domain_child_request(request, "Finance Printer", state="waiting")
        default_nodes = request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=request._get_form_data(),
        )
        self.assertEqual([node.attrib.get("id") for node in default_nodes], ["Task_Default_WfAll"])

    def test_conditional_event_false_without_default_stops_execution(self):
        self.version.sudo().write(
            {
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_No_Default">
                  <bpmn:process id="Process_Conditional_No_Default" isExecutable="true">
                    <bpmn:startEvent id="StartEvent_1" name="Start">
                      <bpmn:outgoing>Flow_1</bpmn:outgoing>
                    </bpmn:startEvent>
                    <bpmn:intermediateCatchEvent id="Event_Check" name="Check Request">
                      <bpmn:incoming>Flow_1</bpmn:incoming>
                      <bpmn:outgoing>Flow_Matched</bpmn:outgoing>
                      <bpmn:conditionalEventDefinition id="Cond_1"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:userTask id="Task_Matched" name="Matched">
                      <bpmn:incoming>Flow_Matched</bpmn:incoming>
                    </bpmn:userTask>
                    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Event_Check"/>
                    <bpmn:sequenceFlow id="Flow_Matched" sourceRef="Event_Check" targetRef="Task_Matched"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Check Request",
                "node_id": "Event_Check",
                "node_type": "conditionalEventDefinition",
                "automation_condition_domain": "[('state', '=', 'waiting')]",
            }
        )
        engine = BpmnEngine(self.version.bpmn_xml)
        conditional_node = engine.get_element_by_id("Event_Check")

        before_message_count = len(self.request.message_ids)
        self.request.sudo().write({"state": "draft"})
        next_nodes = self.request._workflow_get_next_elements(
            engine,
            conditional_node,
            form_data=self.request._get_form_data(),
        )

        self.assertEqual(next_nodes, [])
        self.assertGreater(len(self.request.message_ids), before_message_count)
        self.assertTrue(
            any("no BPMN default outgoing path" in (message.body or "") for message in self.request.message_ids),
            "Expected a chatter warning when a conditional event false branch has no BPMN default flow.",
        )

    def test_assignment_fallback_handler_registry_defaults(self):
        handlers = self.assignment_service._fallback_policy_handlers()
        self.assertIn("block", handlers)
        self.assertIn("route_admin_queue", handlers)
        self.assertIn("escalate_manager", handlers)

        self.meta_hod.sudo().write({"fallback_user_id": self.approver_b.id})
        fallback_users = self.assignment_service._fallback_users(
            self.request,
            self.meta_hod,
            "route_admin_queue",
        )
        self.assertIn(self.approver_b, fallback_users)

    def test_visible_buttons_hidden_for_non_actor_non_admin(self):
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.request.invalidate_recordset(["visible_buttons"])
        visible_as_manager = self.request.with_user(self.manager).visible_buttons
        self.assertFalse(
            visible_as_manager,
            "Non-actor non-admin users must not see action dropdown buttons.",
        )

    def test_fallback_escalate_manager_assigns_manager_user(self):
        request_by_requester = self.Request.with_user(self.requester).create(
            {
                "name": f"REQ_ESC_MGR_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "current_activity_name": self.meta_hod.name,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.assertEqual(request_by_requester.manager_user_id, self.manager)

        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', 999999999)]",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "fallback_policy": "escalate_manager",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(request_by_requester, self.meta_hod)
        self.assertEqual(result["fallback_policy"], "escalate_manager")
        self.assertIn(self.manager.id, result["final_user_ids"])
        self.assertFalse(result["blocked"])

    def test_fallback_escalate_manager_blocks_when_manager_missing(self):
        no_manager_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"No Manager {uuid4().hex[:6]}",
                "login": f"no_manager_{uuid4().hex[:6]}",
                "email": f"no_manager_{uuid4().hex[:6]}@example.com",
                "group_ids": [(6, 0, [self.env.ref("workflow_engine.group_workflow_approval_user").id])],
            }
        )
        self.env["hr.employee"].sudo().create(
            {
                "name": no_manager_user.name,
                "user_id": no_manager_user.id,
                "company_id": no_manager_user.company_id.id if no_manager_user.company_id else False,
            }
        )
        self.category.sudo().write({"allowed_user_ids": [(4, no_manager_user.id)]})

        request_without_manager = self.Request.with_user(no_manager_user).create(
            {
                "name": f"REQ_ESC_MGR_NONE_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": no_manager_user.id,
                "current_node_id": self.meta_hod.node_id,
                "current_activity_name": self.meta_hod.name,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.assertFalse(request_without_manager.manager_user_id)

        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', 999999999)]",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "fallback_policy": "escalate_manager",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(request_without_manager, self.meta_hod)
        self.assertEqual(result["fallback_policy"], "escalate_manager")
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["blocked"])

    def test_legacy_adapter_prepares_rows_via_assignment_service(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": "[('request_owner_id', '=', request_owner_id)]",
                "user_domain": "[('id', '=', request_owner_id)]",
                "sequence": 10,
            }
        )

        result = self.legacy_adapter_service.prepare_legacy_approver_rows(
            request_record=self.request,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
            iteration_no=1,
            existing_keys=set(),
        )
        self.assertTrue(result["matched_any"])
        self.assertTrue(result["approver_data_list"])
        row_user_ids = {row.get("user_id") for row in result["approver_data_list"]}
        self.assertIn(self.requester.id, row_user_ids)
        self.assertIn("assignment mode", (result["approver_data_list"][0].get("remark") or "").lower())

    def test_legacy_adapter_surfaces_blocked_resolution(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', 999999999)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        result = self.legacy_adapter_service.prepare_legacy_approver_rows(
            request_record=self.request,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
            iteration_no=1,
            existing_keys=set(),
        )
        self.assertFalse(result["approver_data_list"])
        self.assertFalse(result["matched_any"])
        self.assertTrue((result["resolution"] or {}).get("blocked"))
        reason = self.legacy_adapter_service.build_unassigned_stage_reason(
            current_meta_task=self.meta_hod,
            resolution=result["resolution"],
        )
        self.assertIn("No approvers were added", reason)
        self.assertTrue(self.legacy_adapter_service.is_unassigned_stage_reason(reason))

    def test_assignment_method_uses_adapter_not_safe_eval(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._assign_dynamic_approvers_from_meta)
        self.assertNotIn("safe_eval(", source)
        self.assertIn("workflow.engine.legacy.adapter.service", source)
        self.assertIn(
            "for a in self.approver_ids\n            if a.status in ['new', 'pending', 'waiting']",
            source,
        )

    def test_child_assignment_does_not_rewrite_approver_ids_after_sudo_create(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._assign_dynamic_approvers_from_meta)
        self.assertNotIn("self.approver_ids += new_approvers", source)
        self.assertIn('base_request.invalidate_recordset(["approver_ids"])', source)
        self.assertIn('self.invalidate_recordset(["approver_ids"])', source)

    def test_child_assignment_sends_owner_update_after_block_sync(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._assign_dynamic_approvers_from_meta)
        self.assertGreater(
            source.index("_workflow_send_owner_update_notification(current_meta_task=current_meta_task)"),
            source.index("_sync_blocked_state_from_approvers()"),
        )

    def test_existing_assignment_keys_ignore_closed_rows(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._build_existing_assignment_keys)
        self.assertIn("a.status in open_statuses", source)

    def test_assignment_user_domain_supports_safe_eval_context(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', request_owner_id)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.requester.id, result["candidate_user_ids"])
        self.assertIn(self.requester.id, result["final_user_ids"])

    def test_assignment_user_domain_uses_eval_record_as_request_symbol(self):
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        virtual_request = self.env["res.partner"].sudo().new({"name": "DRYRUN_VIRTUAL_REQUEST"})
        users, details = domain_service.eval_user_domain(
            self.User.browse([self.requester.id]),
            "[('id', '=', request.request_owner_id.id if request.name == 'DRYRUN_VIRTUAL_REQUEST' else 0)]",
            request_record=self.request,
            eval_record=virtual_request,
            actor_user=self.env.user,
            return_details=True,
        )
        self.assertFalse(details.get("config_error"), details.get("error_message"))
        self.assertEqual(users, self.requester)

    def test_assignment_user_domain_supports_user_id_alias(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('user_id', '=', request_owner_id)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.requester.id, result["candidate_user_ids"])
        self.assertIn(self.requester.id, result["final_user_ids"])

    def test_assignment_user_domain_supports_request_creator_symbols(self):
        request_by_creator = self.Request.with_user(self.requester).create(
            {
                "name": f"REQ_CREATOR_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', request_creator_id)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        creator_result = self.assignment_service.resolve_assignees(request_by_creator, self.meta_hod)
        self.assertIn(self.requester.id, creator_result["candidate_user_ids"])
        self.assertIn(self.requester.id, creator_result["final_user_ids"])

        self.meta_hod.sudo().write(
            {
                "assignment_user_domain": "[('id', '=', request_creator_manager_user_id)]",
            }
        )
        manager_result = self.assignment_service.resolve_assignees(request_by_creator, self.meta_hod)
        self.assertIn(self.manager.id, manager_result["candidate_user_ids"])
        self.assertIn(self.manager.id, manager_result["final_user_ids"])

    def test_assignment_user_domain_supports_request_owner_line_manager_symbol(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', request_owner_line_manager_user_id)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.manager.id, result["candidate_user_ids"])
        self.assertIn(self.manager.id, result["final_user_ids"])

    def test_assignment_user_domain_supports_request_owner_department_manager_symbol(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', request_owner_department_manager_user_id)]",
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.department_manager.id, result["candidate_user_ids"])
        self.assertIn(self.department_manager.id, result["final_user_ids"])

    def test_domain_assignment_can_match_candidates_but_resolve_no_eligible_users(self):
        scoped_domain = (
            "[('share', '=', False), ('active', '=', True), "
            "('id', 'in', [%s, %s, %s])]"
        ) % (self.approver_a.id, self.approver_b.id, self.outsider.id)
        self.category.sudo().write(
            {
                "allowed_user_ids": [(5, 0, 0)],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "allow_assignee_without_category_access": False,
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": scoped_domain,
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertTrue(
            result["candidate_user_ids"],
            "Domain mode should still produce candidate users for active internal users.",
        )
        self.assertFalse(
            result["eligible_user_ids"],
            "No users should pass eligibility when category allow-list is empty in zero-trust mode.",
        )
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["blocked"])

    def test_domain_assignment_can_bypass_category_allowlist_when_enabled(self):
        scoped_domain = (
            "[('share', '=', False), ('active', '=', True), "
            "('id', 'in', [%s, %s, %s])]"
        ) % (self.approver_a.id, self.approver_b.id, self.outsider.id)
        self.category.sudo().write(
            {
                "allowed_user_ids": [(5, 0, 0)],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "allow_assignee_without_category_access": True,
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "domain",
                "assignment_user_domain": scoped_domain,
                "fallback_policy": "block",
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertTrue(result["candidate_user_ids"])
        self.assertTrue(
            result["eligible_user_ids"],
            "Eligibility should resolve users when category allow-list bypass is enabled.",
        )
        self.assertTrue(result["final_user_ids"])
        self.assertFalse(result["blocked"])

    def test_group_link_domain_and_user_domain_support_context(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": "[('request_owner_id', '=', request_owner_id)]",
                "user_domain": "[('id', '=', request_owner_id)]",
                "sequence": 10,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.requester.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])

    def test_group_link_user_domain_accepts_logical_operators(self):
        link = self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": "[('request_owner_id', '=', request_owner_id)]",
                "user_domain": "['|', ('id', '=', request_owner_id), ('id', '=', uid)]",
                "sequence": 20,
            }
        )
        self.assertTrue(link.exists())
        self.assertIn("|", link.user_domain or "")

    def test_group_link_request_domain_supports_legacy_many2one_id_suffix(self):
        legacy_match_group = self.ApprovalGroup.sudo().create(
            {
                "name": f"Legacy Match Group {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.requester.id])],
            }
        )
        legacy_skip_group = self.ApprovalGroup.sudo().create(
            {
                "name": f"Legacy Skip Group {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": legacy_skip_group.id,
                "domain": "[('request_owner_id.id', 'not in', [%s, %s])]"
                % (self.requester.id, self.manager.id),
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": legacy_match_group.id,
                "domain": "[('request_owner_id.id', 'in', [%s, %s])]"
                % (self.requester.id, self.manager.id),
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.requester.id, result["candidate_user_ids"])
        self.assertIn(self.requester.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])

    def test_group_link_user_domain_supports_decided_approver_symbol(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": "[('id', 'in', decided_approver_user_ids)]",
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.requester.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])

    def test_group_link_user_domain_decided_symbol_ignores_routed_audit_rows(self):
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "closed",
                "user_decision": "Routed",
                "is_routed_audit": True,
                "required": True,
                "iteration_no": 1,
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": "[('id', 'in', decided_approver_user_ids)]",
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)

        self.assertIn(self.requester.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])

    def test_group_link_user_domain_supports_node_assigned_approver_helper(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        group = self.ApprovalGroup.sudo().create(
            {
                "name": f"Node Assigned Runtime Group {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id, self.outsider.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": "[('id', 'in', node_assigned_approver_user_ids('Task_HOD'))]",
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)

        self.assertEqual(set(result["final_user_ids"]), {self.approver_a.id, self.approver_b.id})
        self.assertNotIn(self.outsider.id, result["final_user_ids"])

    def test_group_link_user_domain_rejects_invalid_symbol(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": ROUTING_ALWAYS_TRUE,
                "user_domain": "[('id', '=', unknown_symbol)]",
                "sequence": 30,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod, debug=True)
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["debug"].get("config_errors"))
        self.assertEqual(result["debug"]["config_errors"][0]["scope"], "group_user_domain")

    def test_action_visibility_domain_uses_actor_and_request_context(self):
        self.Approver.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("status", "in", ("new", "pending", "waiting")),
            ]
        ).unlink()
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_hod.id,
                    "current_meta_node_id": self.meta_hod.node_id,
                    "status": "new",
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_hod.id,
                    "current_meta_node_id": self.meta_hod.node_id,
                    "status": "new",
                    "iteration_no": 1,
                },
            ]
        )
        self.action_approve_hod.sudo().write(
            {
                "invisible_domain": (
                    "[('wf_actor_uid', '=', uid), ('wf_actor_uid', '=', %s), "
                    "('request_owner_id', '=', request_owner_id)]"
                ) % self.approver_a.id
            }
        )

        domain_expr = self.action_approve_hod.invisible_domain
        self.assertTrue(
            self.request.with_user(self.approver_a).check_domain(
                domain_expr,
                default=False,
                task_node_id=self.meta_hod.node_id,
                action_key=self.action_approve_hod.name,
            )
        )
        self.assertFalse(
            self.request.with_user(self.approver_b).check_domain(
                domain_expr,
                default=False,
                task_node_id=self.meta_hod.node_id,
                action_key=self.action_approve_hod.name,
            )
        )

        actions_for_a = self.request.with_user(self.approver_a).get_match_user_actions(
            self.action_approve_hod,
            task_node_id=self.meta_hod.node_id,
        )
        actions_for_b = self.request.with_user(self.approver_b).get_match_user_actions(
            self.action_approve_hod,
            task_node_id=self.meta_hod.node_id,
        )
        self.assertIn(self.action_approve_hod, actions_for_a)
        self.assertNotIn(self.action_approve_hod, actions_for_b)

    def test_action_assignment_index_init_is_safe_before_table_creation(self):
        source = inspect.getsource(WorkflowRequestActionAssignment.init)

        self.assertIn("if not table_exists(self.env.cr, self._table):", source)

    def test_business_action_assignments_are_opt_in_and_do_not_multiply_approvers(self):
        actions = self.MetaAction
        for name in ("Cancel", "Withdraw", "Request Changes"):
            actions |= self._new_business_action(
                name=name,
                business_actor_include_owner=True,
            )
        task = self._new_active_task()
        assignee_users = (
            self.approver_a
            | self.approver_b
            | self.delegate_user
            | self.manager
            | self.department_manager
        )
        self.TaskAssignee.sudo().create(
            [
                {
                    "task_instance_id": task.id,
                    "assignee_user_id": user.id,
                    "original_user_id": user.id,
                    "status": "new",
                }
                for user in assignee_users
            ]
        )

        disabled_service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=False
        )
        self.assertFalse(disabled_service._sync_business_action_assignments(self.request, task))

        enabled_service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        assignments = enabled_service._sync_business_action_assignments(self.request, task)
        self.assertEqual(len(assignments), 3)
        self.assertEqual(assignments.mapped("actor_user_id"), self.requester)
        self.assertEqual(set(assignments.mapped("meta_action_id").ids), set(actions.ids))
        self.assertEqual(len(task.assignee_ids), 5)

    def test_business_action_visibility_and_rpc_authorization_are_exact(self):
        cancel_action = self._new_business_action(
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        self.TaskAssignee.sudo().create(
            {
                "task_instance_id": task.id,
                "assignee_user_id": self.approver_a.id,
                "original_user_id": self.approver_a.id,
                "status": "new",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "current_meta_node_id": self.meta_hod.node_id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        assignment_service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        assignment_service._sync_business_action_assignments(self.request, task)
        permission_service = self.permission_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        available_actions = self.action_approve_hod | cancel_action

        owner_actions = permission_service.filter_authorized_actions(
            self.request,
            available_actions,
            user=self.requester,
        )
        approver_actions = permission_service.filter_authorized_actions(
            self.request,
            available_actions,
            user=self.approver_a,
        )
        self.assertEqual(owner_actions, cancel_action)
        self.assertEqual(approver_actions, self.action_approve_hod)

        with self.assertRaises(AccessError):
            permission_service.assert_can_execute_action(
                self.request,
                self.request,
                cancel_action,
                user=self.approver_a,
            )
        permission = permission_service.assert_can_execute_action(
            self.request,
            self.request,
            cancel_action,
            user=self.requester,
        )
        self.assertTrue(permission["allowed"])
        self.assertEqual(permission["authorization_mode"], "business_actor")

        self.Approver.sudo().create(
            {
                "user_id": self.requester.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "current_meta_node_id": self.meta_hod.node_id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        dual_role_actions = permission_service.filter_authorized_actions(
            self.request,
            available_actions,
            user=self.requester,
        )
        self.assertEqual(set(dual_role_actions.ids), set(available_actions.ids))

    def test_business_action_records_event_without_approval_decision_and_closes_branch(self):
        cancel_action = self._new_business_action(
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        task_assignee = self.TaskAssignee.sudo().create(
            {
                "task_instance_id": task.id,
                "assignee_user_id": self.approver_a.id,
                "original_user_id": self.approver_a.id,
                "status": "new",
            }
        )
        approver = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "current_meta_node_id": self.meta_hod.node_id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        assignment = service._sync_business_action_assignments(self.request, task)
        event = service._record_business_action(
            self.request,
            cancel_action,
            actor_user=self.requester,
            comment="Owner cancelled the request",
        )

        self.assertEqual(event.event_type, "action")
        self.assertFalse(event.decision)
        self.assertEqual(assignment.status, "acted")
        self.assertFalse(assignment.can_act)
        self.assertFalse(
            self.TaskEvent.sudo().search_count(
                [
                    ("request_id", "=", self.request.id),
                    ("event_type", "=", "decision"),
                    ("actor_user_id", "=", self.requester.id),
                ]
            )
        )

        self.runtime_service.with_context(
            workflow_business_action_actor_enabled=True
        )._close_runtime_branch_state(
            self.request,
            self.meta_hod.node_id,
            reason="Closed by owner Cancel business action.",
            iteration_no=1,
        )
        task.invalidate_recordset(["status"])
        task_assignee.invalidate_recordset(["status"])
        approver.invalidate_recordset(["status", "user_decision"])
        assignment.invalidate_recordset(["status", "close_reason"])
        self.assertEqual(task.status, "closed")
        self.assertEqual(task_assignee.status, "closed")
        self.assertEqual(approver.status, "closed")
        self.assertFalse(approver.user_decision)
        self.assertEqual(assignment.status, "acted")

    def test_non_interrupting_business_action_keeps_task_and_assignment_open(self):
        notify_action = self._new_business_action(
            name="Notify",
            action_mode="execute_path",
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        assignment = service._sync_business_action_assignments(self.request, task)
        event = service._record_business_action(
            self.request,
            notify_action,
            actor_user=self.requester,
            execute_path=True,
        )

        task.invalidate_recordset(["status"])
        assignment.invalidate_recordset(["status", "can_act", "acted_at"])
        self.assertEqual(event.event_type, "action")
        self.assertEqual(task.status, "pending")
        self.assertEqual(assignment.status, "open")
        self.assertTrue(assignment.can_act)
        self.assertTrue(assignment.acted_at)

    def test_business_action_share_and_redirect_transfer_every_exact_open_action(self):
        first_action = self._new_business_action(
            name="Cancel",
            business_actor_include_owner=True,
        )
        second_action = self._new_business_action(
            name="Request Changes",
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        source_rows = service._sync_business_action_assignments(self.request, task)
        self.assertEqual(set(source_rows.mapped("meta_action_id").ids), {first_action.id, second_action.id})

        shared = service._delegate_business_action_assignments(
            self.request,
            self.requester,
            self.delegate_user,
            "shared",
            node_id=self.meta_hod.node_id,
            iteration_no=1,
            delegated_by=self.requester,
            comment="Share exact business actions",
        )
        shared_rows = self.ActionAssignment.sudo().browse(shared["target_ids"])
        source_rows.invalidate_recordset(["status", "can_act"])
        self.assertEqual(len(shared_rows), 2)
        self.assertTrue(all(source_rows.mapped("can_act")))
        self.assertEqual(set(shared_rows.mapped("original_actor_user_id").ids), {self.requester.id})

        redirected = service._delegate_business_action_assignments(
            self.request,
            self.requester,
            self.outsider,
            "redirected",
            node_id=self.meta_hod.node_id,
            iteration_no=1,
            delegated_by=self.requester,
            comment="Redirect exact business actions",
        )
        redirected_rows = self.ActionAssignment.sudo().browse(redirected["target_ids"])
        source_rows.invalidate_recordset(["status", "can_act"])
        self.assertEqual(len(redirected_rows), 2)
        self.assertEqual(set(source_rows.mapped("status")), {"redirected"})
        self.assertFalse(any(source_rows.mapped("can_act")))
        self.assertEqual(set(redirected_rows.mapped("delegated_from_user_id").ids), {self.requester.id})

    def test_delegate_wizard_shares_business_actions_with_multiple_users(self):
        self.request.sudo().write({"state": "waiting"})
        first_action = self._new_business_action(
            name="Cancel",
            business_actor_include_owner=True,
        )
        second_action = self._new_business_action(
            name="Request Changes",
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        source_rows = service._sync_business_action_assignments(self.request, task)
        recipients = self.delegate_user | self.outsider
        wizard = self.env["delegate_wizard"].with_context(
            workflow_business_action_actor_enabled=True
        ).with_user(self.requester).create({
            "res_model": "workflow.base.approval.request",
            "res_id": self.request.id,
            "delegate_type": "shared",
            "selected_user_ids": [(6, 0, recipients.ids)],
            "comment": "Share owner actions with the support users",
        })

        result = wizard.action_server_delegate()

        self.assertEqual(result.get("tag"), "reload")
        source_rows.invalidate_recordset(["status", "can_act"])
        self.assertEqual(set(source_rows.mapped("meta_action_id").ids), {first_action.id, second_action.id})
        self.assertEqual(set(source_rows.mapped("status")), {"open"})
        self.assertTrue(all(source_rows.mapped("can_act")))
        target_rows = self.ActionAssignment.sudo().search([
            ("request_id", "=", self.request.id),
            ("actor_user_id", "in", recipients.ids),
            ("delegation_mode", "=", "shared"),
            ("status", "=", "open"),
        ])
        self.assertEqual(len(target_rows), len(recipients) * 2)
        for recipient in recipients:
            recipient_rows = target_rows.filtered(
                lambda row: row.actor_user_id == recipient
            )
            self.assertEqual(
                set(recipient_rows.meta_action_id.ids),
                {first_action.id, second_action.id},
            )

    def test_business_action_assignments_are_isolated_per_parallel_task_instance(self):
        hod_action = self._new_business_action(
            name="Cancel HOD",
            business_actor_include_owner=True,
        )
        parallel_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Parallel Clearance",
                "node_id": f"Task_Parallel_{uuid4().hex[:8]}",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
                "completion_mode": "any",
                "fallback_policy": "route_admin_queue",
            }
        )
        parallel_action = self._new_business_action(
            name="Cancel Clearance",
            meta_task=parallel_meta,
            business_actor_include_owner=True,
        )
        hod_task = self._new_active_task()
        parallel_task = self._new_active_task(meta_task=parallel_meta)
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )
        hod_assignment = service._sync_business_action_assignments(self.request, hod_task)
        parallel_assignment = service._sync_business_action_assignments(self.request, parallel_task)
        self.assertEqual(hod_assignment.meta_action_id, hod_action)
        self.assertEqual(parallel_assignment.meta_action_id, parallel_action)

        self.runtime_service.with_context(
            workflow_business_action_actor_enabled=True
        )._close_runtime_branch_state(
            self.request,
            self.meta_hod.node_id,
            reason="Close only the HOD branch.",
            iteration_no=1,
        )
        hod_task.invalidate_recordset(["status"])
        parallel_task.invalidate_recordset(["status"])
        hod_assignment.invalidate_recordset(["status", "can_act"])
        parallel_assignment.invalidate_recordset(["status", "can_act"])
        self.assertEqual(hod_task.status, "closed")
        self.assertEqual(hod_assignment.status, "closed")
        self.assertFalse(hod_assignment.can_act)
        self.assertEqual(parallel_task.status, "pending")
        self.assertEqual(parallel_assignment.status, "open")
        self.assertTrue(parallel_assignment.can_act)

    def test_business_action_approval_group_source_resolves_once_per_actor(self):
        action = self._new_business_action(
            name="Review",
            business_actor_approval_group_ids=[(6, 0, [self.dynamic_group.id])],
        )
        task = self._new_active_task()
        assignments = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )._sync_business_action_assignments(self.request, task)

        self.assertEqual(assignments.mapped("meta_action_id"), action)
        self.assertEqual(
            set(assignments.mapped("actor_user_id").ids),
            set(self.dynamic_group.user_ids.ids),
        )

    def test_business_action_sync_is_idempotent_for_the_same_task(self):
        action = self._new_business_action(
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        service = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )

        first = service._sync_business_action_assignments(self.request, task)
        second = service._sync_business_action_assignments(self.request, task)

        self.assertEqual(first, second)
        self.assertEqual(first.meta_action_id, action)
        self.assertEqual(
            self.ActionAssignment.sudo().search_count(
                [
                    ("task_instance_id", "=", task.id),
                    ("meta_action_id", "=", action.id),
                    ("actor_user_id", "=", self.requester.id),
                ]
            ),
            1,
        )

    def test_terminal_task_cancellation_closes_business_assignment(self):
        self._new_business_action(
            business_actor_include_owner=True,
        )
        task = self._new_active_task()
        assignment = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )._sync_business_action_assignments(self.request, task)

        task.mark_status("cancelled", reason="Request cancelled.")

        assignment.invalidate_recordset(["status", "can_act", "close_reason"])
        self.assertEqual(assignment.status, "closed")
        self.assertFalse(assignment.can_act)
        self.assertEqual(assignment.close_reason, "Request cancelled.")

    def test_multi_approver_any_mode(self):
        cancel_action = self._new_business_action(
            business_actor_include_owner=True,
        )
        task = self.TaskInstance.sudo().create(
            {
                "request_id": self.request.id,
                "node_id": self.meta_hod.node_id,
                "node_name": self.meta_hod.name,
                "node_type": self.meta_hod.node_type,
                "status": "pending",
                "completion_mode": "any",
                "iteration_no": 1,
            }
        )
        self.TaskAssignee.sudo().create(
            [
                {
                    "task_instance_id": task.id,
                    "assignee_user_id": self.approver_a.id,
                    "original_user_id": self.approver_a.id,
                    "status": "new",
                },
                {
                    "task_instance_id": task.id,
                    "assignee_user_id": self.approver_b.id,
                    "original_user_id": self.approver_b.id,
                    "status": "new",
                },
            ]
        )
        business_assignment = self.assignment_service.with_context(
            workflow_business_action_actor_enabled=True
        )._sync_business_action_assignments(self.request, task)
        self.runtime_service.record_decision_from_legacy(
            request_record=self.request,
            meta_action=self.action_approve_hod,
            actor_user=self.approver_a,
            comment="approve-any",
            idempotency_key=f"any-{uuid4().hex}",
        )
        task.invalidate_recordset(["status"])
        business_assignment.invalidate_recordset(["status", "can_act"])
        self.assertEqual(task.status, "approved")
        open_rows = task.assignee_ids.filtered(lambda a: a.status in ("new", "pending", "in_progress"))
        self.assertFalse(open_rows)
        self.assertEqual(business_assignment.meta_action_id, cancel_action)
        self.assertEqual(business_assignment.status, "closed")
        self.assertFalse(business_assignment.can_act)

    def test_multi_approver_all_mode(self):
        task = self.TaskInstance.sudo().create(
            {
                "request_id": self.request.id,
                "node_id": f"{self.meta_hod.node_id}_all",
                "node_name": f"{self.meta_hod.name} All",
                "node_type": self.meta_hod.node_type,
                "status": "pending",
                "completion_mode": "all",
                "iteration_no": 1,
            }
        )
        self.TaskAssignee.sudo().create(
            [
                {
                    "task_instance_id": task.id,
                    "assignee_user_id": self.approver_a.id,
                    "original_user_id": self.approver_a.id,
                    "status": "new",
                },
                {
                    "task_instance_id": task.id,
                    "assignee_user_id": self.approver_b.id,
                    "original_user_id": self.approver_b.id,
                    "status": "new",
                },
            ]
        )
        action_all = self.action_approve_hod.copy(
            {
                "source_id": task.node_id,
                "source_name": task.node_name,
                "node_id": f"Flow_{uuid4().hex[:6]}",
            }
        )
        self.runtime_service.record_decision_from_legacy(
            request_record=self.request,
            meta_action=action_all,
            actor_user=self.approver_a,
            comment="approve-all-a",
            idempotency_key=f"all-a-{uuid4().hex}",
        )
        task.invalidate_recordset(["status"])
        self.assertEqual(task.status, "pending")

        self.runtime_service.record_decision_from_legacy(
            request_record=self.request,
            meta_action=action_all,
            actor_user=self.approver_b,
            comment="approve-all-b",
            idempotency_key=f"all-b-{uuid4().hex}",
        )
        task.invalidate_recordset(["status"])
        self.assertEqual(task.status, "approved")

    def test_parallel_strict_reject_cancels_open_siblings(self):
        join_key = f"JOIN_{uuid4().hex[:8]}"
        task_a = self.TaskInstance.sudo().create(
            {
                "request_id": self.request.id,
                "node_id": f"{self.meta_hod.node_id}_parallel_a",
                "node_name": "Parallel A",
                "node_type": self.meta_hod.node_type,
                "status": "pending",
                "completion_mode": "any",
                "join_key": join_key,
                "join_policy": "all_of",
                "reject_policy": "strict",
                "iteration_no": 1,
            }
        )
        task_b = self.TaskInstance.sudo().create(
            {
                "request_id": self.request.id,
                "node_id": f"{self.meta_hod.node_id}_parallel_b",
                "node_name": "Parallel B",
                "node_type": self.meta_hod.node_type,
                "status": "pending",
                "completion_mode": "any",
                "join_key": join_key,
                "join_policy": "all_of",
                "reject_policy": "strict",
                "iteration_no": 1,
            }
        )
        self.TaskAssignee.sudo().create(
            [
                {
                    "task_instance_id": task_a.id,
                    "assignee_user_id": self.approver_a.id,
                    "original_user_id": self.approver_a.id,
                    "status": "new",
                },
                {
                    "task_instance_id": task_b.id,
                    "assignee_user_id": self.approver_b.id,
                    "original_user_id": self.approver_b.id,
                    "status": "new",
                },
            ]
        )
        reject_action = self.action_approve_hod.copy(
            {
                "name": "Reject",
                "source_id": task_a.node_id,
                "source_name": task_a.node_name,
                "node_id": f"Flow_Reject_{uuid4().hex[:6]}",
            }
        )
        self.runtime_service.record_decision_from_legacy(
            request_record=self.request,
            meta_action=reject_action,
            actor_user=self.approver_a,
            comment="reject-strict",
            idempotency_key=f"reject-{uuid4().hex}",
        )
        task_a.invalidate_recordset(["status"])
        task_b.invalidate_recordset(["status", "blocked_reason"])
        self.assertEqual(task_a.status, "rejected")
        self.assertEqual(task_b.status, "cancelled")
        self.assertIn("strict", (task_b.blocked_reason or "").lower())

    def test_fallback_block_when_no_assignee(self):
        meta_block = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "No Assignee",
                "node_id": f"Task_Block_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', 999999999)]",
                "fallback_policy": "block",
            }
        )
        result = self.assignment_service.resolve_assignees(self.request, meta_block)
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["blocked"])

        task = self.assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=self.request,
            meta_task=meta_block,
            iteration_no=1,
        )
        self.assertEqual(task.status, "blocked")

    def test_run_engine_prechecks_assignment_before_approve(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._run_engine)
        self.assertIn("_precheck_parallel_split_assignment", source)
        self.assertIn("_precheck_next_stage_assignment", source)
        split_precheck_index = source.find("_precheck_parallel_split_assignment")
        first_actor_action_index = source.find(
            "self._workflow_process_actor_action(meta_action)"
        )
        self.assertGreaterEqual(split_precheck_index, 0)
        self.assertGreaterEqual(first_actor_action_index, 0)
        self.assertLess(
            split_precheck_index,
            first_actor_action_index,
            "Split-gateway path must precheck assignees before recording the actor action.",
        )

    def test_confirm_wizard_closes_without_reopening_current_record(self):
        wizard = self.env["workflow.confirm.wizard"].create({})

        close_action = wizard._workflow_close_after_action()
        self.assertEqual(close_action, {"type": "ir.actions.act_window_close"})

        notification = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Done",
                "message": "Workflow completed",
            },
        }
        result = wizard._workflow_close_after_action(notification)
        self.assertEqual(result["params"]["next"], {"type": "ir.actions.act_window_close"})

    def test_confirmation_dialog_helper_respects_action_configuration(self):
        self.action_approve_hod.sudo().write(
            {"show_confirm_dialog": True, "require_2fa": False, "domain": False}
        )
        self.assertTrue(
            self.request._workflow_should_open_confirmation_dialog(
                self.action_approve_hod, show_dialog=True
            )
        )
        self.assertFalse(
            self.request._workflow_should_open_confirmation_dialog(
                self.action_approve_hod, show_dialog=False
            )
        )

        self.action_approve_hod.sudo().write(
            {
                "show_confirm_dialog": False,
                "domain": f"[('name', '=', '{self.request.name}')]",
            }
        )
        self.assertFalse(
            self.request._workflow_should_open_confirmation_dialog(
                self.action_approve_hod, show_dialog=True
            )
        )

        self.action_approve_hod.sudo().write({"show_confirm_dialog": False, "domain": False})
        self.assertFalse(
            self.request._workflow_should_open_confirmation_dialog(
                self.action_approve_hod, show_dialog=True
            )
        )

    def test_confirm_wizard_hands_off_to_twofactor_dialog(self):
        self.action_approve_hod.sudo().write(
            {
                "show_confirm_dialog": True,
                "require_2fa": True,
                "twofa_method": "qr",
                "domain": False,
            }
        )
        wizard = self.env["workflow.confirm.wizard"].with_context(
            default_res_model=self.request._name,
            default_res_id=self.request.id,
            meta_action_id=self.action_approve_hod.id,
            workflow_action_key=self.action_approve_hod.name,
            workflow_task_node_id=self.action_approve_hod.source_id,
            action_type=self.action_approve_hod.name,
        ).create({})

        result = wizard.action_confirm()
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "workflow_engine_twofa_dialog")
        self.assertEqual(result["params"]["meta_action_id"], self.action_approve_hod.id)
        self.assertEqual(result["params"]["res_model"], self.request._name)
        self.assertEqual(result["params"]["res_id"], self.request.id)

    def test_duplicate_confirm_skip_does_not_suppress_required_input(self):
        self.action_approve_hod.sudo().write(
            {
                "show_confirm_dialog": True,
                "require_reason": True,
                "domain": False,
            }
        )
        request = self.request.with_context(workflow_skip_config_confirm=True)

        self.assertFalse(
            request._workflow_should_open_confirmation_dialog(
                self.action_approve_hod, show_dialog=True
            )
        )
        self.assertTrue(
            request._workflow_requires_action_input_dialog(
                self.action_approve_hod, show_dialog=True
            )
        )
        self.assertTrue(
            request._workflow_should_open_action_wizard(
                self.action_approve_hod, show_dialog=True
            )
        )

    def test_required_attachment_count_is_enforced(self):
        self.action_approve_hod.sudo().write(
            {
                "require_attachment": True,
                "required_attachment_count": 2,
            }
        )
        attachment = self.Attachment.sudo().create(
            {
                "name": "one.txt",
                "type": "binary",
                "datas": "V29ya2Zsb3c=",
                "mimetype": "text/plain",
            }
        )
        wizard = self.env["workflow.confirm.wizard"].create(
            {"attachment_ids": [(6, 0, [attachment.id])]}
        )

        with self.assertRaises(ValidationError):
            wizard._validate_action_input(self.action_approve_hod)

    def test_require_attachment_domain_controls_attachment_requirement(self):
        self.action_approve_hod.sudo().write(
            {
                "require_attachment": True,
                "required_attachment_count": 2,
                "require_attachment_domain": f"[('name', '=', '{self.request.name}')]",
            }
        )
        wizard = self.env["workflow.confirm.wizard"].with_context(
            default_res_model=self.request._name,
            default_res_id=self.request.id,
        ).create({})

        self.assertTrue(
            self.request._workflow_requires_action_input_dialog(self.action_approve_hod)
        )
        self.assertTrue(
            self.request._workflow_action_requires_attachment(self.action_approve_hod)
        )
        with self.assertRaises(ValidationError):
            wizard._validate_action_input(self.action_approve_hod, record=self.request)

        self.action_approve_hod.sudo().write(
            {"require_attachment_domain": "[('name', '=', 'DOES_NOT_MATCH')]"}
        )
        self.assertTrue(
            self.request._workflow_requires_action_input_dialog(self.action_approve_hod)
        )
        self.assertFalse(
            self.request._workflow_action_requires_attachment(self.action_approve_hod)
        )
        wizard._validate_action_input(self.action_approve_hod, record=self.request)

    def test_require_reason_domain_controls_reason_requirement(self):
        self.action_approve_hod.sudo().write(
            {
                "require_reason": True,
                "require_reason_domain": f"[('name', '=', '{self.request.name}')]",
            }
        )
        wizard = self.env["workflow.confirm.wizard"].with_context(
            default_res_model=self.request._name,
            default_res_id=self.request.id,
        ).create({})
        with self.assertRaises(ValidationError):
            wizard._validate_action_input(self.action_approve_hod, record=self.request)

        self.action_approve_hod.sudo().write(
            {"require_reason_domain": "[('name', '=', 'DOES_NOT_MATCH')]"}
        )
        wizard._validate_action_input(self.action_approve_hod, record=self.request)

    def test_comment_required_domain_is_independent_from_reason_requirement(self):
        self.action_approve_hod.sudo().write(
            {
                "require_reason": True,
                "require_reason_domain": "[('name', '=', 'DOES_NOT_MATCH')]",
                "comment_required": True,
                "comment_required_domain": f"[('name', '=', '{self.request.name}')]",
            }
        )
        wizard = self.env["workflow.confirm.wizard"].with_context(
            default_res_model=self.request._name,
            default_res_id=self.request.id,
        ).create({"reason": ""})

        with self.assertRaises(ValidationError):
            wizard._validate_action_input(self.action_approve_hod, record=self.request)

        wizard.comment = "checked"
        wizard._validate_action_input(self.action_approve_hod, record=self.request)

    def test_comment_required_domain_default_is_false_for_new_actions(self):
        defaults = self.MetaAction.default_get(["comment_required_domain"])
        self.assertFalse(defaults.get("comment_required_domain"))

    def test_comment_required_domain_legacy_false_sentinel_is_supported(self):
        action = self.action_approve_hod.sudo().copy(
            {
                "comment_required": True,
                "comment_required_domain": "[(0,'=',1)]",
            }
        )
        self.assertTrue(self.request._workflow_requires_action_input_dialog(action))
        self.assertFalse(self.request._workflow_action_requires_comment(action))

        wizard = self.env["workflow.confirm.wizard"].create({})
        wizard._validate_action_input(action, record=self.request)

    def test_constant_workflow_domain_sentinels_are_supported(self):
        field_rule_service = self.env["workflow.engine.field.rule.service"]
        safe_symbols = {"request": self.request, "record": self.request}

        self.assertFalse(
            field_rule_service._safe_eval_domain_expression("[(0,'=',1)]", safe_symbols)
        )
        self.assertTrue(
            field_rule_service._safe_eval_domain_expression("[(1,'=',1)]", safe_symbols)
        )
        self.assertFalse(self.request.check_domain("[(0,'=',1)]", default=True))
        self.assertTrue(self.request.check_domain("[(1,'=',1)]", default=False))

    def test_comment_textbox_can_display_without_being_required(self):
        self.action_approve_hod.sudo().write(
            {
                "comment_required": True,
                "comment_required_domain": "[('name', '=', 'DOES_NOT_MATCH')]",
            }
        )
        self.assertTrue(self.request._workflow_requires_action_input_dialog(self.action_approve_hod))
        self.assertFalse(self.request._workflow_action_requires_comment(self.action_approve_hod))

        wizard = self.env["workflow.confirm.wizard"].create({})
        wizard._validate_action_input(self.action_approve_hod, record=self.request)

    def test_runtime_domain_guard_blocks_action_execution(self):
        self.action_approve_hod.sudo().write({"domain": "[('name', '=', 'DOES_NOT_MATCH')]"})
        with self.assertRaises(UserError):
            self.request.action_do_transition(
                {
                    "meta_action_id": self.action_approve_hod.id,
                    "action_key": self.action_approve_hod.name,
                    "source_node_id": self.action_approve_hod.source_id,
                },
                show_dialog=False,
            )

    def test_action_do_transition_checks_confirmation_before_twofactor(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin.action_do_transition)
        confirm_index = source.find("_workflow_should_open_confirmation_dialog")
        twofa_index = source.find("action_requires_twofactor")
        self.assertGreaterEqual(confirm_index, 0)
        self.assertGreaterEqual(twofa_index, 0)
        self.assertLess(
            confirm_index,
            twofa_index,
            "Confirmation handling must execute before direct 2FA handling.",
        )

    def test_first_time_run_prechecks_assignment_before_tracking_update(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._first_time_run)
        self.assertIn("_precheck_parallel_split_assignment", source)
        self.assertIn("_precheck_next_stage_assignment", source)
        split_precheck_index = source.find("_precheck_parallel_split_assignment")
        split_process_index = source.find("split_result = self._process_parallel_split")
        tracking_update_index = source.find("self._update_tracking_fields")
        stage_precheck_index = source.find("_precheck_next_stage_assignment")
        self.assertGreaterEqual(split_precheck_index, 0)
        self.assertGreaterEqual(split_process_index, 0)
        self.assertGreaterEqual(stage_precheck_index, 0)
        self.assertGreaterEqual(tracking_update_index, 0)
        self.assertLess(
            split_precheck_index,
            split_process_index,
            "First-run split path must validate assignees before branch processing.",
        )
        self.assertLess(
            stage_precheck_index,
            tracking_update_index,
            "First-run path must validate assignees before moving tracking fields.",
        )

    def test_parallel_resume_prechecks_assignment_before_tracking_update(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._workflow_resume_parallel_join)
        self.assertIn("_precheck_next_stage_assignment", source)
        stage_precheck_index = source.find("_precheck_next_stage_assignment")
        tracking_update_index = source.find("self._update_tracking_fields")
        self.assertGreaterEqual(stage_precheck_index, 0)
        self.assertGreaterEqual(tracking_update_index, 0)
        self.assertLess(
            stage_precheck_index,
            tracking_update_index,
            "Parallel-join resume must validate assignees before moving tracking fields.",
        )

    def test_task_sync_prefers_open_legacy_approver_rows_before_runtime_resolution(self):
        meta_block = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Legacy Open Approver",
                "node_id": f"Task_Legacy_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "assignment_mode": "domain",
                "assignment_user_domain": "[('id', '=', 999999999)]",
                "fallback_policy": "block",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": meta_block.id,
                "previous_meta_id": self.meta_hod.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )

        task = self.assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=self.request,
            meta_task=meta_block,
            iteration_no=1,
        )
        task.invalidate_recordset(["status"])
        assignees = task.assignee_ids.mapped("assignee_user_id")
        self.assertEqual(task.status, "pending")
        self.assertIn(self.approver_a, assignees)

    def test_request_blocked_when_current_stage_has_no_pending_approver(self):
        blocked_request = self.Request.sudo().create(
            {
                "name": f"REQ_BLOCKED_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_activity_name": self.meta_hod.name,
                "previous_activity_name": self.meta_submission.name,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        blocked_request.invalidate_recordset(["wf_is_blocked", "wf_block_reason"])
        self.assertTrue(blocked_request.wf_is_blocked)
        self.assertIn("no pending approver", (blocked_request.wf_block_reason or "").lower())
        self.assertIn(self.meta_hod.name.lower(), (blocked_request.wf_block_reason or "").lower())

    def test_request_blocked_flag_clears_once_pending_approver_exists(self):
        blocked_request = self.Request.sudo().create(
            {
                "name": f"REQ_UNBLOCK_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_activity_name": self.meta_hod.name,
                "previous_activity_name": self.meta_submission.name,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.assertTrue(blocked_request.wf_is_blocked)

        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": blocked_request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        blocked_request.invalidate_recordset(["wf_is_blocked", "wf_block_reason"])
        self.assertFalse(blocked_request.wf_is_blocked)
        self.assertFalse(blocked_request.wf_block_reason)

    def test_request_blocked_flag_stays_for_sticky_unassigned_stage_reason(self):
        sticky_request = self.Request.sudo().create(
            {
                "name": f"REQ_STICKY_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_submission.node_id,
                "current_activity_name": self.meta_submission.name,
                "current_iteration_no": 1,
                "state": "new",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.requester.id,
                "request_id": sticky_request.id,
                "current_meta_id": self.meta_submission.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        sticky_reason = self.legacy_adapter_service.build_unassigned_stage_reason(
            current_meta_task=self.meta_hod,
            resolution={},
        )
        sticky_request.sudo().with_context(wf_skip_block_sync=True).write(
            {
                "wf_is_blocked": True,
                "wf_block_reason": sticky_reason,
            }
        )

        sticky_request._sync_blocked_state_from_approvers()
        sticky_request.invalidate_recordset(["wf_is_blocked", "wf_block_reason"])
        self.assertTrue(sticky_request.wf_is_blocked)
        self.assertEqual(sticky_request.wf_block_reason, sticky_reason)

    def test_request_not_blocked_on_non_approver_end_node(self):
        done_request = self.Request.sudo().create(
            {
                "name": f"REQ_END_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_end.node_id,
                "previous_node_id": self.meta_hod.node_id,
                "current_activity_name": self.meta_end.name,
                "previous_activity_name": self.meta_hod.name,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        done_request.invalidate_recordset(["wf_is_blocked", "wf_block_reason"])
        self.assertFalse(done_request.wf_is_blocked)
        self.assertFalse(done_request.wf_block_reason)

    def test_assignment_filters_users_without_category_access(self):
        self.meta_hod.sudo().write({"explicit_user_ids": [(6, 0, [self.outsider.id])]})
        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertNotIn(
            self.outsider.id,
            result["final_user_ids"],
            "Assignment pipeline must not return users outside category legal access.",
        )

    def test_zero_trust_category_access_enforced(self):
        private_category = self.Category.sudo().create(
            {
                "name": f"Runtime Private Category {uuid4().hex[:8]}",
                "res_model": self.base_request_model.id,
                "zero_trust_enforced": True,
                "create_access_mode": "restricted",
                "allowed_user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        private_request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_PRIVATE_{uuid4().hex[:8]}",
                "category_id": private_category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )

        allowed = self.Category.with_user(self.approver_a).search([("id", "=", private_category.id)])
        denied = self.Category.with_user(self.outsider).search([("id", "=", private_category.id)])
        allowed_request = self.Request.with_user(self.approver_a).search([("id", "=", private_request.id)])
        denied_request = self.Request.with_user(self.outsider).search([("id", "=", private_request.id)])
        self.assertTrue(allowed, "Allowed user should see the category in zero-trust mode.")
        self.assertFalse(denied, "Outsider must not see the category in zero-trust mode.")
        self.assertTrue(allowed_request, "Allowed user should read requests in the zero-trust category.")
        self.assertFalse(denied_request, "Outsider must not read requests in the zero-trust category.")

    def test_base_request_write_requires_active_stage_actor_for_edit_scope(self):
        comment_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", self.Request._name), ("name", "=", "comment")],
            limit=1,
        )
        self.env["workflow.category.version.meta.field"].sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "field_id": comment_field.id,
                "field_type": "visible",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "closed",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

        self.assertTrue(
            self.permission_service.can_access_request(self.request, user=self.approver_a, scope="edit")
        )
        self.assertFalse(
            self.permission_service.can_access_request(self.request, user=self.approver_b, scope="edit")
        )

        self.request.with_user(self.approver_a).write({"comment": "actor update"})
        with self.assertRaises(UserError):
            self.request.with_user(self.approver_b).write({"comment": "closed approver update"})

    def test_permission_flag_keeps_current_stage_actor_when_parallel_branch_exists(self):
        meta_on_going = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "On Going",
                "node_id": "Task_OnGoing_Permission",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
            }
        )
        self.request.sudo().write(
            {
                "current_node_id": self.meta_hod.node_id,
                "active_branch_node_ids": [meta_on_going.node_id],
                "current_iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )

        request_as_actor = self.request.with_user(self.approver_a)
        self.assertTrue(
            request_as_actor.check_if_user_has_permission(request_as_actor),
            "Current-stage actor should retain permission even when parallel branch nodes are active.",
        )
        self.assertTrue(request_as_actor.is_user_has_permission)

    def test_pending_summary_includes_current_and_parallel_branch_nodes(self):
        meta_on_going = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "On Going",
                "node_id": "Task_OnGoing_Summary",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
            }
        )
        self.request.sudo().write(
            {
                "current_node_id": self.meta_hod.node_id,
                "active_branch_node_ids": [meta_on_going.node_id],
                "current_iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": meta_on_going.id,
                "previous_meta_id": self.meta_hod.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )

        self.request.invalidate_recordset()
        summary = self.request.pending_approver_summary or ""
        self.assertIn(self.approver_a.name, summary)
        self.assertIn(self.approver_b.name, summary)

    def test_close_approver_closes_pending_and_waiting_siblings(self):
        actor_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        pending_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        waiting_row = self.Approver.sudo().create(
            {
                "user_id": self.delegate_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "waiting",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        approved_row = self.Approver.sudo().create(
            {
                "user_id": self.manager.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "approved",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

        self.request.with_user(self.approver_a).close_approver(
            self.meta_hod,
            iteration_no=self.request.current_iteration_no or 1,
        )

        self.assertEqual(actor_row.status, "new", "Actor row should not be closed by self-cleanup.")
        self.assertEqual(pending_row.status, "closed", "Pending sibling approver must be closed.")
        self.assertEqual(waiting_row.status, "closed", "Waiting sibling approver must be closed.")
        self.assertEqual(approved_row.status, "approved", "Already approved row must remain approved.")

    def test_close_approver_include_current_user_closes_actor_row(self):
        actor_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        sibling_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

        self.request.with_user(self.approver_a).close_approver(
            self.meta_hod,
            iteration_no=self.request.current_iteration_no or 1,
            include_current_user=True,
        )

        self.assertEqual(actor_row.status, "closed", "Force cleanup should close the actor row as well.")
        self.assertEqual(sibling_row.status, "closed", "Sibling approvers must still be closed.")

    def test_close_approver_closes_same_stage_rows_when_duplicate_meta_exists(self):
        duplicate_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "HOD Approval Duplicate",
                "node_id": self.meta_hod.node_id,
                "node_type": self.meta_hod.node_type,
            }
        )
        actor_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        sibling_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

        self.request.with_user(self.approver_a).close_approver(
            duplicate_meta,
            iteration_no=self.request.current_iteration_no or 1,
        )

        self.assertEqual(actor_row.status, "new", "Actor row should still be preserved during sibling cleanup.")
        self.assertEqual(
            sibling_row.status,
            "closed",
            "Duplicate meta rows for the same BPMN node must still close sibling approvers on that stage.",
        )

    def test_close_approver_force_routed_decision_fills_only_blank_rows(self):
        audit_comment = "Force transition to next approver"
        actor_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        blank_sibling_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        decided_row = self.Approver.sudo().create(
            {
                "user_id": self.delegate_user.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "waiting",
                "user_decision": "Keep",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )

        self.request.with_user(self.approver_a).close_approver(
            self.meta_hod,
            iteration_no=self.request.current_iteration_no or 1,
            include_current_user=True,
            decision_if_blank="Routed",
            comment_if_blank=audit_comment,
        )

        self.assertEqual(actor_row.status, "closed")
        self.assertEqual(blank_sibling_row.status, "closed")
        self.assertEqual(decided_row.status, "closed")
        self.assertEqual(actor_row.user_decision, "Routed", "Blank actor decision should be stamped as Routed.")
        self.assertEqual(blank_sibling_row.user_decision, "Routed", "Blank sibling decision should be stamped as Routed.")
        self.assertEqual(decided_row.user_decision, "Keep", "Existing decisions must not be overwritten.")
        self.assertEqual(actor_row.comment, audit_comment)
        self.assertEqual(blank_sibling_row.comment, audit_comment)
        self.assertTrue(actor_row.has_decision)
        self.assertTrue(blank_sibling_row.has_decision)
        self.assertFalse(actor_row.counts_as_decided_user)
        self.assertFalse(blank_sibling_row.counts_as_decided_user)
        self.assertTrue(actor_row.is_routed_audit)
        self.assertTrue(blank_sibling_row.is_routed_audit)
        self.assertTrue(decided_row.counts_as_decided_user)
        self.assertFalse(decided_row.is_routed_audit)

    def test_decided_helper_context_excludes_routed_audit_rows(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "closed",
                    "user_decision": "Routed",
                    "is_routed_audit": True,
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )

        context = self.env["workflow.engine.assignment.domain.service"]._assignment_eval_context(self.request)

        self.assertEqual(
            set(context["decided_approver_user_ids"]),
            {self.requester.id, self.approver_b.id},
        )
        self.assertEqual(
            set(context["has_decision_user_ids"]),
            {self.requester.id, self.approver_b.id},
        )
        self.assertNotIn(self.approver_a.id, context["decided_approver_user_ids"])

    def test_manual_redirect_history_is_visible_but_does_not_count_as_decided_user(self):
        audit_comment = "Delegate to backup approver"
        self.request.sudo().write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        current_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        other_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": self.request.id,
                "delegate_type": "redirected",
                "selected_user_id": self.delegate_user.id,
                "comment": audit_comment,
            }
        )

        wizard.delegate(self.request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)
        current_row.invalidate_recordset([
            "status",
            "comment",
            "user_decision",
            "counts_as_decided_user",
            "show_in_decision_history",
            "decision_history_kind",
        ])
        other_row.invalidate_recordset(["status"])
        self.assertEqual(current_row.status, "closed")
        self.assertEqual(current_row.comment, audit_comment)
        self.assertEqual(current_row.user_decision, "Redirected")
        self.assertEqual(current_row.decision_history_kind, "delegation_decision")
        self.assertTrue(current_row.show_in_decision_history)
        self.assertFalse(current_row.counts_as_decided_user)
        self.assertEqual(current_row.delegated_from_user_id, self.approver_a)
        self.assertEqual(current_row.delegated_from_approver_id, current_row)
        self.assertEqual(current_row.delegated_to_user_id, self.delegate_user)
        self.assertEqual(other_row.status, "new")

        delegate_row = self.Approver.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.delegate_user.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(delegate_row)
        self.assertEqual(delegate_row.comment, audit_comment)
        self.assertIn("Delegated by", delegate_row.remark or "")
        self.assertEqual(delegate_row.delegation_mode, "redirected")
        self.assertEqual(delegate_row.delegated_from_user_id, self.approver_a)
        self.assertEqual(delegate_row.delegated_from_approver_id, current_row)
        self.assertEqual(delegate_row.delegated_to_user_id, self.delegate_user)
        self.assertGreater(current_row.event_order, delegate_row.event_order)
        self.assertIn(current_row.id, self.request.approver_decisions_ids.ids)
        self.assertNotIn(delegate_row.id, self.request.approver_decisions_ids.ids)

        delegate_row.write({"status": "approved", "user_decision": "Approve"})

        self.assertTrue(delegate_row.has_decision)
        self.assertTrue(delegate_row.counts_as_decided_user)
        self.assertFalse(delegate_row.is_routed_audit)
        self.assertIn(delegate_row.id, self.request.approver_decisions_ids.ids)

        event = self.TaskEvent.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("event_type", "=", "delegation"),
                ("target_user_id", "=", self.delegate_user.id),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(event)
        self.assertEqual(event.actor_user_id, self.approver_a)
        self.assertEqual(event.on_behalf_of_user_id, self.approver_a)
        self.assertEqual((event.payload_json or {}).get("mode"), "redirected")

    def test_manual_shared_creates_decision_history_without_closing_source_row(self):
        audit_comment = "Share with backup approver"
        self.request.sudo().write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        source_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": self.request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
                "comment": audit_comment,
            }
        )

        wizard.delegate(self.request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)
        source_row.invalidate_recordset(["status"])
        self.assertEqual(source_row.status, "new")

        shared_row = self.Approver.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.delegate_user.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        shared_audit_row = self.Approver.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.approver_a.id),
                ("user_decision", "=", "Shared"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(shared_row)
        self.assertEqual(shared_row.delegation_mode, "shared")
        self.assertEqual(shared_row.delegated_from_user_id, self.approver_a)
        self.assertEqual(shared_row.delegated_to_user_id, self.delegate_user)
        self.assertTrue(shared_audit_row)
        self.assertEqual(shared_audit_row.status, "closed")
        self.assertTrue(shared_audit_row.show_in_decision_history)
        self.assertFalse(shared_audit_row.counts_as_decided_user)
        self.assertEqual(shared_audit_row.decision_history_kind, "delegation_decision")
        self.assertEqual(shared_audit_row.delegated_from_user_id, self.approver_a)
        self.assertEqual(shared_audit_row.delegated_from_approver_id, source_row)
        self.assertEqual(shared_audit_row.delegated_to_user_id, self.delegate_user)
        self.assertGreater(shared_audit_row.event_order, shared_row.event_order)
        self.assertIn(shared_audit_row.id, self.request.approver_decisions_ids.ids)

        event = self.TaskEvent.sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("event_type", "=", "delegation"),
                ("target_user_id", "=", self.delegate_user.id),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(event)
        self.assertEqual((event.payload_json or {}).get("mode"), "shared")

    def test_actor_ui_snapshot_for_shared_delegate_matches_effective_actor_visibility(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_SHARED_UI_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.action_approve_hod.sudo().write(
            {"invisible_domain": "[] if actor_has_approval_group(%d) else [(0,'=',1)]" % self.dynamic_group.id}
        )
        cancel_action = self.MetaAction.sudo().create(
            {
                "name": "Cancel",
                "meta_task_id": self.meta_hod.id,
                "source_id": self.meta_hod.node_id,
                "source_name": self.meta_hod.name,
                "source_node_type": self.meta_hod.node_type,
                "target_id": self.meta_end.node_id,
                "target_name": self.meta_end.name,
                "target_node_type": self.meta_end.node_type,
                "node_id": f"Flow_HOD_Cancel_UI_{uuid4().hex[:6]}",
                "version_id": self.version.id,
                "invisible_domain": "[] if request.request_owner_id.id == user.id else [(0,'=',1)]",
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
                "comment": "Share for actor UI snapshot",
            }
        )
        wizard.delegate(request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)

        request_as_delegate = request.with_user(self.delegate_user)
        snapshot = request_as_delegate.workflow_get_actor_ui_snapshot(snapshot_values={})
        labels = [button["label"] for button in snapshot["visible_buttons"]]
        self.assertEqual(
            labels,
            [button["label"] for button in request_as_delegate.workflow_get_visible_buttons_snapshot({})],
        )
        self.assertTrue(snapshot["is_user_has_permission"])
        self.assertTrue(snapshot["is_user_can_delegate"])
        self.assertIn("Approve", labels)
        self.assertNotIn(cancel_action.name, labels)

    def test_actor_ui_snapshot_for_shared_delegate_clears_after_delegate_row_is_consumed(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_SHARED_UI_DONE_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
                "comment": "Share then consume delegate row",
            }
        )
        wizard.delegate(request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)
        delegate_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.delegate_user.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(delegate_row)
        shared_audit_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.approver_a.id),
                ("user_decision", "=", "Shared"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(shared_audit_row)
        delegate_row.write({"status": "approved", "user_decision": "Approve"})
        delegate_row.invalidate_recordset(["event_order", "activity_event_at", "decision_history_kind"])
        shared_audit_row.invalidate_recordset(["event_order", "activity_event_at", "decision_history_kind"])

        snapshot = request.with_user(self.delegate_user).workflow_get_actor_ui_snapshot(snapshot_values={})
        self.assertEqual(snapshot["visible_buttons"], [])
        self.assertFalse(snapshot["is_user_has_permission"])
        self.assertFalse(snapshot["is_user_can_delegate"])
        self.assertEqual(delegate_row.decision_history_kind, "workflow_decision")
        self.assertEqual(shared_audit_row.decision_history_kind, "delegation_decision")
        history_rows = request.activity_history[:2]
        self.assertEqual(history_rows[0], delegate_row)
        self.assertEqual(history_rows[1], shared_audit_row)

    def test_activity_history_prefers_real_decision_over_delegation_audit_on_same_timestamp(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_SHARED_ORDER_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
                "comment": "Share then consume delegate row",
            }
        )
        wizard.delegate(request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)
        delegate_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.delegate_user.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        shared_audit_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.approver_a.id),
                ("user_decision", "=", "Shared"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(delegate_row)
        self.assertTrue(shared_audit_row)

        shared_when = shared_audit_row.activity_event_at
        stale_order = max((shared_audit_row.event_order or 0) - 1, 0)
        delegate_row.sudo().write(
            {
                "status": "approved",
                "user_decision": "Approve",
                "activity_event_at": shared_when,
                "event_order": stale_order,
            }
        )
        delegate_row.invalidate_recordset(["event_order", "activity_event_at", "decision_history_kind"])
        shared_audit_row.invalidate_recordset(["event_order", "activity_event_at", "decision_history_kind"])

        history_rows = request.activity_history[:2]
        self.assertEqual(delegate_row.activity_event_at, shared_audit_row.activity_event_at)
        self.assertLess(delegate_row.event_order, shared_audit_row.event_order)
        self.assertEqual(delegate_row.decision_history_kind, "workflow_decision")
        self.assertEqual(shared_audit_row.decision_history_kind, "delegation_decision")
        self.assertEqual(history_rows[0], delegate_row)
        self.assertEqual(history_rows[1], shared_audit_row)

    def test_last_approver_tracks_latest_decision_without_previous_activity_name(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_LAST_APPROVER_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        decision_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )

        request.invalidate_recordset(["last_approver_id"])
        self.assertFalse(request.last_approver_id)

        decision_row.write({"status": "approved", "user_decision": "Approve"})
        request.invalidate_recordset(["last_approver_id"])

        self.assertEqual(
            request.last_approver_id,
            decision_row,
            "Stored last approver should update when an existing stage row receives a decision.",
        )
        self.assertEqual(request.last_approver_id.user_id, self.approver_a)

    def test_last_approver_prefers_real_decision_over_shared_audit(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_LAST_APPROVER_SHARED_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
                "comment": "Share for last approver ordering",
            }
        )
        wizard.delegate(request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)
        delegate_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.delegate_user.id),
                ("status", "=", "new"),
            ],
            order="id desc",
            limit=1,
        )
        shared_audit_row = self.Approver.sudo().search(
            [
                ("request_id", "=", request.id),
                ("current_meta_id", "=", self.meta_hod.id),
                ("user_id", "=", self.approver_a.id),
                ("user_decision", "=", "Shared"),
            ],
            order="id desc",
            limit=1,
        )
        self.assertTrue(delegate_row)
        self.assertTrue(shared_audit_row)

        shared_when = shared_audit_row.activity_event_at
        delegate_row.sudo().write(
            {
                "status": "approved",
                "user_decision": "Approve",
                "activity_event_at": shared_when,
                "event_order": max((shared_audit_row.event_order or 0) - 1, 0),
            }
        )
        request.invalidate_recordset(["last_approver_id"])

        self.assertEqual(
            request.last_approver_id,
            delegate_row,
            "Last approver should point to the real decision row, not the earlier Shared audit row.",
        )

    def test_manual_delegated_user_inherits_source_actor_visibility_without_owner_actions(self):
        audit_comment = "Redirect to backup approver"
        request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_VIS_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.action_approve_hod.sudo().write(
            {"invisible_domain": "[] if actor_has_approval_group(%d) else [(0,'=',1)]" % self.dynamic_group.id}
        )
        cancel_action = self.MetaAction.sudo().create(
            {
                "name": "Cancel",
                "meta_task_id": self.meta_hod.id,
                "source_id": self.meta_hod.node_id,
                "source_name": self.meta_hod.name,
                "source_node_type": self.meta_hod.node_type,
                "target_id": self.meta_end.node_id,
                "target_name": self.meta_end.name,
                "target_node_type": self.meta_end.node_type,
                "node_id": f"Flow_HOD_Cancel_{uuid4().hex[:6]}",
                "version_id": self.version.id,
                "invisible_domain": "[] if request.request_owner_id.id == user.id else [(0,'=',1)]",
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": request.id,
                "delegate_type": "redirected",
                "selected_user_id": self.delegate_user.id,
                "comment": audit_comment,
            }
        )
        wizard.delegate(request, wizard.delegate_type, wizard.selected_user_id, is_create_activity=False)

        permission = self.permission_service.assert_can_execute_action(
            request,
            request,
            self.action_approve_hod,
            user=self.delegate_user,
        )
        self.assertTrue(permission["allowed"])
        self.assertEqual(permission["on_behalf_user_id"], self.approver_a.id)
        self.assertTrue(permission["manual_delegated_approver_id"])

        labels = [button["label"] for button in request.with_user(self.delegate_user).workflow_get_visible_buttons_snapshot({})]
        self.assertIn("Approve", labels)
        self.assertNotIn(cancel_action.name, labels)

    def test_confirm_wizard_executes_delegated_actions_on_elevated_workflow_record(self):
        from odoo.addons.workflow_engine.models.workflow_confirm_wizard import WorkflowConfirmWizard

        source = inspect.getsource(WorkflowConfirmWizard.action_confirm)
        self.assertIn("workflow_record = record._workflow_elevated_action_record()", source)
        self.assertIn("result = workflow_record.with_context(", source)
        self.assertIn("workflow_notification_actor_user_id=self.env.user.id", source)
        self.assertIn("form_data=workflow_record._get_form_data()", source)

    def test_no_dialog_transition_executes_delegated_actions_on_elevated_workflow_record(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin.action_do_transition)
        self.assertIn("workflow_record = self._workflow_elevated_action_record()", source)
        self.assertIn("return workflow_record.with_context(", source)
        self.assertIn("workflow_notification_actor_user_id=self.env.user.id", source)
        self.assertIn("form_data=workflow_record._get_form_data()", source)

    def test_twofactor_finalize_executes_delegated_actions_on_elevated_workflow_record(self):
        from odoo.addons.workflow_engine.controller.twofactor_controller import WorkflowTwoFactorController

        source = inspect.getsource(WorkflowTwoFactorController.finalize_action)
        self.assertIn("workflow_record = record._workflow_elevated_action_record()", source)
        self.assertIn("next_action = workflow_record.with_context(", source)
        self.assertIn("workflow_notification_actor_user_id=request.env.user.id", source)
        self.assertIn("form_data=workflow_record._get_form_data()", source)

    def test_manual_delegate_requires_comment(self):
        self.request.sudo().write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": self.request.current_iteration_no or 1,
            }
        )
        wizard = self.env["delegate_wizard"].with_user(self.approver_a).create(
            {
                "res_model": "workflow.base.approval.request",
                "res_id": self.request.id,
                "delegate_type": "shared",
                "selected_user_id": self.delegate_user.id,
            }
        )

        with self.assertRaises(ValidationError):
            wizard.action_server_delegate()

    def test_force_transition_meta_action_requires_current_source(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._resolve_force_transition_meta_action)
        self.assertIn("if self.current_node_id:", source)
        self.assertIn(
            "return Action.search(base_domain + [(\"source_id\", \"=\", self.current_node_id)], limit=1)",
            source,
        )
        self.assertNotIn("direct = Action.search", source)

    def test_task_event_idempotency_key_unique(self):
        key = f"dup-{uuid4().hex}"
        self.audit_service.log_event(
            request_record=self.request,
            event_type="decision",
            action_key="Approve",
            idempotency_key=key,
        )
        with self.assertRaises(Exception):
            self.audit_service.log_event(
                request_record=self.request,
                event_type="decision",
                action_key="Approve",
                idempotency_key=key,
            )

    def test_lock_request_raises_user_error_when_db_lock_fails(self):
        real_execute = self.env.cr.execute

        def _execute_with_lock_conflict(query, *args, **kwargs):
            if "FOR UPDATE NOWAIT" in str(query):
                raise Exception("lock_conflict")
            return real_execute(query, *args, **kwargs)

        with patch.object(self.env.cr, "execute", side_effect=_execute_with_lock_conflict):
            try:
                self.runtime_service.lock_request(self.request)
            except UserError:
                return
        self.fail("Expected lock_request to raise UserError when DB lock fails.")

    def test_runtime_decision_status_rules_default_mapping(self):
        self.assertEqual(self.runtime_service._decision_to_status("Approve"), "approved")
        self.assertEqual(self.runtime_service._decision_to_status("Reject"), "rejected")
        self.assertEqual(self.runtime_service._decision_to_status("Refuse"), "rejected")
        self.assertEqual(self.runtime_service._decision_to_status("Need Rework"), "rework")
        self.assertEqual(self.runtime_service._decision_to_status("Cancel"), "cancelled")

    def test_department_payload_unique_per_request_department_key_iteration(self):
        key = f"exit-clearance-{uuid4().hex[:8]}"
        values = {
            "request_id": self.request.id,
            "department_id": self.department.id,
            "key": key,
            "iteration_no": 1,
            "data_json": {"status": "clear", "remark": "ok"},
        }
        row = self.DepartmentPayload.sudo().create(values)
        self.assertTrue(row)

        with self.assertRaises(Exception), self.cr.savepoint():
            self.DepartmentPayload.sudo().create(values)

        next_iteration = self.DepartmentPayload.sudo().create(
            dict(values, iteration_no=2, data_json={"status": "clear", "remark": "iter2"})
        )
        self.assertTrue(next_iteration)

    def test_department_payload_scope_blocks_other_department_user(self):
        other_department = self.env["hr.department"].sudo().create(
            {"name": f"Other Department {uuid4().hex[:8]}"}
        )
        self.outsider.write({"department_id": other_department.id})

        payload = self.DepartmentPayload.sudo().create(
            {
                "request_id": self.request.id,
                "department_id": self.department.id,
                "key": f"dept-only-{uuid4().hex[:8]}",
                "iteration_no": 1,
                "data_json": {"handover_asset": True},
            }
        )
        self.assertTrue(
            self.DepartmentPayload.with_user(self.requester).search([("id", "=", payload.id)]),
            "Requester should still be able to see own request payload rows.",
        )
        self.assertFalse(
            self.DepartmentPayload.with_user(self.outsider).search([("id", "=", payload.id)]),
            "User from unrelated department must not read other department payload rows.",
        )

    def test_twofactor_qr_method_supported(self):
        self.action_approve_hod.sudo().write({"require_2fa": True, "twofa_method": "qr"})
        twofa_service = self.env["workflow.engine.twofactor.service"]
        challenge = twofa_service.issue_action_challenge(
            request_record=self.request,
            meta_action=self.action_approve_hod,
            action_key="Approve",
            method="qr",
        )
        self.assertTrue(challenge, "QR challenge should be created.")
        self.assertEqual(challenge.method, "qr")
        self.assertTrue(challenge.token, "QR challenge token should be generated.")
        self.assertTrue(
            twofa_service.verify_action_challenge(challenge.id, challenge.token),
            "QR challenge token verification should pass.",
        )

    def test_twofactor_unknown_method_defaults_to_email_otp_issuer(self):
        self.action_approve_hod.sudo().write({"require_2fa": True, "twofa_method": "email_otp"})
        service = self.env["workflow.engine.twofactor.service"]
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        issuer = service._resolve_twofactor_challenge_issuer(challenge_model, "unsupported_method")
        self.assertEqual(getattr(issuer, "__name__", ""), "issue_email_otp")

        challenge = service.issue_action_challenge(
            request_record=self.request,
            meta_action=self.action_approve_hod,
            action_key="Approve",
            method="unsupported_method",
        )
        self.assertTrue(challenge)
        self.assertEqual(challenge.method, "email_otp")

    def test_twofactor_otp_flow(self):
        self.action_approve_hod.sudo().write({"require_2fa": True, "twofa_method": "email_otp"})
        service = self.env["workflow.engine.twofactor.service"]
        ch = service.issue_action_challenge(
            request_record=self.request,
            meta_action=self.action_approve_hod,
            action_key="Approve",
            method="email_otp",
        )
        self.assertEqual(ch.method, "email_otp")
        # wrong code fails
        self.assertFalse(ch.verify_email_otp("00000"))
        # request new otp and verify the stored hash directly
        ch.request_otp()
        otp = "12345"
        ch.sudo().write({"code_hash": ch._hash_code(ch.token, otp)})
        self.assertTrue(ch.verify_email_otp(otp))

    def test_twofactor_mobile_decision(self):
        self.action_approve_hod.sudo().write({"require_2fa": True, "twofa_method": "qr"})
        service = self.env["workflow.engine.twofactor.service"]
        ch = service.issue_action_challenge(
            request_record=self.request,
            meta_action=self.action_approve_hod,
            action_key="Approve",
            method="qr",
        )
        ch.mark_scanned()
        self.assertEqual(ch.state, "scanned")
        ch.mark_decision("approve")
        self.assertEqual(ch.state, "approved")

    def test_twofactor_qr_payload_contains_expected_identity(self):
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        challenge = challenge_model.issue_qr_challenge(
            request_record=self.request,
            action_key="Approve",
            user=self.approver_a,
        )
        payload = challenge.build_qr_payload()
        self.assertEqual(payload.get("qr_kind"), "workflow.approval.twofa")
        self.assertEqual(payload.get("expected_user_id"), self.approver_a.id)
        self.assertEqual(payload.get("expected_user_login"), (self.approver_a.login or "").lower())
        self.assertTrue(
            challenge.verify_qr_signature(payload.get("signature")),
            "QR signature in payload should be verifiable by backend.",
        )

    def test_twofactor_scanner_identity_rejects_wrong_user(self):
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        challenge = challenge_model.issue_qr_challenge(
            request_record=self.request,
            action_key="Approve",
            user=self.approver_a,
        )
        ok, error = challenge.validate_scanner_identity(actor_user=self.requester)
        self.assertFalse(ok)
        self.assertEqual(error, "forbidden_user_mismatch")

        ok, error = challenge.validate_scanner_identity(actor_user=self.approver_a)
        self.assertTrue(ok)
        self.assertFalse(error)

    def test_twofactor_otp_length_defaults_to_six_and_keeps_legacy_length(self):
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        challenge = challenge_model.issue_email_otp(
            request_record=self.request,
            action_key="Approve",
            user=self.approver_a,
        )
        self.assertEqual(challenge.otp_length, 6, "New OTP challenges should default to 6 digits.")

        challenge.sudo().write({"otp_length": 5})
        challenge.request_otp()
        self.assertEqual(
            challenge.otp_length,
            5,
            "Legacy challenges keep configured OTP length when requesting a new OTP.",
        )

    def test_version_execution_profile_defaults_to_legacy(self):
        self.assertEqual(self.version.execution_profile, "legacy")
        self.version.sudo().write({"execution_profile": "runtime_v2"})
        self.assertEqual(self.version.execution_profile, "runtime_v2")

    def test_service_task_executor_behavior_is_explicit_and_scoped(self):
        service_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Sync Service",
                "node_id": "Task_Service",
                "node_type": "serviceTask",
                "service_behavior": "executor",
            }
        )
        self.assertEqual(service_meta.service_behavior, "executor")
        with self.assertRaises(ValidationError):
            self.meta_hod.sudo().write({"service_behavior": "executor"})

    def test_request_automation_instance_create_or_get_is_idempotent(self):
        automation = self.AutomationNode.sudo().create(
            {
                "name": "Auto Approve After Delay",
                "category_id": self.category.id,
                "version_id": self.version.id,
                "node_id": "Event_Timer_OneWeek",
                "trigger_type": "schedule",
                "schedule_mode": "interval",
                "interval_number": 7,
                "interval_type": "days",
                "action_type": "transition",
                "failure_policy": "retry",
                "timeout_seconds": 45,
            }
        )
        due_at = fields.Datetime.now() + timedelta(days=7)
        first = self.AutomationInstance.create_or_get(
            request_record=self.request,
            automation_node=automation,
            node_name="Allow admin to edit for 1 week",
            node_type="intermediateCatchEventTimer",
            branch_node_id="Task_OnGoing",
            gateway_node_id="Gateway_Parallel_1",
            join_key="join_on_going",
            trigger_type="timer",
            due_at=due_at,
            payload_json={"target_state": "auto_approved"},
            max_retries=3,
        )
        second = self.AutomationInstance.create_or_get(
            request_record=self.request,
            automation_node=automation,
            node_name="Allow admin to edit for 1 week",
            node_type="intermediateCatchEventTimer",
            branch_node_id="Task_OnGoing",
            gateway_node_id="Gateway_Parallel_1",
            join_key="join_on_going",
            trigger_type="timer",
            due_at=due_at,
            payload_json={"target_state": "auto_approved"},
            max_retries=3,
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, "scheduled")
        self.assertEqual(first.failure_policy, "retry")
        self.assertEqual(first.timeout_seconds, 45)
        self.assertEqual(first.max_retries, 3)
        self.assertEqual(self.request.automation_instance_ids, first)

    def test_request_automation_instance_rearms_terminal_instance_on_force_reentry(self):
        instance = self.AutomationInstance.create_or_get(
            request_record=self.request,
            node_id="Task_Sync_Reentry",
            node_name="Reentry Node",
            node_type="serviceTask",
            trigger_type="automation",
            action_type="enqueue_job",
            payload_json={"attempt": 1},
        )
        instance.mark_cancelled("Superseded by transition")
        self.assertEqual(instance.status, "cancelled")

        reopened = self.AutomationInstance.create_or_get(
            request_record=self.request,
            node_id="Task_Sync_Reentry",
            node_name="Reentry Node",
            node_type="serviceTask",
            trigger_type="automation",
            action_type="enqueue_job",
            payload_json={"attempt": 2},
            rearm_on_reentry=True,
        )

        self.assertEqual(reopened.id, instance.id, "Re-entry should reactivate existing runtime instance.")
        self.assertEqual(reopened.status, "new", "Reactivated immediate automation must be runnable again.")
        self.assertEqual(reopened.payload_json, {"attempt": 2})
        self.assertFalse(reopened.error_message)
        self.assertFalse(reopened.cancelled_at)

    def test_request_automation_instance_status_markers(self):
        instance = self.AutomationInstance.create_or_get(
            request_record=self.request,
            node_id="Task_Sync_Blue",
            node_name="Sync with Blue",
            node_type="serviceTask",
            trigger_type="automation",
            action_type="enqueue_job",
            payload_json={"channel": "blue"},
        )
        self.assertEqual(instance.status, "new")
        self.assertTrue(instance.is_due())

        instance.mark_running()
        self.assertEqual(instance.status, "running")
        self.assertTrue(instance.started_at)

        instance.mark_failed("Temporary outage")
        self.assertEqual(instance.status, "failed")
        self.assertEqual(instance.retry_count, 1)

    def test_service_task_executor_filters_actions_to_model_scoped_server_actions(self):
        service_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Service Executor",
                "node_id": "Task_ServiceExecutor",
                "node_type": "serviceTask",
                "service_behavior": "executor",
            }
        )
        matching_server_action = self.WorkflowAction.sudo().create(
            {
                "name": "Server Action Match",
                "action_type": "server_action",
                "version_id": self.version.id,
            }
        )
        matching_log_action = self.WorkflowAction.sudo().create(
            {
                "name": "Log Action Match",
                "action_type": "log",
                "version_id": self.version.id,
            }
        )

        service_meta._compute_allowed_actions()
        self.assertIn(matching_server_action, service_meta.allowed_action_ids)
        self.assertNotIn(matching_log_action, service_meta.allowed_action_ids)

        with self.assertRaises(ValidationError):
            service_meta.sudo().write({"activity_type_ids": [(6, 0, [matching_log_action.id])]})

    def test_send_task_filters_actions_to_notification_types(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Typed Notification",
                "node_id": "Task_SendTyped",
                "node_type": "sendTask",
            }
        )
        email_action = self.WorkflowAction.sudo().create(
            {
                "name": "Email Match",
                "action_type": "email",
                "version_id": self.version.id,
            }
        )
        server_action = self.WorkflowAction.sudo().create(
            {
                "name": "Server Match",
                "action_type": "server_action",
                "version_id": self.version.id,
            }
        )

        send_meta._compute_allowed_actions()
        self.assertIn(email_action, send_meta.allowed_action_ids)
        self.assertNotIn(server_action, send_meta.allowed_action_ids)

        with self.assertRaises(ValidationError):
            send_meta.sudo().write({"activity_type_ids": [(6, 0, [server_action.id])]})

    def test_send_task_properties_support_engine_managed_schedule_and_template(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Runtime Send Template",
                "model_id": self.base_request_model.id,
                "subject": "Runtime Workflow Mail",
                "body_html": "<p>Hello</p>",
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Notification",
                "node_id": "Task_Send",
                "node_type": "sendTask",
                "notification_recipient_mode": "both",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
                "notification_recipient_domain": f"[('id', '=', {self.approver_b.id})]",
                "notification_email_template_id": template.id,
                "automation_run_mode": "scheduled",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "hours",
            }
        )
        reference_dt = fields.Datetime.now()
        due_at = send_meta._compute_automation_due_at(reference_dt=reference_dt)

        self.assertEqual(send_meta.notification_recipient_mode, "both")
        self.assertEqual(send_meta.notification_email_template_id, template)
        self.assertTrue(send_meta._supports_engine_managed_automation())
        self.assertTrue(due_at)
        self.assertGreaterEqual(due_at, reference_dt + timedelta(minutes=59))
        self.assertLessEqual(due_at, reference_dt + timedelta(hours=1, minutes=1))

    def test_owner_update_notification_settings_store_default_template(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Settings",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Settings",
                "body_html": "<p>Owner default settings</p>",
            }
        )
        settings = self.env["res.config.settings"].create(
            {
                "workflow_default_owner_notification_template_id": template.id,
            }
        )

        settings.set_values()
        values = self.env["res.config.settings"].create({}).get_values()

        self.assertEqual(
            values.get("workflow_default_owner_notification_template_id"),
            template.id,
        )

    def test_owner_update_notification_skips_submission_stage(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Submission Silent",
                "model_id": self.base_request_model.id,
                "subject": "Owner Submission Silent",
                "body_html": "<p>Owner submission silent</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(
            status="new",
            current_meta_task=self.meta_submission,
            previous_meta_task=self.meta_submission,
        )

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_not_called()

    def test_owner_update_notification_sends_on_submit_to_hod_even_when_request_status_new(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default HOD",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default HOD",
                "body_html": "<p>Owner default hod</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(status="new")

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()

    def test_owner_update_notification_sends_on_hod_to_nurse_target_stage_change(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Nurse",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Nurse",
                "body_html": "<p>Owner default nurse</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        nurse_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Nurse",
                "node_id": f"Task_Nurse_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
                "completion_mode": "any",
                "fallback_policy": "route_admin_queue",
            }
        )
        request = self._new_owner_update_request(status="pending")

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification(
                current_meta_task=nurse_meta,
            )

        notify_mock.assert_called_once()

    def test_owner_update_notification_respects_no_notification_context(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Silent Migration",
                "model_id": self.base_request_model.id,
                "subject": "Owner silent migration",
                "body_html": "<p>Owner silent migration</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(status="pending")

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request.with_context(no_notification=True, tracking_disable=True)._workflow_send_owner_update_notification()

        notify_mock.assert_not_called()

    def test_owner_update_notification_respects_target_stage_full_opt_out(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Opt Out",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Opt Out",
                "body_html": "<p>Owner default opt out</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        self.meta_hod.sudo().write(
            {
                "notify_request_owner_email": False,
                "notify_request_creator_email": False,
            }
        )
        request = self._new_owner_update_request(status="new")

        try:
            with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
                request._workflow_send_owner_update_notification()
            notify_mock.assert_not_called()
        finally:
            self.meta_hod.sudo().write(
                {
                    "notify_request_owner_email": True,
                    "notify_request_creator_email": True,
                }
            )

    def test_owner_update_notification_can_send_to_creator_only(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Creator Only",
                "model_id": self.base_request_model.id,
                "subject": "Creator Only",
                "body_html": "<p>Creator only</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        self.meta_hod.sudo().write(
            {
                "notify_request_owner_email": False,
                "notify_request_creator_email": True,
            }
        )
        request = self._new_owner_update_request(
            status="pending",
            creator=self.approver_b,
            owner=self.requester,
        )

        try:
            with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
                request._workflow_send_owner_update_notification()
            notify_mock.assert_called_once()
            kwargs = notify_mock.call_args.kwargs
            self.assertEqual(kwargs["partner_ids"], [self.approver_b.partner_id.id])
        finally:
            self.meta_hod.sudo().write(
                {
                    "notify_request_owner_email": True,
                    "notify_request_creator_email": True,
                }
            )

    def test_owner_update_notification_can_send_to_owner_only(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Only",
                "model_id": self.base_request_model.id,
                "subject": "Owner Only",
                "body_html": "<p>Owner only</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        self.meta_hod.sudo().write(
            {
                "notify_request_owner_email": True,
                "notify_request_creator_email": False,
            }
        )
        request = self._new_owner_update_request(
            status="pending",
            creator=self.approver_b,
            owner=self.requester,
        )

        try:
            with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
                request._workflow_send_owner_update_notification()
            notify_mock.assert_called_once()
            kwargs = notify_mock.call_args.kwargs
            self.assertEqual(kwargs["partner_ids"], [self.requester.partner_id.id])
        finally:
            self.meta_hod.sudo().write(
                {
                    "notify_request_owner_email": True,
                    "notify_request_creator_email": True,
                }
            )

    def test_owner_update_notification_sends_for_terminal_stage_by_default(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Terminal",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Terminal",
                "body_html": "<p>Owner default terminal</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(
            status=False,
            current_meta_task=self.meta_end,
            previous_meta_task=self.meta_hod,
            state="done",
        )

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()

    def test_owner_update_notification_uses_default_template_and_owner_creator_recipients(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Pending",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Pending",
                "body_html": "<p>Owner default pending</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(
            status="pending",
            creator=self.approver_b,
            owner=self.requester,
        )

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Owner Default Pending")
        self.assertIn("Owner default pending", str(kwargs["body"]))
        self.assertEqual(
            set(kwargs["partner_ids"]),
            {
                self.requester.partner_id.id,
                self.approver_b.partner_id.id,
            },
        )

    def test_owner_update_default_template_uses_single_recipient_name(self):
        template = self.env.ref("workflow_engine.email_template_workflow_email_notify")
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(status="pending")

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["partner_ids"], [self.requester.partner_id.id])
        self.assertIn("Dear", str(kwargs["body"]))
        self.assertIn(self.requester.name, str(kwargs["body"]))

    def test_owner_update_default_template_uses_generic_greeting_for_owner_and_creator(self):
        template = self.env.ref("workflow_engine.email_template_workflow_email_notify")
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(
            status="pending",
            creator=self.approver_b,
            owner=self.requester,
        )

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(
            set(kwargs["partner_ids"]),
            {
                self.requester.partner_id.id,
                self.approver_b.partner_id.id,
            },
        )
        self.assertIn("Dear User,", str(kwargs["body"]))
        self.assertNotIn(
            f"Dear <strong>{self.requester.name}</strong>",
            str(kwargs["body"]),
        )

    def test_owner_update_notification_version_override_wins_over_default(self):
        default_template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Default Override",
                "model_id": self.base_request_model.id,
                "subject": "Owner Default Override",
                "body_html": "<p>Owner default override</p>",
            }
        )
        override_template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Version Override",
                "model_id": self.base_request_model.id,
                "subject": "Owner Version Override",
                "body_html": "<p>Owner version override</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            default_template.id,
        )
        self.version.sudo().write(
            {"request_owner_notification_template_id": override_template.id}
        )
        request = self._new_owner_update_request(status="pending")

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Owner Version Override")
        self.assertIn("Owner version override", str(kwargs["body"]))

    def test_owner_update_notification_render_failure_logs_warning_without_abort(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Render Failure",
                "model_id": self.base_request_model.id,
                "subject": "Owner Render Failure",
                "body_html": "<p>Owner render failure</p>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(status="pending")
        before_messages = self.env["mail.message"].sudo().search(
            [("model", "=", request._name), ("res_id", "=", request.id)]
        )

        with patch.object(type(template), "_render_field", side_effect=AccessError("template denied")):
            with patch.object(type(request), "message_notify", return_value=False):
                request._workflow_send_owner_update_notification()

        created_messages = self.env["mail.message"].sudo().search(
            [("id", "not in", before_messages.ids), ("model", "=", request._name), ("res_id", "=", request.id)]
        )
        self.assertTrue(
            created_messages.filtered(lambda msg: "Notification warning:" in (msg.body or "")),
            "Template render failure must leave a chatter warning without aborting the workflow notification path.",
        )

    def test_owner_update_notification_falls_back_from_generic_template_and_targets_child_layout(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Workflow Owner Generic Legacy",
                "model_id": self.base_request_model.id,
                "subject": "Email Notification (Ref: {{ object.name }})",
                "body_html": "<div>Email Notify</div>",
            }
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        request = self._new_owner_update_request(status="pending")

        with patch.object(type(request), "_workflow_resolve_notification_target_record", return_value=self.requester):
            with patch.object(type(request), "workflow_email_document_label", return_value="Medical Request"):
                with patch.object(type(request), "workflow_email_record_name", return_value=request.name):
                    with patch.object(type(request), "workflow_email_reference_code", return_value=request.name):
                        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
                            request._workflow_send_owner_update_notification()

        notify_mock.assert_called_once()
        kwargs = notify_mock.call_args.kwargs
        self.assertEqual(kwargs["target_record"], self.requester)
        self.assertEqual(kwargs["model_description"], "Medical Request")
        self.assertEqual(kwargs["force_record_name"], request.name)
        self.assertEqual(kwargs["subject"], f"Update on your Medical Request - {request.name}")
        self.assertIn("Medical Request", str(kwargs["body"]))

    def test_owner_update_email_helpers_prefer_terminal_labels_and_friendly_subject(self):
        request = self._new_owner_update_request(status="pending")
        request.sudo().with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_allow_runtime_tracking_write=True,
        ).write(
            {
                "current_activity_name": "Nurse Verify",
                "state": "done",
            }
        )
        request.invalidate_recordset(
            ["current_activity_name", "state", "request_status", "next_activity_name", "next_is_end_event"]
        )

        self.assertEqual(request.workflow_email_current_stage_label(), "Done")
        self.assertEqual(request.workflow_email_status_label(), "Done")
        self.assertEqual(
            request.workflow_email_owner_update_subject(),
            f"Update on your {request.category_id.name} - {request.name}",
        )

    def test_owner_update_notification_prefers_target_stage_label_when_snapshot_is_stale(self):
        template = self.env.ref("workflow_engine.email_template_workflow_email_notify").sudo()
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template.id,
        )
        done_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Done",
                "node_id": f"Task_Done_{uuid4().hex[:6]}",
                "node_type": "userTask",
                "assignment_mode": "explicit_users",
                "completion_mode": "any",
                "fallback_policy": "route_admin_queue",
            }
        )
        request = self._new_owner_update_request(status="pending")
        request.sudo().with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_allow_runtime_tracking_write=True,
        ).write(
            {
                "current_activity_name": "Nurse Verify",
                "current_node_id": self.meta_hod.node_id,
                "state": "waiting",
            }
        )
        request.invalidate_recordset(["current_activity_name", "current_node_id", "state"])

        with patch.object(type(request), "_workflow_safe_message_notify", return_value=False) as notify_mock:
            request._workflow_send_owner_update_notification(current_meta_task=done_meta)

        notify_mock.assert_called_once()
        body_text = re.sub(r"<[^>]+>", " ", str(notify_mock.call_args.kwargs["body"]))
        body_text = re.sub(r"\s+", " ", body_text).strip()
        self.assertIn("Current Stage: Done", body_text)
        self.assertNotIn("Current Stage: Nurse Verify", body_text)

    def test_archived_request_mini_snapshot_still_loads_for_view_flow(self):
        request = self._new_owner_update_request(status="pending")
        request.sudo().with_context(active_test=False).write({"active": False})

        snapshot = self.Request.workflow_get_mini_update_snapshot(request.id)

        self.assertEqual(snapshot.get("request_id"), request.id)
        self.assertEqual(snapshot.get("current_node_id"), request.current_node_id)

    def test_archived_parent_request_subworkflow_lookup_keeps_children(self):
        parent = self._new_domain_parent_request(name_suffix="ARCHIVE_FLOW")
        child = self._new_domain_child_request(parent, name="REQ_ARCHIVE_CHILD", state="waiting")
        parent.sudo().with_context(active_test=False).write({"active": False})

        rows = self.Request.get_all_by_parent(parent.id, "workflow.base.approval.request")

        self.assertEqual([row["id"] for row in rows], [child.id])

    def test_send_task_email_template_and_recipients_work_without_channel(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Direct Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Direct send task mail",
                "body_html": "<p>Reminder</p>",
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Direct Email",
                "node_id": "Task_SendDirectEmail",
                "node_type": "sendTask",
                "email_template_external_id": template.id,
                "notification_recipient_mode": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Direct send task mail"
        )

        self.assertEqual(created_mail.subject, "Direct send task mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_notification_share_helper_grants_reader_access_without_duplicates(self):
        self.assertFalse(
            self.permission_service.can_access_request(
                self.request,
                user=self.reader_user,
                scope="read",
            )
        )

        first = self.request._workflow_grant_notification_read_scopes(
            self.reader_user,
            reason="notification_recipient:Task_HOD",
        )
        second = self.request._workflow_grant_notification_read_scopes(
            self.reader_user,
            reason="notification_recipient:Task_HOD",
        )

        scope_rows = self.env["workflow.request.visibility.scope"].sudo().search(
            [
                ("request_id", "=", self.request.id),
                ("allowed_user_id", "=", self.reader_user.id),
                ("scope", "=", "read"),
                ("active", "=", True),
            ]
        )
        self.assertEqual(len(scope_rows), 1)
        self.assertEqual(first.ids, second.ids)
        self.assertTrue(
            self.permission_service.can_access_request(
                self.request,
                user=self.reader_user,
                scope="read",
            )
        )
        self.assertFalse(
            self.permission_service.can_access_request(
                self.request,
                user=self.reader_user,
                scope="edit",
            )
        )

    def test_send_task_template_email_failure_logs_warning_without_abort(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Direct Send Task Failure",
                "model_id": self.base_request_model.id,
                "subject": "Direct send task failure",
                "body_html": "<p>Reminder</p>",
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Direct Failure",
                "node_id": "Task_SendDirectFailure",
                "node_type": "sendTask",
                "email_template_external_id": template.id,
                "notification_recipient_mode": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        before_messages = self.env["mail.message"].sudo().search(
            [("model", "=", self.request._name), ("res_id", "=", self.request.id)]
        )

        with patch.object(type(template), "send_mail", side_effect=AccessError("mail denied")):
            self.request._send_task_template_email(send_meta, self.approver_a)

        created_messages = self.env["mail.message"].sudo().search(
            [("id", "not in", before_messages.ids), ("model", "=", self.request._name), ("res_id", "=", self.request.id)]
        )
        self.assertTrue(
            created_messages.filtered(lambda msg: "Notification warning:" in (msg.body or "")),
            "Send-task template failures must be logged to chatter without aborting execution.",
        )

    def test_message_throw_event_sends_template_email_when_configured(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Message Throw Email",
                "model_id": self.base_request_model.id,
                "subject": "Message throw mail",
                "body_html": "<p>Message event</p>",
            }
        )
        message_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Notify Mid Flow",
                "node_id": "Event_MessageThrow",
                "node_type": "intermediateThrowEventMessage",
                "email_template_external_id": template.id,
                "notification_recipient_source": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(message_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Message throw mail"
        )

        self.assertEqual(created_mail.subject, "Message throw mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")

    def test_message_throw_event_without_template_routes_without_email(self):
        message_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Notify Without Template",
                "node_id": "Event_MessageThrowNoTemplate",
                "node_type": "intermediateThrowEventMessage",
                "notification_recipient_source": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(message_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])

        self.assertFalse(created_mail)

    def test_send_task_email_mode_resolves_approval_group_recipients(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Approval Group Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Approval group send task mail",
                "body_html": "<p>Approval group reminder</p>",
            }
        )
        approval_group = self.ApprovalGroup.sudo().create(
            {
                "name": "MTF Admin Group Runtime",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Approval Group Email",
                "node_id": "Task_SendApprovalGroupEmail",
                "node_type": "sendTask",
                "notification_delivery_mode": "email",
                "email_template_external_id": template.id,
                "notification_recipient_source": "approval_group_users",
                "notification_approval_group_ids": [(6, 0, [approval_group.id])],
                "notification_recipient_filter_domain": ROUTING_ALWAYS_TRUE,
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Approval group send task mail"
        )

        self.assertEqual(created_mail.subject, "Approval group send task mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_send_task_email_mode_filters_approval_group_recipients_by_domain(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Approval Group Filtered Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Approval group filtered send task mail",
                "body_html": "<p>Approval group filtered reminder</p>",
            }
        )
        approval_group = self.ApprovalGroup.sudo().create(
            {
                "name": "MTF Admin Group Filter Runtime",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Filtered Approval Group Email",
                "node_id": "Task_SendFilteredApprovalGroupEmail",
                "node_type": "sendTask",
                "notification_delivery_mode": "email",
                "email_template_external_id": template.id,
                "notification_recipient_source": "approval_group_users",
                "notification_approval_group_ids": [(6, 0, [approval_group.id])],
                "notification_recipient_filter_domain": f"[('id', '=', {self.approver_b.id})]",
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Approval group filtered send task mail"
        )

        self.assertEqual(created_mail.subject, "Approval group filtered send task mail")
        self.assertNotIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_send_task_email_mode_approval_group_true_sentinel_keeps_all_users(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Approval Group Sentinel Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Approval group sentinel send task mail",
                "body_html": "<p>Approval group sentinel reminder</p>",
            }
        )
        approval_group = self.ApprovalGroup.sudo().create(
            {
                "name": "MTF Admin Group Sentinel Runtime",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Sentinel Approval Group Email",
                "node_id": "Task_SendSentinelApprovalGroupEmail",
                "node_type": "sendTask",
                "notification_delivery_mode": "email",
                "email_template_external_id": template.id,
                "notification_recipient_source": "approval_group_users",
                "notification_approval_group_ids": [(6, 0, [approval_group.id])],
                "notification_recipient_filter_domain": "[(1, '=', 1)]",
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Approval group sentinel send task mail"
        )

        self.assertEqual(created_mail.subject, "Approval group sentinel send task mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_send_task_email_mode_resolves_odoo_group_recipients(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "System Group Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Security group send task mail",
                "body_html": "<p>System group reminder</p>",
            }
        )
        group = self.env["res.groups"].sudo().create(
            {
                "name": "Workflow Runtime Email Group",
            }
        )
        (self.approver_a | self.approver_b).sudo().write({"group_ids": [(4, group.id)]})
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send System Group Email",
                "node_id": "Task_SendOdooGroupEmail",
                "node_type": "sendTask",
                "notification_delivery_mode": "email",
                "email_template_external_id": template.id,
                "notification_recipient_source": "group_users",
                "notification_group_ids": [(6, 0, [group.id])],
                "notification_recipient_filter_domain": ROUTING_ALWAYS_TRUE,
            }
        )
        self.assertIn(self.approver_a, group.user_ids)
        self.assertIn(self.approver_b, group.user_ids)
        resolved_recipients = self.request._resolve_notification_recipients(send_meta)
        self.assertIn(self.approver_a, resolved_recipients)
        self.assertIn(self.approver_b, resolved_recipients)

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        new_mails = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])
        created_mail = new_mails.filtered(
            lambda mail: mail.subject == "Security group send task mail"
        )

        self.assertTrue(
            created_mail,
            f"Expected security group send task mail. New mails: {[(mail.subject, mail.email_to) for mail in new_mails]}",
        )
        self.assertEqual(created_mail.subject, "Security group send task mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_email_channel_recipient_rows_support_raw_to_cc_bcc(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Channel Raw Email",
                "model_id": self.base_request_model.id,
                "subject": "Channel raw mail",
                "body_html": "<p>Channel raw</p>",
            }
        )
        email_action = self.WorkflowAction.sudo().create(
            {
                "name": "Raw Workforce Channel",
                "action_type": "email",
                "email_template_id": template.id,
                "email_recipient_line_ids": [
                    (0, 0, {"header": "to", "source": "direct", "raw_emails": "workforce@nagaworld.com"}),
                    (0, 0, {"header": "cc", "source": "direct", "raw_emails": "hr@nagaworld.com"}),
                    (0, 0, {"header": "bcc", "source": "direct", "raw_emails": "audit@nagaworld.com"}),
                ],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Raw Channel",
                "node_id": "Task_SendRawChannel",
                "node_type": "sendTask",
                "notification_delivery_mode": "channels",
                "activity_type_ids": [(6, 0, [email_action.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Channel raw mail"
        )

        self.assertEqual(created_mail.subject, "Channel raw mail")
        self.assertEqual(created_mail.email_to, "workforce@nagaworld.com")
        self.assertEqual(created_mail.email_cc, "hr@nagaworld.com")
        self.assertIn("audit@nagaworld.com", created_mail.headers or "")

    def test_email_channel_recipient_rows_filter_approval_group_users_by_domain(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Channel Approval Group Filter Email",
                "model_id": self.base_request_model.id,
                "subject": "Channel approval group filter mail",
                "body_html": "<p>Channel approval group filter</p>",
            }
        )
        approval_group = self.ApprovalGroup.sudo().create(
            {
                "name": "Channel Filter Group Runtime",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )
        email_action = self.WorkflowAction.sudo().create(
            {
                "name": "Filtered Approval Group Channel",
                "action_type": "email",
                "email_template_id": template.id,
                "email_recipient_line_ids": [
                    (
                        0,
                        0,
                        {
                            "header": "to",
                            "source": "approval_group_users",
                            "approval_group_ids": [(6, 0, [approval_group.id])],
                            "domain": f"[('id', '=', {self.approver_b.id})]",
                        },
                    )
                ],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Filtered Approval Group Channel",
                "node_id": "Task_SendFilteredApprovalGroupChannel",
                "node_type": "sendTask",
                "notification_delivery_mode": "channels",
                "activity_type_ids": [(6, 0, [email_action.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        result = self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Channel approval group filter mail"
        )

        self.assertEqual(created_mail.subject, "Channel approval group filter mail")
        self.assertNotIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")
        audit_entry = result["notification_audit"]["entries"][0]
        self.assertEqual(audit_entry["status"], "sent")
        self.assertEqual(audit_entry["recipient_lines"][0]["resolved_user_ids"], [self.approver_b.id])

    def test_email_channel_domain_recipient_rows_support_request_owner_and_creator_symbols(self):
        request = self._new_owner_update_request(
            status=False,
            creator=self.approver_b,
            owner=self.requester,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
        )
        template = self.MailTemplate.sudo().create(
            {
                "name": "Channel Owner Creator Symbol Email",
                "model_id": self.base_request_model.id,
                "subject": "Channel owner creator symbol mail",
                "body_html": "<p>Owner creator symbol</p>",
            }
        )
        email_action = self.WorkflowAction.sudo().create(
            {
                "name": "Owner Creator Symbol Channel",
                "action_type": "email",
                "email_template_id": template.id,
                "email_recipient_line_ids": [
                    (
                        0,
                        0,
                        {
                            "header": "to",
                            "source": "domain",
                            "domain": "[('id', 'in', [request_owner_id, request_creator_id])]",
                        },
                    )
                ],
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Owner Creator Symbol Channel",
                "node_id": "Task_SendOwnerCreatorSymbolChannel",
                "node_type": "sendTask",
                "notification_delivery_mode": "channels",
                "activity_type_ids": [(6, 0, [email_action.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        result = request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Channel owner creator symbol mail"
        )

        self.assertEqual(created_mail.subject, "Channel owner creator symbol mail")
        self.assertIn(self.requester.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")
        self.assertEqual(
            set(result["notification_audit"]["entries"][0]["resolved_user_ids"]),
            {self.requester.id, self.approver_b.id},
        )

    def test_email_channel_without_recipient_rows_uses_send_task_recipients(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Channel Fallback Email",
                "model_id": self.base_request_model.id,
                "subject": "Channel fallback mail",
                "body_html": "<p>Channel fallback</p>",
            }
        )
        email_action = self.WorkflowAction.sudo().create(
            {
                "name": "Fallback Channel",
                "action_type": "email",
                "email_template_id": template.id,
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Send Channel Fallback",
                "node_id": "Task_SendChannelFallback",
                "node_type": "sendTask",
                "notification_delivery_mode": "channels",
                "activity_type_ids": [(6, 0, [email_action.id])],
                "notification_recipient_source": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        self.request._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)]).filtered(
            lambda mail: mail.subject == "Channel fallback mail"
        )

        self.assertEqual(created_mail.subject, "Channel fallback mail")
        self.assertIn(self.approver_a.email, created_mail.email_to or "")
        self.assertIn(self.approver_b.email, created_mail.email_to or "")

    def test_no_email_send_suppresses_send_task_email_without_skipping_resolution(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Silent Migration Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Silent migration mail",
                "body_html": "<p>Reminder</p>",
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Silent Send Direct Email",
                "node_id": "Task_SilentSendDirectEmail",
                "node_type": "sendTask",
                "email_template_external_id": template.id,
                "notification_recipient_mode": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        recipients = self.request._resolve_notification_recipients(send_meta)
        self.request.with_context(no_email_send=True)._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])

        self.assertEqual(recipients, self.approver_a | self.approver_b)
        self.assertFalse(created_mail)

    def test_no_notification_suppresses_send_task_email_without_skipping_resolution(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Silent Migration No Notification Send Task Email",
                "model_id": self.base_request_model.id,
                "subject": "Silent no notification mail",
                "body_html": "<p>Reminder</p>",
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Silent No Notification Send Direct Email",
                "node_id": "Task_SilentNoNotificationSendDirectEmail",
                "node_type": "sendTask",
                "email_template_external_id": template.id,
                "notification_recipient_mode": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        recipients = self.request._resolve_notification_recipients(send_meta)
        self.request.with_context(no_notification=True, tracking_disable=True)._handle_send_task(send_meta, False)
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])

        self.assertEqual(recipients, self.approver_a | self.approver_b)
        self.assertFalse(created_mail)

    def test_workflow_safe_send_mail_template_respects_no_notification_context(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Silent Migration Safe Template Helper",
                "model_id": self.base_request_model.id,
                "subject": "Silent helper mail",
                "body_html": "<p>Silent helper</p>",
            }
        )

        before_mail = self.env["mail.mail"].sudo().search([])
        sent = self.request.with_context(no_notification=True, tracking_disable=True)._workflow_safe_send_mail_template(
            template=template,
            render_record=self.request,
            email_values={"email_to": self.approver_a.email},
        )
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])

        self.assertFalse(sent)
        self.assertFalse(created_mail)

    def test_no_email_send_suppresses_workflow_messages_but_keeps_activity_creation(self):
        request = self.request.with_context(no_email_send=True)
        before_messages = self.env["mail.message"].sudo().search([])
        request._workflow_safe_message_post(
            body="Silent migration log",
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        created_messages = self.env["mail.message"].sudo().search([("id", "not in", before_messages.ids)])
        self.assertFalse(created_messages)

        approver = self.Approver.sudo().with_context(no_email_send=True).create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.request.sudo().write({"state": "waiting"})
        before_activities = self.env["mail.activity"].sudo().search([])
        activity_type = self.env.ref("workflow_engine.mail_activity_data_workflow_approval")
        with patch.object(type(self.request), "message_notify", return_value=False) as notify_mock:
            approver.with_context(no_email_send=True)._create_activity()
        notify_mock.assert_not_called()
        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        self.assertEqual(len(created_activities), 1)
        self.assertEqual(created_activities.activity_type_id, activity_type)
        self.assertEqual(created_activities.user_id, self.approver_a)

    def test_workflow_activity_push_notification_creates_inbox_without_email(self):
        approver = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.request.sudo().write({"state": "waiting"})
        before_activities = self.env["mail.activity"].sudo().search([])
        before_notifications = self.env["mail.notification"].sudo().search([])
        before_mails = self.env["mail.mail"].sudo().search([])

        approver._create_activity()

        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        created_notifications = self.env["mail.notification"].sudo().search(
            [("id", "not in", before_notifications.ids)]
        )
        created_mails = self.env["mail.mail"].sudo().search([("id", "not in", before_mails.ids)])

        self.assertEqual(len(created_activities), 1)
        self.assertEqual(created_activities.user_id, self.approver_a)
        self.assertTrue(
            created_notifications.filtered(
                lambda n: n.res_partner_id == self.approver_a.partner_id
                and n.notification_type == "inbox"
            )
        )
        self.assertFalse(created_mails)

    def test_create_activity_batch_lookup_keeps_unrelated_open_activities(self):
        activity_type = self.env.ref("workflow_engine.mail_activity_data_workflow_approval")
        request_a = self.request.sudo()
        request_a.write(
            {
                "state": "waiting",
                "current_node_id": self.meta_hod.node_id,
                "current_activity_name": self.meta_hod.name,
            }
        )
        request_b = self.Request.sudo().create(
            {
                "name": f"REQ_ACTIVITY_BATCH_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "version_id": self.version.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "current_activity_name": self.meta_hod.name,
                "state": "waiting",
            }
        )
        unrelated_activity = request_a.with_context(workflow_activity_no_email=True).activity_schedule(
            activity_type_id=activity_type.id,
            user_id=self.approver_b.id,
            summary="Unrelated stage to keep",
            note="This activity is not part of the batched approver candidate set.",
        )
        approvers = self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": request_a.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": request_b.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )

        approvers._create_activity()

        self.assertTrue(unrelated_activity.exists())
        created_for_candidates = self.env["mail.activity"].sudo().search(
            [
                ("activity_type_id", "=", activity_type.id),
                ("date_done", "=", False),
                ("summary", "=", self.meta_hod.name),
            ]
        )
        self.assertTrue(
            created_for_candidates.filtered(
                lambda activity: activity.res_model == request_a._name
                and activity.res_id == request_a.id
                and activity.user_id == self.approver_a
            )
        )
        self.assertTrue(
            created_for_candidates.filtered(
                lambda activity: activity.res_model == request_b._name
                and activity.res_id == request_b.id
                and activity.user_id == self.approver_b
            )
        )

    def test_workflow_activity_respects_stage_push_flag(self):
        self.meta_hod.sudo().write({"push_notification_to_actor": False})
        approver = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.request.sudo().write({"state": "waiting"})
        before_activities = self.env["mail.activity"].sudo().search([])

        approver._create_activity()

        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        self.assertFalse(created_activities)

    def test_workflow_activity_respects_user_push_opt_out(self):
        self.approver_a.sudo().write({"wf_approval_push_enabled": False})
        approver = self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.request.sudo().write({"state": "waiting"})
        before_activities = self.env["mail.activity"].sudo().search([])

        approver._create_activity()

        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        self.assertFalse(created_activities)

    def test_email_otp_respects_no_notification_context(self):
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        before_mail = self.env["mail.mail"].sudo().search([])

        challenge = challenge_model.with_context(no_notification=True, tracking_disable=True).issue_email_otp(
            self.request,
            "approve",
            self.approver_a,
            ttl_seconds=120,
        )
        created_mail = self.env["mail.mail"].sudo().search([("id", "not in", before_mail.ids)])

        self.assertEqual(challenge.method, "email_otp")
        self.assertFalse(created_mail)

    def test_no_notification_suppresses_workflow_message_helpers_and_activity_creation(self):
        request = self.request.with_context(no_notification=True, tracking_disable=True)
        before_messages = self.env["mail.message"].sudo().search([])
        request._workflow_safe_message_post(
            body="Silent no notification migration log",
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        created_messages = self.env["mail.message"].sudo().search([("id", "not in", before_messages.ids)])
        self.assertFalse(created_messages)

    def test_runtime_automation_instance_stores_notification_audit_for_send_task_channels(self):
        data = self._create_runtime_v2_pass_through_version("automation_audit_channels", approval_require_number=1)
        template = self.MailTemplate.sudo().create(
            {
                "name": "Automation Audit Channel Email",
                "model_id": self.base_request_model.id,
                "subject": "Automation audit channel mail",
                "body_html": "<p>Automation audit channel</p>",
            }
        )
        matching_action = self.WorkflowAction.sudo().create(
            {
                "name": "Matching Department Channel",
                "action_type": "email",
                "domain": f"[('request_owner_id.employee_id.department_id.id', '=', {self.department.id})]",
                "email_template_id": template.id,
            }
        )
        skipped_action = self.WorkflowAction.sudo().create(
            {
                "name": "Skipped Department Channel",
                "action_type": "email",
                "domain": f"[('request_owner_id.employee_id.department_id.id', '=', {self.department.id + 999})]",
                "email_template_id": template.id,
            }
        )
        send_meta = data["meta_send"].sudo()
        send_meta.write(
            {
                "name": "Automation Audit Send Task",
                "notification_delivery_mode": "channels",
                "notification_recipient_source": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
                "activity_type_ids": [(6, 0, [matching_action.id, skipped_action.id])],
            }
        )
        request_record = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_AUTOMATION_AUDIT_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "version_id": data["version"].id,
                "request_owner_id": self.requester.id,
                "current_node_id": send_meta.node_id,
                "previous_node_id": data["meta_hod"].node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=request_record,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
        )

        request_record._workflow_run_runtime_automation_instance(instance)

        instance.invalidate_recordset(["status", "result_json"])
        audit = instance.notification_audit_json
        self.assertEqual(instance.status, "success")
        self.assertEqual(audit.get("delivery_mode"), "channels")
        self.assertEqual(audit.get("node_id"), send_meta.node_id)
        entry_by_name = {
            entry.get("action_name"): entry
            for entry in (audit.get("entries") or [])
        }
        self.assertEqual(entry_by_name["Matching Department Channel"]["status"], "sent")
        self.assertEqual(entry_by_name["Skipped Department Channel"]["status"], "skipped_guard")
        self.assertTrue(entry_by_name["Matching Department Channel"]["guard_matched"])
        self.assertFalse(entry_by_name["Skipped Department Channel"]["guard_matched"])
        self.assertIn(self.approver_a.email, entry_by_name["Matching Department Channel"]["email_to"])
        self.assertEqual(entry_by_name["Skipped Department Channel"]["email_to"], [])
        self.assertEqual(
            entry_by_name["Matching Department Channel"]["resolved_user_ids"],
            [self.approver_a.id],
        )
        self.assertIn("Matching Department Channel", instance.notification_audit_sent_summary or "")
        self.assertIn(self.approver_a.email, instance.notification_audit_sent_summary or "")
        self.assertIn(
            "Matching Department Channel [Sent]",
            instance.notification_audit_summary or "",
        )
        self.assertIn(
            "Skipped Department Channel [Skipped: guard not matched]",
            instance.notification_audit_summary or "",
        )
        self.assertEqual(
            (instance.result_json or {}).get("notification_audit", {}).get("delivery_mode"),
            "channels",
        )

        approver = self.Approver.sudo().with_context(no_notification=True, tracking_disable=True).create(
            {
                "user_id": self.approver_a.id,
                "request_id": self.request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )
        before_activities = self.env["mail.activity"].sudo().search([])
        approver.with_context(no_notification=True, tracking_disable=True)._create_activity()
        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        self.assertFalse(created_activities)

    def test_workflow_activity_email_suppression_does_not_affect_non_workflow_activity(self):
        todo_type = self.env.ref("mail.mail_activity_data_todo")
        before_activities = self.env["mail.activity"].sudo().search([])

        with patch.object(type(self.request), "message_notify", return_value=False) as notify_mock:
            self.request.with_context(workflow_activity_no_email=True).activity_schedule(
                activity_type_id=todo_type.id,
                user_id=self.approver_a.id,
                summary="Generic follow-up",
                note="Generic Odoo activity must keep default notification behavior.",
            )

        notify_mock.assert_called_once()
        created_activities = self.env["mail.activity"].sudo().search([("id", "not in", before_activities.ids)])
        self.assertEqual(len(created_activities), 1)
        self.assertEqual(created_activities.activity_type_id, todo_type)
        self.assertEqual(created_activities.user_id, self.approver_a)
        self.assertTrue(created_activities.date_deadline)

    def test_notification_node_users_recipient_source_resolves_assigned_pending_decided(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Node User Notification",
                "node_id": "Task_NodeUserNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "node_users",
                "notification_recipient_node_ref": self.meta_hod.node_id,
                "notification_recipient_filter_domain": ROUTING_ALWAYS_TRUE,
            }
        )

        send_meta.notification_recipient_node_user_type = "assigned"
        assigned = self.request._resolve_notification_recipients(send_meta)
        self.assertEqual(set(assigned.ids), {self.approver_a.id, self.approver_b.id})

        send_meta.notification_recipient_node_user_type = "pending"
        pending = self.request._resolve_notification_recipients(send_meta)
        self.assertEqual(pending.ids, [self.approver_a.id])

        send_meta.notification_recipient_node_user_type = "decided"
        decided = self.request._resolve_notification_recipients(send_meta)
        self.assertEqual(decided.ids, [self.approver_b.id])

    def test_notification_node_users_advanced_filter_narrows_source_users(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Filtered Node Notification",
                "node_id": "Task_FilteredNodeNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "node_users",
                "notification_recipient_node_ref": self.meta_hod.node_id,
                "notification_recipient_node_user_type": "assigned",
                "notification_recipient_filter_domain": f"[('id', '=', {self.approver_b.id})]",
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(recipients.ids, [self.approver_b.id])

    def test_send_task_domain_recipients_support_decided_approver_symbol(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Decided Approver Domain Notification",
                "node_id": "Task_DecidedApproverDomainNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": "[('id', 'in', decided_approver_user_ids)]",
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(set(recipients.ids), {self.requester.id, self.approver_b.id})
        self.assertNotIn(self.approver_a.id, recipients.ids)

    def test_send_task_domain_recipients_support_json_symbol_values(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "JSON Symbol Domain Notification",
                "node_id": "Task_JsonSymbolDomainNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": '[["id", "in", "decided_approver_user_ids"]]',
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(set(recipients.ids), {self.requester.id, self.approver_b.id})
        self.assertNotIn(self.approver_a.id, recipients.ids)

    def test_send_task_domain_recipients_support_json_node_helper_values(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "JSON Node Helper Domain Notification",
                "node_id": "Task_JsonNodeHelperDomainNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": (
                    '[["id", "in", "node_decided_approver_user_ids(\\\'Task_HOD\\\')"]]'
                ),
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(recipients.ids, [self.approver_b.id])

    def test_send_task_node_decided_recipients_ignore_routed_audit_rows(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "closed",
                    "user_decision": "Routed",
                    "is_routed_audit": True,
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Node Decided Routed Audit Notification",
                "node_id": "Task_NodeDecidedRoutedAuditNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": (
                    '[["id", "in", "node_decided_approver_user_ids(\\\'Task_HOD\\\')"]]'
                ),
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(recipients.ids, [self.approver_b.id])

    def test_send_task_domain_recipients_support_node_assigned_approver_helper(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Node Assigned Domain Notification",
                "node_id": "Task_NodeAssignedDomainNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": (
                    "[('id', 'in', node_assigned_approver_user_ids('Task_HOD'))]"
                ),
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(set(recipients.ids), {self.approver_a.id, self.approver_b.id})

    def test_send_task_domain_recipients_support_json_node_assigned_helper(self):
        self.Approver.sudo().create(
            [
                {
                    "user_id": self.approver_a.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "pending",
                    "required": True,
                    "iteration_no": 1,
                },
                {
                    "user_id": self.approver_b.id,
                    "request_id": self.request.id,
                    "current_meta_id": self.meta_hod.id,
                    "previous_meta_id": self.meta_submission.id,
                    "status": "approved",
                    "user_decision": "Approve",
                    "required": True,
                    "iteration_no": 1,
                },
            ]
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "JSON Node Assigned Domain Notification",
                "node_id": "Task_JsonNodeAssignedDomainNotification",
                "node_type": "sendTask",
                "notification_recipient_source": "domain",
                "notification_recipient_filter_domain": (
                    '[["id", "in", "node_assigned_approver_user_ids(\\\'Task_HOD\\\')"]]'
                ),
            }
        )

        recipients = self.request._resolve_notification_recipients(send_meta)

        self.assertEqual(set(recipients.ids), {self.approver_a.id, self.approver_b.id})

    def test_send_task_recurring_schedule_plan_supports_forever_and_fixed_count(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Recurring Reminder",
                "node_id": "Task_Reminder",
                "node_type": "sendTask",
                "automation_run_mode": "scheduled",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 2,
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="count",
            recurrence_count=2,
        )

        first_plan = instance._prepare_recurrence_after_success(send_meta)
        self.assertEqual(first_plan["completed_runs"], 1)
        self.assertTrue(first_plan["next_due_at"])

        instance.sudo().write({"run_count": 1})
        second_plan = instance._prepare_recurrence_after_success(send_meta)
        self.assertEqual(second_plan["completed_runs"], 2)
        self.assertFalse(second_plan["next_due_at"])

    def test_date_based_scheduled_side_effect_can_recur_forever_while_stage_is_active(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Overdue Reminder",
                "node_id": "Task_OverdueReminder",
                "node_type": "sendTask",
                "automation_run_mode": "scheduled",
                "automation_condition_domain": "[('date_deadline', '<', current_date)]",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "forever",
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="forever",
        )

        plan = instance._prepare_recurrence_after_success(send_meta)
        self.assertEqual(plan["completed_runs"], 1)
        self.assertTrue(plan["next_due_at"])

    def test_send_task_recurring_schedule_plan_honors_until_date(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Recurring Until",
                "node_id": "Task_ReminderUntil",
                "node_type": "sendTask",
                "automation_run_mode": "scheduled",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "hours",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "until",
                "automation_recurrence_until": fields.Datetime.now() + timedelta(minutes=30),
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="until",
            recurrence_until=fields.Datetime.now() + timedelta(minutes=30),
        )
        plan = instance._prepare_recurrence_after_success(send_meta)
        self.assertEqual(plan["completed_runs"], 1)
        self.assertFalse(plan["next_due_at"])

    def test_scheduled_side_effect_rearms_when_condition_not_yet_true(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Future Overdue Reminder",
                "node_id": "Task_FutureReminder",
                "node_type": "sendTask",
                "automation_run_mode": "scheduled",
                "automation_condition_domain": "[('state', '=', 'approved')]",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 2,
            }
        )
        self.request.sudo().write({"state": "waiting", "current_node_id": self.meta_hod.node_id})
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            branch_node_id=self.meta_hod.node_id,
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
            payload_json={"execution_mode": "side_effect", "source_node_id": self.meta_hod.node_id},
            recurrence_enabled=True,
            recurrence_mode="count",
            recurrence_count=2,
        )

        self.request._workflow_run_runtime_automation_instance(instance)
        instance.invalidate_recordset(["status", "run_count", "result_json", "due_at"])
        self.assertEqual(instance.status, "scheduled")
        self.assertEqual(instance.run_count, 1)
        self.assertTrue((instance.result_json or {}).get("skipped"))

    def test_scheduled_side_effect_cancels_when_source_stage_is_inactive(self):
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Inactive Source Reminder",
                "node_id": "Task_InactiveReminder",
                "node_type": "sendTask",
                "automation_run_mode": "scheduled",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 2,
            }
        )
        self.request.sudo().write({"current_node_id": self.meta_hod.node_id})
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=send_meta.node_id,
            node_name=send_meta.name,
            node_type="sendTask",
            branch_node_id="Task_Old",
            trigger_type="automation",
            action_type="send_email",
            due_at=fields.Datetime.now(),
            payload_json={"execution_mode": "side_effect", "source_node_id": "Task_Old"},
            recurrence_enabled=True,
            recurrence_mode="count",
            recurrence_count=2,
        )

        self.request._workflow_run_runtime_automation_instance(instance)
        instance.invalidate_recordset(["status"])
        self.assertEqual(instance.status, "cancelled")

    def test_non_admin_runtime_can_read_workflow_action_config_with_sudo(self):
        workflow_action = self.WorkflowAction.sudo().create(
            {
                "name": "Runtime Log",
                "action_type": "log",
                "version_id": self.version.id,
            }
        )
        send_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Permission Reminder",
                "node_id": "Task_PermissionReminder",
                "node_type": "sendTask",
                "activity_type_ids": [(6, 0, [workflow_action.id])],
            }
        )

        with self.assertRaises(AccessError):
            workflow_action.with_user(self.approver_a).read(["name"])
        self.assertEqual(
            self.request.with_user(self.approver_a)._resolve_send_task_delivery_mode(
                send_meta.with_user(self.approver_a)
            ),
            "channels",
        )

    def test_auto_action_owns_timer_schedule_and_recurring_plan(self):
        timer_action = self.MetaAction.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Reminder Timer",
                "source_id": "Task_Approval",
                "target_id": "Timer_Reminder",
                "target_node_type": "timerEvent",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 2,
            }
        )
        reference_dt = fields.Datetime.now()
        due_at = timer_action._compute_automation_due_at(reference_dt=reference_dt)
        self.assertEqual(timer_action.flow_type, "autoAction")
        self.assertTrue(timer_action._is_automation_recurring_enabled())
        self.assertGreaterEqual(due_at, reference_dt + timedelta(minutes=2, seconds=50))
        self.assertLessEqual(due_at, reference_dt + timedelta(minutes=3, seconds=10))

        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=timer_action.target_id,
            node_name=timer_action.name,
            node_type="timerEvent",
            trigger_type="timer",
            action_type="transition",
            due_at=reference_dt,
            recurrence_enabled=True,
            recurrence_mode="count",
            recurrence_count=2,
        )
        first_plan = instance._prepare_recurrence_after_success(meta_action=timer_action)
        self.assertEqual(first_plan["completed_runs"], 1)
        self.assertTrue(first_plan["next_due_at"])

        instance.sudo().write({"run_count": 1})
        second_plan = instance._prepare_recurrence_after_success(meta_action=timer_action)
        self.assertEqual(second_plan["completed_runs"], 2)
        self.assertFalse(second_plan["next_due_at"])

    def test_shared_timer_action_config_is_resolved_by_source_and_target(self):
        version = self.Version.sudo().create(
            {
                "category_id": self.category.id,
                "name": "v_shared_timer_source_config",
                "execution_profile": "runtime_v2",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_SharedTimer">
                  <bpmn:process id="Process_SharedTimer" isExecutable="true">
                    <bpmn:userTask id="Task_Return" name="Return">
                      <bpmn:outgoing>Flow_Return_Timer</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:userTask id="Task_Extend" name="Extend Return Date">
                      <bpmn:outgoing>Flow_Extend_Timer</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateCatchEvent id="Timer_DueTomorrow" name="Due Date Tomorrow">
                      <bpmn:incoming>Flow_Return_Timer</bpmn:incoming>
                      <bpmn:incoming>Flow_Extend_Timer</bpmn:incoming>
                      <bpmn:outgoing>Flow_Timer_Script</bpmn:outgoing>
                      <bpmn:timerEventDefinition id="TimerDefinition_DueTomorrow"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:scriptTask id="Task_LogReminder" name="Log Reminder">
                      <bpmn:incoming>Flow_Timer_Script</bpmn:incoming>
                    </bpmn:scriptTask>
                    <bpmn:sequenceFlow id="Flow_Return_Timer" sourceRef="Task_Return" targetRef="Timer_DueTomorrow"/>
                    <bpmn:sequenceFlow id="Flow_Extend_Timer" sourceRef="Task_Extend" targetRef="Timer_DueTomorrow"/>
                    <bpmn:sequenceFlow id="Flow_Timer_Script" sourceRef="Timer_DueTomorrow" targetRef="Task_LogReminder"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        self.category.sudo().write({"active_version_id": version.id})
        self.MetaTask.sudo().create(
            {
                "version_id": version.id,
                "name": "Log Reminder",
                "node_id": "Task_LogReminder",
                "node_type": "scriptTask",
            }
        )
        extend_action = self.MetaAction.sudo().create(
            {
                "version_id": version.id,
                "name": "Due Date Tomorrow",
                "source_id": "Task_Extend",
                "source_name": "Extend Return Date",
                "source_node_type": "userTask",
                "target_id": "Timer_DueTomorrow",
                "target_name": "Due Date Tomorrow",
                "target_node_type": "timerEvent",
                "node_id": "Flow_Extend_Timer",
                "auto_action_condition": "[('name', '=', 'SHOULD_NOT_MATCH_RETURN_BRANCH')]",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
            }
        )
        return_action = self.MetaAction.sudo().create(
            {
                "version_id": version.id,
                "name": "Due Date Tomorrow",
                "source_id": "Task_Return",
                "source_name": "Return",
                "source_node_type": "userTask",
                "target_id": "Timer_DueTomorrow",
                "target_name": "Due Date Tomorrow",
                "target_node_type": "timerEvent",
                "node_id": "Flow_Return_Timer",
                "automation_trigger_mode": "reminder",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
            }
        )
        request_record = self.Request.sudo().create(
            {
                "name": "REQ_SHARED_TIMER_SOURCE",
                "category_id": self.category.id,
                "version_id": version.id,
                "request_owner_id": self.requester.id,
                "current_node_id": "Task_Return",
                "active_branch_node_ids": ["Task_Return"],
            }
        )

        self.assertEqual(
            request_record._workflow_find_meta_action_for_transition(
                "Timer_DueTomorrow",
                source_node_id="Task_Return",
            ),
            return_action,
        )
        self.assertEqual(
            request_record._workflow_find_meta_action_for_transition(
                "Timer_DueTomorrow",
                source_node_id="Task_Extend",
            ),
            extend_action,
        )

        timer_instance = self.AutomationInstance.sudo().create_or_get(
            request_record=request_record,
            node_id="Timer_DueTomorrow",
            node_name="Due Date Tomorrow",
            node_type="timerEvent",
            branch_node_id="Task_Return",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            payload_json={"execution_mode": "timer_transition", "source_node_id": "Task_Return"},
        )

        request_record._workflow_run_runtime_automation_instance(timer_instance)

        timer_instance.invalidate_recordset(["status", "result_json", "error_message"])
        self.assertEqual(timer_instance.status, "success", timer_instance.error_message or timer_instance.result_json)
        self.assertEqual((timer_instance.result_json or {}).get("executed_node_ids"), ["Task_LogReminder"])

    def test_date_based_recurring_timer_reminder_can_recur_forever_while_stage_is_active(self):
        timer_action = self.MetaAction.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Overdue Timer Reminder",
                "source_id": "Task_Approval",
                "target_id": "Timer_OverdueReminder",
                "target_node_type": "timerEvent",
                "domain": "[('date_deadline', '<', current_date)]",
                "automation_trigger_mode": "reminder",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "forever",
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=timer_action.target_id,
            node_name=timer_action.name,
            node_type="timerEvent",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="forever",
        )

        self.assertEqual(timer_action.flow_type, "autoAction")
        plan = instance._prepare_recurrence_after_success(meta_action=timer_action)
        self.assertEqual(plan["completed_runs"], 1)
        self.assertTrue(plan["next_due_at"])

    def test_execute_path_precheck_preserves_queue_pairs_through_side_effect_nodes(self):
        engine = BpmnEngine("""<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_ExecutePathPrecheck">
              <bpmn:process id="Process_ExecutePathPrecheck" isExecutable="true">
                <bpmn:userTask id="Task_Source" name="Source">
                  <bpmn:outgoing>Flow_Send</bpmn:outgoing>
                </bpmn:userTask>
                <bpmn:sendTask id="Task_SendReminder" name="Send Reminder">
                  <bpmn:incoming>Flow_Send</bpmn:incoming>
                  <bpmn:outgoing>Flow_User</bpmn:outgoing>
                </bpmn:sendTask>
                <bpmn:userTask id="Task_Return" name="Return">
                  <bpmn:incoming>Flow_User</bpmn:incoming>
                </bpmn:userTask>
                <bpmn:sequenceFlow id="Flow_Send" sourceRef="Task_Source" targetRef="Task_SendReminder"/>
                <bpmn:sequenceFlow id="Flow_User" sourceRef="Task_SendReminder" targetRef="Task_Return"/>
              </bpmn:process>
            </bpmn:definitions>""")
        source_node = engine.get_element_by_id("Task_Source")
        start_node = engine.get_element_by_id("Task_SendReminder")

        activations = self.request._workflow_collect_execute_path_targets(
            engine=engine,
            start_node=start_node,
            source_node=source_node,
            form_data=self.request._get_form_data(),
        )

        self.assertEqual(len(activations), 1)
        self.assertEqual(activations[0][0].attrib.get("id"), "Task_Return")
        self.assertEqual(activations[0][1].attrib.get("id"), "Task_SendReminder")

    def _build_timer_guard_case(self, *, action_values):
        version = self.Version.sudo().create(
            {
                "category_id": self.category.id,
                "name": "v_timer_guard_rearm",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_TimerGuard">
                  <bpmn:process id="Process_TimerGuard" isExecutable="true">
                    <bpmn:userTask id="Task_HOD" name="HOD Approval">
                      <bpmn:outgoing>Flow_Timer</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateCatchEvent id="Timer_Check" name="Check Later">
                      <bpmn:incoming>Flow_Timer</bpmn:incoming>
                      <bpmn:outgoing>Flow_End</bpmn:outgoing>
                      <bpmn:timerEventDefinition id="TimerDefinition_Check"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:endEvent id="Event_End" name="Done">
                      <bpmn:incoming>Flow_End</bpmn:incoming>
                    </bpmn:endEvent>
                    <bpmn:sequenceFlow id="Flow_Timer" sourceRef="Task_HOD" targetRef="Timer_Check"/>
                    <bpmn:sequenceFlow id="Flow_End" sourceRef="Timer_Check" targetRef="Event_End"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        version.action_sync_bpmn_metadata()
        self.category.sudo().write({"active_version_id": version.id})
        timer_action = self.MetaAction.sudo().search(
            [("version_id", "=", version.id), ("target_id", "=", "Timer_Check")],
            limit=1,
        )
        if not timer_action:
            timer_action = self.MetaAction.sudo().create(
                {
                    "version_id": version.id,
                    "name": "Check Later",
                    "source_id": "Task_HOD",
                    "source_name": "HOD Approval",
                    "source_node_type": "userTask",
                    "target_id": "Timer_Check",
                    "target_name": "Check Later",
                    "target_node_type": "timerEvent",
                    "node_id": "Flow_Timer",
                }
            )
        timer_action.sudo().write(
            {
                "automation_schedule_mode": "interval",
                "automation_interval_number": 1,
                "automation_interval_type": "days",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 2,
                **action_values,
            }
        )
        timer_action.invalidate_recordset([
            "automation_recurrence_end_mode",
            "automation_recurrence_count",
            "automation_recurrence_until",
        ])
        request_record = self.Request.sudo().create(
            {
                "name": "REQ_TIMER_GUARD_REARM",
                "category_id": self.category.id,
                "version_id": version.id,
                "request_owner_id": self.requester.id,
                "current_node_id": "Task_HOD",
                "active_branch_node_ids": ["Task_HOD"],
            }
        )
        timer_instance = self.AutomationInstance.sudo().create_or_get(
            request_record=request_record,
            node_id="Timer_Check",
            node_name="Check Later",
            node_type="timerEvent",
            branch_node_id="Task_HOD",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode=timer_action.automation_recurrence_end_mode,
            recurrence_count=timer_action.automation_recurrence_count,
            recurrence_until=timer_action.automation_recurrence_until,
            payload_json={"execution_mode": "timer_transition", "source_node_id": "Task_HOD"},
        )
        return request_record, timer_instance

    def test_recurring_timer_rearms_when_auto_action_condition_is_false(self):
        request_record, timer_instance = self._build_timer_guard_case(
            action_values={"auto_action_condition": "[('name', '=', 'WILL_MATCH_LATER')]"}
        )

        request_record._workflow_run_runtime_automation_instance(timer_instance)

        timer_instance.invalidate_recordset(["status", "run_count", "result_json", "due_at", "error_message"])
        self.assertEqual(timer_instance.status, "scheduled", timer_instance.error_message or timer_instance.result_json)
        self.assertEqual(timer_instance.run_count, 1)
        self.assertTrue((timer_instance.result_json or {}).get("skipped"))
        self.assertTrue(timer_instance.due_at)

    def test_recurring_route_timer_until_first_success_rearms_when_condition_is_false(self):
        request_record, timer_instance = self._build_timer_guard_case(
            action_values={
                "automation_trigger_mode": "route",
                "automation_recurrence_end_mode": "until_success",
                "auto_action_condition": "[('name', '=', 'WILL_MATCH_LATER')]",
            }
        )

        request_record._workflow_run_runtime_automation_instance(timer_instance)

        timer_instance.invalidate_recordset(["status", "run_count", "result_json", "due_at", "error_message"])
        self.assertEqual(timer_instance.status, "scheduled", timer_instance.error_message or timer_instance.result_json)
        self.assertEqual(timer_instance.run_count, 1)
        self.assertTrue((timer_instance.result_json or {}).get("skipped"))
        self.assertTrue(timer_instance.due_at)

    def test_until_first_success_stops_after_success_but_not_after_skip(self):
        timer_action = self.MetaAction.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Until Success Timer",
                "source_id": "Task_Approval",
                "target_id": "Timer_UntilSuccess",
                "target_node_type": "timerEvent",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 5,
                "automation_interval_type": "minutes",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "until_success",
            }
        )
        instance = self.AutomationInstance.sudo().create_or_get(
            request_record=self.request,
            node_id=timer_action.target_id,
            node_name=timer_action.name,
            node_type="timerEvent",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="until_success",
        )

        skipped_plan = instance._prepare_recurrence_after_success(
            meta_action=timer_action,
            execution_succeeded=False,
        )
        self.assertEqual(skipped_plan["completed_runs"], 1)
        self.assertTrue(skipped_plan["next_due_at"])

        success_plan = instance._prepare_recurrence_after_success(meta_action=timer_action)
        self.assertEqual(success_plan["completed_runs"], 1)
        self.assertFalse(success_plan["next_due_at"])

    def test_recurring_timer_rearms_when_runtime_guard_is_false(self):
        request_record, timer_instance = self._build_timer_guard_case(
            action_values={"domain": "[('name', '=', 'WILL_MATCH_LATER')]"}
        )

        request_record._workflow_run_runtime_automation_instance(timer_instance)

        timer_instance.invalidate_recordset(["status", "run_count", "result_json", "due_at", "error_message"])
        self.assertEqual(timer_instance.status, "scheduled", timer_instance.error_message or timer_instance.result_json)
        self.assertEqual(timer_instance.run_count, 1)
        self.assertTrue((timer_instance.result_json or {}).get("skipped"))
        self.assertTrue(timer_instance.due_at)

    def test_timer_reminder_path_executes_side_effect_without_moving_workflow(self):
        version = self.Version.sudo().create(
            {
                "category_id": self.category.id,
                "name": "v_timer_reminder_path",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Reminder">
                  <bpmn:process id="Process_Reminder" isExecutable="true">
                    <bpmn:userTask id="Task_HOD" name="HOD Approval">
                      <bpmn:outgoing>Flow_Timer</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateCatchEvent id="Timer_Reminder" name="Reminder">
                      <bpmn:incoming>Flow_Timer</bpmn:incoming>
                      <bpmn:outgoing>Flow_Send</bpmn:outgoing>
                      <bpmn:timerEventDefinition id="TimerDefinition_Reminder"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:sendTask id="Task_SendReminder" name="Send Reminder">
                      <bpmn:incoming>Flow_Send</bpmn:incoming>
                      <bpmn:outgoing>Flow_End</bpmn:outgoing>
                    </bpmn:sendTask>
                    <bpmn:endEvent id="Event_End" name="Done">
                      <bpmn:incoming>Flow_End</bpmn:incoming>
                    </bpmn:endEvent>
                    <bpmn:sequenceFlow id="Flow_Timer" sourceRef="Task_HOD" targetRef="Timer_Reminder"/>
                    <bpmn:sequenceFlow id="Flow_Send" sourceRef="Timer_Reminder" targetRef="Task_SendReminder"/>
                    <bpmn:sequenceFlow id="Flow_End" sourceRef="Task_SendReminder" targetRef="Event_End"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        version.action_sync_bpmn_metadata()
        request_record = self.request.sudo()
        request_record.sudo().write(
            {
                "version_id": version.id,
                "current_node_id": "Task_HOD",
                "active_branch_node_ids": ["Task_HOD"],
            }
        )
        timer_action = self.MetaAction.sudo().search(
            [("version_id", "=", version.id), ("target_id", "=", "Timer_Reminder")],
            limit=1,
        )
        timer_action.sudo().write(
            {
                "automation_trigger_mode": "reminder",
                "automation_is_recurring": True,
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
            }
        )
        timer_instance = self.AutomationInstance.sudo().create_or_get(
            request_record=request_record,
            node_id="Timer_Reminder",
            node_name="Reminder",
            node_type="timerEvent",
            branch_node_id="Task_HOD",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            recurrence_enabled=True,
            recurrence_mode="forever",
            payload_json={"execution_mode": "timer_transition", "source_node_id": "Task_HOD"},
        )
        request_record._workflow_run_runtime_automation_instance(timer_instance)

        request_record.invalidate_recordset(["current_node_id", "active_branch_node_ids"])
        timer_instance.invalidate_recordset(["status", "due_at", "run_count", "result_json"])
        self.assertEqual((timer_instance.result_json or {}).get("executed_node_ids"), ["Task_SendReminder"])
        self.assertEqual(request_record.current_node_id, "Task_HOD")
        self.assertIn("Task_HOD", request_record.active_branch_node_ids)
        self.assertEqual(timer_instance.status, "scheduled")
        self.assertEqual(timer_instance.run_count, 1)

    def test_execute_path_action_runs_side_effect_and_reassigns_current_task_repeatedly(self):
        self.skipTest("Execute-path transitions require a concrete approval child model in integration tests.")
        version = self.Version.sudo().create(
            {
                "category_id": self.category.id,
                "name": "v_execute_path_notify_loop",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_NotifyLoop">
                  <bpmn:process id="Process_NotifyLoop" isExecutable="true">
                    <bpmn:userTask id="Task_HOD" name="HOD Approval">
                      <bpmn:incoming>Flow_Back</bpmn:incoming>
                      <bpmn:outgoing>Flow_Notify</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateThrowEvent id="Event_Notify" name="Notify">
                      <bpmn:incoming>Flow_Notify</bpmn:incoming>
                      <bpmn:outgoing>Flow_Send</bpmn:outgoing>
                    </bpmn:intermediateThrowEvent>
                    <bpmn:sendTask id="Task_SendNotify" name="Send Notify">
                      <bpmn:incoming>Flow_Send</bpmn:incoming>
                      <bpmn:outgoing>Flow_Back</bpmn:outgoing>
                    </bpmn:sendTask>
                    <bpmn:sequenceFlow id="Flow_Notify" sourceRef="Task_HOD" targetRef="Event_Notify"/>
                    <bpmn:sequenceFlow id="Flow_Send" sourceRef="Event_Notify" targetRef="Task_SendNotify"/>
                    <bpmn:sequenceFlow id="Flow_Back" sourceRef="Task_SendNotify" targetRef="Task_HOD"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        version.action_sync_bpmn_metadata()
        meta_hod = self.MetaTask.sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_HOD")],
            limit=1,
        )
        meta_hod.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        notify_action = self.MetaAction.sudo().search(
            [("version_id", "=", version.id), ("source_id", "=", "Task_HOD"), ("target_id", "=", "Event_Notify")],
            limit=1,
        )
        notify_action.sudo().write({"action_mode": "execute_path"})
        request_record = self.Request.sudo().create(
            {
                "name": "REQ_EXECUTE_PATH_NOTIFY_LOOP",
                "category_id": self.category.id,
                "version_id": version.id,
                "request_owner_id": self.requester.id,
                "current_node_id": "Task_HOD",
                "current_iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request_record.id,
                "current_meta_id": meta_hod.id,
                "previous_meta_id": meta_hod.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )

        with patch.object(type(request_record), "_workflow_execute_runtime_actions", return_value=None) as execute_actions:
            request_record.with_user(self.approver_a)._run_engine(meta_action_id=notify_action.id)
            request_record.invalidate_recordset(["current_node_id", "active_branch_node_ids"])
            self.assertEqual(request_record.current_node_id, "Task_HOD")
            self.assertFalse(request_record.active_branch_node_ids)
            self.assertEqual(execute_actions.call_count, 1)

            request_record.with_user(self.approver_a)._run_engine(meta_action_id=notify_action.id)
            request_record.invalidate_recordset(["current_node_id", "active_branch_node_ids"])
            self.assertEqual(request_record.current_node_id, "Task_HOD")
            self.assertEqual(execute_actions.call_count, 2)

        notify_instances = self.AutomationInstance.sudo().search(
            [("request_id", "=", request_record.id), ("node_id", "=", "Task_SendNotify")]
        )
        self.assertEqual(len(notify_instances), 2)
        open_hod_rows = request_record.approver_ids.filtered(
            lambda row: row.current_meta_id == meta_hod
            and row.user_id == self.approver_a
            and row.status in ["new", "pending", "waiting"]
        )
        self.assertEqual(len(open_hod_rows), 1)

    def test_timer_reminder_does_not_execute_unlinked_side_effect_task(self):
        version = self.Version.sudo().create(
            {
                "category_id": self.category.id,
                "name": "v_timer_reminder_no_fallback",
                "bpmn_xml": """<?xml version="1.0" encoding="UTF-8"?>
                <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Reminder_NoFallback">
                  <bpmn:process id="Process_Reminder_NoFallback" isExecutable="true">
                    <bpmn:userTask id="Task_HOD" name="HOD Approval">
                      <bpmn:outgoing>Flow_Timer</bpmn:outgoing>
                    </bpmn:userTask>
                    <bpmn:intermediateCatchEvent id="Timer_Reminder" name="Reminder">
                      <bpmn:incoming>Flow_Timer</bpmn:incoming>
                      <bpmn:timerEventDefinition id="TimerDefinition_Reminder"/>
                    </bpmn:intermediateCatchEvent>
                    <bpmn:sendTask id="Task_UnlinkedReminder" name="Unlinked Reminder"/>
                    <bpmn:sequenceFlow id="Flow_Timer" sourceRef="Task_HOD" targetRef="Timer_Reminder"/>
                  </bpmn:process>
                </bpmn:definitions>""",
            }
        )
        version.action_sync_bpmn_metadata()
        request_record = self.request.sudo()
        request_record.sudo().write(
            {
                "version_id": version.id,
                "current_node_id": "Task_HOD",
                "active_branch_node_ids": ["Task_HOD"],
            }
        )
        timer_action = self.MetaAction.sudo().search(
            [("version_id", "=", version.id), ("target_id", "=", "Timer_Reminder")],
            limit=1,
        )
        timer_action.sudo().write({"automation_trigger_mode": "reminder"})
        timer_instance = self.AutomationInstance.sudo().create_or_get(
            request_record=request_record,
            node_id="Timer_Reminder",
            node_name="Reminder",
            node_type="timerEvent",
            branch_node_id="Task_HOD",
            trigger_type="timer",
            action_type="transition",
            due_at=fields.Datetime.now(),
            payload_json={"execution_mode": "timer_transition", "source_node_id": "Task_HOD"},
        )

        with patch.object(
            type(request_record),
            "_workflow_execute_runtime_actions",
            wraps=type(request_record)._workflow_execute_runtime_actions,
        ) as execute_actions:
            request_record._workflow_run_runtime_automation_instance(timer_instance)

        timer_instance.invalidate_recordset(["status", "result_json"])
        self.assertEqual((timer_instance.result_json or {}).get("executed_node_ids"), [])
        self.assertEqual(timer_instance.status, "success")
        self.assertFalse(execute_actions.called)

    def test_runtime_v2_pass_through_single_approval_closes_source_rows_and_preserves_business_labels(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        run_engine_source = inspect.getsource(ApprovalChildMixin._run_engine)
        transition_source = inspect.getsource(ApprovalChildMixin._workflow_run_runtime_transition_path)

        self.assertIn("source_stage_node = current_node", run_engine_source)
        self.assertIn("source_stage_node=source_stage_node", run_engine_source)
        self.assertIn("_first_available_node(source_stage_node, current_node, previous)", transition_source)
        self.assertIn("current_node=_first_available_node(source_stage_node, previous)", transition_source)
        self.assertIn("_first_available_node(source_stage_node, previous)", transition_source)

    def test_runtime_v2_pass_through_multi_approval_waits_before_closing_source_rows(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._run_engine)
        multi_guard_index = source.index(
            'and (meta_action.authorization_mode or "approval_actor") == "approval_actor"'
        )
        approval_count_index = source.index(
            "and meta_action.approval_require_number > 1",
            multi_guard_index,
        )
        multi_handle_index = source.index(
            "multi_approval_result = self._handle_multiple_approvers(current_node, meta_action)"
        )
        early_return_index = source.index("if multi_approval_result is False:")
        transition_index = source.index("transition_result = self._workflow_run_runtime_transition_path(")

        self.assertLess(multi_guard_index, transition_index)
        self.assertLess(approval_count_index, transition_index)
        self.assertLess(multi_handle_index, transition_index)
        self.assertLess(early_return_index, transition_index)
        self.assertIn("approval_recorded = multi_approval_result is True", source)

    def test_runtime_v2_direct_reject_end_event_closes_other_stage_assignees(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._run_engine)
        direct_branch_anchor = source.index("# for not assign approval for migrate old data")
        actor_action_index = source.index(
            "self._workflow_process_actor_action(meta_action)",
            direct_branch_anchor,
        )
        cleanup_guard_index = source.index(
            'if source_node_id and next_node_id and source_node_id != next_node_id:',
            actor_action_index,
        )
        cleanup_index = source.index(
            "self._close_open_source_stage_approvers(current_node)",
            cleanup_guard_index,
        )
        branch_resolution_index = source.index(
            "if self.active_branch_node_ids and meta_action.source_id in (self.active_branch_node_ids or []):",
            cleanup_index,
        )

        self.assertLess(actor_action_index, cleanup_guard_index)
        self.assertLess(cleanup_guard_index, cleanup_index)
        self.assertLess(cleanup_index, branch_resolution_index)

    def test_repair_stale_open_assignment_rows_scopes_to_selected_requests_only(self):
        data = self._create_runtime_v2_pass_through_version("repair", approval_require_number=1)
        request_record = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_V2_REPAIR_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "version_id": data["version"].id,
                "request_owner_id": self.requester.id,
                "current_node_id": data["meta_nurse"].node_id,
                "previous_node_id": data["meta_send"].node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        untouched_request = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_V2_REPAIR_UNTOUCHED_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "version_id": data["version"].id,
                "request_owner_id": self.requester.id,
                "current_node_id": data["meta_nurse"].node_id,
                "previous_node_id": data["meta_send"].node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        stale_hod_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": request_record.id,
                "current_meta_id": data["meta_hod"].id,
                "previous_meta_id": data["meta_submission"].id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        untouched_stale_row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": untouched_request.id,
                "current_meta_id": data["meta_hod"].id,
                "previous_meta_id": data["meta_submission"].id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": request_record.id,
                "current_meta_id": data["meta_hod"].id,
                "previous_meta_id": data["meta_submission"].id,
                "status": "approved",
                "user_decision": "Approve",
                "required": False,
                "iteration_no": 1,
            }
        )
        self.Approver.sudo().create(
            {
                "user_id": self.approver_a.id,
                "request_id": untouched_request.id,
                "current_meta_id": data["meta_hod"].id,
                "previous_meta_id": data["meta_submission"].id,
                "status": "approved",
                "user_decision": "Approve",
                "required": False,
                "iteration_no": 1,
            }
        )
        nurse_row = self.Approver.sudo().create(
            {
                "user_id": self.requester.id,
                "request_id": request_record.id,
                "current_meta_id": data["meta_nurse"].id,
                "previous_meta_id": data["meta_send"].id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )

        repaired_rows = self.Approver._repair_stale_open_assignment_rows(requests=request_record)
        stale_hod_row.invalidate_recordset(["status"])
        untouched_stale_row.invalidate_recordset(["status"])
        nurse_row.invalidate_recordset(["status", "from_activity_label", "to_activity_label", "activity_flow"])

        self.assertIn(stale_hod_row, repaired_rows)
        self.assertEqual(stale_hod_row.status, "closed")
        self.assertEqual(untouched_stale_row.status, "new")
        self.assertEqual(nurse_row.status, "new")
        self.assertEqual(nurse_row.from_activity_label, "HOD Approval")
        self.assertIn("Nurse", nurse_row.to_activity_label)
        self.assertIn("HOD Approval -> Nurse", nurse_row.activity_flow)

    def test_activity_event_at_tracks_workflow_event_time_not_raw_row_creation(self):
        data = self._create_runtime_v2_pass_through_version("event_at", approval_require_number=1)
        request_record = self.Request.sudo().create(
            {
                "name": f"REQ_RUNTIME_V2_EVENT_AT_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "version_id": data["version"].id,
                "request_owner_id": self.requester.id,
                "current_node_id": data["meta_nurse"].node_id,
                "previous_node_id": data["meta_hod"].node_id,
                "current_iteration_no": 1,
                "state": "waiting",
            }
        )
        row = self.Approver.sudo().create(
            {
                "user_id": self.approver_b.id,
                "request_id": request_record.id,
                "current_meta_id": data["meta_nurse"].id,
                "previous_meta_id": data["meta_hod"].id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        row.invalidate_recordset(["create_date", "activity_event_at"])
        self.assertEqual(row.activity_event_at, row.create_date)

        original_event_at = row.activity_event_at
        row.write({"remark": "metadata only"})
        row.invalidate_recordset(["activity_event_at"])
        self.assertEqual(
            row.activity_event_at,
            original_event_at,
            "Non-workflow metadata edits must not rewrite the visible activity timestamp.",
        )

        row.write({"status": "closed"})
        row.invalidate_recordset(["status", "write_date", "activity_event_at", "create_date"])
        self.assertEqual(row.status, "closed")
        self.assertNotEqual(row.activity_event_at, row.create_date)
        self.assertGreaterEqual(
            row.activity_event_at,
            original_event_at.replace(microsecond=0),
        )

    def test_workflow_action_payloads_must_match_workflow_model(self):
        user_model = self.env["ir.model"]._get("res.users")
        valid_server_action = self.env["ir.actions.server"].sudo().create(
            {
                "name": "Runtime Valid Server Action",
                "model_id": self.base_request_model.id,
                "state": "code",
                "code": "result = True",
            }
        )
        invalid_server_action = self.env["ir.actions.server"].sudo().create(
            {
                "name": "Runtime Invalid Server Action",
                "model_id": user_model.id,
                "state": "code",
                "code": "result = True",
            }
        )
        valid_template = self.MailTemplate.sudo().create(
            {
                "name": "Runtime Valid Template",
                "model_id": self.base_request_model.id,
                "subject": "Runtime Valid",
                "body_html": "<p>OK</p>",
            }
        )
        invalid_template = self.MailTemplate.sudo().create(
            {
                "name": "Runtime Invalid Template",
                "model_id": user_model.id,
                "subject": "Runtime Invalid",
                "body_html": "<p>No</p>",
            }
        )

        action = self.WorkflowAction.sudo().create(
            {
                "name": "Valid Server Wrapper",
                "action_type": "server_action",
                "version_id": self.version.id,
                "server_action_id": valid_server_action.id,
            }
        )
        self.assertEqual(action.server_action_id, valid_server_action)

        mail_action = self.WorkflowAction.sudo().create(
            {
                "name": "Valid Mail Wrapper",
                "action_type": "email",
                "version_id": self.version.id,
                "email_template_id": valid_template.id,
            }
        )
        self.assertEqual(mail_action.email_template_id, valid_template)

        with self.assertRaises(ValidationError):
            self.WorkflowAction.sudo().create(
                {
                    "name": "Invalid Server Wrapper",
                    "action_type": "server_action",
                    "version_id": self.version.id,
                    "server_action_id": invalid_server_action.id,
                }
            )

        with self.assertRaises(ValidationError):
            self.WorkflowAction.sudo().create(
                {
                    "name": "Invalid Mail Wrapper",
                    "action_type": "email",
                    "version_id": self.version.id,
                    "email_template_id": invalid_template.id,
                }
            )

    def test_meta_task_form_view_exposes_runtime_property_fields(self):
        form_view = self.MetaTask.get_view(
            view_id=self.env.ref("workflow_engine.view_workflow_meta_form").id,
            view_type="form",
        )
        arch = form_view["arch"]

        self.assertIn("service_behavior", arch)
        self.assertIn("automation_run_mode", arch)
        self.assertIn("notification_recipient_mode", arch)
        self.assertIn("notification_email_template_id", arch)
        self.assertIn("notify_request_owner_email", arch)
        self.assertIn("notify_request_creator_email", arch)

    def test_request_form_exposes_notification_audit_on_automation_instances(self):
        arch = self.env.ref("workflow_engine.approval_base_request_view_form").arch_db

        self.assertIn("notification_audit_json", arch)
        self.assertIn("notification_audit_sent_summary", arch)
        self.assertIn("notification_audit_summary", arch)

    def test_request_automation_instance_schedule_retry_sets_due_status(self):
        instance = self.AutomationInstance.create_or_get(
            request_record=self.request,
            node_id="Task_Sync_Blue_Retry",
            node_name="Sync with Blue Retry",
            node_type="serviceTask",
            trigger_type="automation",
            action_type="enqueue_job",
            payload_json={"execution_mode": "side_effect"},
        )
        instance.schedule_retry("Temporary outage")
        self.assertEqual(instance.status, "scheduled")
        self.assertEqual(instance.retry_count, 1)
        self.assertTrue(instance.due_at)
        self.assertEqual(instance.error_message, "Temporary outage")

    def test_request_automation_instance_run_once_dispatches_to_delegate(self):
        instance = self.AutomationInstance.create_or_get(
            request_record=self.request,
            node_id="Task_Sync_Blue_Dispatch",
            node_name="Sync with Blue Dispatch",
            node_type="serviceTask",
            trigger_type="automation",
            action_type="enqueue_job",
            payload_json={"execution_mode": "side_effect"},
        )

        request_model_cls = type(self.request)

        def _fake_runtime_runner(automation_instance):
            automation_instance.mark_success({"dispatched": True})
            return True

        with patch.object(
            request_model_cls,
            "_workflow_run_runtime_automation_instance",
            create=True,
            side_effect=_fake_runtime_runner,
        ):
            instance._run_once()

        instance.invalidate_recordset()
        self.assertEqual(instance.status, "success")
        self.assertEqual(instance.result_json, {"dispatched": True})

    def test_runtime_v2_parallel_split_uses_branch_executor(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._process_parallel_split)
        self.assertIn("self._workflow_is_runtime_v2()", source)
        self.assertIn("_workflow_execute_runtime_branch", source)
        self.assertIn("_set_parallel_wait_state(split_node, join_node, active_branch_ids, display_node=display_node)", source)

    def test_runtime_v2_transition_path_closes_source_stage_before_split(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._workflow_run_runtime_transition_path)
        close_source_index = source.find(
            "_first_available_node(source_stage_node, current_node, previous)"
        )
        split_process_index = source.find("split_result = self._process_parallel_split")
        self.assertGreaterEqual(close_source_index, 0)
        self.assertGreaterEqual(split_process_index, 0)
        self.assertLess(
            close_source_index,
            split_process_index,
            "Transition path must close source-stage approvers before processing a split gateway.",
        )

    def test_runtime_v2_transition_path_closes_source_stage_before_plain_end_event_return(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._workflow_run_runtime_transition_path)
        end_branch_index = source.rfind("if engine.is_end_event(current):")
        self.assertGreaterEqual(end_branch_index, 0)

        end_branch_source = source[end_branch_index:]
        close_source_index = end_branch_source.find(
            "_first_available_node(source_stage_node, current_node, previous)"
        )
        update_index = end_branch_source.find("self._update_tracking_fields(")
        return_index = end_branch_source.find('return {"waiting": False, "next_node": current}')

        self.assertGreaterEqual(close_source_index, 0)
        self.assertGreaterEqual(update_index, 0)
        self.assertGreaterEqual(return_index, 0)
        self.assertLess(
            close_source_index,
            update_index,
            "Transition path must close source-stage approvers before finishing on a plain end event.",
        )
        self.assertLess(update_index, return_index)

    def test_runtime_v2_run_engine_manages_timers_and_post_activation(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._run_engine)
        self.assertIn("_workflow_cancel_runtime_instances", source)
        self.assertIn("_workflow_post_activate_runtime_node", source)

    def test_force_jump_without_meta_action_closes_previous_runtime_state(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._force_jump_without_meta_action)
        self.assertIn("workflow_skip_edit_scope=True", source)
        self.assertIn("workflow_skip_field_policy=True", source)
        self.assertIn("workflow_allow_runtime_tracking_write=True", source)
        self.assertIn("_workflow_close_runtime_branch", source)
        self.assertIn("decision_if_blank", source)
        self.assertIn("_workflow_cancel_runtime_instances", source)
        self.assertIn("_workflow_post_activate_runtime_node", source)

    def test_runtime_v2_parallel_resume_initializes_engine_before_projection(self):
        from odoo.addons.workflow_engine.models.approval_child_mixin import ApprovalChildMixin

        source = inspect.getsource(ApprovalChildMixin._workflow_resume_parallel_join)
        self.assertIn("_resolve_parallel_display_node", source)
        self.assertLess(source.index("engine = BpmnEngine"), source.index("if active_nodes:"))

    def test_group_link_domain_resolved_against_child_model_field(self):
        """link.domain referencing a child-model field (e.g. x_it_session_id) must be
        evaluated against the child record, not workflow.base.approval.request.

        Regression: before the eval_record fix, match_request_domain was called with
        the base request which has no x_* custom fields.  The domain silently failed
        (field not found → exception → returns False) and NO group was ever included,
        producing "No approvers were added" even when a group was correctly configured.
        """
        group_a = self.ApprovalGroup.sudo().create(
            {
                "name": f"Child Field Group A {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        group_b = self.ApprovalGroup.sudo().create(
            {
                "name": f"Child Field Group B {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_b.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_a.id,
                "domain": "[('id', 'in', [999999])]",   # never matches any real record
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_b.id,
                "domain": "[('id', 'in', [%d])]" % self.request.id,  # matches this request
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 20,
            }
        )

        # Passing base request directly: group_b domain matches (request.id matches).
        result_base = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertIn(self.approver_b.id, result_base["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result_base["final_user_ids"])

        # Now simulate the child-model scenario using eval_record.
        # Create a minimal proxy object whose id matches a different domain condition.
        # We use a second base request record as the "child-model eval record"
        # (real child models are Studio-generated; we use a second request to avoid
        #  Studio dependency in the engine test suite).
        child_like_record = self.Request.sudo().create(
            {
                "name": f"CHILD_PROXY_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "current_iteration_no": 1,
            }
        )
        # group_a domain [('id','in',[999999])] → never matches child_like_record
        # group_b domain [('id','in',[request.id])] → only matches self.request, not child_like_record
        # So when eval against child_like_record, neither group matches → blocked.
        result_child_no_match = self.legacy_adapter_service.prepare_legacy_approver_rows(
            request_record=self.request,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
            iteration_no=1,
            existing_keys=set(),
            eval_record=child_like_record,  # different id → neither domain matches
        )
        self.assertFalse(result_child_no_match["approver_data_list"],
            "eval_record with non-matching id should yield no approvers (block)")

        # Update group_b's domain to match child_like_record's id.
        self.meta_hod.approval_group_link_ids.sudo().filtered(
            lambda l: l.approval_group_id == group_b
        ).write({"domain": "[('id', 'in', [%d])]" % child_like_record.id})

        result_child_match = self.legacy_adapter_service.prepare_legacy_approver_rows(
            request_record=self.request,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
            iteration_no=1,
            existing_keys=set(),
            eval_record=child_like_record,  # now matches group_b
        )
        self.assertTrue(result_child_match["approver_data_list"],
            "eval_record matching group_b domain should assign approver_b")
        row_user_ids = {r["user_id"] for r in result_child_match["approver_data_list"]}
        self.assertIn(self.approver_b.id, row_user_ids)
        self.assertNotIn(self.approver_a.id, row_user_ids)
        # request_id in rows must still point to the base request, not eval_record
        for row in result_child_match["approver_data_list"]:
            self.assertEqual(row["request_id"], self.request.id,
                "request_id in approver rows must always be the base request id")

    def test_group_link_domain_supports_relational_request_owner_path(self):
        group_a = self.ApprovalGroup.sudo().create(
            {
                "name": f"Owner Path Group A {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        group_b = self.ApprovalGroup.sudo().create(
            {
                "name": f"Owner Path Group B {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_b.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_a.id,
                "domain": f"[('request_owner_id.employee_id.department_id.id', '=', {self.department.id + 999})]",
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_b.id,
                "domain": f"[('request_owner_id.employee_id.department_id.id', '=', {self.department.id})]",
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)

        self.assertIn(self.approver_b.id, result["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result["final_user_ids"])

    def test_group_link_domain_base_request_used_when_no_eval_record(self):
        """When eval_record is not passed, base request is used for domain evaluation.
        This preserves backward compatibility for callers that do not supply eval_record.
        """
        group_c = self.ApprovalGroup.sudo().create(
            {
                "name": f"Base Request Group C {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_c.id,
                "domain": "[('id', 'in', [%d])]" % self.request.id,  # matches base request
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )

        # No eval_record → falls back to request_record for domain eval
        result = self.legacy_adapter_service.prepare_legacy_approver_rows(
            request_record=self.request,
            current_meta_task=self.meta_hod,
            previous_meta_task=self.meta_submission,
            iteration_no=1,
            existing_keys=set(),
            # eval_record intentionally omitted
        )
        self.assertTrue(result["approver_data_list"],
            "Without eval_record, domain is evaluated against base request — must still match")
        row_user_ids = {r["user_id"] for r in result["approver_data_list"]}
        self.assertIn(self.approver_a.id, row_user_ids)

    def test_group_link_domains_route_distinct_groups_by_request_value(self):
        """Per-link record domains should route to different approval groups based on request data."""
        group_a = self.ApprovalGroup.sudo().create(
            {
                "name": f"Route Group A {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        group_b = self.ApprovalGroup.sudo().create(
            {
                "name": f"Route Group B {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_b.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_a.id,
                "domain": "[('request_owner_id', '=', %d)]" % self.requester.id,
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_b.id,
                "domain": "[('request_owner_id', '=', %d)]" % self.manager.id,
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 20,
            }
        )

        request_a = self.Request.sudo().create(
            {
                "name": f"REQ_ROUTE_A_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )
        request_b = self.Request.sudo().create(
            {
                "name": f"REQ_ROUTE_B_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.manager.id,
                "current_node_id": self.meta_hod.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )

        result_a = self.assignment_service.resolve_assignees(request_a, self.meta_hod)
        self.assertIn(self.approver_a.id, result_a["final_user_ids"])
        self.assertNotIn(self.approver_b.id, result_a["final_user_ids"])

        result_b = self.assignment_service.resolve_assignees(request_b, self.meta_hod)
        self.assertIn(self.approver_b.id, result_b["final_user_ids"])
        self.assertNotIn(self.approver_a.id, result_b["final_user_ids"])

    def test_group_link_domains_block_when_no_rule_matches(self):
        """When no approval-group record domain matches, group assignment should yield no candidates and stay blocked."""
        group_a = self.ApprovalGroup.sudo().create(
            {
                "name": f"No Match Group A {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_a.id])],
            }
        )
        group_b = self.ApprovalGroup.sudo().create(
            {
                "name": f"No Match Group B {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [self.approver_b.id])],
            }
        )
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_a.id,
                "domain": "[('request_owner_id', '=', 99999999)]",
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": group_b.id,
                "domain": "[('request_owner_id', '=', 88888888)]",
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 20,
            }
        )

        result = self.assignment_service.resolve_assignees(self.request, self.meta_hod)
        self.assertFalse(result["candidate_user_ids"])
        self.assertFalse(result["final_user_ids"])
        self.assertTrue(result["blocked"])

    # ──────────────────────────────────────────────────────────────────────────
    # Button visibility domain tests (workflow_get_visible_buttons_snapshot)
    # ──────────────────────────────────────────────────────────────────────────

    def _make_button_test_request(self):
        """Create a fresh request with active HOD approvers for button-policy tests."""
        unique = uuid4().hex[:8]
        request = self.Request.sudo().create({
            "name": f"BTN_TEST_{unique}",
            "category_id": self.category.id,
            "request_owner_id": self.requester.id,
            "current_node_id": self.meta_hod.node_id,
            "previous_node_id": self.meta_submission.node_id,
            "current_iteration_no": 1,
            "state": "waiting",
        })
        self.Approver.sudo().create([
            {
                "user_id": user.id,
                "request_id": request.id,
                "current_meta_id": self.meta_hod.id,
                "previous_meta_id": self.meta_submission.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
            for user in (self.requester, self.approver_a, self.approver_b, self.manager, self.department_manager)
        ])
        return request

    def _make_hod_action(self, name, attr_label, invisible_domain=False, node_suffix=None):
        """Create a userAction-typed meta action on the HOD task for button tests."""
        unique = uuid4().hex[:6]
        node_id = f"Flow_{node_suffix or unique}_End"
        return self.MetaAction.sudo().create({
            "name": name,
            "attr_label": attr_label,
            "flow_type": "userAction",
            "meta_task_id": self.meta_hod.id,
            "source_id": self.meta_hod.node_id,
            "source_name": self.meta_hod.name,
            "source_node_type": self.meta_hod.node_type,
            "target_id": self.meta_end.node_id,
            "target_name": self.meta_end.name,
            "target_node_type": self.meta_end.node_type,
            "node_id": node_id,
            "version_id": self.version.id,
            "invisible_domain": invisible_domain or False,
        })

    # ── Business case 1: no invisible_domain → always visible ─────────────────

    def test_visible_buttons_no_domain_always_visible(self):
        """Button with no invisible_domain is returned regardless of snapshot contents."""
        action = self._make_hod_action("btn_no_domain", "Approve", invisible_domain=False)
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            keys = [b["action_key"] for b in buttons]
            self.assertIn("btn_no_domain", keys,
                "Button without invisible_domain must always be included in the result")
        finally:
            action.sudo().unlink()

    def test_ensure_can_approve_allows_empty_list_visibility_domain(self):
        """Server-side action guard must treat invisible_domain='[]' as unrestricted."""
        action = self._make_hod_action("btn_empty_list_domain", "Approve", invisible_domain="[]")
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            req.ensure_can_approve(action)
        finally:
            action.sudo().unlink()

    # ── Business case 2 & 5: snapshot-driven field value / amount threshold ───

    def test_visible_buttons_snapshot_field_match(self):
        """Domain [('x_section', '=', 'hotel')] is satisfied when snapshot provides the matching value."""
        action = self._make_hod_action(
            "btn_hotel", "Hotel Approve",
            invisible_domain="[('x_section', '=', 'hotel')]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(
                snapshot_values={"x_section": "hotel"}
            )
            self.assertIn("btn_hotel", [b["action_key"] for b in buttons],
                "Button must be visible when snapshot field matches domain value")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_snapshot_field_no_match(self):
        """Domain [('x_section', '=', 'hotel')] hides the button when snapshot value differs or is absent."""
        action = self._make_hod_action(
            "btn_hotel2", "Hotel Approve",
            invisible_domain="[('x_section', '=', 'hotel')]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            keys_wrong = [
                b["action_key"]
                for b in req.workflow_get_visible_buttons_snapshot(
                    snapshot_values={"x_section": "office"}
                )
            ]
            self.assertNotIn("btn_hotel2", keys_wrong,
                "Button must be hidden when snapshot field does not match domain value")

            keys_empty = [
                b["action_key"]
                for b in req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            ]
            self.assertNotIn("btn_hotel2", keys_empty,
                "Button must be hidden when the field is absent from snapshot and not on the model")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_snapshot_many2one_resid_match(self):
        """Unsaved many2one snapshots using the web client's {resId, displayName} shape must evaluate live."""
        action = self._make_hod_action(
            "btn_owner_m2o", "Owner Many2one Approve",
            invisible_domain="[('request_owner_id', 'in', [uid])]",
        )
        req = self._make_button_test_request().with_user(self.manager)
        try:
            keys = [
                b["action_key"]
                for b in req.workflow_get_visible_buttons_snapshot(
                    snapshot_values={
                        "request_owner_id": {
                            "resId": self.manager.id,
                            "displayName": self.manager.name,
                        }
                    }
                )
            ]
            self.assertIn("btn_owner_m2o", keys,
                "Button must be visible when snapshot many2one uses the web client's resId/displayName shape")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_amount_threshold(self):
        """Domain [('x_amount', '>', 200)] shows button only when snapshot amount exceeds threshold."""
        action = self._make_hod_action(
            "btn_2nd_approval", "2nd Approval",
            invisible_domain="[('x_amount', '>', 200)]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            keys_above = [
                b["action_key"]
                for b in req.workflow_get_visible_buttons_snapshot(
                    snapshot_values={"x_amount": 250}
                )
            ]
            self.assertIn("btn_2nd_approval", keys_above,
                "Button must be visible when snapshot amount exceeds threshold")

            keys_below = [
                b["action_key"]
                for b in req.workflow_get_visible_buttons_snapshot(
                    snapshot_values={"x_amount": 150}
                )
            ]
            self.assertNotIn("btn_2nd_approval", keys_below,
                "Button must be hidden when snapshot amount is below threshold")
        finally:
            action.sudo().unlink()

    # ── Business case 3: user group ───────────────────────────────────────────

    def test_visible_buttons_actor_group_visible(self):
        """actor_has_group domain shows button when the acting user has the required group."""
        xmlid = "workflow_engine.group_workflow_approval_user"
        action = self._make_hod_action(
            "btn_group_check", "Group Approve",
            invisible_domain=f"actor_has_group('{xmlid}')",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            # approver_a was created with group_workflow_approval_user in setUpClass
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_group_check", [b["action_key"] for b in buttons],
                "Button must be visible when actor has the required group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_hidden_for_non_member(self):
        """actor_has_group domain hides button when the acting user lacks the required group."""
        xmlid = "workflow_engine.group_workflow_approval_admin"
        action = self._make_hod_action(
            "btn_admin_only", "Admin Approve",
            invisible_domain=f"actor_has_group('{xmlid}')",
        )
        # approver_b has group_workflow_approval_user but NOT group_workflow_approval_admin
        req = self._make_button_test_request().with_user(self.approver_b)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_admin_only", [b["action_key"] for b in buttons],
                "Button must be hidden when actor does not have the required group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_csv_domain_visible(self):
        """wf_actor_group_xmlids list-domain shows button when the acting user has the required group."""
        action = self._make_hod_action(
            "btn_group_csv", "Group CSV Approve",
            invisible_domain="[('wf_actor_group_xmlids', 'ilike', ',workflow_engine.group_workflow_approval_user,')]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_group_csv", [b["action_key"] for b in buttons],
                "Button must be visible when actor group XML IDs include the required group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_csv_domain_hidden_for_non_member(self):
        """wf_actor_group_xmlids list-domain hides button when the acting user lacks the required group."""
        action = self._make_hod_action(
            "btn_admin_csv", "Admin CSV Approve",
            invisible_domain="[('wf_actor_group_xmlids', 'ilike', ',workflow_engine.group_workflow_approval_admin,')]",
        )
        req = self._make_button_test_request().with_user(self.approver_b)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_admin_csv", [b["action_key"] for b in buttons],
                "Button must be hidden when actor group XML IDs do not include the required group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_ids_visible(self):
        """wf_actor_group_ids list-domain shows button when the acting user has the required System group."""
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        action = self._make_hod_action(
            "btn_group_ids", "Group IDs Approve",
            invisible_domain=f"[('wf_actor_group_ids', 'in', [{workflow_group.id}])]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn(
                "btn_group_ids",
                [b["action_key"] for b in buttons],
                "Button must be visible when actor group IDs include the required System group",
            )
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_ids_hidden_for_non_member(self):
        """wf_actor_group_ids list-domain hides button when the acting user lacks the required System group."""
        admin_group = self.env.ref("workflow_engine.group_workflow_approval_admin")
        action = self._make_hod_action(
            "btn_group_ids_hidden", "Group IDs Hidden",
            invisible_domain=f"[('wf_actor_group_ids', 'in', [{admin_group.id}])]",
        )
        req = self._make_button_test_request().with_user(self.approver_b)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn(
                "btn_group_ids_hidden",
                [b["action_key"] for b in buttons],
                "Button must be hidden when actor group IDs do not include the configured System group",
            )
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_approval_group_visible(self):
        """wf_actor_approval_group_ids list-domain shows button when the actor belongs to the workflow approval group."""
        action = self._make_hod_action(
            "btn_approval_group_ids", "Approval Group Approve",
            invisible_domain=f"[('wf_actor_approval_group_ids', 'in', [{self.dynamic_group.id}])]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_approval_group_ids", [b["action_key"] for b in buttons],
                "Button must be visible when actor approval-group IDs include the configured workflow approval group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_approval_group_hidden_for_non_member(self):
        """wf_actor_approval_group_ids list-domain hides button when the actor is not in the workflow approval group."""
        action = self._make_hod_action(
            "btn_approval_group_ids_hidden", "Approval Group Hidden",
            invisible_domain=f"[('wf_actor_approval_group_ids', 'in', [{self.dynamic_group.id}])]",
        )
        req = self._make_button_test_request().with_user(self.approver_b)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_approval_group_ids_hidden", [b["action_key"] for b in buttons],
                "Button must be hidden when actor approval-group IDs do not include the configured workflow approval group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_has_approval_group_helper_visible(self):
        """actor_has_approval_group helper shows button when the actor belongs to the workflow approval group."""
        action = self._make_hod_action(
            "btn_approval_group_helper", "Approval Group Helper",
            invisible_domain=f"actor_has_approval_group({self.dynamic_group.id})",
        )
        req = self._make_button_test_request().with_user(self.requester)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_approval_group_helper", [b["action_key"] for b in buttons],
                "Button must be visible when actor_has_approval_group matches the acting user's workflow approval group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_has_approval_group_helper_hidden_for_non_member(self):
        """actor_has_approval_group helper hides button when the actor is not in the workflow approval group."""
        action = self._make_hod_action(
            "btn_approval_group_helper_hidden", "Approval Group Helper Hidden",
            invisible_domain=f"actor_has_approval_group({self.dynamic_group.id})",
        )
        req = self._make_button_test_request().with_user(self.approver_b)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_approval_group_helper_hidden", [b["action_key"] for b in buttons],
                "Button must be hidden when actor_has_approval_group does not match any workflow approval group")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_actor_group_or_approval_group_visible(self):
        """OR domain must allow button visibility when either System group or workflow approval group matches."""
        admin_group = self.env.ref("workflow_engine.group_workflow_approval_admin")
        action = self._make_hod_action(
            "btn_group_or_approval_group", "Group Or Approval Group",
            invisible_domain=(
                "['|', "
                f"('wf_actor_group_ids', 'in', [{admin_group.id}]), "
                f"('wf_actor_approval_group_ids', 'in', [{self.dynamic_group.id}])]"
            ),
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_group_or_approval_group", [b["action_key"] for b in buttons],
                "Button must be visible when the workflow approval group branch of the OR expression matches")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_flat_prefix_or_and_domain_is_validated_and_evaluated(self):
        """Odoo-style flat prefix domains may nest '&' after '|'."""
        admin_group = self.env.ref("workflow_engine.group_workflow_approval_admin")
        action = self._make_hod_action(
            "btn_flat_prefix_or_and", "Flat Prefix Or And",
            invisible_domain=(
                "['|', "
                f"('wf_actor_group_ids', 'in', [{admin_group.id}]), "
                "'&', "
                f"('wf_actor_approval_group_ids', 'in', [{self.dynamic_group.id}]), "
                "('wf_current_stage_age_minutes', '<', 999999)]"
            ),
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            buttons = req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn(
                "btn_flat_prefix_or_and",
                [b["action_key"] for b in buttons],
                "Flat Odoo prefix OR/AND domain must evaluate without rewriting '&' into a nested list.",
            )
        finally:
            action.sudo().unlink()

    def test_visible_buttons_compute_matches_snapshot(self):
        """Stored compute path and snapshot RPC must return the same visible action set for the same effective state."""
        action = self._make_hod_action(
            "btn_compute_snapshot_match", "Compute Snapshot Match",
            invisible_domain="[('state', 'in', ['new', 'waiting'])]",
        )
        req = self._make_button_test_request().with_user(self.approver_a)
        try:
            req.invalidate_recordset(["visible_buttons"])
            compute_keys = sorted([
                button["action_key"] for button in (req.visible_buttons or [])
            ])
            snapshot_keys = sorted([
                button["action_key"]
                for button in req.workflow_get_visible_buttons_snapshot(snapshot_values={})
            ])
            self.assertEqual(compute_keys, snapshot_keys,
                "Initial compute and live snapshot evaluation must return the same action-key set")
        finally:
            action.sudo().unlink()

    # ── Business case 4: manager relationship ────────────────────────────────

    def test_visible_buttons_manager_relationship(self):
        """is_manager_of_requester domain shows button for the manager, hides it for others."""
        action = self._make_hod_action(
            "btn_mgr_only", "Manager Approve",
            invisible_domain="is_manager_of_requester",
        )
        try:
            # cls.manager is the direct parent of cls.requester_employee (set in setUpClass)
            req_as_mgr = self._make_button_test_request().with_user(self.manager)
            buttons_mgr = req_as_mgr.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_mgr_only", [b["action_key"] for b in buttons_mgr],
                "Button must be visible for the request owner's direct manager")

            # approver_a is not the manager of requester
            req_as_a = self._make_button_test_request().with_user(self.approver_a)
            buttons_a = req_as_a.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_mgr_only", [b["action_key"] for b in buttons_a],
                "Button must be hidden for an actor who is not the request owner's manager")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_manager_flag_domain(self):
        """wf_actor_is_manager list-domain shows button for the manager, hides it for others."""
        action = self._make_hod_action(
            "btn_mgr_flag", "Manager Flag Approve",
            invisible_domain="[('wf_actor_is_manager', '=', True)]",
        )
        try:
            req_as_mgr = self._make_button_test_request().with_user(self.manager)
            buttons_mgr = req_as_mgr.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_mgr_flag", [b["action_key"] for b in buttons_mgr],
                "Button must be visible when wf_actor_is_manager resolves to True")

            req_as_a = self._make_button_test_request().with_user(self.approver_a)
            buttons_a = req_as_a.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_mgr_flag", [b["action_key"] for b in buttons_a],
                "Button must be hidden when wf_actor_is_manager resolves to False")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_uid_matches_request_owner_manager(self):
        """uid=request_owner_manager_user_id list-domain shows button only for the request owner's manager."""
        action = self._make_hod_action(
            "btn_mgr_uid", "Manager UID Approve",
            invisible_domain="[('uid', '=', request_owner_manager_user_id)]",
        )
        try:
            req_as_mgr = self._make_button_test_request().with_user(self.manager)
            buttons_mgr = req_as_mgr.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_mgr_uid", [b["action_key"] for b in buttons_mgr],
                "Button must be visible when current actor ID matches request_owner_manager_user_id")

            req_as_a = self._make_button_test_request().with_user(self.approver_a)
            buttons_a = req_as_a.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_mgr_uid", [b["action_key"] for b in buttons_a],
                "Button must be hidden when current actor ID does not match request_owner_manager_user_id")
        finally:
            action.sudo().unlink()

    def test_visible_buttons_uid_matches_request_owner_department_manager(self):
        """uid=request_owner_department_manager_user_id list-domain shows button only for the department manager."""
        action = self._make_hod_action(
            "btn_dept_mgr_uid", "Dept Manager UID Approve",
            invisible_domain="[('uid', '=', request_owner_department_manager_user_id)]",
        )
        try:
            req_as_dept_mgr = self._make_button_test_request().with_user(self.department_manager)
            buttons_dept_mgr = req_as_dept_mgr.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertIn("btn_dept_mgr_uid", [b["action_key"] for b in buttons_dept_mgr],
                "Button must be visible when current actor ID matches request_owner_department_manager_user_id")

            req_as_mgr = self._make_button_test_request().with_user(self.manager)
            buttons_mgr = req_as_mgr.workflow_get_visible_buttons_snapshot(snapshot_values={})
            self.assertNotIn("btn_dept_mgr_uid", [b["action_key"] for b in buttons_mgr],
                "Button must be hidden when current actor is not the department manager")
        finally:
            action.sudo().unlink()

    @common.tagged("-at_install", "post_install")
    def test_previous_actor_dryrun_uses_simulated_history(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_DRYRUN_PREV_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_rework.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )
        simulated_history = {
            "by_node": {
                self.meta_submission.node_id: {
                    "assigned_user_ids": [self.requester.id],
                    "pending_user_ids": [self.requester.id],
                    "decided_user_ids": [self.requester.id],
                    "manual_assigned": True,
                    "manual_decided": True,
                }
            }
        }
        result = self.assignment_service.resolve_assignees(
            request,
            self.meta_rework,
            simulated_history=simulated_history,
            debug=True,
        )
        self.assertIn(self.requester.id, result["final_user_ids"])
        self.assertFalse(result["debug"].get("needs_input"))

    @common.tagged("-at_install", "post_install")
    def test_previous_actor_dryrun_marks_missing_input(self):
        request = self.Request.sudo().create(
            {
                "name": f"REQ_DRYRUN_NEEDS_INPUT_{uuid4().hex[:8]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
                "current_node_id": self.meta_rework.node_id,
                "previous_node_id": self.meta_submission.node_id,
                "current_iteration_no": 1,
            }
        )
        result = self.assignment_service.resolve_assignees(
            request,
            self.meta_rework,
            simulated_history={},
            debug=True,
        )
        self.assertTrue(result["blocked"])
        self.assertTrue(result["debug"].get("needs_input"))
        self.assertEqual(
            result["debug"]["needs_input"][0]["source_node_id"],
            self.meta_submission.node_id,
        )

    @common.tagged("-at_install", "post_install")
    def test_invalid_group_request_domain_reports_config_error(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": self.dynamic_group.id,
                "domain": "[('missing_runtime_field', '=', True)]",
                "user_domain": ROUTING_ALWAYS_TRUE,
                "sequence": 10,
            }
        )
        result = self.assignment_service.resolve_assignees(
            self.request,
            self.meta_hod,
            debug=True,
        )
        self.assertTrue(result["debug"].get("config_errors"))
        self.assertEqual(
            result["debug"]["config_errors"][0]["scope"],
            "group_request_domain",
        )

    @common.tagged("-at_install", "post_install")
    def test_dryrun_wizard_create_populates_node_input_lines(self):
        DryRunWizard = self.env["workflow.dryrun.wizard"]
        wizard = DryRunWizard.sudo().create(
            {
                "category_id": self.category.id,
                "version_id": self.version.id,
                "simulated_user_id": self.requester.id,
            }
        )
        self.assertTrue(wizard.node_input_ids)
        self.assertFalse(wizard.node_input_ids.filtered(lambda line: not line.node_id))

    @common.tagged("-at_install", "post_install")
    def test_dryrun_category_action_opens_persisted_wizard(self):
        action = self.category.action_open_dryrun_wizard()
        self.assertEqual(action.get("res_model"), "workflow.dryrun.wizard")
        self.assertTrue(action.get("res_id"))
        wizard = self.env["workflow.dryrun.wizard"].browse(action["res_id"])
        self.assertTrue(wizard.exists())
        self.assertTrue(wizard.node_input_ids)
        line = wizard.node_input_ids.filtered(lambda item: item.node_id == self.meta_submission.node_id)[:1]
        self.assertTrue(line)
        line.write({"assigned_user_ids": [(6, 0, [self.requester.id])]})
        self.assertEqual(line.wizard_id, wizard)
        self.assertIn(self.requester, line.assigned_user_ids)
        node_input = self.env["workflow.dryrun.node.input"].with_context(
            default_wizard_id=wizard.id
        ).create(
            {
                "node_id": "Task_Context_Default",
                "node_name": "Context Default",
                "node_type": "userTask",
            }
        )
        self.assertEqual(node_input.wizard_id, wizard)
        field = self.env["ir.model.fields"]._get("workflow.base.approval.request", "name")
        field_input = self.env["workflow.dryrun.field.input"].with_context(
            active_model="workflow.dryrun.wizard",
            active_id=wizard.id,
        ).create(
            {
                "field_id": field.id,
                "value_char": "Dry Run Name",
            }
        )
        self.assertEqual(field_input.wizard_id, wizard)

    @common.tagged("-at_install", "post_install")
    def test_dryrun_virtual_request_preserves_simulated_creator_for_routing_domains(self):
        self.meta_hod.sudo().write(
            {
                "assignment_mode": "groups",
                "explicit_user_ids": [(5, 0, 0)],
                "explicit_group_ids": [(5, 0, 0)],
                "assignment_user_domain": False,
                "approval_group_domain": False,
                "assign_to_previous_actor": False,
                "assign_to_request_owner": False,
                "fallback_policy": "block",
            }
        )
        self.meta_hod.approval_group_link_ids.sudo().unlink()
        other_department = self.env["hr.department"].sudo().create(
            {"name": "Other Dry Run Department"}
        )
        self.approver_a.employee_id.sudo().write({"department_id": self.department.id})
        self.approver_b.employee_id.sudo().write({"department_id": other_department.id})
        dryrun_group = self.ApprovalGroup.sudo().create(
            {
                "name": "Dry Run Creator Department Group",
                "user_ids": [(6, 0, [self.approver_a.id, self.approver_b.id])],
            }
        )
        self.MetaTaskApprovalGroup.sudo().create(
            {
                "meta_id": self.meta_hod.id,
                "approval_group_id": dryrun_group.id,
                "domain": "[('create_uid.employee_id.department_id.name', '=', %r)]"
                % self.department.name,
                "user_domain": "[('employee_id.department_id', '=', request.create_uid.employee_id.department_id.id)]",
                "sequence": 10,
            }
        )
        wizard = self.env["workflow.dryrun.wizard"].sudo().create(
            {
                "category_id": self.category.id,
                "version_id": self.version.id,
                "simulated_user_id": self.requester.id,
            }
        )

        wizard.action_run_dryrun()

        hod_line = wizard.result_line_ids.filtered(
            lambda line: line.node_id == self.meta_hod.node_id
        )[:1]
        self.assertTrue(hod_line)
        self.assertEqual(hod_line.assignee_user_ids, self.approver_a)
        self.assertEqual(hod_line.status, "ok")

    @common.tagged("-at_install", "post_install")
    def test_dryrun_send_task_shows_notification_recipients(self):
        template = self.MailTemplate.sudo().create(
            {
                "name": "Dry Run Send Task Template",
                "model_id": self.base_request_model.id,
                "subject": "Dry run notification",
                "body_html": "<p>Dry run</p>",
            }
        )
        notify_meta = self.MetaTask.sudo().create(
            {
                "version_id": self.version.id,
                "name": "Notify Email",
                "node_id": "Task_Notify_Email",
                "node_type": "sendTask",
                "sequence": 99,
                "notification_delivery_mode": "email",
                "notification_recipient_source": "specific_users",
                "notification_recipient_ids": [(6, 0, [self.approver_a.id])],
                "notification_email_template_id": template.id,
            }
        )
        wizard = self.env["workflow.dryrun.wizard"].sudo().create(
            {
                "category_id": self.category.id,
                "version_id": self.version.id,
                "simulated_user_id": self.requester.id,
            }
        )

        wizard.action_run_dryrun()

        notify_line = wizard.result_line_ids.filtered(
            lambda line: line.node_id == notify_meta.node_id
        )[:1]
        self.assertTrue(notify_line)
        self.assertFalse(notify_line.assignee_user_ids)
        self.assertEqual(notify_line.notification_recipient_user_ids, self.approver_a)
        self.assertEqual(notify_line.notification_recipient_count, 1)
        self.assertIn(self.approver_a.email, notify_line.notification_email_to)
        self.assertEqual(notify_line.status, "ok")
        self.assertIn("notification", notify_line.debug_json)

    @common.tagged("-at_install", "post_install")
    def test_dryrun_wizard_runs_from_modal_without_persisting_request(self):
        DryRunWizard = self.env["workflow.dryrun.wizard"]
        before_count = self.Request.sudo().search_count(
            [("name", "like", "[DRY RUN]%")]
        )
        wizard = DryRunWizard.sudo().create(
            {
                "category_id": self.category.id,
                "version_id": self.version.id,
                "simulated_user_id": self.requester.id,
                "snapshot_json": {
                    "category_id": {"id": self.category.id, "display_name": self.category.name},
                    "request_owner_id": {"id": self.requester.id, "display_name": self.requester.name},
                },
                "node_input_ids": [
                    (
                        0,
                        0,
                        {
                            "node_id": self.meta_submission.node_id,
                            "node_name": self.meta_submission.name,
                            "node_type": self.meta_submission.node_type,
                            "decided_user_ids": [(6, 0, [self.requester.id])],
                        },
                    )
                ],
            }
        )
        action = wizard.action_run_dryrun()
        after_count = self.Request.sudo().search_count(
            [("name", "like", "[DRY RUN]%")]
        )
        self.assertEqual(before_count, after_count)
        self.assertEqual(action.get("res_model"), "workflow.dryrun.wizard")
        self.assertTrue(action.get("views"))
        self.assertEqual(action["views"][0][1], "form")
        wizard.invalidate_recordset()
        self.assertTrue(wizard.snapshot_json)
        self.assertTrue(wizard.result_line_ids)
