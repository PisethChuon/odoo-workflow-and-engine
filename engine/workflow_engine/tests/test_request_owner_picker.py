# -*- coding: utf-8 -*-

from uuid import uuid4

from odoo.fields import Command
from odoo.tests import common


class TestRequestOwnerPicker(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        unique = uuid4().hex[:8]
        internal_group = cls.env.ref("base.group_user")
        cls.config_parameter = cls.env["ir.config_parameter"].sudo()
        cls.original_request_owner_email_domains = cls.config_parameter.get_param(
            "workflow_engine.request_owner_email_domains"
        )
        cls.config_parameter.set_param(
            "workflow_engine.request_owner_email_domains",
            "nagaworld.com,nagworld.com",
        )

        def _new_user(key, name, email_domain="nagaworld.com"):
            login = f"wf_owner_picker_{key}_{unique}"
            return cls.env["res.users"].with_context(no_reset_password=True).create(
                {
                    "name": name,
                    "login": login,
                    "email": f"{login}@{email_domain}",
                    "group_ids": [Command.set([internal_group.id])],
                    "company_id": cls.env.company.id,
                    "company_ids": [Command.set([cls.env.company.id])],
                }
            )

        cls.employee_user = _new_user("employee", f"Owner User {unique}")
        cls.partner_user = _new_user("partner", f"Fallback User {unique}")
        cls.external_user = _new_user("external", f"External User {unique}", email_domain="example.com")
        cls.hidden_user = _new_user("hidden", f"Hidden User {unique}")
        cls.hidden_user.write({"wf_hide_from_workflow_picker": True})

        cls.department = cls.env["hr.department"].sudo().create(
            {"name": f"Group IT {unique}", "company_id": cls.env.company.id}
        )
        cls.job = cls.env["hr.job"].sudo().create({"name": f"Software Manager {unique}"})
        cls.employee = cls.env["hr.employee"].sudo().create(
            {
                "name": f"SOK PUTHIPHORN {unique}",
                "user_id": cls.employee_user.id,
                "company_id": cls.env.company.id,
                "department_id": cls.department.id,
                "job_id": cls.job.id,
                "job_title": "Manager - Software Developments",
                "x_emp_code": f"024703{unique}",
                "x_ext_phone": "7906",
                "mobile_phone": "+85592862627",
                "work_phone": "7906",
                "work_email": f"sok_{unique}@nagaworld.com",
            }
        )
        cls.hidden_employee = cls.env["hr.employee"].sudo().create(
            {
                "name": f"HIDDEN PICKER USER {unique}",
                "user_id": cls.hidden_user.id,
                "company_id": cls.env.company.id,
                "department_id": cls.department.id,
                "job_id": cls.job.id,
                "job_title": "Workflow Service Account",
                "x_emp_code": f"HIDE{unique}",
                "x_ext_phone": "0000",
                "mobile_phone": "+85500000000",
                "work_phone": "0000",
                "work_email": f"hidden_{unique}@nagaworld.com",
            }
        )

        cls.partner_user.partner_id.write(
            {
                "name": f"Partner Only Owner {unique}",
                "email": f"partner_owner_{unique}@nagaworld.com",
                "phone": "0235550101",
                "function": "External Request Owner",
            }
        )
        cls.external_user.partner_id.write(
            {
                "name": f"External Owner {unique}",
                "email": f"external_owner_{unique}@example.com",
                "phone": "0235550102",
                "function": "External Request Owner",
            }
        )

    @classmethod
    def tearDownClass(cls):
        if cls.original_request_owner_email_domains is None:
            cls.config_parameter.search(
                [("key", "=", "workflow_engine.request_owner_email_domains")]
            ).unlink()
        else:
            cls.config_parameter.set_param(
                "workflow_engine.request_owner_email_domains",
                cls.original_request_owner_email_domains,
            )
        super().tearDownClass()

    def test_request_owner_context_searches_employee_code(self):
        result = self.env["res.users"].with_context(workflow_request_owner_picker=True).name_search(
            self.employee.x_emp_code,
            limit=20,
        )

        self.assertIn(self.employee_user.id, [user_id for user_id, _name in result])

    def test_request_owner_context_searches_employee_name(self):
        result = self.env["res.users"].with_context(workflow_request_owner_picker=True).name_search(
            self.employee.name,
            limit=20,
        )

        self.assertIn(self.employee_user.id, [user_id for user_id, _name in result])

    def test_delegate_picker_context_searches_employee_code(self):
        result = self.env["res.users"].with_context(workflow_delegate_picker=True).name_search(
            self.employee.x_emp_code,
            limit=20,
        )

        self.assertIn(self.employee_user.id, [user_id for user_id, _name in result])

    def test_request_owner_picker_hides_hidden_users(self):
        result = self.env["res.users"].with_context(workflow_request_owner_picker=True).name_search(
            self.hidden_employee.x_emp_code,
            limit=20,
        )

        self.assertNotIn(self.hidden_user.id, [user_id for user_id, _name in result])

    def test_delegate_picker_hides_hidden_users(self):
        result = self.env["res.users"].with_context(workflow_delegate_picker=True).name_search(
            self.hidden_employee.x_emp_code,
            limit=20,
        )

        self.assertNotIn(self.hidden_user.id, [user_id for user_id, _name in result])

    def test_regular_name_search_does_not_search_employee_name(self):
        result = self.env["res.users"].name_search(self.employee.name, limit=20)

        self.assertNotIn(self.employee_user.id, [user_id for user_id, _name in result])

    def test_user_without_employee_uses_partner_fallback_values(self):
        self.assertFalse(self.partner_user.employee_id)
        self.assertEqual(
            self.partner_user.wf_request_owner_employee_name,
            self.partner_user.partner_id.name,
        )
        self.assertEqual(self.partner_user.wf_request_owner_email, self.partner_user.email)
        self.assertEqual(self.partner_user.wf_request_owner_phone, self.partner_user.partner_id.phone)
        self.assertEqual(
            self.partner_user.wf_request_owner_job_position,
            self.partner_user.partner_id.function,
        )

    def test_user_without_allowed_work_email_gets_blank_request_owner_email(self):
        self.assertFalse(self.external_user.employee_id)
        self.assertEqual(self.external_user.wf_request_owner_email, "")

    def test_request_owner_email_uses_first_matching_configured_domain_candidate(self):
        self.employee.write({"work_email": f"employee_{uuid4().hex[:6]}@example.com"})
        self.employee_user.write({"email": f"user_{uuid4().hex[:6]}@nagaworld.com"})
        self.employee_user.invalidate_recordset(["wf_request_owner_email"])

        self.assertEqual(self.employee_user.wf_request_owner_email, self.employee_user.email)

    def test_grouping_fields_track_request_owner_employee_data(self):
        self.employee_user.invalidate_recordset(
            [
                "wf_request_owner_has_employee",
                "wf_request_owner_employee_profile",
                "wf_request_owner_department_id",
                "wf_request_owner_job_id",
            ]
        )
        self.partner_user.invalidate_recordset(
            ["wf_request_owner_has_employee", "wf_request_owner_employee_profile"]
        )

        self.assertTrue(self.employee_user.wf_request_owner_has_employee)
        self.assertEqual(self.employee_user.wf_request_owner_employee_profile, "employee")
        self.assertEqual(self.employee_user.wf_request_owner_department_id, self.department)
        self.assertEqual(self.employee_user.wf_request_owner_job_id, self.job)
        self.assertFalse(self.partner_user.wf_request_owner_has_employee)
        self.assertEqual(self.partner_user.wf_request_owner_employee_profile, "non_employee")

    def test_request_owner_search_view_exposes_default_filters_and_groups(self):
        arch = self.env.ref("workflow_engine.view_res_users_request_owner_picker_search").arch_db

        self.assertIn('name="request_owner_employee"', arch)
        self.assertIn('name="request_owner_non_employee"', arch)
        self.assertIn("wf_request_owner_department_id", arch)
        self.assertIn("wf_request_owner_job_id", arch)
        self.assertIn("wf_request_owner_employee_profile", arch)
        self.assertIn('name="request_owner_group_employee"', arch)
        self.assertNotIn('name="request_owner_internal"', arch)
        self.assertNotIn('name="request_owner_external"', arch)
        self.assertNotIn('name="request_owner_has_emp_code"', arch)
        self.assertNotIn('name="request_owner_has_email"', arch)
        self.assertNotIn('name="request_owner_archived"', arch)
        self.assertNotIn("request_owner_group_company", arch)
        self.assertNotIn("request_owner_group_user_type", arch)
        self.assertNotIn("request_owner_group_status", arch)

    def test_request_owner_kanban_view_exposes_picker_columns(self):
        arch = self.env.ref("workflow_engine.view_res_users_request_owner_picker_kanban").arch_db

        self.assertIn("wf_request_owner_emp_code", arch)
        self.assertIn("wf_request_owner_employee_name", arch)
        self.assertIn("wf_request_owner_department", arch)
        self.assertIn("wf_request_owner_position", arch)
        self.assertIn("wf_request_owner_extension", arch)
        self.assertIn("wf_request_owner_email", arch)
        self.assertNotIn("wf_request_owner_work_mobile", arch)
        self.assertNotIn("wf_request_owner_phone", arch)
        self.assertNotIn("wf_request_owner_job_position", arch)

    def test_web_name_search_returns_picker_columns(self):
        records = self.env["res.users"].with_context(workflow_request_owner_picker=True).web_name_search(
            self.employee.x_emp_code,
            specification={
                "display_name": {},
                "wf_request_owner_emp_code": {},
                "wf_request_owner_employee_name": {},
                "wf_request_owner_department": {},
                "wf_request_owner_position": {},
                "wf_request_owner_extension": {},
                "wf_request_owner_work_mobile": {},
                "wf_request_owner_phone": {},
                "wf_request_owner_email": {},
                "wf_request_owner_job_position": {},
            },
            limit=20,
        )
        row = next(record for record in records if record["id"] == self.employee_user.id)

        self.assertEqual(row["wf_request_owner_emp_code"], self.employee.x_emp_code)
        self.assertEqual(row["wf_request_owner_employee_name"], self.employee.name)
        self.assertEqual(row["wf_request_owner_department"], self.department.display_name)
        self.assertEqual(row["wf_request_owner_position"], self.job.display_name)
        self.assertEqual(row["wf_request_owner_extension"], "7906")
        self.assertEqual(row["wf_request_owner_work_mobile"], "+85592862627")
        self.assertEqual(row["wf_request_owner_email"], self.employee.work_email)

    def test_web_name_search_exposes_work_email_to_basic_internal_user(self):
        records = self.env["res.users"].with_user(
            self.partner_user
        ).with_context(workflow_request_owner_picker=True).web_name_search(
            self.employee.x_emp_code,
            specification={
                "display_name": {},
                "wf_request_owner_email": {},
            },
            limit=20,
        )
        row = next(record for record in records if record["id"] == self.employee_user.id)

        self.assertEqual(row["wf_request_owner_email"], self.employee.work_email)

    def test_web_name_search_hides_hidden_users(self):
        records = self.env["res.users"].with_context(workflow_request_owner_picker=True).web_name_search(
            self.hidden_employee.x_emp_code,
            specification={
                "display_name": {},
                "wf_request_owner_emp_code": {},
                "wf_request_owner_employee_name": {},
            },
            limit=20,
        )

        self.assertNotIn(self.hidden_user.id, [record["id"] for record in records])

    def test_web_search_read_hides_hidden_users_for_picker_modal(self):
        result = self.env["res.users"].with_context(workflow_request_owner_picker=True).web_search_read(
            [("id", "in", [self.employee_user.id, self.hidden_user.id])],
            specification={
                "display_name": {},
                "wf_request_owner_emp_code": {},
                "wf_request_owner_employee_name": {},
            },
            limit=20,
            order="id asc",
        )

        self.assertIn(self.employee_user.id, [record["id"] for record in result["records"]])
        self.assertNotIn(self.hidden_user.id, [record["id"] for record in result["records"]])

    def test_web_read_group_hides_hidden_users_for_picker_modal(self):
        result = self.env["res.users"].with_context(workflow_request_owner_picker=True).web_read_group(
            [("id", "in", [self.employee_user.id, self.hidden_user.id])],
            ["wf_request_owner_employee_profile"],
            ["__count"],
        )

        employee_group = next(
            group
            for group in result["groups"]
            if group["wf_request_owner_employee_profile"] == "employee"
        )
        self.assertEqual(employee_group["__count"], 1)

    def test_delegate_picker_list_view_exposes_request_owner_columns(self):
        arch = self.env.ref("workflow_engine.view_res_users_workflow_delegate_picker_list").arch_db

        self.assertIn("wf_request_owner_emp_code", arch)
        self.assertIn("wf_request_owner_employee_name", arch)
        self.assertIn("wf_request_owner_department", arch)
        self.assertIn("wf_request_owner_position", arch)
        self.assertIn("wf_request_owner_extension", arch)
        self.assertIn("wf_request_owner_email", arch)
        self.assertNotIn("wf_request_owner_work_mobile", arch)
        self.assertNotIn("wf_request_owner_phone", arch)
        self.assertNotIn("wf_request_owner_job_position", arch)

    def test_delegate_picker_search_view_exposes_default_filters_and_groups(self):
        arch = self.env.ref("workflow_engine.view_res_users_workflow_delegate_picker_search").arch_db

        self.assertIn('name="approver_employee"', arch)
        self.assertIn('name="approver_non_employee"', arch)
        self.assertIn("wf_request_owner_department_id", arch)
        self.assertIn("wf_request_owner_job_id", arch)
        self.assertIn("wf_request_owner_employee_profile", arch)
        self.assertIn('name="approver_group_employee"', arch)
        self.assertNotIn('name="approver_internal"', arch)
        self.assertNotIn('name="approver_external"', arch)
        self.assertNotIn('name="approver_has_emp_code"', arch)
        self.assertNotIn('name="approver_has_email"', arch)
        self.assertNotIn('name="approver_archived"', arch)
        self.assertNotIn("approver_group_company", arch)
        self.assertNotIn("approver_group_user_type", arch)
        self.assertNotIn("approver_group_status", arch)

    def test_delegate_picker_kanban_view_exposes_picker_columns(self):
        arch = self.env.ref("workflow_engine.view_res_users_workflow_delegate_picker_kanban").arch_db

        self.assertIn("wf_request_owner_emp_code", arch)
        self.assertIn("wf_request_owner_employee_name", arch)
        self.assertIn("wf_request_owner_department", arch)
        self.assertIn("wf_request_owner_position", arch)
        self.assertIn("wf_request_owner_extension", arch)
        self.assertIn("wf_request_owner_email", arch)
        self.assertNotIn("wf_request_owner_work_mobile", arch)
        self.assertNotIn("wf_request_owner_phone", arch)
        self.assertNotIn("wf_request_owner_job_position", arch)

    def test_delegate_wizard_uses_delegate_picker_widget(self):
        arch = self.env.ref("workflow_engine.view_form_delegate_wizard").arch_db

        self.assertIn('widget="many2one_workflow_delegate_user"', arch)
        self.assertIn('widget="many2many_workflow_delegate_user"', arch)
        self.assertIn('name="selected_user_ids"', arch)
        self.assertEqual(
            self.env["delegate_wizard"]._fields["selected_user_ids"].type,
            "many2many",
        )
        self.assertIn('name="comment"', arch)
        self.assertIn('required="1"', arch)
