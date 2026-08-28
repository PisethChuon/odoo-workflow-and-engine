# -*- coding: utf-8 -*-

from odoo import models


class ResGroups(models.Model):
    _name = 'res.groups'
    _inherit = ['workflow.studio.mixin', 'res.groups']
