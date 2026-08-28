# -*- coding: utf-8 -*-

from datetime import timedelta
from uuid import uuid4

from odoo import Command, fields
from odoo.addons.web.controllers.utils import get_action_triples
from odoo.tests import tagged
from odoo.tests.common import HttpCase
from odoo.addons.base.tests.common import HttpCaseWithUserDemo
from odoo.tools.safe_eval import safe_eval


RUNTIME_V2_NURSE_VERIFY_UI_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:custom="http://example.com/schema/custom"
    id="Definitions_RuntimeV2Ui"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_RuntimeV2Ui" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_Start_To_NurseVerify</bpmn:outgoing>
    </bpmn:startEvent>

    <bpmn:userTask id="Task_NurseVerify" name="Nurse Verify">
      <bpmn:incoming>Flow_Start_To_NurseVerify</bpmn:incoming>
      <bpmn:outgoing>Flow_NurseVerify_To_Done</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:intermediateThrowEvent id="Event_Done" name="Done">
      <bpmn:incoming>Flow_NurseVerify_To_Done</bpmn:incoming>
      <bpmn:outgoing>Flow_Done_To_Gateway</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>

    <bpmn:parallelGateway id="Gateway_AfterDone">
      <bpmn:incoming>Flow_Done_To_Gateway</bpmn:incoming>
      <bpmn:outgoing>Flow_Gateway_To_Email</bpmn:outgoing>
      <bpmn:outgoing>Flow_Gateway_To_Medicine</bpmn:outgoing>
      <bpmn:outgoing>Flow_Gateway_To_Blue</bpmn:outgoing>
      <bpmn:outgoing>Flow_Gateway_To_OnGoing</bpmn:outgoing>
    </bpmn:parallelGateway>

    <bpmn:sendTask id="Task_EmailNotify" name="Email Notify">
      <bpmn:incoming>Flow_Gateway_To_Email</bpmn:incoming>
    </bpmn:sendTask>

    <bpmn:serviceTask id="Task_MedicineStockOut" name="Send medicine stock out">
      <bpmn:incoming>Flow_Gateway_To_Medicine</bpmn:incoming>
    </bpmn:serviceTask>

    <bpmn:serviceTask id="Task_SyncBlue" name="Sync with blue">
      <bpmn:incoming>Flow_Gateway_To_Blue</bpmn:incoming>
    </bpmn:serviceTask>

    <bpmn:userTask id="Task_OnGoing" name="On Going">
      <bpmn:incoming>Flow_Gateway_To_OnGoing</bpmn:incoming>
      <bpmn:outgoing>Flow_OnGoing_To_GoNurse</bpmn:outgoing>
      <bpmn:outgoing>Flow_OnGoing_To_GoDoctor</bpmn:outgoing>
      <bpmn:outgoing>Flow_OnGoing_To_Timer</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:intermediateThrowEvent id="Event_GoToNurse" name="Go to Nurse">
      <bpmn:incoming>Flow_OnGoing_To_GoNurse</bpmn:incoming>
      <bpmn:outgoing>Flow_GoNurse_To_Rework</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>

    <bpmn:userTask id="Task_NurseRework" name="Nurse Rework">
      <bpmn:incoming>Flow_GoNurse_To_Rework</bpmn:incoming>
      <bpmn:outgoing>Flow_NurseRework_To_Submit</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:intermediateThrowEvent id="Event_SubmitFromNurse" name="Submit">
      <bpmn:incoming>Flow_NurseRework_To_Submit</bpmn:incoming>
      <bpmn:outgoing>Flow_SubmitNurse_To_NurseVerify</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>

    <bpmn:intermediateThrowEvent id="Event_GoToDoctor" name="Go to Doctor">
      <bpmn:incoming>Flow_OnGoing_To_GoDoctor</bpmn:incoming>
      <bpmn:outgoing>Flow_GoDoctor_To_Rework</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>

    <bpmn:userTask id="Task_DoctorRework" name="Doctor Rework">
      <bpmn:incoming>Flow_GoDoctor_To_Rework</bpmn:incoming>
      <bpmn:outgoing>Flow_DoctorRework_To_Submit</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:intermediateThrowEvent id="Event_SubmitFromDoctor" name="Submit">
      <bpmn:incoming>Flow_DoctorRework_To_Submit</bpmn:incoming>
      <bpmn:outgoing>Flow_SubmitDoctor_To_NurseVerify</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>

    <bpmn:intermediateCatchEvent id="Event_Timer_1Week" name="Allow admin to edit for 1 week">
      <bpmn:incoming>Flow_OnGoing_To_Timer</bpmn:incoming>
      <bpmn:outgoing>Flow_Timer_To_Approved</bpmn:outgoing>
      <bpmn:timerEventDefinition id="TimerDefinition_1Week"/>
    </bpmn:intermediateCatchEvent>

    <bpmn:endEvent id="End_Approved" name="Approved">
      <bpmn:incoming>Flow_Timer_To_Approved</bpmn:incoming>
    </bpmn:endEvent>

    <bpmn:sequenceFlow id="Flow_Start_To_NurseVerify" sourceRef="StartEvent_1" targetRef="Task_NurseVerify"/>
    <bpmn:sequenceFlow id="Flow_NurseVerify_To_Done" sourceRef="Task_NurseVerify" targetRef="Event_Done"/>
    <bpmn:sequenceFlow id="Flow_Done_To_Gateway" sourceRef="Event_Done" targetRef="Gateway_AfterDone"/>
    <bpmn:sequenceFlow id="Flow_Gateway_To_Email" sourceRef="Gateway_AfterDone" targetRef="Task_EmailNotify"/>
    <bpmn:sequenceFlow id="Flow_Gateway_To_Medicine" sourceRef="Gateway_AfterDone" targetRef="Task_MedicineStockOut"/>
    <bpmn:sequenceFlow id="Flow_Gateway_To_Blue" sourceRef="Gateway_AfterDone" targetRef="Task_SyncBlue"/>
    <bpmn:sequenceFlow id="Flow_Gateway_To_OnGoing" sourceRef="Gateway_AfterDone" targetRef="Task_OnGoing"/>
    <bpmn:sequenceFlow id="Flow_OnGoing_To_GoNurse" sourceRef="Task_OnGoing" targetRef="Event_GoToNurse"/>
    <bpmn:sequenceFlow id="Flow_GoNurse_To_Rework" sourceRef="Event_GoToNurse" targetRef="Task_NurseRework"/>
    <bpmn:sequenceFlow id="Flow_NurseRework_To_Submit" sourceRef="Task_NurseRework" targetRef="Event_SubmitFromNurse"/>
    <bpmn:sequenceFlow id="Flow_SubmitNurse_To_NurseVerify" sourceRef="Event_SubmitFromNurse" targetRef="Task_NurseVerify"/>
    <bpmn:sequenceFlow id="Flow_OnGoing_To_GoDoctor" sourceRef="Task_OnGoing" targetRef="Event_GoToDoctor"/>
    <bpmn:sequenceFlow id="Flow_GoDoctor_To_Rework" sourceRef="Event_GoToDoctor" targetRef="Task_DoctorRework"/>
    <bpmn:sequenceFlow id="Flow_DoctorRework_To_Submit" sourceRef="Task_DoctorRework" targetRef="Event_SubmitFromDoctor"/>
    <bpmn:sequenceFlow id="Flow_SubmitDoctor_To_NurseVerify" sourceRef="Event_SubmitFromDoctor" targetRef="Task_NurseVerify"/>
    <bpmn:sequenceFlow id="Flow_OnGoing_To_Timer" sourceRef="Task_OnGoing" targetRef="Event_Timer_1Week"/>
    <bpmn:sequenceFlow id="Flow_Timer_To_Approved" sourceRef="Event_Timer_1Week" targetRef="End_Approved"/>
  </bpmn:process>
</bpmn:definitions>
"""

SMOKE_CREATE_VISIBLE_CATEGORY = "Workflow Smoke Create Visible"
SMOKE_READ_ONLY_VISIBLE_CATEGORY = "Workflow Smoke Read Only Visible"


@tagged('-at_install', 'post_install')
class TestUi(HttpCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        workflow_admin_group = cls.env.ref("workflow_engine.group_workflow_approval_admin")
        workflow_technical_group = cls.env.ref("workflow_engine.group_workflow_technical_admin")
        internal_group = cls.env.ref("base.group_user")
        system_group = cls.env.ref("base.group_system")
        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        unique = uuid4().hex[:8]

        cls.smoke_admin_login = f"wf_smoke_admin_{unique}"
        cls.smoke_admin_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": f"Workflow Smoke Admin {unique}",
                "login": cls.smoke_admin_login,
                "password": cls.smoke_admin_login,
                "email": f"{cls.smoke_admin_login}@example.com",
                "group_ids": [
                    Command.set(
                        [
                            internal_group.id,
                            workflow_group.id,
                            workflow_admin_group.id,
                            workflow_technical_group.id,
                            system_group.id,
                        ]
                    )
                ],
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
            }
        )
        cls.smoke_creator_login = f"wf_smoke_creator_{unique}"
        cls.smoke_creator_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": f"Workflow Smoke Creator {unique}",
                "login": cls.smoke_creator_login,
                "password": cls.smoke_creator_login,
                "email": f"{cls.smoke_creator_login}@example.com",
                "group_ids": [Command.set([internal_group.id, workflow_group.id])],
                "company_id": cls.env.company.id,
                "company_ids": [Command.set([cls.env.company.id])],
            }
        )
        cls.smoke_category = cls.env["workflow.approval.category"].sudo().create(
            {
                "name": f"{SMOKE_CREATE_VISIBLE_CATEGORY} {unique}",
                "res_model": base_request_model.id,
                "zero_trust_enforced": True,
                "allow_requester_read": True,
                "create_access_mode": "restricted",
                "create_allowed_group_ids": [Command.set([workflow_group.id])],
            }
        )
        cls.smoke_version = cls.env["workflow.approval.category.version"].sudo().create(
            {
                "name": f"smoke_v1_{unique}",
                "title": "Smoke Version",
                "category_id": cls.smoke_category.id,
                "is_active": True,
            }
        )
        cls.smoke_category.sudo().write({"active_version_id": cls.smoke_version.id})
        cls.smoke_read_only_category = cls.env["workflow.approval.category"].sudo().create(
            {
                "name": f"{SMOKE_READ_ONLY_VISIBLE_CATEGORY} {unique}",
                "res_model": base_request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [Command.set([cls.smoke_creator_user.id])],
                "create_access_mode": "restricted",
            }
        )
        cls.smoke_request = cls.env["workflow.base.approval.request"].sudo().create(
            {
                "name": f"Workflow Smoke Request {unique}",
                "category_id": cls.smoke_category.id,
                "request_owner_id": cls.smoke_creator_user.id,
                "state": "new",
                "request_status": "new",
            }
        )

    def test_workflow_dashboard_smoke(self):
        self.start_tour("/odoo?debug=tests", "workflow_engine_smoke_tour", login=self.smoke_admin_login)

    def test_workflow_predeploy_route_smoke(self):
        route_paths = [
            "my-workflow-dashboard",
            "my-work-list",
            "my-contribute-list",
            "my-request-list",
            "approval-request-report",
            "approvals-report",
            f"approvals-report/{self.smoke_category.id}/m-workflow.base.approval.request",
        ]
        user_env = self.env(user=self.smoke_admin_user.id)
        for route_path in route_paths:
            with self.subTest(route_path=route_path):
                self._assert_action_route_loads(user_env, route_path)

    def _assert_action_route_loads(self, user_env, route_path):
        active_id, action, record_id = list(get_action_triples(user_env, route_path))[-1]
        action = action.sudo()
        self.assertEqual(action._name, "ir.actions.act_window")
        self.assertIn(action.res_model, user_env)

        context = dict(user_env.context)
        eval_context = dict(
            action._get_eval_context(action),
            active_id=active_id,
            context=context,
            allowed_company_ids=user_env.user.company_ids.ids,
        )
        context.update(safe_eval(action.context or "{}", eval_context))
        model = user_env[action.res_model].with_context(context)

        view_id, view_type = action.views[0]
        if record_id:
            view_type = "form"
        model.get_view(view_id or False, view_type)

        if record_id:
            self.assertTrue(model.browse(record_id).exists())
            return
        domain = safe_eval(action.domain or "[]", eval_context)
        model.search(domain, limit=1)

    def test_workflow_creator_group_can_see_create_category_on_dashboard(self):
        self.start_tour(
            "/odoo/my-workflow-dashboard?debug=tests",
            "workflow_engine_predeploy_creator_dashboard_tour",
            login=self.smoke_creator_login,
            timeout=180,
        )


@tagged("-at_install", "post_install")
class TestWorkflowRuntimeV2Ui(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.MetaTask = cls.env["workflow.category.version.meta.task"]
        cls.MetaAction = cls.env["workflow.category.version.meta.task.action"]
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.Approver = cls.env["workflow.approval.approver"]
        cls.WorkflowAction = cls.env["workflow.approval.action"]
        cls.AutomationInstance = cls.env["workflow.request.automation.instance"]
        cls.PermissionService = cls.env["workflow.engine.permission.service"]
        cls.AssignmentService = cls.env["workflow.engine.assignment.service"]

        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        internal_group = cls.env.ref("base.group_user")
        unique = uuid4().hex[:8]
        cls.child_model_record = cls.env["ir.model"].sudo().create(
            {
                "name": f"Workflow Runtime V2 UI Request {unique}",
                "model": f"x_wf_runtime_v2_ui_{unique}",
                "state": "manual",
            }
        )
        cls.child_model_record.sudo().write({"is_approval": True})
        cls.child_model_record.sudo()._workflow_sync_child_request_reader_security()
        cls.child_model_name = cls.child_model_record.model

        def _new_user(role):
            login = f"wf_ui_{role}_{unique}"
            return cls.env["res.users"].with_context(no_reset_password=True).create(
                {
                    "name": f"Workflow UI {role.title()} {unique}",
                    "login": login,
                    "password": login,
                    "email": f"{login}@example.com",
                    "group_ids": [(6, 0, [internal_group.id, workflow_group.id])],
                    "company_id": cls.env.company.id,
                    "company_ids": [Command.set([cls.env.company.id])],
                }
            )

        cls.requester_user = _new_user("requester")
        cls.nurse_user = _new_user("nurse")
        cls.doctor_user = _new_user("doctor")

        cls.category = cls.Category.sudo().create(
            {
                "name": f"UI Runtime V2 {unique}",
                "res_model": cls.child_model_record.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [
                    Command.set(
                        [
                            cls.requester_user.id,
                            cls.nurse_user.id,
                            cls.doctor_user.id,
                        ]
                    )
                ],
            }
        )
        cls.version = cls.Version.sudo().create(
            {
                "name": f"ui_v2_{unique}",
                "category_id": cls.category.id,
                "is_active": True,
                "execution_profile": "runtime_v2",
                "bpmn_xml": RUNTIME_V2_NURSE_VERIFY_UI_BPMN,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})

        def _meta_task(node_id):
            return cls.version.meta_task_ids.filtered(lambda task: task.node_id == node_id)[:1]

        def _meta_action(source_id, label):
            return cls.version.meta_task_ids.mapped("meta_action_ids").filtered(
                lambda action: action.source_id == source_id and action.attr_label == label
            )[:1]

        cls.meta_start = _meta_task("StartEvent_1")
        cls.meta_nurse_verify = _meta_task("Task_NurseVerify")
        cls.meta_email_notify = _meta_task("Task_EmailNotify")
        cls.meta_medicine_stock = _meta_task("Task_MedicineStockOut")
        cls.meta_sync_blue = _meta_task("Task_SyncBlue")
        cls.meta_on_going = _meta_task("Task_OnGoing")
        cls.meta_nurse_rework = _meta_task("Task_NurseRework")
        cls.meta_doctor_rework = _meta_task("Task_DoctorRework")

        cls.meta_nurse_verify.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [Command.set([cls.nurse_user.id])],
                "fallback_policy": "block",
            }
        )
        cls.meta_on_going.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [Command.set([cls.doctor_user.id])],
                "fallback_policy": "block",
            }
        )
        cls.meta_nurse_rework.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [Command.set([cls.nurse_user.id])],
                "fallback_policy": "block",
            }
        )
        cls.meta_doctor_rework.sudo().write(
            {
                "assignment_mode": "explicit_users",
                "explicit_user_ids": [Command.set([cls.doctor_user.id])],
                "fallback_policy": "block",
            }
        )

        cls.email_action = cls.WorkflowAction.sudo().create(
            {
                "name": f"UI Runtime Email Notify {unique}",
                "action_type": "log",
                "version_id": cls.version.id,
            }
        )
        cls.medicine_action = cls.WorkflowAction.sudo().create(
            {
                "name": f"UI Runtime Medicine Stock {unique}",
                "action_type": "server_action",
                "version_id": cls.version.id,
            }
        )
        cls.sync_blue_action = cls.WorkflowAction.sudo().create(
            {
                "name": f"UI Runtime Sync Blue {unique}",
                "action_type": "server_action",
                "version_id": cls.version.id,
            }
        )

        cls.meta_email_notify.sudo().write(
            {
                "notification_recipient_ids": [Command.set([cls.doctor_user.id])],
                "activity_type_ids": [Command.set([cls.email_action.id])],
            }
        )
        cls.meta_medicine_stock.sudo().write(
            {
                "service_behavior": "executor",
                "activity_type_ids": [Command.set([cls.medicine_action.id])],
            }
        )
        cls.meta_sync_blue.sudo().write(
            {
                "service_behavior": "executor",
                "activity_type_ids": [Command.set([cls.sync_blue_action.id])],
            }
        )

        cls.done_action = _meta_action("Task_NurseVerify", "Done")
        cls.go_to_nurse_action = _meta_action("Task_OnGoing", "Go to Nurse")
        cls.go_to_doctor_action = _meta_action("Task_OnGoing", "Go to Doctor")
        (cls.done_action | cls.go_to_nurse_action | cls.go_to_doctor_action).sudo().write(
            {
                "show_confirm_dialog": False,
                "require_reason": False,
                "comment_required": False,
            }
        )

        cls.request = cls.Request.sudo().create(
            {
                "name": f"UI Runtime Request {unique}",
                "category_id": cls.category.id,
                "request_owner_id": cls.requester_user.id,
                "current_node_id": cls.meta_nurse_verify.node_id,
                "previous_node_id": cls.meta_start.node_id,
                "current_activity_name": cls.meta_nurse_verify.name,
                "previous_activity_name": cls.meta_start.name,
                "current_iteration_no": 1,
                "state": "waiting",
                "request_status": "pending",
            }
        )
        cls.child_request = cls.env[cls.child_model_name].sudo().with_context(
            workflow_skip_create_autorun=True
        ).create(
            {
                "x_approval_base_id": cls.request.id,
            }
        )
        cls.Approver.sudo().create(
            {
                "user_id": cls.nurse_user.id,
                "request_id": cls.request.id,
                "current_meta_id": cls.meta_nurse_verify.id,
                "previous_meta_id": cls.meta_start.id,
                "status": "new",
                "required": True,
                "iteration_no": 1,
            }
        )
        cls.AssignmentService.create_or_sync_task_instance_from_legacy(
            request_record=cls.request,
            meta_task=cls.meta_nurse_verify,
            previous_meta_task=cls.meta_start,
            iteration_no=1,
        )

        cls.request_action = cls.env.ref("workflow_engine.all_requests_action_window")
        cls.request_form_url = f"/odoo/action-{cls.request_action.id}/{cls.request.id}?debug=tests"

    def _fresh_request(self):
        self.env.invalidate_all()
        return self.Request.sudo().browse(self.request.id)

    def test_child_request_action_open_child_opens_child_form(self):
        action = self.child_request.action_open_child()
        self.assertEqual(action.get("res_model"), self.child_model_name)
        self.assertEqual(action.get("res_id"), self.child_request.id)
        self.assertEqual(action.get("target"), "current")
        self.assertEqual(action.get("views"), [[False, "form"]])

        popup_action = self.child_request.with_context(wf_open_target="new").action_open_child()
        self.assertEqual(popup_action.get("target"), "new")

    def test_runtime_v2_ui_nurse_verify_done_to_on_going_then_timer_auto_approve(self):
        self.start_tour(
            self.request_form_url,
            "workflow_engine_runtime_v2_nurse_done_to_on_going",
            login=self.nurse_user.login,
            timeout=180,
        )

        request = self._fresh_request()
        self.assertEqual(request.current_node_id, self.meta_on_going.node_id)
        self.assertEqual(request.current_activity_name, self.meta_on_going.name)
        self.assertEqual(request.state, "waiting")
        self.assertEqual(request.request_status, "pending")
        self.assertEqual(request.active_branch_node_ids, [self.meta_on_going.node_id])

        doctor_open_rows = request.approver_ids.filtered(
            lambda row: row.user_id == self.doctor_user
            and row.current_meta_node_id == self.meta_on_going.node_id
            and row.status in ("new", "pending", "waiting")
        )
        self.assertTrue(doctor_open_rows, "On Going task should be assigned to the doctor actor.")

        instance_by_name = {instance.node_name: instance for instance in request.automation_instance_ids}
        self.assertEqual(instance_by_name["Email Notify"].status, "success")
        self.assertEqual(instance_by_name["Send medicine stock out"].status, "success")
        self.assertEqual(instance_by_name["Sync with blue"].status, "success")
        self.assertEqual(instance_by_name["Allow admin to edit for 1 week"].status, "scheduled")

        message_bodies = " ".join(
            (request.message_ids | self.child_request.message_ids).sudo().mapped("body")
        )
        # email_action is type=log (sendTask) so it posts its name to the workflow chatter.
        # Concrete child models own business execution, while the base request is the runtime parent.
        self.assertIn(self.email_action.name, message_bodies)
        # medicine_action and sync_blue_action are server_action type — they
        # execute via ir.actions.server and do not necessarily post to chatter.
        # Their execution is validated via automation_instance status above.

        self.start_tour(
            self.request_form_url,
            "workflow_engine_runtime_v2_doctor_sees_on_going_actions",
            login=self.doctor_user.login,
            timeout=180,
        )

        timer_instance = instance_by_name["Allow admin to edit for 1 week"].sudo()
        timer_instance.sudo().write({"due_at": fields.Datetime.now() - timedelta(minutes=1)})
        timer_instance.flush_recordset(["due_at", "status"])
        # Run only this test timer. A production-copy database may already have
        # hundreds of due timers, so the global cron batch can process unrelated
        # clone data before reaching this instance.
        timer_instance._run_once()

        request = self._fresh_request()
        timer_instance = self.AutomationInstance.sudo().browse(timer_instance.id).exists()
        self.assertTrue(timer_instance)
        self.assertEqual(
            timer_instance.status,
            "success",
            timer_instance.error_message
            or "due_at=%s result=%s" % (timer_instance.due_at, timer_instance.result_json or {}),
        )
        self.assertEqual(request.current_activity_name, "Approved")
        self.assertEqual(request.state, "completed")
        self.assertEqual(request.request_status, "approved")
        self.assertFalse(request.active_branch_node_ids)
        self.assertFalse(
            self.PermissionService.can_access_request(request, user=self.doctor_user, scope="edit"),
            "Doctor should lose edit access once timer auto-approves the request.",
        )

        self.start_tour(
            self.request_form_url,
            "workflow_engine_runtime_v2_auto_approved_after_timer",
            login=self.doctor_user.login,
            timeout=180,
        )
