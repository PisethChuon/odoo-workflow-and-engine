# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("ws_patch")
class TestWorkflowStudioQuickStartWizard(TransactionCase):
    def _unique_name(self, prefix):
        return f"{prefix} {uuid4().hex[:8]}"

    def test_create_new_model_path_creates_approval_enabled_model(self):
        model_name = self._unique_name("Quick Start Model")
        category_name = self._unique_name("Quick Start Category")
        wizard = self.env["workflow.studio.quick.start.wizard"].create(
            {
                "model_source": "create_new",
                "model_name": model_name,
                "category_name": category_name,
            }
        )

        action = wizard.action_create_and_open_studio()

        model = self.env["ir.model"].search([("name", "=", model_name)], order="id desc", limit=1)
        self.assertTrue(model, "Quick start should create a model in create-new mode.")
        self.assertTrue(model.is_approval, "Created model must be approval-enabled.")

        category = self.env["workflow.approval.category"].search(
            [("res_model", "=", model.id)],
            order="id desc",
            limit=1,
        )
        self.assertTrue(category, "Quick start should create or reuse a category for the model.")

        context = action.get("params", {}).get("context", {})
        self.assertEqual(context.get("workflow_category_id"), category.id)
        self.assertTrue(
            context.get("workflow_version_id"),
            "Quick start should open Studio with a workflow version in context.",
        )

    def test_use_existing_model_path_accepts_approval_enabled_model(self):
        existing_name = self._unique_name("Existing Approval Model")
        model, _extra_models = self.env["ir.model"].studio_model_create(
            existing_name,
            options=["has_approval"],
        )
        category = self.env["workflow.approval.category"].search(
            [("res_model", "=", model.id)],
            limit=1,
        )
        self.assertTrue(category)
        before_version_ids = set(category.version_ids.ids)

        wizard = self.env["workflow.studio.quick.start.wizard"].create(
            {
                "model_source": "use_existing",
                "existing_model_id": model.id,
                "category_name": self._unique_name("Existing Category"),
            }
        )
        action = wizard.action_create_and_open_studio()

        self.assertEqual(
            self.env["ir.model"].search_count([("model", "=", model.model)]),
            1,
            "Selecting existing model must not create a duplicate model.",
        )

        category.invalidate_recordset()
        after_version_ids = set(category.version_ids.ids)
        self.assertEqual(
            len(after_version_ids),
            len(before_version_ids) + 1,
            "Quick start should create a new editable version for existing model flow.",
        )

        created_version_ids = after_version_ids - before_version_ids
        context = action.get("params", {}).get("context", {})
        self.assertIn(context.get("workflow_version_id"), created_version_ids)
        self.assertEqual(context.get("workflow_category_id"), category.id)

    def test_use_existing_model_requires_approval_enabled_model(self):
        plain_name = self._unique_name("Plain Model")
        plain_model, _extra_models = self.env["ir.model"].studio_model_create(
            plain_name,
            options=[],
        )
        self.assertFalse(plain_model.is_approval)

        wizard = self.env["workflow.studio.quick.start.wizard"].create(
            {
                "model_source": "use_existing",
                "existing_model_id": plain_model.id,
            }
        )
        with self.assertRaises(UserError):
            wizard.action_create_and_open_studio()
