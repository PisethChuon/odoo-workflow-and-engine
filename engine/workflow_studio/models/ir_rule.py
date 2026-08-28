# -*- coding: utf-8 -*-

from odoo import models


class IrRule(models.Model):
    _name = 'ir.rule'
    _description = 'Rule'
    _inherit = ['workflow.studio.mixin', 'ir.rule']
