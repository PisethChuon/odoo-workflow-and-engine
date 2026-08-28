# -*- coding: utf-8 -*-
from odoo import models


class IrQweb(models.AbstractModel):
    _inherit = 'ir.qweb'

    def _in_workflow_studio(self):
        return self.env.context.get("workflow_studio")

    # REPORT STUFF
    def _render(self, template, values=None, **options):
        if self._in_workflow_studio():
            # Force inherit branding from report rendering
            return super(IrQweb, self.with_context(inherit_branding=True))._render(template, values, **options)
        return super()._render(template, values, **options)

    def _get_template_cache_keys(self):
        return super()._get_template_cache_keys() + ["workflow_studio"]

    def _prepare_environment(self, values):
        # blacklist known parasite variables
        if self._in_workflow_studio():
            for k in ["main_object"]:
                if k in values:
                    del values[k]
        return super()._prepare_environment(values)
