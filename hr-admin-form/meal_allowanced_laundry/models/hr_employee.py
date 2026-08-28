from odoo import api, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _meal_allowance_employee_code(self):
        self.ensure_one()
        employee_no = getattr(self, 'x_emp_code', False)
        if not employee_no:
            employee_no = self.barcode or self.identification_id or ''
        return employee_no

    def name_get(self):
        if not self.env.context.get('meal_allowance_show_code'):
            return super().name_get()

        result = []
        for employee in self:
            result.append((employee.id, employee._meal_allowance_employee_code() or employee.name))
        return result

    @api.depends('name', 'barcode', 'identification_id', 'x_emp_code')
    @api.depends_context('meal_allowance_show_code')
    def _compute_display_name(self):
        if not self.env.context.get('meal_allowance_show_code'):
            return super()._compute_display_name()

        for employee in self:
            employee.display_name = employee._meal_allowance_employee_code() or employee.name