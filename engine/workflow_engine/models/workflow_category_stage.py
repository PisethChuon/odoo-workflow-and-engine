# -*- coding: utf-8 -*-

from odoo import models, fields, api


class WorkflowApprovalStage(models.Model):
    _name = "workflow.category.stage"
    _description = "Workflow Category Stage"

    version_id = fields.Many2one('workflow.approval.category.version', required=True, ondelete='cascade')
    category_id = fields.Many2one(related='version_id.category_id', store=True, readonly=True)

    name = fields.Char(string="Stage Name", required=True)
    sequence = fields.Integer(default=10)

    user_ids = fields.Many2many("res.users", string="Users")
    group_ids = fields.Many2many("res.groups", string="Groups")

    require_fields = fields.Char(string="Required Fields (CSV)")
    readonly_fields = fields.Char(string="Readonly Fields (CSV)")
    invisible_fields = fields.Char(string="Invisible Fields (CSV)")
    visible_buttons = fields.Char(string="Visible Buttons (CSV)")

