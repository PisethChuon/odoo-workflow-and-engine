# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import secrets
import base64
import hmac
import io
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.sql import table_exists

_logger = logging.getLogger(__name__)

AUTOMATION_ACTION_SELECTION = [
    ("send_email", "Send Email"),
    ("create_activity", "Create Activity"),
    ("call_webhook", "Call Webhook"),
    ("update_fields", "Update Fields"),
    ("enqueue_job", "Enqueue Job"),
    ("transition", "Transition"),
]

AUTOMATION_FAILURE_POLICY_SELECTION = [
    ("ignore", "Ignore"),
    ("retry", "Retry"),
    ("block", "Block"),
]

AUTOMATION_INSTANCE_STATUS_SELECTION = [
    ("new", "New"),
    ("scheduled", "Scheduled"),
    ("running", "Running"),
    ("success", "Success"),
    ("failed", "Failed"),
    ("cancelled", "Cancelled"),
    ("skipped", "Skipped"),
    ("blocked", "Blocked"),
]


class WorkflowRequestTaskInstance(models.Model):
    _name = "workflow.request.task.instance"
    _description = "Workflow Request Task Instance"
    _order = "id desc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    version_id = fields.Many2one(related="request_id.version_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    node_id = fields.Char(required=True, index=True)
    node_name = fields.Char()
    node_type = fields.Char(index=True)

    status = fields.Selection(
        [
            ("new", "New"),
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("rework", "Rework"),
            ("cancelled", "Cancelled"),
            ("closed", "Closed"),
            ("blocked", "Blocked"),
        ],
        required=True,
        default="new",
        index=True,
    )
    required = fields.Boolean(default=True, index=True)
    completion_mode = fields.Selection(
        [("any", "Any"), ("all", "All")],
        default="any",
        required=True,
        help="ANY: first approver completes task. ALL: all assignees must approve.",
    )
    iteration_no = fields.Integer(default=1, required=True, index=True)

    # Join/gateway metadata
    join_key = fields.Char(index=True, help="Gateway correlation key for parallel joins.")
    gateway_node_id = fields.Char(index=True)
    join_policy = fields.Selection(
        [("all_of", "All Of"), ("any_of", "Any Of"), ("min_n", "Min N")],
        default="all_of",
        required=True,
    )
    join_min_n = fields.Integer(default=0)
    reject_policy = fields.Selection(
        [("strict", "Strict"), ("soft", "Soft")],
        default="strict",
        required=True,
    )

    due_date = fields.Datetime()
    sla_deadline = fields.Datetime()
    started_at = fields.Datetime()
    completed_at = fields.Datetime()
    blocked_reason = fields.Char()

    assignment_snapshot = fields.Json(
        help="Resolved assignment debug snapshot used for deterministic audit."
    )
    source_task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="set null",
        index=True,
    )

    assignee_ids = fields.One2many(
        "workflow.request.task.assignee",
        "task_instance_id",
        string="Assignees",
    )
    action_assignment_ids = fields.One2many(
        "workflow.request.action.assignment",
        "task_instance_id",
        string="Business Action Assignments",
    )
    event_ids = fields.One2many(
        "workflow.request.task.event",
        "task_instance_id",
        string="Events",
    )

    assignee_count = fields.Integer(compute="_compute_assignee_stats", store=True)
    approved_count = fields.Integer(compute="_compute_assignee_stats", store=True)
    rejected_count = fields.Integer(compute="_compute_assignee_stats", store=True)
    open_count = fields.Integer(compute="_compute_assignee_stats", store=True)
    is_active = fields.Boolean(compute="_compute_is_active", store=True, index=True)

    _task_instance_iteration_positive = models.Constraint(
        "CHECK(iteration_no > 0)",
        "Iteration number must be positive.",
    )
    _task_instance_join_min_non_negative = models.Constraint(
        "CHECK(join_min_n >= 0)",
        "Join minimum must be >= 0.",
    )

    @api.depends("assignee_ids.status")
    def _compute_assignee_stats(self):
        for rec in self:
            statuses = rec.assignee_ids.mapped("status")
            rec.assignee_count = len(statuses)
            rec.approved_count = len([s for s in statuses if s == "approved"])
            rec.rejected_count = len([s for s in statuses if s == "rejected"])
            rec.open_count = len([s for s in statuses if s in ("new", "pending", "in_progress")])

    @api.depends("status")
    def _compute_is_active(self):
        active_statuses = {"new", "pending", "in_progress", "blocked", "rework"}
        for rec in self:
            rec.is_active = rec.status in active_statuses

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_instance_req_node_status_idx
                ON workflow_request_task_instance (request_id, node_id, status)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_instance_req_iteration_idx
                ON workflow_request_task_instance (request_id, iteration_no)
            """
        )

    def action_close_remaining_assignees(self, winner_assignee_id=False):
        for rec in self:
            rows = rec.assignee_ids.filtered(lambda a: a.status in ("new", "pending", "in_progress"))
            if winner_assignee_id:
                rows = rows.filtered(lambda a: a.id != winner_assignee_id)
            if rows:
                rows.sudo().write({"status": "closed"})

    def mark_status(self, status, reason=False):
        for rec in self:
            vals = {"status": status}
            if status in ("approved", "rejected", "cancelled", "closed"):
                vals["completed_at"] = fields.Datetime.now()
            if reason:
                vals["blocked_reason"] = reason
            if status in ("pending", "in_progress") and not rec.started_at:
                vals["started_at"] = fields.Datetime.now()
            rec.sudo().write(vals)
            if status in ("approved", "rejected", "cancelled", "closed"):
                self.env[
                    "workflow.engine.assignment.service"
                ]._close_business_action_assignments(
                    rec.request_id,
                    task_instance=rec,
                    reason=reason or _("Closed when the workflow task became terminal."),
                )


class WorkflowRequestTaskAssignee(models.Model):
    _name = "workflow.request.task.assignee"
    _description = "Workflow Task Assignee Snapshot"
    _order = "id asc"
    _check_company_auto = True

    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        required=True,
        ondelete="cascade",
        index=True,
    )
    request_id = fields.Many2one(related="task_instance_id.request_id", store=True, index=True)
    category_id = fields.Many2one(related="task_instance_id.category_id", store=True, index=True)
    company_id = fields.Many2one(related="task_instance_id.company_id", store=True, index=True)
    node_id = fields.Char(related="task_instance_id.node_id", store=True, index=True)
    iteration_no = fields.Integer(related="task_instance_id.iteration_no", store=True, index=True)

    assignee_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    original_user_id = fields.Many2one(
        "res.users",
        ondelete="set null",
        index=True,
        help="The originally resolved assignee before delegation substitution.",
    )
    delegated_from_user_id = fields.Many2one(
        "res.users",
        ondelete="set null",
        index=True,
        help="If delegate acted, this stores on-behalf assignee.",
    )
    visibility_scope_id = fields.Many2one(
        "workflow.request.visibility.scope",
        ondelete="set null",
        index=True,
    )

    status = fields.Selection(
        [
            ("new", "New"),
            ("pending", "Pending"),
            ("in_progress", "In Progress"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("rework", "Rework"),
            ("cancelled", "Cancelled"),
            ("closed", "Closed"),
            ("skipped", "Skipped"),
        ],
        required=True,
        default="new",
        index=True,
    )
    can_act = fields.Boolean(default=True, index=True)
    assigned_at = fields.Datetime(default=fields.Datetime.now, index=True)
    decision_at = fields.Datetime(index=True)
    decision = fields.Char()
    comment = fields.Text()

    _task_assignee_unique = models.Constraint(
        "UNIQUE(task_instance_id, assignee_user_id)",
        "This assignee already exists on the task instance.",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_assignee_user_status_request_idx
                ON workflow_request_task_assignee (assignee_user_id, status, request_id)
                WHERE assignee_user_id IS NOT NULL AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_assignee_open_user_request_idx
                ON workflow_request_task_assignee (assignee_user_id, request_id)
                WHERE status IN ('new', 'pending', 'in_progress', 'rework')
                  AND assignee_user_id IS NOT NULL
                  AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_assignee_request_user_status_idx
                ON workflow_request_task_assignee (request_id, assignee_user_id, status)
                WHERE request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_assignee_instance_status_idx
                ON workflow_request_task_assignee (task_instance_id, status)
            """
        )


class WorkflowRequestActionAssignment(models.Model):
    _name = "workflow.request.action.assignment"
    _description = "Workflow Request Business Action Assignment"
    _order = "id asc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="cascade",
        index=True,
    )
    meta_action_id = fields.Many2one(
        "workflow.category.version.meta.task.action",
        required=True,
        ondelete="restrict",
        index=True,
    )
    action_name = fields.Char(related="meta_action_id.name", readonly=True)
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    version_id = fields.Many2one(related="request_id.version_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    node_id = fields.Char(related="task_instance_id.node_id", store=True, index=True)
    iteration_no = fields.Integer(related="task_instance_id.iteration_no", store=True, index=True)

    scope = fields.Selection(
        [("task", "Current Task"), ("request", "Whole Request")],
        required=True,
        default="task",
        index=True,
    )
    actor_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    original_actor_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="restrict",
        index=True,
        help="Root actor from whom this exact action right originated.",
    )
    delegated_from_user_id = fields.Many2one(
        "res.users",
        ondelete="set null",
        index=True,
        help="Immediate actor who shared or redirected this action right.",
    )
    delegated_by_user_id = fields.Many2one(
        "res.users",
        ondelete="set null",
        index=True,
    )
    delegation_mode = fields.Selection(
        [("shared", "Shared"), ("redirected", "Redirected")],
        index=True,
    )
    status = fields.Selection(
        [
            ("open", "Open"),
            ("acted", "Acted"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
            ("redirected", "Redirected"),
        ],
        required=True,
        default="open",
        index=True,
    )
    can_act = fields.Boolean(default=True, required=True, index=True)
    source_snapshot = fields.Json(default=dict)
    visibility_scope_id = fields.Many2one(
        "workflow.request.visibility.scope",
        ondelete="set null",
        index=True,
    )
    assigned_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    acted_at = fields.Datetime(index=True)
    closed_at = fields.Datetime(index=True)
    close_reason = fields.Char()

    _action_assignment_unique = models.Constraint(
        "UNIQUE(task_instance_id, meta_action_id, actor_user_id, original_actor_user_id)",
        "This exact business action grant already exists for the task actor.",
    )
    _action_assignment_task_scope = models.Constraint(
        "CHECK(scope <> 'task' OR task_instance_id IS NOT NULL)",
        "Task-scoped business actions require a task instance.",
    )

    @api.constrains("scope", "task_instance_id", "request_id", "meta_action_id")
    def _check_assignment_scope(self):
        for assignment in self:
            if assignment.scope != "task":
                raise ValidationError(
                    _("Whole-request business actions are reserved for a future engine release.")
                )
            if assignment.task_instance_id.request_id != assignment.request_id:
                raise ValidationError(_("The business action task belongs to another request."))
            if assignment.meta_action_id.authorization_mode != "business_actor":
                raise ValidationError(_("Only business actions can create action assignments."))
            if assignment.meta_action_id.source_id != assignment.task_instance_id.node_id:
                raise ValidationError(_("The business action does not belong to this task node."))

    def init(self):
        if not table_exists(self.env.cr, self._table):
            return

        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_action_assignment_open_actor_request_idx
                ON workflow_request_action_assignment
                   (actor_user_id, request_id, node_id, meta_action_id)
             WHERE status = 'open' AND can_act IS TRUE
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_action_assignment_open_task_action_actor_idx
                ON workflow_request_action_assignment
                   (task_instance_id, meta_action_id, actor_user_id)
             WHERE status = 'open' AND can_act IS TRUE
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_action_assignment_task_status_idx
                ON workflow_request_action_assignment (task_instance_id, status)
            """
        )

    def mark_closed(self, status="closed", reason=False):
        rows = self.filtered(lambda row: row.status == "open" or row.can_act)
        if rows:
            rows.sudo().write(
                {
                    "status": status,
                    "can_act": False,
                    "closed_at": fields.Datetime.now(),
                    "close_reason": reason or False,
                }
            )
        return rows


class WorkflowRequestTaskEvent(models.Model):
    _name = "workflow.request.task.event"
    _description = "Workflow Task Event (Immutable Audit)"
    _order = "id asc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="set null",
        index=True,
    )
    task_assignee_id = fields.Many2one(
        "workflow.request.task.assignee",
        ondelete="set null",
        index=True,
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)

    event_type = fields.Selection(
        [
            ("assignment", "Assignment"),
            ("action", "Business Action"),
            ("decision", "Decision"),
            ("transition", "Transition"),
            ("delegation", "Delegation"),
            ("fallback", "Fallback"),
            ("security", "Security"),
            ("twofactor", "2FA"),
            ("automation", "Automation"),
            ("system", "System"),
            ("admin_override", "Admin Override"),
        ],
        required=True,
        default="system",
        index=True,
    )
    action_key = fields.Char(index=True)
    decision = fields.Char(index=True)
    from_node_id = fields.Char(index=True)
    to_node_id = fields.Char(index=True)
    actor_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    on_behalf_of_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    target_user_id = fields.Many2one("res.users", ondelete="set null", index=True)

    comment = fields.Text()
    payload_json = fields.Json(default=dict)
    idempotency_key = fields.Char(index=True)

    request_ip = fields.Char(size=128)
    request_host = fields.Char(size=512)
    user_agent = fields.Char(size=1024)

    challenge_id = fields.Many2one(
        "workflow.approval.action.challenge",
        ondelete="set null",
        index=True,
    )
    challenge_method = fields.Selection(
        [("none", "None"), ("qr", "QR"), ("email_otp", "Email OTP")]
    )
    challenge_verified = fields.Boolean(default=False)

    _task_event_idempotency_unique = models.Constraint(
        "UNIQUE(request_id, event_type, idempotency_key)",
        "Duplicate idempotency event is not allowed.",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_event_actor_request_idx
                ON workflow_request_task_event (actor_user_id, request_id)
                WHERE actor_user_id IS NOT NULL AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_event_on_behalf_request_idx
                ON workflow_request_task_event (on_behalf_of_user_id, request_id)
                WHERE on_behalf_of_user_id IS NOT NULL AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_task_event_request_type_id_idx
                ON workflow_request_task_event (request_id, event_type, id)
                WHERE request_id IS NOT NULL
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        # Odoo 19 deprecates _sql_constraints; keep server-side guard for idempotency.
        seen = set()
        for vals in vals_list:
            key = vals.get("idempotency_key")
            request_id = vals.get("request_id")
            event_type = vals.get("event_type")
            if not key or not request_id or not event_type:
                continue
            scope = (request_id, event_type, key)
            if scope in seen:
                raise ValidationError(_("Duplicate idempotency event is not allowed."))
            seen.add(scope)
            exists = self.sudo().search(
                [
                    ("request_id", "=", request_id),
                    ("event_type", "=", event_type),
                    ("idempotency_key", "=", key),
                ],
                limit=1,
            )
            if exists:
                raise ValidationError(_("Duplicate idempotency event is not allowed."))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Workflow task events are immutable and cannot be updated."))

    def unlink(self):
        raise UserError(_("Workflow task events are immutable and cannot be deleted."))


class WorkflowRequestVisibilityScope(models.Model):
    _name = "workflow.request.visibility.scope"
    _description = "Workflow Request Visibility Scope"
    _order = "id desc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="cascade",
        index=True,
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)

    scope = fields.Selection(
        [("read", "Read"), ("edit", "Edit"), ("decision", "Decision")],
        required=True,
        default="read",
        index=True,
    )
    allowed_user_id = fields.Many2one("res.users", ondelete="cascade", index=True)
    allowed_group_id = fields.Many2one("res.groups", ondelete="cascade", index=True)
    granted_by_user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        required=True,
        ondelete="restrict",
        index=True,
    )
    reason = fields.Char()
    expires_at = fields.Datetime(index=True)
    active = fields.Boolean(default=True, index=True)

    _visibility_scope_target_check = models.Constraint(
        "CHECK((allowed_user_id IS NOT NULL) OR (allowed_group_id IS NOT NULL))",
        "Visibility scope must target a user or a group.",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_request_scope_active_idx
                ON workflow_request_visibility_scope (request_id, scope, active)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_allowed_user_scope_active_idx
                ON workflow_request_visibility_scope (allowed_user_id, scope, active)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_allowed_group_scope_active_idx
                ON workflow_request_visibility_scope (allowed_group_id, scope, active)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_active_expires_idx
                ON workflow_request_visibility_scope (active, expires_at)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_active_user_request_idx
                ON workflow_request_visibility_scope (allowed_user_id, request_id)
                WHERE active IS TRUE AND allowed_user_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_visibility_scope_active_group_request_idx
                ON workflow_request_visibility_scope (allowed_group_id, request_id)
                WHERE active IS TRUE AND allowed_group_id IS NOT NULL
            """
        )

    def is_valid(self):
        self.ensure_one()
        if not self.active:
            return False
        if self.expires_at and fields.Datetime.now() > self.expires_at:
            return False
        return True

    def _sync_request_visibility_scope_targets(self, requests=False):
        requests = (requests or self.sudo().mapped("request_id")).sudo().exists()
        if not requests:
            return
        requests._compute_visibility_scope_targets()
        requests.flush_recordset(["visibility_scope_user_ids", "visibility_scope_group_ids"])
        requests.invalidate_recordset(["visibility_scope_user_ids", "visibility_scope_group_ids"])

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_request_visibility_scope_targets()
        return records

    def write(self, vals):
        tracked_fields = {
            "request_id",
            "scope",
            "allowed_user_id",
            "allowed_group_id",
            "expires_at",
            "active",
        }
        should_sync = bool(tracked_fields.intersection(vals))
        requests = self.env["workflow.base.approval.request"]
        if should_sync:
            requests |= self.sudo().with_context(active_test=False).mapped("request_id")
        result = super().write(vals)
        if should_sync:
            requests |= self.sudo().with_context(active_test=False).mapped("request_id")
            self._sync_request_visibility_scope_targets(requests=requests)
        return result

    def unlink(self):
        requests = self.sudo().with_context(active_test=False).mapped("request_id")
        result = super().unlink()
        self._sync_request_visibility_scope_targets(requests=requests)
        return result


class WorkflowApprovalDelegation(models.Model):
    _name = "workflow.approval.delegation"
    _description = "Workflow Approval Delegation"
    _order = "id desc"
    _check_company_auto = True

    delegator_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    delegate_user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_delegation_category_rel",
        "delegation_id",
        "category_id",
        string="Scoped Categories",
    )
    date_from = fields.Datetime(required=True, index=True)
    date_to = fields.Datetime(required=True, index=True)
    scope = fields.Selection(
        [("approvals", "Approvals"), ("all", "All")],
        default="approvals",
        required=True,
        index=True,
    )
    delegation_source = fields.Selection(
        [
            ("manual", "Manual"),
            ("out_of_office", "Out of Office"),
        ],
        default="manual",
        required=True,
        index=True,
        help="Manual: created explicitly by users/admin.\n"
             "Out of Office: generated from user preference configuration.",
    )
    assignment_strategy = fields.Selection(
        [
            ("replace", "Replace Assignee"),
            ("cc_delegate", "Keep Assignee + Add Delegate"),
        ],
        default="replace",
        required=True,
        index=True,
        help="Replace Assignee: only delegate is assigned.\n"
             "Keep Assignee + Add Delegate: delegate is added while original assignee remains active.",
    )
    active = fields.Boolean(default=True, index=True)
    note = fields.Text()
    company_id = fields.Many2one(
        "res.company",
        compute="_compute_company_id",
        store=True,
        index=True,
    )

    _delegation_date_check = models.Constraint(
        "CHECK(date_to >= date_from)",
        "Delegation end date must be after start date.",
    )
    _delegation_not_self = models.Constraint(
        "CHECK(delegator_user_id <> delegate_user_id)",
        "Delegator and delegate cannot be the same user.",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_delegation_active_delegate_window_idx
                ON workflow_approval_delegation (delegate_user_id, active, date_from, date_to)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_delegation_active_delegator_window_idx
                ON workflow_approval_delegation (delegator_user_id, active, date_from, date_to)
            """
        )

    @api.depends("delegator_user_id")
    def _compute_company_id(self):
        for rec in self:
            rec.company_id = rec.delegator_user_id.company_id.id if rec.delegator_user_id.company_id else False

    def is_active_now(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return bool(self.active and self.date_from <= now <= self.date_to)

    @api.model
    def get_active_delegations(self, delegator_user, category=False, at_datetime=False):
        if not delegator_user:
            return self.browse()
        at_datetime = at_datetime or fields.Datetime.now()
        domain = [
            ("delegator_user_id", "=", delegator_user.id),
            ("active", "=", True),
            ("date_from", "<=", at_datetime),
            ("date_to", ">=", at_datetime),
        ]
        delegations = self.search(domain)
        if category:
            scoped = delegations.filtered(lambda d: not d.category_ids or category in d.category_ids)
            delegations = scoped
        return delegations

    def select_best_for_category(self, category=False):
        """Pick the delegation rule that should apply for one request category.

        Category-specific rules intentionally win over catch-all rules, so users
        can configure Workflow A -> Delegate A and a catch-all fallback without
        runtime ambiguity.
        """
        delegations = self
        if category:
            specific = delegations.filtered(lambda d: category in d.category_ids)
            delegations = specific or delegations.filtered(lambda d: not d.category_ids)
        else:
            delegations = delegations.filtered(lambda d: not d.category_ids)
        return delegations.sorted(key=lambda d: (d.date_from, d.id), reverse=True)[:1]


class WorkflowApprovalActionChallenge(models.Model):
    _name = "workflow.approval.action.challenge"
    _description = "Workflow Action 2FA Challenge"
    _order = "id desc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="set null",
        index=True,
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)

    action_key = fields.Char(required=True, index=True)
    meta_action_id = fields.Many2one(
        "workflow.category.version.meta.task.action",
        string="Meta Action",
        ondelete="set null",
        index=True,
    )
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    method = fields.Selection(
        [("qr", "QR"), ("email_otp", "Email OTP")],
        required=True,
        default="email_otp",
        index=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("scanned", "Scanned"),
            ("verified", "Verified"),
            ("approved", "Approved"),
            ("denied", "Denied"),
            ("expired", "Expired"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    token = fields.Char(required=True, index=True, default=lambda self: secrets.token_urlsafe(24))
    qr_secret = fields.Char(help="Random secret used in QR payload HMAC")
    qr_signature = fields.Char(help="Server-side HMAC signature for mobile validation")
    qr_image = fields.Binary(
        compute="_compute_qr_image",
        help="Generated QR with challenge payload",
    )
    code_hash = fields.Char()
    expires_at = fields.Datetime(required=True, index=True)
    otp_expires_at = fields.Datetime()
    otp_attempts = fields.Integer(default=0)
    otp_last_sent_at = fields.Datetime()
    otp_resend_cooldown = fields.Integer(default=30)
    otp_length = fields.Integer(default=6)
    last_error = fields.Char()
    verified_at = fields.Datetime()
    used_at = fields.Datetime()
    attempts = fields.Integer(default=0)
    max_attempts = fields.Integer(default=5)
    one_time = fields.Boolean(default=True)
    idempotency_key = fields.Char(index=True)
    scanned_at = fields.Datetime(index=True)
    scanned_by_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    scanned_ip = fields.Char(size=128)
    scanned_host = fields.Char(size=512)
    scanned_user_agent = fields.Char(size=1024)
    decision_at = fields.Datetime(index=True)
    decision_by_user_id = fields.Many2one("res.users", ondelete="set null", index=True)
    decision_ip = fields.Char(size=128)
    decision_host = fields.Char(size=512)
    decision_user_agent = fields.Char(size=1024)

    def _compute_qr_image(self):
        for rec in self:
            rec.qr_image = False
            try:
                import qrcode
                import io
                payload = rec.qr_payload_json()
                img = qrcode.make(payload)
                buff = io.BytesIO()
                img.save(buff, format="PNG")
                rec.qr_image = base64.b64encode(buff.getvalue())
            except Exception:
                rec.qr_image = False

    _action_challenge_token_unique = models.Constraint(
        "UNIQUE(token)",
        "Challenge token must be unique.",
    )

    @staticmethod
    def _normalize_login(value):
        return (value or "").strip().lower()

    def _signed_payload_v1(self):
        self.ensure_one()
        return f"{self.token}:{self.qr_secret}"

    def _signed_payload_v2(self):
        self.ensure_one()
        return (
            f"{self.token}:{self.qr_secret}:{int(self.user_id.id or 0)}:"
            f"workflow.approval.twofa"
        )

    def build_qr_payload(self):
        self.ensure_one()
        return {
            "qr_kind": "workflow.approval.twofa",
            "schema_version": 2,
            "challenge_id": self.id,
            "token": self.token,
            "signature": self.qr_signature,
            "request_id": self.request_id.id,
            "action_key": self.action_key or "",
            "expected_user_id": self.user_id.id or False,
            "expected_user_login": self._normalize_login(self.user_id.login),
            "expires_at": fields.Datetime.to_string(self.expires_at) if self.expires_at else False,
        }

    def qr_payload_json(self):
        self.ensure_one()
        return json.dumps(
            self.build_qr_payload(),
            separators=(",", ":"),
            sort_keys=True,
        )

    def _hmac_key(self):
        param = self.env["ir.config_parameter"].sudo().get_param("workflow_engine.twofa_hmac_key")
        if not param:
            param = secrets.token_hex(16)
            self.env["ir.config_parameter"].sudo().set_param("workflow_engine.twofa_hmac_key", param)
        return param.encode("utf-8")

    def _sign_payload(self, payload):
        key = self._hmac_key()
        mac = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return mac

    def verify_qr_signature(self, signature):
        self.ensure_one()
        if not signature:
            return False
        incoming = str(signature or "").strip()
        expected_v2 = self._sign_payload(self._signed_payload_v2())
        if hmac.compare_digest(expected_v2, incoming):
            return True
        # Backward compatibility for previously issued challenges.
        expected_v1 = self._sign_payload(self._signed_payload_v1())
        return hmac.compare_digest(expected_v1, incoming)

    def validate_scanner_identity(self, actor_user=False, scanner_user_id=False, scanner_login=False):
        self.ensure_one()
        actor = (actor_user or self.env.user).sudo()
        if not actor or not actor.id:
            return False, "missing_actor"
        if actor.id != self.user_id.id:
            return False, "forbidden_user_mismatch"
        if scanner_user_id:
            try:
                scanner_uid = int(scanner_user_id)
            except Exception:
                return False, "invalid_scanner_user"
            if scanner_uid != actor.id:
                return False, "forbidden_scanner_user_mismatch"
        if scanner_login and self._normalize_login(scanner_login) != self._normalize_login(actor.login):
            return False, "forbidden_scanner_login_mismatch"
        return True, False

    def _notify_bus_state(self, state, message=False):
        """Send bus notification for real-time UI updates."""
        self.ensure_one()
        channel = f"workflow_2fa.challenge_{self.id}"
        payload = {
            "challenge_id": self.id,
            "state": state,
            "message": message or "",
            "expires_at": self.expires_at,
        }
        self.env["bus.bus"].sudo()._sendone(channel, "workflow_2fa.challenge_state", payload)

    @api.model
    def _hash_code(self, token, code):
        payload = f"{token}:{code or ''}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @api.model
    def _normalize_otp_length(self, length=False):
        try:
            normalized = int(length or 6)
        except Exception:
            normalized = 6
        return max(4, min(8, normalized))

    @api.model
    def _generate_otp_code(self, length=False):
        otp_length = self._normalize_otp_length(length)
        otp_code = "".join(str(secrets.randbelow(10)) for _ in range(otp_length))
        return otp_code, otp_length

    @api.model
    def issue_email_otp(self, request_record, action_key, user, ttl_seconds=90, task_instance=False):
        if not request_record or not user:
            raise ValidationError(_("Missing challenge target or user."))
        otp_code, otp_length = self._generate_otp_code()
        token = secrets.token_urlsafe(24)
        challenge = self.create(
            {
                "request_id": request_record.id,
                "task_instance_id": task_instance.id if task_instance else False,
                "action_key": action_key,
                "user_id": user.id,
                "method": "email_otp",
                "state": "pending",
                "token": token,
                "expires_at": fields.Datetime.now() + timedelta(seconds=max(30, int(ttl_seconds))),
                "otp_expires_at": fields.Datetime.now() + timedelta(minutes=5),
                "otp_length": otp_length,
                "code_hash": self._hash_code(token, otp_code),
            }
        )
        challenge._send_email_otp(otp_code)
        return challenge

    @api.model
    def issue_qr_challenge(self, request_record, action_key, user, ttl_seconds=90, task_instance=False):
        if not request_record or not user:
            raise ValidationError(_("Missing challenge target or user."))
        token = secrets.token_urlsafe(24)
        secret = secrets.token_urlsafe(16)
        user_id = int(user.id or 0)
        signature = self._sign_payload(
            f"{token}:{secret}:{user_id}:workflow.approval.twofa"
        )
        challenge = self.create(
            {
                "request_id": request_record.id,
                "task_instance_id": task_instance.id if task_instance else False,
                "action_key": action_key,
                "user_id": user.id,
                "method": "qr",
                "state": "pending",
                "token": token,
                "qr_secret": secret,
                "qr_signature": signature,
                "expires_at": fields.Datetime.now() + timedelta(seconds=max(30, int(ttl_seconds))),
            }
        )
        return challenge

    def _can_resend_otp(self):
        self.ensure_one()
        if not self.otp_last_sent_at:
            return True
        delta = fields.Datetime.now() - self.otp_last_sent_at
        return delta.total_seconds() >= (self.otp_resend_cooldown or 30)

    def request_otp(self):
        self.ensure_one()
        if not self._can_resend_otp():
            raise ValidationError(_("Please wait before requesting another code."))
        otp_code, otp_length = self._generate_otp_code(self.otp_length)
        expires = fields.Datetime.now() + timedelta(minutes=5)
        self.sudo().write(
            {
                "method": "email_otp",
                "state": "pending",
                "otp_attempts": 0,
                "otp_last_sent_at": fields.Datetime.now(),
                "otp_expires_at": expires,
                "expires_at": fields.Datetime.now() + timedelta(minutes=5),
                "code_hash": self._hash_code(self.token, otp_code),
                "otp_length": otp_length,
                "last_error": False,
            }
        )
        self._send_email_otp(otp_code)
        self._notify_bus_state("pending")
        return True

    def _send_email_otp(self, otp_code):
        self.ensure_one()
        if any(
            self.env.context.get(flag)
            for flag in (
                "no_notification",
                "no_email_send",
                "workflow_no_email_send",
                "workflow_suppress_notifications",
                "workflow_skip_notifications",
                "workflow_silent_migration",
                "workflow_migration_mode",
            )
        ):
            return
        if not self.user_id.email:
            _logger.warning("Skipping OTP email: user %s has no email.", self.user_id.id)
            return
        subject = _("Workflow Approval OTP")
        body_html = _(
            "<p>Your one-time approval code is <b>%(code)s</b>.</p>"
            "<p>It expires at %(expiry)s.</p>",
            code=otp_code,
            expiry=fields.Datetime.to_string(self.otp_expires_at or self.expires_at),
        )
        mail = self.env["mail.mail"].sudo().create(
            {
                "subject": subject,
                "body_html": body_html,
                "email_to": self.user_id.email,
            }
        )
        mail.send()

    def verify_email_otp(
        self,
        otp_code,
        actor_user=False,
        request_ip=False,
        request_host=False,
        user_agent=False,
    ):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state not in ("pending", "scanned"):
            return False
        if self.otp_expires_at and now > self.otp_expires_at:
            self.sudo().write({"state": "expired"})
            self._notify_bus_state("expired", "OTP expired")
            return False
        attempts = (self.otp_attempts or 0) + 1
        values = {"otp_attempts": attempts}
        if attempts > 5:
            values["state"] = "failed"
            self.sudo().write(values)
            self._notify_bus_state("failed", "Too many OTP attempts")
            return False

        expected = self._hash_code(self.token, otp_code)
        if expected != self.code_hash:
            self.sudo().write(values)
            return False

        actor = (actor_user or self.env.user).sudo()
        values.update(
            {
                "state": "approved",
                "verified_at": now,
                "decision_at": now,
                "decision_by_user_id": actor.id if actor and actor.id else False,
                "decision_ip": request_ip or False,
                "decision_host": request_host or False,
                "decision_user_agent": user_agent or False,
            }
        )
        self.sudo().write(values)
        self._notify_bus_state("approved")
        return True

    def verify_qr_token(
        self,
        token,
        actor_user=False,
        request_ip=False,
        request_host=False,
        user_agent=False,
    ):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state in ("verified", "approved"):
            return True
        if self.state not in ("pending", "scanned"):
            return False
        if self.expires_at and now > self.expires_at:
            self.sudo().write({"state": "expired"})
            return False
        attempts = (self.attempts or 0) + 1
        values = {"attempts": attempts}
        if attempts > (self.max_attempts or 5):
            values["state"] = "failed"
            self.sudo().write(values)
            self._notify_bus_state("failed")
            return False
        if not token or not secrets.compare_digest((self.token or "").strip(), token.strip()):
            self.sudo().write(values)
            return False
        actor = (actor_user or self.env.user).sudo()
        values.update(
            {
                "state": "approved",
                "verified_at": now,
                "decision_at": now,
                "decision_by_user_id": actor.id if actor and actor.id else False,
                "decision_ip": request_ip or False,
                "decision_host": request_host or False,
                "decision_user_agent": user_agent or False,
            }
        )
        self.sudo().write(values)
        self._notify_bus_state("approved")
        return True

    def mark_scanned(
        self,
        actor_user=False,
        request_ip=False,
        request_host=False,
        user_agent=False,
    ):
        self.ensure_one()
        if self.state != "pending":
            return False
        actor = (actor_user or self.env.user).sudo()
        self.sudo().write(
            {
                "state": "scanned",
                "scanned_at": fields.Datetime.now(),
                "scanned_by_user_id": actor.id if actor and actor.id else False,
                "scanned_ip": request_ip or False,
                "scanned_host": request_host or False,
                "scanned_user_agent": user_agent or False,
            }
        )
        self._notify_bus_state("scanned")
        return True

    def mark_decision(
        self,
        decision,
        actor_user=False,
        request_ip=False,
        request_host=False,
        user_agent=False,
    ):
        self.ensure_one()
        if self.state not in ("pending", "scanned", "approved"):
            return False
        now = fields.Datetime.now()
        if self.expires_at and now > self.expires_at:
            self.sudo().write({"state": "expired"})
            self._notify_bus_state("expired")
            return False
        actor = (actor_user or self.env.user).sudo()
        decision_meta = {
            "decision_at": now,
            "decision_by_user_id": actor.id if actor and actor.id else False,
            "decision_ip": request_ip or False,
            "decision_host": request_host or False,
            "decision_user_agent": user_agent or False,
        }
        if decision == "approve":
            self.sudo().write({"state": "approved", "verified_at": now, **decision_meta})
            self._notify_bus_state("approved")
            return True
        if decision in ("deny", "reject"):
            self.sudo().write({"state": "denied", "last_error": "Denied by mobile", **decision_meta})
            self._notify_bus_state("denied")
            return False
        return False

    @api.model
    def _cron_expire_pending(self):
        now = fields.Datetime.now()
        stale = self.search(
            [
                ("state", "in", ["pending", "scanned"]),
                ("expires_at", "!=", False),
                ("expires_at", "<", now),
            ]
        )
        if stale:
            stale.sudo().write({"state": "expired"})
            for ch in stale:
                ch._notify_bus_state("expired")


class WorkflowFieldRuleSet(models.Model):
    _name = "workflow.field.rule.set"
    _description = "Workflow Field Rule Set"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)
    category_id = fields.Many2one("workflow.approval.category", ondelete="cascade", index=True)
    version_id = fields.Many2one("workflow.approval.category.version", ondelete="cascade", index=True)
    description = fields.Text()
    is_legacy_bridge = fields.Boolean(
        default=False,
        help="Rule set generated from legacy meta field configuration.",
    )
    rule_ids = fields.One2many("workflow.field.rule", "rule_set_id", string="Rules")

    _field_rule_set_code_unique = models.Constraint(
        "UNIQUE(code)",
        "Rule-set code must be unique.",
    )


class WorkflowFieldRule(models.Model):
    _name = "workflow.field.rule"
    _description = "Workflow Field Rule"
    _order = "sequence, id"

    rule_set_id = fields.Many2one(
        "workflow.field.rule.set",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)
    name = fields.Char(required=True)
    task_node_id = fields.Char(index=True)
    action_key = fields.Char(index=True)
    condition_json = fields.Json(
        default=dict,
        help="Safe JSON condition DSL. Example: {'all': [{'field': 'amount', 'op': '>', 'value': 1000}]}.",
    )
    effect_json = fields.Json(
        default=dict,
        help="Field effect payload. Example: {'fields': {'x_secret': {'visible': false, 'readonly': true}}}.",
    )
    stop_on_match = fields.Boolean(default=False)
    note = fields.Text()


class WorkflowFieldRuleBinding(models.Model):
    _name = "workflow.field.rule.binding"
    _description = "Workflow Field Rule Binding"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)
    scope = fields.Selection(
        [("category", "Category"), ("task", "Task"), ("action", "Action")],
        required=True,
        default="category",
        index=True,
    )
    category_id = fields.Many2one("workflow.approval.category", required=True, ondelete="cascade", index=True)
    version_id = fields.Many2one("workflow.approval.category.version", ondelete="cascade", index=True)
    task_node_id = fields.Char(index=True)
    action_key = fields.Char(index=True)
    rule_set_id = fields.Many2one("workflow.field.rule.set", required=True, ondelete="cascade", index=True)


class WorkflowAutomationNode(models.Model):
    _name = "workflow.automation.node"
    _description = "Workflow Automation Node"
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True, index=True)
    category_id = fields.Many2one("workflow.approval.category", required=True, ondelete="cascade", index=True)
    version_id = fields.Many2one("workflow.approval.category.version", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="category_id.company_id", store=True, index=True)
    node_id = fields.Char(required=True, index=True)

    trigger_type = fields.Selection(
        [("on_reach", "On Reach"), ("schedule", "Schedule")],
        default="schedule",
        required=True,
        index=True,
    )
    schedule_mode = fields.Selection(
        [("interval", "Interval"), ("fixed_time", "Fixed Time"), ("cron", "Cron")],
        default="interval",
    )
    interval_number = fields.Integer(default=5)
    interval_type = fields.Selection(
        [("minutes", "Minutes"), ("hours", "Hours"), ("days", "Days")],
        default="minutes",
    )
    fixed_time = fields.Float(
        help="Hour in 24h format (e.g. 13.5 means 13:30). Used when schedule_mode=fixed_time."
    )
    cron_expr = fields.Char()
    condition_json = fields.Json(default=dict)

    action_type = fields.Selection(
        AUTOMATION_ACTION_SELECTION,
        required=True,
        default="enqueue_job",
        index=True,
    )
    action_config_json = fields.Json(default=dict)
    retry_policy_json = fields.Json(default=dict)
    timeout_seconds = fields.Integer(default=30)
    failure_policy = fields.Selection(
        AUTOMATION_FAILURE_POLICY_SELECTION,
        default="retry",
        required=True,
    )
    next_run_at = fields.Datetime(index=True)
    last_run_at = fields.Datetime(index=True)

    run_ids = fields.One2many("workflow.automation.run", "automation_node_id", string="Runs")

    def _interval_to_timedelta(self):
        self.ensure_one()
        number = max(1, int(self.interval_number or 1))
        match self.interval_type:
            case "hours":
                return timedelta(hours=number)
            case "days":
                return timedelta(days=number)
            case _:
                return timedelta(minutes=number)

    def _compute_next_run_value(self, reference_dt=False):
        self.ensure_one()
        reference_dt = reference_dt or fields.Datetime.now()
        if self.schedule_mode == "interval":
            return reference_dt + self._interval_to_timedelta()
        if self.schedule_mode == "fixed_time" and self.fixed_time is not False:
            base = fields.Datetime.from_string(fields.Datetime.to_string(reference_dt))
            hour = int(self.fixed_time)
            minute = int(round((self.fixed_time - hour) * 60))
            candidate = base.replace(hour=max(0, min(23, hour)), minute=max(0, min(59, minute)), second=0, microsecond=0)
            if candidate <= reference_dt:
                candidate = candidate + timedelta(days=1)
            return candidate
        # cron mode fallback: run every 5 minutes unless external scheduler parses cron.
        return reference_dt + timedelta(minutes=5)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("trigger_type", "schedule") == "schedule" and not vals.get("next_run_at"):
                tmp = self.new(vals)
                vals["next_run_at"] = fields.Datetime.to_string(tmp._compute_next_run_value())
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        schedule_fields = {"active", "trigger_type", "schedule_mode", "interval_number", "interval_type", "fixed_time", "cron_expr"}
        if schedule_fields.intersection(vals.keys()):
            for rec in self.filtered(lambda n: n.trigger_type == "schedule" and n.active):
                if not rec.next_run_at:
                    rec.sudo().write({"next_run_at": rec._compute_next_run_value()})
        return res

    @api.model
    def _cron_run_scheduled_automations(self, batch_size=100):
        now = fields.Datetime.now()
        domain = [
            ("active", "=", True),
            ("trigger_type", "=", "schedule"),
            ("next_run_at", "!=", False),
            ("next_run_at", "<=", now),
        ]
        nodes = self.search(domain, limit=max(1, int(batch_size)))
        for node in nodes:
            node._run_once()

    def _run_once(self):
        for node in self:
            run = self.env["workflow.automation.run"].sudo().create(
                {
                    "automation_node_id": node.id,
                    "status": "running",
                    "started_at": fields.Datetime.now(),
                }
            )
            try:
                # Implementation hook: enterprise-specific executor can extend this.
                affected = 0
                node.sudo().write(
                    {
                        "last_run_at": fields.Datetime.now(),
                        "next_run_at": node._compute_next_run_value(),
                    }
                )
                run.sudo().write(
                    {
                        "status": "success",
                        "ended_at": fields.Datetime.now(),
                        "affected_count": affected,
                    }
                )
            except Exception as error:
                _logger.exception("Workflow automation node run failed: %s", node.id)
                run.sudo().write(
                    {
                        "status": "failed",
                        "ended_at": fields.Datetime.now(),
                        "error_message": str(error),
                    }
                )
                if node.failure_policy == "ignore":
                    node.sudo().write({"next_run_at": node._compute_next_run_value()})


class WorkflowRequestAutomationInstance(models.Model):
    _name = "workflow.request.automation.instance"
    _description = "Workflow Request Automation Instance"
    _order = "id desc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="set null",
        index=True,
    )
    automation_node_id = fields.Many2one(
        "workflow.automation.node",
        ondelete="set null",
        index=True,
        help="Design-time automation definition that produced this runtime instance.",
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    version_id = fields.Many2one(related="request_id.version_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)

    node_id = fields.Char(required=True, index=True)
    node_name = fields.Char()
    node_type = fields.Char(index=True)
    branch_node_id = fields.Char(index=True)
    gateway_node_id = fields.Char(index=True)
    join_key = fields.Char(index=True)
    iteration_no = fields.Integer(default=1, required=True, index=True)

    trigger_type = fields.Selection(
        [
            ("automation", "Automation"),
            ("timer", "Timer"),
            ("transition", "Transition"),
        ],
        default="automation",
        required=True,
        index=True,
    )
    action_type = fields.Selection(
        AUTOMATION_ACTION_SELECTION,
        default="transition",
        required=True,
        index=True,
    )
    status = fields.Selection(
        AUTOMATION_INSTANCE_STATUS_SELECTION,
        default="scheduled",
        required=True,
        index=True,
    )
    required = fields.Boolean(
        default=False,
        help="If enabled, the runtime instance is on the critical execution path.",
    )
    failure_policy = fields.Selection(
        AUTOMATION_FAILURE_POLICY_SELECTION,
        default="retry",
        required=True,
    )
    timeout_seconds = fields.Integer(default=30)
    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=0)

    due_at = fields.Datetime(index=True)
    started_at = fields.Datetime(index=True)
    ended_at = fields.Datetime(index=True)
    cancelled_at = fields.Datetime(index=True)
    idempotency_key = fields.Char(required=True, index=True)
    payload_json = fields.Json(default=dict)
    result_json = fields.Json(default=dict)
    notification_audit_json = fields.Json(
        compute="_compute_notification_audit_json",
        readonly=True,
    )
    notification_audit_sent_summary = fields.Text(
        compute="_compute_notification_audit_json",
        readonly=True,
    )
    notification_audit_summary = fields.Text(
        compute="_compute_notification_audit_json",
        readonly=True,
    )
    error_message = fields.Text()
    recurrence_enabled = fields.Boolean(default=False)
    recurrence_mode = fields.Selection(
        [
            ("forever", "Forever"),
            ("count", "Fixed Count"),
            ("until", "Until Date"),
            ("until_success", "Until First Success"),
        ],
        default="forever",
        required=True,
    )
    recurrence_count = fields.Integer(default=0)
    recurrence_until = fields.Datetime()
    run_count = fields.Integer(default=0)

    _request_automation_iteration_positive = models.Constraint(
        "CHECK(iteration_no > 0)",
        "Iteration number must be positive.",
    )

    @api.depends("result_json")
    def _compute_notification_audit_json(self):
        for rec in self:
            result = rec.result_json or {}
            audit = result.get("notification_audit") or {}
            rec.notification_audit_json = audit
            rec.notification_audit_sent_summary = rec._notification_audit_build_sent_summary(audit)
            rec.notification_audit_summary = rec._notification_audit_build_summary(audit)

    @api.model
    def _notification_audit_unique_values(self, values):
        ordered = []
        seen = set()
        for value in values or []:
            normalized = str(value or "").strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
        return ordered

    @api.model
    def _notification_audit_user_labels(self, user_ids):
        ordered_ids = []
        seen = set()
        for user_id in user_ids or []:
            try:
                normalized_id = int(user_id)
            except (TypeError, ValueError):
                continue
            if normalized_id <= 0 or normalized_id in seen:
                continue
            seen.add(normalized_id)
            ordered_ids.append(normalized_id)
        if not ordered_ids:
            return []
        users = self.env["res.users"].sudo().browse(ordered_ids).exists()
        labels = []
        for user in users:
            email = (user.partner_id.email or "").strip()
            if email:
                labels.append(f"{user.name} <{email}>")
            else:
                labels.append(user.name or str(user.id))
        return labels

    @api.model
    def _notification_audit_entry_name(self, entry, index=0):
        return (
            entry.get("action_name")
            or entry.get("template_name")
            or _("Notification %s") % (index or 1)
        )

    @api.model
    def _notification_audit_status_label(self, status):
        status_map = {
            "sent": _("Sent"),
            "failed": _("Failed"),
            "suppressed": _("Suppressed"),
            "skipped_guard": _("Skipped: guard not matched"),
            "skipped_no_recipients": _("Skipped: no recipients"),
            "skipped_no_template": _("Skipped: no template"),
        }
        normalized = str(status or "").strip()
        if not normalized:
            return _("Unknown")
        return status_map.get(normalized, normalized.replace("_", " ").title())

    @api.model
    def _notification_audit_entry_detail_lines(self, entry):
        user_labels = self._notification_audit_user_labels(
            entry.get("resolved_user_ids")
            or entry.get("recipient_user_ids")
            or []
        )
        email_to = self._notification_audit_unique_values(entry.get("email_to") or [])
        email_cc = self._notification_audit_unique_values(entry.get("email_cc") or [])
        email_bcc = self._notification_audit_unique_values(entry.get("email_bcc") or [])
        fallback_emails = self._notification_audit_unique_values(
            (entry.get("recipient_emails") or []) + (entry.get("resolved_emails") or [])
        )
        lines = []
        if user_labels:
            lines.append(_("Users: %s") % ", ".join(user_labels))
        if email_to:
            lines.append(_("To: %s") % ", ".join(email_to))
        if email_cc:
            lines.append(_("CC: %s") % ", ".join(email_cc))
        if email_bcc:
            lines.append(_("BCC: %s") % ", ".join(email_bcc))
        if not email_to and not email_cc and not email_bcc and fallback_emails:
            lines.append(_("Recipients: %s") % ", ".join(fallback_emails))
        error_message = (entry.get("error_message") or entry.get("error") or "").strip()
        if error_message:
            lines.append(_("Error: %s") % error_message)
        return lines

    @api.model
    def _notification_audit_build_sent_summary(self, audit):
        entries = (audit or {}).get("entries") or []
        blocks = []
        for index, entry in enumerate(entries, start=1):
            if entry.get("status") != "sent":
                continue
            lines = [self._notification_audit_entry_name(entry, index=index)]
            lines.extend(self._notification_audit_entry_detail_lines(entry))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    @api.model
    def _notification_audit_build_summary(self, audit):
        entries = (audit or {}).get("entries") or []
        blocks = []
        for index, entry in enumerate(entries, start=1):
            title = "%s [%s]" % (
                self._notification_audit_entry_name(entry, index=index),
                self._notification_audit_status_label(entry.get("status")),
            )
            lines = [title]
            if entry.get("status") == "skipped_guard":
                lines.append(_("Request domain guard did not match."))
            lines.extend(self._notification_audit_entry_detail_lines(entry))
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
    _request_automation_retry_non_negative = models.Constraint(
        "CHECK(retry_count >= 0 AND max_retries >= 0)",
        "Retry counters must be non-negative.",
    )
    _request_automation_idempotency_unique = models.Constraint(
        "UNIQUE(request_id, idempotency_key)",
        "Duplicate request automation idempotency key is not allowed.",
    )

    def init(self):
        # Guard: skip index creation if the table doesn't exist yet (e.g., first
        # install or when check_tables_exist marks this model for recreation).
        self.env.cr.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'workflow_request_automation_instance'
            """
        )
        if not self.env.cr.fetchone():
            return
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_request_automation_due_status_idx
                ON workflow_request_automation_instance (status, due_at)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_request_automation_req_status_idx
                ON workflow_request_automation_instance (request_id, status)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_request_automation_node_status_idx
                ON workflow_request_automation_instance (automation_node_id, status)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_request_automation_req_node_iter_idx
                ON workflow_request_automation_instance (request_id, node_id, iteration_no)
            """
        )

    @api.model
    def _coerce_datetime(self, value):
        if not value:
            return False
        if isinstance(value, str):
            return fields.Datetime.to_datetime(value)
        return value

    @api.model
    def build_idempotency_key(
        self,
        *,
        request_id,
        node_id,
        iteration_no=1,
        branch_node_id=False,
        trigger_type="automation",
        action_type="transition",
        due_at=False,
    ):
        due_value = fields.Datetime.to_string(due_at) if due_at else ""
        raw = "|".join(
            [
                str(int(request_id or 0)),
                str(node_id or ""),
                str(branch_node_id or ""),
                str(int(iteration_no or 1)),
                str(trigger_type or ""),
                str(action_type or ""),
                due_value,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @api.model_create_multi
    def create(self, vals_list):
        seen = set()
        for vals in vals_list:
            scope = (vals.get("request_id"), vals.get("idempotency_key"))
            if not all(scope):
                continue
            if scope in seen:
                raise ValidationError(_("Duplicate request automation idempotency key is not allowed."))
            seen.add(scope)
            exists = self.sudo().search(
                [
                    ("request_id", "=", scope[0]),
                    ("idempotency_key", "=", scope[1]),
                ],
                limit=1,
            )
            if exists:
                raise ValidationError(_("Duplicate request automation idempotency key is not allowed."))
        return super().create(vals_list)

    @api.model
    def create_or_get(
        self,
        *,
        request_record,
        node_id=False,
        automation_node=False,
        task_instance=False,
        node_name=False,
        node_type=False,
        branch_node_id=False,
        gateway_node_id=False,
        join_key=False,
        trigger_type=False,
        action_type=False,
        due_at=False,
        failure_policy=False,
        timeout_seconds=False,
        required=False,
        iteration_no=False,
        payload_json=False,
        max_retries=False,
        idempotency_key=False,
        rearm_on_reentry=False,
        recurrence_enabled=False,
        recurrence_mode=False,
        recurrence_count=False,
        recurrence_until=False,
    ):
        if not request_record:
            raise ValidationError(_("Request is required to create a workflow automation instance."))
        request_record = request_record.sudo()
        automation_node = automation_node.sudo() if automation_node else self.env["workflow.automation.node"]
        task_instance = task_instance.sudo() if task_instance else self.env["workflow.request.task.instance"]

        node_id = node_id or (automation_node.node_id if automation_node else False)
        if not node_id:
            raise ValidationError(_("Node ID is required to create a workflow automation instance."))

        due_dt = self._coerce_datetime(due_at)
        iteration_no = int(iteration_no or request_record.current_iteration_no or 1)
        node_name = node_name or (automation_node.name if automation_node else False) or node_id
        node_type = node_type or (task_instance.node_type if task_instance else False) or False
        trigger_type = trigger_type or ("timer" if due_dt else "automation")
        action_type = action_type or (automation_node.action_type if automation_node else False) or "transition"
        idempotency_key = idempotency_key or self.build_idempotency_key(
            request_id=request_record.id,
            node_id=node_id,
            iteration_no=iteration_no,
            branch_node_id=branch_node_id,
            trigger_type=trigger_type,
            action_type=action_type,
            due_at=due_dt,
        )

        existing = self.sudo().search(
            [
                ("request_id", "=", request_record.id),
                ("idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if existing:
            if rearm_on_reentry and existing.status in ("success", "failed", "cancelled", "skipped", "blocked"):
                existing.sudo().write(
                    {
                        "task_instance_id": task_instance.id if task_instance else False,
                        "automation_node_id": automation_node.id if automation_node else False,
                        "node_name": node_name,
                        "node_type": node_type,
                        "branch_node_id": branch_node_id or False,
                        "gateway_node_id": gateway_node_id or False,
                        "join_key": join_key or False,
                        "iteration_no": iteration_no,
                        "trigger_type": trigger_type,
                        "action_type": action_type,
                        "status": "scheduled" if due_dt else "new",
                        "required": bool(required),
                        "failure_policy": failure_policy or (automation_node.failure_policy if automation_node else False) or "retry",
                        "timeout_seconds": int(timeout_seconds or (automation_node.timeout_seconds if automation_node else 30) or 30),
                        "max_retries": int(max_retries or 0),
                        "due_at": due_dt or False,
                        "payload_json": payload_json or {},
                        "recurrence_enabled": bool(recurrence_enabled),
                        "recurrence_mode": recurrence_mode or "forever",
                        "recurrence_count": int(recurrence_count or 0),
                        "recurrence_until": self._coerce_datetime(recurrence_until) or False,
                        "retry_count": 0,
                        "run_count": 0,
                        "started_at": False,
                        "ended_at": False,
                        "cancelled_at": False,
                        "result_json": {},
                        "error_message": False,
                    }
                )
            return existing

        vals = {
            "request_id": request_record.id,
            "task_instance_id": task_instance.id if task_instance else False,
            "automation_node_id": automation_node.id if automation_node else False,
            "node_id": node_id,
            "node_name": node_name,
            "node_type": node_type,
            "branch_node_id": branch_node_id or False,
            "gateway_node_id": gateway_node_id or False,
            "join_key": join_key or False,
            "iteration_no": iteration_no,
            "trigger_type": trigger_type,
            "action_type": action_type,
            "status": "scheduled" if due_dt else "new",
            "required": bool(required),
            "failure_policy": failure_policy or (automation_node.failure_policy if automation_node else False) or "retry",
            "timeout_seconds": int(timeout_seconds or (automation_node.timeout_seconds if automation_node else 30) or 30),
            "max_retries": int(max_retries or 0),
            "due_at": due_dt or False,
            "idempotency_key": idempotency_key,
            "payload_json": payload_json or {},
            "recurrence_enabled": bool(recurrence_enabled),
            "recurrence_mode": recurrence_mode or "forever",
            "recurrence_count": int(recurrence_count or 0),
            "recurrence_until": self._coerce_datetime(recurrence_until) or False,
        }
        try:
            return self.sudo().create(vals)
        except ValidationError:
            return self.sudo().search(
                [
                    ("request_id", "=", request_record.id),
                    ("idempotency_key", "=", idempotency_key),
                ],
                limit=1,
            )

    def is_due(self):
        self.ensure_one()
        if self.status not in ("new", "scheduled"):
            return False
        if not self.due_at:
            return True
        return self.due_at <= fields.Datetime.now()

    def mark_running(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.sudo().write(
                {
                    "status": "running",
                    "started_at": now,
                    "error_message": False,
                }
            )

    def mark_success(self, result_json=False, *, run_count=False, next_due_at=False):
        now = fields.Datetime.now()
        for rec in self:
            values = {
                "ended_at": now,
                "cancelled_at": False,
                "result_json": result_json or {},
                "error_message": False,
            }
            if run_count is not False:
                values["run_count"] = max(0, int(run_count or 0))
            if next_due_at:
                values.update(
                    {
                        "status": "scheduled",
                        "due_at": next_due_at,
                    }
                )
            else:
                values.update(
                    {
                        "status": "success",
                    }
                )
            rec.sudo().write(values)

    def _prepare_recurrence_after_success(self, meta_task=False, meta_action=False, execution_succeeded=True):
        self.ensure_one()
        completed_runs = max(0, int(self.run_count or 0)) + 1
        schedule_provider = meta_action or meta_task
        if not schedule_provider or not self.recurrence_enabled:
            return {
                "completed_runs": completed_runs,
                "next_due_at": False,
            }
        if meta_task and getattr(meta_task, "automation_run_mode", "immediate") != "scheduled":
            return {
                "completed_runs": completed_runs,
                "next_due_at": False,
            }

        mode = self.recurrence_mode or "forever"
        if mode == "until_success" and execution_succeeded:
            return {
                "completed_runs": completed_runs,
                "next_due_at": False,
            }
        if mode == "count":
            total_runs = max(0, int(self.recurrence_count or 0))
            if total_runs and completed_runs >= total_runs:
                return {
                    "completed_runs": completed_runs,
                    "next_due_at": False,
                }

        reference_dt = self._coerce_datetime(self.due_at) or fields.Datetime.now()
        now = fields.Datetime.now()
        if reference_dt < now:
            reference_dt = now
        next_due_at = schedule_provider._compute_automation_due_at(reference_dt=reference_dt)

        if mode == "until":
            until_dt = self._coerce_datetime(self.recurrence_until)
            if not until_dt or not next_due_at or next_due_at > until_dt:
                return {
                    "completed_runs": completed_runs,
                    "next_due_at": False,
                }

        return {
            "completed_runs": completed_runs,
            "next_due_at": next_due_at,
        }

    def mark_failed(self, error_message=False, *, retry_count=False, status="failed"):
        now = fields.Datetime.now()
        for rec in self:
            next_retry = rec.retry_count + 1 if retry_count is False else int(retry_count)
            rec.sudo().write(
                {
                    "status": status or "failed",
                    "ended_at": now,
                    "retry_count": max(0, next_retry),
                    "error_message": error_message or False,
                }
            )

    def schedule_retry(self, error_message=False, due_at=False):
        now = fields.Datetime.now()
        for rec in self:
            next_retry = (rec.retry_count or 0) + 1
            retry_due = due_at or (now + timedelta(minutes=min(max(next_retry, 1) * 5, 60)))
            rec.sudo().write(
                {
                    "status": "scheduled",
                    "retry_count": next_retry,
                    "due_at": retry_due,
                    "ended_at": now,
                    "error_message": error_message or False,
                }
            )

    def mark_cancelled(self, error_message=False):
        now = fields.Datetime.now()
        for rec in self:
            rec.sudo().write(
                {
                    "status": "cancelled",
                    "cancelled_at": now,
                    "ended_at": now,
                    "error_message": error_message or False,
                }
            )

    @api.model
    def _claim_due_instance_ids(self, batch_size=200):
        batch_size = max(1, int(batch_size or 200))
        now = fields.Datetime.now()
        self.env.cr.execute(
            """
            SELECT id
              FROM workflow_request_automation_instance
             WHERE status IN ('new', 'scheduled')
               AND (due_at IS NULL OR due_at <= %s)
             ORDER BY COALESCE(due_at, %s), id
             FOR UPDATE SKIP LOCKED
             LIMIT %s
            """,
            (now, now, batch_size),
        )
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def _cron_run_due_instances(self, batch_size=200):
        runtime_service = self.env["workflow.engine.runtime.service"]
        instance_ids = self._claim_due_instance_ids(batch_size=batch_size)
        for instance in self.sudo().browse(instance_ids):
            if not instance.exists():
                continue
            try:
                runtime_service.lock_request(instance.request_id.sudo())
                instance._run_once()
            except Exception as error:
                _logger.exception("Workflow request automation instance failed: %s", instance.id)
                if instance.failure_policy == "retry":
                    if instance.max_retries and (instance.retry_count or 0) >= instance.max_retries:
                        instance.mark_failed(str(error))
                    else:
                        instance.schedule_retry(str(error))
                elif instance.failure_policy == "ignore":
                    instance.mark_failed(str(error))
                else:
                    instance.mark_failed(str(error))

    def _run_once(self):
        for rec in self:
            if rec.status not in ("new", "scheduled") or not rec.is_due():
                continue
            request_record = rec.request_id.sudo()
            if not request_record or not request_record.exists():
                rec.mark_cancelled(_("Workflow request no longer exists."))
                continue
            delegate_record = request_record._get_transition_delegate_record()
            if not delegate_record or not hasattr(delegate_record, "_workflow_run_runtime_automation_instance"):
                rec.mark_failed(_("Workflow delegate record is not available for runtime automation."))
                continue
            delegate_record = delegate_record.with_context(
                workflow_skip_edit_scope=True,
                workflow_skip_field_policy=True,
            )
            delegate_record._workflow_run_runtime_automation_instance(rec)


class WorkflowAutomationRun(models.Model):
    _name = "workflow.automation.run"
    _description = "Workflow Automation Run Log"
    _order = "id desc"
    _check_company_auto = True

    automation_node_id = fields.Many2one(
        "workflow.automation.node",
        required=True,
        ondelete="cascade",
        index=True,
    )
    category_id = fields.Many2one(related="automation_node_id.category_id", store=True, index=True)
    version_id = fields.Many2one(related="automation_node_id.version_id", store=True, index=True)
    company_id = fields.Many2one(related="automation_node_id.company_id", store=True, index=True)
    request_id = fields.Many2one("workflow.base.approval.request", ondelete="set null", index=True)

    status = fields.Selection(
        [("running", "Running"), ("success", "Success"), ("failed", "Failed"), ("skipped", "Skipped")],
        default="running",
        required=True,
        index=True,
    )
    started_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    ended_at = fields.Datetime(index=True)
    duration_ms = fields.Integer(compute="_compute_duration_ms", store=True)
    affected_count = fields.Integer(default=0)
    error_message = fields.Text()
    payload_json = fields.Json(default=dict)

    @api.depends("started_at", "ended_at")
    def _compute_duration_ms(self):
        for rec in self:
            if rec.started_at and rec.ended_at:
                delta = rec.ended_at - rec.started_at
                rec.duration_ms = int(delta.total_seconds() * 1000)
            else:
                rec.duration_ms = 0


class WorkflowRequestDepartmentPayload(models.Model):
    _name = "workflow.request.department.payload"
    _description = "Workflow Department Confidential Payload"
    _order = "id desc"
    _check_company_auto = True

    request_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    task_instance_id = fields.Many2one(
        "workflow.request.task.instance",
        ondelete="set null",
        index=True,
    )
    category_id = fields.Many2one(related="request_id.category_id", store=True, index=True)
    company_id = fields.Many2one(related="request_id.company_id", store=True, index=True)
    department_id = fields.Many2one("hr.department", required=True, ondelete="cascade", index=True)

    key = fields.Char(required=True, index=True)
    iteration_no = fields.Integer(default=1, required=True, index=True)
    data_json = fields.Json(default=dict)
    is_confidential = fields.Boolean(default=True, index=True)

    _request_department_payload_unique = models.Constraint(
        "UNIQUE(request_id, department_id, key, iteration_no)",
        "Department payload already exists for this key and iteration.",
    )
    _request_department_payload_iteration_positive = models.Constraint(
        "CHECK(iteration_no > 0)",
        "Iteration must be positive.",
    )

    def export_pretty_json(self):
        self.ensure_one()
        return json.dumps(self.data_json or {}, indent=2, ensure_ascii=False)
