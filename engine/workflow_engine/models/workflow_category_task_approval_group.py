from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class ApprovalCategoryApproverGroup(models.Model):
    _name = 'workflow.category.task.approval.group'
    _description = 'Group Approval On Meta Task'
    _rec_name = 'approval_group_id'
    _order = 'sequence'

    sequence = fields.Integer('Sequence', default=10)
    meta_id = fields.Many2one('workflow.category.version.meta.task', string='Meta', ondelete='cascade', required=True)
    res_model_id = fields.Many2one(related='meta_id.res_model_id', store=False, readonly=True)
    res_model_name = fields.Char(related='meta_id.res_model_name', store=False, readonly=True)
    approval_group_id = fields.Many2one('workflow.approval.group', string='Group', ondelete='cascade', required=True)
    user_ids = fields.Many2many(related='approval_group_id.user_ids', string='Users')
    user_domain = fields.Char(
        string='User Filter Domain',
        help="Optional res.users domain used to filter users inside the matched approval group. "
             "Use this to narrow members after the Record Domain decides whether the group applies."
    )
    domain = fields.Char(
        string="Record Domain",
        help="Optional request domain used to decide when this approval group rule applies. "
             "Use this for business routing such as hotel -> Group A and casino -> Group B."
    )
    note = fields.Text(string='Note', help="Additional information about this group approval task.")
    
    # for maping on main worklfow, and able to view sub workflow records, to create record rule when adding approver
    # meta_worklfow_map_id = fields.Many2one(
    #     'workflow.category.version.meta.task.workflow.map', 
    #     string='Meta Task',
    #     required=True,
    #     ondelete='cascade'
    # )

    def _build_request_sample_record(self):
        self.ensure_one()
        if not self.res_model_name:
            return self.env["workflow.base.approval.request"]
        try:
            RequestModel = self.env[self.res_model_name].sudo()
        except KeyError:
            return self.env["workflow.base.approval.request"]
        request_record = RequestModel.search([], limit=1)
        if not request_record:
            request_record = RequestModel.new({})
        return request_record

    def _build_domain_eval_context(self, request_record=False):
        self.ensure_one()
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        context = domain_service._assignment_eval_context(request_record=request_record)
        actor = self.env.user.sudo()
        context.setdefault("request", request_record or self.env["workflow.base.approval.request"])
        context.setdefault("object", request_record or self.env["workflow.base.approval.request"])
        context.setdefault("env", self.env)
        context.setdefault("user", actor)
        context.setdefault("uid", actor.id)
        context.setdefault("request_owner_id", actor.id)
        context.setdefault("create_uid", actor.id)
        context.setdefault("write_uid", actor.id)
        context.setdefault("manager_user_id", actor.id)
        context.setdefault("request_owner_manager_user_id", actor.id)
        context.setdefault("all_approver_user_ids", [])
        context.setdefault("decided_approver_user_ids", [])
        context.setdefault("has_decision_user_ids", [])
        context.setdefault("pending_approver_user_ids", [])
        context.setdefault("notification_submitter_and_decided_user_ids", [actor.id])
        return context

    def _validate_domain_expression(self, expression, target_model_name, context, label):
        self.ensure_one()
        group_name = self.approval_group_id.display_name or _("Unknown")
        try:
            request_model_name = self.res_model_name or "workflow.base.approval.request"
            validation_scope = (
                "assignment_users" if target_model_name == "res.users" else "request_scope"
            )
            validator = self.env["workflow.approval.category.version"]
            result = validator.workflow_studio_validate_domain_expression(
                target_model_name,
                expression,
                validation_scope,
                request_model_name,
            )
            if not result.get("valid"):
                raise ValidationError(result.get("error") or _("Domain is not valid."))
        except Exception as exc:
            raise ValidationError(
                _("Invalid %(label)s in group '%(group)s': %(error)s")
                % {
                    "label": label,
                    "group": group_name,
                    "error": str(exc),
                }
            )

    @api.constrains("user_domain", "domain")
    def _check_user_domain_syntax(self):
        # Assignment-routing domains are intentionally permissive at save time.
        # Blank, [], shorthand constants, and malformed expressions are stored
        # and ignored safely at runtime so they never broaden users or records.
        return

    # company_id = fields.Many2one('res.company', related='category_id.company_id')
    # user_id = fields.Many2one('res.users', string='User', ondelete='cascade', required=True,
    #                           check_company=True,
    #                           domain="[('company_ids', 'in', company_id), ('id', 'not in', existing_user_ids)]")
    # required = fields.Boolean(default=False)
    #
    # existing_user_ids = fields.Many2many('res.users', compute='_compute_existing_user_ids')
    #
    # @api.depends('category_id')
    # def _compute_existing_user_ids(self):
    #     for record in self:
    #         record.existing_user_ids = record.category_id.approver_ids.user_id
