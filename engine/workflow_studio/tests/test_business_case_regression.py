# -*- coding: utf-8 -*-

from pathlib import Path
from uuid import uuid4

from odoo.addons.workflow_studio.models.workflow_approval_category_version import (
    DOMAIN_PRESET_OPTIONS,
)
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("ws_patch", "business_case_regression")
class TestWorkflowStudioBusinessCaseRegression(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.target_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.flow_root = (
            Path(__file__).resolve().parents[2]
            / "workflow_engine"
            / "demo"
            / "flow"
            / "all_flows_bpmn"
        )
        cls.exit_flow_files = sorted(
            path.name for path in cls.flow_root.glob("exit_clearance_form__*.bpmn")
        )
        cls.bcj_flow_files = sorted(path.name for path in cls.flow_root.glob("finance__bcj*.bpmn"))
        cls.maintenance_flow_files = sorted(
            path.name for path in cls.flow_root.glob("maintenance__*.bpmn")
        )
        cls.medical_flow_files = ["hr__hr_medical_treatment.bpmn"]

    def _create_version_from_flow(self, flow_file_name, name_prefix):
        unique = uuid4().hex[:8]
        category = self.env["workflow.approval.category"].create(
            {
                "name": f"{name_prefix} {unique}",
                "res_model": self.target_model.id,
            }
        )
        bpmn_xml = (self.flow_root / flow_file_name).read_text(encoding="utf-8")
        version = self.env["workflow.approval.category.version"].create(
            {
                "name": f"v_{unique}",
                "category_id": category.id,
                "bpmn_xml": bpmn_xml,
            }
        )
        category.active_version_id = version.id
        return version

    def _action_domain(self, payload, source_id, target_id):
        actions = payload.get("meta", {}).get("actions", [])
        for row in actions:
            if row.get("source_id") == source_id and row.get("target_id") == target_id:
                return row.get("domain") or ""
        return ""

    def test_bcj_payload_keeps_finance_route_conditions(self):
        version = self._create_version_from_flow("finance__bcj.bpmn", "BCJ Studio Regression")
        payload = version.workflow_studio_get_bpmn_payload()

        action_map = {row.get("node_id"): row for row in payload.get("meta", {}).get("actions", [])}
        self.assertEqual(
            action_map.get("Flow_22", {}).get("domain"),
            "[('total_amount', '<=', 500), ('branch_company', '=', 'gaming')]",
        )
        self.assertEqual(
            action_map.get("Flow_23", {}).get("domain"),
            "[('total_amount', '<=', 500), ('branch_company', '=', 'hotel')]",
        )
        self.assertEqual(
            action_map.get("Flow_24", {}).get("domain"),
            "[('total_amount', '<=', 500), ('branch_company', '=', 'others')]",
        )
        self.assertEqual(
            action_map.get("Flow_25", {}).get("domain"),
            "[('total_amount', '>', 500), ('total_amount', '<=', 100000)]",
        )
        self.assertEqual(
            action_map.get("Flow_26", {}).get("domain"),
            "[('total_amount', '>', 100000)]",
        )
        self.assertEqual(
            action_map.get("Flow_51", {}).get("domain"),
            "[('allow_modification', '=', True)]",
        )

        task_nodes = {row.get("node_id") for row in payload.get("meta", {}).get("tasks", [])}
        self.assertIn("Gateway_FinanceRoute", task_nodes)
        self.assertIn("Task_Purchasing", task_nodes)
        self.assertIn("Task_Modification", task_nodes)

    def test_bcj_revision_family_payload_keeps_finance_domains(self):
        self.assertTrue(self.bcj_flow_files, "Expected BCJ revisions in bundled flows.")
        expected_routes = {
            ("Gateway_FinanceRoute", "Task_FinanceGaming"): "[('total_amount', '<=', 500), ('branch_company', '=', 'gaming')]",
            ("Gateway_FinanceRoute", "Task_FinanceHotel"): "[('total_amount', '<=', 500), ('branch_company', '=', 'hotel')]",
            ("Gateway_FinanceRoute", "Task_GroupFinance"): "[('total_amount', '<=', 500), ('branch_company', '=', 'others')]",
            ("Gateway_FinanceRoute", "Task_CFO_DYCFO"): "[('total_amount', '>', 500), ('total_amount', '<=', 100000)]",
            ("Gateway_FinanceRoute", "Task_CFO"): "[('total_amount', '>', 100000)]",
            ("Gateway_ModificationWindow", "Task_Modification"): "[('allow_modification', '=', True)]",
        }
        for flow_file in self.bcj_flow_files:
            version = self._create_version_from_flow(flow_file, "BCJ Studio Revision Regression")
            payload = version.workflow_studio_get_bpmn_payload()
            for edge, expected_domain in expected_routes.items():
                source_id, target_id = edge
                self.assertEqual(
                    self._action_domain(payload, source_id, target_id),
                    expected_domain,
                    "Unexpected domain for %s -> %s in %s." % (source_id, target_id, flow_file),
                )

    def test_exit_revision_family_payload_keeps_offboard_domains(self):
        self.assertTrue(self.exit_flow_files, "Expected Exit Clearance revisions in bundled flows.")
        for flow_file in self.exit_flow_files:
            version = self._create_version_from_flow(flow_file, "Exit Studio Revision Regression")
            payload = version.workflow_studio_get_bpmn_payload()
            self.assertEqual(
                self._action_domain(payload, "Gateway_OffboardRoute", "Task_DisableAccounts"),
                "[('request_owner_emp_type', '=', 'employee')]",
                "Unexpected offboard disable-account domain in %s." % flow_file,
            )
            self.assertEqual(
                self._action_domain(payload, "Gateway_OffboardRoute", "Task_NotifyChannels"),
                "[('id', '!=', 0)]",
                "Unexpected offboard notify domain in %s." % flow_file,
            )

    def test_maintenance_and_medical_revision_payload_keeps_additional_approval_domain(self):
        flow_files = self.maintenance_flow_files + self.medical_flow_files
        self.assertTrue(flow_files, "Expected maintenance/medical revisions in bundled flows.")

        for flow_file in flow_files:
            version = self._create_version_from_flow(flow_file, "Maintenance Medical Studio Regression")
            payload = version.workflow_studio_get_bpmn_payload()
            actions = payload.get("meta", {}).get("actions", [])
            add_action = next(
                (
                    row
                    for row in actions
                    if (row.get("source_id") or "").startswith("Gateway_Route")
                    and (row.get("target_id") or "").startswith("Task_AdditionalApproval")
                ),
                {},
            )
            done_action = next(
                (
                    row
                    for row in actions
                    if (row.get("source_id") or "").startswith("Gateway_Route")
                    and (row.get("target_id") or "").startswith("EndEvent_Completed")
                ),
                {},
            )
            self.assertTrue(add_action, "Missing additional-approval edge in %s." % flow_file)
            self.assertTrue(done_action, "Missing completed edge in %s." % flow_file)
            self.assertEqual(
                add_action.get("domain"),
                "[('need_additional_approval', '=', True)]",
                "Unexpected additional-approval domain in %s." % flow_file,
            )
            self.assertEqual(
                done_action.get("domain") or "",
                "",
                "Fallback completed edge should stay unconditional in %s." % flow_file,
            )

    def test_exit_studio_reconfiguration_handles_approval_links_and_twofa(self):
        version = self.env.ref(
            "workflow_engine.workflow_category_exit_clearance_demo_version_v1",
            raise_if_not_found=False,
        )
        if not version:
            self.skipTest("Exit Clearance demo data is not installed; run with demo data enabled.")

        it_group = self.env.ref("workflow_engine.approval_group_exit_clearance_it")
        link_result = version.workflow_studio_set_task_approval_links(
            "Task_ITClearance",
            [
                {
                    "approval_group_ref": {"id": it_group.id},
                    "sequence": 10,
                    "user_domain": "[('active', '=', True)]",
                    "domain": "[('request_owner_emp_type', '=', 'employee')]",
                    "note": "Mission-critical IT gate",
                }
            ],
        )
        self.assertFalse(link_result.get("warnings"))
        rows = link_result.get("rows") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("approval_group_ref", {}).get("id"), it_group.id)
        self.assertEqual(
            rows[0].get("domain"),
            "[('request_owner_emp_type', '=', 'employee')]",
        )

        payroll_action = version.workflow_studio_write_meta_action(
            "Task_PayrollReview",
            "Event_PayrollApprove",
            {
                "require_2fa": True,
                "twofa_method": "email_otp",
                "twofa_condition_domain": "[('request_owner_emp_type', '=', 'employee')]",
                "comment_required": True,
            },
        )
        self.assertTrue(payroll_action.get("require_2fa"))
        self.assertEqual(payroll_action.get("twofa_method"), "email_otp")
        self.assertEqual(
            payroll_action.get("twofa_condition_domain"),
            "[('request_owner_emp_type', '=', 'employee')]",
        )

    def test_domain_validator_accepts_exit_and_assignment_expressions(self):
        validator = self.env["workflow.approval.category.version"]
        cases = [
            (
                "workflow.base.approval.request",
                "[('wf_actor_uid', '=', request_owner_id)]",
                "field_modifiers",
                False,
            ),
            (
                "workflow.base.approval.request",
                "[('wf_actor_is_hod', '=', True)]",
                "field_modifiers",
                False,
            ),
            (
                "workflow.base.approval.request",
                "[('request_owner_emp_type', '=', 'employee')]",
                "field_modifiers",
                False,
            ),
            (
                "res.users",
                "[('active', '=', True)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "[('id', 'in', notification_submitter_and_decided_user_ids)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "[('id', '=', request_owner_manager_user_id)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "[('id', '=', request_creator_id)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "[('id', '=', request_creator_manager_user_id)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "[('id', 'in', pending_approver_user_ids)]",
                "assignment_users",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('uid', '=', request_owner_manager_user_id)]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('uid', '=', request_owner_department_manager_user_id)]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('wf_actor_is_manager', '=', True)]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('wf_actor_group_ids', 'in', [3])]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('wf_actor_group_xmlids', 'ilike', ',workflow_engine.group_workflow_approval_user,')]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "actor_has_group('workflow_engine.group_workflow_approval_user')",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "actor_has_approval_group(12)",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "res.users",
                "actor_has_group('workflow_engine.group_workflow_approval_user')",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "['|', ('wf_actor_group_ids', 'in', [3]), ('wf_actor_approval_group_ids', 'in', [12])]",
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                (
                    "['|', "
                    "('wf_actor_approval_group_ids', 'in', [21]), "
                    "'&', "
                    "('wf_actor_approval_group_ids', 'in', [19]), "
                    "('last_approver_id.stage_age_minutes', '<', 5)]"
                ),
                "request_scope",
                "workflow.base.approval.request",
            ),
            (
                "workflow.base.approval.request",
                "[('current_action_key', '=', 'submit')]",
                "field_modifiers",
                False,
            ),
        ]

        for model_name, expression, scope, request_model in cases:
            result = validator.workflow_studio_validate_domain_expression(
                model_name,
                expression,
                scope,
                request_model,
            )
            self.assertTrue(
                result.get("valid"),
                "Domain should be valid for scope '%s': %s (error=%s)"
                % (scope, expression, result.get("error")),
            )

    def test_domain_preset_catalog_is_supported_by_server_validator(self):
        validator = self.env["workflow.approval.category.version"]
        request_model = "workflow.base.approval.request"
        catalog_scopes = {
            "generic": (request_model, "request_scope"),
            "user_assignment": ("res.users", "assignment_users"),
            "request_scope": (request_model, "request_scope"),
            "action_visibility": (request_model, "request_scope"),
            "routing_user_assignment": ("res.users", "assignment_users_routing"),
            "routing_request_scope": (request_model, "request_scope_routing"),
        }

        for catalog, (target_model, validation_scope) in catalog_scopes.items():
            for preset in DOMAIN_PRESET_OPTIONS[catalog]:
                with self.subTest(catalog=catalog, preset=preset["key"]):
                    result = validator.workflow_studio_validate_domain_expression(
                        target_model,
                        preset["domain"],
                        validation_scope,
                        request_model,
                    )
                    self.assertTrue(result.get("valid"), result.get("error"))
                    self.assertFalse(result.get("ignored"), result.get("warning"))

        action_always = next(
            preset
            for preset in DOMAIN_PRESET_OPTIONS["action_visibility"]
            if preset["key"] == "always"
        )
        self.assertEqual(action_always["domain"], "[(1, '=', 1)]")
