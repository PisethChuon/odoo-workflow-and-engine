from datetime import date

from odoo import api, fields, models


class HomeLeaveTicket(models.Model):
    _name = "x_home_leave_ticket"
    _description = "Home Leave Ticket"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "approval.child.mixin",
    ]
    _inherits = {"workflow.base.approval.request": "x_approval_base_id"}

    @api.model
    def _get_year_requested_selection(self):
        base_year = date.today().year
        return [(str(base_year + i), str(base_year + i)) for i in range(3)]

    x_year_requested = fields.Selection(
        selection="_get_year_requested_selection",
        string="Year Requested",
        default=lambda self: str(date.today().year + 1) if date.today().month >= 10 else str(date.today().year)
    )
