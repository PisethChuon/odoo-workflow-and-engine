from unittest.mock import patch

from odoo.addons.workflow_studio.models.ir_model import STUDIO_APPROVAL_READER_RULE_DOMAIN
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


@tagged("ws_patch")
class TestWorkflowStudioModelOptions(TransactionCase):
    def _create_studio_approval_model_bundle(self, name):
        model, _extra_models = self.env["ir.model"].studio_model_create(
            name,
            options=["has_approval"],
        )
        category = self.env["workflow.approval.category"].search(
            [("res_model", "=", model.id)],
            limit=1,
        )
        self.assertTrue(category)
        self.assertTrue(category.active_version_id)
        meta_task = self.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": category.active_version_id.id,
                "name": f"{name} Review",
                "node_id": f"Task_{model.id}_Review",
                "node_type": "userTask",
            }
        )
        return model, category, meta_task

    def test_has_approval_option_bootstrap(self):
        model, _extra_models = self.env["ir.model"].studio_model_create(
            "Approval Rockets",
            options=["has_approval"],
        )
        self.assertTrue(model.is_approval)

        category = self.env["workflow.approval.category"].search(
            [("res_model", "=", model.id)],
            limit=1,
        )
        self.assertTrue(category)
        self.assertTrue(category.version_ids)
        self.assertTrue(category.active_version_id)

        base_form = self.env.ref("workflow_engine.approval_base_request_view_form")
        inherited_form = self.env["ir.ui.view"].search(
            [
                ("model", "=", model.model),
                ("inherit_id", "=", base_form.id),
                ("type", "=", "form"),
                ("mode", "=", "primary"),
            ],
            limit=1,
        )
        self.assertTrue(inherited_form)

        action = self.env["ir.actions.act_window"].search(
            [("res_model", "=", model.model)],
            limit=1,
        )
        self.assertTrue(action, "Approval-enabled models should get a default window action")
        self.assertIn("form", (action.view_mode or "").split(","))

    def test_transient_option_creates_wizard_action(self):
        model, _extra_models = self.env["ir.model"].studio_model_create(
            "Rockets Wizard",
            options=["is_transient"],
        )
        self.assertTrue(model.transient)
        action = model._create_default_action("Rockets Wizard")
        self.assertEqual(action.view_mode, "form")
        self.assertEqual(action.target, "new")

    def test_transient_and_approval_is_invalid(self):
        with self.assertRaises(ValidationError):
            self.env["ir.model"].studio_model_create(
                "Invalid Wizard",
                options=["is_transient", "has_approval"],
            )

    def test_has_approval_option_removes_generic_internal_acl(self):
        model, _extra_models = self.env["ir.model"].studio_model_create(
            "Approval ACL Isolation",
            options=["has_approval"],
        )
        internal_acl = self.env["ir.model.access"].search(
            [
                ("model_id", "=", model.id),
                ("group_id", "=", self.env.ref("base.group_user").id),
            ],
            limit=1,
        )
        self.assertFalse(
            internal_acl,
            "Approval-enabled models should not keep the generic base.group_user ACL",
        )

    def test_has_approval_option_creates_workflow_group_acls_and_rules(self):
        model, _extra_models = self.env["ir.model"].studio_model_create(
            "Approval Security Matrix",
            options=["has_approval"],
        )
        access_model = self.env["ir.model.access"]
        rule_model = self.env["ir.rule"]

        expected_acls = {
            "workflow_engine.group_workflow_request_reader": (True, False, False, False),
            "workflow_engine.group_workflow_approval_user": (True, True, True, False),
            "workflow_engine.group_workflow_approval_admin": (True, True, True, True),
        }
        for group_xmlid, expected_perms in expected_acls.items():
            group = self.env.ref(group_xmlid)
            acl = access_model.search(
                [
                    ("model_id", "=", model.id),
                    ("group_id", "=", group.id),
                ],
                limit=1,
            )
            self.assertTrue(acl, f"Missing ACL for {group_xmlid}")
            self.assertEqual(
                (acl.perm_read, acl.perm_write, acl.perm_create, acl.perm_unlink),
                expected_perms,
            )

        expected_rules = [
            {
                "name": f"{model.name}: Request Reader Rule",
                "domain_force": STUDIO_APPROVAL_READER_RULE_DOMAIN,
                "groups": {"workflow_engine.group_workflow_request_reader"},
                "perms": (True, False, False, False),
            },
            {
                "name": f"{model.name}: Request Owner Rule",
                "domain_force": "['|', ('x_approval_base_id.create_uid', '=', user.id), ('x_approval_base_id.request_owner_id', '=', user.id)]",
                "groups": {"workflow_engine.group_workflow_approval_user"},
                "perms": (True, True, True, False),
            },
            {
                "name": f"{model.name}: Approver Rule",
                "domain_force": "[('x_approval_base_id.approver_ids.user_id', 'in', [user.id])]",
                "groups": {"workflow_engine.group_workflow_approval_user"},
                "perms": (True, True, True, False),
            },
            {
                "name": f"{model.name}: Admin Rule",
                "domain_force": "[(1, '=', 1)]",
                "groups": {
                    "workflow_engine.group_workflow_approval_admin",
                    "base.group_system",
                },
                "perms": (True, True, True, True),
            },
        ]
        for expected in expected_rules:
            rule = rule_model.search(
                [
                    ("model_id", "=", model.id),
                    ("name", "=", expected["name"]),
                ],
                limit=1,
            )
            self.assertTrue(rule, f"Missing record rule: {expected['name']}")
            self.assertEqual(rule.domain_force, expected["domain_force"])
            self.assertEqual(
                (rule.perm_read, rule.perm_write, rule.perm_create, rule.perm_unlink),
                expected["perms"],
            )
            actual_groups = {group.get_external_id().get(group.id) for group in rule.groups}
            self.assertTrue(
                expected["groups"].issubset(actual_groups),
                f"Rule {expected['name']} missing expected groups. actual={actual_groups}",
            )

    def test_workflow_tracking_update_bypasses_generated_child_record_rules(self):
        model, category, meta_task = self._create_studio_approval_model_bundle(
            "Approval Tracking Rule Guard"
        )
        base_group = self.env.ref("base.group_user")
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        requester = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Tracking Rule Requester",
                "login": "tracking_rule_requester@example.com",
                "email": "tracking_rule_requester@example.com",
                "group_ids": [(6, 0, [base_group.id, workflow_group.id])],
            }
        )
        owner = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Tracking Rule Owner",
                "login": "tracking_rule_owner@example.com",
                "email": "tracking_rule_owner@example.com",
                "group_ids": [(6, 0, [base_group.id, workflow_group.id])],
            }
        )
        base_request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_STUDIO_TRACKING_RULE",
                "category_id": category.id,
                "version_id": category.active_version_id.id,
                "request_owner_id": owner.id,
                "state": "new",
                "current_iteration_no": 1,
            }
        )
        child_request = self.env[model.model].sudo().with_context(
            workflow_skip_create_autorun=True,
        ).create(
            {
                "x_approval_base_id": base_request.id,
            }
        )

        class FakeNode:
            def __init__(self, node_id, name):
                self.attrib = {"id": node_id, "name": name}

        class FakeEngine:
            def is_end_event(self, node):
                return False

            def is_start_event(self, node):
                return (node.attrib.get("id") or "").startswith("StartEvent")

            def get_next_elements(self, node, form_data=None):
                return []

        child_request.with_user(requester)._update_tracking_fields(
            FakeEngine(),
            form_data={},
            current_node=FakeNode("Task_Previous", "Previous"),
            next_node=FakeNode(meta_task.node_id, meta_task.name),
        )

        child_request.invalidate_recordset(
            ["current_node_id", "current_activity_name", "state", "request_status"]
        )
        child_request = child_request.sudo()
        self.assertEqual(child_request.current_node_id, meta_task.node_id)
        self.assertEqual(child_request.current_activity_name, meta_task.name)
        self.assertEqual(child_request.state, "waiting")
        self.assertEqual(child_request.request_status, "pending")

    def test_edit_scope_share_can_write_generated_child_request(self):
        model, category, meta_task = self._create_studio_approval_model_bundle(
            "Approval Child Share Guard"
        )
        base_group = self.env.ref("base.group_user")
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        shared_user = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Child Shared Editor",
                "login": "child_shared_editor@example.com",
                "email": "child_shared_editor@example.com",
                "group_ids": [(6, 0, [base_group.id, workflow_group.id])],
            }
        )
        owner = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Child Share Owner",
                "login": "child_share_owner@example.com",
                "email": "child_share_owner@example.com",
                "group_ids": [(6, 0, [base_group.id, workflow_group.id])],
            }
        )
        base_request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_STUDIO_CHILD_SHARE",
                "category_id": category.id,
                "version_id": category.active_version_id.id,
                "request_owner_id": owner.id,
                "current_node_id": meta_task.node_id,
                "previous_node_id": meta_task.node_id,
                "current_activity_name": meta_task.name,
                "state": "waiting",
                "current_iteration_no": 1,
            }
        )
        child_request = self.env[model.model].sudo().with_context(
            workflow_skip_create_autorun=True,
        ).create(
            {
                "x_approval_base_id": base_request.id,
            }
        )
        self.env["workflow.request.visibility.scope"].sudo().create(
            {
                "request_id": base_request.id,
                "scope": "edit",
                "allowed_user_id": shared_user.id,
                "granted_by_user_id": self.env.user.id,
            }
        )

        shared_child = child_request.with_user(shared_user)
        shared_child.check_access("write")
        self.assertTrue(shared_child.has_access("write"))

    def test_transition_delegate_skips_child_lookup_for_transient_request(self):
        model, category, _meta_task = self._create_studio_approval_model_bundle(
            "Approval Delegate Guard"
        )
        child_model = self.env[model.model]
        draft_request = self.env["workflow.base.approval.request"].new(
            {
                "name": "Draft Approval",
                "category_id": category.id,
                "version_id": category.active_version_id.id,
                "request_owner_id": self.env.user.id,
            }
        )
        self.assertEqual(draft_request.res_model_name, model.model)

        with patch.object(
            type(child_model),
            "search",
            side_effect=AssertionError("Transient requests must not search child records."),
        ) as search_mock:
            delegate = draft_request._get_transition_delegate_record()

        self.assertEqual(delegate, draft_request)
        search_mock.assert_not_called()

    def test_workflow_activity_type_schedules_on_studio_child_model(self):
        model, category, meta_task = self._create_studio_approval_model_bundle(
            "Approval Activity Target"
        )
        base_request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_STUDIO_ACTIVITY",
                "category_id": category.id,
                "request_owner_id": self.env.user.id,
                "current_node_id": meta_task.node_id,
                "previous_node_id": meta_task.node_id,
                "current_activity_name": meta_task.name,
                "state": "waiting",
                "current_iteration_no": 1,
            }
        )
        child_request = self.env[model.model].sudo().create(
            {
                "x_approval_base_id": base_request.id,
            }
        )
        approver = self.env["workflow.approval.approver"].sudo().create(
            {
                "user_id": self.env.user.id,
                "request_id": base_request.id,
                "current_meta_id": meta_task.id,
                "previous_meta_id": meta_task.id,
                "status": "pending",
                "required": True,
                "iteration_no": 1,
            }
        )

        approver._create_activity()

        activity_type = self.env.ref("workflow_engine.mail_activity_data_workflow_approval")
        activity = self.env["mail.activity"].sudo().search(
            [
                ("activity_type_id", "=", activity_type.id),
                ("res_model", "=", child_request._name),
                ("res_id", "=", child_request.id),
                ("user_id", "=", self.env.user.id),
                ("date_done", "=", False),
            ],
            limit=1,
        )
        self.assertTrue(activity)
        self.assertFalse(activity.activity_type_id.res_model)

    def test_force_transition_wizard_does_not_block_studio_child_delete(self):
        model, category, meta_task = self._create_studio_approval_model_bundle(
            "Force Wizard Child Delete"
        )
        self.env["workflow.category.version.meta.task"].sudo().create(
            {
                "version_id": category.active_version_id.id,
                "name": "Alternate Target",
                "node_id": f"Task_{model.id}_Alternate",
                "node_type": "userTask",
            }
        )
        base_request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "REQ_STUDIO_FORCE_DELETE",
                "category_id": category.id,
                "request_owner_id": self.env.user.id,
                "current_node_id": meta_task.node_id,
                "previous_node_id": meta_task.node_id,
                "current_activity_name": meta_task.name,
                "state": "waiting",
                "current_iteration_no": 1,
            }
        )
        child_request = self.env[model.model].sudo().create(
            {
                "x_approval_base_id": base_request.id,
            }
        )
        wizard_model = self.env["workflow.force.transition.wizard"].with_context(
            default_model=child_request._name,
            default_request_id=child_request.id,
            active_model=child_request._name,
            active_id=child_request.id,
        )
        defaults = wizard_model.default_get(["model", "request_id", "target_node"])
        wizard = wizard_model.create(
            {
                "model": defaults.get("model"),
                "request_id": defaults.get("request_id"),
                "target_node": defaults.get("target_node"),
                "re_assign_approvals": True,
            }
        )
        stale_wizard = self.env["workflow.force.transition.wizard"].sudo().create(
            {
                "model": "workflow.base.approval.request",
                "request_id": child_request.id,
                "target_node": defaults.get("target_node"),
                "re_assign_approvals": True,
            }
        )

        child_request.unlink()

        self.assertFalse(child_request.exists())
        self.assertFalse(base_request.exists())
        self.assertFalse(wizard.exists())
        self.assertFalse(stale_wizard.exists())

    def test_studio_models_keep_workflow_studio_table_and_relation_columns(self):
        rule_model = self.env["workflow.studio.approval.rule"]
        approver_model = self.env["workflow.studio.approval.rule.approver"]
        entry_model = self.env["workflow.studio.approval.entry"]
        request_model = self.env["workflow.studio.approval.request"]
        delegate_model = self.env["workflow.studio.approval.rule.delegate"]
        export_model = self.env["workflow.studio.export.model"]
        export_wizard_model = self.env["workflow.studio.export.wizard"]
        export_wizard_data_model = self.env["workflow.studio.export.wizard.data"]

        self.assertEqual(rule_model._table, "workflow_studio_approval_rule")
        self.assertEqual(approver_model._table, "workflow_studio_approval_rule_approver")
        self.assertEqual(entry_model._table, "workflow_studio_approval_entry")
        self.assertEqual(request_model._table, "workflow_studio_approval_request")
        self.assertEqual(delegate_model._table, "workflow_studio_approval_rule_delegate")
        self.assertEqual(export_model._table, "workflow_studio_export_model")
        self.assertEqual(export_wizard_model._table, "workflow_studio_export_wizard")
        self.assertEqual(export_wizard_data_model._table, "workflow_studio_export_wizard_data")

        rule_notify = rule_model._fields["users_to_notify"]
        self.assertEqual(rule_notify.relation, "approval_rule_users_to_notify_rel")
        self.assertEqual(rule_notify.column1, "workflow_studio_approval_rule_id")
        self.assertEqual(rule_notify.column2, "res_users_id")

        delegate_approvers = delegate_model._fields["approver_ids"]
        self.assertEqual(
            delegate_approvers.relation,
            "res_users_studio_approval_rule_delegate_rel",
        )
        self.assertEqual(delegate_approvers.column1, "workflow_studio_approval_rule_delegate_id")
        self.assertEqual(delegate_approvers.column2, "res_users_id")

        excluded_fields = export_model._fields["excluded_fields"]
        self.assertEqual(
            excluded_fields.relation,
            "ir_model_fields_studio_export_model_rel",
        )
        self.assertEqual(excluded_fields.column1, "studio_export_model_id")
        self.assertEqual(excluded_fields.column2, "ir_model_fields_id")

        default_export_data = export_wizard_model._fields["default_export_data"]
        self.assertEqual(default_export_data.relation, "rel_studio_export_wizard_data")
        self.assertEqual(default_export_data.column1, "workflow_studio_export_wizard_id")
        self.assertEqual(default_export_data.column2, "workflow_studio_export_wizard_data_id")

        additional_export_data = export_wizard_model._fields["additional_export_data"]
        self.assertFalse(
            additional_export_data.store,
            "Computed additional export data should stay non-stored",
        )
