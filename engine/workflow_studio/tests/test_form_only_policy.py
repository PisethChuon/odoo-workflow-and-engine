import odoo

from odoo import Command, api
from odoo.addons.workflow_studio.controllers.main import WebStudioController
from odoo.exceptions import UserError, ValidationError
from odoo.http import _request_stack
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import DotDict
from lxml import etree

ROUTING_ALWAYS_TRUE = "[(1, '=', 1)]"
ROUTING_ALWAYS_FALSE = "[(0, '=', 1)]"


@tagged("ws_patch")
class TestWorkflowStudioFormOnlyPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env = api.Environment(self.cr, odoo.SUPERUSER_ID, {"load_all_views": True})
        _request_stack.push(self)
        self.session = DotDict({"debug": ""})
        self.controller = WebStudioController()

        self.form_view = self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.form_only.partner.form",
                "type": "form",
                "model": "res.partner",
                "arch": "<form><field name='name'/></form>",
            }
        )
        self.list_view = self.env["ir.ui.view"].create(
            {
                "name": "workflow_studio.form_only.partner.list",
                "type": "list",
                "model": "res.partner",
                "arch": "<list><field name='name'/></list>",
            }
        )
        self.action = self.env["ir.actions.act_window"].create(
            {
                "name": "workflow_studio.form_only.action",
                "res_model": "res.partner",
                "view_mode": "list,form",
                "view_ids": [Command.create({"view_id": self.form_view.id, "view_mode": "form"})],
            }
        )
        self.approval_base_form_view = self.env.ref("workflow_engine.approval_base_request_view_form")
        self.approval_model = self.approval_base_form_view.model
        self.approval_primary_view = self.env["ir.ui.view"].create(
            {
                "name": "x_test.workflow.approval.form.primary",
                "type": "form",
                "model": self.approval_model,
                "inherit_id": self.approval_base_form_view.id,
                "mode": "primary",
                "priority": 99,
                "arch_db": """
                    <data>
                        <group name="request_main" position="inside"/>
                    </data>
                """,
            }
        )
        self.approval_category = self.env["workflow.approval.category"].create(
            {
                "name": "Workflow Studio Test Category",
                "res_model": self.env["ir.model"]._get(self.approval_model).id,
            }
        )
        self.approval_version = self.env["workflow.approval.category.version"].create(
            {
                "name": "Workflow Studio Test Version",
                "category_id": self.approval_category.id,
            }
        )

    def tearDown(self):
        _request_stack.pop()
        super().tearDown()

    def update_context(self, **overrides):
        self.env = self.env(context=dict(self.env.context, **overrides))

    def assertNoLegacyWorkflowPolicyAttrs(self, arch):
        for token in (
            "wf_policy_id",
            "wf_group_policy_id",
            "wf_policy_domains",
            "wf_visible_domain",
            "wf_readonly_domain",
            "wf_required_domain",
            "wf_has_visible",
            "wf_has_readonly",
            "wf_has_required",
            'widget="wf_field"',
            'widget="wf_group"',
        ):
            self.assertNotIn(token, arch)

    def test_create_new_app_is_blocked(self):
        with self.assertRaises(UserError):
            self.controller.create_new_app()

    def test_create_top_level_menu_is_blocked(self):
        with self.assertRaises(UserError):
            self.controller.create_new_menu(
                menu_name="Blocked App",
                model_choice="new",
                model_options=[],
                parent_menu_id=False,
            )

    def test_edit_action_keeps_only_form_view_mode(self):
        self.controller.edit_action(
            "ir.actions.act_window",
            self.action.id,
            {"view_mode": "kanban,list,form"},
        )
        self.action.invalidate_recordset()
        self.assertEqual(self.action.view_mode, "form")

    def test_add_view_type_rejects_non_form(self):
        result = self.controller.add_view_type(
            "ir.actions.act_window",
            self.action.id,
            "res.partner",
            "list",
            {"view_mode": "list,form"},
        )
        self.assertFalse(result)

    def test_get_studio_view_arch_rejects_non_form(self):
        with self.assertRaises(UserError):
            self.controller.get_studio_view_arch("res.partner", "list")

    def test_edit_view_rejects_non_form_view(self):
        with self.assertRaises(UserError):
            self.controller.edit_view(self.list_view.id, "<data/>", operations=[])

    def test_edit_view_arch_rejects_non_form_view(self):
        with self.assertRaises(UserError):
            self.controller.edit_view_arch(self.list_view.id, "<list><field name='name'/></list>")

    def test_get_studio_view_arch_uses_extension_view_for_approval_form(self):
        payload = self.controller.get_studio_view_arch(
            self.approval_model,
            "form",
            view_id=self.approval_primary_view.id,
        )
        self.assertFalse(payload["studio_view_id"])
        self.assertEqual(payload["main_view_id"], self.approval_primary_view.id)
        self.assertIn("<data", payload["studio_view_arch"])

    def test_set_studio_view_creates_approval_extension_without_touching_primary(self):
        new_arch = """
            <data>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Injected by Workflow Studio"/>
                </xpath>
            </data>
        """
        studio_view = self.controller._set_studio_view(self.approval_primary_view, new_arch)
        self.approval_primary_view.flush_recordset()
        self.approval_primary_view.invalidate_recordset(["arch_db"])

        self.assertNotEqual(studio_view.id, self.approval_primary_view.id)
        self.assertEqual(studio_view.inherit_id, self.approval_primary_view)
        self.assertEqual(studio_view.mode, "extension")
        self.assertIn("Injected by Workflow Studio", studio_view.arch_db)
        self.assertNotIn("Injected by Workflow Studio", self.approval_primary_view.arch_db)

        ext_views = self.env["ir.ui.view"].search(
            [
                ("inherit_id", "=", self.approval_primary_view.id),
                ("name", "=", self.controller._generate_studio_view_name(self.approval_primary_view)),
            ]
        )
        self.assertEqual(ext_views, studio_view)

    def test_get_studio_view_keeps_legacy_extension_as_studio_view(self):
        legacy_arch = """
            <data>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Legacy Studio Customization"/>
                </xpath>
            </data>
        """
        legacy_view = self.env["ir.ui.view"].create(
            {
                "name": self.controller._generate_studio_view_name(self.approval_primary_view),
                "type": "form",
                "model": self.approval_model,
                "inherit_id": self.approval_primary_view.id,
                "mode": "extension",
                "priority": 999,
                "arch_db": legacy_arch,
            }
        )

        studio_view = self.controller._get_studio_view(self.approval_primary_view)
        self.assertEqual(studio_view, legacy_view)

        legacy_view.invalidate_recordset(["active", "arch_db"])
        self.assertTrue(legacy_view.exists())
        self.assertIn("Legacy Studio Customization", legacy_view.arch_db)
        self.approval_primary_view.invalidate_recordset(["arch_db"])
        self.assertNotIn("Legacy Studio Customization", self.approval_primary_view.arch_db)

    def test_get_studio_view_demotes_primary_customization_into_extension(self):
        primary_arch = """
            <data>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Primary Studio Customization"/>
                </xpath>
            </data>
        """
        self.approval_primary_view.with_context(workflow_studio=True).write({"arch_db": primary_arch})

        studio_view = self.controller._get_studio_view(self.approval_primary_view)
        self.assertTrue(studio_view)
        self.assertEqual(studio_view.inherit_id, self.approval_primary_view)
        self.assertIn("Primary Studio Customization", studio_view.arch_db)

        self.approval_primary_view.invalidate_recordset(["arch_db"])
        self.assertTrue(self.controller._is_default_approval_primary_arch(self.approval_primary_view.arch_db))

    def test_get_studio_view_merges_primary_and_extension_without_duplicates(self):
        primary_arch = """
            <data>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Primary Studio Customization"/>
                </xpath>
            </data>
        """
        extension_arch = """
            <data>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Primary Studio Customization"/>
                </xpath>
                <xpath expr="//group[@name='request_main']" position="inside">
                    <separator string="Extension Studio Customization"/>
                </xpath>
            </data>
        """
        self.approval_primary_view.with_context(workflow_studio=True).write({"arch_db": primary_arch})
        self.env["ir.ui.view"].create(
            {
                "name": self.controller._generate_studio_view_name(self.approval_primary_view),
                "type": "form",
                "model": self.approval_model,
                "inherit_id": self.approval_primary_view.id,
                "mode": "extension",
                "priority": 999,
                "arch_db": extension_arch,
            }
        )

        studio_view = self.controller._get_studio_view(self.approval_primary_view)
        self.controller._get_studio_view(self.approval_primary_view)
        studio_view.invalidate_recordset(["arch_db"])

        self.assertEqual(studio_view.arch_db.count("Primary Studio Customization"), 1)
        self.assertEqual(studio_view.arch_db.count("Extension Studio Customization"), 1)
        ext_views = self.env["ir.ui.view"].search([
            ("inherit_id", "=", self.approval_primary_view.id),
            ("name", "=", self.controller._generate_studio_view_name(self.approval_primary_view)),
        ])
        self.assertEqual(len(ext_views), 1)

    def test_edit_view_new_field_on_approval_form_renders_in_returned_arch(self):
        self.addCleanup(self.registry.reset_changes)
        field_name = "x_workflow_studio_char_field_drag_render"
        result = self.controller.edit_view(
            self.approval_primary_view.id,
            "<data/>",
            operations=[
                {
                    "type": "add",
                    "target": {
                        "tag": "field",
                        "attrs": {"name": "request_owner_ext_phone"},
                    },
                    "position": "after",
                    "node": {
                        "tag": "field",
                        "attrs": {"string": "Dragged Text"},
                        "field_description": {
                            "type": "char",
                            "field_description": "Dragged Text",
                            "name": field_name,
                            "model_name": self.approval_model,
                        },
                    },
                }
            ],
            model=self.approval_model,
        )

        self.assertIn(field_name, result["views"]["form"]["arch"])
        studio_view = self.controller._get_studio_view(self.approval_primary_view)
        self.assertIn(field_name, studio_view.arch_db)
        self.assertNotEqual(studio_view.id, self.approval_primary_view.id)

    def test_edit_view_existing_field_inside_workflow_config_group_renders_in_returned_arch(self):
        result = self.controller.edit_view(
            self.approval_primary_view.id,
            "<data/>",
            operations=[
                {
                    "type": "add",
                    "target": {
                        "tag": "group",
                        "attrs": {"name": "wf_runtime_configurable_fields"},
                    },
                    "position": "inside",
                    "node": {
                        "tag": "field",
                        "attrs": {"name": "display_name"},
                    },
                }
            ],
            model=self.approval_model,
        )

        returned_arch = result["views"]["form"]["arch"]
        self.assertIn("wf_runtime_configurable_fields", returned_arch)
        self.assertIn('name="display_name"', returned_arch)
        studio_view = self.controller._get_studio_view(self.approval_primary_view)
        self.assertIn("display_name", studio_view.arch_db)

    def test_edit_view_accepts_existing_workflow_studio_context_key(self):
        result = self.controller.edit_view(
            self.approval_primary_view.id,
            "<data/>",
            operations=[
                {
                    "type": "add",
                    "target": {
                        "tag": "group",
                        "attrs": {"name": "wf_runtime_configurable_fields"},
                    },
                    "position": "inside",
                    "node": {
                        "tag": "field",
                        "attrs": {"name": "display_name"},
                    },
                }
            ],
            model=self.approval_model,
            context={"workflow_studio": True, "no_address_format": True},
        )

        self.assertIn('name="display_name"', result["views"]["form"]["arch"])

    def test_workflow_studio_create_and_update_approval_group_on_the_fly(self):
        result = self.approval_version.workflow_studio_create_approval_group(
            {
                "name": "QA Approval Group",
                "user_ids": [self.env.user.id],
            }
        )
        created_group = result["approval_group"]
        self.assertTrue(created_group.get("id"))
        self.assertEqual(created_group.get("name"), "QA Approval Group")
        self.assertIsInstance(created_group.get("user_ids", []), list)

        updated = self.approval_version.workflow_studio_update_approval_group(
            created_group["id"],
            {"name": "QA Approval Group Updated"},
        )
        updated_group = updated["approval_group"]
        self.assertEqual(updated_group.get("id"), created_group["id"])
        self.assertEqual(updated_group.get("name"), "QA Approval Group Updated")

    def test_workflow_studio_search_approval_groups_matches_hierarchy_department_and_members(self):
        department = self.env["hr.department"].create({"name": "Workflow Search Department"})
        search_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Workflow Search Member",
            "login": "workflow.search.member@example.com",
            "email": "workflow.search.member@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        parent_group = self.env["workflow.approval.group"].create({
            "name": "Workflow Search Parent",
        })
        child_group = self.env["workflow.approval.group"].create({
            "name": "Workflow Search Child",
            "parent_id": parent_group.id,
            "department_id": department.id,
            "user_ids": [(6, 0, [search_user.id])],
        })

        parent_result = self.approval_version.workflow_studio_search_approval_groups("Workflow Search Parent")
        parent_ids = [row["id"] for row in parent_result.get("rows") or []]
        self.assertIn(parent_group.id, parent_ids)
        self.assertIn(
            child_group.id,
            parent_ids,
            "Searching by an ancestor name should still find descendant groups through the display path.",
        )

        department_result = self.approval_version.workflow_studio_search_approval_groups("Workflow Search Department")
        self.assertIn(child_group.id, [row["id"] for row in department_result.get("rows") or []])

        member_token = "Workflow Search Member"
        member_result = self.approval_version.workflow_studio_search_approval_groups(member_token)
        self.assertIn(child_group.id, [row["id"] for row in member_result.get("rows") or []])

    def test_workflow_studio_browse_approval_groups_filters_and_paginates_server_side(self):
        alpha_group = self.env["workflow.approval.group"].create({
            "name": "Workflow Browser Alpha",
        })
        beta_group = self.env["workflow.approval.group"].create({
            "name": "Workflow Browser Beta",
        })
        gamma_group = self.env["workflow.approval.group"].create({
            "name": "Workflow Browser Gamma",
        })
        approval_link_rows = [
            {
                "approval_group_id": alpha_group.id,
                "user_domain": ROUTING_ALWAYS_TRUE,
                "domain": ROUTING_ALWAYS_TRUE,
            },
            {
                "approval_group_id": beta_group.id,
                "user_domain": "",
                "domain": "[]",
            },
        ]

        all_result = self.approval_version.workflow_studio_browse_approval_groups({
            "query": "Workflow Browser",
            "mode": "all",
            "routing_filter": "all",
            "offset": 1,
            "limit": 1,
            "approval_link_rows": approval_link_rows,
        })
        self.assertEqual(all_result.get("total"), 3)
        self.assertTrue(all_result.get("has_more"))
        self.assertEqual([row["id"] for row in all_result.get("rows") or []], [beta_group.id])
        self.assertEqual(
            [warning["label"] for warning in all_result["rows"][0].get("routing_warnings") or []],
            ["User Filter Blank", "Record Domain []"],
        )

        needs_config_result = self.approval_version.workflow_studio_browse_approval_groups({
            "query": "Workflow Browser",
            "mode": "linked",
            "routing_filter": "needs_config",
            "offset": 0,
            "limit": 10,
            "approval_link_rows": approval_link_rows,
        })
        self.assertEqual(
            [row["id"] for row in needs_config_result.get("rows") or []],
            [beta_group.id],
        )

        available_result = self.approval_version.workflow_studio_browse_approval_groups({
            "query": "Workflow Browser",
            "mode": "available",
            "routing_filter": "all",
            "offset": 0,
            "limit": 10,
            "approval_link_rows": approval_link_rows,
        })
        self.assertEqual(
            [row["id"] for row in available_result.get("rows") or []],
            [gamma_group.id],
        )

    def test_workflow_studio_set_task_approval_links_accepts_string_group_id(self):
        meta_task = self.env["workflow.category.version.meta.task"].create(
            {
                "version_id": self.approval_version.id,
                "name": "Approval Node",
                "node_id": "Task_Approval_Node",
                "node_type": "userTask",
            }
        )
        group_payload = self.approval_version.workflow_studio_create_approval_group(
            {"name": "String ID Group"}
        )["approval_group"]

        result = self.approval_version.workflow_studio_set_task_approval_links(
            meta_task.node_id,
            [
                {
                    "approval_group_ref": {
                        "id": str(group_payload["id"]),
                        "name": group_payload["name"],
                    },
                    "sequence": 15,
                    "user_domain": ROUTING_ALWAYS_TRUE,
                    "domain": ROUTING_ALWAYS_TRUE,
                    "note": "from test",
                }
            ],
        )

        self.assertFalse(result.get("warnings"), "String approval_group_ref.id should resolve.")
        self.assertEqual(len(result.get("rows") or []), 1)
        saved_row = result["rows"][0]
        self.assertEqual(saved_row.get("sequence"), 15)
        self.assertEqual(saved_row.get("approval_group_ref", {}).get("id"), group_payload["id"])

    def test_workflow_studio_set_task_approval_links_warns_but_saves_ignored_routing_domains(self):
        meta_task = self.env["workflow.category.version.meta.task"].create(
            {
                "version_id": self.approval_version.id,
                "name": "Approval Node With Ignored Domains",
                "node_id": "Task_Approval_Node_Ignored",
                "node_type": "userTask",
            }
        )
        group_payload = self.approval_version.workflow_studio_create_approval_group(
            {"name": "Ignored Routing Group"}
        )["approval_group"]

        result = self.approval_version.workflow_studio_set_task_approval_links(
            meta_task.node_id,
            [
                {
                    "approval_group_ref": {
                        "id": str(group_payload["id"]),
                        "name": group_payload["name"],
                    },
                    "sequence": 20,
                    "user_domain": "[]",
                    "domain": "",
                }
            ],
        )

        warnings = result.get("warnings") or []
        self.assertTrue(warnings)
        self.assertTrue(any("Approval link user filter domain" in warning for warning in warnings))
        self.assertTrue(any("Approval link record domain" in warning for warning in warnings))
        self.assertTrue(all("Ignored Routing Group" in warning for warning in warnings))
        saved_row = (result.get("rows") or [])[0]
        self.assertEqual(saved_row.get("user_domain"), "[]")
        self.assertEqual(saved_row.get("domain"), "")

    def test_workflow_studio_set_task_approval_links_accepts_field_routing_record_domain(self):
        meta_task = self.env["workflow.category.version.meta.task"].create(
            {
                "version_id": self.approval_version.id,
                "name": "Routing Approval Node",
                "node_id": "Task_Routing_Approval_Node",
                "node_type": "userTask",
            }
        )
        group_payload = self.approval_version.workflow_studio_create_approval_group(
            {"name": "Routing Group"}
        )["approval_group"]

        result = self.approval_version.workflow_studio_set_task_approval_links(
            meta_task.node_id,
            [
                {
                    "approval_group_ref": {
                        "id": group_payload["id"],
                        "name": group_payload["name"],
                    },
                    "sequence": 10,
                    "user_domain": "[('active', '=', True)]",
                    "domain": "[('request_owner_id', '=', uid)]",
                    "note": "Route this group when the current actor is the request owner.",
                }
            ],
        )

        self.assertFalse(result.get("warnings"), "Field-based record routing domains should save cleanly.")
        self.assertEqual(len(result.get("rows") or []), 1)
        saved_row = result["rows"][0]
        self.assertEqual(saved_row.get("domain"), "[('request_owner_id', '=', uid)]")
        self.assertEqual(saved_row.get("user_domain"), "[('active', '=', True)]")
        self.assertEqual(saved_row.get("approval_group_ref", {}).get("id"), group_payload["id"])

    def test_sanitize_workflow_modifier_arch_strips_legacy_policy_attrs(self):
        root = etree.fromstring(
            b"""
            <data>
                <field name="x_test_field" options="{&quot;wf_required_domain&quot;:&quot;[('wf_actor_login','=','hod')]&quot;,&quot;wf_readonly_domain&quot;:&quot;[('wf_actor_uid','!=',0)]&quot;}"/>
            </data>
            """
        )

        self.controller._sanitize_workflow_modifier_arch(
            root,
            model_name="res.partner",
            view_id=self.form_view.id,
        )

        field_node = root.xpath("//field[@name='x_test_field']")[0]
        # widget is no longer overwritten — wf_policy_id is the policy marker
        self.assertIsNone(field_node.get("widget"))
        self.assertIsNone(field_node.get("wf_policy_id"))
        self.assertIsNone(field_node.get("invisible"))
        self.assertIsNone(field_node.get("readonly"))
        self.assertIsNone(field_node.get("required"))
        self.assertNotIn("wf_required_domain", field_node.get("options", ""))
        self.assertNotIn("wf_readonly_domain", field_node.get("options", ""))

    def test_workflow_domain_validator_accepts_runtime_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.partner",
            "[('id', '=', wf_actor_uid)]",
            "field_modifiers",
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_routing_scopes_accept_explicit_true_false_sentinels(self):
        validator = self.env["workflow.approval.category.version"]
        for expression, expected_state in (
            (ROUTING_ALWAYS_TRUE, "always_true"),
            (ROUTING_ALWAYS_FALSE, "always_false"),
        ):
            result = validator.workflow_studio_validate_domain_expression(
                "res.users",
                expression,
                "assignment_users_routing",
                self.approval_model,
            )
            self.assertTrue(result.get("valid"), result.get("error"))
            self.assertEqual(result.get("domain_state"), expected_state)
            self.assertFalse(result.get("warning"))

    def test_workflow_domain_validator_routing_scopes_warn_for_ignored_values(self):
        validator = self.env["workflow.approval.category.version"]
        cases = (
            ("", "ignored_blank"),
            ("[]", "ignored_empty"),
            ("[1, '=', 1]", "ignored_invalid"),
            ("[('id', '=', unknown_symbol)]", "ignored_invalid"),
        )
        for expression, expected_state in cases:
            result = validator.workflow_studio_validate_domain_expression(
                "res.users",
                expression,
                "assignment_users_routing",
                self.approval_model,
            )
            self.assertTrue(result.get("valid"), result.get("error"))
            self.assertEqual(result.get("domain_state"), expected_state)
            self.assertTrue(result.get("warning"))

    def test_workflow_domain_validator_accepts_stage_age_symbols(self):
        validator = self.env["workflow.approval.category.version"]
        simple_result = validator.workflow_studio_validate_domain_expression(
            "res.partner",
            "[('wf_current_stage_age_minutes', '>=', 1440)]",
            "field_modifiers",
        )
        self.assertTrue(simple_result.get("valid"), simple_result.get("error"))

        advanced_result = validator.workflow_studio_validate_domain_expression(
            "res.partner",
            "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 1440",
            "request_scope",
        )
        self.assertTrue(advanced_result.get("valid"), advanced_result.get("error"))

    def test_workflow_domain_validator_accepts_one2many_any_all_helpers(self):
        validator = self.env["workflow.approval.category.version"]
        for expression in (
            "wf_any('child_ids', [('name', 'ilike', 'ADMIN')])",
            "wf_all('child_ids', [('name', 'ilike', 'ADMIN')])",
            "wf_any('child_ids', True)",
            "not wf_any('child_ids', True)",
            "wf_any('child_ids', [('comment', '!=', False)])",
            "wf_all('child_ids', [('comment', '=', False)])",
            "wf_any('child_ids', [('parent_id', '=', False)])",
            "wf_any('child_ids', [('parent_id.name', 'ilike', 'ADMIN')])",
            "[('child_ids.name', 'ilike', 'ADMIN')]",
        ):
            result = validator.workflow_studio_validate_domain_expression(
                "workflow.base.approval.request",
                expression,
                "request_scope",
                "workflow.base.approval.request",
            )
            self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_rejects_invalid_one2many_helper_path(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "workflow.base.approval.request",
            "wf_any('missing_line_ids', [('name', 'ilike', 'ADMIN')])",
            "request_scope",
            "workflow.base.approval.request",
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("missing_line_ids", result.get("error", ""))

    def test_workflow_domain_validator_rejects_invalid_one2many_line_field_path(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "workflow.base.approval.request",
            "wf_any('child_ids', [('missing_line_field', '=', 1)])",
            "request_scope",
            "workflow.base.approval.request",
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("missing_line_field", result.get("error", ""))

    def test_workflow_domain_validator_rejects_unknown_runtime_field(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.partner",
            "[('wf_unknown_field', '=', 1)]",
            "field_modifiers",
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("Unknown runtime/domain field", result.get("error", ""))

    def test_workflow_domain_validator_assignment_users_uses_request_context(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_owner_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_studio_write_meta_task_warns_for_ignored_assignment_routing_domain(self):
        meta_task = self.env["workflow.category.version.meta.task"].create(
            {
                "version_id": self.approval_version.id,
                "name": "Routing Domain Save Warning",
                "node_id": "Task_Routing_Domain_Warning",
                "node_type": "userTask",
            }
        )
        result = self.approval_version.workflow_studio_write_meta_task(
            meta_task.node_id,
            {"assignment_user_domain": "[]"},
        )
        self.assertTrue(result.get("warnings"))
        self.assertEqual(result.get("assignment_user_domain"), "[]")

    def test_workflow_domain_validator_assignment_users_accepts_user_id_alias(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('user_id', '=', request_owner_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_request_owner_manager_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_owner_manager_user_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_request_creator_symbols(self):
        validator = self.env["workflow.approval.category.version"]
        creator_result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_creator_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(creator_result.get("valid"), creator_result.get("error"))

        creator_manager_result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_creator_manager_user_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(creator_manager_result.get("valid"), creator_manager_result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_request_owner_line_manager_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_owner_line_manager_user_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_request_owner_department_manager_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', '=', request_owner_department_manager_user_id)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_request_owner_manager_chain_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', 'in', request_owner_manager_chain_user_ids)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_assignment_users_accepts_decided_approver_symbol(self):
        validator = self.env["workflow.approval.category.version"]
        result = validator.workflow_studio_validate_domain_expression(
            "res.users",
            "[('id', 'in', decided_approver_user_ids)]",
            "assignment_users",
            self.approval_model,
        )
        self.assertTrue(result.get("valid"), result.get("error"))

    def test_workflow_domain_validator_rejects_oversized_expression(self):
        validator = self.env["workflow.approval.category.version"]
        huge_value = "x" * 5000
        result = validator.workflow_studio_validate_domain_expression(
            "res.partner",
            f"[('name', 'ilike', '{huge_value}')]",
            "field_modifiers",
        )
        self.assertFalse(result.get("valid"))
        self.assertIn("too large", (result.get("error") or "").lower())

    def test_edit_view_rejects_invalid_workflow_modifier_options(self):
        with self.assertRaises(ValidationError):
            self.controller.edit_view(
                self.form_view.id,
                "<data/>",
                operations=[
                    {
                        "type": "attributes",
                        "target": {"tag": "field", "attrs": {"name": "name"}},
                        "new_attrs": {
                            "options": {
                                "wf_visible_domain": "[('wf_unknown_field', '=', 1)]",
                            },
                        },
                    }
                ],
                model="res.partner",
            )

    def test_edit_view_replayed_attribute_ops_replace_previous_same_attr_write(self):
        self.controller.edit_view(
            self.form_view.id,
            "<data/>",
            operations=[
                {
                    "type": "attributes",
                    "position": "attributes",
                    "target": {"tag": "field", "attrs": {"name": "name"}},
                    "new_attrs": {"readonly": "True"},
                },
                {
                    "type": "attributes",
                    "position": "attributes",
                    "target": {"tag": "field", "attrs": {"name": "name"}},
                    "new_attrs": {"readonly": "False"},
                },
            ],
            model="res.partner",
        )

        studio_view = self.controller._get_studio_view(self.form_view)
        self.assertTrue(studio_view, "A Studio view should exist after applying attribute operations.")
        root = etree.fromstring((studio_view.arch_db or "<data/>").encode("utf-8"))

        readonly_attribute_nodes = root.xpath(
            "//xpath[@position='attributes']/attribute[@name='readonly']"
        )
        self.assertEqual(
            len(readonly_attribute_nodes),
            1,
            "Replayed writes to the same attribute should keep only the latest entry in Studio arch.",
        )
        self.assertEqual(readonly_attribute_nodes[0].text, "False")
