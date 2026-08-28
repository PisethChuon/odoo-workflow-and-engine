import base64
import io
import zipfile
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("ws_patch")
class TestWorkflowStudioImportZipWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.target_model = cls.env["ir.model"]._get("res.partner")

    def _create_target_category(self, name):
        return self.env["workflow.approval.category"].create(
            {
                "name": name,
                "res_model": self.target_model.id,
            }
        )

    def _make_manifest(self, category):
        return {
            "category": {"name": category.name},
            "res_model_name": category.res_model.model,
            "version": {"name": "v1", "title": "Imported"},
        }

    def _create_wizard(self, category, **extra):
        vals = {
            "bundle_file": base64.b64encode(b"dummy-bundle"),
            "bundle_filename": "workflow.zip",
            "target_category_id": category.id,
            "create_category_if_missing": False,
            "deploy_after_import": False,
        }
        vals.update(extra)
        return self.env["workflow.studio.import.zip.wizard"].create(vals)

    def test_action_import_bundle_runs_dry_run_when_enabled(self):
        category = self._create_target_category("Import Dry Run Enabled")
        wizard = self._create_wizard(category, run_dry_run_before_import=True)
        manifest = self._make_manifest(category)

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=False),
            patch.object(type(wizard), "_dry_run_manifest_import") as dry_run_mock,
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            wizard.action_import_bundle()

        dry_run_mock.assert_called_once()

    def test_action_import_bundle_skips_dry_run_when_disabled(self):
        category = self._create_target_category("Import Dry Run Disabled")
        wizard = self._create_wizard(category, run_dry_run_before_import=False)
        manifest = self._make_manifest(category)

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=False),
            patch.object(type(wizard), "_dry_run_manifest_import") as dry_run_mock,
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            wizard.action_import_bundle()

        dry_run_mock.assert_not_called()

    def test_action_import_bundle_passes_force_flag_to_customization_install(self):
        category = self._create_target_category("Import Force Init")
        wizard = self._create_wizard(
            category,
            run_dry_run_before_import=False,
            force_init_customizations=False,
        )
        manifest = self._make_manifest(category)
        sanitize_result = (
            b"sanitized",
            {
                "module_root": "workflow_studio_customization",
                "stripped_models": 0,
                "stripped_fields": 0,
                "removed_params": 0,
                "remapped_model_refs": 0,
            },
        )

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=b"zip-bytes"),
            patch.object(type(wizard), "_sanitize_customization_zip", return_value=sanitize_result),
            patch.object(type(wizard), "_install_customizations_in_new_cursor") as install_mock,
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            wizard.action_import_bundle()

        install_mock.assert_called_once()
        _args, kwargs = install_mock.call_args
        self.assertFalse(kwargs.get("force_init"))

    def test_action_import_bundle_aborts_when_customization_install_locked(self):
        category = self._create_target_category("Import Lock Timeout Abort")
        wizard = self._create_wizard(
            category,
            run_dry_run_before_import=False,
            deploy_after_import=False,
        )
        manifest = self._make_manifest(category)

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=b"zip-bytes"),
            patch.object(
                type(wizard),
                "_install_customizations_in_new_cursor",
                side_effect=UserError("lock timeout while inserting index"),
            ),
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            with self.assertRaises(UserError) as error:
                wizard.action_import_bundle()

        self.assertIn("Import aborted to avoid configuration loss", str(error.exception))

    def test_action_import_bundle_returns_next_action_with_views(self):
        category = self._create_target_category("Import Next Action Views")
        wizard = self._create_wizard(
            category,
            run_dry_run_before_import=False,
            deploy_after_import=False,
        )
        manifest = self._make_manifest(category)

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=False),
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            action = wizard.action_import_bundle()

        next_action = action.get("params", {}).get("next", {})
        self.assertEqual(next_action.get("type"), "ir.actions.act_window")
        self.assertEqual(next_action.get("views"), [[False, "form"]])

    def test_prepare_target_category_existing_model_mode_error_raises(self):
        category = self._create_target_category("Import Existing Model Conflict")
        wizard = self._create_wizard(
            category,
            target_category_id=False,
            create_category_if_missing=True,
            existing_model_mode="error",
        )
        manifest = self._make_manifest(category)
        manifest["category"] = {"name": "Another Category"}
        with self.assertRaises(UserError):
            wizard._prepare_target_category(manifest)

    def test_prepare_target_category_sync_mode_allows_existing_model(self):
        category = self._create_target_category("Import Existing Model Sync")
        wizard = self._create_wizard(
            category,
            target_category_id=False,
            create_category_if_missing=True,
            existing_model_mode="sync",
        )
        manifest = self._make_manifest(category)
        manifest["category"] = {"name": "Sync Category"}
        prepared = wizard._prepare_target_category(manifest)
        self.assertEqual(prepared.res_model.id, category.res_model.id)

    def test_prepare_target_category_duplicate_mode_creates_new_category(self):
        category = self._create_target_category("Import Duplicate Category")
        wizard = self._create_wizard(
            category,
            target_category_id=False,
            create_category_if_missing=True,
            existing_model_mode="duplicate",
        )
        manifest = self._make_manifest(category)
        manifest["category"] = {"name": category.name}

        prepared = wizard._prepare_target_category(manifest)
        self.assertNotEqual(prepared.id, category.id)
        self.assertEqual(prepared.res_model.id, category.res_model.id)
        self.assertTrue(
            prepared.name.startswith(category.name),
            "Duplicate mode should preserve base category name with a unique suffix",
        )

    def test_prepare_target_category_existing_model_mode_error_allows_same_target_category(self):
        category = self._create_target_category("Import Existing Model Same Category")
        wizard = self._create_wizard(
            category,
            existing_model_mode="error",
        )
        manifest = self._make_manifest(category)
        prepared = wizard._prepare_target_category(manifest)
        self.assertEqual(
            prepared.id,
            category.id,
            "Error mode should allow importing when the explicit target category already matches the manifest model",
        )

    def test_prepare_target_category_model_mismatch_raises(self):
        category = self._create_target_category("Import Model Mismatch")
        wizard = self._create_wizard(
            category,
            existing_model_mode="sync",
        )
        manifest = {
            "category": {"name": category.name},
            "res_model_name": "res.users",
            "version": {"name": "v1", "title": "Imported"},
        }
        with self.assertRaises(UserError):
            wizard._prepare_target_category(manifest)

    def test_action_validate_bundle_runs_dry_run(self):
        category = self._create_target_category("Validate Bundle")
        wizard = self._create_wizard(category)
        manifest = self._make_manifest(category)
        sanitize_result = (
            b"sanitized",
            {
                "module_root": "workflow_studio_customization",
                "stripped_models": 0,
                "stripped_fields": 0,
                "removed_params": 0,
                "remapped_model_refs": 0,
            },
        )
        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=b"zip-bytes"),
            patch.object(type(wizard), "_sanitize_customization_zip", return_value=sanitize_result) as sanitize_mock,
            patch.object(type(wizard), "_dry_run_manifest_import") as dry_run_mock,
        ):
            action = wizard.action_validate_bundle()
        dry_run_mock.assert_called_once()
        sanitize_mock.assert_called_once()
        _sanitize_args, sanitize_kwargs = sanitize_mock.call_args
        self.assertFalse(sanitize_kwargs.get("persist_xmlids"))
        _args, kwargs = dry_run_mock.call_args
        self.assertEqual(kwargs.get("customizations_zip"), b"zip-bytes")
        self.assertEqual(kwargs.get("force_init_customizations"), wizard.force_init_customizations)
        self.assertEqual(action.get("tag"), "display_notification")
        self.assertEqual(action.get("params", {}).get("type"), "success")

    def test_read_bundle_manifest_invalid_zip_raises(self):
        category = self._create_target_category("Validate Invalid ZIP")
        wizard = self._create_wizard(category)
        with self.assertRaises(UserError):
            wizard._read_bundle_manifest(b"not-a-zip")

    def test_isolated_env_rolls_back_created_records(self):
        category = self._create_target_category("Dry Run Rollback")
        wizard = self._create_wizard(category)
        before_category_count = self.env["workflow.approval.category"].search_count([])
        before_version_count = self.env["workflow.approval.category.version"].search_count([])

        with wizard._isolated_env() as wiz:
            isolated_model = wiz.env["ir.model"].sudo()._get("res.partner")
            isolated_category = wiz.env["workflow.approval.category"].sudo().create(
                {
                    "name": "Isolated Category",
                    "res_model": isolated_model.id,
                }
            )
            wiz.env["workflow.approval.category.version"].sudo().create(
                {
                    "category_id": isolated_category.id,
                    "name": "v_isolated",
                    "title": "Transient",
                    "is_active": False,
                }
            )

        self.assertEqual(
            self.env["workflow.approval.category"].search_count([]),
            before_category_count,
            "Isolated dry-run cursor must rollback created categories",
        )
        self.assertEqual(
            self.env["workflow.approval.category.version"].search_count([]),
            before_version_count,
            "Isolated dry-run cursor must rollback created versions",
        )

    def test_action_import_bundle_uses_next_version_name_for_duplicates(self):
        category = self._create_target_category("Duplicate Version Name")
        self.env["workflow.approval.category.version"].create(
            {
                "category_id": category.id,
                "name": "v1",
                "title": "Existing",
                "is_active": False,
            }
        )
        wizard = self._create_wizard(
            category,
            run_dry_run_before_import=False,
            deploy_after_import=False,
        )
        manifest = self._make_manifest(category)

        with (
            patch.object(type(wizard), "_decode_bundle_content", return_value=b"raw"),
            patch.object(type(wizard), "_read_bundle_manifest", return_value=manifest),
            patch.object(type(wizard), "_extract_customizations_zip", return_value=False),
            patch(
                "odoo.addons.workflow_studio.models.workflow_approval_category_version."
                "WorkflowApprovalCategoryVersion.workflow_studio_import_bundle",
                return_value={"warnings": []},
            ),
        ):
            wizard.action_import_bundle()

        latest = self.env["workflow.approval.category.version"].search(
            [("category_id", "=", category.id)],
            order="id desc",
            limit=1,
        )
        self.assertEqual(
            latest.name,
            "v1_2",
            "Import should avoid duplicate version names inside the same category",
        )

    def test_extract_customizations_zip_supports_flat_single_module_layout(self):
        category = self._create_target_category("Extract Flat Customizations")
        wizard = self._create_wizard(category)

        bundle_bytes = io.BytesIO()
        with zipfile.ZipFile(bundle_bytes, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("workflow_bundle/manifest.json", "{}")
            zf.writestr("workflow_bundle/customizations/.module_root", "workflow_studio_customization")
            zf.writestr(
                "workflow_bundle/customizations/__manifest__.py",
                "{'name': 'Workflow Studio customizations'}",
            )
            zf.writestr(
                "workflow_bundle/customizations/data/studio_customizations.xml",
                "<odoo/>",
            )

        custom_zip = wizard._extract_customizations_zip(bundle_bytes.getvalue())
        self.assertTrue(custom_zip)
        with zipfile.ZipFile(io.BytesIO(custom_zip), "r") as extracted:
            extracted_names = set(extracted.namelist())
            self.assertIn(
                "workflow_studio_customization/__manifest__.py",
                extracted_names,
            )
            self.assertIn(
                "workflow_studio_customization/data/studio_customizations.xml",
                extracted_names,
            )

    def test_extract_customizations_zip_supports_merged_payload_manifest(self):
        category = self._create_target_category("Extract Merged Payload")
        wizard = self._create_wizard(category)

        bundle_bytes = io.BytesIO()
        with zipfile.ZipFile(bundle_bytes, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("workflow_bundle/manifest.json", "{}")
            zf.writestr(
                "workflow_bundle/studio_customizations_manifest.json",
                (
                    '{"module_root":"workflow_studio_customization",'
                    '"files":["data/studio_customizations.xml","security/ir.model.access.csv"]}'
                ),
            )
            zf.writestr("workflow_bundle/data/studio_customizations.xml", "<odoo/>")
            zf.writestr(
                "workflow_bundle/security/ir.model.access.csv",
                "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n",
            )

        custom_zip = wizard._extract_customizations_zip(bundle_bytes.getvalue())
        self.assertTrue(custom_zip)
        with zipfile.ZipFile(io.BytesIO(custom_zip), "r") as extracted:
            extracted_names = set(extracted.namelist())
            self.assertIn(
                "workflow_studio_customization/data/studio_customizations.xml",
                extracted_names,
            )
            self.assertIn(
                "workflow_studio_customization/security/ir.model.access.csv",
                extracted_names,
            )
            self.assertIn(
                "workflow_studio_customization/__manifest__.py",
                extracted_names,
            )

    def test_extract_customizations_zip_supports_legacy_flattened_path(self):
        category = self._create_target_category("Extract Legacy Customizations")
        wizard = self._create_wizard(category)

        bundle_bytes = io.BytesIO()
        with zipfile.ZipFile(bundle_bytes, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("workflow_bundle/manifest.json", "{}")
            zf.writestr(
                "workflow_bundle/workflow_studio/customizations/workflow_studio_customization/__manifest__.py",
                "{'name': 'Workflow Studio customizations'}",
            )

        custom_zip = wizard._extract_customizations_zip(bundle_bytes.getvalue())
        self.assertTrue(custom_zip)
        with zipfile.ZipFile(io.BytesIO(custom_zip), "r") as extracted:
            self.assertIn(
                "workflow_studio_customization/__manifest__.py",
                set(extracted.namelist()),
            )
