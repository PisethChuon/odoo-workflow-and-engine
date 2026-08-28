# -*- coding: utf-8 -*-

from odoo import models


class IrFilters(models.Model):
    _name = 'ir.filters'
    _inherit = ['workflow.studio.mixin', 'ir.filters']
