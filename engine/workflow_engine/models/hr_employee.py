from odoo import api, models
from odoo.fields import Domain


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        result = super().name_search(name=name, domain=domain, operator=operator, limit=limit)
        if not name or operator in Domain.NEGATIVE_OPERATORS:
            return result
        if "x_emp_code" not in self._fields:
            return result

        remaining = None if limit is None else limit - len(result)
        if remaining is not None and remaining <= 0:
            return result

        existing_ids = {employee_id for employee_id, _label in result}
        employee_domain = Domain(domain or Domain.TRUE) & Domain("x_emp_code", operator, name)
        if existing_ids:
            employee_domain &= Domain("id", "not in", list(existing_ids))

        extra_employees = self.search(employee_domain, limit=remaining)
        if extra_employees:
            result.extend(extra_employees.name_get())
        return result
