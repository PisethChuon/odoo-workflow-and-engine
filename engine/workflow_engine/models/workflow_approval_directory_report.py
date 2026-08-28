# -*- coding: utf-8 -*-

from odoo import _, api, fields, models, tools
from odoo.tools import SQL


ASSIGNMENT_MODES = [
    ("mixed", "Mixed"),
    ("explicit_users", "Explicit Users"),
    ("groups", "Groups"),
    ("domain", "Domain"),
    ("previous_actor", "Users From Workflow Node"),
    ("reentry_previous_actor", "Re-entry: Previous Actor"),
    ("request_owner", "Request Owner"),
]


class WorkflowApprovalDirectoryReport(models.Model):
    _name = "workflow.approval.directory.report"
    _description = "Workflow Approval Directory"
    _auto = False
    _rec_name = "meta_task_id"
    _order = (
        "category_id, task_sequence, meta_task_id, group_department_id, "
        "team_id, line_id, approval_group_id, source_type"
    )

    category_id = fields.Many2one(
        "workflow.approval.category",
        string="Workflow Category",
        readonly=True,
    )
    version_id = fields.Many2one(
        "workflow.approval.category.version",
        string="Workflow Version",
        readonly=True,
    )
    version_active = fields.Boolean(string="Active Version", readonly=True)
    request_model_id = fields.Many2one("ir.model", string="Request Model", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)

    meta_task_id = fields.Many2one(
        "workflow.category.version.meta.task",
        string="Workflow Activity",
        readonly=True,
    )
    task_sequence = fields.Integer(string="Activity Sequence", readonly=True)
    node_id = fields.Char(string="BPMN Node ID", readonly=True)
    node_type = fields.Char(string="Workflow Node Type", readonly=True)
    assignment_mode = fields.Selection(
        ASSIGNMENT_MODES,
        string="Approval Assignment Mode",
        readonly=True,
    )
    completion_mode = fields.Selection(
        [("any", "Any"), ("all", "All")],
        string="Approval Completion Mode",
        readonly=True,
    )

    source_type = fields.Selection(
        [
            ("approval_group", "Workflow Approval Group"),
            ("explicit_users", "Specific Users"),
            ("system_group", "System Security Group"),
            ("assignment_domain", "Dynamic User Rule"),
            ("request_owner", "Request Owner"),
            ("previous_actor", "Users From Workflow Node"),
            ("fallback_domain", "Fallback User Rule"),
            ("runtime_fallback", "Runtime Fallback Policy"),
        ],
        string="Approver Source",
        readonly=True,
    )
    source_usage = fields.Selection(
        [
            ("primary", "Primary"),
            ("additive", "Additional Source"),
            ("first_entry_fallback", "First-entry Fallback"),
            ("no_candidate_fallback", "No-candidate Fallback"),
        ],
        string="Source Usage",
        readonly=True,
    )
    resolution_type = fields.Selection(
        [
            ("fixed", "Fixed List"),
            ("conditional_pool", "Conditional Pool"),
            ("dynamic_request", "Resolved Per Request"),
            ("workflow_history", "Resolved From Workflow History"),
            ("fallback", "Fallback Only"),
        ],
        string="Resolution",
        readonly=True,
    )
    routing_reference = fields.Selection(
        [
            ("all_requests", "All Requests"),
            ("request_creator", "Request Creator"),
            ("request_owner", "Request Owner"),
            ("creator_and_owner", "Creator and Request Owner"),
            ("previous_actor", "Previous Workflow Actor"),
            ("request_data", "Request Data / Advanced Rule"),
        ],
        string="Routing Based On",
        readonly=True,
    )

    approval_group_id = fields.Many2one(
        "workflow.approval.group",
        string="Workflow Approval Group",
        readonly=True,
    )
    system_group_id = fields.Many2one(
        "res.groups",
        string="System Security Group",
        readonly=True,
    )
    group_department_id = fields.Many2one(
        "hr.department",
        string="Workflow Approval Department",
        readonly=True,
    )
    line_id = fields.Many2one(
        "workflow.approval.group.line",
        string="Workflow Approval Line",
        readonly=True,
    )
    team_id = fields.Many2one(
        "workflow.approval.group.team",
        string="Workflow Approval Team",
        readonly=True,
    )
    source_node_ref = fields.Char(string="Source Workflow Node", readonly=True)

    configured_member_count = fields.Integer(string="Configured Members", readonly=True)
    active_approver_count = fields.Integer(string="Active Configured Users", readonly=True)
    inactive_member_count = fields.Integer(string="Inactive Members", readonly=True)
    portal_member_count = fields.Integer(string="Portal/Shared Members", readonly=True)
    configured_user_ids = fields.Many2many(
        "res.users",
        string="Configured Users",
        compute="_compute_configured_user_ids",
        readonly=True,
    )
    approver_employee_codes = fields.Text(string="All Employee Codes", readonly=True)
    approver_employee_code_display = fields.Char(
        string="Employee Codes",
        compute="_compute_approver_employee_code_display",
    )
    approver_names = fields.Text(string="Active Configured User Names", readonly=True)
    approver_display = fields.Text(
        string="Configured Approvers / Dynamic Source",
        compute="_compute_approver_display",
    )
    is_dynamic = fields.Boolean(string="Dynamic Source", readonly=True)

    fallback_policy = fields.Selection(
        [
            ("escalate_manager", "Escalate to Manager"),
            ("route_admin_queue", "Route to Workflow Admin Queue"),
            ("block", "Block Task"),
        ],
        readonly=True,
    )
    fallback_user_id = fields.Many2one("res.users", string="Fallback User", readonly=True)
    record_domain = fields.Char(string="Approval Record Domain", readonly=True)
    user_filter_domain = fields.Char(string="Approval User Filter Domain", readonly=True)
    note = fields.Text(string="Note", readonly=True)

    @api.depends(
        "approval_group_id",
        "fallback_user_id",
        "meta_task_id",
        "source_type",
        "system_group_id",
    )
    def _compute_configured_user_ids(self):
        empty_users = self.env["res.users"]
        for row in self:
            users = empty_users
            if row.source_type == "approval_group":
                users = row.approval_group_id.sudo().user_ids
            elif row.source_type == "explicit_users":
                users = row.meta_task_id.sudo().explicit_user_ids
            elif row.source_type == "system_group":
                users = row.system_group_id.sudo().user_ids
            elif row.source_type == "runtime_fallback" and row.fallback_user_id:
                users = row.fallback_user_id.sudo()

            row.configured_user_ids = users.filtered(
                lambda user: user.active and not user.share
            )

    @api.depends("approver_employee_codes")
    def _compute_approver_employee_code_display(self):
        visible_code_limit = 4
        for row in self:
            codes = [
                code.strip()
                for code in (row.approver_employee_codes or "").split(",")
                if code.strip()
            ]
            visible_codes = codes[:visible_code_limit]
            display = ", ".join(visible_codes)
            remaining = len(codes) - len(visible_codes)
            if remaining:
                display = _("%(codes)s +%(remaining)s", codes=display, remaining=remaining)
            row.approver_employee_code_display = display

    @api.depends(
        "active_approver_count",
        "approver_names",
        "fallback_policy",
        "fallback_user_id",
        "source_node_ref",
        "source_type",
    )
    def _compute_approver_display(self):
        for row in self:
            if row.source_type == "request_owner":
                row.approver_display = _("Request owner (resolved for each request)")
            elif row.source_type == "previous_actor":
                source = row.source_node_ref or _("configured workflow node")
                row.approver_display = _(
                    "Users from %(source)s (resolved from workflow history)",
                    source=source,
                )
            elif row.source_type == "assignment_domain":
                row.approver_display = _("Dynamic user rule (resolved for each request)")
            elif row.source_type == "fallback_domain":
                row.approver_display = _("Fallback user rule (resolved only when needed)")
            elif row.source_type == "runtime_fallback":
                policy = dict(row._fields["fallback_policy"].selection).get(
                    row.fallback_policy,
                    _("runtime fallback"),
                )
                row.approver_display = _("%(policy)s (used only when no approver resolves)", policy=policy)
            elif row.active_approver_count == 0:
                row.approver_display = _("No active internal users configured")
            else:
                row.approver_display = _(
                    "%(count)s active configured users",
                    count=row.active_approver_count,
                )

    def init(self):
        meta_model = self.env["workflow.category.version.meta.task"]
        explicit_user_field = meta_model._fields["explicit_user_ids"]
        explicit_group_field = meta_model._fields["explicit_group_ids"]

        approval_group_user_field = self.env["workflow.approval.group"]._fields["user_ids"]
        system_group_user_field = self.env["res.groups"]._fields["user_ids"]

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL(
                """
                CREATE OR REPLACE VIEW %(table)s AS (
                    WITH configured_sources AS (
                        SELECT
                            'approval_group:' || link.id::text AS source_key,
                            ver.category_id,
                            ver.id AS version_id,
                            ver.is_active AS version_active,
                            COALESCE(ver.res_model_id, category.res_model) AS request_model_id,
                            category.company_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed') AS assignment_mode,
                            meta.completion_mode,
                            'approval_group'::varchar AS source_type,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') = 'reentry_previous_actor'
                                THEN 'first_entry_fallback'
                                ELSE 'primary'
                            END::varchar AS source_usage,
                            CASE
                                WHEN regexp_replace(
                                    COALESCE(link.domain, ''), '[[:space:]]+', '', 'g'
                                ) NOT IN ('', '[]', '[(1,''='',1)]')
                                  OR regexp_replace(
                                      COALESCE(link.user_domain, ''), '[[:space:]]+', '', 'g'
                                  ) NOT IN ('', '[]', '[(1,''='',1)]')
                                THEN 'conditional_pool'
                                ELSE 'fixed'
                            END::varchar AS resolution_type,
                            CASE
                                WHEN (
                                    link.domain LIKE '%%create_uid%%'
                                    OR link.domain LIKE '%%request_creator_id%%'
                                ) AND link.domain LIKE '%%request_owner_id%%'
                                THEN 'creator_and_owner'
                                WHEN link.domain LIKE '%%create_uid%%'
                                  OR link.domain LIKE '%%request_creator_id%%'
                                THEN 'request_creator'
                                WHEN link.domain LIKE '%%request_owner_id%%'
                                THEN 'request_owner'
                                WHEN regexp_replace(
                                    COALESCE(link.domain, ''), '[[:space:]]+', '', 'g'
                                ) IN ('', '[]', '[(1,''='',1)]')
                                THEN 'all_requests'
                                ELSE 'request_data'
                            END::varchar AS routing_reference,
                            link.approval_group_id,
                            NULL::integer AS system_group_id,
                            NULL::varchar AS source_node_ref,
                            link.domain AS record_domain,
                            link.user_domain AS user_filter_domain,
                            link.note,
                            FALSE AS is_dynamic,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_task_approval_group link
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = link.meta_id
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND COALESCE(meta.assignment_mode, 'mixed') IN (
                              'mixed', 'groups', 'reentry_previous_actor'
                          )

                        UNION ALL

                        SELECT
                            'explicit_users:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'explicit_users'::varchar,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') = 'reentry_previous_actor'
                                THEN 'first_entry_fallback'
                                ELSE 'primary'
                            END::varchar,
                            'fixed'::varchar,
                            'all_requests'::varchar,
                            NULL::integer,
                            NULL::integer,
                            NULL::varchar,
                            NULL::varchar,
                            NULL::varchar,
                            meta.description,
                            FALSE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND COALESCE(meta.assignment_mode, 'mixed') IN (
                              'mixed', 'explicit_users', 'reentry_previous_actor'
                          )
                          AND EXISTS (
                              SELECT 1
                              FROM %(explicit_user_rel)s explicit_user_rel
                              WHERE explicit_user_rel.%(explicit_user_meta_col)s = meta.id
                          )

                        UNION ALL

                        SELECT
                            'system_group:' || meta.id::text || ':' || explicit_group_rel.%(explicit_group_group_col)s::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'system_group'::varchar,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') = 'reentry_previous_actor'
                                THEN 'first_entry_fallback'
                                ELSE 'primary'
                            END::varchar,
                            'fixed'::varchar,
                            'all_requests'::varchar,
                            NULL::integer,
                            explicit_group_rel.%(explicit_group_group_col)s,
                            NULL::varchar,
                            NULL::varchar,
                            NULL::varchar,
                            meta.description,
                            FALSE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        JOIN %(explicit_group_rel)s explicit_group_rel
                          ON explicit_group_rel.%(explicit_group_meta_col)s = meta.id
                        WHERE meta.node_type = 'userTask'
                          AND COALESCE(meta.assignment_mode, 'mixed') IN (
                              'mixed', 'groups', 'reentry_previous_actor'
                          )

                        UNION ALL

                        SELECT
                            'assignment_domain:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'assignment_domain'::varchar,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') = 'reentry_previous_actor'
                                THEN 'first_entry_fallback'
                                ELSE 'primary'
                            END::varchar,
                            'dynamic_request'::varchar,
                            CASE
                                WHEN (
                                    meta.assignment_user_domain LIKE '%%create_uid%%'
                                    OR meta.assignment_user_domain LIKE '%%request_creator_id%%'
                                ) AND meta.assignment_user_domain LIKE '%%request_owner_id%%'
                                THEN 'creator_and_owner'
                                WHEN meta.assignment_user_domain LIKE '%%create_uid%%'
                                  OR meta.assignment_user_domain LIKE '%%request_creator_id%%'
                                THEN 'request_creator'
                                WHEN meta.assignment_user_domain LIKE '%%request_owner_id%%'
                                THEN 'request_owner'
                                WHEN regexp_replace(
                                    COALESCE(meta.assignment_user_domain, ''),
                                    '[[:space:]]+',
                                    '',
                                    'g'
                                ) IN ('', '[]', '[(1,''='',1)]')
                                THEN 'all_requests'
                                ELSE 'request_data'
                            END::varchar,
                            NULL::integer,
                            NULL::integer,
                            NULL::varchar,
                            NULL::varchar,
                            meta.assignment_user_domain,
                            meta.description,
                            TRUE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND COALESCE(meta.assignment_mode, 'mixed') IN (
                              'mixed', 'domain', 'reentry_previous_actor'
                          )
                          AND btrim(COALESCE(meta.assignment_user_domain, '')) NOT IN ('', '[]')

                        UNION ALL

                        SELECT
                            'request_owner:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'request_owner'::varchar,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') = 'request_owner'
                                THEN 'primary'
                                ELSE 'additive'
                            END::varchar,
                            'dynamic_request'::varchar,
                            'request_owner'::varchar,
                            NULL::integer,
                            NULL::integer,
                            NULL::varchar,
                            NULL::varchar,
                            NULL::varchar,
                            meta.description,
                            TRUE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND (
                              COALESCE(meta.assignment_mode, 'mixed') = 'request_owner'
                              OR (
                                  meta.assign_to_request_owner
                                  AND COALESCE(meta.assignment_mode, 'mixed') NOT IN (
                                      'request_owner', 'reentry_previous_actor'
                                  )
                              )
                          )

                        UNION ALL

                        SELECT
                            'previous_actor:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'previous_actor'::varchar,
                            CASE
                                WHEN COALESCE(meta.assignment_mode, 'mixed') IN (
                                    'previous_actor', 'reentry_previous_actor'
                                )
                                THEN 'primary'
                                ELSE 'additive'
                            END::varchar,
                            'workflow_history'::varchar,
                            'previous_actor'::varchar,
                            NULL::integer,
                            NULL::integer,
                            COALESCE(NULLIF(meta.previous_actor_node_ref, ''), meta.node_id),
                            NULL::varchar,
                            NULL::varchar,
                            meta.description,
                            TRUE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND (
                              COALESCE(meta.assignment_mode, 'mixed') IN (
                                  'previous_actor', 'reentry_previous_actor'
                              )
                              OR (
                                  meta.assign_to_previous_actor
                                  AND COALESCE(meta.assignment_mode, 'mixed') NOT IN (
                                      'previous_actor', 'reentry_previous_actor'
                                  )
                              )
                          )

                        UNION ALL

                        SELECT
                            'fallback_domain:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'fallback_domain'::varchar,
                            'no_candidate_fallback'::varchar,
                            'fallback'::varchar,
                            'request_data'::varchar,
                            NULL::integer,
                            NULL::integer,
                            NULL::varchar,
                            NULL::varchar,
                            meta.approval_group_domain,
                            meta.description,
                            TRUE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND COALESCE(meta.assignment_mode, 'mixed') IN ('mixed', 'groups', 'domain')
                          AND btrim(COALESCE(meta.approval_group_domain, '')) NOT IN ('', '[]')
                    ),
                    source_config AS (
                        SELECT * FROM configured_sources

                        UNION ALL

                        SELECT
                            'runtime_fallback:' || meta.id::text,
                            ver.category_id,
                            ver.id,
                            ver.is_active,
                            COALESCE(ver.res_model_id, category.res_model),
                            category.company_id,
                            meta.id,
                            meta.sequence,
                            meta.node_id,
                            meta.node_type,
                            COALESCE(meta.assignment_mode, 'mixed'),
                            meta.completion_mode,
                            'runtime_fallback'::varchar,
                            'no_candidate_fallback'::varchar,
                            'fallback'::varchar,
                            'request_data'::varchar,
                            NULL::integer,
                            NULL::integer,
                            NULL::varchar,
                            NULL::varchar,
                            NULL::varchar,
                            meta.description,
                            TRUE,
                            meta.fallback_policy,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category category
                          ON category.id = ver.category_id
                        WHERE meta.node_type = 'userTask'
                          AND NOT EXISTS (
                              SELECT 1
                              FROM configured_sources configured
                              WHERE configured.meta_task_id = meta.id
                                AND configured.source_usage != 'no_candidate_fallback'
                          )
                    ),
                    source_users AS (
                        SELECT
                            'approval_group:' || link.id::text AS source_key,
                            approval_user_rel.%(approval_user_user_col)s AS user_id
                        FROM workflow_category_task_approval_group link
                        JOIN %(approval_user_rel)s approval_user_rel
                          ON approval_user_rel.%(approval_user_group_col)s = link.approval_group_id

                        UNION ALL

                        SELECT
                            'explicit_users:' || explicit_user_rel.%(explicit_user_meta_col)s::text,
                            explicit_user_rel.%(explicit_user_user_col)s
                        FROM %(explicit_user_rel)s explicit_user_rel

                        UNION ALL

                        SELECT
                            'system_group:' || explicit_group_rel.%(explicit_group_meta_col)s::text
                                || ':' || explicit_group_rel.%(explicit_group_group_col)s::text,
                            system_user_rel.%(system_user_user_col)s
                        FROM %(explicit_group_rel)s explicit_group_rel
                        JOIN %(system_user_rel)s system_user_rel
                          ON system_user_rel.%(system_user_group_col)s = explicit_group_rel.%(explicit_group_group_col)s

                        UNION ALL

                        SELECT
                            'runtime_fallback:' || meta.id::text,
                            meta.fallback_user_id
                        FROM workflow_category_version_meta_task meta
                        WHERE meta.fallback_user_id IS NOT NULL
                    ),
                    user_summary AS (
                        SELECT
                            users.source_key,
                            COUNT(DISTINCT user_record.id) AS configured_member_count,
                            COUNT(DISTINCT user_record.id) FILTER (
                                WHERE user_record.active AND NOT user_record.share
                            ) AS active_approver_count,
                            COUNT(DISTINCT user_record.id) FILTER (
                                WHERE NOT user_record.active
                            ) AS inactive_member_count,
                            COUNT(DISTINCT user_record.id) FILTER (
                                WHERE user_record.active AND user_record.share
                            ) AS portal_member_count,
                            string_agg(
                                DISTINCT COALESCE(partner.name, user_record.login),
                                ', ' ORDER BY COALESCE(partner.name, user_record.login)
                            ) FILTER (
                                WHERE user_record.active AND NOT user_record.share
                            ) AS approver_names,
                            string_agg(
                                DISTINCT COALESCE(employee.x_emp_code, user_record.emp_code),
                                ', ' ORDER BY COALESCE(employee.x_emp_code, user_record.emp_code)
                            ) FILTER (
                                WHERE user_record.active
                                  AND NOT user_record.share
                                  AND NULLIF(
                                      btrim(COALESCE(employee.x_emp_code, user_record.emp_code)),
                                      ''
                                  ) IS NOT NULL
                            ) AS approver_employee_codes
                        FROM source_users users
                        JOIN source_config configured
                          ON configured.source_key = users.source_key
                        JOIN res_users user_record
                          ON user_record.id = users.user_id
                        LEFT JOIN LATERAL (
                            SELECT hr_employee.x_emp_code
                            FROM hr_employee
                            WHERE hr_employee.user_id = user_record.id
                            ORDER BY hr_employee.active DESC, hr_employee.id
                            LIMIT 1
                        ) employee ON TRUE
                        LEFT JOIN res_partner partner
                          ON partner.id = user_record.partner_id
                        GROUP BY users.source_key
                    )
                    SELECT
                        row_number() OVER (ORDER BY configured.source_key) AS id,
                        configured.category_id,
                        configured.version_id,
                        configured.version_active,
                        configured.request_model_id,
                        configured.company_id,
                        configured.meta_task_id,
                        configured.task_sequence,
                        configured.node_id,
                        configured.node_type,
                        configured.assignment_mode,
                        configured.completion_mode,
                        configured.source_type,
                        configured.source_usage,
                        configured.resolution_type,
                        configured.routing_reference,
                        configured.approval_group_id,
                        configured.system_group_id,
                        approval_group.department_id AS group_department_id,
                        approval_group.line_id,
                        approval_group.team_id,
                        configured.source_node_ref,
                        COALESCE(summary.configured_member_count, 0) AS configured_member_count,
                        COALESCE(summary.active_approver_count, 0) AS active_approver_count,
                        COALESCE(summary.inactive_member_count, 0) AS inactive_member_count,
                        COALESCE(summary.portal_member_count, 0) AS portal_member_count,
                        summary.approver_employee_codes,
                        summary.approver_names,
                        configured.is_dynamic,
                        configured.fallback_policy,
                        configured.fallback_user_id,
                        configured.record_domain,
                        configured.user_filter_domain,
                        configured.note
                    FROM source_config configured
                    LEFT JOIN user_summary summary
                      ON summary.source_key = configured.source_key
                    LEFT JOIN workflow_approval_group approval_group
                      ON approval_group.id = configured.approval_group_id
                )
                """,
                table=SQL.identifier(self._table),
                approval_user_rel=SQL.identifier(approval_group_user_field.relation),
                approval_user_group_col=SQL.identifier(approval_group_user_field.column1),
                approval_user_user_col=SQL.identifier(approval_group_user_field.column2),
                explicit_user_rel=SQL.identifier(explicit_user_field.relation),
                explicit_user_meta_col=SQL.identifier(explicit_user_field.column1),
                explicit_user_user_col=SQL.identifier(explicit_user_field.column2),
                explicit_group_rel=SQL.identifier(explicit_group_field.relation),
                explicit_group_meta_col=SQL.identifier(explicit_group_field.column1),
                explicit_group_group_col=SQL.identifier(explicit_group_field.column2),
                system_user_rel=SQL.identifier(system_group_user_field.relation),
                system_user_group_col=SQL.identifier(system_group_user_field.column1),
                system_user_user_col=SQL.identifier(system_group_user_field.column2),
            )
        )
