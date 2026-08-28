# -*- coding: utf-8 -*-

import base64
from collections import defaultdict
from random import randint
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError, UserError
from odoo.addons.workflow_engine.utils.util import RequestDataContext
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine
from odoo.tools.safe_eval import safe_eval


class ApprovalCategory(models.Model):
    _name = 'workflow.approval.category'
    _description = 'Workflow Approval Category'
    _order = 'sequence, create_date, id'

    _check_company_auto = True

    def _get_default_image(self):
        default_image_path = 'workflow_engine/static/src/img/Folder.png'
        return base64.b64encode(tools.misc.file_open(default_image_path, 'rb').read())

    @api.model
    def _get_default_sequence(self):
        last_category = self.sudo().search([], order="sequence desc, id desc", limit=1)
        return (last_category.sequence if last_category else 0) + 10

    name = fields.Char(string="Name", translate=True, required=True)
    company_id = fields.Many2one(
        'res.company', 'Company', copy=False,
        required=True, index=True, default=lambda s: s.env.company)
    department_id = fields.Many2one('hr.department')
    color = fields.Integer(default=lambda dummy: randint(1, 11))
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        string="Sequence",
        default=_get_default_sequence,
        help=(
            "Controls the workflow order on category configuration, dashboards, "
            "and category reports."
        ),
    )
    description = fields.Char(string="Description", translate=True)
    guide_html = fields.Html(
        string="Workflow Guide",
        translate=True,
        help="End-user instructions shown from the category info icon on the dashboard card.",
    )
    image = fields.Binary(string='Image', default=_get_default_image)

    res_model = fields.Many2one('ir.model', string='Model', ondelete='cascade')
    res_model_name = fields.Char(
        'Document Model Name', related='res_model.model', readonly=True, store=True)
    version_ids = fields.One2many('workflow.approval.category.version', 'category_id', string='Versions')
    active_version_id = fields.Many2one('workflow.approval.category.version', string='Active Version')
    bpmn_xml = fields.Text(string='BPMN', related='active_version_id.bpmn_xml')
    automation_action_ids = fields.One2many(
        'base.automation',  # Related model
        'model_id',  # The field on base.automation that relates to ir.model
        string='Automation Actions',
        compute='_compute_automation_actions')
    
    is_child = fields.Boolean(
        string='Is Child Category',
        compute="_compute_is_child",
        store=True
    )
    
    requirer_document = fields.Selection([('required', 'Required'), ('optional', 'Optional')], string="Documents",
                                         default="optional", required=True)
    approval_minimum = fields.Integer(string="Minimum Approval", default="1", required=True)
    invalid_minimum = fields.Boolean(compute='_compute_invalid_minimum')
    invalid_minimum_warning = fields.Char(compute='_compute_invalid_minimum')

    approval_type = fields.Selection(string="Approval Type", selection=[],
                                     help="Allows you to define which documents you would like to create once the request has been approved")
    manager_approval = fields.Selection([('approver', 'Is Approver'), ('required', 'Is Required Approver')],
                                        string="Employee's Manager",
                                        help="""How the employee's manager interacts with this type of approval.

        Empty: do nothing
        Is Approver: the employee's manager will be in the approver list
        Is Required Approver: the employee's manager will be required to approve the request.
    """)
    user_ids = fields.Many2many('res.users', compute='_compute_user_ids', string="Approver Users")

    approver_ids = fields.One2many('workflow.approval.category.approver', 'category_id', string="Approvers")
    request_ids = fields.One2many(
        'workflow.base.approval.request',
        'category_id',
        string="Requests",
        readonly=True,
    )
    approver_sequence = fields.Boolean('Approvers Sequence?', help="If checked, the approvers have to approve in sequence (one after the other). If Employee's Manager is selected as approver, they will be the first in line.")
    request_to_validate_count = fields.Integer("Number of requests to validate", compute="_compute_request_to_validate_count")
    request_to_validate_count_display = fields.Char(
        string="Requests To Validate (Display)",
        compute="_compute_request_stat_displays",
    )
    
    automated_sequence = fields.Boolean('Automated Sequence?', default=True, help="If checked, the Approval Requests will have an automated generated name based on the given code.")
    sequence_code = fields.Char(string="Code", default="RQ")
    sequence_id = fields.Many2one('ir.sequence', 'Reference Sequence', copy=False, check_company=True)

    request_all_count = fields.Integer("Number of total requests", compute="_compute_request_stats")
    request_tosubmit_count = fields.Integer("Number of open requests", compute="_compute_request_stats")
    request_waiting_count = fields.Integer("Number of progress requests", compute="_compute_request_stats")
    request_reviewed_count = fields.Integer("Number of reviewed requests", compute="_compute_request_stats")
    request_completed_count = fields.Integer("Number of close requests", compute="_compute_request_stats")
    request_all_count_display = fields.Char(
        string="Total Requests (Display)",
        compute="_compute_request_stat_displays",
    )
    request_tosubmit_count_display = fields.Char(
        string="New Requests (Display)",
        compute="_compute_request_stat_displays",
    )
    request_waiting_count_display = fields.Char(
        string="In Progress Requests (Display)",
        compute="_compute_request_stat_displays",
    )
    request_reviewed_count_display = fields.Char(
        string="Reviewed Requests (Display)",
        compute="_compute_request_stat_displays",
    )
    request_completed_count_display = fields.Char(
        string="Done Requests (Display)",
        compute="_compute_request_stat_displays",
    )

    allowed_duplicate = fields.Boolean(
        string='Allow Duplicate Requests',
        default=True,
        help="Allow the same request owner to keep multiple active requests in this workflow category.",
    )
    auto_cancel_timeout = fields.Integer(string="Auto-cancel timeout (days)", default=3, help="Number of days to auto cancel the request.")
    
    allow_duplicate_domain = fields.Char(
        string='Duplicate Block Domain',
        default="[(1, '=', 1)]",
        help=(
            "When duplicate requests are not allowed, existing owner/category requests "
            "matching this request-domain will trigger the cancel/create confirmation. "
            "Use [] or [(1, '=', 1)] to block any active existing request."
        ),
    )
    enable_request_history = fields.Boolean(
        string="Enable History Button",
        default=False,
        help="Allow child workflow forms to open request history for the same requester in this category.",
    )
    request_history_domain = fields.Char(
        string="History Domain",
        default="[(1, '=', 1)]",
        help=(
            "Filter which requester history records appear in the popup. "
            "The domain is evaluated against the child request model for this workflow category."
        ),
    )

    @api.depends('res_model')
    def _compute_automation_actions(self):
        for record in self:
            if record.res_model:
                model_id = record.res_model
                automation_records = self.env['base.automation'].sudo().search([
                    ('model_id', '=', model_id.id)
                ])
                if len(automation_records) > 0:
                    record.automation_action_ids = automation_records.ids
                else:
                    record.automation_action_ids = False  # Set to False if no actions found
            else:
                record.automation_action_ids = False


    def action_open_automation_actions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'base.automation',
            'view_mode': 'list,form',
            'name': 'Automation Actions',
            'domain': [('model_id', '=', self.res_model.id)],
            'context': {
                'default_model_id': self.res_model.id,
            }
        }


    def load_design(self):
        self.ensure_one()
        print("..............", str(self.active_version_id.bpmn_xml))
    
    @api.depends_context('uid')
    def _compute_request_stats(self):
        """Compute request counters with aggregated queries for dashboard scale."""
        if not self:
            return

        filter_key = self.env.context.get("filter")
        base_domain = self._get_count_domain_for_approval_request(filter_key) + [('category_id', 'in', self.ids)]
        waiting_domain = self._get_dashboard_waiting_scope_domain(filter_key) + [('category_id', 'in', self.ids)]
        Request = self.env['workflow.base.approval.request']
        done_states = self._done_state_values()
        review_domain = self._get_dashboard_to_review_domain() + [('category_id', 'in', self.ids)]

        grouped_all = Request._read_group(base_domain, ['category_id'], ['__count'])
        grouped_new = Request._read_group(base_domain + [('state', '=', 'new')], ['category_id'], ['__count'])
        grouped_waiting = Request._read_group(waiting_domain + [('state', '=', 'waiting')], ['category_id'], ['__count'])
        grouped_reviewed = Request._read_group(review_domain, ['category_id'], ['__count'])
        grouped_completed = Request._read_group(base_domain + [('state', 'in', done_states)], ['category_id'], ['__count'])

        all_map = defaultdict(int, {cat.id: count for cat, count in grouped_all if cat})
        new_map = defaultdict(int, {cat.id: count for cat, count in grouped_new if cat})
        waiting_map = defaultdict(int, {cat.id: count for cat, count in grouped_waiting if cat})
        reviewed_map = defaultdict(int, {cat.id: count for cat, count in grouped_reviewed if cat})
        completed_map = defaultdict(int, {cat.id: count for cat, count in grouped_completed if cat})

        for rec in self:
            rec.request_all_count = all_map[rec.id]
            rec.request_tosubmit_count = new_map[rec.id]
            rec.request_waiting_count = waiting_map[rec.id]
            rec.request_reviewed_count = reviewed_map[rec.id]
            rec.request_completed_count = completed_map[rec.id]

    @api.model
    def _done_state_values(self):
        # Include all request stages that should be treated as done in dashboard metrics.
        return ["done", "completed", "cancelled", "auto_cancelled", "refused", "auto_approved"]

    def _get_dashboard_review_domain(self):
        """Requests this user contributed to that are not pending for them and are not done."""
        Request = self.env["workflow.base.approval.request"]
        return (
            Request._domain_my_contribution()
            + [("state", "not in", ["draft", "new"] + self._done_state_values())]
        )

    def _get_dashboard_to_review_domain(self):
        """Requests that currently require the logged-in user's decision."""
        return self.env["workflow.base.approval.request"]._domain_my_work_item()

    @api.model
    def _get_dashboard_waiting_scope_domain(self, filter_key):
        """
        Resolve the waiting dashboard scope for the active filter.

        My Workflow Dashboard treats "in progress" as requests owned by or
        created by the logged-in user that are waiting for approval. Other
        dashboards keep their broader request scopes.
        """
        if filter_key == RequestDataContext.MY_REQUESTS.value:
            return ["|", ("request_owner_id", "=", self.env.uid), ("create_uid", "=", self.env.uid)]
        return self._get_count_domain_for_approval_request(filter_key)
    
    def _compute_request_to_validate_count(self):
        if not self:
            return

        Request = self.env["workflow.base.approval.request"]
        work_domain = Request._domain_my_work_item() + [("category_id", "in", self.ids)]
        requests_data = Request._read_group(work_domain, ["category_id"], ["__count"])
        requests_mapped_data = {category.id: count for category, count in requests_data if category}
        for category in self:
            category.request_to_validate_count = requests_mapped_data.get(category.id, 0)

    @api.depends(
        'request_all_count',
        'request_tosubmit_count',
        'request_waiting_count',
        'request_reviewed_count',
        'request_completed_count',
        'request_to_validate_count',
    )
    def _compute_request_stat_displays(self):
        for category in self:
            category.request_all_count_display = category._format_compact_count(category.request_all_count)
            category.request_tosubmit_count_display = category._format_compact_count(category.request_tosubmit_count)
            category.request_waiting_count_display = category._format_compact_count(category.request_waiting_count)
            category.request_reviewed_count_display = category._format_compact_count(category.request_reviewed_count)
            category.request_completed_count_display = category._format_compact_count(category.request_completed_count)
            category.request_to_validate_count_display = category._format_compact_count(category.request_to_validate_count)

    @api.model
    def _format_compact_count(self, value):
        try:
            value = int(value or 0)
        except (TypeError, ValueError):
            value = 0

        negative = value < 0
        absolute = abs(value)
        suffixes = (
            (1_000_000_000, "B", True),
            (1_000_000, "M", True),
            (1_000, "K", False),
        )
        rendered = str(absolute)

        for threshold, suffix, show_plus in suffixes:
            if absolute < threshold:
                continue
            whole = absolute // threshold
            remainder = absolute % threshold
            use_decimal = whole < 100 and remainder
            if use_decimal:
                decimal = (remainder * 10) // threshold
                rendered = f"{whole}.{decimal}".rstrip("0").rstrip(".")
            else:
                rendered = str(whole)
            rendered = f"{rendered}{suffix}"
            if show_plus:
                rendered = f"{rendered}+"
            break

        if negative and rendered != "0":
            return f"-{rendered}"
        return rendered


    @api.depends_context('lang')
    @api.depends('approval_minimum', 'approver_ids', 'manager_approval')
    def _compute_invalid_minimum(self):
        for record in self:
            if record.approval_minimum > len(record.approver_ids) + int(bool(record.manager_approval)):
                record.invalid_minimum = True
            else:
                record.invalid_minimum = False
            record.invalid_minimum_warning = record.invalid_minimum and _(
                'Your minimum approval exceeds the total of default approvers.')


    @api.depends('approver_ids')
    def _compute_user_ids(self):
        for record in self:
            record.user_ids = record.approver_ids.user_id


    @api.constrains('approval_minimum', 'approver_ids')
    def _constrains_approval_minimum(self):
        for record in self:
            if record.approval_minimum < len(record.approver_ids.filtered('required')):
                raise ValidationError(_('Minimum Approval must be equal or superior to the sum of required Approvers.'))


    @api.constrains('approver_ids')
    def _constrains_approver_ids(self):
        # There seems to be a problem with how the database is updated which doesn't let use to an sql constraint for
        # this Issue is: records seem to be created before others are saved, meaning that if you originally have only
        # user a change user a to user b and add a new line with user a, the second line will be created and will
        # trigger the constraint before the first line will be updated which wouldn't trigger a ValidationError
        for record in self:
            if len(record.approver_ids) != len(record.approver_ids.user_id):
                raise ValidationError(_('An user may not be in the approver list multiple times.'))

    @api.constrains('approver_sequence', 'approval_minimum')
    def _constrains_approver_sequence(self):
        if any(a.approver_sequence and not a.approval_minimum for a in self):
            raise ValidationError(_('Approver Sequence can only be activated with at least 1 minimum approver.'))


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('automated_sequence'):
                sequence = self.env['ir.sequence'].create({
                    'name': _('Sequence %(code)s', code=vals.get('sequence_code', 'RQ')),
                    'padding': 5,
                    'prefix': vals.get('sequence_code', 'RQ'),
                    'company_id': vals.get('company_id'),
                })
                vals['sequence_id'] = sequence.id
        return super().create(vals_list)


    def write(self, vals):
        if 'sequence_code' in vals:
            for approval_category in self:
                sequence_vals = {
                    'name': _('Sequence %(code)s', code=vals['sequence_code']),
                    'padding': 5,
                    'prefix': vals['sequence_code'],
                }
                if approval_category.sequence_id:
                    approval_category.sequence_id.write(sequence_vals)
                else:
                    sequence_vals['company_id'] = vals.get('company_id', approval_category.company_id.id)
                    sequence = self.env['ir.sequence'].create(sequence_vals)
                    approval_category.sequence_id = sequence
        if 'company_id' in vals:
            for approval_category in self:
                if approval_category.sequence_id:
                    approval_category.sequence_id.company_id = vals.get('company_id')
        return super().write(vals)


    def create_request(self):
        self.ensure_one()
        self.check_create_request_access(user=self.env.user)
        # If category uses sequence, set next sequence as name
        # (if not, set category name as default name).
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": self.res_model_name,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
            "context": {
                'default_name': _('New') if self.automated_sequence else self.name,
                'default_category_id': self.id,
                'default_version_id': self.active_version_id.id,
                'default_request_owner_id': self.env.user.id,
                'default_request_status': 'new',
                'default_state': 'draft',
                'form_view_initial_mode': 'edit',
            },
        }


    def action_new_request(self):
        """
        Called when the "New Request" button is clicked.

        Resolution order for the initiation form action:
        1. Start Event meta task action_id  (preferred — configure in Studio on the Start Event)
        2. First userTask after Start Event (legacy fallback for existing workflows)
        """
        self.ensure_one()
        self.check_create_request_access(user=self.env.user)

        if not self.active_version_id or not self.active_version_id.bpmn_xml:
            raise UserError(_("This workflow has no active version or BPMN diagram."))

        engine = BpmnEngine(self.active_version_id.bpmn_xml)
        start_node = engine.get_start_event()
        if start_node is None:
            raise UserError(_("No start event found in the BPMN diagram."))

        # Preferred: read action_id from the Start Event meta task.
        start_node_id = start_node.attrib.get("id")
        if start_node_id:
            start_meta = self._get_meta_task(start_node_id)
            if start_meta and start_meta.action_id:
                return self._render_bpmn_user_task(start_meta, engine)

        # Legacy fallback: first userTask immediately after the Start Event.
        next_nodes = engine.get_next_elements(start_node)
        if not next_nodes:
            raise UserError(_("No sequence flow found after the Start Event in the BPMN diagram."))

        user_task_node = next((n for n in next_nodes if engine.is_user_task(n)), None)
        if user_task_node is None:
            raise UserError(
                _("No initiation form configured. Set an Initiation Form on the Start Event in Workflow Studio.")
            )

        meta_task = self._get_meta_task(user_task_node.attrib["id"])
        if not meta_task:
            raise UserError(
                _("No metadata found for task '%s'.") % user_task_node.attrib.get("id", "")
            )

        return self._render_bpmn_user_task(meta_task, engine)

    def action_open_guide_modal(self):
        self.ensure_one()
        view = self.env.ref("workflow_engine.workflow_approval_category_guide_modal_view")
        return {
            "type": "ir.actions.act_window",
            "name": _("%s - Guide") % (self.display_name,),
            "res_model": "workflow.approval.category",
            "res_id": self.id,
            "views": [(view.id, "form")],
            "view_mode": "form",
            "target": "new",
            "context": {
                **self.env.context,
                "create": False,
                "edit": False,
                "delete": False,
                "wf_fullscreen_dialog": True,
            },
        }


    def _get_meta_task(self, node_id):
        return self.active_version_id.meta_task_ids.filtered(lambda t: t.node_id == node_id)


    def _render_bpmn_user_task(self, meta_task, engine):
        """
        Return the ir.actions.act_window dict for the given meta task.
        Uses sudo() on the action record because ir.actions.act_window is a
        technical model not granted to regular users via ACL data files.
        """
        if not meta_task.action_id:
            return self.create_request()
        action = meta_task.action_id.sudo()
        context = {
            'default_name': _('New') if self.automated_sequence else self.name,
            'default_category_id': self.id,
            'default_version_id': self.active_version_id.id,
            'default_request_owner_id': self.env.user.id,
            'default_request_status': 'new',
            'default_state': 'draft',
            'form_view_initial_mode': 'edit',
        }
        action['context'] = context
        action['view_mode'] = "form"
        action['path'] = f"category_{self.id}"
        action_dict = action._get_action_dict()
        if (
            self.res_model_name
            and self.res_model_name != "workflow.base.approval.request"
            and action_dict.get("res_model") == "workflow.base.approval.request"
        ):
            action_dict["res_model"] = self.res_model_name
            action_dict["views"] = [[False, "form"]]
            action_dict.pop("view_id", None)
        return action_dict


    def _get_count_domain_for_approval_request(self, filter):
        """
        Return the same request scopes used by the top-level dashboard/list menus.

        Filter names are historical:
        - MY_REVIEWS opens "My Work List" (requests requiring my decision now)
        - MY_APPROVALS opens "My Contribute List" (requests I participated in)
        - MY_REQUESTS opens requests I own, requested, or created
        """
        Request = self.env["workflow.base.approval.request"]
        match filter:
            case RequestDataContext.MY_REQUESTS.value:
                domain = Request._domain_my_owned_request()
            case RequestDataContext.MY_REVIEWS.value:
                domain = Request._domain_my_work_item()
            case RequestDataContext.MY_APPROVALS.value:
                domain = Request._domain_my_contribution()
            case _:
               domain = []
        return domain

    def _merge_action_context(self, action, extra_context=None):
        """Normalize action context to dict and merge runtime keys safely."""
        action_context = action.get("context") or {}
        if isinstance(action_context, str):
            try:
                action_context = safe_eval(action_context, {"uid": self.env.uid})
            except Exception:
                action_context = {}
        if not isinstance(action_context, dict):
            action_context = {}
        merged = dict(action_context)
        merged.update(extra_context or {})
        action["context"] = merged
        return action


    def action_approval_category(self):
        """
        this action executes when open, in progress or complete button is clicked.
        it requires two context variables.
        - filter: to tell if it is for my request or not...etc
        - state: to tell if it is clicked from open, in progress or completed button
        
        """
        filter = self.env.context.get("filter")
        domain = self._get_count_domain_for_approval_request(filter)
        state = self.env.context.get('state') or None
        review_scope_requested = False
        if state:
            state_values = list(state) if isinstance(state, (list, tuple, set)) else [state]
            if "reviewed" in state_values:
                review_scope_requested = True
                domain = self._get_dashboard_to_review_domain()
                state_values = [s for s in state_values if s != "reviewed"]
            elif "waiting" in state_values:
                domain = self._get_dashboard_waiting_scope_domain(filter)
            if "completed" in state_values:
                state_values = [s for s in state_values if s != "completed"] + self._done_state_values()
            # keep order stable but unique
            state_values = list(dict.fromkeys(state_values))
            if state_values:
                domain += [('state', 'in', state_values)]

        opens_request_scope = review_scope_requested or filter in (
            RequestDataContext.MY_REVIEWS.value,
            RequestDataContext.MY_APPROVALS.value,
        )

        if opens_request_scope or filter in (
            RequestDataContext.MY_REQUESTS.value,
            RequestDataContext.MY_REVIEWS.value,
            RequestDataContext.MY_APPROVALS.value,
        ):
            domain += [('category_id', '=', self.id)]
            # Review domains are resolved against base-request runtime rows. Keep
            # those scopes on the unified work list because child record IDs do
            # not match their linked workflow.base.approval.request IDs.
            if (
                not opens_request_scope
                and self.res_model_name
                and self.res_model_name != "workflow.base.approval.request"
            ):
                return {
                    "type": "ir.actions.act_window",
                    "res_model": self.res_model_name,
                    "view_mode": "list,kanban,form",
                    "mobile_view_mode": "kanban",
                    "name": self.name,
                    "views": [[False, "list"], [False, "kanban"], [False, "form"]],
                    "domain": domain,
                    "target": "current",
                    "context": {"wf_open_target": "current"},
                }
            action_map = {
                RequestDataContext.MY_REQUESTS.value: "workflow_engine.my_all_approval_requests_action_window",
                RequestDataContext.MY_REVIEWS.value: "workflow_engine.my_approval_requests_to_review_action_window",
                RequestDataContext.MY_APPROVALS.value: "workflow_engine.my_all_approval_requests_action_window",
            }
            action_xmlid = (
                "workflow_engine.my_approval_requests_to_review_action_window"
                if opens_request_scope
                else action_map.get(filter)
            ) or "workflow_engine.my_approval_requests_to_review_action_window"
            action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
            action.update({
                "name": self.name,
                "domain": domain,
            })
            return self._merge_action_context(action, {"wf_open_target": "current"})

        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model_name,
            'view_mode': 'list,kanban,form',
            'mobile_view_mode': 'kanban',
            "name": self.name,
            "domain": domain,
            "target": "current",
            "context": {"wf_open_target": "current"},
        }

    @api.model
    def action_open_dashboard_requests(self, state=None):
        """Open request list from dashboard KPI cards with current context filter."""
        filter_key = self.env.context.get("filter")
        domain = self._get_count_domain_for_approval_request(filter_key)
        action_xmlid = None
        if state:
            if state == 'completed':
                domain += [('state', 'in', self._done_state_values())]
            elif state == 'reviewed':
                domain = self._get_dashboard_to_review_domain()
                action_xmlid = "workflow_engine.my_approval_requests_to_review_action_window"
            elif state == 'waiting':
                domain = self._get_dashboard_waiting_scope_domain(filter_key) + [('state', '=', 'waiting')]
            else:
                domain += [('state', '=', state)]

        title_map = {
            'new': _('New Requests'),
            'waiting': _('Requests In Progress'),
            'reviewed': _('Requests To Review'),
            'completed': _('Done Requests'),
        }

        if action_xmlid:
            action = self.env["ir.actions.actions"]._for_xml_id(action_xmlid)
            action.update({
                "name": title_map.get(state) or _("All Requests"),
                "domain": domain,
                "target": "current",
            })
        else:
            action = {
                "type": "ir.actions.act_window",
                "name": title_map.get(state) or _("All Requests"),
                "res_model": "workflow.base.approval.request",
                "view_mode": "list,kanban,form",
                "mobile_view_mode": "kanban",
                "views": [
                    [self.env.ref("workflow_engine.approval_base_request_view_list").id, "list"],
                    [self.env.ref("workflow_engine.approval_base_request_view_kanban_mobile").id, "kanban"],
                    [self.env.ref("workflow_engine.approval_base_request_view_form").id, "form"],
                ],
                "domain": domain,
                "context": {
                    "search_default_groupby_category_id": 1,
                },
                "target": "current",
            }
        return self._merge_action_context(action, {"wf_open_target": "current"})


    def workflow_approval_request_action_to_review_category(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model_name,
            'view_mode': 'list,form,kanban',
            "name": self.name,
            "domain": [("category_id", "in", self.ids)],
        }

    @api.model
    def retrieve_dashboard_header_data(self):
        """
        Dashboard counters for large category sets.
        Uses request-level aggregated queries instead of per-category loops.
        """
        filter_key = self.env.context.get("filter") or ""
        base_domain = self._get_count_domain_for_approval_request(filter_key)
        waiting_domain = self._get_dashboard_waiting_scope_domain(filter_key)
        Request = self.env["workflow.base.approval.request"]
        done_states = self._done_state_values()

        all_count = Request.search_count(base_domain)
        tosubmit_count = Request.search_count(base_domain + [('state', '=', 'new')])
        waiting_count = Request.search_count(waiting_domain + [('state', '=', 'waiting')])
        reviewed_count = Request.search_count(self._get_dashboard_to_review_domain())
        completed_count = Request.search_count(base_domain + [('state', 'in', done_states)])

        categories = self.search([])
        waiting_groups = Request._read_group(
            waiting_domain + [('state', '=', 'waiting')],
            ['category_id'],
            ['__count'],
        )
        waiting_category_count = len([cat for cat, _count in waiting_groups if cat])
        department_groups = self._read_group(
            [('id', 'in', categories.ids), ('department_id', '!=', False)],
            ['department_id'],
            ['__count'],
        )
        top_departments = [
            {
                "name": dept.display_name,
                "count": count,
                "count_display": self._format_compact_count(count),
            }
            for dept, count in sorted(
                [(dept, count) for dept, count in department_groups if dept],
                key=lambda item: item[1],
                reverse=True,
            )[:8]
        ]

        return {
            "all_count": all_count,
            "tosubmit_count": tosubmit_count,
            "waiting_count": waiting_count,
            "reviewed_count": reviewed_count,
            "completed_count": completed_count,
            "all_count_display": self._format_compact_count(all_count),
            "tosubmit_count_display": self._format_compact_count(tosubmit_count),
            "waiting_count_display": self._format_compact_count(waiting_count),
            "reviewed_count_display": self._format_compact_count(reviewed_count),
            "completed_count_display": self._format_compact_count(completed_count),
            "category_count": len(categories),
            "department_count": len(categories.mapped('department_id')),
            "waiting_category_count": waiting_category_count,
            "category_count_display": self._format_compact_count(len(categories)),
            "department_count_display": self._format_compact_count(len(categories.mapped('department_id'))),
            "waiting_category_count_display": self._format_compact_count(waiting_category_count),
            "top_departments": top_departments,
        }

    
    @api.model
    def action_total_click_handler(self):
        print("hello")
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model_name,
            'view_mode': "list,graph"
        }



    @api.depends('version_ids')
    def _compute_is_child(self):
        """Compute whether this category is a child category in the workflow map."""
        Map = self.env['workflow.category.version.meta.task.workflow.map']
        
        for category in self:
            # Collect all version IDs belonging to this category
            version_ids = category.version_ids.ids

            if not version_ids:
                category.is_child = False
                continue

            # Check if any mapping references these versions as called_workflow_id
            exist = Map.search_count([('called_workflow_id', 'in', version_ids)], limit=1)

            category.is_child = bool(exist)

    def action_open_dryrun_wizard(self):
        """Open a persisted dry-run wizard so nested input dialogs have a parent."""
        self.ensure_one()
        version = self.active_version_id
        if not version:
            raise UserError(_("Please activate a workflow version before running dry run."))
        wizard = self.env["workflow.dryrun.wizard"].sudo().create(
            {
                "category_id": self.id,
                "version_id": version.id,
                "simulated_user_id": self.env.user.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Workflow Dry Run"),
            "res_model": "workflow.dryrun.wizard",
            "res_id": wizard.id,
            "views": [(self.env.ref("workflow_engine.view_workflow_dryrun_wizard_form").id, "form")],
            "view_mode": "form",
            "view_id": self.env.ref("workflow_engine.view_workflow_dryrun_wizard_form").id,
            "target": "new",
            "context": {
                **dict(self.env.context or {}),
                "active_model": "workflow.dryrun.wizard",
                "active_id": wizard.id,
                "default_wizard_id": wizard.id,
            },
        }
