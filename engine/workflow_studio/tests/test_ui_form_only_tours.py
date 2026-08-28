# -*- coding: utf-8 -*-

import odoo.tests

from odoo.tests import tagged


@tagged("post_install", "-at_install", "ws_patch")
class TestWorkflowStudioFormOnlyTours(odoo.tests.HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        model, _ = cls.env["ir.model"].studio_model_create(
            "Workflow Studio Form Tour Model",
            options=["has_approval"],
        )
        category = cls.env["workflow.approval.category"].search(
            [("res_model", "=", model.id)],
            order="id desc",
            limit=1,
        )
        if not category:
            category = cls.env["workflow.approval.category"].create(
                {
                    "name": "Workflow Studio Form Tour Category",
                    "res_model": model.id,
                }
            )

        context = {
            "active_id": category.id,
            "active_ids": [category.id],
            "active_model": "workflow.approval.category",
        }

        cls.test_action = cls.env["ir.actions.client"].create(
            {
                "name": "workflow_studio.form_only.test.action",
                "tag": "workflow_studio.open_workflow_studio",
                "target": "current",
                "params": {
                    "model": model.model,
                    "name": model.name,
                    "context": context,
                    "editor_tab": "views",
                },
            }
        )

    def test_open_form_editor_tour(self):
        start_url = f"/odoo/action-{self.test_action.id}?debug=tests"
        self.start_tour(
            start_url,
            "workflow_studio_form_editor_tour",
            login="admin",
            cookies={"color_scheme": "dark"},
        )
