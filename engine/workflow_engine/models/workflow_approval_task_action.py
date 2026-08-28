import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.mail import email_normalize

class WorkflowApprovalAction(models.Model):
    _name = "workflow.approval.action"
    _description = "Workflow Approval Action"

    name = fields.Char(required=True)
    action_type = fields.Selection([
        ('log', 'Log Message'),
        ('email', 'Send Email'),
        ('sms', 'Send SMS'),
        ('telegram', 'Send Telegram'),
        ('webhook', 'Webhook'),
        ('server_action', 'Run Server Action'),
        ('workflow', 'Workflow Action'),
    ], default='workflow')
    
    email_template_id = fields.Many2one('mail.template', string='Email Template')
    email_recipient_line_ids = fields.One2many(
        "workflow.approval.action.email.recipient",
        "action_id",
        string="Email Recipients",
        copy=True,
    )
    message_body = fields.Text(
        string='Message Body',
        help="Optional plain message body for SMS/Telegram/Webhook payloads.",
    )
    telegram_webhook_url = fields.Char(string='Telegram Webhook URL')
    webhook_url = fields.Char(string='Webhook URL')
    server_action_id = fields.Many2one(
        'ir.actions.server',
        string='Server Action',
        help="Server action executed when action_type = Run Server Action.",
    )
    code = fields.Text(string='Python Code')  # Optional: custom code execution
    
    # domain widget field
    domain = fields.Char(
        help="Domain to filter records for the action"
    )
    domain_string = fields.Char(
        help="Domain to filter records for the action"
    )

    # link back to version
    version_id = fields.Many2one(
        'workflow.approval.category.version',
        string='Version',
        readonly=True
    )
    
    res_model_id = fields.Many2one(
        'ir.model',
        string="Model",
        compute="_compute_res_model_id",
        store=True,
        readonly=True
    )

    res_model_name = fields.Char(
        related='version_id.res_model_name',
        store=True,
        readonly=True
        
    )

    def _is_workflow_config_admin(self):
        user = self.env.user
        return bool(
            self.env.su
            or user.has_group("base.group_system")
            or user.has_group("workflow_engine.group_workflow_approval_admin")
        )

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if result or self._is_workflow_config_admin():
            return result
        return self, lambda: AccessError(
            _("Only workflow administrators can access workflow action configuration.")
        )
    
    @api.depends('version_id')
    def _compute_res_model_id(self):
        for rec in self:
            rec.res_model_id = rec.version_id.res_model_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("action_type") and vals["action_type"] != "email":
                vals["email_template_id"] = False
                vals["email_recipient_line_ids"] = [(5, 0, 0)]
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals or {})
        if vals.get("action_type") and vals["action_type"] != "email":
            vals["email_template_id"] = False
            vals["email_recipient_line_ids"] = [(5, 0, 0)]
        return super().write(vals)

    @api.onchange("action_type")
    def _onchange_action_type_cleanup(self):
        for rec in self:
            if rec.action_type != "email":
                rec.email_template_id = False
                rec.email_recipient_line_ids = [(5, 0, 0)]
            if rec.action_type != "server_action":
                rec.server_action_id = False
            if rec.action_type not in ("sms", "telegram"):
                rec.message_body = False
            if rec.action_type != "telegram":
                rec.telegram_webhook_url = False
            if rec.action_type not in ("webhook", "telegram"):
                rec.webhook_url = False

    @api.constrains("action_type", "server_action_id", "email_template_id", "res_model_id")
    def _check_payload_matches_workflow_model(self):
        for rec in self:
            if (
                rec.action_type == "server_action"
                and rec.server_action_id
                and rec.res_model_id
                and rec.server_action_id.model_id
                and rec.server_action_id.model_id != rec.res_model_id
            ):
                raise ValidationError(
                    _("Selected server action must belong to the same model as the workflow category.")
                )
            if (
                rec.action_type == "email"
                and rec.email_template_id
                and rec.res_model_id
                and rec.email_template_id.model_id
                and rec.email_template_id.model_id != rec.res_model_id
            ):
                raise ValidationError(
                    _("Selected email template must belong to the same model as the workflow category.")
                )


class WorkflowApprovalActionEmailRecipient(models.Model):
    _name = "workflow.approval.action.email.recipient"
    _description = "Workflow Approval Action Email Recipient"
    _order = "sequence, id"

    action_id = fields.Many2one(
        "workflow.approval.action",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    header = fields.Selection(
        [
            ("to", "To"),
            ("cc", "CC"),
            ("bcc", "BCC"),
        ],
        required=True,
        default="to",
    )
    source = fields.Selection(
        [
            ("direct", "Raw Emails"),
            ("send_task", "Send Task Recipients"),
            ("specific_users", "Specific Users"),
            ("approval_group_users", "Workflow Approval Group Users"),
            ("group_users", "System Group Users"),
            ("node_users", "Users From Workflow Node"),
            ("domain", "Domain Over Users"),
        ],
        required=True,
        default="send_task",
    )
    raw_emails = fields.Text(
        string="Raw Emails",
        help="Comma, semicolon, or newline separated email addresses.",
    )
    user_ids = fields.Many2many(
        "res.users",
        "workflow_action_email_recipient_user_rel",
        "line_id",
        "user_id",
        string="Users",
    )
    approval_group_ids = fields.Many2many(
        "workflow.approval.group",
        "workflow_action_email_recipient_approval_group_rel",
        "line_id",
        "group_id",
        string="Workflow Approval Groups",
    )
    group_ids = fields.Many2many(
        "res.groups",
        "workflow_action_email_recipient_group_rel",
        "line_id",
        "group_id",
        string="System Groups",
    )
    node_ref = fields.Char(string="Workflow Node")
    node_user_type = fields.Selection(
        [
            ("assigned", "Assigned Users"),
            ("pending", "Pending Users"),
            ("decided", "Decided Users"),
        ],
        default="assigned",
        required=True,
    )
    domain = fields.Char(
        string="User Domain",
        help=(
            "For 'Domain Over Users' this selects users directly. "
            "For 'Workflow Approval Group Users' it further filters the selected group users."
        ),
    )

    @api.onchange("source")
    def _onchange_source_cleanup(self):
        for rec in self:
            if rec.source != "direct":
                rec.raw_emails = False
            if rec.source != "specific_users":
                rec.user_ids = [(5, 0, 0)]
            if rec.source != "approval_group_users":
                rec.approval_group_ids = [(5, 0, 0)]
            if rec.source != "group_users":
                rec.group_ids = [(5, 0, 0)]
            if rec.source != "node_users":
                rec.node_ref = False
            if rec.source not in ("domain", "approval_group_users"):
                rec.domain = False

    @api.constrains("source", "raw_emails")
    def _check_raw_emails(self):
        for rec in self:
            if rec.source != "direct" or not rec.raw_emails:
                continue
            tokens = [token.strip() for token in re.split(r"[,;\n\r]+", rec.raw_emails) if token.strip()]
            invalid = [token for token in tokens if not email_normalize(token)]
            if invalid:
                raise ValidationError(
                    _("Invalid raw email address(es): %s") % ", ".join(invalid)
                )
