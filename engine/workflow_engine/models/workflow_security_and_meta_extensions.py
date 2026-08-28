# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.orm.domains import Domain

CREATE_ACCESS_MODE_SELECTION = [
    ("inherit_current_behavior", "All Workflow Users"),
    ("restricted", "Restricted"),
]


class WorkflowApprovalCategorySecurity(models.Model):
    _inherit = "workflow.approval.category"

    zero_trust_enforced = fields.Boolean(
        default=True,
        help="When enabled, category visibility is allowlist-only (users/groups/departments).",
    )
    allowed_user_ids = fields.Many2many(
        "res.users",
        "wf_category_allowed_user_rel",
        "category_id",
        "user_id",
        string="Allowed Users",
    )
    allowed_group_ids = fields.Many2many(
        "res.groups",
        "wf_category_allowed_group_rel",
        "category_id",
        "group_id",
        string="Allowed Groups",
    )
    allowed_department_ids = fields.Many2many(
        "hr.department",
        "wf_category_allowed_department_rel",
        "category_id",
        "department_id",
        string="Allowed Departments",
    )
    allow_requester_read = fields.Boolean(
        default=True,
        help="Allow requester/creator to read request header data.",
    )
    allow_manager_access = fields.Boolean(
        default=False,
        help="Allow request manager to read request and assigned department payloads (if scoped).",
    )
    allow_assignee_without_category_access = fields.Boolean(
        default=False,
        help="Allow users to be assigned even if they are outside category allowlist.",
    )
    default_fallback_policy = fields.Selection(
        [
            ("escalate_manager", "Escalate to Manager"),
            ("route_admin_queue", "Route to Workflow Admin Queue"),
            ("block", "Block Task"),
        ],
        default="route_admin_queue",
        required=True,
    )
    admin_queue_user_id = fields.Many2one(
        "res.users",
        string="Admin Queue Owner",
        help="Fallback assignee for unresolved tasks.",
    )
    group_can_share_id = fields.Many2one(
        "res.groups",
        string="Share Permission Group",
        help="Optional group allowed to share workflow tasks/visibility scopes.",
    )
    enable_force_transition = fields.Boolean(default=True)
    enable_mini_bus_updates = fields.Boolean(
        string="Enable Mini Bus Updates",
        default=False,
        help="Publish lightweight real-time request updates over bus for live BPMN refresh.",
    )
    create_access_mode = fields.Selection(
        CREATE_ACCESS_MODE_SELECTION,
        string="Request Creation Access",
        default="inherit_current_behavior",
        required=True,
        help=(
            "All Workflow Users lets any user with the Workflow Approval User group see this "
            "category and create requests. Restricted adds an allowlist for who may submit "
            "new requests in this category."
        ),
    )
    create_allowed_user_ids = fields.Many2many(
        "res.users",
        "wf_category_create_allowed_user_rel",
        "category_id",
        "user_id",
        string="Create Allowed Users",
        help="Users explicitly allowed to create requests when Request Creation Access is Restricted.",
    )
    create_allowed_group_ids = fields.Many2many(
        "res.groups",
        "wf_category_create_allowed_group_rel",
        "category_id",
        "group_id",
        string="Create Allowed Groups",
        help="Groups allowed to create requests when Request Creation Access is Restricted.",
    )
    create_allowed_department_ids = fields.Many2many(
        "hr.department",
        "wf_category_create_allowed_department_rel",
        "category_id",
        "department_id",
        string="Create Allowed Departments",
        help="Departments allowed to create requests when Request Creation Access is Restricted.",
    )
    can_create_request = fields.Boolean(
        string="Can Create Request",
        compute="_compute_can_create_request",
        compute_sudo=False,
        help="Technical UI flag using the same backend rule that protects new request creation.",
    )

    @api.depends_context("uid")
    @api.depends(
        "create_access_mode",
        "create_allowed_user_ids",
        "create_allowed_group_ids",
        "create_allowed_department_ids",
    )
    def _compute_can_create_request(self):
        user = self.env.user
        service = self.env["workflow.engine.permission.service"]
        if not user or not service._has_approval_workflow_group(user):
            for category in self:
                category.can_create_request = service._is_admin(user)
            return

        if service._is_admin(user):
            for category in self:
                category.can_create_request = True
            return

        effective_groups = service._user_effective_groups(user)
        department = user.department_id
        for category in self:
            if category.create_access_mode != "restricted":
                category.can_create_request = True
                continue
            category.can_create_request = bool(
                user in category.create_allowed_user_ids
                or category.create_allowed_group_ids & effective_groups
                or (
                    department
                    and department in category.create_allowed_department_ids
                )
            )

    def _create_access_match_sources(self, user=False):
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return []

        service = self.env["workflow.engine.permission.service"]
        if service._is_admin(user):
            return ["admin"]
        if not service._has_approval_workflow_group(user):
            return []
        if self.create_access_mode != "restricted":
            return ["inherit_current_behavior"]

        sources = []
        if user in self.create_allowed_user_ids:
            sources.append("create_allowed_user")
        if self.create_allowed_group_ids & service._user_effective_groups(user):
            sources.append("create_allowed_group")
        department = user.department_id
        if department and department in self.create_allowed_department_ids:
            sources.append("create_allowed_department")
        return sources

    def can_user_create_request(self, user=False):
        self.ensure_one()
        return bool(self._create_access_match_sources(user=user))

    def check_create_request_access(self, user=False):
        self.ensure_one()
        user = user or self.env.user
        if self.can_user_create_request(user=user):
            return True
        raise AccessError(
            _(
                "You are not allowed to create requests in workflow category '%(category)s'."
            )
            % {"category": self.display_name}
        )

    def check_access_rule(self, operation):
        super().check_access_rule(operation)
        if self.env.su:
            return
        service = self.env["workflow.engine.permission.service"]
        if operation == "read":
            denied = self.filtered(
                lambda c: not (
                    service._has_global_category_read_access(self.env.user)
                    or service.can_access_category(c, user=self.env.user)
                    or c.can_user_create_request(user=self.env.user)
                    or service._has_static_policy_category_access(c, self.env.user)
                    or service._has_visibility_category_access(c, self.env.user, scope="read")
                    or service._has_follower_category_access(c, self.env.user)
                )
            )
        else:
            denied = self.filtered(lambda c: not service.can_access_category(c, user=self.env.user))
        if denied:
            raise AccessError(_("You are not allowed to access one or more workflow categories."))


class WorkflowApprovalCategoryVersionSecurity(models.Model):
    _inherit = "workflow.approval.category.version"

    execution_profile = fields.Selection(
        [
            ("legacy", "Legacy Runtime"),
            ("runtime_v2", "Runtime V2"),
        ],
        default="legacy",
        required=True,
        copy=False,
        help=(
            "Legacy Runtime preserves current production execution. "
            "Runtime V2 opt-ins this workflow version into the new request-scoped runtime engine."
        ),
    )


class WorkflowBaseApprovalRequestSecurity(models.Model):
    _inherit = "workflow.base.approval.request"

    is_my_work_item = fields.Boolean(
        string="My Work Item",
        compute="_compute_scope_flags",
        search="_search_is_my_work_item",
    )
    is_my_contribution = fields.Boolean(
        string="My Contribution",
        compute="_compute_scope_flags",
        search="_search_is_my_contribution",
    )
    is_my_owned_request = fields.Boolean(
        string="My Request",
        compute="_compute_scope_flags",
        search="_search_is_my_owned_request",
    )
    is_shared_with_me = fields.Boolean(
        string="Shared With Me",
        compute="_compute_scope_flags",
        search="_search_is_shared_with_me",
    )
    is_delegated_to_me = fields.Boolean(
        string="Delegated To Me",
        compute="_compute_scope_flags",
        search="_search_is_delegated_to_me",
    )
    is_cc_or_bcc = fields.Boolean(
        string="CC/BCC",
        compute="_compute_scope_flags",
        search="_search_is_cc_or_bcc",
    )

    def _resolve_notification_recipients(self, meta_task, memo=False):
        self.ensure_one()
        return self.env["workflow.engine.assignment.domain.service"].resolve_notification_recipients(
            self,
            meta_task,
            memo=memo,
        )

    task_instance_ids = fields.One2many(
        "workflow.request.task.instance",
        "request_id",
        string="Task Instances",
        readonly=True,
    )
    action_assignment_ids = fields.One2many(
        "workflow.request.action.assignment",
        "request_id",
        string="Business Action Assignments",
        readonly=True,
    )
    visibility_scope_ids = fields.One2many(
        "workflow.request.visibility.scope",
        "request_id",
        string="Visibility Scopes",
        readonly=True,
    )
    visibility_scope_user_ids = fields.Many2many(
        "res.users",
        "wf_request_visibility_user_rel",
        "request_id",
        "user_id",
        string="Active Visibility Users",
        compute="_compute_visibility_scope_targets",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    visibility_scope_group_ids = fields.Many2many(
        "res.groups",
        "wf_request_visibility_group_rel",
        "request_id",
        "group_id",
        string="Active Visibility Groups",
        compute="_compute_visibility_scope_targets",
        store=True,
        compute_sudo=True,
        readonly=True,
    )
    task_event_ids = fields.One2many(
        "workflow.request.task.event",
        "request_id",
        string="Task Events",
        readonly=True,
    )
    department_payload_ids = fields.One2many(
        "workflow.request.department.payload",
        "request_id",
        string="Department Payloads",
        readonly=True,
    )
    automation_instance_ids = fields.One2many(
        "workflow.request.automation.instance",
        "request_id",
        string="Automation Instances",
        readonly=True,
    )

    approver_decisions_ids = fields.One2many(
        'workflow.approval.approver', 'request_id',
        domain=[('show_in_decision_history', '=', True)]
    )

    @api.depends(
        "visibility_scope_ids.active",
        "visibility_scope_ids.scope",
        "visibility_scope_ids.allowed_user_id",
        "visibility_scope_ids.allowed_group_id",
        "visibility_scope_ids.expires_at",
    )
    def _compute_visibility_scope_targets(self):
        scopes_by_request = {request.id: [] for request in self if request.id}
        if scopes_by_request:
            now = fields.Datetime.now()
            scopes = self.env["workflow.request.visibility.scope"].sudo().with_context(active_test=False).search([
                ("request_id", "in", list(scopes_by_request)),
                ("active", "=", True),
                ("scope", "in", ["read", "edit", "decision"]),
                "|",
                    ("expires_at", "=", False),
                    ("expires_at", ">=", now),
            ])
            for scope in scopes:
                scopes_by_request.setdefault(scope.request_id.id, []).append(scope)
        for request in self:
            user_ids = set()
            group_ids = set()
            for scope in scopes_by_request.get(request.id, []):
                if scope.allowed_user_id:
                    user_ids.add(scope.allowed_user_id.id)
                if scope.allowed_group_id:
                    group_ids.add(scope.allowed_group_id.id)
            request.visibility_scope_user_ids = [(6, 0, sorted(user_ids))]
            request.visibility_scope_group_ids = [(6, 0, sorted(group_ids))]

    @api.depends_context("uid")
    def _compute_scope_flags(self):
        uid = self.env.uid
        for rec in self:
            rec.is_my_owned_request = bool(rec.request_owner_id.id == uid or rec.create_uid.id == uid)
            rec.is_my_work_item = False
            rec.is_my_contribution = False
            rec.is_shared_with_me = False
            rec.is_delegated_to_me = False
            rec.is_cc_or_bcc = False

    @api.model
    def _bool_search_positive(self, operator, value):
        if operator not in ("=", "!="):
            return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            value_bool = normalized in ("1", "true", "yes", "y")
        else:
            value_bool = bool(value)
        return (operator == "=" and value_bool) or (operator == "!=" and not value_bool)

    @api.model
    def _finalize_scope_search(self, operator, value, positive_domain):
        positive = self._bool_search_positive(operator, value)
        if positive:
            return positive_domain
        matched_ids = self.search(positive_domain).ids
        return [("id", "in", matched_ids or [0])]

    @api.model
    def _domain_or(self, domains):
        normalized = [Domain(domain) for domain in domains if domain]
        if not normalized:
            return [("id", "=", 0)]
        return list(Domain.OR(normalized))

    @api.model
    def _domain_and(self, domains):
        normalized = [Domain(domain) for domain in domains if domain]
        if not normalized:
            return []
        return list(Domain.AND(normalized))

    @api.model
    def _domain_shared_with_me(self):
        uid = self.env.uid
        user_groups = self.env.user.all_group_ids if hasattr(self.env.user, "all_group_ids") else self.env.user.groups_id
        visibility_domain = [
            "|",
            ("visibility_scope_user_ids", "in", [uid]),
            ("visibility_scope_group_ids", "in", user_groups.ids or [0]),
        ]
        shared_request_ids = self.env["workflow.approval.approver"].sudo().search(
            [
                ("user_id", "=", uid),
                ("delegation_mode", "=", "shared"),
                ("delegated_from_user_id", "!=", False),
                ("status", "in", ("new", "pending", "waiting")),
                ("request_id.state", "=", "waiting"),
            ]
        ).mapped("request_id").ids
        if not shared_request_ids:
            return visibility_domain
        return self._domain_or([visibility_domain, [("id", "in", shared_request_ids)]])

    @api.model
    def _domain_open_work_request_ids_for_user(self, user_id):
        """Return request ids with an open work assignment for exactly user_id.

        Do not express this as multiple one2many leaf domains on approver_ids:
        Odoo may satisfy `approver_ids.user_id = X` from one historical row and
        `approver_ids.status in open` from another user's current row.
        """
        open_approver_statuses = ("new", "pending", "waiting")
        open_task_statuses = ("new", "pending", "in_progress", "rework")
        request_ids = set(
            self.env["workflow.approval.approver"].sudo().search([
                ("user_id", "=", user_id),
                ("status", "in", open_approver_statuses),
                ("request_id.state", "=", "waiting"),
            ]).mapped("request_id").ids
        )
        request_ids.update(
            self.env["workflow.request.task.assignee"].sudo().search([
                ("assignee_user_id", "=", user_id),
                ("status", "in", open_task_statuses),
                ("task_instance_id.request_id.state", "=", "waiting"),
            ]).mapped("task_instance_id.request_id").ids
        )
        return list(request_ids)

    @api.model
    def _domain_open_work_for_user(self, user_id):
        request_ids = self._domain_open_work_request_ids_for_user(user_id)
        if not request_ids:
            return [("id", "=", 0)]
        return [("id", "in", request_ids)]

    @api.model
    def _domain_delegated_to_me(self):
        uid = self.env.uid
        now = fields.Datetime.now()
        delegation_model = self.env["workflow.approval.delegation"].sudo()
        delegations = delegation_model.search(
            [
                ("delegate_user_id", "=", uid),
                ("active", "=", True),
                ("date_from", "<=", now),
                ("date_to", ">=", now),
            ]
        )
        if not delegations:
            return [("id", "=", 0)]

        branches = []
        for delegation in delegations:
            if not delegation.delegator_user_id:
                continue
            delegator_id = delegation.delegator_user_id.id
            delegated_branch = self._domain_open_work_for_user(delegator_id)
            if delegation.category_ids:
                delegated_branch = self._domain_and(
                    [[("category_id", "in", delegation.category_ids.ids)], delegated_branch]
                )
            branches.append(delegated_branch)

        manual_redirect_request_ids = self.env["workflow.approval.approver"].sudo().search(
            [
                ("user_id", "=", uid),
                ("delegation_mode", "=", "redirected"),
                ("delegated_from_user_id", "!=", False),
                ("status", "in", ("new", "pending", "waiting")),
                ("request_id.state", "=", "waiting"),
            ]
        ).mapped("request_id").ids
        if manual_redirect_request_ids:
            branches.append([("id", "in", manual_redirect_request_ids)])

        if not branches:
            return [("id", "=", 0)]
        return self._domain_or(branches)

    @api.model
    def _domain_my_work_item(self):
        uid = self.env.uid
        direct_work = self._domain_open_work_for_user(uid)
        delegated_work = self._domain_delegated_to_me()
        # A request must stay in My Work List whenever the current user still has
        # an open approval/task assignment, even if they also created or own it.
        return self._domain_or([direct_work, delegated_work])

    @api.model
    def _domain_my_contribution(self):
        uid = self.env.uid
        contribution_domain = self._domain_or(
            [
                [("approver_ids.user_id", "=", uid)],
                [("task_instance_ids.assignee_ids.assignee_user_id", "=", uid)],
                [("task_event_ids.actor_user_id", "=", uid)],
                [("task_event_ids.on_behalf_of_user_id", "=", uid)],
            ]
        )
        # Contribution is historical involvement. It excludes requests that still
        # require this actor's decision and requests that belong in My Request.
        return self._domain_and(
            [
                contribution_domain,
                list(~Domain(self._domain_my_work_item())),
                list(~Domain(self._domain_my_owned_request())),
            ]
        )

    @api.model
    def _domain_my_owned_request(self):
        uid = self.env.uid
        return [
            "|",
            ("owner_user_ids.user_id", "=", uid),
            "|",
            ("request_owner_id", "=", uid),
            ("create_uid", "=", uid),
        ]

    @api.model
    def _domain_cc_or_bcc(self):
        uid = self.env.uid
        return [("message_partner_ids.user_ids", "in", [uid])]

    def _search_is_my_work_item(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_my_work_item())

    def _search_is_my_contribution(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_my_contribution())

    def _search_is_my_owned_request(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_my_owned_request())

    def _search_is_shared_with_me(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_shared_with_me())

    def _search_is_delegated_to_me(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_delegated_to_me())

    def _search_is_cc_or_bcc(self, operator, value):
        return self._finalize_scope_search(operator, value, self._domain_cc_or_bcc())

    @api.depends_context("uid")
    @api.depends("current_node_id", "version_id", "to_approve_user_ids")
    def _compute_dynamic_fields(self):
        super()._compute_dynamic_fields()
        for request in self:
            invisible = set(request.invisible_fields or [])
            readonly = set(request.readonly_fields or []) | invisible
            required = set(request.required_fields or []) - invisible

            # Non-actors must not edit request payload at active workflow stages.
            # Keep admin/workflow-admin/active actor behavior unchanged.
            if not request.check_if_user_has_permission(request):
                required = set()
                readonly = set(request._fields.keys()) | invisible
                child_model_name = (request.res_model_name or "").strip()
                if child_model_name and child_model_name in self.env:
                    readonly |= set(self.env[child_model_name]._fields.keys())

            request.required_fields = sorted(required)
            request.readonly_fields = sorted(readonly)
            request.invisible_fields = sorted(invisible)

    def _check_access(self, operation):
        if self.env.su or operation == "create":
            return super()._check_access(operation)

        if self.env.context.get("workflow_history_mode"):
            if operation != "read":
                return self, lambda: AccessError(_("Workflow history is read-only."))
            allowed_ids = set(self._workflow_history_allowed_base_request_ids())
            denied = self.filtered(lambda record: record.id not in allowed_ids)
            if denied:
                return denied, lambda: AccessError(
                    _("You are not allowed to access one or more workflow history records.")
                )
            return None

        result = super()._check_access(operation)
        if result:
            return result

        service = self.env["workflow.engine.permission.service"]
        scope = "edit" if operation in ("write", "unlink") else "read"
        if scope == "read":
            allowed_ids = service.allowed_request_ids(self, user=self.env.user, scope=scope)
            denied = self.filtered(lambda record: record.id not in allowed_ids)
        else:
            denied = self.filtered(
                lambda record: not service.can_access_request(record, user=self.env.user, scope=scope)
            )
        if denied:
            return denied, lambda: AccessError(
                _("You are not allowed to access one or more workflow requests.")
            )
        return None

    def check_access_rule(self, operation):
        self.check_access(operation)
        return None


class WorkflowCategoryVersionMetaTaskSecurity(models.Model):
    _inherit = "workflow.category.version.meta.task"

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET push_notification_to_actor = TRUE
             WHERE push_notification_to_actor IS NULL
            """
        )
        self.env.cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notify_request_owner_email = TRUE
             WHERE notify_request_owner_email IS NULL
            """
        )
        self.env.cr.execute(
            """
            UPDATE workflow_category_version_meta_task
               SET notify_request_creator_email = TRUE
             WHERE notify_request_creator_email IS NULL
            """
        )

    assignment_mode = fields.Selection(
        [
            ("mixed", "Mixed"),
            ("explicit_users", "Explicit Users"),
            ("groups", "Groups"),
            ("domain", "Domain"),
            ("previous_actor", "Users From Workflow Node"),
            ("reentry_previous_actor", "Re-entry: Previous Actor"),
            ("request_owner", "Request Owner"),
        ],
        default="mixed",
        required=True,
    )
    explicit_user_ids = fields.Many2many(
        "res.users",
        "wf_meta_task_user_rel",
        "meta_task_id",
        "user_id",
        string="Explicit Users",
    )
    explicit_group_ids = fields.Many2many(
        "res.groups",
        "wf_meta_task_group_rel",
        "meta_task_id",
        "group_id",
        string="Explicit Groups",
    )
    assignment_user_domain = fields.Char(
        help="User domain literal used to resolve dynamic assignees without Python eval.",
    )
    completion_mode = fields.Selection(
        [("any", "Any"), ("all", "All")],
        default="any",
        required=True,
    )
    fallback_policy = fields.Selection(
        [
            ("escalate_manager", "Escalate to Manager"),
            ("route_admin_queue", "Route to Workflow Admin Queue"),
            ("block", "Block Task"),
        ],
        default="route_admin_queue",
        required=True,
    )
    fallback_user_id = fields.Many2one("res.users", string="Fallback User")

    # Parallel and join metadata
    join_key = fields.Char(help="Parallel join correlation key.")
    gateway_node_id = fields.Char(help="Gateway node identifier for joins.")
    join_policy = fields.Selection(
        [("all_of", "All Of"), ("any_of", "Any Of"), ("min_n", "Min N")],
        default="all_of",
        required=True,
    )
    join_min_n = fields.Integer(default=0)
    parallel_reject_policy = fields.Selection(
        [("strict", "Strict"), ("soft", "Soft")],
        default="strict",
        required=True,
    )

    # Historical assignment controls
    assign_to_previous_actor = fields.Boolean(string="Add Users From Workflow Node", default=False)
    previous_actor_node_ref = fields.Char(string="Assignment Source Node")
    assignment_source_user_type = fields.Selection(
        [
            ("assigned", "Assigned Users"),
            ("pending", "Pending Users"),
            ("decided", "Decided Users"),
        ],
        default="decided",
        required=True,
        help="When assignment mode is Users From Workflow Node, choose which users from the source node are assigned.",
    )
    assign_to_request_owner = fields.Boolean(default=False)
    reset_request_to_submit = fields.Boolean(
        string="Reset Request To Submit On Entry",
        default=False,
        help="When enabled, entering this stage reopens the request in To Submit state instead of Waiting Approval.",
    )
    push_notification_to_actor = fields.Boolean(
        string="Push Notification To Actor",
        default=True,
        help=(
            "When enabled, direct actor assignment on this stage creates workflow push/inbox notifications. "
            "Disable it to keep email behavior unchanged while silencing actor push/inbox on stage entry."
        ),
    )
    notify_request_owner_email = fields.Boolean(
        string="Notify Request Owner",
        default=True,
        help=(
            "When enabled, entering this node sends the request-owner update email. "
            "Submission stages remain silent even when this option is enabled."
        ),
    )
    notify_request_creator_email = fields.Boolean(
        string="Notify Request Creator",
        default=True,
        help=(
            "When enabled, entering this node sends the request-creator update email. "
            "Submission stages remain silent even when this option is enabled."
        ),
    )

    # Notification recipient controls
    notification_delivery_mode = fields.Selection(
        [
            ("email", "Send Email"),
            ("log", "Log Activity"),
            ("channels", "Channels"),
        ],
        string="Delivery Type",
        help="Empty keeps compatibility: selected channels run as Channels, otherwise Send Email.",
    )
    notification_recipient_source = fields.Selection(
        [
            ("specific_users", "Specific Users"),
            ("approval_group_users", "Workflow Approval Group Users"),
            ("group_users", "System Group Users"),
            ("node_users", "Users From Workflow Node"),
            ("domain", "Domain Over Users"),
        ],
        help="Optional new recipient source. Empty values keep legacy Recipient Mode behavior.",
    )
    notification_approval_group_ids = fields.Many2many(
        "workflow.approval.group",
        "workflow_meta_task_notification_approval_group_rel",
        "meta_task_id",
        "group_id",
        string="Notification Approval Groups",
    )
    notification_group_ids = fields.Many2many(
        "res.groups",
        "workflow_meta_task_notification_res_group_rel",
        "meta_task_id",
        "group_id",
        string="Notification System Groups",
    )
    notification_recipient_node_ref = fields.Char(string="Notification Source Node")
    notification_recipient_node_user_type = fields.Selection(
        [
            ("assigned", "Assigned Users"),
            ("pending", "Pending Users"),
            ("decided", "Decided Users"),
        ],
        default="assigned",
        required=True,
    )
    notification_recipient_filter_domain = fields.Char(
        help="Optional res.users domain used to further filter recipients resolved by the selected source.",
    )

    # Confidentiality controls
    confidentiality_level = fields.Selection(
        [("public", "Public"), ("department", "Department"), ("restricted", "Restricted")],
        default="public",
        required=True,
    )
    department_id = fields.Many2one("hr.department", string="Task Department")
    requires_department_payload = fields.Boolean(default=False)
    enable_share_override = fields.Boolean(default=True)
    service_behavior = fields.Selection(
        [
            ("router", "Router"),
            ("executor", "Executor"),
        ],
        default="router",
        required=True,
        help=(
            "Router keeps current service-task semantics and resolves the next route. "
            "Executor reserves the node for runtime_v2 automation execution."
        ),
    )

    @api.constrains("join_policy", "join_min_n", "service_behavior", "node_type")
    def _check_join_policy(self):
        for rec in self:
            if rec.join_policy == "min_n" and rec.join_min_n <= 0:
                raise ValidationError(_("Min N join policy requires join_min_n > 0."))
            if rec.service_behavior != "router" and rec.node_type != "serviceTask":
                raise ValidationError(_("Service behavior is only supported on BPMN service tasks."))


class WorkflowCategoryVersionMetaTaskActionSecurity(models.Model):
    _inherit = "workflow.category.version.meta.task.action"

    comment_required = fields.Boolean(default=True)
    comment_required_domain = fields.Char(
        string="Comment Required Domain",
        default=False,
        help="Optional request domain. The comment input is required only when this domain matches.",
    )
    require_2fa = fields.Boolean(default=False)
    twofa_method = fields.Selection(
        [("email_otp", "Email OTP"), ("qr", "QR")],
        default="email_otp",
    )
    twofa_condition_domain = fields.Char(
        help="Optional request domain to conditionally require 2FA for this action.",
    )
    required_rule_set_id = fields.Many2one(
        "workflow.field.rule.set",
        string="Action Rule Set",
        help="Optional rule set evaluated at action-time for required field validation.",
    )
    idempotency_required = fields.Boolean(default=True)
