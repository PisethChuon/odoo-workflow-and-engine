# -*- coding: utf-8 -*-

from odoo import models, api


class WorkflowStudioMixin(models.AbstractModel):
    """ Mixin that overrides the create and write methods to properly generate
        ir.model.data entries flagged with Studio for the corresponding resources.
        Doesn't create an ir.model.data if the record is part of a module being
        currently installed as the ir.model.data will be created automatically
        afterwards.
    """
    _name = 'workflow.studio.mixin'
    _description = 'Workflow Studio Mixin'

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        in_studio = self.env.context.get("workflow_studio")
        if in_studio and not self.env.context.get("install_mode"):
            for ob in res:
                ob.create_studio_model_data(ob.display_name)
        return res

    def write(self, vals):
        res = super(WorkflowStudioMixin, self).write(vals)

        in_studio = self.env.context.get("workflow_studio")
        if in_studio and not self.env.context.get("install_mode"):
            for record in self:
                record.create_studio_model_data(record.display_name)

        return res
