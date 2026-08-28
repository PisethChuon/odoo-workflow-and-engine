import base64
import io
import logging

import openpyxl

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WorkflowRequestorImportWizard(models.TransientModel):
    _name = "workflow.requestor.import.wizard"
    _description = "Requestor Import Wizard"

    request_user_id = fields.Many2one(
        "res.users",
        string="Request For",
        domain="[('active', '=', True), ('share', '=', False), ('wf_hide_from_workflow_picker', '=', False)]",
    )
    excel_file = fields.Binary(string="Excel File")
    excel_filename = fields.Char(string="File Name")
    line_ids = fields.One2many(
        "workflow.requestor.import.line",
        "wizard_id",
        string="Preview",
    )

    @api.onchange("request_user_id")
    def _onchange_request_user_id(self):
        for wizard in self:
            if not wizard.request_user_id:
                continue
            values = wizard._employee_values_from_user(wizard.request_user_id)
            commands = wizard._unique_create_commands_by_employee_code(
                [fields.Command.create(values)]
            )
            update_values = {"request_user_id": False}
            if commands:
                update_values["line_ids"] = commands
            wizard.update(update_values)

    @api.onchange("excel_file")
    def _onchange_excel_file(self):
        for wizard in self:
            if not wizard.excel_file:
                continue
            try:
                commands = wizard._line_commands_from_excel()
            except UserError as error:
                return wizard._reset_excel_upload_with_warning(wizard._friendly_user_error_message(error))
            if not commands:
                return wizard._reset_excel_upload_with_warning(wizard._no_excel_rows_message())
            commands = wizard._unique_create_commands_by_employee_code(commands)
            if not commands:
                return wizard._reset_excel_upload_with_warning(wizard._duplicate_excel_rows_message())
            wizard.line_ids = commands

    def _friendly_user_error_message(self, error):
        message = error.args[0] if error.args else ""
        return str(message or self._invalid_excel_file_message())

    def _reset_excel_upload_with_warning(self, message):
        self.excel_file = False
        self.excel_filename = False
        return {
            "warning": {
                "title": _("Invalid Excel File"),
                "message": message,
                "type": "notification",
            }
        }

    def _invalid_excel_file_message(self):
        return _("Please choose a valid Excel .xlsx file using the provided template.")

    def _missing_headers_message(self, missing):
        return _(
            "Please choose the requestor Excel template. Required columns: %(columns)s."
        ) % {"columns": ", ".join(self._excel_headers())}

    def _no_excel_rows_message(self):
        return _("The Excel file has no requestor rows. Please add requestors and try again.")

    def _duplicate_excel_rows_message(self):
        return _("All requestors in this Excel file are already in the preview.")

    def _excel_headers(self):
        return ["EMP.NO", "EMP.NAME", "POSITION", "DEPT.NAME"]

    def _cell_to_text(self, value):
        if value in (False, None):
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value)).strip()
        return str(value).strip()

    def _normalize_header(self, value):
        return self._cell_to_text(value).upper()

    def _employee_code_key(self, employee_code):
        return (employee_code or "").strip().upper()

    def _request_user_avatar_url(self, user_id):
        return f"/web/image/res.users/{user_id}/avatar_128" if user_id else ""

    def _existing_employee_code_keys(self):
        self.ensure_one()
        return {
            self._employee_code_key(line.x_employee_code)
            for line in self.line_ids
            if self._employee_code_key(line.x_employee_code)
        }

    def _create_command_values(self, command):
        if isinstance(command, (tuple, list)) and len(command) >= 3 and command[0] == 0:
            return command[2] or {}
        return {}

    def _unique_create_commands_by_employee_code(self, commands):
        self.ensure_one()
        seen_codes = self._existing_employee_code_keys()
        unique_commands = []
        for command in commands:
            values = self._create_command_values(command)
            employee_code = self._employee_code_key(values.get("x_employee_code"))
            if employee_code and employee_code in seen_codes:
                continue
            if employee_code:
                seen_codes.add(employee_code)
            unique_commands.append(command)
        return unique_commands

    def _employee_values_from_record(self, employee):
        employee = employee.sudo()
        user = getattr(employee, "user_id", False)
        return {
            "x_request_user_id": user.id if user else False,
            "x_employee_code": getattr(employee, "x_emp_code", "") or "",
            "x_employee_name": employee.name or "",
            "x_department_name": employee.department_id.display_name or "",
            "x_position_name": employee.job_id.display_name or getattr(employee, "job_title", "") or "",
        }

    def _employee_values_from_user(self, user):
        employee = user.employee_id.sudo() if getattr(user, "employee_id", False) else self.env["hr.employee"]
        if employee:
            return self._employee_values_from_record(employee)
        return {
            "x_request_user_id": user.id,
            "x_employee_code": getattr(user, "emp_code", "") or user.login or "",
            "x_employee_name": user.name or "",
            "x_department_name": "",
            "x_position_name": "",
        }

    def _employee_values_from_excel(self, row_values):
        return {
            "x_employee_code": row_values.get("EMP.NO", ""),
            "x_employee_name": row_values.get("EMP.NAME", ""),
            "x_department_name": row_values.get("DEPT.NAME", ""),
            "x_position_name": row_values.get("POSITION", ""),
        }

    def _employee_by_code(self, codes):
        clean_codes = [code for code in codes if code]
        if not clean_codes:
            return {}

        employees_by_code = {}
        for model_name in ("hr.employee.public", "hr.employee"):
            Employee = self.env[model_name].sudo()
            if "x_emp_code" not in Employee._fields:
                continue
            missing_codes = [
                code.strip().upper()
                for code in clean_codes
                if code.strip().upper() not in employees_by_code
            ]
            if not missing_codes:
                break
            domain = []
            for code in missing_codes:
                domain = ["|", ("x_emp_code", "=ilike", code), *domain] if domain else [("x_emp_code", "=ilike", code)]
            employees = Employee.search(domain)
            employees_by_code.update(
                {
                    (employee.x_emp_code or "").strip().upper(): employee
                    for employee in employees
                    if employee.x_emp_code
                }
            )
        return employees_by_code

    def _line_commands_from_excel(self):
        self.ensure_one()
        if not self.excel_file:
            raise UserError(_("Please upload an Excel file."))

        try:
            workbook = openpyxl.load_workbook(
                io.BytesIO(base64.b64decode(self.excel_file)),
                data_only=True,
            )
        except Exception as error:
            _logger.debug("Requestor import could not read Excel file", exc_info=True)
            raise UserError(self._invalid_excel_file_message()) from error

        sheet = workbook.active
        headers = [self._normalize_header(cell.value) for cell in sheet[1]]
        required_headers = self._excel_headers()
        missing = [header for header in required_headers if header not in headers]
        if missing:
            raise UserError(self._missing_headers_message(missing))

        rows = []
        for row_no, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            row_values = {}
            for index, value in enumerate(row):
                if index >= len(headers):
                    continue
                header = headers[index]
                if header in required_headers:
                    row_values[header] = self._cell_to_text(value)

            if not any(row_values.values()):
                continue
            row_values["_row_no"] = row_no
            rows.append(row_values)

        employee_by_code = self._employee_by_code(
            [(row.get("EMP.NO") or "").strip().upper() for row in rows]
        )

        commands = []
        for row in rows:
            employee = employee_by_code.get((row.get("EMP.NO") or "").strip().upper())
            values = (
                self._employee_values_from_record(employee)
                if employee
                else self._employee_values_from_excel(row)
            )
            commands.append((0, 0, values))
        return commands

    def action_import_file(self):
        self.ensure_one()
        commands = self._line_commands_from_excel()
        if not commands:
            raise UserError(self._no_excel_rows_message())
        commands = self._unique_create_commands_by_employee_code(commands)
        if not commands:
            raise UserError(self._duplicate_excel_rows_message())
        self.write({"line_ids": commands})
        return {
            "type": "ir.actions.act_window",
            "name": _("Import Requestors"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _prepare_output_line_vals(self, line):
        return {
            "x_employee_code": line.x_employee_code or "",
            "x_employee_name": line.x_employee_name or "",
            "x_department_name": line.x_department_name or "",
            "x_position_name": line.x_position_name or "",
        }

    def action_confirm_import(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add or import at least one requestor."))

        lines = []
        for line in self.line_ids:
            vals = self._prepare_output_line_vals(line)
            if not any(vals.values()):
                continue
            lines.append(vals)

        if not lines:
            raise UserError(_("Please add at least one requestor with employee information."))

        return {
            "type": "ir.actions.act_window_close",
            "infos": {
                "requestor_import_lines": lines,
                "noReload": True,
            },
        }


class WorkflowRequestorImportLine(models.TransientModel):
    _name = "workflow.requestor.import.line"
    _description = "Requestor Import Preview Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        "workflow.requestor.import.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    x_request_user_id = fields.Many2one(
        "res.users",
        string="Request For",
        domain="[('active', '=', True), ('share', '=', False), ('wf_hide_from_workflow_picker', '=', False)]",
    )
    x_request_user_avatar_url = fields.Char(
        string="Requestor Avatar URL",
        compute="_compute_x_request_user_avatar_url",
    )
    x_employee_code = fields.Char(string="Employee Code")
    x_employee_name = fields.Char(string="Employee Name")
    x_department_name = fields.Char(string="Department")
    x_position_name = fields.Char(string="Position")

    @api.depends("x_request_user_id")
    def _compute_x_request_user_avatar_url(self):
        for line in self:
            line.x_request_user_avatar_url = line.wizard_id._request_user_avatar_url(
                line.x_request_user_id.id
            )

    @api.onchange("x_request_user_id")
    def _onchange_x_request_user_id(self):
        for line in self:
            if not line.x_request_user_id:
                continue
            values = line.wizard_id._employee_values_from_user(line.x_request_user_id)
            line.update(values)
