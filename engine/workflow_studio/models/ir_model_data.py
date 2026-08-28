# -*- coding: utf-8 -*-

from odoo import api, fields, models

STUDIO_CUSTOMIZATION_MODULES = ("workflow_studio_customization",)


class IrModelData(models.Model):
    _inherit = 'ir.model.data'

    workflow_studio = fields.Boolean(help='Checked if it has been edited with Studio.')

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('workflow_studio'):
            for vals in vals_list:
                vals['workflow_studio'] = True
        return super().create(vals_list)

    def write(self, vals):
        """ When editing an ir.model.data with Studio, we put it in noupdate to
                avoid the customizations to be dropped when upgrading the module.
        """
        if self.env.context.get('workflow_studio'):
            vals['noupdate'] = True
            vals['workflow_studio'] = True
        return super(IrModelData, self).write(vals)

    def _build_insert_xmlids_values(self):
        values = super()._build_insert_xmlids_values()
        if self.env.context.get('workflow_studio'):
            values['workflow_studio'] = 'true'
        return values

    def _xmlid_for_export(self):
        self.ensure_one()
        xmlid = self.complete_name.replace("__export__.", "")
        for module in STUDIO_CUSTOMIZATION_MODULES:
            xmlid = xmlid.replace(f"{module}.", "")
        return xmlid

    def init(self):
        super_init = getattr(super(), 'init', None)
        if super_init:
            super_init()
        # One-time safe normalization for databases that already contain
        # legacy Studio-generated names.
        self.env.cr.execute(
            """
            UPDATE ir_model_data
               SET name = REPLACE(REPLACE(name, 'odoo_studio', 'workflow_studio'), 'web_studio', 'workflow_studio')
             WHERE module = %s
               AND (name LIKE 'odoo_studio%%' OR name LIKE 'web_studio%%')
            """,
            (STUDIO_CUSTOMIZATION_MODULES,),
        )
        self.env.cr.execute(
            """
            UPDATE ir_ui_view
               SET name = REPLACE(name, 'Odoo Studio:', 'Workflow Studio:')
             WHERE name LIKE 'Odoo Studio:% customization'
            """
        )
