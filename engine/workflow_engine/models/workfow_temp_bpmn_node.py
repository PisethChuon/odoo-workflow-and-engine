
from odoo import fields, models

class WorkflowBPMNTempNode(models.TransientModel):
    _name = "workflow.bpmn.temp.node"
    _description = "Temporary BPMN Node List"

    code = fields.Char(string="Code")
    name = fields.Char(string="Label")
    node_type = fields.Char(string="Node Type")

    category_id = fields.Many2one('workflow.approval.category', string="Workflow Category")

    def _compute_display_name(self):
        for rec in self:
            if rec.name and rec.node_type:
                rec.display_name = f"{rec.name} ({rec.node_type})"
            else:
                rec.display_name = rec.name or rec.code or "New Node"



