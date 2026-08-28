from odoo import api, fields, models, _

class ApproverGroup(models.Model):
    _name = 'workflow.approval.group'

    _description = 'Group Approval'
    _parent_store = True

    name = fields.Char('Group Name')
    #parent_id = fields.Many2one('workflow.approval.group', string='Parent Group', index=True, check_company=True)
    parent_id = fields.Many2one('workflow.approval.group', string='Parent Group', index=True)
    child_ids = fields.One2many('workflow.approval.group', 'parent_id', string='Child Group')
    parent_path = fields.Char(index=True)
    category_id = fields.Many2one(
        'workflow.approval.category',
        string='Approval Category',
        ondelete='set null',
        index=True,
    )
    department_id = fields.Many2one('hr.department', string='Department')
    line_id = fields.Many2one(
        'workflow.approval.group.line',
        string='Line',
        ondelete='set null',
        index=True,
    )
    team_id = fields.Many2one(
        'workflow.approval.group.team',
        string='Team',
        ondelete='set null',
        index=True,
    )
    user_ids = fields.Many2many('res.users', string='Users')

    meta_task_link_ids = fields.One2many(
        'workflow.category.task.approval.group',
        'approval_group_id',
        string='Linked Meta Tasks',
        help='Meta tasks that use this Approval Group'
    )

    meta_task_ids = fields.Many2many(
        'workflow.category.version.meta.task',
        compute='_compute_meta_tasks',
        string='Meta Tasks'
    )

    @api.depends('meta_task_link_ids.meta_id')
    def _compute_meta_tasks(self):
        for group in self:
            group.meta_task_ids = group.meta_task_link_ids.mapped('meta_id')
