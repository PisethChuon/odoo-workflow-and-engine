# -*- coding: utf-8 -*-

from odoo import models


class IrDefault(models.Model):
    _name = 'ir.default'
    _inherit = ['workflow.studio.mixin', 'ir.default']
