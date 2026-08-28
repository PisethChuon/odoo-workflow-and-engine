# -*- coding: utf-8 -*-

import base64
import io
from pathlib import Path
from uuid import uuid4

import openpyxl
from lxml import etree

from odoo.modules.module import get_module_path
from odoo.tests import common


class TestWorkflowRequestorImport(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        unique = uuid4().hex[:8]
        cls.department = cls.env["hr.department"].sudo().create(
            {"name": f"Group IT Import {unique}", "company_id": cls.env.company.id}
        )
        cls.job = cls.env["hr.job"].sudo().create({"name": f"Import Manager {unique}"})
        cls.employee = cls.env["hr.employee"].sudo().create(
            {
                "name": f"Database Employee {unique}",
                "company_id": cls.env.company.id,
                "department_id": cls.department.id,
                "job_id": cls.job.id,
                "job_title": f"Fallback Position {unique}",
                "x_emp_code": f"IMP{unique}",
            }
        )
        cls.requestor_user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .sudo()
            .create(
                {
                    "name": f"Requestor User {unique}",
                    "login": f"requestor-import-{unique}@example.com",
                    "email": f"requestor-import-{unique}@example.com",
                }
            )
        )
        cls.employee.user_id = cls.requestor_user.id

    def _xlsx_binary(self, rows):
        return self._xlsx_binary_with_headers(["EMP.NO", "EMP.NAME", "POSITION", "DEPT.NAME"], rows)

    def _xlsx_binary_with_headers(self, headers, rows):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        stream = io.BytesIO()
        workbook.save(stream)
        return base64.b64encode(stream.getvalue())

    def _read_workflow_engine_file(self, *path_parts):
        path = Path(get_module_path("workflow_engine")).joinpath(*path_parts)
        with open(path, encoding="utf-8") as source:
            return source.read()

    def test_excel_import_prefers_database_employee_values(self):
        unknown_code = f"UNKNOWN{uuid4().hex[:6]}"
        wizard = self.env["workflow.requestor.import.wizard"].create(
            {
                "excel_file": self._xlsx_binary(
                    [
                        [
                            self.employee.x_emp_code,
                            "Wrong Excel Name",
                            "Wrong Excel Position",
                            "Wrong Excel Department",
                        ],
                        [
                            unknown_code,
                            "Excel Only Employee",
                            "Excel Only Position",
                            "Excel Only Department",
                        ],
                    ]
                )
            }
        )

        action = wizard.action_import_file()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(len(wizard.line_ids), 2)

        db_line = wizard.line_ids[0]
        self.assertEqual(db_line.x_employee_code, self.employee.x_emp_code)
        self.assertEqual(db_line.x_employee_name, self.employee.name)
        self.assertEqual(db_line.x_department_name, self.department.display_name)
        self.assertEqual(db_line.x_position_name, self.job.display_name)
        self.assertEqual(db_line.x_request_user_id, self.requestor_user)
        self.assertEqual(
            db_line.x_request_user_avatar_url,
            f"/web/image/res.users/{self.requestor_user.id}/avatar_128",
        )

        excel_line = wizard.line_ids[1]
        self.assertEqual(excel_line.x_employee_code, unknown_code)
        self.assertEqual(excel_line.x_employee_name, "Excel Only Employee")
        self.assertEqual(excel_line.x_department_name, "Excel Only Department")
        self.assertEqual(excel_line.x_position_name, "Excel Only Position")
        self.assertFalse(excel_line.x_request_user_id)
        self.assertFalse(
            self.env["hr.employee"].sudo().search([("x_emp_code", "=", unknown_code)], limit=1)
        )

    def test_excel_upload_onchange_auto_loads_preview(self):
        wizard = self.env["workflow.requestor.import.wizard"].new(
            {
                "excel_file": self._xlsx_binary(
                    [
                        [
                            self.employee.x_emp_code,
                            "Wrong Excel Name",
                            "Wrong Excel Position",
                            "Wrong Excel Department",
                        ]
                    ]
                )
            }
        )

        wizard._onchange_excel_file()

        self.assertEqual(len(wizard.line_ids), 1)
        line = wizard.line_ids[0]
        self.assertEqual(line.x_employee_code, self.employee.x_emp_code)
        self.assertEqual(line.x_employee_name, self.employee.name)
        self.assertEqual(line.x_department_name, self.department.display_name)
        self.assertEqual(line.x_position_name, self.job.display_name)
        self.assertEqual(line.x_request_user_id, self.requestor_user)

    def test_excel_upload_invalid_file_returns_friendly_warning(self):
        wizard = self.env["workflow.requestor.import.wizard"].new(
            {
                "excel_file": base64.b64encode(b"not an excel workbook"),
                "excel_filename": "wrong.xlsx",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "x_employee_code": "EXISTING",
                            "x_employee_name": "Existing Requestor",
                        },
                    )
                ],
            }
        )

        result = wizard._onchange_excel_file()

        self.assertEqual(result["warning"]["title"], "Invalid Excel File")
        self.assertIn("Please choose a valid Excel .xlsx file", result["warning"]["message"])
        self.assertFalse(wizard.excel_file)
        self.assertFalse(wizard.excel_filename)
        self.assertEqual(wizard.line_ids.mapped("x_employee_code"), ["EXISTING"])

    def test_excel_upload_wrong_template_returns_friendly_warning(self):
        wizard = self.env["workflow.requestor.import.wizard"].new(
            {
                "excel_file": self._xlsx_binary_with_headers(
                    ["EMPLOYEE", "NAME"],
                    [["024703", "Wrong Template"]],
                ),
                "excel_filename": "wrong_template.xlsx",
            }
        )

        result = wizard._onchange_excel_file()

        self.assertEqual(result["warning"]["title"], "Invalid Excel File")
        self.assertIn("Please choose the requestor Excel template", result["warning"]["message"])
        self.assertIn("EMP.NO", result["warning"]["message"])
        self.assertFalse(wizard.excel_file)
        self.assertFalse(wizard.excel_filename)
        self.assertFalse(wizard.line_ids)

    def test_excel_upload_appends_preview_and_skips_duplicate_employee_codes(self):
        unknown_code = f"APPEND{uuid4().hex[:6]}"
        wizard = self.env["workflow.requestor.import.wizard"].new(
            {
                "excel_file": self._xlsx_binary(
                    [
                        [
                            self.employee.x_emp_code,
                            "Duplicate Excel Name",
                            "Duplicate Excel Position",
                            "Duplicate Excel Department",
                        ],
                        [
                            unknown_code,
                            "Excel Added Employee",
                            "Excel Added Position",
                            "Excel Added Department",
                        ],
                    ]
                ),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "x_employee_code": self.employee.x_emp_code,
                            "x_employee_name": self.employee.name,
                            "x_department_name": self.department.display_name,
                            "x_position_name": self.job.display_name,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "x_employee_code": "MANUAL",
                            "x_employee_name": "Manual Requestor",
                        },
                    ),
                ],
            }
        )

        wizard._onchange_excel_file()

        employee_codes = wizard.line_ids.mapped("x_employee_code")
        self.assertEqual(employee_codes.count(self.employee.x_emp_code), 1)
        self.assertIn("MANUAL", employee_codes)
        self.assertIn(unknown_code, employee_codes)
        self.assertEqual(len(wizard.line_ids), 3)

    def test_action_import_file_appends_preview_and_skips_duplicate_employee_codes(self):
        unknown_code = f"FALLBACK{uuid4().hex[:6]}"
        wizard = self.env["workflow.requestor.import.wizard"].create(
            {
                "excel_file": self._xlsx_binary(
                    [
                        [
                            self.employee.x_emp_code,
                            "Duplicate Excel Name",
                            "Duplicate Excel Position",
                            "Duplicate Excel Department",
                        ],
                        [
                            unknown_code,
                            "Fallback Excel Employee",
                            "Fallback Excel Position",
                            "Fallback Excel Department",
                        ],
                    ]
                ),
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "x_employee_code": self.employee.x_emp_code,
                            "x_employee_name": self.employee.name,
                        },
                    )
                ],
            }
        )

        wizard.action_import_file()

        employee_codes = wizard.line_ids.mapped("x_employee_code")
        self.assertEqual(employee_codes.count(self.employee.x_emp_code), 1)
        self.assertIn(unknown_code, employee_codes)
        self.assertEqual(len(wizard.line_ids), 2)

    def test_confirm_import_returns_preview_text_without_relations(self):
        wizard = self.env["workflow.requestor.import.wizard"].create(
            {
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "x_employee_code": "024703",
                            "x_employee_name": "Sok Puthiphorn",
                            "x_department_name": "Group IT",
                            "x_position_name": "Manager",
                        },
                    )
                ]
            }
        )

        action = wizard.action_confirm_import()
        lines = action["infos"]["requestor_import_lines"]
        self.assertEqual(action["type"], "ir.actions.act_window_close")
        self.assertTrue(action["infos"]["noReload"])
        self.assertEqual(lines[0]["x_employee_code"], "024703")
        self.assertEqual(lines[0]["x_employee_name"], "Sok Puthiphorn")
        self.assertNotIn("x_employee_id", lines[0])

    def test_selecting_requestor_adds_preview_row_and_clears_picker(self):
        wizard = self.env["workflow.requestor.import.wizard"].new(
            {
                "request_user_id": self.requestor_user.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "x_employee_code": "EXISTING",
                            "x_employee_name": "Existing Requestor",
                        },
                    )
                ],
            }
        )

        wizard._onchange_request_user_id()

        self.assertFalse(wizard.request_user_id)
        self.assertEqual(len(wizard.line_ids), 2)
        added_line = wizard.line_ids[-1]
        self.assertEqual(added_line.x_employee_code, self.employee.x_emp_code)
        self.assertEqual(added_line.x_employee_name, self.employee.name)
        self.assertEqual(added_line.x_department_name, self.department.display_name)
        self.assertEqual(added_line.x_position_name, self.job.display_name)

    def test_requestor_import_view_uses_specific_excel_widget(self):
        arch = self.env["workflow.requestor.import.wizard"].get_view(view_type="form")["arch"]

        self.assertIn('name="excel_file"', arch)
        self.assertIn('widget="requestor_excel_import"', arch)
        self.assertIn("'hide_on_mobile': True", arch)
        self.assertNotIn('name="x_file"', arch)

    def test_requestor_import_preview_text_fields_are_readonly(self):
        arch = self.env["workflow.requestor.import.wizard"].get_view(view_type="form")["arch"]
        root = etree.fromstring(arch.encode())
        kanban = root.xpath("//field[@name='line_ids']/kanban")[0]
        self.assertTrue(kanban.xpath(".//field[@name='x_request_user_avatar_url']"))
        self.assertFalse(kanban.xpath(".//field[@name='x_request_user_id']"))
        avatar_node = kanban.xpath(".//img[@t-att-src='record.x_request_user_avatar_url.raw_value']")[0]
        self.assertEqual(avatar_node.get("alt"), "Requestor")
        self.assertFalse(kanban.xpath(".//img[contains(@t-att-src, 'kanban_image')]"))
        self.assertFalse(kanban.xpath(".//field[@name='x_request_user_id'][@widget='many2one_avatar_user']"))
        self.assertFalse(kanban.xpath(".//field[@name='avatar_1024']"))

        for field_name in (
            "x_employee_code",
            "x_employee_name",
            "x_department_name",
            "x_position_name",
        ):
            field_node = root.xpath(f"//field[@name='{field_name}']")[0]
            self.assertEqual(field_node.get("readonly"), "1")
            self.assertEqual(field_node.get("force_save"), "1")

        preview_list = root.xpath("//field[@name='line_ids']/list")[0]
        self.assertEqual(preview_list.get("create"), "false")
        self.assertEqual(preview_list.get("edit"), "false")
        self.assertEqual(preview_list.get("delete"), "true")
        self.assertEqual(preview_list.get("no_open"), "True")
        self.assertFalse(root.xpath("//field[@name='line_ids']/list/field[@name='x_request_user_id']"))

        request_user_node = root.xpath("//field[@name='request_user_id']")[0]
        self.assertEqual(request_user_node.get("widget"), "many2one_request_owner")

    def test_requestor_import_preview_has_mobile_kanban(self):
        arch = self.env["workflow.requestor.import.wizard"].get_view(view_type="form")["arch"]
        root = etree.fromstring(arch.encode())

        preview_field = root.xpath("//field[@name='line_ids']")[0]
        self.assertEqual(preview_field.get("mode"), "list,kanban")

        preview_kanban = root.xpath("//field[@name='line_ids']/kanban")[0]
        self.assertIn("o_kanban_mobile", preview_kanban.get("class", ""))
        self.assertEqual(preview_kanban.get("create"), "false")
        preview_card = root.xpath("//field[@name='line_ids']/kanban/templates/t[@t-name='card']")[0]
        self.assertIn("flex-row", preview_card.get("class", ""))
        self.assertTrue(
            root.xpath(
                "//field[@name='line_ids']/kanban/templates/t/aside"
                "[contains(concat(' ', normalize-space(@class), ' '), ' o_kanban_aside_full ')]"
            )
        )
        for field_name in (
            "x_employee_code",
            "x_employee_name",
            "x_department_name",
            "x_position_name",
            "x_request_user_avatar_url",
        ):
            self.assertTrue(root.xpath(f"//field[@name='line_ids']/kanban/field[@name='{field_name}']"))
        self.assertFalse(root.xpath("//field[@name='line_ids']/kanban/field[@name='x_request_user_id']"))

    def test_requestor_import_widget_requests_runtime_field_refresh(self):
        source = self._read_workflow_engine_file(
            "static",
            "src",
            "web",
            "import_button",
            "requestor_import_o2m.js",
        )

        self.assertIn("WF-RUNTIME-FIELD-STATE:REFRESH", source)
        self.assertIn('phase: "before"', source)
        self.assertIn('phase: "after"', source)
        self.assertIn("suppressMs", source)
        self.assertIn("skipActorSnapshot: true", source)
        self.assertIn("fieldName: this.props.name", source)

    def test_form_runtime_patch_handles_external_runtime_refresh(self):
        source = self._read_workflow_engine_file(
            "static",
            "src",
            "web",
            "patches",
            "wf_form_runtime_field_state.js",
        )

        self.assertIn('useBus(this.env.bus, "WF-RUNTIME-FIELD-STATE:REFRESH"', source)
        self.assertIn("_wfHandleRuntimeRefreshRequest", source)
        self.assertIn("suppressRecordChangedUntil", source)
        self.assertIn("force: detail.force !== false", source)
        self.assertIn("skipActorSnapshot: Boolean(detail.skipActorSnapshot)", source)
        self.assertIn("record.__wfActorUiSnapshotLoaded !== true && !record.isInEdition", source)
        self.assertIn("preserve an already editable form from flickering readonly", source)
        self.assertIn("lastReentryAt", source)
