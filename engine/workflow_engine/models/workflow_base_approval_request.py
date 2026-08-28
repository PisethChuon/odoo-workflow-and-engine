import logging
import re
import requests
from datetime import datetime, timezone
from lxml import html
from odoo import api, Command, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.mail import email_normalize
from odoo.tools.safe_eval import safe_eval
from odoo.addons.workflow_engine.utils.util import RequestDataContext, EmployeeType
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE
from odoo.addons.workflow_engine.utils.util import EmployeeType
from markupsafe import Markup

_logger = logging.getLogger(__name__)

class ApprovalBaseRequest(models.Model):
    """
    \
    This is the base model for approval request, 
    which will be inherited by different approval request models. 
    It contains all common fields and computed methods for approval request.
    """
    _name = 'workflow.base.approval.request'
    _description = 'Approval Base Request'
    _order = 'name'
    _mail_post_access = 'read'
    _check_company_auto = True
    _inherit = ['mail.thread', 'mail.activity.mixin','html.field.history.mixin', 'portal.mixin', 'approval.base.mixin']

    @api.model
    def _workflow_history_allowed_base_request_ids(self):
        if not self.env.context.get("workflow_history_mode"):
            return []

        source_base_id = self.env.context.get("workflow_history_source_base_id")
        try:
            source_base_id = int(source_base_id or 0)
        except (TypeError, ValueError):
            source_base_id = 0
        if not source_base_id:
            return []

        source_request = self.sudo().browse(source_base_id).exists()
        if not source_request:
            return []

        child_model_name = (source_request.res_model_name or "").strip()
        if not child_model_name or child_model_name not in self.env:
            return [source_request.id]

        child_model = self.env[child_model_name].with_context(self.env.context)
        allowed_child_ids = child_model._workflow_history_effective_allowed_record_ids(
            source_request=source_request
        )
        if not allowed_child_ids:
            return [source_request.id]

        child_records = self.env[child_model_name].sudo().browse(allowed_child_ids).exists()
        allowed_base_ids = set(child_records.mapped("x_approval_base_id").ids)
        allowed_base_ids.add(source_request.id)
        return sorted(allowed_base_ids)

    def unlink(self):
        self._workflow_cleanup_force_transition_wizards_for_unlink()
        if self and self._workflow_should_archive_on_unlink():
            self._workflow_archive_on_unlink()
            return True
        return super().unlink()

    active = fields.Boolean(default=True, index=True, copy=False)
    attachment_number = fields.Integer('Number of Attachments', compute='_compute_attachment_number')
    name = fields.Char(string="Folio", tracking=True)
    note = fields.Html(string='Request Note', sanitize_attributes=False)
    category_id = fields.Many2one('workflow.approval.category', string="Category", required=True)
    version_id = fields.Many2one('workflow.approval.category.version', string='Active Version', compute="_compute_version_id", store=True)
    workflow_category_label = fields.Char(
        string="Workflow Category Label",
        compute="_compute_workflow_reference_labels",
        store=False,
    )
    workflow_version_label = fields.Char(
        string="Workflow Version Label",
        compute="_compute_workflow_reference_labels",
        store=False,
    )
    res_model_id = fields.Many2one(related='version_id.res_model_id', store=True)
    res_model_name = fields.Char(related='version_id.res_model_name')
    current_node_id = fields.Char("Current BPMN Node ID")
    previous_node_id = fields.Char("Previous BPMN Node ID")
    next_node_id = fields.Char("Next BPMN Node ID")
    active_branch_node_ids = fields.Json(
        string="Active Branch Nodes",
        default=list,
        copy=False,
        help="Runtime branch node ids that are currently active in parallel/inclusive split mode.",
    )
    branch_gateway_node_id = fields.Char("Branch Gateway Node ID", copy=False)
    branch_join_node_id = fields.Char("Branch Join Node ID", copy=False)
    branch_mode = fields.Selection(
        [("parallel", "Parallel"), ("inclusive", "Inclusive")],
        string="Branch Mode",
        copy=False,
    )
    current_activity_name = fields.Char("Activity Name", tracking=True)
    previous_activity_name = fields.Char("Previous Activity")
    next_activity_name = fields.Char("Next Activity")
    wf_is_blocked = fields.Boolean(
        string="Workflow Blocked",
        default=False,
        copy=False,
        tracking=True,
        help="True when workflow cannot continue because no approver/assignee was resolved for the current stage.",
    )
    wf_block_reason = fields.Char(
        string="Block Reason",
        copy=False,
        tracking=True,
    )
    wf_block_badge = fields.Char(
        string="Block Status",
        compute="_compute_wf_block_badge",
        store=False,
    )
    branch_progress_summary = fields.Char(
        string="Branch Progress",
        compute="_compute_review_header_fields",
        store=False,
    )
    branch_active_count = fields.Integer(
        string="Active Branches",
        compute="_compute_review_header_fields",
        store=False,
    )
    next_action_label = fields.Char(
        string="Next Action",
        compute="_compute_review_header_fields",
        store=False,
    )
    pending_approver_summary = fields.Char(
        string="Pending Activity",
        compute="_compute_review_header_fields",
        store=False,
    )
    latest_transition_summary = fields.Char(
        string="Latest Transition",
        compute="_compute_review_header_fields",
        store=False,
    )
    category_image = fields.Binary(related='category_id.image')
    approver_ids = fields.One2many('workflow.approval.approver', 'request_id', string="Approvers", bypass_search_access=True)
    user_ids = fields.Many2many('res.users', string="Users", compute='_compute_approver_user_ids', readonly=True)
    current_iteration_no = fields.Integer(
        string="Current Iteration",
        default=1,
        help="Current workflow cycle number used to group submission/rework loops.",
    )
    company_id = fields.Many2one(
        string='Company', related='category_id.company_id',
        store=True, readonly=True, index=True)
    
    date = fields.Datetime(string="Date")
    date_start = fields.Datetime(string="Date start")
    date_end = fields.Datetime(string="Date end")
    
    # Request owner
    request_owner_id = fields.Many2one('res.users', string="Request Owner", 
                                       check_company=True, domain="[('company_ids', 'in', company_id), ('wf_hide_from_workflow_picker', '=', False)]", default=lambda self: self.env.user)
    request_owner_emp_id = fields.Many2one(string="Employee", related='request_owner_id.employee_id', store=True)
    request_owner_emp_type = fields.Selection(EmployeeType.selection(), compute="_compute_employee_type", store=True)
    request_owner_ext_phone = fields.Char(string="Requestor Extension", related="request_owner_emp_id.x_ext_phone", store=True)
    request_owner_emp_code = fields.Char(string="Requestor Code", related="request_owner_emp_id.x_emp_code", store=True)
    request_owner_emp_name = fields.Char(string="Requestor Name", related="request_owner_emp_id.name", store=True)
    request_owner_position = fields.Char(string="Requestor Position", related="request_owner_id.wf_request_owner_position", store=False)
    change_request_owner = fields.Boolean(string='Can Change Request Owner', compute='_compute_has_access_to_request')
    request_owner_department = fields.Many2one(string="Department", related="request_owner_emp_id.department_id", store=True)
    request_owner_department_name = fields.Char(string="Requestor Department", related="request_owner_department.name", store=False)
    request_owner_department_code = fields.Char(string="Department Code", related="request_owner_department.code", store=False)

    request_owner_gender = fields.Selection(string="Request Owner Gender", related="request_owner_emp_id.sex", store=True)
    request_owner_age = fields.Char(string="Request Owner Age", compute="_compute_request_owner_age", store=True)
    
    # Creator
    create_uid = fields.Many2one('res.users', string="Create by", default=lambda self: self.env.user, readonly=True)
    creator_emp = fields.Many2one(string="Creator Employee", related="create_uid.employee_id")
    creator_emp_code = fields.Char(string="Creator Emp Code", related='creator_emp.x_emp_code', store=True)
    manager_id = fields.Many2one(string="Creator Manager Employee", related='creator_emp.parent_id', readonly=True, store=True)
    manager_user_id = fields.Many2one(string="Manager", related='manager_id.user_id', readonly=True, store=True) 

    next_is_end_event = fields.Boolean(string="Next Is End Event", readonly=True)
    is_finished = fields.Boolean(string="Is Finished", readonly=True, compute='_compute_is_finished', store=False)

    required_fields = fields.Json(compute="_compute_dynamic_fields", store=False,)
    readonly_fields = fields.Json(compute="_compute_dynamic_fields", store=False,)
    invisible_fields = fields.Json(compute="_compute_dynamic_fields", store=False)

    has_access_to_request = fields.Boolean(string="Has Access To Request", compute="_compute_has_access_to_request")
    
    attachment_ids = fields.One2many(comodel_name='ir.attachment', inverse_name='res_id',
                                     domain=lambda self: [('res_model', '=', self._name)], string='Attachments')
    file_attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        compute='_compute_file_attachment_ids',
        string='Files',
        help='Unified attachment list linked to this workflow request and its business form record.',
    )

    requirer_document = fields.Selection(related="category_id.requirer_document")
    approval_minimum = fields.Integer(related="category_id.approval_minimum")
    approval_type = fields.Selection(related="category_id.approval_type")
    approver_sequence = fields.Boolean(related="category_id.approver_sequence")
    automated_sequence = fields.Boolean(related="category_id.automated_sequence")

    visible_buttons = fields.Json(string="Visible BPMN Buttons", compute="_compute_visible_buttons", store=False)
    
    # owner of the request, can be creator or owner, or both
    owner_user_id = fields.Many2one('res.users', compute='_compute_owner_user_id', store=True)

    owner_user_ids = fields.One2many('workflow.approval.approver', 'request_id', 
                        string="Approver Owner", check_company=True, domain=lambda self: [('is_owner','=',True)])
    
    # Approvers
    to_approve_user_ids = fields.One2many('workflow.approval.approver', 'request_id', string="Approvers Reviewer", 
                                   check_company=True, domain=lambda self: [('status','=','new')])
    
    to_approve_res_user_ids = fields.One2many('res.users', compute='_compute_to_approve_res_user_ids', store=False)

    already_approved_user_ids = fields.One2many('workflow.approval.approver', 'request_id', string="Approvers Already",
                                   check_company=True, domain=lambda self: [('status','!=','new'), ('is_owner','!=',True)])

    comment = fields.Text(string='Comment', tracking=True)

    activity_history = fields.One2many('workflow.approval.approver', compute='_compute_activity_history', string='Activity History')

    is_user_has_permission = fields.Boolean(compute='_compute_is_user_has_permission', store=False)
    is_user_can_delegate = fields.Boolean(compute='_compute_is_user_can_delegate', store=False)

    bpmn_xml = fields.Text(string='BPMN XML', compute='_compute_bpmn_xml', store=True)

    #==========================================
    # ALL STATES
    #==========================================
    request_status = fields.Selection([
        ('new', 'To Submit'),
        ('pending', 'Submitted'),
        ('done', 'Done'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancelled', 'Cancelled'),
        ('auto_cancelled', 'Auto Cancelled'),
    ], default="new", compute="_compute_request_status",
        store=True, index=True, tracking=True,
        group_expand=True)
    
    """
    state is the workflow stage to be shown at status bar, it is static for any state.
    done means request is informationally finished for normal users while remaining
    open for workflow admins to continue controlled manual workflow work.
    """
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'To Submit'),
        ('waiting', 'Waiting Approval'),
        ('done', 'Done'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('auto_cancelled', 'Auto Cancelled'),
        ('refused', 'Refused'),
        ('auto_approved', 'Auto Approved'),
    ], string='Workflow Stage',
        copy=False,
        default='draft',
        index=True,
        readonly=True,
        tracking=True,
        help="* Draft (draft): The request is not saved yet.\n"
             "* To Submit (new): The request is saved but not yet submitted.\n"
             "* Waiting Approval (waiting): The request was already submitted and waiting for the approver to take action.\n"
             "* Done (done): The request is informationally done for normal users but can remain open for workflow admins to continue manual workflow work.\n"
             "* Completed (completed): The request was completed (completed, refused, cancelled, auto_cancelled).\n"
             "* Cancelled: The request was cancelled.\n"
             "* Auto Cancelled (auto_cancelled): The request was cancelled automatically by the system.\n"
             "* Refused (refused): The request was refused.\n"
             "* Auto Approved (auto_approved): The request was auto-approved."
        )
    
    """
    user_status varies from user to user.
    for example:
    - for approver, it is 'To Approve'
    - for requestor, it is 'Waiting'

    we need this status to show:
    - all requests a manager used to approved
    - all pending requests
    """
    user_status = fields.Selection([
        ('new', 'New'),
        ('pending', 'To Approve'),
        ('waiting', 'Waiting'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancelled', 'Cancelled'),
        ('closed', 'Closed'),
        ('auto_cancelled', 'Auto Cancelled')],
    compute="_compute_user_status")

    previous_node_ids = fields.Json(compute="_compute_previous_node_ids", store=False)
    
    # vanchhai 2024-06-24: for sub process
    # parent_id = fields.Char(string="Parents", store=True)
    parent_id = fields.Many2one(
        comodel_name="workflow.base.approval.request",  # <-- replace with the actual model name
        string="Parent Request",
        ondelete="cascade",  # optional, decide how to handle delete
        index=True,
    )
    parent_meta_node_id = fields.Char(
        string="Parent Meta Node ID",
        help="The parent workflow node id that spawned this sub workflow.",
        copy=False,
        index=True,
    )
    
    child_ids = fields.One2many(
        comodel_name="workflow.base.approval.request",
        inverse_name="parent_id",
        string="Child Requests",
    )
    execution_mode = fields.Char(string="Execution Mode", store=True)
    form_view_ref = fields.Char(
        string="Form View Ref",
        compute="_compute_form_view_ref",
        store=False
    )

    is_admin = fields.Boolean(compute='_compute_is_admin', store=False)
    is_workflow_admin = fields.Boolean(string="Workflow Admin", compute='_compute_is_workflow_admin', store=False, default=False)

    approver_emails = fields.Char(string="Approver Email", store=False, compute='_compute_approver_emails')
    last_approver_id = fields.Many2one('workflow.approval.approver', compute="_compute_last_approver", store=True, string="Last Approver")
    
    # This is hollow field, it holds no value.
    # The base view needs this field.
    x_approval_base_id = fields.Many2one('workflow.base.approval.request', store=False)
    
    # because there is a cron that will run to update age_after_completed every day, that makes the default write_date
    # meaningless for other fields.
    updated_date = fields.Datetime(string="Last Update On Parent", compute="_compute_updated_date", store=True)

    # activity_change_date = fields.Datetime(string="State Change Date", compute="_compute_activity_change_date", store=True)
    is_an_approver = fields.Boolean(string="is an approver?", store=False, compute="_compute_is_login_an_approver")

    submit_date = fields.Datetime(string="Submitted Date")
    
    created_by_legacy = fields.Char(
        string="Legacy Created By K2",
        readonly=True,
        copy=False,
    )
    
    def init(self):
        self.env.cr.execute(
            """
            UPDATE workflow_base_approval_request
               SET current_iteration_no = 1
             WHERE current_iteration_no IS NULL OR current_iteration_no <= 0
            """
        )
        # Keep legacy rows consistent with terminal-state semantics after upgrades.
        self.env.cr.execute(
            """
            UPDATE workflow_base_approval_request
               SET request_status = CASE
                    WHEN state = 'done' THEN 'done'
                    WHEN state IN ('cancelled', 'auto_cancelled', 'refused') THEN state
                    WHEN state IN ('completed', 'auto_approved') THEN 'approved'
                    ELSE request_status
                   END
             WHERE state IN ('done', 'cancelled', 'auto_cancelled', 'refused', 'completed', 'auto_approved')
               AND COALESCE(request_status, '') <> CASE
                    WHEN state = 'done' THEN 'done'
                    WHEN state IN ('cancelled', 'auto_cancelled', 'refused') THEN state
                    WHEN state IN ('completed', 'auto_approved') THEN 'approved'
                    ELSE COALESCE(request_status, '')
                   END
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_category_state_id_idx
                ON workflow_base_approval_request (category_id, state, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_state_category_id_idx
                ON workflow_base_approval_request (state, category_id, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_owner_state_id_idx
                ON workflow_base_approval_request (request_owner_id, state, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_category_owner_state_id_idx
                ON workflow_base_approval_request (category_id, request_owner_id, state, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_creator_state_id_idx
                ON workflow_base_approval_request (create_uid, state, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_manager_state_id_idx
                ON workflow_base_approval_request (manager_user_id, state, id)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_active_category_state_idx
                ON workflow_base_approval_request (active, category_id, state)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_list_order_idx
                ON workflow_base_approval_request (updated_date DESC, create_date DESC, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_category_list_order_idx
                ON workflow_base_approval_request (category_id, updated_date DESC, create_date DESC, id DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_base_request_node_iteration_state_idx
                ON workflow_base_approval_request (current_node_id, current_iteration_no, state)
            """
        )

    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        active_test=True,
        bypass_access=False,
    ):
        """
        Hide requests that belong to archived categories by default.
        Keep an explicit context escape hatch for technical/audit views.
        """
        effective_domain = fields.Domain(domain)
        if self.env.context.get("workflow_history_mode"):
            allowed_ids = self._workflow_history_allowed_base_request_ids()
            effective_domain &= fields.Domain("id", "in", allowed_ids or [0])
        if not self.env.context.get("wf_include_archived_categories"):
            effective_domain &= fields.Domain("category_id.active", "=", True)
        if self.env.context.get("workflow_history_mode"):
            return super(ApprovalBaseRequest, self.sudo())._search(
                effective_domain,
                offset=offset,
                limit=limit,
                order=order,
                active_test=active_test,
                bypass_access=bypass_access,
            )
        return super()._search(
            effective_domain,
            offset=offset,
            limit=limit,
            order=order,
            active_test=active_test,
            bypass_access=bypass_access,
        )

    @api.model_create_multi
    def create(self, vals_list):
        self._workflow_check_create_access_from_vals_list(vals_list)
        records = super().create(vals_list)
        records._workflow_force_created_uid_on_records()
        records._sync_blocked_state_from_approvers()
        records._notify_mini_update_bus(reason="request_created")
        return records

    def write(self, vals):
        if (
            vals.get("state")
            and vals.get("state") not in {"waiting"}
            and "wf_is_blocked" not in vals
            and "wf_block_reason" not in vals
        ):
            vals = dict(vals)
            vals["wf_is_blocked"] = False
            vals["wf_block_reason"] = False

        tracked_keys = {
            "state",
            "request_status",
            "current_node_id",
            "previous_node_id",
            "current_activity_name",
            "previous_activity_name",
            "current_iteration_no",
            "next_node_id",
            "next_activity_name",
            "comment",
            "completed_date",
            "active_branch_node_ids",
            "branch_gateway_node_id",
            "branch_join_node_id",
            "branch_mode",
            "wf_is_blocked",
            "wf_block_reason",
        }
        should_notify = bool(set(vals.keys()) & tracked_keys)
        res = super().write(vals)
        if not self.env.context.get("wf_skip_block_sync"):
            self._sync_blocked_state_from_approvers()
        if should_notify:
            self._notify_mini_update_bus(reason="request_updated")
        return res

    def _is_sticky_unassigned_stage_block(self):
        self.ensure_one()
        if not (self.wf_is_blocked and self.wf_block_reason):
            return False
        adapter_service = self.env["workflow.engine.legacy.adapter.service"]
        return bool(adapter_service.is_unassigned_stage_reason(self.wf_block_reason))

    def _sync_blocked_state_from_approvers(self):
        """Keep blocked flag consistent when no pending approvers exist on current node.

        Callers that are mid-transition (approver rows not yet fully committed)
        must suppress this sync via ``wf_skip_block_sync=True`` in context.
        The guard lives here — not only in write() — so it applies to direct
        callers such as ``workflow.approval.approver.write/create/unlink``.
        """
        if self.env.context.get("wf_skip_block_sync"):
            return
        open_statuses = {"new", "pending", "waiting"}
        for rec in self:
            sticky_unassigned_block = rec._is_sticky_unassigned_stage_block()

            if rec.state not in {"new", "waiting"}:
                if rec.wf_is_blocked or rec.wf_block_reason:
                    rec.sudo().with_context(wf_skip_block_sync=True).write({
                        "wf_is_blocked": False,
                        "wf_block_reason": False,
                    })
                continue

            if sticky_unassigned_block:
                continue

            if not rec.current_node_id:
                if rec.wf_is_blocked or rec.wf_block_reason:
                    rec.sudo().with_context(wf_skip_block_sync=True).write({
                        "wf_is_blocked": False,
                        "wf_block_reason": False,
                    })
                continue

            if not rec._is_approver_driven_current_node():
                if rec.wf_is_blocked or rec.wf_block_reason:
                    rec.sudo().with_context(wf_skip_block_sync=True).write({
                        "wf_is_blocked": False,
                        "wf_block_reason": False,
                    })
                continue

            current_rows = rec.approver_ids.filtered(
                lambda row: row.current_meta_node_id == rec.current_node_id
            )
            has_open = bool(current_rows.filtered(lambda row: row.status in open_statuses))
            if has_open:
                if rec.wf_is_blocked or rec.wf_block_reason:
                    rec.sudo().with_context(wf_skip_block_sync=True).write({
                        "wf_is_blocked": False,
                        "wf_block_reason": False,
                    })
                continue

            # All approvers for this stage have approved — the workflow is in the
            # middle of advancing to the next node.  This is not a blocked state;
            # the transition will clear the rows.  Setting a block here would
            # create a spurious chatter entry that gets immediately reversed.
            has_approved = bool(current_rows.filtered(lambda row: row.status == "approved"))
            if has_approved:
                if rec.wf_is_blocked or rec.wf_block_reason:
                    rec.sudo().with_context(wf_skip_block_sync=True).write({
                        "wf_is_blocked": False,
                        "wf_block_reason": False,
                    })
                continue

            reason = _(
                "Workflow is blocked at stage %s — no pending approver is assigned."
            ) % (rec.current_activity_name or rec.current_node_id or _("Unknown"))
            if (not rec.wf_is_blocked) or rec.wf_block_reason != reason:
                rec.sudo().with_context(wf_skip_block_sync=True).write({
                    "wf_is_blocked": True,
                    "wf_block_reason": reason,
                })

    def _is_approver_driven_current_node(self):
        """True only for stages that are expected to have approver assignments."""
        self.ensure_one()
        if not self.version_id or not self.current_node_id:
            return False
        meta_task = self.version_id.meta_task_ids.filtered(
            lambda task: task.node_id == self.current_node_id
        )[:1]
        if not meta_task:
            return False
        if meta_task.is_end_node:
            return False
        # Submission stages have no pre-assigned approvers — the submitter creates
        # their own row at the moment they act, so the sync should never block here.
        node_name = (meta_task.name or "").lower()
        if "submit" in node_name or "submission" in node_name:
            return False

        approver_node_types = {
            NODE_TYPE["USER_TASK"],
            NODE_TYPE["MANUAL_TASK"],
            NODE_TYPE["TASK"],
        }
        if meta_task.node_type in approver_node_types:
            return True
        return bool(meta_task.approval_group_link_ids)

    def _mini_update_bus_channel(self):
        self.ensure_one()
        return f"workflow_approval.request_{self.id}"

    def _mini_update_bus_enabled(self):
        self.ensure_one()
        return bool(self.category_id and self.category_id.enable_mini_bus_updates)

    def _build_mini_update_snapshot(self):
        self.ensure_one()
        approver_rows = self.approver_ids.sorted(key=lambda r: ((r.create_date or fields.Datetime.now()), r.id))
        serialized_approvers = []
        for row in approver_rows:
            serialized_approvers.append(
                {
                    "id": row.id,
                    "current_meta_id": [row.current_meta_id.id, row.current_meta_id.name or ""]
                    if row.current_meta_id
                    else False,
                    "previous_meta_id": [row.previous_meta_id.id, row.previous_meta_id.name or ""]
                    if row.previous_meta_id
                    else False,
                    "current_meta_node_id": row.current_meta_node_id or "",
                    "user_id": [row.user_id.id, row.user_id.name or ""] if row.user_id else False,
                    "status": row.status or "",
                    "user_decision": row.user_decision or "",
                    "required": bool(row.required),
                }
            )
        return {
            "request_id": self.id,
            "state": self.state or "",
            "request_status": self.request_status or "",
            "current_node_id": self.current_node_id or "",
            "previous_node_id": self.previous_node_id or "",
            "previous_node_ids": self.previous_node_ids or [],
            "active_branch_node_ids": self.active_branch_node_ids or [],
            "branch_gateway_node_id": self.branch_gateway_node_id or "",
            "branch_join_node_id": self.branch_join_node_id or "",
            "branch_mode": self.branch_mode or "",
            "current_activity_name": self.current_activity_name or "",
            "previous_activity_name": self.previous_activity_name or "",
            "current_iteration_no": self.current_iteration_no or 1,
            "wf_is_blocked": bool(self.wf_is_blocked),
            "wf_block_reason": self.wf_block_reason or "",
            "approver_rows": serialized_approvers,
            "updated_at": fields.Datetime.now(),
        }

    def _notify_mini_update_bus(self, reason=False):
        if self._workflow_notifications_suppressed():
            return
        Bus = self.env["bus.bus"].sudo()
        for rec in self:
            if not rec.exists() or not rec._mini_update_bus_enabled():
                continue
            payload = {
                "request_id": rec.id,
                "current_node_id": rec.current_node_id or "",
                "state": rec.state or "",
                "request_status": rec.request_status or "",
                "wf_is_blocked": bool(rec.wf_is_blocked),
                "wf_block_reason": rec.wf_block_reason or "",
                "reason": reason or "request_updated",
                "updated_at": fields.Datetime.now(),
            }
            Bus._sendone(
                rec._mini_update_bus_channel(),
                "workflow_approval.request_mini_update",
                payload,
            )

    @api.model
    def workflow_get_mini_update_snapshot(self, request_id):
        request = self.with_context(active_test=False).browse(request_id).exists()
        if not request:
            return {}
        request.check_access_rights("read")
        request.check_access_rule("read")
        return request._build_mini_update_snapshot()
    
    @api.depends("request_owner_id")
    def _compute_request_owner_age(self):
        now = fields.Datetime.now()
        for rec in self:
            birthday = rec.request_owner_emp_id.birthday
            if birthday:
                age = now.year - birthday.year
                if (now.month, now.day) < (birthday.month, birthday.day):
                    age -= 1
                rec.request_owner_age = age
            
    @api.depends_context('uid')
    def _compute_is_login_an_approver(self):
        for rec in self:
            rec.is_an_approver= self.is_login_an_approver_in_current_activity(rec)

    def _get_transition_delegate_record(self):
        """Resolve the concrete request model (approval.child.mixin) for transition actions."""
        self.ensure_one()
        if not isinstance(self.id, int) or self.id <= 0:
            return self

        # Read model metadata in sudo to avoid false negatives when approvers cannot read
        # workflow version internals but are still allowed to act on the request.
        model_name = self.sudo().res_model_name or self.res_model_name
        if not model_name or model_name == self._name:
            return self

        if model_name not in self.env:
            return self

        model = self.env[model_name]
        if 'x_approval_base_id' not in model._fields:
            return self

        # First try in current user context.
        target = model.search([('x_approval_base_id', '=', self.id)], limit=1)
        if target:
            return target

        # Fallback:
        # some approvers can act on workflow requests but cannot "search" child records
        # due model-specific record rules. Resolve the child id in sudo, then re-browse in
        # current user context so downstream permission checks still execute as the actor.
        sudo_target = model.sudo().search([('x_approval_base_id', '=', self.id)], limit=1)
        if not sudo_target:
            return self
        return model.browse(sudo_target.id)

    def _resolve_base_request_record(self):
        self.ensure_one()
        return self

    def _run_engine(self, form_data=None, meta_action_id=None, re_assign_approvals=True):
        """Delegate engine execution from the base request to the concrete form.

        The base request is the reporting/runtime parent. Real transitions must
        run on the concrete child model because that record owns the business
        fields, form data, field policy, and model-specific access rules.
        """
        self.ensure_one()
        target = self._get_transition_delegate_record()
        if target._name != self._name and callable(getattr(target, "_run_engine", None)):
            return target._run_engine(
                form_data=form_data,
                meta_action_id=meta_action_id,
                re_assign_approvals=re_assign_approvals,
            )
        raise UserError(_("Workflow transitions require a concrete workflow form record."))

    def _get_transition_access_block_reason(self, target=None):
        """Return a user-facing reason when transition target is not accessible."""
        self.ensure_one()
        if not self.id and self.state in ("draft", "new"):
            return False
        target = target or self._get_transition_delegate_record()
        if target._name == self._name or not hasattr(type(target), "action_do_transition"):
            return _("Transition is not available on this request model.")

        try:
            target.check_access("read")
        except AccessError:
            model_label = target._description or target._name
            return _(
                "You are assigned as approver, but access rules prevent access to '%(model)s'. "
                "Please contact Workflow Admin to grant access or reassign this approval."
            ) % {"model": model_label}

        return False

    def action_do_transition(self, button, show_dialog=True):
        """
        Compatibility entrypoint when UI invokes transitions from workflow.base.approval.request.
        Delegates to the concrete child request model where engine methods live.
        """
        self.ensure_one()
        target = self._get_transition_delegate_record()
        block_reason = self._get_transition_access_block_reason(target=target)
        if block_reason:
            raise UserError(block_reason)

        if target._name != self._name and hasattr(type(target), "action_do_transition"):
            try:
                return target.action_do_transition(button, show_dialog=show_dialog)
            except AccessError:
                raise UserError(self._get_transition_access_block_reason(target=target))

        raise UserError(_("Transition is not available on this request model."))

    def action_repair_stale_approvers(self):
        if not (
            self.env.user.has_group("base.group_system")
            or self.env.user.has_group("workflow_engine.group_workflow_technical_admin")
        ):
            raise AccessError(
                _("Only Odoo Admin or Workflow Technical Admin can repair stale approvers.")
            )

        selected_requests = self.exists()
        if not selected_requests:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Repair Stale Approvers"),
                    "message": _("No requests were selected."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        repaired_rows = self.env["workflow.approval.approver"].sudo()._repair_stale_open_assignment_rows(
            requests=selected_requests.sudo(),
            notify=True,
            sync_blocked=True,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Repair Stale Approvers"),
                "message": _(
                    "Processed %(request_count)s request(s). Closed %(row_count)s stale approver row(s)."
                )
                % {
                    "request_count": len(selected_requests),
                    "row_count": len(repaired_rows),
                },
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
    
    @api.depends('current_node_id', 'previous_node_id', 'next_node_id', 'current_activity_name', 
                 'state', 'previous_activity_name', 'next_activity_name', 'approver_ids', 'comment')
    def _compute_updated_date(self):
        for rec in self:
            rec.updated_date = fields.Datetime.now()

    @api.depends("wf_is_blocked")
    def _compute_wf_block_badge(self):
        for rec in self:
            rec.wf_block_badge = _("Blocked") if rec.wf_is_blocked else False

    def _compute_is_workflow_admin(self):
        is_workflow_admin = self.env.user.has_group('workflow_engine.group_workflow_approval_admin')
        for record in self:
            record.is_workflow_admin = is_workflow_admin

    @staticmethod
    def _is_terminal_workflow_state(state):
        return (state or "") in {"completed", "cancelled", "auto_cancelled", "refused", "auto_approved"}

    @staticmethod
    def _workflow_terminal_state_to_request_status(state):
        state_value = (state or "").strip()
        if state_value == "done":
            return "done"
        if state_value in {"cancelled", "auto_cancelled", "refused"}:
            return state_value
        if state_value in {"completed", "auto_approved"}:
            return "approved"
        return False
    
    @api.depends(
        'approver_ids',
        'approver_ids.user_id',
        'approver_ids.user_decision',
        'approver_ids.activity_event_at',
        'approver_ids.event_order',
        'approver_ids.decision_history_kind',
        'approver_ids.status',
    )
    def _compute_last_approver(self):
        for rec in self:
            decision_rows = rec.approver_ids.filtered(
                lambda a: bool((a.user_decision or "").strip()) and bool(a.user_id)
            ).sorted(
                key=lambda a: (
                    a.activity_event_at or a.write_date or a.create_date or fields.Datetime.now(),
                    a._decision_history_sort_rank(),
                    a.event_order or 0,
                    a.id,
                ),
                reverse=True,
            )
            rec.last_approver_id = decision_rows[:1] or False

    @api.depends('to_approve_user_ids', 'state')
    def _compute_to_approve_res_user_ids(self):
        empty_users = self.env['res.users']
        for rec in self:
            if rec.state == 'done':
                rec.to_approve_res_user_ids = empty_users
                continue
            rec.to_approve_res_user_ids = rec.to_approve_user_ids.user_id.filtered(lambda u: u)

    @api.depends('approver_ids')
    def _compute_approver_emails(self):
        for rec in self:
            emails = rec.approver_ids.filtered(lambda a: a.status == 'new').mapped('user_id.email')
            rec.approver_emails = ",".join(filter(None, set(emails)))

    @api.depends_context('uid')
    def _compute_is_admin(self):
        for rec in self:
            rec.is_admin = self.env.user.has_group('base.group_system')
    
    def _compute_form_view_ref(self):
        for rec in self:
            # If the record is a custom model (x_clearance_hr, x_clearance_it, etc.)
            if rec._name != "workflow.base.approval.request":
                rec.form_view_ref = f"{rec._module}.view_form_{rec._name.replace('.', '_')}"
            else:
                # Fallback: base form view XML ID
                rec.form_view_ref = f"{rec._module}.view_form_{rec._name.replace('.', '_')}"
                
    @api.depends('approver_ids')
    def _compute_previous_node_ids(self):
        """
        compute the previous node ids
        """
        for request in self:
            if request.approver_ids:
                valid_meta_ids = set(request.version_id.meta_task_ids.ids) if request.version_id else set()
                non_processed_list = [
                    approver.current_meta_id.node_id
                    for approver in request.approver_ids
                    if approver.current_meta_id
                    and (not valid_meta_ids or approver.current_meta_id.id in valid_meta_ids)
                    and approver.current_meta_id.node_id != request.current_node_id
                ]
                # remove duplicates
                request.previous_node_ids = list(dict.fromkeys(non_processed_list))
            else:
                request.previous_node_ids = []
        
    @api.depends("current_node_id")
    def _compute_bpmn_xml(self):
        for rec in self:
            active_version = rec.version_id.filtered(lambda v: v.is_active)[:1]
            rec.bpmn_xml = active_version.bpmn_xml if active_version else False

    @api.depends('request_owner_id')
    def _compute_employee_type(self):
        for rec in self:
            group_name = rec.request_owner_emp_id.employee_group_id.name
            rec.request_owner_emp_type = EmployeeType.EMPLOYEE.value if group_name in ['',False,'Employee'] else EmployeeType.NON_EMPLOYEE.value

    @api.depends(
        'approver_ids',
        'approver_ids.user_decision',
        'approver_ids.activity_event_at',
        'approver_ids.event_order',
        'approver_ids.decision_history_kind',
    )
    def _compute_activity_history(self):
        for request in self:
            approvers = request.approver_ids
            filtered_approvers = approvers.filtered(lambda a: a.user_decision).sorted(
                key=lambda a: (
                    a.activity_event_at or a.write_date or a.create_date or fields.Datetime.now(),
                    a._decision_history_sort_rank(),
                    a.event_order or 0,
                    a.id,
                ),
                reverse=True,
            )
            request.activity_history = filtered_approvers   

    @api.depends('create_uid')
    def _compute_owner_user_id(self):
        # take only owner
        for rec in self:
            rec.owner_user_id = rec.create_uid

    # @api.depends('create_uid')
    # def _compute_creator_emp_code(self):
    #     for rec in self:
    #         emp = rec.create_uid.employee_id.sudo()
    #         rec.creator_emp_code = emp.x_emp_code if emp and emp.x_emp_code else False

    # @api.depends('request_owner_id')
    # def _compute_request_owner_emp_code(self):
    #     for rec in self:
    #         emp = rec.request_owner_id.employee_id.sudo()
    #         rec.request_owner_emp_code = emp.x_emp_code if emp and emp.x_emp_code else False

    # @api.depends('request_owner_id')
    # def _compute_request_owner_ext_phone(self):
    #     for rec in self:
    #         emp = rec.request_owner_id.employee_id.sudo()
    #         rec.request_owner_ext_phone = emp.x_ext_phone if emp and emp.x_ext_phone else False
    
    @api.depends_context('uid')
    @api.depends('state')
    def _compute_is_finished(self):
        for rec in self:
            """
            we consider as a finished state if it is not draft, new or waiting.
            And the login user has no permission.
            """
            if rec._is_terminal_workflow_state(rec.state):
                rec.is_finished = True
                continue
            rec.is_finished = not rec.check_if_user_has_permission(rec)

    def _get_button_config(
        self,
        action,
        actor_node_id,
        meta_task,
        transition_block_reason,
        target_record=False,
        snapshot_values=False,
        user=False,
    ):
        """
        Helper to construct the button configuration dictionary for a specific workflow action.
        """
        self.ensure_one()
        actor_user = user or self.env.user
        required_payload = self._workflow_button_required_field_payload(
            action,
            meta_task,
            target_record=target_record or self,
            task_node_id=actor_node_id,
            snapshot_values=snapshot_values,
            user=actor_user,
        )

        # 2. Check for permission blocks
        permission_block_reason = ""
        if not self._workflow_can_execute_actor_node(actor_node_id, user=actor_user):
            permission_block_reason = _("You are not an active approver for this stage.")

        disabled_reason = transition_block_reason or permission_block_reason

        # 3. Build the payload
        return {
            'label': self._workflow_get_action_label(action),
            'css_class': action.attr_class,
            'icon_class': action.icon_class or '',
            'action_button_label': action.action_button_label or '',
            'action_key': action.name or action.attr_label or '',
            'required_fields': required_payload["required_fields"],
            'meta_action_id': action.id,
            'meta_node_id': action.node_id,
            'source_node_id': actor_node_id or action.source_id,
            'target_node_id': action.target_id,
            'all_require_fields': required_payload["all_require_fields"],
            'has_conditional_required_fields': required_payload["has_conditional_required_fields"],
            'conditional_required_fields': required_payload["conditional_required_fields"],
            'disabled': bool(disabled_reason),
            'disabled_reason': disabled_reason or '',
        }

    @api.model
    def get_button_object(self, request, action_name, activity_name):
        """
        Get the button dict based on action name and activity name.
        This is used for the API call from frontend when user click the button, to get the button info and do transition.
        """
        action = self.env['workflow.category.version.meta.task.action'].sudo().search([
            ('name', '=', action_name),
            ('source_name', '=', activity_name),
            ('version_id.id', '=', request.version_id.id),
        ], limit=1)
        if not action:
            return False
        
        actor_node_id = request._workflow_get_actor_primary_node_id(user=self.env.user)

        meta_task = request.version_id.meta_task_ids.filtered(lambda m: m.node_id == actor_node_id) or \
                        request.version_id.meta_task_ids[:1]
        transition_block_reason = request._get_transition_access_block_reason()
        
        target_record = request
        if hasattr(request, "_get_transition_delegate_record"):
            try:
                delegate_record = request._get_transition_delegate_record()
                if delegate_record and delegate_record.exists():
                    target_record = delegate_record
            except Exception:
                pass
        return request._get_button_config(
            action,
            actor_node_id,
            meta_task,
            transition_block_reason,
            target_record=target_record,
            user=self.env.user,
        )

    def _to_plain_text(self, body):
        if not body:
            return ""
        try:
            return html.fromstring(str(body)).text_content().strip()
        except Exception:
            return str(body).strip()

    def _workflow_is_message_notification_node_type(self, node_type):
        return node_type in {
            NODE_TYPE["END_EVENT_WITH_MESSAGE"],
            NODE_TYPE["INTERMEDIATE_THROW_EVENT_WITH_MESSAGE"],
        }

    def _resolve_send_task_email_template(self, meta_task):
        if not meta_task or (
            meta_task.node_type != "sendTask"
            and not self._workflow_is_message_notification_node_type(meta_task.node_type)
        ):
            return self.env["mail.template"]
        return (
            meta_task.notification_email_template_id
            or meta_task.email_template_external_id
            or self.env["mail.template"]
        )

    def _workflow_email_addresses_from_users(self, users):
        addresses = set()
        for user in users or self.env["res.users"]:
            email = user.partner_id.email if user.partner_id else user.email
            normalized = email_normalize(email or "")
            if normalized:
                addresses.add(normalized)
        return sorted(addresses)

    def _workflow_split_raw_email_addresses(self, raw_emails):
        addresses = set()
        for token in re.split(r"[,;\n\r]+", raw_emails or ""):
            normalized = email_normalize((token or "").strip())
            if normalized:
                addresses.add(normalized)
        return sorted(addresses)

    def _workflow_resolve_action_email_recipient_line_details(
        self,
        line,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        service = self.env["workflow.engine.assignment.domain.service"]
        detail = {
            "header": line.header or "to",
            "source": line.source or "send_task",
            "domain": (line.domain or "").strip(),
            "node_ref": (line.node_ref or "").strip(),
            "node_user_type": line.node_user_type or "assigned",
            "approval_group_ids": line.approval_group_ids.ids,
            "group_ids": line.group_ids.ids,
            "configured_user_ids": line.user_ids.ids,
            "resolved_user_ids": [],
            "resolved_emails": [],
            "config_error": False,
            "error_message": "",
        }
        if line.source == "direct":
            detail["resolved_emails"] = self._workflow_split_raw_email_addresses(line.raw_emails)
            return detail
        if line.source == "send_task":
            detail["resolved_user_ids"] = send_task_recipients.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(send_task_recipients)
            return detail
        if line.source == "specific_users":
            users = line.user_ids.sudo()
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "approval_group_users":
            users = line.approval_group_ids.sudo().mapped("user_ids")
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "group_users":
            group_user_field = "user_ids" if "user_ids" in self.env["res.groups"]._fields else "users"
            users = line.group_ids.sudo().mapped(group_user_field)
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "node_users":
            users = service.node_approver_users(
                request_record,
                (line.node_ref or "").strip(),
                user_type=line.node_user_type or "assigned",
            )
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "domain":
            users, domain_details = service.eval_routing_user_domain(
                service._memoized_all_active_non_portal_users(memo),
                detail["domain"],
                request_record=request_record,
                memo=memo,
                return_details=True,
            )
            detail["config_error"] = bool(domain_details.get("config_error"))
            detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        return detail

    def _workflow_resolve_action_email_recipient_line(
        self,
        line,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        return self._workflow_resolve_action_email_recipient_line_details(
            line,
            send_task_recipients,
            request_record,
            meta_task,
            memo=memo,
        )["resolved_emails"]

    def _workflow_build_action_email_values(self, action, send_task_recipients, request_record, meta_task):
        return self._workflow_build_action_email_payload(
            action,
            send_task_recipients,
            request_record,
            meta_task,
        )["email_values"]

    def _workflow_build_action_email_payload(
        self,
        action,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        recipient_lines = action.email_recipient_line_ids.sudo() if action else self.env["workflow.approval.action.email.recipient"]
        if not recipient_lines:
            to_addresses = self._workflow_email_addresses_from_users(send_task_recipients)
            return {
                "email_values": {"email_to": ",".join(to_addresses)} if to_addresses else None,
                "headers": {"to": to_addresses, "cc": [], "bcc": []},
                "recipient_lines": [
                    {
                        "header": "to",
                        "source": "send_task",
                        "domain": "",
                        "node_ref": "",
                        "node_user_type": "assigned",
                        "approval_group_ids": [],
                        "group_ids": [],
                        "configured_user_ids": [],
                        "resolved_user_ids": send_task_recipients.ids,
                        "resolved_emails": to_addresses,
                        "config_error": False,
                        "error_message": "",
                    }
                ],
            }

        headers = {"to": set(), "cc": set(), "bcc": set()}
        resolved_lines = []
        for line in recipient_lines:
            line_details = self._workflow_resolve_action_email_recipient_line_details(
                line,
                send_task_recipients,
                request_record,
                meta_task,
                memo=memo,
            )
            resolved_lines.append(line_details)
            for address in line_details["resolved_emails"]:
                headers.setdefault(line_details["header"], set()).add(address)
        email_values = {}
        if headers["to"]:
            email_values["email_to"] = ",".join(sorted(headers["to"]))
        if headers["cc"]:
            email_values["email_cc"] = ",".join(sorted(headers["cc"]))
        if headers["bcc"]:
            email_values["headers"] = repr({"Bcc": sorted(headers["bcc"])})
        return {
            "email_values": email_values or None,
            "headers": {key: sorted(values) for key, values in headers.items()},
            "recipient_lines": resolved_lines,
        }

    def _resolve_send_task_delivery_mode(self, meta_task):
        mode = getattr(meta_task, "notification_delivery_mode", False)
        if mode:
            return mode
        return "channels" if meta_task.sudo().activity_type_ids else "email"

    def _workflow_empty_notification_audit(self, delivery_mode, meta_task):
        return {
            "delivery_mode": delivery_mode or "",
            "node_id": meta_task.node_id if meta_task else "",
            "node_name": meta_task.name if meta_task else "",
            "entries": [],
        }

    def _send_task_template_email(self, meta_task, recipients, memo=False):
        if not meta_task:
            return None
        suppress_notifications = self._workflow_notifications_suppressed()
        audit = self._workflow_empty_notification_audit("email", meta_task)
        for rec in self:
            entry = {
                "status": "",
                "record_id": rec.id,
                "template_id": False,
                "template_name": "",
                "recipient_user_ids": recipients.ids,
                "recipient_emails": [],
            }
            if suppress_notifications:
                entry["status"] = "suppressed"
                audit["entries"].append(entry)
                continue
            task_email_template = rec._resolve_send_task_email_template(meta_task).sudo()
            if not task_email_template:
                entry["status"] = "skipped_no_template"
                audit["entries"].append(entry)
                continue
            entry["template_id"] = task_email_template.id
            entry["template_name"] = task_email_template.name or ""
            emails = rec._workflow_email_addresses_from_users(recipients)
            entry["recipient_emails"] = emails
            if not emails:
                entry["status"] = "skipped_no_recipients"
                audit["entries"].append(entry)
                continue
            sent = rec._workflow_safe_send_mail_template(
                template=task_email_template,
                render_record=rec,
                email_values={"email_to": ",".join(emails)},
                warning_label=meta_task.name or meta_task.node_id or _("send task notification"),
            )
            if sent:
                rec._workflow_grant_notification_read_scopes(
                    recipients,
                    reason="notification_recipient:%s" % (meta_task.node_id or meta_task.name or "send_task"),
                    request_record=rec,
                )
                rec._workflow_safe_message_post(
                    body=f"Task email sent: {task_email_template.name}",
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
                entry["status"] = "sent"
            else:
                entry["status"] = "failed"
            audit["entries"].append(entry)
        return {"notification_audit": audit}

    def _execute_send_task_log(self, meta_task):
        if not meta_task or self._workflow_notifications_suppressed():
            return None
        for rec in self:
            template = meta_task.activity_message_template
            body = False
            if template:
                body = template.sudo()._render_field("body_html", rec.ids).get(rec.id)
                body = Markup(body or "")
            rec._workflow_safe_message_post(
                body=body or f"Send task logged: {meta_task.name or meta_task.node_id}",
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        return None

    def _execute_workflow_actions(self, meta_task, recipients=False, allow_template_fallback=True, memo=False):
        if not meta_task:
            return None
        recipients = recipients or self.env["res.users"]
        suppress_notifications = self._workflow_notifications_suppressed()
        action_pool = meta_task.sudo().activity_type_ids.sudo()
        partner_ids = recipients.mapped("partner_id").ids if recipients else []
        guard_cache = {}
        audit = self._workflow_empty_notification_audit("channels", meta_task)
        for rec in self:
            template = meta_task.activity_message_template
            html_template = False
            if template:
                html_template = template.sudo()._render_field("body_html", rec.ids).get(rec.id)
                html_template = Markup(html_template or "")
            plain_template = rec._to_plain_text(html_template)
            task_email_template = rec._resolve_send_task_email_template(meta_task).sudo()
            if allow_template_fallback and not action_pool and task_email_template:
                entry = {
                    "action_id": False,
                    "action_name": task_email_template.name or "",
                    "action_type": "email",
                    "record_id": rec.id,
                    "guard_domain": "",
                    "guard_matched": True,
                    "status": "",
                    "template_id": task_email_template.id,
                    "template_name": task_email_template.name or "",
                    "recipient_lines": [],
                    "resolved_user_ids": recipients.ids,
                    "resolved_emails": [],
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                }
                if suppress_notifications:
                    entry["status"] = "suppressed"
                    audit["entries"].append(entry)
                    continue
                emails = sorted(
                    {
                        u.partner_id.email
                        for u in recipients
                        if u.partner_id and u.partner_id.email
                    }
                )
                entry["resolved_emails"] = emails
                entry["email_to"] = emails
                if emails:
                    task_email_template.send_mail(
                        rec.id,
                        force_send=False,
                        email_values={"email_to": ",".join(emails)},
                    )
                    rec._workflow_grant_notification_read_scopes(
                        recipients,
                        reason="notification_recipient:%s" % (meta_task.node_id or meta_task.name or "send_task"),
                        request_record=rec,
                    )
                    rec._workflow_safe_message_post(
                        body=f"Task email sent: {task_email_template.name}",
                        message_type="notification",
                        subtype_xmlid="mail.mt_note",
                    )
                    entry["status"] = "sent"
                else:
                    entry["status"] = "skipped_no_recipients"
                audit["entries"].append(entry)
                continue
            for action in action_pool:
                audit_entry = {
                    "action_id": action.id,
                    "action_name": action.name or "",
                    "action_type": action.action_type or "",
                    "record_id": rec.id,
                    "guard_domain": action.domain or "",
                    "guard_matched": True,
                    "status": "",
                    "template_id": False,
                    "template_name": "",
                    "recipient_lines": [],
                    "resolved_user_ids": [],
                    "resolved_emails": [],
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                }
                if action.domain:
                    cache_key = (rec.id, action.id, action.domain)
                    if cache_key not in guard_cache:
                        guard_cache[cache_key] = rec.check_domain(action.domain, default=False)
                    audit_entry["guard_matched"] = bool(guard_cache[cache_key])
                    if not guard_cache[cache_key]:
                        audit_entry["status"] = "skipped_guard"
                        audit["entries"].append(audit_entry)
                        continue
                try:
                    match action.action_type:
                        case "log":
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            rec._workflow_safe_message_post(
                                body=html_template or f"Action executed: {action.name}",
                                message_type="notification",
                                subtype_xmlid="mail.mt_note",
                            )
                            audit_entry["status"] = "sent"
                        case "email":
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            email_template = action.email_template_id or task_email_template
                            if not email_template:
                                audit_entry["status"] = "skipped_no_template"
                                audit["entries"].append(audit_entry)
                                continue
                            audit_entry["template_id"] = email_template.id
                            audit_entry["template_name"] = email_template.name or ""
                            email_payload = rec._workflow_build_action_email_payload(
                                action,
                                recipients,
                                rec,
                                meta_task,
                                memo=memo,
                            )
                            audit_entry["recipient_lines"] = email_payload["recipient_lines"]
                            audit_entry["resolved_user_ids"] = sorted(
                                {
                                    user_id
                                    for line_details in email_payload["recipient_lines"]
                                    for user_id in (line_details.get("resolved_user_ids") or [])
                                }
                            )
                            audit_entry["resolved_emails"] = sorted(
                                {
                                    address
                                    for line_details in email_payload["recipient_lines"]
                                    for address in (line_details.get("resolved_emails") or [])
                                }
                            )
                            audit_entry["email_to"] = email_payload["headers"].get("to", [])
                            audit_entry["email_cc"] = email_payload["headers"].get("cc", [])
                            audit_entry["email_bcc"] = email_payload["headers"].get("bcc", [])
                            email_values = email_payload["email_values"]
                            if not email_values:
                                audit_entry["status"] = "skipped_no_recipients"
                                audit["entries"].append(audit_entry)
                                continue
                            sent = email_template.sudo().send_mail(
                                rec.id,
                                force_send=False,
                                email_values=email_values,
                            )
                            if sent:
                                recipient_users = self.env["res.users"].browse(
                                    audit_entry["resolved_user_ids"]
                                )
                                rec._workflow_grant_notification_read_scopes(
                                    recipient_users,
                                    reason="notification_recipient:%s"
                                    % (
                                        getattr(action, "node_id", False)
                                        or action.name
                                        or meta_task.node_id
                                        or meta_task.name
                                        or "email_action"
                                    ),
                                    request_record=rec,
                                )
                                rec._workflow_safe_message_post(
                                    body=f"Action email sent: {action.name}",
                                    message_type="notification",
                                    subtype_xmlid="mail.mt_note",
                                )
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "failed"
                        case "sms":
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            sms_body = action.message_body or plain_template or action.name or ""
                            if hasattr(rec, "_message_sms") and sms_body and partner_ids:
                                rec._message_sms(body=sms_body, partner_ids=partner_ids)
                                audit_entry["status"] = "sent"
                            else:
                                rec._workflow_safe_message_post(
                                    body=f"SMS action skipped (missing sms support/recipients/body): {action.name}",
                                    message_type="notification",
                                    subtype_xmlid="mail.mt_note",
                                )
                                audit_entry["status"] = "skipped_no_recipients"
                        case "telegram":
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            endpoint = action.telegram_webhook_url or action.webhook_url
                            if endpoint:
                                payload = {
                                    "model": rec._name,
                                    "res_id": rec.id,
                                    "action_name": action.name,
                                    "message": action.message_body or plain_template or action.name,
                                    "recipient_ids": recipients.ids if recipients else [],
                                    "recipient_logins": recipients.mapped("login") if recipients else [],
                                }
                                requests.post(endpoint, json=payload, timeout=8)
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case "webhook":
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            if action.webhook_url:
                                requests.post(
                                    action.webhook_url,
                                    json={
                                        "model": rec._name,
                                        "res_id": rec.id,
                                        "action_name": action.name,
                                        "recipient_ids": recipients.ids if recipients else [],
                                    },
                                    timeout=8,
                                )
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case "server_action":
                            if action.server_action_id:
                                action.server_action_id.sudo().with_context(
                                    active_model=rec._name,
                                    active_id=rec.id,
                                    active_ids=[rec.id],
                                    active_domain=[("id", "=", rec.id)],
                                ).run()
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case _:
                            audit_entry["status"] = "sent"
                    if action.code:
                        safe_eval(
                            action.code,
                            {
                                "record": rec,
                                "self": self,
                                "env": self.env,
                                "recipients": recipients,
                            },
                            mode="exec",
                        )
                        audit_entry["status"] = audit_entry["status"] or "sent"
                except Exception as exc:
                    audit_entry["status"] = "failed"
                    audit_entry["error_message"] = str(exc)
                    rec._workflow_safe_message_post(
                        body=f"Action failed ({action.name}): {exc}",
                        message_type="notification",
                        subtype_xmlid="mail.mt_note",
                    )
                audit["entries"].append(audit_entry)
        return {"notification_audit": audit}

    def _handle_send_task(self, meta_task, meta_action):
        if not meta_task:
            return None
        memo = {}
        recipients = self._resolve_notification_recipients(meta_task, memo=memo)
        delivery_mode = self._resolve_send_task_delivery_mode(meta_task)
        if delivery_mode == "log":
            return self._execute_send_task_log(meta_task)
        if delivery_mode == "channels":
            return self._execute_workflow_actions(
                meta_task,
                recipients=recipients,
                allow_template_fallback=False,
                memo=memo,
            )
        return self._send_task_template_email(meta_task, recipients, memo=memo)

    def _handle_script_task(self, meta_task, meta_action):
        if not meta_task:
            return None
        return self._execute_workflow_actions(meta_task)

    def _workflow_execute_runtime_actions(self, engine, node, meta_task, automation_instance=False, meta_action=False):
        self.ensure_one()
        node_type = engine.get_element_type(node)
        if node_type == NODE_TYPE["SEND_TASK"] or self._workflow_is_message_notification_node_type(node_type):
            return self._handle_send_task(meta_task, meta_action)
        if node_type == NODE_TYPE["SCRIPT_TASK"]:
            return self._handle_script_task(meta_task, meta_action)
        if node_type == NODE_TYPE["SERVICE_TASK"]:
            return self._execute_workflow_actions(meta_task)
        return None

    def _get_form_data(self):
        return {
            f.name: self[f.name]
            for f in self._fields.values()
            if not f.compute and not f.related and f.store and f.name.startswith('x_')
        }

    def _workflow_schedule_retry_instance(self, automation_instance, error_message):
        self.ensure_one()
        retry_count = (automation_instance.retry_count or 0) + 1
        if automation_instance.max_retries and retry_count > automation_instance.max_retries:
            automation_instance.mark_failed(error_message, retry_count=retry_count)
            return
        automation_instance.schedule_retry(error_message)

    def _workflow_should_execute_meta_task(self, meta_task):
        self.ensure_one()
        condition_domain = (meta_task.automation_condition_domain or "").strip() if meta_task else ""
        if not meta_task or not condition_domain or condition_domain in ("[]", "[ ]"):
            return True
        return self.check_domain(condition_domain, default=False)

    def _workflow_active_node_ids_for_runtime_instance(self, base_request):
        active_nodes = set(base_request.active_branch_node_ids or [])
        if base_request.current_node_id:
            active_nodes.add(base_request.current_node_id)
        return active_nodes

    def _workflow_skip_or_rearm_runtime_instance(self, automation_instance, schedule_provider, reason, *, meta_task=False, meta_action=False):
        self.ensure_one()
        if not automation_instance.recurrence_enabled or not schedule_provider:
            automation_instance.mark_cancelled(reason)
            return False
        recurrence_plan = automation_instance._prepare_recurrence_after_success(
            meta_task=meta_task,
            meta_action=meta_action,
            execution_succeeded=False,
        )
        next_due_at = recurrence_plan.get("next_due_at")
        if not next_due_at:
            automation_instance.mark_cancelled(reason)
            automation_instance.sudo().write({"run_count": recurrence_plan.get("completed_runs") or automation_instance.run_count})
            return False
        automation_instance.mark_success(
            {"skipped": True, "reason": reason},
            run_count=recurrence_plan.get("completed_runs"),
            next_due_at=next_due_at,
        )
        return True

    def _workflow_get_next_elements(self, engine, node, form_data=None, evaluate_conditions=True):
        self.ensure_one()
        if node is None:
            return []

        node_type = engine.get_element_type(node)
        if node_type != NODE_TYPE["CONDITIONAL_EVENT_DEFINITION"]:
            return engine.get_next_elements(node, form_data=form_data, evaluate_conditions=evaluate_conditions)

        if not evaluate_conditions:
            return engine.get_next_elements(node, form_data=form_data, evaluate_conditions=False)

        meta_task = self._resolve_meta_task_for_node(node.attrib.get("id"), node.attrib.get("name"))
        condition_domain = meta_task.automation_condition_domain if meta_task else False
        return self._workflow_get_conditional_event_next_elements(
            engine,
            node,
            condition_domain=condition_domain,
        )

    def _workflow_execute_timer_reminder_path(self, engine, timer_node, meta_action, automation_instance):
        self.ensure_one()
        executed = []
        queue = list(self._workflow_get_next_elements(engine, timer_node, form_data=self._get_form_data()))
        if not queue and timer_node is not None and self.version_id:
            timer_node_id = timer_node.attrib.get("id")
            outgoing_actions = self.env["workflow.category.version.meta.task.action"].sudo().search([
                ("version_id", "=", self.version_id.id),
                ("source_id", "=", timer_node_id),
            ])
            queue = [
                target
                for target in (engine.get_element_by_id(action.target_id) for action in outgoing_actions)
                if target is not None
            ]
        if not queue and timer_node is not None:
            outgoing_flow_ids = [
                child.text.strip()
                for child in list(timer_node)
                if child.tag.endswith("outgoing") and child.text and child.text.strip()
            ]
            for flow_id in outgoing_flow_ids:
                flow = engine.get_element_by_id(flow_id)
                target_id = flow.attrib.get("targetRef") if flow is not None else False
                target = engine.get_element_by_id(target_id) if target_id else None
                if target is not None:
                    queue.append(target)
        visited = set()
        hops = 0
        while queue:
            current = queue.pop(0)
            hops += 1
            if hops > 60:
                raise UserError(_("Timer reminder path exceeded maximum hops."))
            if current is None:
                continue
            node_id = current.attrib.get("id")
            if not node_id or node_id in visited:
                continue
            visited.add(node_id)
            current_type = engine.get_element_type(current)
            meta_task = self._resolve_meta_task_for_node(node_id, current.attrib.get("name"))
            effective_type = (meta_task.node_type if meta_task else "") or current_type
            if self._workflow_is_message_notification_node_type(effective_type):
                if meta_task and not self._workflow_should_execute_meta_task(meta_task):
                    continue
                self._workflow_execute_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    automation_instance=automation_instance,
                    meta_action=meta_action,
                )
                executed.append(node_id)
                if engine.is_end_event(current):
                    continue
            if engine.is_end_event(current) or effective_type in [
                NODE_TYPE["USER_TASK"],
                NODE_TYPE["MANUAL_TASK"],
                NODE_TYPE["TASK"],
                NODE_TYPE["CALL_ACTIVITY"],
            ]:
                continue
            if effective_type == NODE_TYPE["SERVICE_TASK"] and meta_task and meta_task.service_behavior != "executor":
                continue
            if effective_type in [NODE_TYPE["SEND_TASK"], NODE_TYPE["SCRIPT_TASK"], NODE_TYPE["SERVICE_TASK"]]:
                if meta_task and not self._workflow_should_execute_meta_task(meta_task):
                    continue
                self._workflow_execute_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    automation_instance=automation_instance,
                    meta_action=meta_action,
                )
                executed.append(node_id)
            queue.extend(self._workflow_get_next_elements(engine, current, form_data=self._get_form_data()))
        if not executed and timer_node is not None and self.version_id:
            timer_node_id = timer_node.attrib.get("id")
            outgoing_actions = self.env["workflow.category.version.meta.task.action"].sudo().search([
                ("version_id", "=", self.version_id.id),
                ("source_id", "=", timer_node_id),
            ])
            for action in outgoing_actions:
                meta_task = self._resolve_meta_task_for_node(action.target_id, action.target_name)
                if not meta_task or meta_task.node_type not in [
                    NODE_TYPE["SEND_TASK"],
                    NODE_TYPE["SCRIPT_TASK"],
                    NODE_TYPE["SERVICE_TASK"],
                    NODE_TYPE["END_EVENT_WITH_MESSAGE"],
                    NODE_TYPE["INTERMEDIATE_THROW_EVENT_WITH_MESSAGE"],
                ]:
                    continue
                if not self._workflow_should_execute_meta_task(meta_task):
                    continue
                target = engine.get_element_by_id(action.target_id)
                if target is not None:
                    self._workflow_execute_runtime_actions(
                        engine,
                        target,
                        meta_task,
                        automation_instance=automation_instance,
                        meta_action=meta_action,
                    )
                elif meta_task.node_type == NODE_TYPE["SEND_TASK"] or self._workflow_is_message_notification_node_type(meta_task.node_type):
                    self._handle_send_task(meta_task, meta_action)
                elif meta_task.node_type == NODE_TYPE["SCRIPT_TASK"]:
                    self._handle_script_task(meta_task, meta_action)
                else:
                    self._execute_workflow_actions(meta_task)
                executed.append(action.target_id)
        return executed

    def _workflow_run_runtime_automation_instance(self, automation_instance):
        self.ensure_one()
        if not automation_instance:
            return False
        automation_instance = automation_instance.sudo()
        base_request = self._resolve_base_request_record()
        if not base_request or not self.version_id:
            automation_instance.mark_cancelled(_("Workflow request is no longer available."))
            return False

        payload = automation_instance.payload_json or {}
        execution_mode = payload.get("execution_mode") or ""
        engine = BpmnEngine(self.version_id.bpmn_xml)
        if execution_mode == "timer_transition":
            active_nodes = self._workflow_active_node_ids_for_runtime_instance(base_request)
            branch_node_id = automation_instance.branch_node_id or payload.get("source_node_id")
            if branch_node_id and branch_node_id not in active_nodes:
                automation_instance.mark_cancelled(_("Timer superseded by a manual transition."))
                return False
            node = engine.get_element_by_id(automation_instance.node_id)
            if node is None:
                automation_instance.mark_failed(
                    _("Runtime automation node '%s' was not found.") % (automation_instance.node_id or ""))
                return False
            meta_action = self._workflow_find_meta_action_for_transition(
                automation_instance.node_id,
                source_node_id=branch_node_id,
            )
            if meta_action and meta_action.auto_action_condition:
                if not self.check_domain(meta_action.auto_action_condition, default=False):
                    return self._workflow_skip_or_rearm_runtime_instance(
                        automation_instance,
                        meta_action,
                        _("Timer condition domain did not match. Execution skipped."),
                        meta_action=meta_action,
                    )
            if meta_action and not self._workflow_action_execution_guard_matches(meta_action):
                return self._workflow_skip_or_rearm_runtime_instance(
                    automation_instance,
                    meta_action,
                    _("Runtime Domain Guard did not match. Execution skipped."),
                    meta_action=meta_action,
                )
            automation_instance.mark_running()
            try:
                executed_node_ids = self._workflow_execute_timer_reminder_path(
                    engine,
                    node,
                    meta_action,
                    automation_instance,
                )
                if executed_node_ids or (meta_action and meta_action.automation_trigger_mode == "reminder"):
                    recurrence_plan = automation_instance._prepare_recurrence_after_success(meta_action=meta_action)
                    automation_instance.mark_success(
                        {
                            "transition_node_id": automation_instance.node_id,
                            "trigger_mode": "reminder",
                            "executed_node_ids": executed_node_ids,
                        },
                        run_count=recurrence_plan.get("completed_runs"),
                        next_due_at=recurrence_plan.get("next_due_at"),
                    )
                    return True
                automation_instance.mark_failed(
                    _("Base workflow requests require a concrete delegate record for timer transitions.")
                )
                return False
            except Exception as error:
                if automation_instance.failure_policy == "retry":
                    self._workflow_schedule_retry_instance(automation_instance, str(error))
                    return False
                if automation_instance.failure_policy == "ignore":
                    automation_instance.mark_failed(str(error))
                    return False
                automation_instance.mark_failed(str(error))
                raise

        active_nodes = self._workflow_active_node_ids_for_runtime_instance(base_request)
        source_node_id = automation_instance.branch_node_id or payload.get("source_node_id")
        if source_node_id and source_node_id not in active_nodes:
            automation_instance.mark_cancelled(_("Automation superseded because the source activity is no longer active."))
            return False
        meta_task = self._resolve_meta_task_for_node(automation_instance.node_id, automation_instance.node_name)
        if meta_task and not self._workflow_should_execute_meta_task(meta_task):
            return self._workflow_skip_or_rearm_runtime_instance(
                automation_instance,
                meta_task,
                _("Automation condition does not match. Execution skipped."),
                meta_task=meta_task,
            )

        node = engine.get_element_by_id(automation_instance.node_id)
        if node is None:
            automation_instance.mark_failed(
                _("Runtime automation node '%s' was not found.") % (automation_instance.node_id or ""))
            return False

        automation_instance.mark_running()
        try:
            execution_result = self._workflow_execute_runtime_actions(
                engine,
                node,
                meta_task,
                automation_instance=automation_instance,
            )
            recurrence_plan = automation_instance._prepare_recurrence_after_success(meta_task)
            result_json = {"node_id": node.attrib.get("id"), "node_type": engine.get_element_type(node)}
            if isinstance(execution_result, dict):
                result_json.update(execution_result)
            automation_instance.mark_success(
                result_json,
                run_count=recurrence_plan.get("completed_runs"),
                next_due_at=recurrence_plan.get("next_due_at"),
            )
            return True
        except Exception as error:
            if automation_instance.failure_policy == "retry":
                self._workflow_schedule_retry_instance(automation_instance, str(error))
                return False
            if automation_instance.failure_policy == "ignore":
                automation_instance.mark_failed(str(error))
                return False
            automation_instance.mark_failed(str(error))
            raise

    @api.model
    def action_find_existing_requests_by_request_owner_id(self, category_id, request_owner_id):
        if not category_id or not request_owner_id:
            return []

        category = self.env["workflow.approval.category"].browse(category_id)
        if not category:
            raise ValidationError(_("Approval category id = %s is not found") % category_id)
        if category.allowed_duplicate:
            return []

        search_domain = [
            ("category_id", "=", category.id),
            ("request_owner_id", "=", request_owner_id),
            ("state", "not in", ["completed", "cancelled", "auto_cancelled", "refused", "auto_approved"]),
        ]
        if self.id and isinstance(self.id, int):
            search_domain.append(("id", "!=", self.id))

        existing_requests = self.env["workflow.base.approval.request"].search(search_domain, order="id desc")
        if not existing_requests:
            return []

        block_domain = (category.allow_duplicate_domain or "").strip()
        if block_domain and block_domain not in ("[]", "[ ]"):
            matching_requests = self.env["workflow.base.approval.request"]
            for request in existing_requests:
                eval_record = request
                if hasattr(request, "_get_transition_delegate_record"):
                    eval_record = request._get_transition_delegate_record()
                if request.check_domain(
                    block_domain,
                    default=False,
                    target_record=eval_record,
                ):
                    matching_requests |= request
            existing_requests = matching_requests

        return existing_requests.mapped(lambda r: {
            "id": r.id,
            "name": r.name,
            "create_date": r.create_date,
            "create_uid": r.create_uid.name,
        })

    @api.depends_context('uid')
    @api.depends('state', 'current_node_id', 'version_id', 'approver_ids')
    def _compute_visible_buttons(self):
        for request in self:
            buttons = []
            request.visible_buttons = buttons
            
            if request._is_terminal_workflow_state(request.state):
                continue

            actor_node_id = request._workflow_get_actor_primary_node_id(user=self.env.user)
            
            # Check if version exists and has actionable nodes
            if request.version_id and ((actor_node_id and request.version_id) or request.version_id.meta_task_ids):
                meta_task = request.version_id.meta_task_ids.filtered(lambda m: m.node_id == actor_node_id) or \
                            request.version_id.meta_task_ids[:1]
                try:
                    if not request._workflow_can_execute_actor_node(actor_node_id, user=self.env.user):
                        continue
                    
                    transition_block_reason = request._get_transition_access_block_reason()
                    user_actions = request.version_id._get_user_action_by_node_id(actor_node_id)
                    user_actions = self.env[
                        "workflow.engine.permission.service"
                    ].filter_authorized_actions(
                        request,
                        user_actions,
                        user=self.env.user,
                    )
                    if not user_actions:
                        continue
                    
                    # Determine delegation target for matching logic
                    visibility_target = request
                    if hasattr(request, "_get_transition_delegate_record"):
                        try:
                            delegate_record = request._get_transition_delegate_record()
                            if delegate_record and delegate_record.exists():
                                visibility_target = delegate_record
                        except Exception:
                            pass

                    match_actions = request.get_match_user_actions(
                        user_actions,
                        target_record=visibility_target,
                        task_node_id=actor_node_id,
                    )

                    # Use the extracted function to generate button configs
                    for action in match_actions:
                        if not request._workflow_get_action_label(action):
                            continue
                        button_config = request._get_button_config(
                            action,
                            actor_node_id,
                            meta_task,
                            transition_block_reason,
                            target_record=visibility_target,
                            user=self.env.user,
                        )
                        buttons.append(button_config)

                    request.visible_buttons = buttons
                except Exception:
                    request.visible_buttons = []
    
    @api.depends_context('uid')
    @api.depends('state', 'current_node_id')
    def _compute_is_user_has_permission(self):
        for req in self:
            if req._is_terminal_workflow_state(req.state):
                req.is_user_has_permission = False
                continue
            req.is_user_has_permission = self.check_if_user_has_permission(req)

    @api.depends_context('uid')
    @api.depends('state', 'current_node_id')
    def _compute_is_user_can_delegate(self):
        for req in self:
            req.is_user_can_delegate = req.check_if_user_can_delegate(req)

    @api.depends_context('uid')
    @api.depends('state', 'current_node_id', 'version_id', 'to_approve_user_ids')
    def _compute_dynamic_fields(self):
        """
        compute dynamic fields: required_fields, readonly_fields, invisible_fields
        based on meta task.
        """
        field_rule_service = self.env["workflow.engine.field.rule.service"].sudo()
        params = self.env.context.get("params") or {}
        view_id = (
            self.env.context.get("view_id")
            or params.get("view_id")
            or params.get("form_view_id")
            or False
        )
        for request in self:
            required_fields = []
            readonly_fields = []
            invisible_fields = []
            if request.version_id:
                try:
                    target_record = request._get_transition_delegate_record()
                    payload = field_rule_service._build_runtime_state_payload(
                        target_record=target_record,
                        request_record=request._workflow_resolve_request_record(),
                        task_node_id=False,
                        action_key=False,
                        view_id=view_id,
                        user=self.env.user,
                        snapshot_values=None,
                    )
                    required_fields = payload.get("required_fields") or []
                    readonly_fields = payload.get("readonly_fields") or []
                    invisible_fields = payload.get("invisible_fields") or []
                    if not request.check_if_user_has_permission(request):
                        required_fields = []
                except Exception:
                    _logger.debug(
                        "Could not compute workflow dynamic fields for request %s",
                        request.id,
                        exc_info=True,
                    )

            request.required_fields = required_fields
            request.readonly_fields = readonly_fields
            request.invisible_fields = invisible_fields

    @api.depends('approver_ids')
    def _compute_approver_user_ids(self):
        """
        compute the approver id list (res.users)
        """
        for request in self:
            request.user_ids = request.approver_ids.user_id

    @api.depends(
        "state",
        "approver_ids.status",
        "approver_ids.user_id.name",
        "approver_ids.user_decision",
        "approver_ids.activity_flow",
        "approver_ids.iteration_no",
        "approver_ids.current_meta_node_id",
        "active_branch_node_ids",
        "branch_join_node_id",
        "current_node_id",
        "current_iteration_no",
        "next_activity_name",
        "next_is_end_event",
        "visible_buttons",
    )
    @api.depends_context("uid")
    def _compute_review_header_fields(self):
        for request in self:
            request.next_action_label = request._resolve_next_action_label_for_review_header()

            if request._is_terminal_workflow_state(request.state) or request.state == "done":
                request.pending_approver_summary = _("No pending activity")
                request.branch_active_count = 0
                request.branch_progress_summary = "-"
            else:
                current_iteration = request.current_iteration_no or 1
                active_nodes = request.active_branch_node_ids or []
                active_node_set = set(active_nodes)
                if request.current_node_id:
                    active_node_set.add(request.current_node_id)
                open_rows = request.approver_ids.filtered(
                    lambda a: (a.iteration_no or 1) == current_iteration
                    and a.current_meta_node_id in active_node_set
                    and a.status in ("new", "pending", "waiting")
                )
                names = []
                for user_name in open_rows.mapped("user_id.name"):
                    if user_name and user_name not in names:
                        names.append(user_name)
                if len(names) > 3:
                    request.pending_approver_summary = _("%(names)s +%(count)s more", names=", ".join(names[:3]), count=len(names) - 3)
                else:
                    request.pending_approver_summary = ", ".join(names) if names else _("No pending activity")
                request.branch_active_count = len(active_nodes)
                if active_nodes:
                    branch_rows = request.approver_ids.filtered(
                        lambda a: (a.iteration_no or 1) == current_iteration
                        and a.current_meta_node_id in active_node_set
                    )
                    done_nodes = {
                        row.current_meta_node_id
                        for row in branch_rows
                        if row.status in ("approved", "closed", "cancelled", "refused")
                    }
                    done_count = len(done_nodes)
                    total = len(active_nodes)
                    request.branch_progress_summary = _(
                        "%(remaining)s of %(total)s branch(es) remaining",
                        remaining=max(total - done_count, 0),
                        total=total,
                    )
                else:
                    request.branch_progress_summary = "-"

            decision_rows = request.approver_ids.filtered(lambda a: bool((a.user_decision or "").strip()))
            if decision_rows:
                latest_row = decision_rows.sorted(key=lambda r: ((r.create_date or fields.Datetime.now()), r.id), reverse=True)[:1]
                request.latest_transition_summary = latest_row.activity_flow or "-"
            else:
                request.latest_transition_summary = "-"

    @staticmethod
    def _is_terminal_negative_action_label(label):
        text = ((label or "") or "").strip().lower()
        if not text:
            return False
        return any(keyword in text for keyword in ("cancel", "reject", "refuse", "decline"))

    def _get_next_action_label_from_visible_buttons(self):
        self.ensure_one()
        buttons = self.visible_buttons or []
        if not isinstance(buttons, list):
            return False

        labels = []
        for button in buttons:
            if not isinstance(button, dict):
                continue
            label = (
                button.get("action_button_label")
                or button.get("label")
                or button.get("action_key")
                or ""
            )
            label = label.strip()
            if not label:
                continue
            labels.append({
                "label": label,
                "disabled": bool(button.get("disabled")),
            })
        if not labels:
            return False

        enabled_labels = [entry for entry in labels if not entry["disabled"]]
        candidate_pool = enabled_labels or labels
        non_terminal_pool = [
            entry for entry in candidate_pool
            if not ApprovalBaseRequest._is_terminal_negative_action_label(entry["label"])
        ]
        selected_pool = non_terminal_pool or candidate_pool
        return selected_pool[0]["label"] if selected_pool else False

    def _resolve_next_action_label_for_review_header(self):
        self.ensure_one()
        if ApprovalBaseRequest._is_terminal_workflow_state(self.state):
            return "-"
        visible_label = self._get_next_action_label_from_visible_buttons()
        if visible_label:
            return visible_label

        next_activity_name = (self.next_activity_name or "").strip()
        if not next_activity_name:
            return "-"

        if ApprovalBaseRequest._is_terminal_negative_action_label(next_activity_name):
            return "-"
        return next_activity_name

    @api.depends('request_owner_id')
    @api.depends_context('uid')
    def _compute_has_access_to_request(self):
        is_approval_user = self.env.user.has_group('workflow_engine.group_workflow_approval_user')
        self.change_request_owner = is_approval_user
        for request in self:
            request.has_access_to_request = request.request_owner_id == self.env.user and is_approval_user

    @api.depends(
        "attachment_ids",
        "attachment_ids.res_model",
        "attachment_ids.res_id",
        "attachment_ids.create_date",
        "attachment_ids.write_date",
        "res_model_name",
    )
    def _compute_attachment_number(self):
        if not self:
            return

        for rec in self:
            if not isinstance(rec.id, int) or rec.id <= 0:
                rec.attachment_number = 0
                continue
            rec.attachment_number = len(rec._search_linked_attachments())

    @api.depends(
        "attachment_ids",
        "attachment_ids.res_model",
        "attachment_ids.res_id",
        "attachment_ids.create_date",
        "attachment_ids.write_date",
        "res_model_name",
    )
    def _compute_file_attachment_ids(self):
        for rec in self:
            if not isinstance(rec.id, int) or rec.id <= 0:
                rec.file_attachment_ids = self.env["ir.attachment"].browse()
                continue
            rec.file_attachment_ids = rec._search_linked_attachments()

    def _get_attachment_link_targets(self):
        """Return all (res_model, res_id) pairs that can hold files for this workflow request."""
        self.ensure_one()
        targets = set()
        if isinstance(self.id, int) and self.id > 0:
            targets.add((self._name, self.id))

        base_request = self
        if self._name != "workflow.base.approval.request":
            base_request = getattr(self, "x_approval_base_id", False) or self
        if base_request and isinstance(base_request.id, int) and base_request.id > 0:
            targets.add(("workflow.base.approval.request", base_request.id))

        model_name = (base_request.sudo().res_model_name if base_request else "") or (base_request.res_model_name if base_request else "")
        if not model_name or model_name not in self.env:
            return list(targets)

        target_model = self.env[model_name]
        if model_name == self._name and isinstance(self.id, int) and self.id > 0:
            targets.add((self._name, self.id))
            return list(targets)

        if "x_approval_base_id" in target_model._fields and base_request and isinstance(base_request.id, int) and base_request.id > 0:
            child = target_model.sudo().search([("x_approval_base_id", "=", base_request.id)], limit=1)
            if child:
                targets.add((model_name, child.id))
        elif base_request and isinstance(base_request.id, int) and base_request.id > 0:
            targets.add((model_name, base_request.id))
        return list(targets)

    def _search_linked_attachments(self):
        self.ensure_one()
        if not isinstance(self.id, int) or self.id <= 0:
            return self.env["ir.attachment"].browse()
        Attachment = self.env["ir.attachment"]
        records = Attachment.browse()
        for model_name, res_id in self._get_attachment_link_targets():
            if not isinstance(res_id, int) or res_id <= 0:
                continue
            records |= Attachment.search([
                ("res_model", "=", model_name),
                ("res_id", "=", res_id),
            ])
        return records.sorted(key=lambda att: (att.create_date or fields.Datetime.now(), att.id), reverse=True)

    @api.depends("category_id", "category_id.active_version_id")
    def _compute_version_id(self):
        for rec in self:
            rec.version_id = rec.category_id.active_version_id if rec.category_id else False

    @api.depends(
        "category_id",
        "category_id.name",
        "version_id",
        "version_id.name",
        "version_id.title",
        "version_id.category_id",
    )
    def _compute_workflow_reference_labels(self):
        for rec in self:
            category = rec.category_id.sudo() if rec.category_id else self.env["workflow.approval.category"]
            version = rec.version_id.sudo() if rec.version_id else category.active_version_id.sudo()

            category_label = category.display_name or category.name if category else ""
            version_label = version.display_name or version.name if version else ""

            rec.workflow_category_label = category_label or "-"
            rec.workflow_version_label = version_label or "-"
    
    @api.depends_context('uid')
    @api.depends('approver_ids.status')
    def _compute_user_status(self):
        """
        Compute user_status based on the current user's approver records.
        Always assign a value to avoid compute errors.
        """
        current_user = self.env.user
        for approval in self:
            # Default value if no matching approver or no status found
            user_status = False

            # Find approvers belonging to the current user
            matching_approvers = approval.approver_ids.filtered(
                lambda approver: approver.user_id == current_user
            )

            if matching_approvers:
                # You can customize priority if multiple approvers exist
                # (e.g. prefer pending > waiting > new)
                status_priority = {"pending": 3, "waiting": 2, "new": 1}
                sorted_approvers = sorted(
                    matching_approvers,
                    key=lambda a: status_priority.get(a.status, 0),
                    reverse=True,
                )
                selected_approver = sorted_approvers[0]

                # Even if status == 'closed', we still assign it
                user_status = selected_approver.status or False

            # Always assign something, even False
            approval.user_status = user_status

    @api.depends('state', 'approver_ids.status', 'approver_ids.required')
    def _compute_request_status(self):
        for request in self:
            if request.state == "done":
                request.request_status = "done"
                continue
            terminal_status = request._workflow_terminal_state_to_request_status(request.state)
            if terminal_status:
                request.request_status = terminal_status
                continue
            status_lst = request.mapped('approver_ids.status')
            required_approved = all(a.status == 'approved' for a in request.approver_ids.filtered('required'))
            minimal_approver = request.approval_minimum if len(status_lst) >= request.approval_minimum else len(
                status_lst)
            if status_lst:
                if status_lst.count('cancelled'):
                    status = 'cancelled'
                elif status_lst.count('refused'):
                    status = 'refused'
                elif status_lst.count('new'):
                    status = 'new'
                elif status_lst.count('approved') >= minimal_approver and required_approved:
                    status = 'approved'
                else:
                    status = 'pending'
            else:
                status = 'new'
            request.request_status = status

        self.filtered_domain([('request_status', 'in', ['approved', 'refused', 'cancelled', 'auto_cancelled'])]).cancel_activities()
    
    @api.ondelete(at_uninstall=False)
    def unlink_attachments(self):
        for record in self:
            attachment_ids = self.env['ir.attachment'].browse()
            for model_name, res_id in record._get_attachment_link_targets():
                attachment_ids |= self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', model_name),
                    ('res_id', '=', res_id),
                ])
            attachment_ids.unlink()


    def action_open_child(self):
        self.ensure_one()
        target = self.env.context.get("wf_open_target") or "current"
        form_rec = self._get_transition_delegate_record()
        if form_rec and form_rec._name != self._name and isinstance(form_rec.id, int) and form_rec.id > 0:
            child_label = getattr(form_rec, "display_name", False) or getattr(form_rec, "name", False) or self.name
            return {
                "type": "ir.actions.act_window",
                "res_model": form_rec._name,
                "res_id": form_rec.id,
                "views": [[False, "form"]],
                "target": target,
                "name": f"Form: {self.name} / {child_label}",
            }
        # Fallback
        return {
            "type": "ir.actions.act_window",
            "res_model": "workflow.base.approval.request",
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": target,
            "name": f"Form: {self.name}", 
        }
    
