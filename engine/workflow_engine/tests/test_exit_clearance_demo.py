# -*- coding: utf-8 -*-

from odoo.tests import common


class TestExitClearanceDemo(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env.ref(
            "workflow_engine.workflow_category_exit_clearance_demo",
            raise_if_not_found=False,
        )
        cls.version = cls.env.ref(
            "workflow_engine.workflow_category_exit_clearance_demo_version_v1",
            raise_if_not_found=False,
        )

    def _skip_if_demo_missing(self):
        if not self.category or not self.version:
            self.skipTest("Exit Clearance demo data is not installed; run with demo data enabled.")

    def test_exit_clearance_demo_has_active_version_and_bpmn(self):
        self._skip_if_demo_missing()

        self.assertEqual(
            self.category.active_version_id.id,
            self.version.id,
            "Exit Clearance category should point to v1 as active version.",
        )
        self.assertIn("Process_ExitClearance", self.version.bpmn_xml or "")
        self.assertIn("Task_ITClearance", self.version.bpmn_xml or "")
        self.assertIn("Task_HRFinalClearance", self.version.bpmn_xml or "")

    def test_exit_clearance_demo_assignment_and_group_links(self):
        self._skip_if_demo_missing()

        meta_task_model = self.env["workflow.category.version.meta.task"]
        link_model = self.env["workflow.category.task.approval.group"]

        expected_assignment_modes = {
            "Task_Submission": "request_owner",
            "Task_RequestorRework": "request_owner",
            "Task_HODDecision": "groups",
            "Task_ITClearance": "groups",
            "Task_FinanceClearance": "groups",
            "Task_AdminClearance": "groups",
            "Task_SecurityClearance": "groups",
            "Task_FacilityClearance": "groups",
            "Task_PurchaseClearance": "groups",
            "Task_OperationsClearance": "groups",
            "Task_HRDeptClearance": "groups",
            "Task_HODFinalReview": "groups",
            "Task_PayrollReview": "groups",
            "Task_HRFinalClearance": "groups",
        }
        department_nodes = {
            "Task_ITClearance",
            "Task_FinanceClearance",
            "Task_AdminClearance",
            "Task_SecurityClearance",
            "Task_FacilityClearance",
            "Task_PurchaseClearance",
            "Task_OperationsClearance",
            "Task_HRDeptClearance",
        }
        required_group_links = {
            "Task_HODDecision": "workflow_engine.approval_group_exit_clearance_hod",
            "Task_ITClearance": "workflow_engine.approval_group_exit_clearance_it",
            "Task_FinanceClearance": "workflow_engine.approval_group_exit_clearance_finance",
            "Task_AdminClearance": "workflow_engine.approval_group_exit_clearance_admin",
            "Task_SecurityClearance": "workflow_engine.approval_group_exit_clearance_security",
            "Task_FacilityClearance": "workflow_engine.approval_group_exit_clearance_facility",
            "Task_PurchaseClearance": "workflow_engine.approval_group_exit_clearance_purchase",
            "Task_OperationsClearance": "workflow_engine.approval_group_exit_clearance_operations",
            "Task_HRDeptClearance": "workflow_engine.approval_group_exit_clearance_hr",
            "Task_HODFinalReview": "workflow_engine.approval_group_exit_clearance_hod",
            "Task_PayrollReview": "workflow_engine.approval_group_exit_clearance_payroll",
            "Task_HRFinalClearance": "workflow_engine.approval_group_exit_clearance_hr",
        }

        for node_id, assignment_mode in expected_assignment_modes.items():
            task = meta_task_model.search(
                [("version_id", "=", self.version.id), ("node_id", "=", node_id)],
                limit=1,
            )
            self.assertTrue(task, "Expected metadata task for node %s." % node_id)
            self.assertEqual(task.assignment_mode, assignment_mode)

            if node_id in department_nodes:
                self.assertEqual(task.join_key, "exit_clearance_departments")
                self.assertEqual(task.gateway_node_id, "Gateway_DeptJoin")
                self.assertEqual(task.join_policy, "all_of")
                self.assertEqual(task.parallel_reject_policy, "strict")

        for node_id, group_xmlid in required_group_links.items():
            task = meta_task_model.search(
                [("version_id", "=", self.version.id), ("node_id", "=", node_id)],
                limit=1,
            )
            group = self.env.ref(group_xmlid)
            link = link_model.search(
                [
                    ("meta_id", "=", task.id),
                    ("approval_group_id", "=", group.id),
                ],
                limit=1,
            )
            self.assertTrue(link, "Expected approval-group link for node %s." % node_id)

    def test_exit_clearance_demo_runtime_controls_for_parallel_departments(self):
        self._skip_if_demo_missing()

        task_model = self.env["workflow.category.version.meta.task"]

        department_nodes = {
            "Task_HODDecision",
            "Task_ITClearance",
            "Task_FinanceClearance",
            "Task_AdminClearance",
            "Task_SecurityClearance",
            "Task_FacilityClearance",
            "Task_PurchaseClearance",
            "Task_OperationsClearance",
            "Task_HRDeptClearance",
            "Task_HRFinalClearance",
        }
        restricted_nodes = {
            "Task_HODFinalReview",
            "Task_PayrollReview",
            "Task_HRFinalClearance",
        }

        for node_id in department_nodes | restricted_nodes:
            task = task_model.search(
                [("version_id", "=", self.version.id), ("node_id", "=", node_id)],
                limit=1,
            )
            self.assertTrue(task, "Expected metadata task for node %s." % node_id)

            if node_id in department_nodes:
                self.assertTrue(
                    task.requires_department_payload,
                    "Task %s must require department-scoped payload for parallel safety." % node_id,
                )
                self.assertEqual(task.completion_mode, "all")
                self.assertEqual(task.fallback_policy, "route_admin_queue")

            if node_id in restricted_nodes:
                self.assertEqual(
                    task.confidentiality_level,
                    "restricted",
                    "Task %s should be restricted at final review stages." % node_id,
                )
