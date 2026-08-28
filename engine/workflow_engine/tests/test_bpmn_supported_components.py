# -*- coding: utf-8 -*-
from odoo.tests import common


TIMER_ACTION_BPMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Definitions_TimerAction"
    targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_TimerAction" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1" name="Start">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:userTask id="Task_1" name="Submission">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
    </bpmn:userTask>
    <bpmn:intermediateCatchEvent id="Event_Timer" name="Auto Timeout">
      <bpmn:incoming>Flow_2</bpmn:incoming>
      <bpmn:outgoing>Flow_3</bpmn:outgoing>
      <bpmn:timerEventDefinition id="TimerEventDefinition_1" />
    </bpmn:intermediateCatchEvent>
    <bpmn:intermediateThrowEvent id="Event_End" name="End">
      <bpmn:incoming>Flow_3</bpmn:incoming>
      <bpmn:signalEventDefinition id="SignalEventDefinition_1" />
    </bpmn:intermediateThrowEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_1" />
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_1" targetRef="Event_Timer" />
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Event_Timer" targetRef="Event_End" />
  </bpmn:process>
</bpmn:definitions>
"""


class TestBpmnSupportedComponents(common.TransactionCase):
    def test_timer_intermediate_event_syncs_as_auto_action(self):
        base_request_model = self.env["ir.model"]._get("workflow.base.approval.request")
        category = self.env["workflow.approval.category"].sudo().create(
            {
                "name": "Timer Support Category",
                "res_model": base_request_model.id,
            }
        )
        version = self.env["workflow.approval.category.version"].sudo().create(
            {
                "name": "v_timer_support",
                "category_id": category.id,
                "bpmn_xml": TIMER_ACTION_BPMN_XML,
            }
        )

        timer_action = self.env["workflow.category.version.meta.task.action"].sudo().search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", "Task_1"),
                ("node_id", "=", "Flow_2"),
            ],
            limit=1,
        )
        self.assertTrue(timer_action, "Expected timer action metadata to be synchronized from BPMN.")
        self.assertEqual(timer_action.flow_type, "autoAction")
        self.assertEqual(timer_action.target_node_type, "timerEvent")
