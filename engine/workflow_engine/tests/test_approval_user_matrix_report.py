# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo import Command
from odoo.tests import common


class TestWorkflowApprovalUserMatrixReport(common.TransactionCase):
    def setUp(self):
        super().setUp()
        unique = uuid4().hex[:8]
        self.base_user_group = self.env.ref("base.group_user")
        self.base_request_model = self.env["ir.model"]._get("workflow.base.approval.request")
        self.department = self.env["hr.department"].create({"name": f"Matrix Department {unique}"})
        self.job = self.env["hr.job"].create({"name": f"Matrix Position {unique}"})
        self.user = self.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": f"Matrix Approver {unique}",
                "login": f"matrix.approver.{unique}@example.com",
                "email": f"matrix.approver.{unique}@example.com",
                "group_ids": [Command.set([self.base_user_group.id])],
            }
        )
        employee_vals = {
            "name": self.user.name,
            "user_id": self.user.id,
            "department_id": self.department.id,
            "job_id": self.job.id,
            "x_emp_code": f"MX{unique}",
            "x_ext_phone": "6045",
            "work_email": self.user.email,
            "work_phone": "6045",
            "mobile_phone": "0960000000",
        }
        if "x_team" in self.env["hr.employee"]._fields:
            employee_vals["x_team"] = f"Employee Team {unique}"
        if "x_line" in self.env["hr.employee"]._fields:
            employee_vals["x_line"] = f"Employee Line {unique}"
        self.employee = self.env["hr.employee"].create(employee_vals)
        self.category = self.env["workflow.approval.category"].create(
            {
                "name": f"Matrix Category {unique}",
                "res_model": self.base_request_model.id,
                "department_id": self.department.id,
            }
        )
        self.fallback_category = self.env["workflow.approval.category"].create(
            {
                "name": f"Fallback Category {unique}",
                "res_model": self.base_request_model.id,
                "department_id": self.department.id,
            }
        )
        self.version = self.env["workflow.approval.category.version"].create(
            {
                "name": "V1",
                "title": "Matrix Version",
                "category_id": self.category.id,
                "is_active": True,
            }
        )
        self.line = self.env["workflow.approval.group.line"].create(
            {
                "name": f"Matrix Line {unique}",
                "department_id": self.department.id,
            }
        )
        self.team = self.env["workflow.approval.group.team"].create(
            {
                "name": f"Matrix Team {unique}",
                "line_id": self.line.id,
            }
        )
        self.approval_group = self.env["workflow.approval.group"].create(
            {
                "name": f"Matrix Approval Group {unique}",
                "category_id": self.fallback_category.id,
                "department_id": self.department.id,
                "line_id": self.line.id,
                "team_id": self.team.id,
                "user_ids": [Command.set([self.user.id])],
            }
        )
        self.notification_only_group = self.env["workflow.approval.group"].create(
            {
                "name": f"Matrix Notification Group {unique}",
                "category_id": self.fallback_category.id,
                "department_id": self.department.id,
                "line_id": self.line.id,
                "team_id": self.team.id,
                "user_ids": [Command.set([self.user.id])],
            }
        )
        self.email_only_group = self.env["workflow.approval.group"].create(
            {
                "name": f"Matrix Email Group {unique}",
                "category_id": self.fallback_category.id,
                "department_id": self.department.id,
                "line_id": self.line.id,
                "team_id": self.team.id,
                "user_ids": [Command.set([self.user.id])],
            }
        )
        self.meta_task = self.env["workflow.category.version.meta.task"].create(
            {
                "name": "Manager Approval",
                "node_id": "Activity_Manager_Approval",
                "node_type": "sendTask",
                "sequence": 20,
                "version_id": self.version.id,
                "assignment_mode": "groups",
                "completion_mode": "any",
                "notification_delivery_mode": "channels",
                "notification_recipient_source": "approval_group_users",
                "notification_approval_group_ids": [
                    Command.set([self.approval_group.id, self.notification_only_group.id])
                ],
            }
        )
        self.email_channel_action = self.env["workflow.approval.action"].create(
            {
                "name": "Complete Notify Email",
                "action_type": "email",
                "version_id": self.version.id,
                "email_recipient_line_ids": [
                    Command.create(
                        {
                            "header": "to",
                            "source": "send_task",
                        }
                    ),
                    Command.create(
                        {
                            "header": "cc",
                            "source": "approval_group_users",
                            "approval_group_ids": [Command.set([self.approval_group.id])],
                            "domain": "[('active', '=', True)]",
                        }
                    ),
                    Command.create(
                        {
                            "header": "bcc",
                            "source": "approval_group_users",
                            "approval_group_ids": [Command.set([self.email_only_group.id])],
                            "domain": "[('active', '=', True)]",
                        }
                    ),
                ],
            }
        )
        self.meta_task.activity_type_ids = [Command.set([self.email_channel_action.id])]
        self.env["workflow.category.task.approval.group"].create(
            {
                "meta_id": self.meta_task.id,
                "approval_group_id": self.approval_group.id,
                "user_domain": "[('active', '=', True)]",
                "domain": "[(1, '=', 1)]",
                "note": "Matrix approval routing",
            }
        )
        self.directory_task = self.env["workflow.category.version.meta.task"].create(
            {
                "name": "HOD Approval",
                "node_id": "Activity_HOD_Approval",
                "node_type": "userTask",
                "sequence": 30,
                "version_id": self.version.id,
                "assignment_mode": "groups",
                "completion_mode": "any",
            }
        )
        self.directory_link = self.env["workflow.category.task.approval.group"].create(
            {
                "meta_id": self.directory_task.id,
                "approval_group_id": self.approval_group.id,
                "user_domain": "[(1, '=', 1)]",
                "domain": "[('create_uid', '!=', False)]",
                "note": "Approvers for the request creator's department",
            }
        )
        self.directory_owner_task = self.env["workflow.category.version.meta.task"].create(
            {
                "name": "Owner Approval",
                "node_id": "Activity_Owner_Approval",
                "node_type": "userTask",
                "sequence": 40,
                "version_id": self.version.id,
                "assignment_mode": "request_owner",
                "completion_mode": "any",
                "description": "The request owner approves this stage",
            }
        )
        self.directory_creator_owner_task = self.env[
            "workflow.category.version.meta.task"
        ].create(
            {
                "name": "Creator or Owner Approval",
                "node_id": "Activity_Creator_Owner_Approval",
                "node_type": "userTask",
                "sequence": 50,
                "version_id": self.version.id,
                "assignment_mode": "domain",
                "assignment_user_domain": (
                    "[('id', 'in', [request_owner_id, request_creator_id])]"
                ),
                "completion_mode": "any",
                "description": "Resolved from the creator and request owner",
            }
        )

    def test_directory_lists_group_pool_creator_rule_and_business_note(self):
        report = self.env["workflow.approval.directory.report"].sudo().search(
            [
                ("meta_task_id", "=", self.directory_task.id),
                ("source_type", "=", "approval_group"),
                ("approval_group_id", "=", self.approval_group.id),
            ],
            limit=1,
        )

        self.assertTrue(report)
        self.assertEqual(report.category_id, self.category)
        self.assertEqual(report.version_id, self.version)
        self.assertTrue(report.version_active)
        self.assertEqual(report.routing_reference, "request_creator")
        self.assertEqual(report.resolution_type, "conditional_pool")
        self.assertEqual(report.active_approver_count, 1)
        self.assertEqual(report.configured_user_ids, self.user)
        self.assertIn(self.employee.x_emp_code, report.approver_employee_codes)
        self.assertEqual(
            report.approver_employee_code_display,
            self.employee.x_emp_code,
        )
        self.assertIn("1 active configured user", report.approver_display)
        self.assertEqual(
            report.note,
            "Approvers for the request creator's department",
        )

    def test_directory_treats_engine_true_sentinels_as_unconditional(self):
        self.env["workflow.category.task.approval.group"].create(
            {
                "meta_id": self.directory_task.id,
                "approval_group_id": self.notification_only_group.id,
                "user_domain": "[(1, '=', 1)]",
                "domain": "[(1, '=', 1)]",
                "note": "Applies to every request",
            }
        )

        report = self.env["workflow.approval.directory.report"].sudo().search(
            [
                ("meta_task_id", "=", self.directory_task.id),
                ("source_type", "=", "approval_group"),
                ("approval_group_id", "=", self.notification_only_group.id),
            ],
            limit=1,
        )

        self.assertTrue(report)
        self.assertEqual(report.routing_reference, "all_requests")
        self.assertEqual(report.resolution_type, "fixed")

    def test_directory_labels_request_owner_as_resolved_per_request(self):
        report = self.env["workflow.approval.directory.report"].sudo().search(
            [
                ("meta_task_id", "=", self.directory_owner_task.id),
                ("source_type", "=", "request_owner"),
            ],
            limit=1,
        )

        self.assertTrue(report)
        self.assertTrue(report.is_dynamic)
        self.assertEqual(report.routing_reference, "request_owner")
        self.assertEqual(report.active_approver_count, 0)
        self.assertFalse(report.configured_user_ids)
        self.assertIn("resolved for each request", report.approver_display)

    def test_directory_labels_creator_and_owner_domain_without_fake_users(self):
        report = self.env["workflow.approval.directory.report"].sudo().search(
            [
                ("meta_task_id", "=", self.directory_creator_owner_task.id),
                ("source_type", "=", "assignment_domain"),
            ],
            limit=1,
        )

        self.assertTrue(report)
        self.assertTrue(report.is_dynamic)
        self.assertEqual(report.routing_reference, "creator_and_owner")
        self.assertEqual(report.resolution_type, "dynamic_request")
        self.assertEqual(report.active_approver_count, 0)
        self.assertFalse(report.configured_user_ids)
        self.assertFalse(report.approver_names)
        self.assertIn("resolved for each request", report.approver_display)

    def test_directory_excludes_send_tasks_from_approval_stages(self):
        report = self.env["workflow.approval.directory.report"].sudo().search(
            [("meta_task_id", "=", self.meta_task.id)]
        )

        self.assertFalse(report)

    def test_matrix_and_directory_support_grouping_by_note(self):
        matrix_groups = self.env["workflow.approval.user.matrix.report"].sudo()._read_group(
            [("note", "=", "Matrix approval routing")],
            groupby=["note"],
            aggregates=["__count"],
        )
        directory_groups = self.env["workflow.approval.directory.report"].sudo()._read_group(
            [("note", "=", "Approvers for the request creator's department")],
            groupby=["note"],
            aggregates=["__count"],
        )

        self.assertEqual(matrix_groups, [("Matrix approval routing", 1)])
        self.assertEqual(
            directory_groups,
            [("Approvers for the request creator's department", 1)],
        )

    def test_matrix_report_lists_members_approval_and_notification_usage(self):
        Report = self.env["workflow.approval.user.matrix.report"].sudo()

        membership = Report.search(
            [
                ("usage_type", "=", "group_member"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.approval_group.id),
            ],
            limit=1,
        )
        self.assertTrue(membership)
        self.assertEqual(membership.category_id, self.category)
        self.assertEqual(membership.employee_id, self.employee)
        self.assertEqual(membership.employee_code, self.employee.x_emp_code)
        self.assertEqual(membership.employee_department_id, self.department)
        self.assertEqual(membership.employee_position, self.job.name)
        self.assertEqual(membership.extension, self.employee.x_ext_phone)
        self.assertEqual(membership.request_model_name, "workflow.base.approval.request")
        if "x_team" in self.employee._fields:
            self.assertEqual(membership.employee_team, self.employee.x_team)
        if "x_line" in self.employee._fields:
            self.assertEqual(membership.employee_line, self.employee.x_line)

        notification_group_membership = Report.search(
            [
                ("usage_type", "=", "group_member"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.notification_only_group.id),
            ],
            limit=1,
        )
        self.assertTrue(notification_group_membership)
        self.assertEqual(notification_group_membership.category_id, self.category)
        self.assertEqual(notification_group_membership.request_model_name, "workflow.base.approval.request")

        email_group_membership = Report.search(
            [
                ("usage_type", "=", "group_member"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.email_only_group.id),
            ],
            limit=1,
        )
        self.assertTrue(email_group_membership)
        self.assertEqual(email_group_membership.category_id, self.category)
        self.assertEqual(email_group_membership.request_model_name, "workflow.base.approval.request")

        approval = Report.search(
            [
                ("usage_type", "=", "approval"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.approval_group.id),
                ("meta_task_id", "=", self.meta_task.id),
            ],
            limit=1,
        )
        self.assertTrue(approval)
        self.assertEqual(approval.category_id, self.category)
        self.assertEqual(approval.version_id, self.version)
        self.assertEqual(approval.request_model_name, "workflow.base.approval.request")
        self.assertEqual(approval.line_id, self.line)
        self.assertEqual(approval.team_id, self.team)
        self.assertEqual(approval.assignment_mode, "groups")
        self.assertEqual(approval.completion_mode, "any")
        self.assertEqual(approval.record_domain, "[(1, '=', 1)]")

        notification = Report.search(
            [
                ("usage_type", "=", "notification"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.approval_group.id),
                ("meta_task_id", "=", self.meta_task.id),
            ],
            limit=1,
        )
        self.assertTrue(notification)
        self.assertEqual(notification.notification_delivery_mode, "channels")
        self.assertEqual(notification.notification_recipient_source, "approval_group_users")

        channel_send_task = Report.search(
            [
                ("usage_type", "=", "channel_notification"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.approval_group.id),
                ("meta_task_id", "=", self.meta_task.id),
                ("notification_action_id", "=", self.email_channel_action.id),
                ("email_recipient_source", "=", "send_task"),
            ],
            limit=1,
        )
        self.assertTrue(channel_send_task)
        self.assertEqual(channel_send_task.notification_delivery_mode, "channels")
        self.assertEqual(channel_send_task.email_header, "to")
        self.assertEqual(channel_send_task.notification_recipient_source, "approval_group_users")

        channel_group_line = Report.search(
            [
                ("usage_type", "=", "channel_notification"),
                ("user_id", "=", self.user.id),
                ("approval_group_id", "=", self.approval_group.id),
                ("meta_task_id", "=", self.meta_task.id),
                ("notification_action_id", "=", self.email_channel_action.id),
                ("email_recipient_source", "=", "approval_group_users"),
            ],
            limit=1,
        )
        self.assertTrue(channel_group_line)
        self.assertEqual(channel_group_line.email_header, "cc")
        self.assertEqual(channel_group_line.notification_filter_domain, "[('active', '=', True)]")

    def test_matrix_report_search_view_uses_explicit_workflow_and_employee_group_bys(self):
        view = self.env.ref("workflow_engine.workflow_approval_user_matrix_report_view_search")
        list_view = self.env.ref("workflow_engine.workflow_approval_user_matrix_report_view_list")
        arch = view.arch_db

        self.assertIn('<field name="note"', list_view.arch_db)
        self.assertIn('string="Workflow Category"', arch)
        self.assertIn('string="Workflow Approval Group"', arch)
        self.assertIn('string="System Security Group"', arch)
        self.assertIn('string="Workflow Approval Department"', arch)
        self.assertIn('string="Workflow Approval Team"', arch)
        self.assertIn('string="Workflow Approval Line"', arch)
        self.assertIn('string="Employee Department"', arch)
        self.assertIn('string="Employee Team"', arch)
        self.assertIn('string="Employee Line"', arch)
        self.assertIn('string="Employee Position"', arch)
        self.assertIn('string="Email Recipient Source"', arch)
        self.assertIn('string="Workflow Node Type"', arch)
        self.assertIn('string="Note" name="group_by_note"', arch)
        self.assertIn(
            'string="Workflow Activity" name="group_by_activity" domain="[('
            "'meta_task_id', '!=', False)]\" context=\"{'group_by': 'meta_task_id'}",
            arch,
        )
        self.assertIn('string="Approval Activity Users"', arch)
        self.assertIn('string="Notification Group Users"', arch)
        self.assertIn('string="Workflow Approval Group Members"', arch)
        self.assertIn('string="Has Workflow Category"', arch)
        self.assertIn('string="Linked to Workflow Activity"', arch)
        self.assertNotIn("{'group_by': 'record_domain'}", arch)

    def test_directory_has_native_read_only_views_and_active_version_default(self):
        list_view = self.env.ref("workflow_engine.workflow_approval_directory_report_view_list")
        form_view = self.env.ref("workflow_engine.workflow_approval_directory_report_view_form")
        search_view = self.env.ref("workflow_engine.workflow_approval_directory_report_view_search")
        action = self.env.ref("workflow_engine.workflow_approval_directory_report_action")

        self.assertEqual(list_view.model, "workflow.approval.directory.report")
        self.assertIn('create="false"', list_view.arch_db)
        self.assertIn('<field name="note"', list_view.arch_db)
        self.assertIn('name="configured_user_ids"', list_view.arch_db)
        self.assertIn('widget="many2many_tags_avatar"', list_view.arch_db)
        self.assertIn('name="approver_employee_code_display"', list_view.arch_db)
        self.assertIn('name="approver_employee_codes" optional="hide"', list_view.arch_db)
        self.assertIn('<field name="is_dynamic" column_invisible="True"', list_view.arch_db)
        self.assertIn('string="Technical Evidence"', form_view.arch_db)
        self.assertIn('name="active_versions"', search_view.arch_db)
        self.assertIn('name="dynamic_sources"', search_view.arch_db)
        self.assertIn('<field name="approver_employee_codes"', search_view.arch_db)
        self.assertIn('string="Note"', search_view.arch_db)
        self.assertIn('name="group_by_note"', search_view.arch_db)
        self.assertIn("{'group_by': 'note'}", search_view.arch_db)
        self.assertIn("search_default_active_versions", action.context)

    def test_directory_shared_labels_match_approval_user_matrix(self):
        matrix_fields = self.env["workflow.approval.user.matrix.report"]._fields
        directory_fields = self.env["workflow.approval.directory.report"]._fields
        shared_fields = (
            "category_id",
            "version_id",
            "request_model_id",
            "company_id",
            "meta_task_id",
            "task_sequence",
            "node_id",
            "node_type",
            "assignment_mode",
            "completion_mode",
            "approval_group_id",
            "system_group_id",
            "group_department_id",
            "line_id",
            "team_id",
            "record_domain",
            "user_filter_domain",
            "note",
        )

        for field_name in shared_fields:
            self.assertEqual(
                directory_fields[field_name].string,
                matrix_fields[field_name].string,
                f"Inconsistent report label for {field_name}",
            )

    def test_matrix_report_uses_dedicated_group_with_technical_admin_default(self):
        technical_admin = self.env.ref("workflow_engine.group_workflow_technical_admin")
        report_group = self.env.ref("workflow_engine.group_workflow_approval_user_matrix_report")
        approval_user = self.env.ref("workflow_engine.group_workflow_approval_user")
        parent_menu = self.env.ref("workflow_engine.workflow_technical_reports_menu")
        menu = self.env.ref("workflow_engine.workflow_approval_user_matrix_report_menu")
        directory_menu = self.env.ref("workflow_engine.workflow_approval_directory_report_menu")
        action = self.env.ref("workflow_engine.workflow_approval_user_matrix_report_action")
        directory_action = self.env.ref("workflow_engine.workflow_approval_directory_report_action")
        access = self.env.ref("workflow_engine.access_workflow_approval_user_matrix_report_user")
        directory_access = self.env.ref(
            "workflow_engine.access_workflow_approval_directory_report_user"
        )

        self.assertIn(report_group, technical_admin.implied_ids)
        self.assertIn(approval_user, report_group.implied_ids)
        self.assertEqual(parent_menu.group_ids, report_group)
        self.assertEqual(menu.parent_id, parent_menu)
        self.assertEqual(menu.group_ids, report_group)
        self.assertEqual(directory_menu.parent_id, parent_menu)
        self.assertEqual(directory_menu.group_ids, report_group)
        self.assertEqual(action.group_ids, report_group)
        self.assertEqual(directory_action.group_ids, report_group)
        self.assertEqual(access.group_id, report_group)
        self.assertTrue(access.perm_read)
        self.assertFalse(access.perm_create)
        self.assertFalse(access.perm_write)
        self.assertFalse(access.perm_unlink)
        self.assertEqual(directory_access.group_id, report_group)
        self.assertTrue(directory_access.perm_read)
        self.assertFalse(directory_access.perm_create)
        self.assertFalse(directory_access.perm_write)
        self.assertFalse(directory_access.perm_unlink)
