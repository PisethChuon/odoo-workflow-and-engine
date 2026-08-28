# -*- coding: utf-8 -*-

from odoo import models


class MailTemplate(models.Model):
    _name = 'mail.template'
    _description = 'Email Templates'
    _inherit = ['workflow.studio.mixin', 'mail.template']
