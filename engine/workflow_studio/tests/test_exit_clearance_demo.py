# -*- coding: utf-8 -*-

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("ws_patch")
class TestExitClearanceStudioDemo(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.version = cls.env.ref(
            "workflow_engine.workflow_category_exit_clearance_demo_version_v1",
            raise_if_not_found=False,
        )

    def _skip_if_demo_missing(self):
        if not self.version:
            self.skipTest("Exit Clearance demo data is not installed; run with demo data enabled.")

    def test_exit_clearance_demo_bpmn_payload_available_in_studio(self):
        self._skip_if_demo_missing()

        payload = self.version.workflow_studio_get_bpmn_payload()
        bpmn_xml = payload.get("version", {}).get("bpmn_xml") or payload.get("bpmn_xml") or ""
        self.assertIn("Process_ExitClearance", bpmn_xml)

        meta_tasks = payload.get("meta", {}).get("tasks", [])
        task_node_ids = {task.get("node_id") for task in meta_tasks}
        self.assertIn("Task_ITClearance", task_node_ids)
        self.assertIn("Task_HRFinalClearance", task_node_ids)

    def test_exit_clearance_demo_task_links_can_be_reconfigured_in_studio(self):
        self._skip_if_demo_missing()

        it_group = self.env.ref("workflow_engine.approval_group_exit_clearance_it")

        result = self.version.workflow_studio_set_task_approval_links(
            "Task_ITClearance",
            [
                {
                    "approval_group_ref": {"id": it_group.id},
                    "sequence": 10,
                    "user_domain": "[('active', '=', True)]",
                    "domain": "[(1, '=', 1)]",
                    "note": "Studio reassignment test",
                }
            ],
        )

        self.assertFalse(result.get("warnings"), "Task assignment link update should be clean.")
        rows = result.get("rows") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("approval_group_ref", {}).get("id"), it_group.id)

        updated_task = self.version.workflow_studio_write_meta_task(
            "Task_ITClearance",
            {
                "assignment_mode": "groups",
                "completion_mode": "all",
                "fallback_policy": "route_admin_queue",
            },
        )
        self.assertEqual(updated_task.get("assignment_mode"), "groups")
