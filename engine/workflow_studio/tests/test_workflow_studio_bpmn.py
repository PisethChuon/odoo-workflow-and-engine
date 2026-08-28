import base64
import io
import json
import zipfile
from uuid import uuid4
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("ws_patch")
class TestWorkflowStudioBpmn(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.target_model = cls.env["ir.model"]._get("res.partner")

    def _create_category(self, name):
        return self.env["workflow.approval.category"].create(
            {
                "name": name,
                "res_model": self.target_model.id,
            }
        )

    def _build_two_step_bpmn(self):
        return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Definition_ApprovalFlow"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="ApprovalProcess" isExecutable="true">
    <bpmn:startEvent id="StartEvent" name="Start">
      <bpmn:outgoing>Flow_Start_Submission</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_Submission" name="Submission">
      <bpmn:incoming>Flow_Start_Submission</bpmn:incoming>
      <bpmn:outgoing>Flow_Submission_Action</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:intermediateThrowEvent id="Event_Submit" name="Submit">
      <bpmn:incoming>Flow_Submission_Action</bpmn:incoming>
      <bpmn:outgoing>Flow_Action_Manager</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>
    <bpmn:userTask id="Task_Manager" name="Manager Approval">
      <bpmn:incoming>Flow_Action_Manager</bpmn:incoming>
      <bpmn:outgoing>Flow_Manager_Action</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:intermediateThrowEvent id="Event_Approve" name="Approve">
      <bpmn:incoming>Flow_Manager_Action</bpmn:incoming>
      <bpmn:outgoing>Flow_Action_End</bpmn:outgoing>
    </bpmn:intermediateThrowEvent>
    <bpmn:intermediateThrowEvent id="Event_End" name="End">
      <bpmn:incoming>Flow_Action_End</bpmn:incoming>
      <bpmn:signalEventDefinition id="Signal_End"/>
    </bpmn:intermediateThrowEvent>
    <bpmn:sequenceFlow id="Flow_Start_Submission" sourceRef="StartEvent" targetRef="Task_Submission"/>
    <bpmn:sequenceFlow id="Flow_Submission_Action" sourceRef="Task_Submission" targetRef="Event_Submit"/>
    <bpmn:sequenceFlow id="Flow_Action_Manager" sourceRef="Event_Submit" targetRef="Task_Manager"/>
    <bpmn:sequenceFlow id="Flow_Manager_Action" sourceRef="Task_Manager" targetRef="Event_Approve"/>
    <bpmn:sequenceFlow id="Flow_Action_End" sourceRef="Event_Approve" targetRef="Event_End"/>
  </bpmn:process>
</bpmn:definitions>
"""

    def _build_user_task_with_end_event_bpmn(self):
        return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Definition_EndEventFlow"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="EndEventProcess" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_Start_Task</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_Review" name="Review">
      <bpmn:incoming>Flow_Start_Task</bpmn:incoming>
      <bpmn:outgoing>Flow_Task_End</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:endEvent id="EndEvent_1" name="Done">
      <bpmn:incoming>Flow_Task_End</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_Start_Task" sourceRef="StartEvent_1" targetRef="Task_Review"/>
    <bpmn:sequenceFlow id="Flow_Task_End" sourceRef="Task_Review" targetRef="EndEvent_1"/>
  </bpmn:process>
</bpmn:definitions>
"""

    def _build_parallel_service_task_bpmn(self):
        return """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Definition_ServiceTaskIsolation"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="ServiceTaskIsolationProcess" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_Start_Gateway</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:parallelGateway id="Gateway_Split" name="Split">
      <bpmn:incoming>Flow_Start_Gateway</bpmn:incoming>
      <bpmn:outgoing>Flow_Gateway_Stock</bpmn:outgoing>
      <bpmn:outgoing>Flow_Gateway_Blue</bpmn:outgoing>
    </bpmn:parallelGateway>
    <bpmn:serviceTask id="Task_ServiceStock" name="Send medicine stock out">
      <bpmn:incoming>Flow_Gateway_Stock</bpmn:incoming>
    </bpmn:serviceTask>
    <bpmn:serviceTask id="Task_ServiceBlue" name="Sync medicine to blue">
      <bpmn:incoming>Flow_Gateway_Blue</bpmn:incoming>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="Flow_Start_Gateway" sourceRef="StartEvent_1" targetRef="Gateway_Split"/>
    <bpmn:sequenceFlow id="Flow_Gateway_Stock" sourceRef="Gateway_Split" targetRef="Task_ServiceStock"/>
    <bpmn:sequenceFlow id="Flow_Gateway_Blue" sourceRef="Gateway_Split" targetRef="Task_ServiceBlue"/>
  </bpmn:process>
</bpmn:definitions>
"""

    def test_sync_from_bpmn_preserves_saved_domain_metadata(self):
        category = self._create_category("Studio Preserve Domains")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        approval_group_domain = "[('id', '=', request_owner_id)]"
        notification_domain = "[('active', '=', True)]"
        invisible_domain = "[('state', '=', 'waiting')]"
        execution_domain = "[('request_status', '=', 'waiting')]"
        reason_domain = "[('request_status', '=', 'needs_reason')]"
        comment_domain = "[('request_status', '=', 'needs_comment')]"
        validation_message = "<p><strong>Approval is not available.</strong></p>"

        version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "approval_group_domain": approval_group_domain,
                "notification_recipient_mode": "both",
                "notification_recipient_domain": notification_domain,
            },
        )
        serialized_action = version.workflow_studio_write_meta_action(
            "Task_Manager",
            "Event_Approve",
            {
                "invisible_domain": invisible_domain,
                "domain": execution_domain,
                "show_validation_dialog": True,
                "validation_message": validation_message,
                "require_reason": True,
                "require_reason_domain": reason_domain,
                "comment_required": True,
                "comment_required_domain": comment_domain,
            },
        )
        self.assertTrue(serialized_action["show_validation_dialog"])
        self.assertEqual(str(serialized_action["validation_message"]), validation_message)

        # Simulate the Studio "Save Diagram" path, which re-syncs metadata from BPMN XML.
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())

        task = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        action = self.env["workflow.category.version.meta.task.action"].search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Manager"),
                ("target_id", "=", "Event_Approve"),
            ],
            limit=1,
        )

        self.assertTrue(task)
        self.assertTrue(action)
        self.assertEqual(task.approval_group_domain, approval_group_domain)
        self.assertEqual(task.notification_recipient_domain, notification_domain)
        self.assertEqual(action.invisible_domain, invisible_domain)
        self.assertEqual(action.domain, execution_domain)
        self.assertTrue(action.show_validation_dialog)
        self.assertEqual(str(action.validation_message), validation_message)
        self.assertEqual(action.require_reason_domain, reason_domain)
        self.assertEqual(action.comment_required_domain, comment_domain)

    def test_workflow_studio_write_meta_action_persists_action_mode(self):
        category = self._create_category("Studio Action Mode")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_action_mode",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())

        action = self.env["workflow.category.version.meta.task.action"].search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Submission"),
                ("target_id", "=", "Event_Submit"),
            ],
            limit=1,
        )
        self.assertEqual(action.action_mode, "route")

        serialized = version.workflow_studio_write_meta_action(
            "Task_Submission",
            "Event_Submit",
            {"action_mode": "execute_path"},
        )

        action.invalidate_recordset(["action_mode"])
        self.assertEqual(action.action_mode, "execute_path")
        self.assertEqual(serialized["action_mode"], "execute_path")

    def test_business_action_authorization_round_trips_through_bpmn_sync(self):
        category = self._create_category("Studio Business Action Authorization")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_business_action",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())
        actor_user = self.env.ref("base.user_admin")
        approval_group = self.env["workflow.approval.group"].create(
            {
                "name": f"Studio Business Actors {uuid4().hex[:8]}",
                "user_ids": [(6, 0, [actor_user.id])],
            }
        )
        system_group = self.env.ref("base.group_user")

        serialized = version.workflow_studio_write_meta_action(
            "Task_Manager",
            "Event_Approve",
            {
                "authorization_mode": "business_actor",
                "authorization_scope": "task",
                "business_actor_include_owner": True,
                "business_actor_include_creator": True,
                "business_actor_include_node_assignees": False,
                "business_actor_user_ids": [actor_user.id],
                "business_actor_group_ids": [system_group.id],
                "business_actor_approval_group_ids": [approval_group.id],
                "business_actor_user_domain": "[('id', '=', uid)]",
            },
        )
        self.assertEqual(serialized["authorization_mode"], "business_actor")
        self.assertTrue(serialized["business_actor_include_owner"])
        self.assertEqual(serialized["business_actor_user_ids"], [actor_user.id])
        self.assertEqual(serialized["business_actor_group_ids"], [system_group.id])
        self.assertEqual(
            serialized["business_actor_approval_group_ids"],
            [approval_group.id],
        )

        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())
        action = self.env["workflow.category.version.meta.task.action"].search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Manager"),
                ("target_id", "=", "Event_Approve"),
            ],
            limit=1,
        )
        self.assertEqual(action.authorization_mode, "business_actor")
        self.assertTrue(action.business_actor_include_owner)
        self.assertTrue(action.business_actor_include_creator)
        self.assertEqual(action.business_actor_user_ids, actor_user)
        self.assertEqual(action.business_actor_group_ids, system_group)
        self.assertEqual(action.business_actor_approval_group_ids, approval_group)
        version._workflow_studio_validate_business_action_guardrails()

    def test_business_action_publish_guardrails_require_actor_source(self):
        category = self._create_category("Studio Business Action Missing Source")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_business_action_missing_source",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())
        version.workflow_studio_write_meta_action(
            "Task_Manager",
            "Event_Approve",
            {"authorization_mode": "business_actor"},
        )

        with self.assertRaisesRegex(ValidationError, "at least one actor source"):
            version._workflow_studio_validate_business_action_guardrails()

    def test_business_action_publish_guardrails_reject_invalid_user_domain(self):
        category = self._create_category("Studio Business Action Invalid Domain")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_business_action_invalid_domain",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())
        version.workflow_studio_write_meta_action(
            "Task_Manager",
            "Event_Approve",
            {
                "authorization_mode": "business_actor",
                "business_actor_include_owner": True,
                "business_actor_user_domain": "[('missing_business_actor_field', '=', True)]",
            },
        )

        with self.assertRaisesRegex(ValidationError, "Invalid user domain"):
            version._workflow_studio_validate_business_action_guardrails()

    def test_workflow_action_option_does_not_read_email_lines_for_non_email_actions(self):
        category = self._create_category("Studio Workflow Action Option No Email Lines")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_action_option_no_email_lines",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        workflow_action = self.env["workflow.approval.action"].create(
            {
                "name": "Log Only",
                "action_type": "log",
                "version_id": version.id,
            }
        )

        with patch.object(
            type(version),
            "_workflow_studio_has_email_recipient_line_table",
            side_effect=AssertionError("non-email actions must not inspect email recipient schema"),
        ):
            payload = version._workflow_studio_serialize_workflow_action_option(workflow_action)

        self.assertEqual(payload["email_recipient_lines"], [])

    def test_workflow_action_option_handles_missing_email_recipient_table(self):
        category = self._create_category("Studio Workflow Action Option Missing Email Table")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_action_option_missing_email_table",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        workflow_action = self.env["workflow.approval.action"].create(
            {
                "name": "Email Without Lines Table",
                "action_type": "email",
                "version_id": version.id,
            }
        )

        with patch.object(type(version), "_workflow_studio_has_email_recipient_line_table", return_value=False):
            payload = version._workflow_studio_serialize_workflow_action_option(workflow_action)

        self.assertEqual(payload["email_recipient_lines"], [])

    def test_sync_from_bpmn_preserves_action_name_when_label_diverges(self):
        category = self._create_category("Studio Preserve Action Name")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        version.workflow_studio_write_meta_action(
            "Task_Manager",
            "Event_Approve",
            {
                "name": "approve_manager_internal",
                "attr_label": "Approve Manager Display",
            },
        )

        synced_xml = self._build_two_step_bpmn().replace(
            'id="Event_Approve" name="Approve"',
            'id="Event_Approve" name="Approve Manager Display"',
            1,
        )
        version.workflow_studio_sync_from_bpmn(synced_xml)

        action = self.env["workflow.category.version.meta.task.action"].search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Manager"),
                ("target_id", "=", "Event_Approve"),
            ],
            limit=1,
        )
        self.assertTrue(action)
        self.assertEqual(action.name, "approve_manager_internal")
        self.assertEqual(action.attr_label, "Approve Manager Display")

    def test_sync_from_bpmn_initializes_blank_action_name_from_label(self):
        category = self._create_category("Studio Initialize Blank Action Name")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        action = self.env["workflow.category.version.meta.task.action"].search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Manager"),
                ("target_id", "=", "Event_Approve"),
            ],
            limit=1,
        )
        self.assertTrue(action)
        action.sudo().write({"name": False})

        synced_xml = self._build_two_step_bpmn().replace(
            'id="Event_Approve" name="Approve"',
            'id="Event_Approve" name="Approve Display"',
            1,
        )
        version.workflow_studio_sync_from_bpmn(synced_xml)

        action.invalidate_recordset(["name", "attr_label"])
        self.assertEqual(action.name, "Approve Display")
        self.assertEqual(action.attr_label, "Approve Display")

    def test_write_meta_task_persists_reset_request_to_submit_flag(self):
        category = self._create_category("Studio Reset Request To Submit")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        task = version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "reset_request_to_submit": True,
            },
        )
        self.assertTrue(task.get("reset_request_to_submit"))

        task_record = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        self.assertTrue(task_record.reset_request_to_submit)

        payload = version.workflow_studio_get_bpmn_payload()
        payload_task = next(
            row for row in (payload.get("meta", {}).get("tasks") or [])
            if row.get("node_id") == "Task_Manager"
        )
        self.assertTrue(payload_task.get("reset_request_to_submit"))

    def test_write_meta_task_persists_push_notification_to_actor_flag(self):
        category = self._create_category("Studio Push Notification To Actor")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        task = version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "push_notification_to_actor": False,
            },
        )
        self.assertFalse(task.get("push_notification_to_actor"))

        task_record = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        self.assertFalse(task_record.push_notification_to_actor)

        payload = version.workflow_studio_get_bpmn_payload()
        payload_task = next(
            row for row in (payload.get("meta", {}).get("tasks") or [])
            if row.get("node_id") == "Task_Manager"
        )
        self.assertFalse(payload_task.get("push_notification_to_actor"))

    def test_write_meta_task_persists_notify_request_owner_email_flag(self):
        category = self._create_category("Studio Notify Request Owner Email")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        task = version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "notify_request_owner_email": False,
            },
        )
        self.assertFalse(task.get("notify_request_owner_email"))

        task_record = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        self.assertFalse(task_record.notify_request_owner_email)

        payload = version.workflow_studio_get_bpmn_payload()
        payload_task = next(
            row for row in (payload.get("meta", {}).get("tasks") or [])
            if row.get("node_id") == "Task_Manager"
        )
        self.assertFalse(payload_task.get("notify_request_owner_email"))

    def test_write_meta_task_persists_notify_request_creator_email_flag(self):
        category = self._create_category("Studio Notify Request Creator Email")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )

        task = version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "notify_request_creator_email": False,
            },
        )
        self.assertFalse(task.get("notify_request_creator_email"))

        task_record = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        self.assertFalse(task_record.notify_request_creator_email)

        payload = version.workflow_studio_get_bpmn_payload()
        payload_task = next(
            row for row in (payload.get("meta", {}).get("tasks") or [])
            if row.get("node_id") == "Task_Manager"
        )
        self.assertFalse(payload_task.get("notify_request_creator_email"))

    def test_set_meta_fields_accepts_multiple_fields_and_types(self):
        category = self._create_category("Studio Multi Meta Fields")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_two_step_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())

        result = version.workflow_studio_set_meta_fields(
            "Task_Manager",
            [
                {
                    "field_model": "res.partner",
                    "field_name": "name",
                    "field_types": ["visible", "required"],
                    "activity_action_keys": ["Task_Manager|Event_Approve"],
                    "domains_by_type": {
                        "visible": "[('name', 'ilike', 'Corp')]",
                        "required": "[('email', '!=', False)]",
                    },
                },
                {
                    "field_model": "res.partner",
                    "field_name": "email",
                    "field_types": ["visible", "readonly"],
                    "activity_action_keys": ["Task_Manager|Event_Approve"],
                },
                {
                    "field_model": "res.partner",
                    "field_name": "phone",
                    "field_types": ["visible", "required", "readonly"],
                    "activity_action_keys": ["Task_Manager|Event_Approve"],
                },
            ],
        )
        self.assertFalse(result["warnings"])

        task = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")],
            limit=1,
        )
        rows = self.env["workflow.category.version.meta.field"].search([("meta_id", "=", task.id)])
        by_field = {}
        for row in rows:
            by_field.setdefault(row.field_id.name, set()).add(row.field_type)

        self.assertEqual(by_field.get("name"), {"visible", "required"})
        self.assertEqual(by_field.get("email"), {"visible", "readonly"})
        self.assertEqual(by_field.get("phone"), {"visible", "readonly"})
        self.assertEqual(len(result["rows"]), 6)
        self.assertTrue(rows.filtered(lambda row: row.field_id.name == "name" and row.field_type == "required").activity_action_ids)
        self.assertEqual(
            rows.filtered(lambda row: row.field_id.name == "name" and row.field_type == "visible").domain,
            "[('name', 'ilike', 'Corp')]",
        )
        self.assertEqual(
            rows.filtered(lambda row: row.field_id.name == "name" and row.field_type == "required").domain,
            "[('email', '!=', False)]",
        )
        self.assertIn(
            "[('email', '!=', False)]",
            [row["domain"] for row in result["rows"] if row["field_ref"]["name"] == "name"],
        )
        payload = version.workflow_studio_get_bpmn_payload()
        payload_rows = [
            row for row in payload["meta"]["fields"]
            if row["task_node_id"] == "Task_Manager" and row["field_ref"]["name"] == "name"
        ]
        by_type_payload = {row["field_type"]: row for row in payload_rows}
        self.assertEqual(
            by_type_payload["visible"]["domains_by_type"]["visible"],
            "[('name', 'ilike', 'Corp')]",
        )
        self.assertEqual(
            by_type_payload["visible"]["visible_domain"],
            "[('name', 'ilike', 'Corp')]",
        )
        self.assertEqual(
            by_type_payload["required"]["domains_by_type"]["required"],
            "[('email', '!=', False)]",
        )
        self.assertEqual(
            by_type_payload["required"]["required_domain"],
            "[('email', '!=', False)]",
        )
        self.assertFalse(rows.filtered(lambda row: row.field_id.name == "email").activity_action_ids)
        self.assertFalse(rows.filtered(lambda row: row.field_id.name == "phone").activity_action_ids)

    def test_set_meta_fields_accepts_end_event_nodes(self):
        category = self._create_category("Studio End Event Meta Fields")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_end_event",
                "is_active": False,
                "bpmn_xml": self._build_user_task_with_end_event_bpmn(),
            }
        )
        version.workflow_studio_sync_from_bpmn(self._build_user_task_with_end_event_bpmn())

        result = version.workflow_studio_set_meta_fields(
            "EndEvent_1",
            [
                {
                    "field_model": "res.partner",
                    "field_name": "name",
                    "field_types": ["visible", "readonly"],
                    "domains_by_type": {
                        "visible": "[('name', '!=', False)]",
                        "readonly": "[('email', '!=', False)]",
                    },
                },
                {
                    "field_model": "res.partner",
                    "field_name": "email",
                    "field_types": ["visible", "required"],
                },
            ],
        )
        self.assertFalse(result["warnings"])

        task = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "EndEvent_1")],
            limit=1,
        )
        self.assertTrue(task)
        self.assertTrue(task.is_end_node)

        rows = self.env["workflow.category.version.meta.field"].search([("meta_id", "=", task.id)])
        by_field = {}
        for row in rows:
            by_field.setdefault(row.field_id.name, set()).add(row.field_type)

        self.assertEqual(by_field.get("name"), {"visible", "readonly"})
        self.assertEqual(by_field.get("email"), {"visible", "required"})
        self.assertEqual(len(result["rows"]), 4)
        self.assertEqual(
            rows.filtered(lambda row: row.field_id.name == "name" and row.field_type == "visible").domain,
            "[('name', '!=', False)]",
        )
        self.assertEqual(
            rows.filtered(lambda row: row.field_id.name == "name" and row.field_type == "readonly").domain,
            "[('email', '!=', False)]",
        )

    def test_create_initial_version_from_empty_category(self):
        category = self._create_category("Studio Initial Version")
        self.assertFalse(category.version_ids)

        result = category.workflow_studio_create_initial_version({"title": "Initial"})
        version = self.env["workflow.approval.category.version"].browse(result["version_id"])

        self.assertTrue(version.exists())
        self.assertEqual(version.category_id.id, category.id)
        self.assertEqual(version.title, "Initial")
        self.assertFalse(version.is_active)
        self.assertFalse(version.is_locked)

    def test_action_activate_workflow_studio_without_version_sets_category_context_only(self):
        category = self._create_category("Studio Empty Category")
        action = category.action_activate_workflow_studio()
        context = action.get("params", {}).get("context", {})
        self.assertEqual(context.get("workflow_category_id"), category.id)
        self.assertFalse(
            context.get("workflow_version_id"),
            "No workflow version should be passed when the category has no versions yet",
        )

    def test_action_activate_workflow_studio_with_active_version_sets_version_context(self):
        category = self._create_category("Studio Active Version")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": True,
            }
        )
        category.active_version_id = version.id

        action = category.action_activate_workflow_studio()
        context = action.get("params", {}).get("context", {})
        self.assertEqual(context.get("workflow_category_id"), category.id)
        self.assertEqual(context.get("workflow_version_id"), version.id)

    def test_action_open_workflow_studio_entry_without_category_opens_quick_start_wizard(self):
        action = self.env["workflow.approval.category"].with_context(
            workflow_studio_skip_global_lookup=True
        ).action_open_workflow_studio_entry()
        self.assertEqual(action.get("res_model"), "workflow.studio.quick.start.wizard")
        self.assertEqual(action.get("target"), "new")

    def test_action_open_workflow_studio_entry_with_category_opens_studio(self):
        category = self._create_category("Studio Launcher Category")
        action = category.action_open_workflow_studio_entry()
        self.assertEqual(action.get("tag"), "workflow_studio.open_workflow_studio")
        self.assertEqual(
            action.get("params", {}).get("context", {}).get("workflow_category_id"),
            category.id,
        )

    def test_create_action_window_on_the_fly(self):
        category = self._create_category("Studio Action Window")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        result = version.workflow_studio_create_action_window({"name": "Open Request"})
        action = self.env["ir.actions.act_window"].browse(result["action"]["id"])

        self.assertTrue(action.exists())
        self.assertEqual(action.name, "Open Request")
        self.assertEqual(action.res_model, version.res_model_name)
        self.assertEqual(action.view_mode, "list,form")
        self.assertEqual(action.target, "current")

    def test_create_email_template_on_the_fly(self):
        category = self._create_category("Studio Email Template")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        result = version.workflow_studio_create_email_template(
            {
                "name": "Approval Mail",
                "subject": "Workflow update",
                "body_html": "<div>Hello</div>",
            }
        )
        template = self.env["mail.template"].browse(result["template"]["id"])

        self.assertTrue(template.exists())
        self.assertEqual(template.name, "Approval Mail")
        self.assertEqual(template.model, version.res_model_name)

    def test_create_activity_template_on_the_fly(self):
        category = self._create_category("Studio Activity Template")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        result = version.workflow_studio_create_activity_template(
            {
                "name": "Activity Mail",
                "subject": "Activity update",
                "body_html": "<div>Activity</div>",
            }
        )
        template = self.env["mail.template"].browse(result["template"]["id"])

        self.assertTrue(template.exists())
        self.assertEqual(template.name, "Activity Mail")
        self.assertEqual(template.model, "workflow.category.version.meta.task")

    def test_create_notification_recipient_on_the_fly_reuses_existing_user(self):
        category = self._create_category("Studio Recipient")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        created = version.workflow_studio_create_notification_recipient(
            {
                "name": "Workflow Recipient",
                "email": "recipient@example.com",
                "login": "workflow.recipient",
            }
        )
        created_user = self.env["res.users"].browse(created["user"]["id"])
        self.assertTrue(created_user.exists())
        self.assertFalse(created["existing"])

        reused = version.workflow_studio_create_notification_recipient(
            {
                "name": "Workflow Recipient Duplicate",
                "login": "workflow.recipient",
            }
        )
        self.assertTrue(reused["existing"])
        self.assertEqual(reused["user"]["id"], created_user.id)

    def test_create_action_window_on_the_fly_defaults_to_wizard_target_for_transient_model(self):
        transient_model, _extra_models = self.env["ir.model"].studio_model_create(
            "Studio BPMN Wizard",
            options=["is_transient"],
        )
        category = self.env["workflow.approval.category"].create(
            {
                "name": "Studio Action Window Wizard",
                "res_model": transient_model.id,
            }
        )
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        result = version.workflow_studio_create_action_window({"name": "Open Wizard"})
        action = self.env["ir.actions.act_window"].browse(result["action"]["id"])
        self.assertTrue(action.exists())
        self.assertEqual(action.view_mode, "form")
        self.assertEqual(action.target, "new")

    def test_create_action_window_on_the_fly_blank_values_use_model_defaults(self):
        transient_model, _extra_models = self.env["ir.model"].studio_model_create(
            "Studio BPMN Wizard Blank",
            options=["is_transient"],
        )
        category = self.env["workflow.approval.category"].create(
            {
                "name": "Studio Action Window Wizard Blank",
                "res_model": transient_model.id,
            }
        )
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )

        result = version.workflow_studio_create_action_window(
            {"name": "Open Wizard Blank", "view_mode": "", "target": ""}
        )
        action = self.env["ir.actions.act_window"].browse(result["action"]["id"])
        self.assertTrue(action.exists())
        self.assertEqual(action.view_mode, "form")
        self.assertEqual(action.target, "new")

    def test_import_bundle_invalid_zip_raises(self):
        category = self._create_category("Studio Invalid ZIP")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
            }
        )
        invalid_bundle = base64.b64encode(b"not-a-zip")
        with self.assertRaises(UserError):
            version.workflow_studio_import_bundle(invalid_bundle)

    def test_import_bundle_supports_flat_customizations_layout(self):
        category = self._create_category("Studio Flat Customizations Import")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_flat_import",
                "is_active": False,
            }
        )

        bundle_bytes = io.BytesIO()
        with zipfile.ZipFile(bundle_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "workflow_bundle/manifest.json",
                '{"format":"workflow_studio_bundle_v2"}',
            )
            archive.writestr(
                "workflow_bundle/customizations/.module_root",
                "workflow_studio_customization",
            )
            archive.writestr(
                "workflow_bundle/customizations/__manifest__.py",
                "{'name': 'Workflow Studio customizations'}",
            )
            archive.writestr(
                "workflow_bundle/customizations/data/custom.xml",
                "<odoo/>",
            )

        with patch.object(
            type(version),
            "_workflow_studio_import_customizations_zip",
            return_value=[],
        ) as import_custom_mock:
            version.workflow_studio_import_bundle(
                base64.b64encode(bundle_bytes.getvalue())
            )

        import_custom_mock.assert_called_once()
        imported_zip = import_custom_mock.call_args[0][0]
        with zipfile.ZipFile(io.BytesIO(imported_zip), "r") as rebuilt:
            rebuilt_names = set(rebuilt.namelist())
            self.assertIn(
                "workflow_studio_customization/__manifest__.py",
                rebuilt_names,
            )
            self.assertIn(
                "workflow_studio_customization/data/custom.xml",
                rebuilt_names,
            )

    def test_export_bundle_has_installable_module_structure(self):
        category = self._create_category("Studio Export Module")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_export",
                "title": "Export Structure",
                "is_active": False,
            }
        )

        result = version.workflow_studio_export_bundle()
        self.assertTrue(result.get("filename", "").endswith(".zip"))
        self.assertTrue(result.get("content"))

        archive_bytes = base64.b64decode(result["content"])
        parsed_manifest = self.env["workflow.studio.import.zip.wizard"]._read_bundle_manifest(
            archive_bytes
        )
        self.assertEqual(parsed_manifest.get("format"), "workflow_studio_bundle_v2")

        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            names = set(archive.namelist())
            module_root = result["filename"][:-4]

            self.assertIn(f"{module_root}/__init__.py", names)
            self.assertIn(f"{module_root}/__manifest__.py", names)
            self.assertIn(f"{module_root}/hooks.py", names)
            self.assertIn(f"{module_root}/security/ir.model.access.csv", names)
            self.assertIn(f"{module_root}/manifest.json", names)
            self.assertIn(f"{module_root}/bpmn/workflow.bpmn", names)
            self.assertIn(f"{module_root}/data/metadata.json", names)
            self.assertIn(f"{module_root}/data/category.json", names)
            self.assertIn(f"{module_root}/data/references.json", names)
            self.assertIn(f"{module_root}/studio_customizations_manifest.json", names)
            self.assertNotIn(f"{module_root}/workflow_studio/workflow_customizations.zip", names)
            self.assertFalse(
                any(name.startswith(f"{module_root}/workflow_studio/customizations/") for name in names),
                "Export should not keep customizations in legacy nested path.",
            )
            self.assertFalse(
                any(name.startswith(f"{module_root}/customizations/") for name in names),
                "Export should not keep customizations under a dedicated subfolder.",
            )
            self.assertFalse(
                any(name.startswith(f"{module_root}/data/studio_payload/") for name in names),
                "Export should merge customization payload files directly into module structure.",
            )

            payload_manifest = json.loads(
                archive.read(f"{module_root}/studio_customizations_manifest.json").decode("utf-8")
            )
            for relative_name in payload_manifest.get("files", []):
                self.assertIn(
                    f"{module_root}/{relative_name}",
                    names,
                    "Every payload file listed in manifest must be present in module root structure.",
                )

            module_manifest_text = archive.read(f"{module_root}/__manifest__.py").decode("utf-8")
            self.assertIn("'post_init_hook': 'post_init_hook'", module_manifest_text)

    def test_category_snapshot_round_trips_duplicate_domain_and_guide(self):
        category = self._create_category("Studio Category Snapshot")
        category.write(
            {
                "guide_html": "<p>Guide</p>",
                "allowed_duplicate": False,
                "allow_duplicate_domain": "[('state', '=', 'waiting')]",
            }
        )
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_snapshot",
                "is_active": False,
            }
        )

        snapshot = version._workflow_studio_build_category_snapshot()

        category.write(
            {
                "guide_html": "",
                "allowed_duplicate": True,
                "allow_duplicate_domain": "[]",
            }
        )
        warnings = version._workflow_studio_apply_category_snapshot(snapshot)

        self.assertEqual(warnings, [])
        category.invalidate_recordset(["guide_html", "allowed_duplicate", "allow_duplicate_domain"])
        self.assertEqual(category.guide_html, "<p>Guide</p>")
        self.assertFalse(category.allowed_duplicate)
        self.assertEqual(category.allow_duplicate_domain, "[('state', '=', 'waiting')]")

    def test_resolve_user_ref_prefers_login_over_conflicting_id(self):
        category = self._create_category("Studio Resolve User")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_user_resolve",
                "is_active": False,
            }
        )
        wrong_user = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Wrong User",
                "login": f"wrong_{uuid4().hex[:6]}",
                "email": f"wrong_{uuid4().hex[:6]}@example.com",
            }
        )
        wanted_login = f"wanted_{uuid4().hex[:6]}"
        wanted_user = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Wanted User",
                "login": wanted_login,
                "email": f"{wanted_login}@example.com",
            }
        )

        resolved = version._workflow_studio_resolve_user_refs(
            [
                {
                    "id": wrong_user.id,
                    "login": wanted_user.login,
                    "name": wanted_user.name,
                    "email": wanted_user.email,
                }
            ]
        )

        self.assertEqual(resolved, wanted_user)

    def test_resolve_approval_group_ref_prefers_name_over_conflicting_id(self):
        category = self._create_category("Studio Resolve Group")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_group_resolve",
                "is_active": False,
            }
        )
        group_model = self.env["workflow.approval.group"]
        wrong_group = group_model.create({"name": f"Wrong {uuid4().hex[:6]}"})
        wanted_group = group_model.create({"name": f"Wanted {uuid4().hex[:6]}"})

        resolved = version.with_context(
            workflow_studio_create_missing_refs=True
        )._workflow_studio_resolve_approval_group_ref(
            {
                "id": wrong_group.id,
                "name": wanted_group.name,
            }
        )

        self.assertEqual(resolved, wanted_group)

    def test_workflow_version_lifecycle_deploy_publish_and_rollback(self):
        category = self._create_category("Studio Lifecycle")
        version_one = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_lifecycle_1",
                "is_active": False,
            }
        )
        version_two = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_lifecycle_2",
                "is_active": False,
            }
        )

        deploy_result = version_one.workflow_studio_deploy_version()
        self.assertEqual(deploy_result.get("version_id"), version_one.id)
        version_one.invalidate_recordset(["is_active", "is_published", "deployed_at", "is_locked"])
        category.invalidate_recordset(["active_version_id"])
        self.assertEqual(category.active_version_id.id, version_one.id)
        self.assertTrue(version_one.is_active)
        self.assertFalse(version_one.is_published)
        self.assertTrue(version_one.deployed_at)
        self.assertFalse(version_one.is_locked)

        publish_result = version_two.workflow_studio_publish_version()
        self.assertEqual(publish_result.get("version_id"), version_two.id)
        version_two.invalidate_recordset(["is_active", "is_published", "published_at", "is_locked"])
        category.invalidate_recordset(["active_version_id"])
        self.assertEqual(category.active_version_id.id, version_two.id)
        self.assertTrue(version_two.is_active)
        self.assertTrue(version_two.is_published)
        self.assertTrue(version_two.published_at)
        self.assertTrue(version_two.is_locked)

        rollback_result = version_two.workflow_studio_rollback_version(version_one.id)
        self.assertEqual(rollback_result.get("version_id"), version_one.id)
        version_one.invalidate_recordset(["is_active"])
        version_two.invalidate_recordset(["is_active"])
        category.invalidate_recordset(["active_version_id"])
        self.assertEqual(category.active_version_id.id, version_one.id)
        self.assertTrue(version_one.is_active)
        self.assertFalse(version_two.is_active)

    def test_workflow_studio_write_meta_task_persists_recurring_send_task_settings(self):
        category = self._create_category("Recurring Send Category")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_recurring_send",
                "title": "Recurring Send",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Send">
              <bpmn:process id="Process_Send" isExecutable="true">
                <bpmn:startEvent id="StartEvent_1" name="Start">
                  <bpmn:outgoing>Flow_1</bpmn:outgoing>
                </bpmn:startEvent>
                <bpmn:sendTask id="Task_Reminder" name="Reminder">
                  <bpmn:incoming>Flow_1</bpmn:incoming>
                  <bpmn:outgoing>Flow_2</bpmn:outgoing>
                </bpmn:sendTask>
                <bpmn:endEvent id="EndEvent_1" name="Done">
                  <bpmn:incoming>Flow_2</bpmn:incoming>
                </bpmn:endEvent>
                <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_Reminder"/>
                <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Reminder" targetRef="EndEvent_1"/>
              </bpmn:process>
            </bpmn:definitions>"""
        )

        task = version.workflow_studio_write_meta_task(
            "Task_Reminder",
            {
                "automation_run_mode": "scheduled",
                "automation_schedule_mode": "interval",
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 10,
            },
        )

        self.assertEqual(task["automation_run_mode"], "scheduled")
        self.assertEqual(task["automation_schedule_mode"], "interval")
        self.assertEqual(task["automation_interval_number"], 3)
        self.assertEqual(task["automation_interval_type"], "minutes")
        self.assertTrue(task["automation_is_recurring"])
        self.assertEqual(task["automation_recurrence_end_mode"], "count")
        self.assertEqual(task["automation_recurrence_count"], 10)

    def test_workflow_studio_write_meta_task_persists_conditional_event_domain(self):
        category = self._create_category("Conditional Event Category")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_conditional_event",
                "title": "Conditional Event",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional">
              <bpmn:process id="Process_Conditional" isExecutable="true">
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
            </bpmn:definitions>"""
        )

        task = version.workflow_studio_write_meta_task(
            "Event_Check",
            {
                "automation_condition_domain": "[('request_status', '=', 'waiting')]",
            },
        )

        self.assertEqual(
            task["automation_condition_domain"],
            "[('request_status', '=', 'waiting')]",
        )

    def test_conditional_event_activation_requires_default_flow(self):
        category = self._create_category("Conditional Event Missing Default")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_conditional_missing_default",
                "title": "Conditional Event Missing Default",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_No_Default">
              <bpmn:process id="Process_Conditional_No_Default" isExecutable="true">
                <bpmn:intermediateCatchEvent id="Event_Check" name="Check Request">
                  <bpmn:outgoing>Flow_Matched</bpmn:outgoing>
                  <bpmn:outgoing>Flow_Default</bpmn:outgoing>
                  <bpmn:conditionalEventDefinition id="Cond_1"/>
                </bpmn:intermediateCatchEvent>
                <bpmn:userTask id="Task_Matched" name="Matched"/>
                <bpmn:userTask id="Task_Default" name="Default"/>
                <bpmn:sequenceFlow id="Flow_Matched" sourceRef="Event_Check" targetRef="Task_Matched"/>
                <bpmn:sequenceFlow id="Flow_Default" sourceRef="Event_Check" targetRef="Task_Default"/>
              </bpmn:process>
            </bpmn:definitions>"""
        )

        with self.assertRaisesRegex(UserError, "default outgoing flow"):
            version.workflow_studio_deploy_version()

    def test_conditional_event_activation_rejects_invalid_condition_domain(self):
        category = self._create_category("Conditional Event Invalid Domain")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_conditional_invalid_domain",
                "title": "Conditional Event Invalid Domain",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_Invalid_Domain">
              <bpmn:process id="Process_Conditional_Invalid_Domain" isExecutable="true">
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
            </bpmn:definitions>"""
        )
        task = version.meta_task_ids.filtered(lambda row: row.node_id == "Event_Check")[:1]
        task.sudo().write({"automation_condition_domain": "[1, '=', 1]"})

        with self.assertRaisesRegex(UserError, "invalid condition domain"):
            version.workflow_studio_publish_version()

    def test_workflow_studio_write_meta_task_preserves_hidden_legacy_fields(self):
        category = self._create_category("Conditional Event Hidden Fields")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_conditional_hidden_fields",
                "title": "Conditional Event Hidden Fields",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Conditional_Hidden">
              <bpmn:process id="Process_Conditional_Hidden" isExecutable="true">
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
            </bpmn:definitions>"""
        )

        task_record = self.env["workflow.category.version.meta.task"].search(
            [("version_id", "=", version.id), ("node_id", "=", "Event_Check")],
            limit=1,
        )
        task_record.write(
            {
                "attr_class": "legacy-css",
                "element": "loop",
            }
        )

        task = version.workflow_studio_write_meta_task(
            "Event_Check",
            {
                "automation_condition_domain": "[('request_status', '=', 'waiting')]",
                "attr_label": "Is Matched",
            },
        )

        task_record.invalidate_recordset(["attr_class", "element", "automation_condition_domain", "attr_label"])
        self.assertEqual(task_record.attr_class, "legacy-css")
        self.assertEqual(task_record.element, "loop")
        self.assertEqual(task["automation_condition_domain"], "[('request_status', '=', 'waiting')]")
        self.assertEqual(task["attr_label"], "Is Matched")

    def test_workflow_studio_write_meta_action_persists_recurring_auto_action_schedule(self):
        category = self._create_category("Recurring AutoAction Category")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_recurring_auto_action",
                "title": "Recurring AutoAction",
                "is_active": False,
            }
        )
        version.workflow_studio_sync_from_bpmn(
            """<?xml version="1.0" encoding="UTF-8"?>
            <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_Timer">
              <bpmn:process id="Process_Timer" isExecutable="true">
                <bpmn:startEvent id="StartEvent_1" name="Start">
                  <bpmn:outgoing>Flow_1</bpmn:outgoing>
                </bpmn:startEvent>
                <bpmn:userTask id="Task_Wait" name="Wait Approval">
                  <bpmn:incoming>Flow_1</bpmn:incoming>
                  <bpmn:outgoing>Flow_Timer</bpmn:outgoing>
                </bpmn:userTask>
                <bpmn:intermediateCatchEvent id="Timer_Reminder" name="Reminder Timer">
                  <bpmn:incoming>Flow_Timer</bpmn:incoming>
                  <bpmn:timerEventDefinition id="TimerDefinition_Reminder"/>
                </bpmn:intermediateCatchEvent>
                <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_Wait"/>
                <bpmn:sequenceFlow id="Flow_Timer" sourceRef="Task_Wait" targetRef="Timer_Reminder"/>
              </bpmn:process>
            </bpmn:definitions>"""
        )

        action = version.workflow_studio_write_meta_action(
            "Task_Wait",
            "Timer_Reminder",
            {
                "automation_schedule_mode": "interval",
                "automation_interval_number": 3,
                "automation_interval_type": "minutes",
                "automation_is_recurring": True,
                "automation_recurrence_end_mode": "count",
                "automation_recurrence_count": 10,
                "automation_trigger_mode": "reminder",
            },
        )

        self.assertEqual(action["flow_type"], "autoAction")
        self.assertEqual(action["automation_schedule_mode"], "interval")
        self.assertEqual(action["automation_interval_number"], 3)
        self.assertEqual(action["automation_interval_type"], "minutes")
        self.assertTrue(action["automation_is_recurring"])
        self.assertEqual(action["automation_recurrence_end_mode"], "count")
        self.assertEqual(action["automation_recurrence_count"], 10)
        self.assertEqual(action["automation_trigger_mode"], "reminder")
        self.assertEqual(action["timer_duration_number"], 3)
        self.assertEqual(action["timer_duration_unit"], "minutes")

    def test_workflow_studio_to_engine_runtime_end_to_end(self):
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        unique = uuid4().hex[:8]

        def _new_user(name_prefix):
            return self.env["res.users"].with_context(no_reset_password=True).create(
                {
                    "name": f"{name_prefix} {unique}",
                    "login": f"{name_prefix.lower()}_{unique}",
                    "email": f"{name_prefix.lower()}_{unique}@example.com",
                    "group_ids": [(6, 0, [workflow_group.id])],
                }
            )

        requester = _new_user("Requester")
        manager = _new_user("Manager")

        request_model = self.env["ir.model"]._get("workflow.base.approval.request")
        category = self.env["workflow.approval.category"].create(
            {
                "name": f"Studio Runtime Category {unique}",
                "res_model": request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [(6, 0, [requester.id, manager.id])],
            }
        )
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v_e2e",
                "title": "Studio Runtime E2E",
                "is_active": False,
            }
        )

        version.workflow_studio_sync_from_bpmn(self._build_two_step_bpmn())
        version.workflow_studio_write_meta_task(
            "Task_Submission",
            {
                "assignment_mode": "request_owner",
                "completion_mode": "any",
            },
        )
        version.workflow_studio_write_meta_task(
            "Task_Manager",
            {
                "assignment_mode": "groups",
                "completion_mode": "any",
                "fallback_policy": "block",
            },
        )
        approval_group = version.workflow_studio_create_approval_group(
            {
                "name": f"Manager Group {unique}",
                "user_ids": [manager.id],
            }
        )["approval_group"]
        link_result = version.workflow_studio_set_task_approval_links(
            "Task_Manager",
            [
                {
                    "approval_group_ref": {"id": approval_group["id"]},
                    "sequence": 10,
                    "user_domain": "[(1, '=', 1)]",
                    "domain": "[(1, '=', 1)]",
                }
            ],
        )
        self.assertFalse(link_result.get("warnings"))

        publish_result = version.workflow_studio_publish_version()
        self.assertEqual(publish_result.get("version_id"), version.id)
        category.invalidate_recordset(["active_version_id"])
        version.invalidate_recordset(["is_active", "is_published", "is_locked"])
        self.assertEqual(category.active_version_id.id, version.id)
        self.assertTrue(version.is_active)
        self.assertTrue(version.is_published)
        self.assertTrue(version.is_locked)

        meta_task_model = self.env["workflow.category.version.meta.task"]
        meta_action_model = self.env["workflow.category.version.meta.task.action"]
        submission_task = meta_task_model.search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Submission")], limit=1
        )
        manager_task = meta_task_model.search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_Manager")], limit=1
        )
        submit_action = meta_action_model.search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Submission"),
                ("target_id", "=", "Event_Submit"),
            ],
            limit=1,
        )
        approve_action = meta_action_model.search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_Manager"),
                ("target_id", "=", "Event_Approve"),
            ],
            limit=1,
        )
        self.assertTrue(submission_task)
        self.assertTrue(manager_task)
        self.assertTrue(submit_action)
        self.assertTrue(approve_action)

        request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": f"REQ_E2E_{unique}",
                "category_id": category.id,
                "request_owner_id": requester.id,
                "current_node_id": submission_task.node_id,
                "previous_node_id": "StartEvent",
                "current_iteration_no": 1,
            }
        )

        assignment_service = self.env["workflow.engine.assignment.service"]
        runtime_service = self.env["workflow.engine.runtime.service"]

        submission_instance = assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=request,
            meta_task=submission_task,
            iteration_no=1,
        )
        self.assertEqual(submission_instance.assignee_ids.mapped("assignee_user_id").ids, [requester.id])
        runtime_service.record_decision_from_legacy(
            request_record=request,
            meta_action=submit_action,
            actor_user=requester,
            comment="submit",
            idempotency_key=f"submit-{unique}",
        )
        submission_instance.invalidate_recordset(["status"])
        self.assertEqual(submission_instance.status, "approved")

        manager_instance = assignment_service.create_or_sync_task_instance_from_legacy(
            request_record=request,
            meta_task=manager_task,
            previous_meta_task=submission_task,
            iteration_no=1,
        )
        self.assertEqual(manager_instance.assignee_ids.mapped("assignee_user_id").ids, [manager.id])
        runtime_service.record_decision_from_legacy(
            request_record=request,
            meta_action=approve_action,
            actor_user=manager,
            comment="approve",
            idempotency_key=f"approve-{unique}",
        )
        manager_instance.invalidate_recordset(["status"])
        self.assertEqual(manager_instance.status, "approved")

        decision_events = self.env["workflow.request.task.event"].sudo().search(
            [("request_id", "=", request.id), ("event_type", "=", "decision")],
            order="id",
        )
        self.assertEqual(len(decision_events), 2)
        self.assertEqual(decision_events.mapped("action_key"), ["Submit", "Approve"])

    def test_update_workflow_action_isolates_shared_task_actions(self):
        category = self._create_category("Studio Shared Service Action")
        version = self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "is_active": False,
                "bpmn_xml": self._build_parallel_service_task_bpmn(),
            }
        )

        MetaTask = self.env["workflow.category.version.meta.task"].sudo()
        task_stock = MetaTask.search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_ServiceStock")], limit=1
        )
        task_blue = MetaTask.search(
            [("version_id", "=", version.id), ("node_id", "=", "Task_ServiceBlue")], limit=1
        )
        self.assertTrue(task_stock)
        self.assertTrue(task_blue)

        server_action_a = self.env["ir.actions.server"].sudo().create(
            {
                "name": "Studio Stock Action A",
                "state": "code",
                "model_id": self.target_model.id,
                "code": "record and True",
            }
        )
        server_action_b = self.env["ir.actions.server"].sudo().create(
            {
                "name": "Studio Stock Action B",
                "state": "code",
                "model_id": self.target_model.id,
                "code": "record and True",
            }
        )
        shared_action = self.env["workflow.approval.action"].sudo().create(
            {
                "name": "Shared Service Action",
                "action_type": "server_action",
                "version_id": version.id,
                "server_action_id": server_action_a.id,
            }
        )
        task_stock.write({"service_behavior": "executor", "activity_type_ids": [(6, 0, [shared_action.id])]})
        task_blue.write({"service_behavior": "executor", "activity_type_ids": [(6, 0, [shared_action.id])]})

        result = version.workflow_studio_update_workflow_action(
            shared_action.id,
            {"server_action_id": server_action_b.id},
            task_stock.node_id,
        )

        self.assertTrue(result.get("isolated_from_shared"))
        isolated_action = self.env["workflow.approval.action"].browse(result["workflow_action"]["id"])
        self.assertTrue(isolated_action.exists())
        self.assertNotEqual(isolated_action.id, shared_action.id)
        self.assertEqual(isolated_action.server_action_id.id, server_action_b.id)

        task_stock.invalidate_recordset(["activity_type_ids"])
        task_blue.invalidate_recordset(["activity_type_ids"])
        shared_action.invalidate_recordset(["server_action_id"])
        self.assertEqual(task_stock.activity_type_ids.ids, [isolated_action.id])
        self.assertEqual(task_blue.activity_type_ids.ids, [shared_action.id])
        self.assertEqual(shared_action.server_action_id.id, server_action_a.id)
