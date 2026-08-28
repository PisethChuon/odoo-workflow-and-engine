# -*- coding: utf-8 -*-

from odoo import models


class ReportPaperformat(models.Model):
    _name = 'report.paperformat'
    _inherit = ['workflow.studio.mixin', 'report.paperformat']
