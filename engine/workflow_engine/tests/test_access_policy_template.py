# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo.tests import common


class TestWorkflowAccessPolicyTemplate(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Template = cls.env["workflow.access.policy.template"]
        cls.ResGroup = cls.env["res.groups"]
        cls.Rule = cls.env["ir.rule"]
        cls.Access = cls.env["ir.model.access"]

        unique = uuid4().hex[:8]
        base_user_group = cls.env.ref("base.group_user")
        cls.principal_user = cls.User.with_context(no_reset_password=True).create(
            {
                "name": f"Policy Principal {unique}",
                "login": f"policy_principal_{unique}",
                "email": f"policy_principal_{unique}@example.com",
                "group_ids": [(6, 0, [base_user_group.id])],
            }
        )

        cls.extra_allowed_group = cls.ResGroup.create(
            {
                "name": f"WF Policy Allowed Group {unique}",
            }
        )
        cls.group_member_user = cls.User.with_context(no_reset_password=True).create(
            {
                "name": f"Policy Group Member {unique}",
                "login": f"policy_group_member_{unique}",
                "email": f"policy_group_member_{unique}@example.com",
                "group_ids": [(6, 0, [base_user_group.id, cls.extra_allowed_group.id])],
            }
        )

        request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.create(
            {
                "name": f"Policy Category {unique}",
                "res_model": request_model.id,
            }
        )

    def _publish_category_policy(self):
        self.category._publish_security_policy(note="template publish")
        self._invalidate_user_groups(self.principal_user | self.group_member_user)

    def _invalidate_user_groups(self, users):
        fields_to_invalidate = [
            field_name
            for field_name in ("group_ids", "groups_id")
            if field_name in self.User._fields
        ]
        users.invalidate_recordset(fields_to_invalidate)

    def test_apply_policy_template_defers_auto_grant_until_publish(self):
        template = self.Template.create(
            {
                "name": "Auto Grant Allowed Users",
                "auto_grant_workflow_user_group": True,
                "allowed_user_ids": [(6, 0, [self.principal_user.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self._invalidate_user_groups(self.principal_user)

        self.assertFalse(
            self.principal_user.has_group("workflow_engine.group_workflow_approval_user")
        )

        self._publish_category_policy()

        self.assertTrue(
            self.principal_user.has_group("workflow_engine.group_workflow_approval_user")
        )

    def test_publish_policy_auto_grants_workflow_user_group_to_allowed_group_members(self):
        template = self.Template.create(
            {
                "name": "Auto Grant Allowed Group Members",
                "auto_grant_workflow_user_group": True,
                "allowed_group_ids": [(6, 0, [self.extra_allowed_group.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self._invalidate_user_groups(self.group_member_user)
        self.assertFalse(
            self.group_member_user.has_group(
                "workflow_engine.group_workflow_approval_user"
            )
        )

        self._publish_category_policy()

        self.assertTrue(
            self.group_member_user.has_group(
                "workflow_engine.group_workflow_approval_user"
            )
        )

    def test_publish_policy_auto_grants_workflow_user_group_to_create_audience(self):
        unique = uuid4().hex[:8]
        create_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Policy Create User {unique}",
                "login": f"policy_create_user_{unique}",
                "email": f"policy_create_user_{unique}@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        template = self.Template.create(
            {
                "name": "Auto Grant Create Audience",
                "auto_grant_workflow_user_group": True,
                "create_access_mode": "restricted",
                "create_allowed_user_ids": [(6, 0, [create_user.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self._invalidate_user_groups(create_user)
        self.assertFalse(
            create_user.has_group("workflow_engine.group_workflow_approval_user")
        )

        self.category._publish_security_policy(note="create audience auto grant")
        self._invalidate_user_groups(create_user)

        self.assertTrue(
            create_user.has_group("workflow_engine.group_workflow_approval_user")
        )
        self.assertTrue(self.category.can_user_create_request(user=create_user))

    def test_create_audience_rule_does_not_grant_broad_read_access(self):
        unique = uuid4().hex[:8]
        approval_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        creator = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Restricted Creator {unique}",
                "login": f"restricted_creator_{unique}",
                "email": f"restricted_creator_{unique}@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, approval_group.id])
                ],
            }
        )
        other_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Other Requester {unique}",
                "login": f"other_requester_{unique}",
                "email": f"other_requester_{unique}@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.category.write(
            {
                "zero_trust_enforced": True,
                "allow_requester_read": True,
                "allowed_user_ids": [(5, 0, 0)],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "create_access_mode": "restricted",
                "create_allowed_group_ids": [(6, 0, [approval_group.id])],
            }
        )
        self._invalidate_user_groups(creator)

        own_request = self.env["workflow.base.approval.request"].with_user(creator).create(
            {
                "name": "Own restricted create request",
                "category_id": self.category.id,
                "request_owner_id": creator.id,
            }
        )
        other_request = self.env["workflow.base.approval.request"].sudo().create(
            {
                "name": "Other restricted request",
                "category_id": self.category.id,
                "request_owner_id": other_user.id,
            }
        )

        visible = self.env["workflow.base.approval.request"].with_user(creator).search(
            [("category_id", "=", self.category.id)]
        )
        self.assertIn(own_request.id, visible.ids)
        self.assertNotIn(other_request.id, visible.ids)

    def test_publish_policy_can_disable_auto_grant(self):
        unique = uuid4().hex[:8]
        no_grant_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Policy No Grant {unique}",
                "login": f"policy_no_grant_{unique}",
                "email": f"policy_no_grant_{unique}@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        template = self.Template.create(
            {
                "name": "No Auto Grant",
                "auto_grant_workflow_user_group": False,
                "allowed_user_ids": [(6, 0, [no_grant_user.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self.category._publish_security_policy(note="no auto grant")
        self._invalidate_user_groups(no_grant_user)

        self.assertFalse(
            no_grant_user.has_group("workflow_engine.group_workflow_approval_user")
        )

    def test_template_apply_wizard_prefills_selected_template(self):
        template = self.Template.create(
            {
                "name": "Wizard Prefill Template",
            }
        )

        action = template.action_open_security_policy_apply_wizard()

        self.assertEqual(action["res_model"], "workflow.access.policy.apply.wizard")
        self.assertEqual(action["context"]["default_template_id"], template.id)

    def test_template_linked_categories_action_filters_current_template(self):
        template = self.Template.create(
            {
                "name": "Linked Categories Template",
            }
        )
        self.category._apply_access_policy_template(template)

        action = template.action_view_linked_categories()

        self.assertEqual(action["res_model"], "workflow.approval.category")
        self.assertEqual(action["domain"], [("access_policy_template_id", "=", template.id)])

    def test_apply_policy_template_skips_non_child_request_models(self):
        partner_model = self.env["ir.model"]._get("res.partner")
        request_reader_group = self.env.ref("workflow_engine.group_workflow_request_reader")
        category = self.Category.create(
            {
                "name": "Partner Policy Category",
                "res_model": partner_model.id,
            }
        )
        template = self.Template.create(
            {
                "name": "Partner Policy Template",
            }
        )

        category._apply_access_policy_template(template)

        bad_rules = self.Rule.sudo().search(
            [
                ("model_id", "=", partner_model.id),
                ("domain_force", "ilike", "x_approval_base_id."),
            ]
        )
        reader_acl = self.Access.sudo().search(
            [
                ("model_id", "=", partner_model.id),
                ("group_id", "=", request_reader_group.id),
            ]
        )

        self.assertFalse(bad_rules)
        self.assertFalse(reader_acl)
