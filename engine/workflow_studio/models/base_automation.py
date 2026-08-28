# -*- coding: utf-8 -*-

from odoo import models


class BaseAutomation(models.Model):
    _name = 'base.automation'
    _inherit = ['workflow.studio.mixin', 'base.automation']
