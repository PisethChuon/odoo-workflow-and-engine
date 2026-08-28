# -*- coding: utf-8 -*-

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        result = super().session_info()
        user = self.env.user.sudo()
        employee = user.employee_id
        department = user.department_id or (employee.department_id if employee else False)
        job = employee.job_id if employee else False

        user_groups = getattr(user, "group_ids", False) or getattr(user, "groups_id", False)
        group_xmlids = []
        if user_groups:
            group_xmlids = self.env["ir.model.data"].sudo().search([
                ("model", "=", "res.groups"),
                ("res_id", "in", user_groups.ids),
            ]).mapped("complete_name")

        normalized_position = (job.name or "").strip().lower() if job else ""
        is_hod = "hod" in normalized_position or "head of department" in normalized_position

        result["workflow_actor"] = {
            "user_id": user.id,
            "name": user.name or "",
            "login": user.login or "",
            "department_name": department.name if department else "",
            "position_name": job.name if job else "",
            "group_xmlids": group_xmlids,
            "is_hod": is_hod,
        }
        return result
