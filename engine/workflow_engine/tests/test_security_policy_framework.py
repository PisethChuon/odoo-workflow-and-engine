# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo import api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import common


class TestWorkflowSecurityPolicyFramework(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.User = cls.env["res.users"]
        cls.Group = cls.env["res.groups"]
        cls.Category = cls.env["workflow.approval.category"]
        cls.Version = cls.env["workflow.approval.category.version"]
        cls.Request = cls.env["workflow.base.approval.request"]
        cls.Template = cls.env["workflow.access.policy.template"]
        cls.PermissionService = cls.env["workflow.engine.permission.service"]
        cls.IrRule = cls.env["ir.rule"]
        cls.VisibilityScope = cls.env["workflow.request.visibility.scope"]
        cls.DiagnosticWizard = cls.env["workflow.security.access.diagnostic.wizard"]
        cls.VisibilityScopeWizard = cls.env["workflow.request.visibility.scope.bulk.wizard"]
        cls.Department = cls.env["hr.department"]
        cls.Employee = cls.env["hr.employee"]
        cls.Line = cls.env["workflow.approval.group.line"]
        cls.Team = cls.env["workflow.approval.group.team"]

        workflow_group = cls.env.ref("workflow_engine.group_workflow_approval_user")
        request_reader_group = cls.env.ref("workflow_engine.group_workflow_request_reader")
        unique = uuid4().hex[:8]

        cls.static_reader_group = cls.Group.create(
            {
                "name": f"Workflow Static Reader {unique}",
            }
        )

        def _new_user(name_prefix, group_ids=None):
            group_ids = group_ids or [workflow_group.id]
            return cls.User.with_context(no_reset_password=True).create(
                {
                    "name": f"{name_prefix} {unique}",
                    "login": f"{name_prefix.lower()}_{unique}",
                    "email": f"{name_prefix.lower()}_{unique}@example.com",
                    "group_ids": [(6, 0, group_ids)],
                }
            )

        def _ensure_employee(user, **extra_vals):
            employee = user.employee_id.sudo()
            values = {
                "name": user.name,
                "user_id": user.id,
                "company_id": user.company_id.id if user.company_id else False,
            }
            values.update(extra_vals)
            if employee:
                employee.write(extra_vals)
                return employee
            return cls.Employee.sudo().create(values)

        cls.requester = _new_user("requester")
        cls.other_requester = _new_user("otherrequester")
        cls.manager = _new_user("manager")
        cls.other_manager = _new_user("othermanager")
        cls.static_reader = _new_user(
            "reader",
            [request_reader_group.id, cls.static_reader_group.id],
        )
        cls.scope_reader = _new_user("scopereader", [request_reader_group.id])

        manager_employee = _ensure_employee(cls.manager)
        other_manager_employee = _ensure_employee(cls.other_manager)
        _ensure_employee(cls.static_reader)
        _ensure_employee(cls.scope_reader)

        cls.department_a = cls.Department.sudo().create(
            {
                "name": f"Security Dept A {unique}",
                "manager_id": manager_employee.id,
            }
        )
        cls.department_b = cls.Department.sudo().create(
            {
                "name": f"Security Dept B {unique}",
                "manager_id": other_manager_employee.id,
            }
        )

        cls.line_a = cls.Line.sudo().create(
            {
                "name": f"Line A {unique}",
                "department_id": cls.department_a.id,
                "hr_line_code": f"LINE-A-{unique}",
            }
        )
        cls.line_b = cls.Line.sudo().create(
            {
                "name": f"Line B {unique}",
                "department_id": cls.department_b.id,
                "hr_line_code": f"LINE-B-{unique}",
            }
        )
        cls.team_a = cls.Team.sudo().create(
            {
                "name": f"Team A {unique}",
                "line_id": cls.line_a.id,
                "hr_team_code": f"TEAM-A-{unique}",
            }
        )
        cls.team_b = cls.Team.sudo().create(
            {
                "name": f"Team B {unique}",
                "line_id": cls.line_b.id,
                "hr_team_code": f"TEAM-B-{unique}",
            }
        )

        _ensure_employee(
            cls.requester,
            parent_id=manager_employee.id,
            department_id=cls.department_a.id,
            x_line_code=cls.line_a.hr_line_code,
            x_team_code=cls.team_a.hr_team_code,
        )
        _ensure_employee(
            cls.other_requester,
            parent_id=other_manager_employee.id,
            department_id=cls.department_b.id,
            x_line_code=cls.line_b.hr_line_code,
            x_team_code=cls.team_b.hr_team_code,
        )

        base_request_model = cls.env["ir.model"]._get("workflow.base.approval.request")
        cls.category = cls.Category.sudo().create(
            {
                "name": f"Security Policy Category {unique}",
                "res_model": base_request_model.id,
                "zero_trust_enforced": True,
                "allowed_user_ids": [(6, 0, [cls.requester.id])],
            }
        )
        cls.version = cls.Version.sudo().create(
            {
                "name": f"v_security_{unique}",
                "category_id": cls.category.id,
                "is_active": True,
            }
        )
        cls.category.sudo().write({"active_version_id": cls.version.id})
        cls.request = cls.Request.sudo().create(
            {
                "name": f"REQ_SECURITY_{unique}",
                "category_id": cls.category.id,
                "request_owner_id": cls.requester.id,
                "state": "waiting",
            }
        )
        cls.other_request = cls.Request.sudo().create(
            {
                "name": f"REQ_SECURITY_OTHER_{unique}",
                "category_id": cls.category.id,
                "request_owner_id": cls.other_requester.id,
                "state": "waiting",
            }
        )

    def _clear_rule_caches(self):
        self.env.registry.clear_cache()

    def _publish_policy(self, rule_values_list, template_values=None, note=False):
        values = {
            "name": f"Security Template {uuid4().hex[:8]}",
            "zero_trust_enforced": True,
            "rule_ids": [(0, 0, vals) for vals in rule_values_list],
        }
        if template_values:
            values.update(template_values)
        template = self.Template.create(values)
        self.category._apply_access_policy_template(template)
        snapshots = self.category._publish_security_policy(note=note or template.display_name)
        self._clear_rule_caches()
        return template, snapshots

    def _reader_rule(self, **extra_vals):
        values = {
            "name": "Static Reader Rule",
            "audience_group_id": self.static_reader_group.id,
            "mode": "preset",
            "preset_scope": "all_requests",
            "access_level": "read",
        }
        values.update(extra_vals)
        return values

    def _visible_request_ids(self, user):
        self._clear_rule_caches()
        env = api.Environment(self.env.cr, user.id, dict(self.env.context))
        return set(
            env["workflow.base.approval.request"]
            .search([("id", "in", [self.request.id, self.other_request.id])])
            .ids
        )

    def test_request_snapshot_fields_resolve_manager_line_and_team_mappings(self):
        self.assertEqual(self.request.request_owner_manager_user_id, self.manager)
        self.assertEqual(self.request.request_owner_line_code, self.line_a.hr_line_code)
        self.assertEqual(self.request.request_owner_team_code, self.team_a.hr_team_code)
        self.assertEqual(self.request.request_owner_line_id, self.line_a)
        self.assertEqual(self.request.request_owner_team_id, self.team_a)

    def test_apply_template_updates_draft_only(self):
        template = self.Template.create(
            {
                "name": "Draft Only Template",
                "zero_trust_enforced": False,
                "create_access_mode": "restricted",
                "create_allowed_user_ids": [(6, 0, [self.requester.id])],
                "rule_ids": [
                    (
                        0,
                        0,
                        self._reader_rule(),
                    )
                ],
            }
        )

        self.category._apply_access_policy_template(template)
        self.category.invalidate_recordset(
            [
                "zero_trust_enforced",
                "security_policy_draft_zero_trust_enforced",
                "create_access_mode",
                "security_policy_draft_create_access_mode",
                "security_policy_rule_ids",
            ]
        )

        self.assertTrue(self.category.zero_trust_enforced)
        self.assertFalse(self.category.security_policy_draft_zero_trust_enforced)
        self.assertEqual(self.category.create_access_mode, "inherit_current_behavior")
        self.assertEqual(self.category.security_policy_draft_create_access_mode, "restricted")
        self.assertEqual(
            self.category.security_policy_draft_create_allowed_user_ids,
            self.requester,
        )
        self.assertEqual(self.category.access_policy_template_id, template)
        self.assertEqual(len(self.category.security_policy_rule_ids), 1)
        self.assertFalse(self.category.security_policy_live_rule_payload)

    def test_publish_template_moves_request_creation_policy_to_live_snapshot(self):
        template = self.Template.create(
            {
                "name": "Create Access Template",
                "create_access_mode": "restricted",
                "create_allowed_user_ids": [(6, 0, [self.requester.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self.assertEqual(self.category.create_access_mode, "inherit_current_behavior")

        snapshot = self.category._publish_security_policy(note="publish create access")
        self.category.invalidate_recordset(
            [
                "create_access_mode",
                "create_allowed_user_ids",
                "security_policy_last_published_snapshot_id",
            ]
        )

        self.assertEqual(self.category.create_access_mode, "restricted")
        self.assertEqual(self.category.create_allowed_user_ids, self.requester)
        self.assertTrue(snapshot.is_current_snapshot)
        self.assertEqual(
            snapshot.runtime_payload.get("create_access_mode"),
            "restricted",
        )
        self.assertEqual(
            snapshot.runtime_payload.get("create_allowed_user_ids"),
            [self.requester.id],
        )
        self.assertTrue(self.category.can_user_create_request(user=self.requester))
        self.assertFalse(self.category.can_user_create_request(user=self.manager))

    def test_read_visible_category_hides_create_button_flag_for_non_creator(self):
        self.category.sudo().write(
            {
                "zero_trust_enforced": True,
                "allowed_user_ids": [(6, 0, [self.manager.id])],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "create_access_mode": "restricted",
                "create_allowed_user_ids": [(6, 0, [self.requester.id])],
                "create_allowed_group_ids": [(5, 0, 0)],
                "create_allowed_department_ids": [(5, 0, 0)],
            }
        )
        self._clear_rule_caches()

        self.assertTrue(
            self.PermissionService.can_access_category(self.category, user=self.manager),
            "Manager has read visibility through the category allowlist.",
        )
        self.assertFalse(self.category.can_user_create_request(user=self.manager))
        self.assertFalse(self.category.with_user(self.manager).can_create_request)
        self.assertTrue(self.category.with_user(self.requester).can_create_request)

    def test_active_security_tab_summarizes_current_published_rules(self):
        _, snapshot = self._publish_policy(
            [
                self._reader_rule(
                    name="Current Published Reader",
                    audience_group_id=self.static_reader_group.id,
                    preset_scope="all_requests",
                )
            ],
            note="summary",
        )

        html = self.category.security_policy_current_rule_summary_html or ""
        self.assertIn(snapshot.display_name, html)
        self.assertIn("Current Published Reader", html)
        self.assertIn(self.static_reader_group.name, html)
        self.assertIn("Read Only", html)
        self.assertIn("Preset", html)
        self.assertIn("All Requests", html)

    def test_implied_groups_match_create_and_static_read_policy(self):
        unique = uuid4().hex[:8]
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        parent_group = self.Group.create(
            {
                "name": f"Workflow Implied Audience {unique}",
                "implied_ids": [(6, 0, [workflow_group.id, self.static_reader_group.id])],
            }
        )
        implied_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Implied Workflow User {unique}",
                "login": f"implied_workflow_user_{unique}",
                "email": f"implied_workflow_user_{unique}@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, parent_group.id])
                ],
            }
        )
        template = self.Template.create(
            {
                "name": "Implied Group Create Access Template",
                "zero_trust_enforced": True,
                "create_access_mode": "restricted",
                "create_allowed_group_ids": [(6, 0, [workflow_group.id])],
                "rule_ids": [
                    (
                        0,
                        0,
                        self._reader_rule(
                            audience_group_id=self.static_reader_group.id,
                            preset_scope="all_requests",
                        ),
                    )
                ],
            }
        )

        self.category._apply_access_policy_template(template)
        self.category._publish_security_policy(note="implied group access")
        self._clear_rule_caches()
        implied_user.invalidate_recordset(["group_ids", "all_group_ids"])
        self.category.invalidate_recordset(
            ["create_access_mode", "create_allowed_group_ids", "security_policy_live_rule_payload"]
        )

        self.assertTrue(implied_user.has_group("workflow_engine.group_workflow_approval_user"))
        self.assertTrue(self.category.can_user_create_request(user=implied_user))
        self.assertTrue(
            self.PermissionService._has_static_policy_category_access(
                self.category,
                implied_user,
            )
        )
        visible_category = self.Category.with_user(implied_user).search(
            [("id", "=", self.category.id)]
        )
        self.assertEqual(visible_category, self.category)

    def test_create_allowed_group_can_see_category_without_request_read(self):
        unique = uuid4().hex[:8]
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        creator_group = self.Group.create(
            {
                "name": f"Workflow Creator Audience {unique}",
                "implied_ids": [(6, 0, [workflow_group.id])],
            }
        )
        creator_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Create Only Workflow User {unique}",
                "login": f"create_only_workflow_user_{unique}",
                "email": f"create_only_workflow_user_{unique}@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, creator_group.id])
                ],
            }
        )
        template = self.Template.create(
            {
                "name": "Create Only Category Visibility Template",
                "zero_trust_enforced": True,
                "create_access_mode": "restricted",
                "create_allowed_group_ids": [(6, 0, [workflow_group.id])],
            }
        )

        self.category._apply_access_policy_template(template)
        self.category._publish_security_policy(note="create-only category visibility")
        self._clear_rule_caches()
        creator_user.invalidate_recordset(["group_ids", "all_group_ids"])
        self.category.invalidate_recordset(["create_access_mode", "create_allowed_group_ids"])

        self.assertTrue(creator_user.has_group("workflow_engine.group_workflow_approval_user"))
        self.assertTrue(self.category.can_user_create_request(user=creator_user))
        self.assertFalse(self.PermissionService.can_access_category(self.category, user=creator_user))
        visible_category = self.Category.with_user(creator_user).search(
            [("id", "=", self.category.id)]
        )
        self.assertEqual(visible_category, self.category)
        self.assertFalse(
            self.PermissionService.can_access_request(
                self.other_request,
                user=creator_user,
                scope="read",
            )
        )
        created_request = self.Request.with_user(creator_user).create(
            {
                "name": f"REQ_CREATE_ONLY_{unique}",
                "category_id": self.category.id,
                "request_owner_id": creator_user.id,
            }
        )
        self.assertEqual(created_request.category_id, self.category)

    def test_field_rule_runtime_context_uses_implied_groups(self):
        unique = uuid4().hex[:8]
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        parent_group = self.Group.create(
            {
                "name": f"Field Rule Implied Group {unique}",
                "implied_ids": [(6, 0, [workflow_group.id])],
            }
        )
        implied_user = self.User.with_context(no_reset_password=True).create(
            {
                "name": f"Field Rule User {unique}",
                "login": f"field_rule_user_{unique}",
                "email": f"field_rule_user_{unique}@example.com",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id, parent_group.id])
                ],
            }
        )
        implied_user.invalidate_recordset(["group_ids", "all_group_ids"])

        context = self.env["workflow.engine.field.rule.service"]._runtime_eval_context(
            self.request,
            self.request,
            user=implied_user,
        )

        self.assertIn(workflow_group.id, context["runtime_values"]["wf_actor_group_ids"])
        self.assertIn(workflow_group.id, context["safe_symbols"]["__actor_group_ids__"])

    def test_workflow_performance_indexes_are_deployable(self):
        expected_indexes = {
            "wf_base_request_category_state_id_idx",
            "wf_base_request_list_order_idx",
            "wf_approver_open_user_request_idx",
            "wf_approver_request_iteration_node_status_idx",
            "wf_task_assignee_open_user_request_idx",
            "wf_task_event_actor_request_idx",
            "wf_visibility_scope_active_user_request_idx",
            "wf_delegation_active_delegate_window_idx",
        }
        self.env.cr.execute(
            """
            SELECT indexname
              FROM pg_indexes
             WHERE schemaname = current_schema()
               AND indexname = ANY(%s)
            """,
            [list(expected_indexes)],
        )
        actual_indexes = {row[0] for row in self.env.cr.fetchall()}
        self.assertFalse(expected_indexes - actual_indexes)

    def test_security_policy_workspace_opens_category_modal(self):
        action = self.category.action_open_security_policy_workspace()

        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "workflow.approval.category")
        self.assertEqual(action["res_id"], self.category.id)
        self.assertEqual(action["target"], "new")
        self.assertEqual(
            action["view_id"][0],
            self.env.ref(
                "workflow_engine.workflow_approval_category_security_policy_workspace_view_form"
            ).id,
        )
        self.assertTrue(self.category.security_policy_draft_initialized)

    def test_apply_template_wizard_preview_assigns_counts_for_virtual_records(self):
        wizard_model = self.env["workflow.access.policy.apply.wizard"].sudo()
        empty_wizard = wizard_model.new({})

        self.assertEqual(empty_wizard.changed_category_count, 0)
        self.assertEqual(empty_wizard.changed_rule_count, 0)
        self.assertTrue(empty_wizard.preview_html)

        template = self.Template.create(
            {
                "name": "Preview Template",
                "zero_trust_enforced": False,
                "rule_ids": [(0, 0, self._reader_rule())],
            }
        )
        preview_wizard = wizard_model.new({})
        preview_wizard.template_id = template
        preview_wizard.category_ids = self.category

        self.assertGreaterEqual(preview_wizard.changed_category_count, 0)
        self.assertGreaterEqual(preview_wizard.changed_rule_count, 0)
        self.assertTrue(preview_wizard.preview_html)

    def test_publish_wizard_preview_uses_real_category_id_for_virtual_records(self):
        template = self.Template.create(
            {
                "name": "Publish Preview Template",
                "zero_trust_enforced": True,
                "rule_ids": [(0, 0, self._reader_rule())],
            }
        )
        self.category._apply_access_policy_template(template)

        wizard_model = self.env["workflow.access.policy.publish.wizard"].sudo()
        preview_wizard = wizard_model.new({})
        preview_wizard.category_ids = self.category

        self.assertEqual(preview_wizard.compiled_rule_count, 1)
        self.assertFalse(preview_wizard.validation_error)
        self.assertNotIn("NewId", preview_wizard.preview_html or "")
        self.assertIn("Publish will replace", preview_wizard.preview_html or "")

    def test_publish_static_policy_grants_read_and_rollback_restores_previous_state(self):
        baseline_snapshot = self.category._publish_security_policy(note="baseline")
        self._clear_rule_caches()

        self.assertFalse(
            self.PermissionService.can_access_request(
                self.request,
                user=self.static_reader,
                scope="read",
            )
        )
        self.assertEqual(self._visible_request_ids(self.static_reader), set())

        template, published_snapshot = self._publish_policy(
            [self._reader_rule()],
            note="grant static read",
        )

        self.assertEqual(self.category.access_policy_template_id, template)
        self.assertTrue(
            self.PermissionService.can_access_request(
                self.request,
                user=self.static_reader,
                scope="read",
            )
        )
        self.assertEqual(
            self._visible_request_ids(self.static_reader),
            {self.request.id, self.other_request.id},
        )
        self.assertEqual(
            self.category.with_user(self.static_reader).read(["name"])[0]["name"],
            self.category.name,
        )
        self.assertEqual(
            self.request.with_user(self.static_reader).read(["category_id"])[0]["category_id"][0],
            self.category.id,
        )

        generated_rules = self.IrRule.sudo().search(
            [
                ("workflow_security_policy_generated", "=", True),
                ("workflow_security_category_id", "=", self.category.id),
            ]
        )
        self.assertTrue(generated_rules)
        self.assertEqual(len(published_snapshot), 1)
        self.assertEqual(
            self.category.security_policy_last_published_snapshot_id,
            published_snapshot,
        )

        self.category._restore_security_policy_snapshot(baseline_snapshot)
        self.category._publish_security_policy(note="rollback baseline")
        self._clear_rule_caches()

        self.assertFalse(
            self.PermissionService.can_access_request(
                self.request,
                user=self.static_reader,
                scope="read",
            )
        )
        self.assertEqual(self._visible_request_ids(self.static_reader), set())

    def test_publish_static_policy_presets_filter_expected_request_snapshots(self):
        cases = [
            (
                "all_requests",
                {},
                {self.request.id, self.other_request.id},
            ),
            (
                "request_owner_department",
                {"department_ids": [(6, 0, [self.department_a.id])]},
                {self.request.id},
            ),
            (
                "request_owner_user",
                {"request_owner_user_ids": [(6, 0, [self.requester.id])]},
                {self.request.id},
            ),
            (
                "request_owner_manager",
                {"manager_user_ids": [(6, 0, [self.manager.id])]},
                {self.request.id},
            ),
            (
                "request_owner_line",
                {"line_ids": [(6, 0, [self.line_a.id])]},
                {self.request.id},
            ),
            (
                "request_owner_team",
                {"team_ids": [(6, 0, [self.team_a.id])]},
                {self.request.id},
            ),
        ]

        request_records = self.request | self.other_request
        for preset_scope, selector_values, expected_ids in cases:
            rule_values = self._reader_rule(
                preset_scope=preset_scope,
                **selector_values,
            )
            self._publish_policy([rule_values], note=preset_scope)

            self.assertEqual(
                self._visible_request_ids(self.static_reader),
                expected_ids,
                "Published preset %s should filter the request report correctly."
                % preset_scope,
            )
            self.assertEqual(
                self.PermissionService.allowed_request_ids(
                    request_records,
                    user=self.static_reader,
                    scope="read",
                ),
                expected_ids,
                "Batched read access should match the compiled preset %s." % preset_scope,
            )

    def test_publish_static_policy_read_only_does_not_grant_edit(self):
        self._publish_policy([self._reader_rule()], note="readonly access")

        self.assertTrue(
            self.PermissionService.can_access_request(
                self.request,
                user=self.static_reader,
                scope="read",
            )
        )
        self.assertFalse(
            self.PermissionService.can_access_request(
                self.request,
                user=self.static_reader,
                scope="edit",
            )
        )

        with self.assertRaises(UserError):
            self.request.with_user(self.static_reader).write({"comment": "blocked"})

    def test_request_reader_category_audience_is_read_only(self):
        self.category.sudo().write({"allowed_user_ids": [(4, self.scope_reader.id)]})

        self.assertTrue(
            self.PermissionService.can_access_request(
                self.request,
                user=self.scope_reader,
                scope="read",
            )
        )
        self.assertFalse(
            self.PermissionService.can_access_request(
                self.request,
                user=self.scope_reader,
                scope="edit",
            )
        )
        self.assertEqual(
            self._visible_request_ids(self.scope_reader),
            {self.request.id, self.other_request.id},
        )

        with self.assertRaises(AccessError):
            self.Request.with_user(self.scope_reader).create(
                {
                    "name": f"REQ_SCOPE_READER_{uuid4().hex[:6]}",
                    "category_id": self.category.id,
                    "request_owner_id": self.requester.id,
                }
            )

    def test_visibility_scope_bulk_wizard_grants_and_revokes_read_access(self):
        self.assertFalse(
            self.PermissionService.can_access_request(
                self.other_request,
                user=self.scope_reader,
                scope="read",
            )
        )

        grant_wizard = self.VisibilityScopeWizard.create(
            {
                "operation": "grant",
                "scope": "read",
                "request_ids": [(6, 0, [self.other_request.id])],
                "user_ids": [(6, 0, [self.scope_reader.id])],
                "reason": "Validation grant",
            }
        )
        grant_wizard.action_apply()

        self.assertTrue(
            self.PermissionService.can_access_request(
                self.other_request,
                user=self.scope_reader,
                scope="read",
            )
        )
        self.assertEqual(self._visible_request_ids(self.scope_reader), {self.other_request.id})

        revoke_wizard = self.VisibilityScopeWizard.create(
            {
                "operation": "revoke",
                "scope": "read",
                "request_ids": [(6, 0, [self.other_request.id])],
                "user_ids": [(6, 0, [self.scope_reader.id])],
            }
        )
        revoke_wizard.action_apply()

        self.assertFalse(
            self.PermissionService.can_access_request(
                self.other_request,
                user=self.scope_reader,
                scope="read",
            )
        )
        self.assertEqual(self._visible_request_ids(self.scope_reader), set())

    def test_archived_user_scope_does_not_leak_through_other_active_scope(self):
        self.VisibilityScope.sudo().create(
            {
                "request_id": self.other_request.id,
                "scope": "read",
                "allowed_user_id": self.static_reader.id,
                "granted_by_user_id": self.env.user.id,
            }
        )
        self.VisibilityScope.sudo().create(
            {
                "request_id": self.other_request.id,
                "scope": "read",
                "allowed_user_id": self.scope_reader.id,
                "granted_by_user_id": self.env.user.id,
                "active": False,
            }
        )

        self.assertTrue(
            self.PermissionService.can_access_request(
                self.other_request,
                user=self.static_reader,
                scope="read",
            )
        )
        self.assertFalse(
            self.PermissionService.can_access_request(
                self.other_request,
                user=self.scope_reader,
                scope="read",
            )
        )
        self.assertEqual(self._visible_request_ids(self.static_reader), {self.other_request.id})
        self.assertEqual(self._visible_request_ids(self.scope_reader), set())

    def test_base_record_rule_self_heal_restores_request_reader_rule_drift(self):
        visibility_rule = self.env.ref(
            "workflow_engine.rule_workflow_base_for_visibility_scope_read"
        ).sudo()
        approval_group = self.env.ref("workflow_engine.group_workflow_approval_user")
        request_reader_group = self.env.ref("workflow_engine.group_workflow_request_reader")

        visibility_rule.write(
            {
                "active": False,
                "groups": [(6, 0, [approval_group.id])],
                "domain_force": "[('id', '=', 0)]",
                "perm_read": False,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )

        self.IrRule.init()

        repaired_rule = self.env.ref(
            "workflow_engine.rule_workflow_base_for_visibility_scope_read"
        ).sudo()
        self.assertTrue(repaired_rule.active)
        self.assertEqual(set(repaired_rule.groups.ids), {request_reader_group.id})
        self.assertTrue(repaired_rule.perm_read)
        self.assertFalse(repaired_rule.perm_write)
        self.assertFalse(repaired_rule.perm_create)
        self.assertFalse(repaired_rule.perm_unlink)
        self.assertNotIn("visibility_scope_ids.active", repaired_rule.domain_force)
        self.assertIn("visibility_scope_user_ids", repaired_rule.domain_force)
        self.assertIn("visibility_scope_group_ids", repaired_rule.domain_force)
        self.assertIn("user.all_group_ids.ids", repaired_rule.domain_force)

    def test_security_access_diagnostic_identifies_static_policy_and_scope_access(self):
        self._publish_policy([self._reader_rule()], note="diagnostic")
        static_wizard = self.DiagnosticWizard.create(
            {
                "user_id": self.static_reader.id,
                "request_id": self.request.id,
            }
        )
        self.assertTrue(static_wizard.access_granted)
        self.assertIn("Matched published static read policy.", static_wizard.analysis_html)

        self.VisibilityScope.sudo().create(
            {
                "request_id": self.other_request.id,
                "scope": "read",
                "allowed_user_id": self.scope_reader.id,
                "granted_by_user_id": self.env.user.id,
            }
        )
        scope_wizard = self.DiagnosticWizard.create(
            {
                "user_id": self.scope_reader.id,
                "request_id": self.other_request.id,
            }
        )
        self.assertTrue(scope_wizard.access_granted)
        self.assertIn("Matched visibility scope access.", scope_wizard.analysis_html)

        category_wizard = self.DiagnosticWizard.create(
            {
                "user_id": self.static_reader.id,
                "category_id": self.category.id,
            }
        )
        self.assertTrue(category_wizard.access_granted)
        self.assertIn("The user can see this category, but cannot create new requests in it.", category_wizard.analysis_html)
        self.assertIn("Published static read policy targets this user", category_wizard.analysis_html)
        self.assertIn("New Request button allowed", category_wizard.analysis_html)

    def test_restricted_create_policy_blocks_non_allowlisted_approval_user(self):
        self.category.sudo().write(
            {
                "allowed_user_ids": [(6, 0, [self.requester.id, self.manager.id])],
                "create_access_mode": "restricted",
                "create_allowed_user_ids": [(6, 0, [self.requester.id])],
                "create_allowed_group_ids": [(5, 0, 0)],
                "create_allowed_department_ids": [(5, 0, 0)],
            }
        )

        action = self.category.with_user(self.requester).create_request()
        self.assertEqual(action.get("type"), "ir.actions.act_window")

        created = self.Request.with_user(self.requester).create(
            {
                "name": f"REQ_RESTRICTED_{uuid4().hex[:6]}",
                "category_id": self.category.id,
                "request_owner_id": self.requester.id,
            }
        )
        self.assertTrue(created)

        with self.assertRaises(AccessError):
            self.category.with_user(self.manager).action_new_request()
        with self.assertRaises(AccessError):
            self.category.with_user(self.manager).create_request()
        with self.assertRaises(AccessError):
            self.Request.with_user(self.manager).create(
                {
                    "name": f"REQ_RESTRICTED_BLOCKED_{uuid4().hex[:6]}",
                    "category_id": self.category.id,
                    "request_owner_id": self.requester.id,
                }
            )

    def test_all_workflow_users_create_mode_allows_create_without_category_allowlist(self):
        self.category.sudo().write(
            {
                "zero_trust_enforced": True,
                "allowed_user_ids": [(5, 0, 0)],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "create_access_mode": "inherit_current_behavior",
                "create_allowed_user_ids": [(5, 0, 0)],
                "create_allowed_group_ids": [(5, 0, 0)],
                "create_allowed_department_ids": [(5, 0, 0)],
            }
        )
        self._clear_rule_caches()

        self.assertFalse(
            self.PermissionService.can_access_category(self.category, user=self.manager),
            "Manager should not have category read allowlist access in this scenario.",
        )
        self.assertTrue(self.category.can_user_create_request(user=self.manager))

        action = self.category.with_user(self.manager).create_request()
        self.assertEqual(action.get("type"), "ir.actions.act_window")

        created = self.Request.with_user(self.manager).create(
            {
                "name": f"REQ_ALL_WORKFLOW_USERS_{uuid4().hex[:6]}",
                "category_id": self.category.id,
                "request_owner_id": self.manager.id,
            }
        )
        self.assertTrue(created)

    def test_security_access_diagnostic_blocks_stale_base_create_rule(self):
        self.category.sudo().write(
            {
                "zero_trust_enforced": True,
                "allowed_user_ids": [(5, 0, 0)],
                "allowed_group_ids": [(5, 0, 0)],
                "allowed_department_ids": [(5, 0, 0)],
                "create_access_mode": "inherit_current_behavior",
                "create_allowed_user_ids": [(5, 0, 0)],
                "create_allowed_group_ids": [(5, 0, 0)],
                "create_allowed_department_ids": [(5, 0, 0)],
            }
        )
        self.env.ref("workflow_engine.rule_workflow_base_for_create_audience").sudo().write(
            {
                "domain_force": "[('category_id.allowed_user_ids', 'in', [user.id])]",
            }
        )
        self._clear_rule_caches()

        wizard = self.DiagnosticWizard.create(
            {
                "user_id": self.manager.id,
                "category_id": self.category.id,
            }
        )

        self.assertFalse(wizard.access_granted)
        self.assertIn("The user can see this category, but saving/submitting a new request may fail.", wizard.analysis_html)
        self.assertIn("Save new request allowed", wizard.analysis_html)
        self.assertIn("Needs module upgrade", wizard.analysis_html)

    def test_publish_blocks_unmapped_line_selector(self):
        unmapped_line = self.Line.sudo().create(
            {
                "name": f"Unmapped Line {uuid4().hex[:8]}",
                "department_id": self.department_a.id,
            }
        )
        template = self.Template.create(
            {
                "name": "Unmapped Line Template",
                "rule_ids": [
                    (
                        0,
                        0,
                        self._reader_rule(
                            preset_scope="request_owner_line",
                            line_ids=[(6, 0, [unmapped_line.id])],
                        ),
                    )
                ],
            }
        )

        self.category._apply_access_policy_template(template)

        with self.assertRaises(ValidationError):
            self.category._compile_security_policy_payloads()

    def test_publish_blocks_non_whitelisted_safe_domain_field(self):
        template = self.Template.create(
            {
                "name": "Unsafe Builder Template",
                "rule_ids": [
                    (
                        0,
                        0,
                        self._reader_rule(
                            mode="domain_builder",
                            domain_builder="[('message_partner_ids', '!=', False)]",
                        ),
                    )
                ],
            }
        )

        self.category._apply_access_policy_template(template)

        with self.assertRaises(ValidationError):
            self.category._compile_security_policy_payloads()
