from odoo import fields, models, _

class HierachyData(models.Model):
    _name = 'hierachy.data'
    _description = 'Hierachy Data'
    
    name = fields.Char("Name")
    type = fields.Selection([
        ('application', 'Application'),
        ('location', 'Location'),
        ('other', 'Other')
    ], default='other')
    parent_id = fields.Many2one('hierachy.data', string='Parent')
    child_ids = fields.One2many('hierachy.data', 'parent_id', string='Child')