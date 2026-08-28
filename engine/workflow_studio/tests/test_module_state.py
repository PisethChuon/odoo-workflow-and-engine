from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("ws_patch")
class TestWorkflowStudioCustomizationModuleState(TransactionCase):
    def test_get_studio_module_repairs_inconsistent_state(self):
        module_model = self.env["ir.module.module"]
        module = module_model.get_studio_module()

        module.write(
            {
                "state": "to upgrade",
                "imported": False,
                "shortdesc": "Broken",
            }
        )

        repaired = module_model.get_studio_module()
        self.assertEqual(repaired.id, module.id)
        self.assertEqual(repaired.state, "installed")
        self.assertTrue(repaired.imported)
        self.assertEqual(repaired.shortdesc, "Workflow Studio customizations")
        self.assertFalse(repaired.dependencies_id)

    def test_button_install_on_customization_module_is_noop(self):
        module_model = self.env["ir.module.module"]
        module = module_model.get_studio_module()
        module.button_install()
        self.assertEqual(module.state, "installed")

    def test_button_upgrade_keeps_customization_module_installed(self):
        module_model = self.env["ir.module.module"]
        module = module_model.get_studio_module()

        workflow_modules = module_model.search(
            [("name", "in", ("workflow_engine", "workflow_studio"))]
        )
        self.assertTrue(workflow_modules, "Workflow modules must exist for this regression test.")

        workflow_modules.button_upgrade()
        module.flush_recordset(["state"])
        self.assertEqual(module.state, "installed")
