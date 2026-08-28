from odoo import api, fields, models, _

class WorkflowCategoryVersionMetaTaskWorkflowMap(models.Model):
    _name = "workflow.category.version.meta.task.workflow.map"
    _description = "Workflow Call Mapping"

    meta_task_id = fields.Many2one(
        "workflow.category.version.meta.task",
        required=True,
        ondelete="cascade",
        string="Meta Task"
    )
    workflow_id = fields.Many2one(
        'workflow.approval.category.version',
        string='Main Workflow',
        required=False, 
        store=True
    )
    called_workflow_id = fields.Many2one(
        "workflow.approval.category.version",
        string="Called Workflow",
        required=True
    )
    execution_mode = fields.Selection([
        ('sync', 'Required'),
        ('async', 'Optional')
    ], default='sync', string="Execution Mode")
    field_mapping = fields.Text(
        string="Field Mapping",
        help="JSON mapping of parent field → child field, e.g. {\"partner_id\": \"customer_id\"}"
    )
    display_name = fields.Char(
        string="Display Name",
        compute="_compute_display_name",
        store=True
    )
    
    domain = fields.Char(help="For filter condtion base on record")
    res_model_id = fields.Many2one(related='called_workflow_id.res_model_id', store=True, readonly=True)
    res_model_name = fields.Char(related='called_workflow_id.res_model_name', store=True, readonly=True)
    
    @api.depends("called_workflow_id", "execution_mode")
    def _compute_display_name(self):
        for rec in self:
            base = rec.called_workflow_id.display_name or "Unnamed Workflow"
            if rec.execution_mode:
                rec.display_name = f"{base} [{rec.execution_mode.capitalize()}]"
            else:
                rec.display_name = base
    
