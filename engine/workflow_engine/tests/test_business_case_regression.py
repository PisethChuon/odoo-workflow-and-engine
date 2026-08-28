# -*- coding: utf-8 -*-

from pathlib import Path

from odoo.tests import common, tagged

from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE


@tagged("business_case_regression")
class TestWorkflowBusinessCaseRegression(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.flow_root = Path(__file__).resolve().parents[1] / "demo" / "flow" / "all_flows_bpmn"
        cls.exit_flow_files = sorted(
            path.name for path in cls.flow_root.glob("exit_clearance_form__*.bpmn")
        )
        cls.bcj_flow_files = sorted(path.name for path in cls.flow_root.glob("finance__bcj*.bpmn"))
        cls.maintenance_flow_files = sorted(
            path.name for path in cls.flow_root.glob("maintenance__*.bpmn")
        )
        cls.medical_flow_files = ["hr__hr_medical_treatment.bpmn"]
        cls.maintenance_medical_flow_files = cls.maintenance_flow_files + cls.medical_flow_files

        cls.bcj_engine = BpmnEngine(
            (cls.flow_root / "finance__bcj.bpmn").read_text(encoding="utf-8")
        )
        cls.exit_engine = BpmnEngine(
            (cls.flow_root / "exit_clearance_form__exit_clearance_form_25july2024.bpmn").read_text(
                encoding="utf-8"
            )
        )
        cls.maintenance_engine = BpmnEngine(
            (
                cls.flow_root
                / "maintenance__maintenance_work_order_request_form_v7_2023may18.bpmn"
            ).read_text(encoding="utf-8")
        )

    def _next_node_ids(self, engine, node_id, form_data=None, evaluate_conditions=True):
        node = engine.get_element_by_id(node_id)
        self.assertIsNotNone(node, "Expected node %s in BPMN flow." % node_id)
        return [
            element.attrib.get("id")
            for element in engine.get_next_elements(
                node, form_data=form_data or {}, evaluate_conditions=evaluate_conditions
            )
        ]

    def _assert_has_path(self, engine, source_id, target_id):
        targets = {row.get("target") for row in engine.sequence_flows.get(source_id, [])}
        self.assertIn(
            target_id,
            targets,
            "Expected BPMN path %s -> %s to exist." % (source_id, target_id),
        )

    def _engine_for(self, file_name):
        return BpmnEngine((self.flow_root / file_name).read_text(encoding="utf-8"))

    def test_bcj_finance_gateway_routes_by_amount_and_branch(self):
        routing_cases = [
            ({"total_amount": 300, "branch_company": "gaming"}, "Task_FinanceGaming"),
            ({"total_amount": 300, "branch_company": "hotel"}, "Task_FinanceHotel"),
            ({"total_amount": 300, "branch_company": "others"}, "Task_GroupFinance"),
            ({"total_amount": 1000, "branch_company": "gaming"}, "Task_CFO_DYCFO"),
            ({"total_amount": 120000, "branch_company": "gaming"}, "Task_CFO"),
        ]

        for form_data, expected_target in routing_cases:
            next_ids = self._next_node_ids(
                self.bcj_engine,
                "Gateway_FinanceRoute",
                form_data=form_data,
            )
            self.assertEqual(
                next_ids,
                [expected_target],
                "BCJ finance route should resolve exactly one branch for %s." % form_data,
            )

        unmatched = self._next_node_ids(
            self.bcj_engine,
            "Gateway_FinanceRoute",
            form_data={"total_amount": 300, "branch_company": "unknown"},
        )
        self.assertEqual(
            unmatched,
            [],
            "BCJ finance route should stay unresolved when no branch condition matches.",
        )

    def test_bcj_rework_and_reject_paths_preserve_business_loops(self):
        # Rework loops from the business specification.
        self._assert_has_path(self.bcj_engine, "Event_HODReworked", "Task_Submitter")
        self._assert_has_path(self.bcj_engine, "Event_LineReworked", "Task_HODApproval")
        self._assert_has_path(self.bcj_engine, "Event_DeptExecReworked", "Task_LineDepartment")
        self._assert_has_path(self.bcj_engine, "Event_FinanceReworked", "Task_DepartmentExecutive")

        # Reject flows converge to rejected end event.
        self._assert_has_path(self.bcj_engine, "Event_HODRejected", "EndEvent_Rejected")
        self._assert_has_path(self.bcj_engine, "Event_LineRejected", "EndEvent_Rejected")
        self._assert_has_path(self.bcj_engine, "Event_DeptExecRejected", "EndEvent_Rejected")
        self._assert_has_path(self.bcj_engine, "Event_FinanceRejected", "EndEvent_Rejected")

    def test_exit_parallel_departments_and_offboard_gateways(self):
        dept_branches = set(
            self._next_node_ids(self.exit_engine, "Gateway_DeptSplit", form_data={"id": 1})
        )
        self.assertEqual(
            dept_branches,
            {
                "Task_ITClearance",
                "Task_FinanceClearance",
                "Task_AdminClearance",
                "Task_SecurityClearance",
                "Task_FacilityClearance",
                "Task_PurchaseClearance",
                "Task_OperationsClearance",
                "Task_HRDeptClearance",
            },
            "Exit flow must keep all department branches in parallel split.",
        )

        offboard_node = self.exit_engine.get_element_by_id("Gateway_OffboardRoute")
        self.assertEqual(
            self.exit_engine.get_element_type(offboard_node),
            NODE_TYPE["INCLUSIVE_GATEWAY"],
        )

        employee_routes = set(
            self._next_node_ids(
                self.exit_engine,
                "Gateway_OffboardRoute",
                form_data={"request_owner_emp_type": "employee", "id": 1},
            )
        )
        self.assertEqual(
            employee_routes,
            {"Task_DisableAccounts", "Task_NotifyChannels"},
            "Employee offboard route should execute both disable-account and notify branches.",
        )

        non_employee_routes = self._next_node_ids(
            self.exit_engine,
            "Gateway_OffboardRoute",
            form_data={"request_owner_emp_type": "non_employee", "id": 1},
        )
        self.assertEqual(
            non_employee_routes,
            ["Task_NotifyChannels"],
            "Non-employee offboard route should keep notification branch only.",
        )

    def test_maintenance_exclusive_gateway_prefers_conditional_branch(self):
        conditional_match = self._next_node_ids(
            self.maintenance_engine,
            "Gateway_Route_P1833323d",
            form_data={"need_additional_approval": True},
        )
        self.assertEqual(
            conditional_match,
            ["Task_AdditionalApproval_P1833323d"],
            "When additional approval is required, maintenance route must not fall through default branch.",
        )

        fallback_match = self._next_node_ids(
            self.maintenance_engine,
            "Gateway_Route_P1833323d",
            form_data={"need_additional_approval": False},
        )
        self.assertEqual(
            fallback_match,
            ["EndEvent_Completed_P1833323d"],
            "When additional approval is not required, maintenance route should use default completion path.",
        )

        design_time_targets = set(
            self._next_node_ids(
                self.maintenance_engine,
                "Gateway_Route_P1833323d",
                form_data={"need_additional_approval": True},
                evaluate_conditions=False,
            )
        )
        self.assertEqual(
            design_time_targets,
            {"Task_AdditionalApproval_P1833323d", "EndEvent_Completed_P1833323d"},
            "Design-time route discovery should still expose all outgoing branches.",
        )

    def test_exit_family_revisions_keep_parallel_and_offboard_routing(self):
        self.assertTrue(
            self.exit_flow_files,
            "Expected exit clearance revision flows under demo bundle.",
        )
        expected_branches = {
            "Task_ITClearance",
            "Task_FinanceClearance",
            "Task_AdminClearance",
            "Task_SecurityClearance",
            "Task_FacilityClearance",
            "Task_PurchaseClearance",
            "Task_OperationsClearance",
            "Task_HRDeptClearance",
        }
        for file_name in self.exit_flow_files:
            engine = self._engine_for(file_name)
            dept_branches = set(
                self._next_node_ids(engine, "Gateway_DeptSplit", form_data={"id": 1})
            )
            self.assertEqual(
                dept_branches,
                expected_branches,
                "Department parallel split changed unexpectedly in %s." % file_name,
            )
            employee_routes = set(
                self._next_node_ids(
                    engine,
                    "Gateway_OffboardRoute",
                    form_data={"request_owner_emp_type": "employee", "id": 1},
                )
            )
            self.assertEqual(
                employee_routes,
                {"Task_DisableAccounts", "Task_NotifyChannels"},
                "Employee offboard routing changed unexpectedly in %s." % file_name,
            )
            non_employee_routes = self._next_node_ids(
                engine,
                "Gateway_OffboardRoute",
                form_data={"request_owner_emp_type": "non_employee", "id": 1},
            )
            self.assertEqual(
                non_employee_routes,
                ["Task_NotifyChannels"],
                "Non-employee offboard routing changed unexpectedly in %s." % file_name,
            )

    def test_bcj_family_revisions_keep_finance_and_modification_routing(self):
        self.assertTrue(
            self.bcj_flow_files,
            "Expected BCJ revision flows under demo bundle.",
        )
        routing_cases = [
            ({"total_amount": 300, "branch_company": "gaming"}, "Task_FinanceGaming"),
            ({"total_amount": 300, "branch_company": "hotel"}, "Task_FinanceHotel"),
            ({"total_amount": 300, "branch_company": "others"}, "Task_GroupFinance"),
            ({"total_amount": 1000, "branch_company": "gaming"}, "Task_CFO_DYCFO"),
            ({"total_amount": 120000, "branch_company": "gaming"}, "Task_CFO"),
        ]
        for file_name in self.bcj_flow_files:
            engine = self._engine_for(file_name)
            for form_data, expected_target in routing_cases:
                next_ids = self._next_node_ids(
                    engine,
                    "Gateway_FinanceRoute",
                    form_data=form_data,
                )
                self.assertEqual(
                    next_ids,
                    [expected_target],
                    "Finance route changed unexpectedly in %s for %s." % (file_name, form_data),
                )
            unmatched = self._next_node_ids(
                engine,
                "Gateway_FinanceRoute",
                form_data={"total_amount": 300, "branch_company": "unknown"},
            )
            self.assertEqual(
                unmatched,
                [],
                "Unmatched finance branch should stay unresolved in %s." % file_name,
            )

            mod_yes = self._next_node_ids(
                engine,
                "Gateway_ModificationWindow",
                form_data={"allow_modification": True},
            )
            self.assertEqual(
                mod_yes,
                ["Task_Modification"],
                "Modification window True branch changed unexpectedly in %s." % file_name,
            )
            mod_no = self._next_node_ids(
                engine,
                "Gateway_ModificationWindow",
                form_data={"allow_modification": False},
            )
            self.assertEqual(
                mod_no,
                ["EndEvent_Completed"],
                "Modification window fallback changed unexpectedly in %s." % file_name,
            )

    def test_maintenance_and_medical_revisions_keep_default_gateway_contract(self):
        self.assertTrue(
            self.maintenance_medical_flow_files,
            "Expected maintenance/medical revision flows under demo bundle.",
        )
        for file_name in self.maintenance_medical_flow_files:
            engine = self._engine_for(file_name)
            route_node_ids = sorted(
                node_id
                for node_id, element in engine.elements_by_id.items()
                if node_id.startswith("Gateway_Route")
                and engine.get_element_type(element) == NODE_TYPE["EXCLUSIVE_GATEWAY"]
            )
            self.assertTrue(
                route_node_ids,
                "Expected exclusive route gateway in %s." % file_name,
            )
            for route_node_id in route_node_ids:
                conditional_targets = self._next_node_ids(
                    engine,
                    route_node_id,
                    form_data={"need_additional_approval": True},
                )
                self.assertEqual(
                    len(conditional_targets),
                    1,
                    "Conditional route should resolve one target in %s (%s)."
                    % (file_name, route_node_id),
                )
                self.assertTrue(
                    conditional_targets[0].startswith("Task_AdditionalApproval"),
                    "Conditional route should target additional approval node in %s (%s)."
                    % (file_name, route_node_id),
                )

                fallback_targets = self._next_node_ids(
                    engine,
                    route_node_id,
                    form_data={"need_additional_approval": False},
                )
                self.assertEqual(
                    len(fallback_targets),
                    1,
                    "Fallback route should resolve one target in %s (%s)."
                    % (file_name, route_node_id),
                )
                self.assertTrue(
                    fallback_targets[0].startswith("EndEvent_Completed"),
                    "Fallback route should target completed end event in %s (%s)."
                    % (file_name, route_node_id),
                )

                design_targets = set(
                    self._next_node_ids(
                        engine,
                        route_node_id,
                        form_data={"need_additional_approval": True},
                        evaluate_conditions=False,
                    )
                )
                self.assertIn(
                    conditional_targets[0],
                    design_targets,
                    "Design-time graph should include conditional branch in %s (%s)."
                    % (file_name, route_node_id),
                )
                self.assertIn(
                    fallback_targets[0],
                    design_targets,
                    "Design-time graph should include fallback branch in %s (%s)."
                    % (file_name, route_node_id),
                )

    def test_full_reference_flows_still_sync_meta_tasks_and_actions(self):
        flow_expectations = {
            "finance__bcj.bpmn": {
                "nodes": {"Gateway_FinanceRoute", "Task_Purchasing", "Task_Modification"},
                "actions": {
                    ("Gateway_FinanceRoute", "Task_FinanceGaming"),
                    ("Gateway_ModificationWindow", "Task_Modification"),
                },
            },
            "exit_clearance_form__exit_clearance_form_25july2024.bpmn": {
                "nodes": {"Gateway_DeptSplit", "Task_DisableAccounts", "Task_NotifyChannels"},
                "actions": {
                    ("Gateway_DeptSplit", "Task_ITClearance"),
                    ("Gateway_OffboardRoute", "Task_DisableAccounts"),
                },
            },
            "maintenance__maintenance_work_order_request_form_v7_2023may18.bpmn": {
                "nodes": {"Gateway_Route_P1833323d", "Task_AdditionalApproval_P1833323d"},
                "actions": {
                    ("Gateway_Route_P1833323d", "Task_AdditionalApproval_P1833323d"),
                    ("Gateway_Route_P1833323d", "EndEvent_Completed_P1833323d"),
                },
            },
            "finance__bcj_routing.bpmn": {
                "nodes": {"Gateway_FinanceRoute", "Task_Purchasing", "Task_Modification"},
                "actions": {
                    ("Gateway_FinanceRoute", "Task_FinanceGaming"),
                    ("Gateway_ModificationWindow", "Task_Modification"),
                },
            },
            "maintenance__maintenance_work_order_request_form.bpmn": {
                "nodes": {"Gateway_Route_P6b26d972", "Task_AdditionalApproval_P6b26d972"},
                "actions": {
                    ("Gateway_Route_P6b26d972", "Task_AdditionalApproval_P6b26d972"),
                    ("Gateway_Route_P6b26d972", "EndEvent_Completed_P6b26d972"),
                },
            },
            "maintenance__maintenance_work_order_request_form_v5_23_nov_2020.bpmn": {
                "nodes": {"Gateway_Route_P30fb5b1a", "Task_AdditionalApproval_P30fb5b1a"},
                "actions": {
                    ("Gateway_Route_P30fb5b1a", "Task_AdditionalApproval_P30fb5b1a"),
                    ("Gateway_Route_P30fb5b1a", "EndEvent_Completed_P30fb5b1a"),
                },
            },
            "maintenance__maintenance_work_order_request_form_v6_2022no.bpmn": {
                "nodes": {"Gateway_Route_P7a81e526", "Task_AdditionalApproval_P7a81e526"},
                "actions": {
                    ("Gateway_Route_P7a81e526", "Task_AdditionalApproval_P7a81e526"),
                    ("Gateway_Route_P7a81e526", "EndEvent_Completed_P7a81e526"),
                },
            },
            "maintenance__preventive_maintenance_form.bpmn": {
                "nodes": {"Gateway_Route_Pbb33afe4", "Task_AdditionalApproval_Pbb33afe4"},
                "actions": {
                    ("Gateway_Route_Pbb33afe4", "Task_AdditionalApproval_Pbb33afe4"),
                    ("Gateway_Route_Pbb33afe4", "EndEvent_Completed_Pbb33afe4"),
                },
            },
            "hr__hr_medical_treatment.bpmn": {
                "nodes": {"Gateway_Route_P81d845c3", "Task_AdditionalApproval_P81d845c3"},
                "actions": {
                    ("Gateway_Route_P81d845c3", "Task_AdditionalApproval_P81d845c3"),
                    ("Gateway_Route_P81d845c3", "EndEvent_Completed_P81d845c3"),
                },
            },
        }

        for file_name, expectation in flow_expectations.items():
            engine = BpmnEngine((self.flow_root / file_name).read_text(encoding="utf-8"))
            meta_tasks, meta_actions = engine.get_meta_tasks_and_actions()
            task_nodes = {task["node_id"] for task in meta_tasks}
            action_pairs = {(action["source_id"], action["target_id"]) for action in meta_actions}

            self.assertTrue(meta_tasks, "Expected metadata tasks for %s." % file_name)
            self.assertTrue(meta_actions, "Expected metadata actions for %s." % file_name)
            self.assertTrue(
                expectation["nodes"].issubset(task_nodes),
                "Expected core task nodes missing for %s." % file_name,
            )
            self.assertTrue(
                expectation["actions"].issubset(action_pairs),
                "Expected core transition metadata missing for %s." % file_name,
            )
