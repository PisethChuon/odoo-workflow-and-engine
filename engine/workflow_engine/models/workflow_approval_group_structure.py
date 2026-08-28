from odoo import fields, models


class ApprovalGroupLine(models.Model):
    _name = "workflow.approval.group.line"
    _description = "Approval Group Line"
    _order = "department_id, name, id"

    name = fields.Char(string="Line", required=True, index=True)
    active = fields.Boolean(default=True)
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        ondelete="set null",
        index=True,
    )
    team_ids = fields.One2many(
        "workflow.approval.group.team",
        "line_id",
        string="Teams",
    )
    approval_group_ids = fields.One2many(
        "workflow.approval.group",
        "line_id",
        string="Approval Groups",
    )


class ApprovalGroupTeam(models.Model):
    _name = "workflow.approval.group.team"
    _description = "Approval Group Team"
    _order = "department_id, line_id, name, id"

    name = fields.Char(string="Team", required=True, index=True)
    active = fields.Boolean(default=True)
    line_id = fields.Many2one(
        "workflow.approval.group.line",
        string="Line",
        ondelete="set null",
        index=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="line_id.department_id",
        store=True,
        readonly=True,
    )
    approval_group_ids = fields.One2many(
        "workflow.approval.group",
        "team_id",
        string="Approval Groups",
    )
