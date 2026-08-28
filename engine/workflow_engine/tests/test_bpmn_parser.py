# -*- coding: utf-8 -*-

from odoo.tests import common

from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE


TEST_BPMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
    xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
    xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
    id="Defs_Test"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Test" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_Submit" name="Submit">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:exclusiveGateway id="Gateway_1" name="Route">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
      <bpmn:outgoing>Flow_4</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:userTask id="Task_Approve" name="Approve">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:outgoing>Flow_5</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:endEvent id="EndEvent_Reject" name="Reject End">
      <bpmn:incoming>Flow_4</bpmn:incoming>
    </bpmn:endEvent>
    <bpmn:endEvent id="EndEvent_Approve" name="Approve End">
      <bpmn:incoming>Flow_5</bpmn:incoming>
      <bpmn:messageEventDefinition id="MessageDef_1"/>
    </bpmn:endEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_Submit"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Submit" targetRef="Gateway_1" name="To Route"/>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Gateway_1" targetRef="Task_Approve">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;=', 1000)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_4" sourceRef="Gateway_1" targetRef="EndEvent_Reject">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&lt;', 1000)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_5" sourceRef="Task_Approve" targetRef="EndEvent_Approve"/>
  </bpmn:process>
</bpmn:definitions>
"""


class TestBpmnParser(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.engine = BpmnEngine(TEST_BPMN_XML)

    def test_element_type_supports_gateway_and_end_event_variants(self):
        gateway = self.engine.get_element_by_id("Gateway_1")
        end_message = self.engine.get_element_by_id("EndEvent_Approve")
        self.assertEqual(self.engine.get_element_type(gateway), NODE_TYPE["EXCLUSIVE_GATEWAY"])
        self.assertEqual(self.engine.get_element_type(end_message), NODE_TYPE["END_EVENT_WITH_MESSAGE"])
        self.assertTrue(self.engine.is_end_event(end_message))

    def test_meta_tasks_and_actions_include_gateway_paths(self):
        meta_tasks, meta_actions = self.engine.get_meta_tasks_and_actions()
        task_node_ids = {task["node_id"] for task in meta_tasks}
        action_keys = {(action["source_id"], action["target_id"]) for action in meta_actions}

        self.assertIn("Gateway_1", task_node_ids, "Gateway should be synchronized as supported node.")
        self.assertIn(("Task_Submit", "Gateway_1"), action_keys, "Direct flow to gateway must create action.")
        self.assertIn(("Gateway_1", "Task_Approve"), action_keys, "Gateway outgoing branch should be represented.")
        self.assertIn(("Gateway_1", "EndEvent_Reject"), action_keys, "Gateway alternate branch should be represented.")
        approve_branch = next(
            action
            for action in meta_actions
            if action["source_id"] == "Gateway_1" and action["target_id"] == "Task_Approve"
        )
        reject_branch = next(
            action
            for action in meta_actions
            if action["source_id"] == "Gateway_1" and action["target_id"] == "EndEvent_Reject"
        )
        self.assertIn("x_amount", approve_branch["domain"])
        self.assertIn("x_amount", reject_branch["domain"])

    def test_get_next_elements_can_skip_condition_evaluation_for_design_time(self):
        gateway = self.engine.get_element_by_id("Gateway_1")
        design_time_targets = self.engine.get_next_elements(
            gateway,
            form_data={},
            evaluate_conditions=False,
        )
        runtime_targets_high = self.engine.get_next_elements(gateway, form_data={"x_amount": 1200})
        runtime_targets_low = self.engine.get_next_elements(gateway, form_data={"x_amount": 300})

        design_target_ids = {el.attrib.get("id") for el in design_time_targets}
        self.assertEqual(design_target_ids, {"Task_Approve", "EndEvent_Reject"})
        self.assertEqual(runtime_targets_high[0].attrib.get("id"), "Task_Approve")
        self.assertEqual(runtime_targets_low[0].attrib.get("id"), "EndEvent_Reject")

    def test_gateway_runtime_semantics_are_distinct(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_GatewaySemantics">
  <bpmn:process id="Process_GatewaySemantics" isExecutable="true">
    <bpmn:exclusiveGateway id="Gateway_Exclusive">
      <bpmn:outgoing>Flow_Ex_A</bpmn:outgoing>
      <bpmn:outgoing>Flow_Ex_B</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:parallelGateway id="Gateway_Parallel">
      <bpmn:outgoing>Flow_Par_A</bpmn:outgoing>
      <bpmn:outgoing>Flow_Par_B</bpmn:outgoing>
    </bpmn:parallelGateway>
    <bpmn:inclusiveGateway id="Gateway_Inclusive">
      <bpmn:outgoing>Flow_In_A</bpmn:outgoing>
      <bpmn:outgoing>Flow_In_B</bpmn:outgoing>
    </bpmn:inclusiveGateway>
    <bpmn:userTask id="Task_A"/>
    <bpmn:userTask id="Task_B"/>
    <bpmn:sequenceFlow id="Flow_Ex_A" sourceRef="Gateway_Exclusive" targetRef="Task_A">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;', 0)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_Ex_B" sourceRef="Gateway_Exclusive" targetRef="Task_B">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;', 0)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_Par_A" sourceRef="Gateway_Parallel" targetRef="Task_A">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;', 1000)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_Par_B" sourceRef="Gateway_Parallel" targetRef="Task_B">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&lt;', 0)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_In_A" sourceRef="Gateway_Inclusive" targetRef="Task_A">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;', 0)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_In_B" sourceRef="Gateway_Inclusive" targetRef="Task_B">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">[('x_amount', '&gt;', 10)]</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
  </bpmn:process>
</bpmn:definitions>
"""
        engine = BpmnEngine(xml)

        exclusive_targets = engine.get_next_elements(
            engine.get_element_by_id("Gateway_Exclusive"),
            form_data={"x_amount": 20},
        )
        parallel_targets = engine.get_next_elements(
            engine.get_element_by_id("Gateway_Parallel"),
            form_data={"x_amount": 20},
        )
        inclusive_targets = engine.get_next_elements(
            engine.get_element_by_id("Gateway_Inclusive"),
            form_data={"x_amount": 20},
        )

        self.assertEqual([node.attrib.get("id") for node in exclusive_targets], ["Task_A"])
        self.assertEqual(
            {node.attrib.get("id") for node in parallel_targets},
            {"Task_A", "Task_B"},
        )
        self.assertEqual(
            {node.attrib.get("id") for node in inclusive_targets},
            {"Task_A", "Task_B"},
        )

    def test_node_profile_contract_for_recommended_nodes(self):
        send_profile = self.engine.get_node_metadata_profile(NODE_TYPE["SEND_TASK"])
        script_profile = self.engine.get_node_metadata_profile(NODE_TYPE["SCRIPT_TASK"])
        inclusive_profile = self.engine.get_node_metadata_profile(NODE_TYPE["INCLUSIVE_GATEWAY"])

        self.assertEqual(send_profile.get("meta_role"), "notification")
        self.assertEqual(script_profile.get("meta_role"), "server_action")
        self.assertEqual(inclusive_profile.get("meta_role"), "conditional_router")

    def test_evaluate_condition_supports_nested_logic_and_in_operator(self):
        condition = "['&', ('x_amount', '>', 500), '|', ('x_branch', '=', 'Gaming'), ('x_branch', 'in', ['Hotel', 'Shared'])]"
        self.assertTrue(
            self.engine.evaluate_condition(
                condition,
                {"x_amount": 700, "x_branch": "Shared"},
            )
        )
        self.assertFalse(
            self.engine.evaluate_condition(
                condition,
                {"x_amount": 300, "x_branch": "Shared"},
            )
        )
        self.assertFalse(
            self.engine.evaluate_condition(
                condition,
                {"x_amount": 700, "x_branch": "Other"},
            )
        )

    def test_evaluate_condition_supports_not_ilike_and_dotted_path(self):
        condition = "['&', '!', ('x_status', '=', 'cancelled'), ('x_department.name', 'ilike', 'finance')]"
        self.assertTrue(
            self.engine.evaluate_condition(
                condition,
                {
                    "x_status": "approved",
                    "x_department": {"name": "Finance Hotel"},
                },
            )
        )
        self.assertFalse(
            self.engine.evaluate_condition(
                condition,
                {
                    "x_status": "cancelled",
                    "x_department": {"name": "Finance Hotel"},
                },
            )
        )
        self.assertFalse(
            self.engine.evaluate_condition(
                condition,
                {
                    "x_status": "approved",
                    "x_department": {"name": "IT"},
                },
            )
        )
