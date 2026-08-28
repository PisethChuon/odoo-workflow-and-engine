# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE, ACTION_TYPE

# convert dictionary to a list supported by fields
NODE_SELECTION_TYPE = [(v, k.replace('_', ' ').title()) for k, v in NODE_TYPE.items()]
ACTION_SELECTION_TYPE = [(v, k.replace('_', ' ').title()) for k, v in ACTION_TYPE.items()]
ROUTING_ALWAYS_TRUE = "[(1, '=', 1)]"


def _table_exists(cr, table_name):
    cr.execute("SELECT to_regclass(%s)", (table_name,))
    return bool(cr.fetchone()[0])


def _backfill_safe_ignore_routing_domains(cr):
    # Keep the legacy broad-match meaning explicit on stored routing fields.
    # This runs idempotently during module registry init so database upgrades do
    # not depend on migration folder/version matching alone.
    if _table_exists(cr, "workflow_category_task_approval_group"):
        cr.execute(
            """
            UPDATE workflow_category_task_approval_group
               SET user_domain = %s
             WHERE user_domain IS NULL
                OR btrim(user_domain) = ''
                OR btrim(user_domain) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_task_approval_group
               SET domain = %s
             WHERE domain IS NULL
                OR btrim(domain) = ''
                OR btrim(domain) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
    if _table_exists(cr, "workflow_category_version_meta_task"):
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET assignment_user_domain = %s
             WHERE btrim(coalesce(assignment_user_domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET approval_group_domain = %s
             WHERE btrim(coalesce(approval_group_domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notification_recipient_domain = %s
             WHERE (
                    notification_recipient_source = 'domain'
                    OR (
                        coalesce(notification_recipient_source, '') = ''
                        AND coalesce(notification_recipient_mode, '') IN ('domain', 'both')
                    )
                )
               AND btrim(coalesce(notification_recipient_domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notification_recipient_domain = %s
             WHERE (
                    notification_recipient_source = 'domain'
                    OR (
                        coalesce(notification_recipient_source, '') = ''
                        AND coalesce(notification_recipient_mode, '') IN ('domain', 'both')
                    )
                )
               AND btrim(coalesce(notification_recipient_domain, '')) = ''
               AND btrim(coalesce(notification_recipient_filter_domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notification_recipient_filter_domain = %s
             WHERE notification_recipient_source IN ('approval_group_users', 'group_users', 'node_users')
               AND btrim(coalesce(notification_recipient_filter_domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notification_recipient_filter_domain = %s
             WHERE notification_recipient_source IN ('approval_group_users', 'group_users', 'node_users')
               AND btrim(coalesce(notification_recipient_filter_domain, '')) = ''
               AND btrim(coalesce(notification_recipient_domain, '')) IN ('', '[]')
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
    if _table_exists(cr, "workflow_approval_action_email_recipient"):
        cr.execute(
            """
            UPDATE workflow_approval_action_email_recipient
               SET domain = %s
             WHERE source = 'domain'
               AND btrim(coalesce(domain, '')) = '[]'
            """,
            (ROUTING_ALWAYS_TRUE,),
        )
        cr.execute(
            """
            UPDATE workflow_approval_action_email_recipient
               SET domain = %s
             WHERE source IN ('approval_group_users', 'group_users', 'node_users')
               AND btrim(coalesce(domain, '')) IN ('', '[]')
            """,
            (ROUTING_ALWAYS_TRUE,),
        )

class WorkflowCategoryVersionMetaTask(models.Model):
    _name = 'workflow.category.version.meta.task'
    _description = 'Workflow Category Version Metadata'

    name = fields.Char('Node Name')
    description = fields.Text('Description')
    node_id = fields.Char('Node ID')
    sequence = fields.Integer(default=10)
    node_type = fields.Selection(NODE_SELECTION_TYPE, string='Node Type')
    attr_class = fields.Char('CSS Class')
    attr_label = fields.Char('Label')
    element = fields.Selection([('sequence', 'Sequence Flow'), ('parallel', 'Parallel Flow'), ('loop', 'Loop')],
                               string='Element Type')

    approval_group_link_ids = fields.One2many('workflow.category.task.approval.group', 'meta_id',
                                              string='Approval Groups')
    approval_group_domain = fields.Char(help="If set, the task will only apply on records that match the domain.")

    action_id = fields.Many2one(comodel_name="ir.actions.act_window", string='Action')

    email_template_external_id = fields.Many2one('mail.template', string='Email Template')
    notification_recipient_mode = fields.Selection(
        [
            ("specific_users", "Specific Users"),
            ("domain", "Domain"),
            ("both", "Specific Users + Domain"),
        ],
        string="Recipient Mode",
        default="specific_users",
        required=True,
    )
    notification_recipient_ids = fields.Many2many('res.users', string='Notification Recipients')
    notification_recipient_domain = fields.Char(
        help="If set, the task will only apply on records that match the domain.")
    notification_email_template_id = fields.Many2one(
        'mail.template',
        string='Notification Email Template',
        domain="[('model_id', '=', res_model_id)]",
        help="Default email template used by Send Task email notifications.",
    )
    version_id = fields.Many2one('workflow.approval.category.version', string='Version', ondelete='cascade')
    category_id = fields.Many2one(related='version_id.category_id')
    res_model_id = fields.Many2one(related='version_id.res_model_id', store=True)
    res_model_name = fields.Char(related='version_id.res_model_name')
    field_ids = fields.One2many('workflow.category.version.meta.field', 'meta_id', string='Fields')
    meta_action_ids = fields.One2many('workflow.category.version.meta.task.action', 'meta_task_id',
                                      string='Meta Actions')
    is_end_node = fields.Boolean(string="Is End Node", compute="_compute_is_end_node")

    activity_type = fields.Selection([('logActivity', 'Log Activity')])
    activity_type_ids = fields.Many2many(
        "workflow.approval.action",
        "workflow_task_action_approval_rel",  # <-- short table name
        "task_id",                     # column for this model
        "action_id",                   # column for related model
        string="Activity Types"
    )
    allowed_action_ids = fields.Many2many(
        "workflow.approval.action",
        compute="_compute_allowed_actions",
        string="Allowed Actions",
        store=False
    )

    activity_message_template = fields.Many2one(
        'mail.template',
        string='Message Template',
        domain="[('model', '=', 'workflow.category.version.meta.task')]"
    )

    def init(self):
        super_init = getattr(super(), "init", None)
        if super_init:
            super_init()
        _backfill_safe_ignore_routing_domains(self.env.cr)

    def _workflow_notification_node_types(self):
        return {
            "sendTask",
            "endEventMessage",
            "intermediateEventMessage",
            "intermediateThrowEventMessage",
            "startEventMessage",
        }

    automation_run_mode = fields.Selection(
        [
            ("immediate", "Immediate"),
            ("scheduled", "Scheduled"),
        ],
        string="Automation Run Mode",
        default="immediate",
        required=True,
        help="Immediate executes when the workflow reaches the node. Scheduled creates a runtime job handled by the workflow engine.",
    )
    automation_condition_domain = fields.Char(
        string="Automation Condition",
        help="Optional request domain that must match before the automation runs.",
    )
    automation_schedule_mode = fields.Selection(
        [
            ("interval", "Interval"),
            ("fixed_time", "Fixed Time"),
            ("cron", "Cron"),
        ],
        string="Schedule Mode",
        default="interval",
    )
    automation_interval_number = fields.Integer(string="Interval Number", default=5)
    automation_interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
        ],
        string="Interval Unit",
        default="minutes",
    )
    automation_fixed_time = fields.Float(
        string="Fixed Time",
        help="Hour in 24h format. Example: 13.5 = 13:30.",
    )
    automation_cron_expr = fields.Char(string="Cron Expression")
    automation_is_recurring = fields.Boolean(
        string="Recurring Automation",
        default=False,
        help="When enabled, the scheduled automation re-arms after each successful run.",
    )
    automation_recurrence_end_mode = fields.Selection(
        [
            ("forever", "Forever"),
            ("count", "Fixed Count"),
            ("until", "Until Date"),
            ("until_success", "Until First Success"),
        ],
        string="Recurrence End",
        default="forever",
    )
    automation_recurrence_count = fields.Integer(
        string="Execution Count",
        default=10,
        help="Total number of executions when recurrence end mode is Fixed Count.",
    )
    automation_recurrence_until = fields.Datetime(
        string="Repeat Until",
        help="Last allowed scheduled run for recurring automation.",
    )
    
    # For callActivity
    workflow_map_ids = fields.One2many(
        "workflow.category.version.meta.task.workflow.map",
        "meta_task_id",
        string="Workflow Mappings"
    )

    def _allowed_action_types_for_node(self):
        self.ensure_one()
        if self.node_type == "serviceTask" and getattr(self, "service_behavior", "router") == "executor":
            return {"server_action"}
        if self.node_type in self._workflow_notification_node_types():
            return {"email", "sms", "telegram", "webhook", "log"}
        if self.node_type == "scriptTask":
            return {"server_action", "workflow", "log"}
        return set()
    
    @api.depends("version_id", "res_model_name", "node_type", "service_behavior")
    def _compute_allowed_actions(self):
        for rec in self:
            try:
                if not rec.res_model_name:
                    rec.allowed_action_ids = []
                    continue
                action_domain = [("res_model_name", "=", rec.res_model_name)]
                if rec.version_id:
                    action_domain.extend([
                        "|",
                        ("version_id", "=", rec.version_id.id),
                        ("version_id", "=", False),
                    ])
                actions = self.env["workflow.approval.action"].sudo().search(action_domain)
                allowed_types = rec._allowed_action_types_for_node()
                if allowed_types:
                    actions = actions.filtered(lambda action: action.action_type in allowed_types)
                rec.allowed_action_ids = actions.ids
            except AccessError:
                rec.allowed_action_ids = []

    @api.depends('node_type')
    def _compute_is_end_node(self):
        for rec in self:
            rec.is_end_node = rec.node_type in [
                'endEvent',
                'endEventMessage',
                'endEventSignal',
                'endEventTerminate',
                'intermediateThrowEventSignal',
            ]

    def _supports_engine_managed_automation(self):
        self.ensure_one()
        return self.node_type in ('scriptTask', 'sendTask') or (
            self.node_type == 'serviceTask' and getattr(self, "service_behavior", "router") == "executor"
        )

    def _compute_automation_due_at(self, reference_dt=False):
        self.ensure_one()
        if self.automation_run_mode != "scheduled":
            return False
        reference_dt = reference_dt or fields.Datetime.now()
        if self.automation_schedule_mode == "fixed_time" and self.automation_fixed_time is not False:
            base = fields.Datetime.from_string(fields.Datetime.to_string(reference_dt))
            hour = int(self.automation_fixed_time)
            minute = int(round((self.automation_fixed_time - hour) * 60))
            candidate = base.replace(
                hour=max(0, min(23, hour)),
                minute=max(0, min(59, minute)),
                second=0,
                microsecond=0,
            )
            if candidate <= reference_dt:
                candidate += timedelta(days=1)
            return candidate
        if self.automation_schedule_mode == "cron":
            # Engine-managed cron parsing is intentionally conservative here.
            return reference_dt + timedelta(minutes=5)

        number = max(1, int(self.automation_interval_number or 1))
        match self.automation_interval_type:
            case "hours":
                return reference_dt + timedelta(hours=number)
            case "days":
                return reference_dt + timedelta(days=number)
            case "weeks":
                return reference_dt + timedelta(weeks=number)
            case _:
                return reference_dt + timedelta(minutes=number)

    def _is_automation_recurring_enabled(self):
        self.ensure_one()
        return bool(
            self.automation_run_mode == "scheduled"
            and self.automation_is_recurring
            and self._supports_engine_managed_automation()
        )

    def assign_action_to_task(env):
        medical_action = env.ref('your_module_name.action_x_medical_request', raise_if_not_found=False)
        if not medical_action:
            return

        task = env['workflow.category.version.meta.task'].search([('node_id', '=', 'Task_ApproveMedicalRequest')], limit=1)
        if task:
            task.action_id = medical_action.id

    def setup_action_window(act_window_id, task_name):
        print(act_window_id, task_name)
        
        
    # @api.model
    def create(self, vals):
        record = super().create(vals)
        if record.workflow_map_ids:
            for map_line in record.workflow_map_ids:
                if not map_line.workflow_id:
                    map_line.workflow_id = record.version_id.id
        return record

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.workflow_map_ids:
                for map_line in rec.workflow_map_ids:
                    if not map_line.workflow_id:
                        map_line.workflow_id = rec.version_id.id
        return res
    
    @api.constrains('workflow_map_ids')
    def _check_workflow_id_matches_version(self):
        for rec in self:
            for map_line in rec.workflow_map_ids:
                if map_line.called_workflow_id.id == rec.version_id.id:
                    raise ValidationError(
                        "The Main Workflow on Workflow Mappings must not match the parent workflow version."
                    )

    @api.onchange("node_type", "service_behavior")
    def _onchange_node_execution_scope(self):
        notification_nodes = self._workflow_notification_node_types()
        for rec in self:
            if rec.node_type != "serviceTask":
                rec.service_behavior = "router"
            if rec.node_type not in notification_nodes:
                rec.notification_recipient_ids = [(5, 0, 0)]
                rec.notification_approval_group_ids = [(5, 0, 0)]
                rec.notification_group_ids = [(5, 0, 0)]
                rec.notification_recipient_domain = False
                rec.notification_delivery_mode = False
                rec.notification_recipient_source = False
                rec.notification_recipient_node_ref = False
                rec.notification_recipient_filter_domain = False
                rec.notification_email_template_id = False
            if not rec._allowed_action_types_for_node():
                rec.activity_type_ids = [(5, 0, 0)]
            if not rec._supports_engine_managed_automation():
                rec.automation_run_mode = "immediate"
                rec.automation_condition_domain = False
                rec.automation_schedule_mode = "interval"
                rec.automation_interval_number = 5
                rec.automation_interval_type = "minutes"
                rec.automation_fixed_time = False
                rec.automation_cron_expr = False
                rec.automation_is_recurring = False
                rec.automation_recurrence_end_mode = "forever"
                rec.automation_recurrence_count = 10
                rec.automation_recurrence_until = False

    @api.onchange("notification_recipient_mode")
    def _onchange_notification_recipient_mode(self):
        for rec in self:
            if rec.notification_recipient_mode == "specific_users":
                rec.notification_recipient_domain = False
            elif rec.notification_recipient_mode == "domain":
                rec.notification_recipient_ids = [(5, 0, 0)]

    @api.onchange("notification_recipient_source")
    def _onchange_notification_recipient_source(self):
        for rec in self:
            if rec.notification_recipient_source == "specific_users":
                rec.notification_recipient_mode = "specific_users"
                rec.notification_approval_group_ids = [(5, 0, 0)]
                rec.notification_group_ids = [(5, 0, 0)]
                rec.notification_recipient_node_ref = False
                rec.notification_recipient_filter_domain = False
            elif rec.notification_recipient_source == "approval_group_users":
                rec.notification_recipient_mode = "domain"
                rec.notification_recipient_ids = [(5, 0, 0)]
                rec.notification_group_ids = [(5, 0, 0)]
                rec.notification_recipient_node_ref = False
            elif rec.notification_recipient_source == "group_users":
                rec.notification_recipient_mode = "domain"
                rec.notification_recipient_ids = [(5, 0, 0)]
                rec.notification_approval_group_ids = [(5, 0, 0)]
                rec.notification_recipient_node_ref = False
            elif rec.notification_recipient_source == "node_users":
                rec.notification_recipient_mode = "domain"
                rec.notification_recipient_ids = [(5, 0, 0)]
                rec.notification_approval_group_ids = [(5, 0, 0)]
                rec.notification_group_ids = [(5, 0, 0)]
            elif rec.notification_recipient_source == "domain":
                rec.notification_recipient_mode = "domain"
                rec.notification_recipient_ids = [(5, 0, 0)]
                rec.notification_approval_group_ids = [(5, 0, 0)]
                rec.notification_group_ids = [(5, 0, 0)]
                rec.notification_recipient_node_ref = False

    @api.onchange("automation_run_mode", "automation_schedule_mode")
    def _onchange_automation_schedule_fields(self):
        for rec in self:
            if rec.automation_run_mode != "scheduled":
                rec.automation_schedule_mode = "interval"
                rec.automation_fixed_time = False
                rec.automation_cron_expr = False
                rec.automation_is_recurring = False
                rec.automation_recurrence_end_mode = "forever"
                rec.automation_recurrence_until = False
                continue
            if rec.automation_schedule_mode != "fixed_time":
                rec.automation_fixed_time = False
            if rec.automation_schedule_mode != "cron":
                rec.automation_cron_expr = False

    @api.onchange("automation_is_recurring", "automation_recurrence_end_mode")
    def _onchange_automation_recurrence_fields(self):
        for rec in self:
            if not rec.automation_is_recurring:
                rec.automation_recurrence_end_mode = "forever"
                rec.automation_recurrence_until = False
                continue
            if rec.automation_recurrence_end_mode != "until":
                rec.automation_recurrence_until = False

    @api.constrains(
        "activity_type_ids",
        "node_type",
        "automation_run_mode",
        "automation_condition_domain",
        "automation_is_recurring",
        "automation_recurrence_end_mode",
        "automation_recurrence_count",
        "automation_recurrence_until",
    )
    def _check_task_action_scope(self):
        for rec in self:
            allowed_types = rec._allowed_action_types_for_node()
            if allowed_types:
                invalid_actions = rec.activity_type_ids.filtered(
                    lambda action: action.action_type not in allowed_types
                )
                if invalid_actions:
                    expected = ", ".join(sorted(allowed_types))
                    raise ValidationError(
                        _("This BPMN node only supports workflow actions of type(s): %s.") % expected
                    )
            if rec.automation_run_mode == "scheduled" and not rec._supports_engine_managed_automation():
                raise ValidationError(
                    _("Scheduled automation is only supported on Send Task, Script Task, or Service Task executors.")
                )
            if rec.automation_is_recurring and rec.automation_run_mode != "scheduled":
                raise ValidationError(
                    _("Recurring automation requires Automation Run Mode = Scheduled.")
                )
            if rec.automation_is_recurring and rec.automation_recurrence_end_mode == "count":
                if int(rec.automation_recurrence_count or 0) <= 0:
                    raise ValidationError(
                        _("Execution Count must be greater than zero for recurring automation with Fixed Count mode.")
                    )
            if rec.automation_is_recurring and rec.automation_recurrence_end_mode == "until":
                if not rec.automation_recurrence_until:
                    raise ValidationError(
                        _("Repeat Until is required when recurrence end mode is Until Date.")
                    )
            if (
                rec.notification_email_template_id
                and rec.res_model_id
                and rec.notification_email_template_id.model_id
                and rec.notification_email_template_id.model_id != rec.res_model_id
            ):
                raise ValidationError(
                    _("Notification email templates must belong to the workflow category model.")
                )
        

class WorkflowCategoryVersionMetaField(models.Model):
    _name = 'workflow.category.version.meta.field'
    _order = 'field_type desc, id desc'
    _description = 'Meta fields'

    meta_id = fields.Many2one('workflow.category.version.meta.task', string='Meta', ondelete='cascade', required=True)
    res_model_id = fields.Many2one(related='meta_id.res_model_id')
    res_model_name = fields.Char(related='meta_id.res_model_name')
    # field_id = fields.Many2one('ir.model.fields', string='Field', ondelete='cascade', required=True,
    #         domain="[('name','not in', ['required_fields','required_fields','readonly_fields'])]")
    # field_id = fields.Many2one('ir.model.fields', string='Field', ondelete='cascade', required=True)
    field_id = fields.Many2one('ir.model.fields', string='Field', ondelete='cascade', required=True,
        domain="[('model_id', 'in', related_model_ids),('name','not in', ['required_fields','required_fields','readonly_fields'])]")

    # 17/12/2025: Malinka
    # to group fields in list view
    field_group = fields.Char('Field Group', store=True)

    field_type = fields.Selection([
        ('visible', 'Visible'),
        ('required', 'Required'),
        ('readonly', 'Readonly'),
        ('invisible', 'Invisible')
    ], string='Field Type')

    domain = fields.Char(
        string='Domain',
        default='[]',
        help=(
            'Optional workflow runtime domain. The field rule applies only when '
            'this domain matches the current form values and actor context.'
        ),
    )

    activity_action_ids = fields.Many2many('workflow.category.version.meta.task.action', 'fields_task_action_rel', 
        help='must assign an action for required field')

    related_model_ids = fields.Many2many(
        'ir.model',
        compute='_compute_related_model',
        string="Related Models",
        store=False
    )
    
    EXCLUDED_MODELS = [
        'hr.employee',
        'res.partner',
        'res.users',
        'res.company',
        'mail.activity',
        'mail.message',
        'ir.model',
        'ir.attachment',
        'mail.activity.type',
        'mail.followers'
    ]


    @api.depends('res_model_id')
    def _compute_related_model(self):
        for rec in self:
            model_ids = []
            if rec.res_model_id:
                parent_model = self.env[rec.res_model_id.model]
                model_ids.append(rec.res_model_id.id)  # include parent

                for field_name, field in parent_model._fields.items():
                    if field.type in ['one2many', 'many2one', 'many2many'] and field.comodel_name:
                        if field.comodel_name not in self.EXCLUDED_MODELS:
                            model = self.env['ir.model'].search([('model', '=', field.comodel_name)], limit=1)
                            if model:
                                model_ids.append(model.id)

            rec.related_model_ids = list(set(model_ids))




class WorkflowCategoryVersionMetaTaskAction(models.Model):
    _name = 'workflow.category.version.meta.task.action'
    _description = 'Workflow Category Version Task Action'
    _order = 'sequence, id desc'

    name = fields.Char('Flow Name')
    meta_task_id = fields.Many2one('workflow.category.version.meta.task', string='Meta Task', ondelete='cascade')
    sequence = fields.Integer(default=10)
    description = fields.Text('Description')
    node_id = fields.Char('Node ID', readonly=True)
    source_id = fields.Char(string='Source Task ID', required=True, readonly=True)
    source_name = fields.Char(string='Source Task Name', readonly=True)
    source_node_type = fields.Selection(NODE_SELECTION_TYPE, string='Source Node Type', readonly=True)
    target_id = fields.Char(string='Target Task ID', required=True, readonly=True)
    target_name = fields.Char(string='Target Task Name', readonly=True)
    target_node_type = fields.Selection(NODE_SELECTION_TYPE, string='Target Node Type', readonly=True)
    attr_class = fields.Char('CSS Class')
    icon_class = fields.Char('Icon Css Class', help="Font Awesome CSS Class")
    attr_label = fields.Char('Label')  # For example, 'Approve', 'Reject'
    flow_type = fields.Selection(ACTION_SELECTION_TYPE, string='Flow Type', compute="_compute_flow_type", store=True)
    auto_action_condition = fields.Char('Auto Action Condition',
                                        help="Condition for automatic flow execution. E.g., time-based cancellation.")
    action_button_label = fields.Char('Action Button Label',
                                      help="Label for the action button, e.g., 'Approve', 'Reject'.")
    invisible_domain = fields.Char(help="whether to show or hide the approver button")
    domain = fields.Char(help="Server-side runtime domain that must match before this action can execute.")
    show_validation_dialog = fields.Boolean(
        string="Show Validation Dialog",
        default=False,
        help=(
            "When the Runtime Domain Guard does not match, show a read-only validation "
            "dialog instead of the standard Odoo error. This option changes presentation "
            "only; the action remains blocked server-side."
        ),
    )
    validation_message = fields.Html(
        string="Validation Message",
        sanitize=True,
        strip_style=True,
        strip_classes=True,
        help="Sanitized message displayed when the Runtime Domain Guard blocks this action.",
    )
    action_mode = fields.Selection(
        [
            ("route", "Route"),
            ("execute_path", "Execute Path"),
        ],
        string="Action Mode",
        default="route",
        required=True,
        help=(
            "Route keeps the existing transition behavior. Execute Path runs the connected "
            "side-effect path, activates reachable user tasks, and is intended for actions "
            "such as Notify that return to the current stage."
        ),
    )
    authorization_mode = fields.Selection(
        [
            ("approval_actor", "Approval Actor"),
            ("business_actor", "Business Action Actor"),
        ],
        default="approval_actor",
        required=True,
        index=True,
        help=(
            "Approval Actor preserves the existing approver decision path. Business Action Actor "
            "uses exact request action assignments without recording an approval decision."
        ),
    )
    authorization_scope = fields.Selection(
        [
            ("task", "Current Task"),
            ("request", "Whole Request"),
        ],
        default="task",
        required=True,
        help="Whole-request actions are reserved for future BPMN interruption support.",
    )
    business_actor_include_owner = fields.Boolean(string="Request Owner")
    business_actor_include_creator = fields.Boolean(string="Request Creator")
    business_actor_include_node_assignees = fields.Boolean(string="Current Node Assignees")
    business_actor_user_ids = fields.Many2many(
        "res.users",
        "wf_meta_action_business_user_rel",
        "meta_action_id",
        "user_id",
        string="Business Action Users",
    )
    business_actor_group_ids = fields.Many2many(
        "res.groups",
        "wf_meta_action_business_group_rel",
        "meta_action_id",
        "group_id",
        string="Business Action System Groups",
    )
    business_actor_approval_group_ids = fields.Many2many(
        "workflow.approval.group",
        "wf_meta_action_business_approval_group_rel",
        "meta_action_id",
        "group_id",
        string="Business Action Approval Groups",
    )
    business_actor_user_domain = fields.Char(
        string="Business Action User Domain",
        help="Optional res.users domain resolved once when the task becomes active.",
    )
    version_id = fields.Many2one('workflow.approval.category.version', string='Version', readonly=True)
    res_model_id = fields.Many2one(related='version_id.res_model_id', store=True, readonly=True)
    res_model_name = fields.Char(related='version_id.res_model_name', store=True, readonly=True)
    show_confirm_dialog = fields.Boolean(string="Show Confirmation Dialog",
                                          help="If enabled, a confirmation dialog will appear when the action button is clicked.", default=True)
    
    require_attachment = fields.Boolean(string="Require Attachment",
                                          help="If enabled, users must attach a file when performing this action.", default=False)
    require_attachment_domain = fields.Char(
        string="Require Attachment Domain",
        help="Optional request domain. Attachments are required only when this domain matches.",
    )
    required_attachment_count = fields.Integer(
        string="Minimum Attachments",
        default=1,
        help="Minimum number of files required when Require Attachment is enabled.",
    )
    dialog_type = fields.Selection([
        ('confirm', 'Confirm'),
        ('proceed', 'Proceed'),
        ('reject', 'Reject with reason'),
    ], string='Dialog Type', default='confirm')
    require_reason = fields.Boolean(string="Require Reason",
                                        help="If enabled, users must provide a reason when performing this action.")
    require_reason_domain = fields.Char(
        string="Require Reason Domain",
        help="Optional request domain. The reason input is required only when this domain matches.",
    )
    confirm_message = fields.Html(string="Confirmation Message",
                                      help="Message displayed in the confirmation dialog.")
    
    approval_require_number = fields.Integer(string="Approval Required Number",
                                              help="Number of required approvals for this action.", default=1)

    # Timer schedule — only meaningful when flow_type == 'autoAction' (target is a timerEvent)
    timer_duration_number = fields.Integer(
        string="Timer Duration",
        default=1,
        help="Duration before the timer fires and auto-transitions the workflow.",
    )
    timer_duration_unit = fields.Selection(
        [("minutes", "Minutes"), ("hours", "Hours"), ("days", "Days"), ("weeks", "Weeks")],
        string="Timer Duration Unit",
        default="days",
    )
    automation_schedule_mode = fields.Selection(
        [
            ("interval", "Interval"),
            ("fixed_time", "Fixed Time"),
            ("cron", "Cron"),
        ],
        string="Schedule Mode",
        default="interval",
        help="Schedule for autoAction timer transitions. Prefer interval for reminders.",
    )
    automation_interval_number = fields.Integer(string="Interval Number", default=1)
    automation_interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
        ],
        string="Interval Unit",
        default="days",
    )
    automation_fixed_time = fields.Float(
        string="Fixed Time",
        help="Hour in 24h format. Example: 13.5 = 13:30.",
    )
    automation_cron_expr = fields.Char(string="Cron Expression")
    automation_is_recurring = fields.Boolean(
        string="Recurring Timer",
        default=False,
        help="When enabled, the scheduled autoAction re-arms while the source activity is still active.",
    )
    automation_recurrence_end_mode = fields.Selection(
        [
            ("forever", "Forever"),
            ("count", "Fixed Count"),
            ("until", "Until Date"),
            ("until_success", "Until First Success"),
        ],
        string="Recurrence End",
        default="forever",
    )
    automation_recurrence_count = fields.Integer(string="Execution Count", default=10)
    automation_recurrence_until = fields.Datetime(string="Repeat Until")
    automation_trigger_mode = fields.Selection(
        [
            ("route", "Route To Next Node"),
            ("reminder", "Reminder / Side Effect Only"),
        ],
        string="Timer Trigger Mode",
        default="route",
        required=True,
        help="Route moves the workflow when the timer fires. Reminder executes linked side-effect nodes and keeps the source activity open.",
    )

    def _compute_automation_due_at(self, reference_dt=False):
        """Compute the next autoAction fire time.

        The legacy timer_duration_* fields are still honored as the interval
        fallback, so existing configured timers keep the same schedule.
        """
        self.ensure_one()
        reference_dt = reference_dt or fields.Datetime.now()
        schedule_mode = self.automation_schedule_mode or "interval"
        if schedule_mode == "fixed_time" and self.automation_fixed_time is not False:
            base = fields.Datetime.from_string(fields.Datetime.to_string(reference_dt))
            hour = int(self.automation_fixed_time)
            minute = int(round((self.automation_fixed_time - hour) * 60))
            candidate = base.replace(
                hour=max(0, min(23, hour)),
                minute=max(0, min(59, minute)),
                second=0,
                microsecond=0,
            )
            if candidate <= reference_dt:
                candidate += timedelta(days=1)
            return candidate
        if schedule_mode == "cron":
            # Keep cron support conservative and consistent with task automation.
            return reference_dt + timedelta(minutes=5)

        number = max(1, int(self.automation_interval_number or self.timer_duration_number or 1))
        unit = self.automation_interval_type or self.timer_duration_unit or "days"
        match unit:
            case "hours":
                return reference_dt + timedelta(hours=number)
            case "minutes":
                return reference_dt + timedelta(minutes=number)
            case "weeks":
                return reference_dt + timedelta(weeks=number)
            case _:
                return reference_dt + timedelta(days=number)

    def _is_automation_recurring_enabled(self):
        self.ensure_one()
        return bool(self.flow_type == ACTION_TYPE["AUTO_ACTION"] and self.automation_is_recurring)

    @api.onchange("timer_duration_number", "timer_duration_unit")
    def _onchange_legacy_timer_duration_fields(self):
        for rec in self:
            if rec.automation_schedule_mode in (False, "interval"):
                rec.automation_interval_number = max(
                    1,
                    int(rec.timer_duration_number or rec.automation_interval_number or 1),
                )
                rec.automation_interval_type = rec.timer_duration_unit or rec.automation_interval_type or "days"

    @api.onchange("automation_is_recurring", "automation_recurrence_end_mode")
    def _onchange_action_automation_recurrence_fields(self):
        for rec in self:
            if not rec.automation_is_recurring:
                rec.automation_recurrence_end_mode = "forever"
                rec.automation_recurrence_until = False
                continue
            if rec.automation_recurrence_end_mode != "until":
                rec.automation_recurrence_until = False

    @api.constrains(
        "flow_type",
        "automation_is_recurring",
        "automation_recurrence_end_mode",
        "automation_recurrence_count",
        "automation_recurrence_until",
        "automation_trigger_mode",
        "domain",
        "auto_action_condition",
    )
    def _check_action_automation_recurrence(self):
        for rec in self:
            if rec.automation_is_recurring and rec.flow_type != ACTION_TYPE["AUTO_ACTION"]:
                raise ValidationError(_("Recurring timer schedule is only supported on autoAction transitions."))
            if rec.automation_is_recurring and rec.automation_recurrence_end_mode == "count":
                if int(rec.automation_recurrence_count or 0) <= 0:
                    raise ValidationError(_("Execution Count must be greater than zero for recurring autoAction."))
            if rec.automation_is_recurring and rec.automation_recurrence_end_mode == "until":
                if not rec.automation_recurrence_until:
                    raise ValidationError(_("Repeat Until is required when autoAction stop mode is Until Date."))

    @api.constrains(
        "authorization_mode",
        "authorization_scope",
        "business_actor_include_owner",
        "business_actor_include_creator",
        "business_actor_include_node_assignees",
        "business_actor_user_ids",
        "business_actor_group_ids",
        "business_actor_approval_group_ids",
        "business_actor_user_domain",
        "approval_require_number",
    )
    def _check_business_actor_configuration(self):
        for action in self:
            if action.authorization_scope != "task":
                raise ValidationError(
                    _("Whole-request business actions are reserved for a future engine release.")
                )
            if action.authorization_mode != "business_actor":
                continue
            if action.approval_require_number > 1:
                raise ValidationError(
                    _("Business actions cannot use an approval-count threshold.")
                )

    @api.depends('target_node_type')
    def _compute_flow_type(self):
        for record in self:
            record.flow_type = BpmnEngine.get_action_type(record.target_node_type)
    
