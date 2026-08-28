from collections import defaultdict, deque
from datetime import timezone
from odoo import api, Command, fields, models, _
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE

class ApprovalApprover(models.Model):
    _name = 'workflow.approval.approver'
    _description = 'Approver'
    _order = 'id asc'
    # _rec_name = 'res_name'

    _check_company_auto = True

    sequence = fields.Integer('Sequence', default=10)
    iteration_no = fields.Integer(
        string='Iteration',
        default=0,
        index=True,
        help="Workflow cycle number. Increments on submission and loopback revisits to completed stages.",
    )
    event_order = fields.Integer(
        string="Step",
        default=0,
        index=True,
        help="Order of events inside the same cycle (iteration).",
    )
    current_meta_id = fields.Many2one('workflow.category.version.meta.task', string='Activity (Technical)',
                                      ondelete='cascade',
                                      required=True)
    
    current_meta_node_id = fields.Char(
        'Activity Node ID',
        related='current_meta_id.node_id',
        readonly=True,
        store=True,
        index=True,
    )

    previous_meta_id = fields.Many2one('workflow.category.version.meta.task', string='From Activity (Technical)',
                                       ondelete='cascade',
                                       required=True)
    
    user_id = fields.Many2one(
        'res.users',
        string="User",
        required=True,
        check_company=True,
        ondelete='cascade',
        index=True,
    )
    
    employee_id = fields.Many2one('hr.employee', string="Employee", related='user_id.employee_id', store=True, readonly=True)
    employee_name = fields.Char(string="Approver", related='employee_id.name', store=False, readonly=True)
    emp_code = fields.Char(related='employee_id.x_emp_code', store=False, readonly=True)
    avatar_128 = fields.Image(related='employee_id.avatar_128')
    job_id = fields.Many2one(related='employee_id.job_id', store=False, readonly=True)
    job_name = fields.Char(string="Position", related='job_id.name', store=False, readonly=True)
    department_id = fields.Many2one(string="Department", related='employee_id.department_id', store=False, readonly=True)
    department_name = fields.Char(string="Department Name", related='department_id.name', store=False, readonly=True)
    ext_phone = fields.Char(related='employee_id.x_ext_phone', store=False, readonly=True)
    work_email = fields.Char(
        string="Work Email",
        compute="_compute_work_email",
        store=False,
        readonly=True,
        compute_sudo=True,
    )
    mobile_phone = fields.Char(related='employee_id.mobile_phone', store=False, readonly=True)

    name = fields.Char('Name', related='user_id.name')
    updated_date = fields.Datetime('Date', copy=False)
    activity_event_at = fields.Datetime(
        string="Activity On",
        copy=False,
        index=True,
    )
    activity_flow = fields.Char(
        string="Flow",
        compute="_compute_activity_flow",
        store=False,
    )
    stage_age_minutes = fields.Integer(
        string="Stage Age (Min)",
        compute="_compute_stage_age",
        store=False,
    )
    stage_age_display = fields.Char(
        string="Stage Age (Display)",
        compute="_compute_stage_age",
        store=False,
    )
    from_activity_label = fields.Char(
        string="From Activity",
        compute="_compute_activity_labels",
        store=False,
    )
    to_activity_label = fields.Char(
        string="Activity Name",
        compute="_compute_activity_labels",
        store=False,
    )
    activity_kind = fields.Selection(
        [
            ("assignment", "Assignment"),
            ("decision", "Decision"),
            ("system", "System"),
        ],
        string="Type",
        compute="_compute_activity_kind",
        store=False,
    )
    remark = fields.Text('Remark')
    comment = fields.Text('Comment')
    status = fields.Selection([
        ('new', 'New'),
        ('pending', 'To Approve'),
        ('waiting', 'Waiting'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancelled', 'Cancelled'),
        ('closed', 'Closed'),
        ('view', 'View'),
        ], string="Status", default="new", readonly=True, index=True)
    user_decision = fields.Char('Decision')
    has_decision = fields.Boolean(
        string="Has Decision",
        compute="_compute_has_decision",
        store=True,
        index=True,
    )
    is_routed_audit = fields.Boolean(
        string="Is Routed Audit",
        default=False,
        index=True,
        help="Marked when the row was auto-stamped as Routed during reroute or force transition.",
    )
    counts_as_decided_user = fields.Boolean(
        string="Counts As Decided User",
        compute="_compute_decision_history_flags",
        store=True,
        index=True,
        help="True only for real user decisions that should appear in decided-user reviews and helpers.",
    )
    decision_history_kind = fields.Selection(
        [
            ("workflow_decision", "Workflow Decision"),
            ("delegation_decision", "Delegation Decision"),
            ("system_audit", "System Audit"),
        ],
        string="Decision History Kind",
        compute="_compute_decision_history_flags",
        store=True,
        index=True,
        help="Classifies history rows for UI/reporting without changing approval-threshold logic.",
    )
    show_in_decision_history = fields.Boolean(
        string="Show In Decision History",
        compute="_compute_decision_history_flags",
        store=True,
        index=True,
        help="True for rows that should appear in the Decision(s) history tab.",
    )
    delegation_mode = fields.Selection(
        [("shared", "Shared"), ("redirected", "Redirected")],
        string="Delegation Mode",
        copy=False,
        index=True,
    )
    delegated_from_user_id = fields.Many2one(
        "res.users",
        string="Delegated From User",
        ondelete="set null",
        index=True,
        copy=False,
    )
    delegated_from_approver_id = fields.Many2one(
        "workflow.approval.approver",
        string="Delegated From Approver",
        ondelete="set null",
        index=True,
        copy=False,
    )
    delegated_to_user_id = fields.Many2one(
        "res.users",
        string="Delegated To User",
        ondelete="set null",
        index=True,
        copy=False,
    )
    delegated_by_user_id = fields.Many2one(
        "res.users",
        string="Delegated By",
        ondelete="set null",
        index=True,
        copy=False,
    )
    delegated_at = fields.Datetime(
        string="Delegated At",
        copy=False,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        store=True,
        readonly=True,
        index=True,
        compute='_compute_company_id',
    )
    required = fields.Boolean(default=False, readonly=True)
    
    # model = fields.Char('Related Document Model', required=True)
    request_id = fields.Many2one(
        'workflow.base.approval.request',
        string="Related request",
        help="This always links to workflow.base.approval.request",
        index=True,
    )
    x_legacy_source_id = fields.Integer(
        string="Legacy Source ID",
        readonly=True,
        copy=False,
        index=True,
    )

    is_owner = fields.Boolean(store=True, compute='_compute_is_owner', index=True)
    verified_version = fields.Integer('Verified Version', default=1)
    
    # Related helper (char)
    current_meta_workflow_map_ids = fields.One2many(
        related="current_meta_id.workflow_map_ids",
        string="Sub Workflow",
        readonly=False
    )
    
    called_workflow_ids = fields.Many2many(
        comodel_name="workflow.approval.category.version",
        string="Sub Workflows",
        compute="_compute_called_workflows",
        store=False,
    )

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_user_status_request_idx
                ON workflow_approval_approver (user_id, status, request_id)
                WHERE user_id IS NOT NULL AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_open_user_request_idx
                ON workflow_approval_approver (user_id, request_id)
                WHERE status IN ('new', 'pending', 'waiting')
                  AND user_id IS NOT NULL
                  AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_request_user_status_idx
                ON workflow_approval_approver (request_id, user_id, status)
                WHERE request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_owner_user_request_idx
                ON workflow_approval_approver (user_id, request_id)
                WHERE is_owner IS TRUE
                  AND user_id IS NOT NULL
                  AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_request_iteration_node_status_idx
                ON workflow_approval_approver (request_id, iteration_no, current_meta_node_id, status)
                WHERE request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_request_decision_latest_idx
                ON workflow_approval_approver (request_id, create_date DESC, id DESC)
                WHERE BTRIM(COALESCE(user_decision, '')) <> ''
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS wf_approver_shared_open_user_request_idx
                ON workflow_approval_approver (user_id, delegation_mode, delegated_from_user_id, status, request_id)
                WHERE delegation_mode IN ('shared', 'redirected')
                  AND delegated_from_user_id IS NOT NULL
                  AND user_id IS NOT NULL
                  AND request_id IS NOT NULL
            """
        )
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET iteration_no = 1
             WHERE iteration_no IS NULL OR iteration_no <= 0
            """
        )
        # Backfill historical records created before first-cycle iteration fix.
        # Symptoms:
        # - all rows for a request started at iteration 2
        # - no iteration 1 rows exist for that request
        # Safe normalization shifts those requests down by exactly one round.
        self.env.cr.execute("SELECT to_regclass('workflow_base_approval_request')")
        has_base_request_table = bool(self.env.cr.fetchone()[0])
        if has_base_request_table:
            self.env.cr.execute(
                """
                WITH offset_requests AS (
                    SELECT request_id
                      FROM workflow_approval_approver
                     WHERE request_id IS NOT NULL
                     GROUP BY request_id
                    HAVING MIN(COALESCE(iteration_no, 1)) = 2
                       AND SUM(CASE WHEN COALESCE(iteration_no, 1) = 1 THEN 1 ELSE 0 END) = 0
                ),
                shifted AS (
                    UPDATE workflow_approval_approver row
                       SET iteration_no = GREATEST(COALESCE(row.iteration_no, 1) - 1, 1)
                      FROM offset_requests req
                     WHERE row.request_id = req.request_id
                    RETURNING row.request_id
                )
                UPDATE workflow_base_approval_request req
                   SET current_iteration_no = GREATEST(COALESCE(req.current_iteration_no, 1) - 1, 1)
                 WHERE req.id IN (SELECT request_id FROM offset_requests)
                """
            )
            # Keep base-request iteration aligned with approver history after
            # any historical fixes or manual data edits.
            self.env.cr.execute(
                """
                WITH iteration_by_request AS (
                    SELECT
                        request_id,
                        GREATEST(MAX(COALESCE(iteration_no, 1)), 1) AS max_iteration
                    FROM workflow_approval_approver
                    WHERE request_id IS NOT NULL
                    GROUP BY request_id
                )
                UPDATE workflow_base_approval_request req
                   SET current_iteration_no = iteration_by_request.max_iteration
                  FROM iteration_by_request
                 WHERE req.id = iteration_by_request.request_id
                   AND COALESCE(req.current_iteration_no, 1) <> iteration_by_request.max_iteration
                """
            )
        else:
            self.env.cr.execute(
                """
                WITH offset_requests AS (
                    SELECT request_id
                      FROM workflow_approval_approver
                     WHERE request_id IS NOT NULL
                     GROUP BY request_id
                    HAVING MIN(COALESCE(iteration_no, 1)) = 2
                       AND SUM(CASE WHEN COALESCE(iteration_no, 1) = 1 THEN 1 ELSE 0 END) = 0
                )
                UPDATE workflow_approval_approver row
                   SET iteration_no = GREATEST(COALESCE(row.iteration_no, 1) - 1, 1)
                  FROM offset_requests req
                 WHERE row.request_id = req.request_id
                """
            )
        self.env.cr.execute(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY request_id, COALESCE(iteration_no, 1)
                        ORDER BY create_date ASC NULLS LAST, id ASC
                    ) AS rn
                FROM workflow_approval_approver
            )
            UPDATE workflow_approval_approver w
               SET event_order = ranked.rn
              FROM ranked
             WHERE ranked.id = w.id
               AND (w.event_order IS NULL OR w.event_order <= 0)
            """
        )
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET activity_event_at = CASE
                   WHEN BTRIM(COALESCE(user_decision, '')) != ''
                       THEN COALESCE(write_date, create_date)
                   WHEN status IN ('approved', 'refused', 'cancelled', 'closed', 'pending')
                       THEN COALESCE(write_date, create_date)
                   ELSE COALESCE(create_date, write_date)
               END
             WHERE activity_event_at IS NULL
            """
        )
        shared_labels = tuple(
            {
                label
                for label in (
                    self._decision_text("Shared").casefold(),
                    self._decision_text(_("Shared")).casefold(),
                )
                if label
            }
        )
        redirected_labels = tuple(
            {
                label
                for label in (
                    self._decision_text("Redirected").casefold(),
                    self._decision_text(_("Redirected")).casefold(),
                )
                if label
            }
        )
        routed_labels = tuple(
            {
                label
                for label in (
                    self._decision_text("Routed").casefold(),
                    self._decision_text(_("Routed")).casefold(),
                )
                if label
            }
        )
        delegation_labels = tuple(
            dict.fromkeys(shared_labels + redirected_labels)
        )
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET has_decision = BTRIM(COALESCE(user_decision, '')) != '',
                   decision_history_kind = CASE
                       WHEN BTRIM(COALESCE(user_decision, '')) = '' THEN NULL
                       WHEN COALESCE(is_routed_audit, FALSE) = TRUE OR LOWER(BTRIM(COALESCE(user_decision, ''))) = ANY(%s) THEN 'system_audit'
                       WHEN LOWER(BTRIM(COALESCE(user_decision, ''))) = ANY(%s) THEN 'delegation_decision'
                       ELSE 'workflow_decision'
                   END,
                   show_in_decision_history = CASE
                       WHEN BTRIM(COALESCE(user_decision, '')) = '' THEN FALSE
                       WHEN COALESCE(is_routed_audit, FALSE) = TRUE OR LOWER(BTRIM(COALESCE(user_decision, ''))) = ANY(%s) THEN FALSE
                       ELSE TRUE
                   END,
                   counts_as_decided_user = CASE
                       WHEN BTRIM(COALESCE(user_decision, '')) = '' THEN FALSE
                       WHEN COALESCE(is_routed_audit, FALSE) = TRUE THEN FALSE
                       WHEN LOWER(BTRIM(COALESCE(user_decision, ''))) = ANY(%s) THEN FALSE
                       ELSE TRUE
                   END
            """,
            [
                list(routed_labels or ("routed",)),
                list(delegation_labels or ("shared", "redirected")),
                list(routed_labels or ("routed",)),
                list(delegation_labels or ("shared", "redirected")),
            ],
        )
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET is_routed_audit = FALSE
             WHERE is_routed_audit IS NULL
            """
        )
        self.env.cr.execute(
            """
            UPDATE workflow_approval_approver
               SET is_routed_audit = TRUE
             WHERE COALESCE(is_routed_audit, FALSE) = FALSE
               AND status = 'closed'
               AND required = TRUE
               AND BTRIM(COALESCE(user_decision, '')) = 'Routed'
            """
        )
    @api.model_create_multi
    def create(self, vals_list):
        activity_event_seed_indices = [
            idx for idx, vals in enumerate(vals_list)
            if "activity_event_at" not in vals
        ]

        grouped = {}
        for idx, vals in enumerate(vals_list):
            request_id = vals.get("request_id")
            if not request_id:
                continue
            iteration = vals.get("iteration_no") or 1
            if iteration <= 0:
                iteration = 1
                vals["iteration_no"] = iteration
            grouped.setdefault((request_id, iteration), []).append(idx)

        for (request_id, iteration), indices in grouped.items():
            self.env.cr.execute(
                """
                SELECT COALESCE(MAX(event_order), 0)
                  FROM workflow_approval_approver
                 WHERE request_id = %s
                   AND COALESCE(iteration_no, 1) = %s
                """,
                (request_id, iteration),
            )
            current_max = self.env.cr.fetchone()[0] or 0
            for pos, idx in enumerate(indices, start=1):
                vals_list[idx].setdefault("event_order", current_max + pos)

        records = super().create(vals_list)
        if activity_event_seed_indices:
            seeded_records = self.browse([records[idx].id for idx in activity_event_seed_indices])
            self.env.cr.execute(
                """
                UPDATE workflow_approval_approver
                   SET activity_event_at = create_date
                 WHERE id = ANY(%s)
                   AND activity_event_at IS NULL
                """,
                [seeded_records.ids],
            )
            seeded_records.invalidate_recordset(["activity_event_at"])
        records._ensure_workflow_access_group()
        records.mapped("request_id")._sync_blocked_state_from_approvers()
        records._notify_request_mini_update(reason="approver_created")
        return records

    def write(self, vals):
        refresh_activity_event_at = False
        refreshed_activity_event_at = False
        resequence_decision_rows = self.browse()
        decision_changed_rows = self.browse()
        if "user_decision" in vals:
            target_decision = (vals.get("user_decision") or "").strip()
            decision_changed_rows = self.filtered(
                lambda rec: (rec.user_decision or "").strip() != target_decision
            )
            if target_decision and "event_order" not in vals:
                resequence_decision_rows = decision_changed_rows
        if "activity_event_at" not in vals:
            if "status" in vals:
                refresh_activity_event_at = any((rec.status or False) != (vals.get("status") or False) for rec in self)
            if not refresh_activity_event_at and decision_changed_rows:
                refresh_activity_event_at = True
            if refresh_activity_event_at:
                refreshed_activity_event_at = fields.Datetime.now()

        requests_before = self.mapped("request_id")
        res = super().write(vals)
        if refreshed_activity_event_at:
            self.env.cr.execute(
                """
                UPDATE workflow_approval_approver
                   SET activity_event_at = %s
                WHERE id = ANY(%s)
                """,
                [refreshed_activity_event_at, self.ids],
            )
            self.invalidate_recordset(["activity_event_at"])
        if resequence_decision_rows:
            resequence_decision_rows._resequence_event_order_after_decision()
        if "user_id" in vals:
            self._ensure_workflow_access_group()
        tracked_keys = {
            "status",
            "user_decision",
            "is_routed_audit",
            "counts_as_decided_user",
            "show_in_decision_history",
            "decision_history_kind",
            "current_meta_id",
            "previous_meta_id",
            "iteration_no",
            "event_order",
            "required",
            "request_id",
            "user_id",
            "delegation_mode",
            "delegated_from_user_id",
            "delegated_from_approver_id",
            "delegated_to_user_id",
            "delegated_by_user_id",
            "delegated_at",
        }
        impacted_requests = requests_before | self.mapped("request_id")
        if refresh_activity_event_at or resequence_decision_rows:
            impacted_requests.invalidate_recordset(["activity_history"])
        impacted_requests._sync_blocked_state_from_approvers()
        if set(vals.keys()) & tracked_keys:
            impacted_requests._notify_mini_update_bus(reason="approver_updated")
        return res

    def _resequence_event_order_after_decision(self):
        grouped = {}
        for rec in self.filtered("request_id"):
            grouped.setdefault((rec.request_id.id, rec.iteration_no or 1), []).append(rec.id)
        if not grouped:
            return
        for (request_id, iteration_no), row_ids in grouped.items():
            ordered_ids = sorted(set(row_ids))
            self.env.cr.execute(
                """
                SELECT COALESCE(MAX(event_order), 0)
                  FROM workflow_approval_approver
                 WHERE request_id = %s
                   AND COALESCE(iteration_no, 1) = %s
                   AND NOT (id = ANY(%s))
                """,
                (request_id, iteration_no, ordered_ids),
            )
            current_max = self.env.cr.fetchone()[0] or 0
            for offset, row_id in enumerate(ordered_ids, start=1):
                self.env.cr.execute(
                    """
                    UPDATE workflow_approval_approver
                       SET event_order = %s
                     WHERE id = %s
                    """,
                    (current_max + offset, row_id),
                )
        self.invalidate_recordset(["event_order"])

    def unlink(self):
        requests = self.mapped("request_id")
        res = super().unlink()
        requests._sync_blocked_state_from_approvers()
        requests._notify_mini_update_bus(reason="approver_deleted")
        return res

    def _notify_request_mini_update(self, reason=False):
        requests = self.mapped("request_id")
        if requests:
            requests._notify_mini_update_bus(reason=reason or "approver_updated")

    def _decision_history_sort_rank(self):
        self.ensure_one()
        kind = self.decision_history_kind or False
        if kind == "workflow_decision":
            return 2
        if kind == "delegation_decision":
            return 1
        return 0

    def _ensure_workflow_access_group(self):
        """Ensure assigned internal approvers can access workflow menus/actions.

        Dynamic assignment can target users that are not manually granted the
        workflow group yet. Without this guard they cannot see My Dashboard /
        My Approvals even when they are the active approver.
        """
        workflow_group = self.env.ref("workflow_engine.group_workflow_approval_user", raise_if_not_found=False)
        if not workflow_group:
            return
        users = self.mapped("user_id").filtered(lambda u: u and not u.share)
        if not users:
            return
        users_missing_group = users.filtered(lambda u: workflow_group not in u.group_ids)
        if users_missing_group:
            users_missing_group.sudo().write({"group_ids": [Command.link(workflow_group.id)]})

    @api.model
    def _repair_stale_open_assignment_rows(self, requests=False, notify=True, sync_blocked=True):
        """Close stale open assignment rows left behind on inactive stages.

        A row is repairable only when:
        - it is still open (`new`, `pending`, `waiting`)
        - it is a required assignment row without a real decision
        - the same request + iteration + stage already has a real decision row
        - the row stage is no longer an active node on the request
        """
        request_ids = []
        if requests:
            request_ids = requests.ids
            if not request_ids:
                return self.browse()
        self.flush_model(
            [
                "request_id",
                "current_meta_id",
                "current_meta_node_id",
                "iteration_no",
                "status",
                "user_decision",
                "required",
                "counts_as_decided_user",
            ]
        )
        self.env["workflow.base.approval.request"].flush_model(
            ["current_node_id", "active_branch_node_ids"]
        )

        self.env.cr.execute(
            """
            SELECT
                to_regclass('workflow_approval_approver'),
                to_regclass('workflow_base_approval_request')
            """
        )
        approver_table, request_table = self.env.cr.fetchone() or (None, None)
        if not approver_table or not request_table:
            return self.browse()

        decision_scope_sql = ""
        stale_scope_sql = ""
        params = []
        if request_ids:
            decision_scope_sql = " AND row.request_id = ANY(%s)"
            stale_scope_sql = " AND row.request_id = ANY(%s)"
            params.extend([request_ids, request_ids])

        repair_time = fields.Datetime.now()
        params.append(repair_time)

        self.env.cr.execute(
            f"""
            WITH decision_keys AS (
                SELECT DISTINCT
                    row.request_id,
                    COALESCE(row.iteration_no, 1) AS iteration_no,
                    row.current_meta_id
                FROM workflow_approval_approver row
                WHERE row.request_id IS NOT NULL
                  AND row.current_meta_id IS NOT NULL
                  AND COALESCE(row.counts_as_decided_user, FALSE) = TRUE
                  {decision_scope_sql}
            ),
            stale_rows AS (
                SELECT row.id
                FROM workflow_approval_approver row
                JOIN workflow_base_approval_request req
                  ON req.id = row.request_id
                JOIN decision_keys decision
                  ON decision.request_id = row.request_id
                 AND decision.iteration_no = COALESCE(row.iteration_no, 1)
                 AND decision.current_meta_id = row.current_meta_id
                WHERE row.required = TRUE
                  AND row.status IN ('new', 'pending', 'waiting')
                  AND BTRIM(COALESCE(row.user_decision, '')) = ''
                  {stale_scope_sql}
                  AND (
                        COALESCE(row.current_meta_node_id, '') = ''
                     OR COALESCE(row.current_meta_node_id, '') <> COALESCE(req.current_node_id, '')
                  )
                  AND NOT (
                        COALESCE(row.current_meta_node_id, '') != ''
                    AND COALESCE(req.active_branch_node_ids, '[]'::jsonb) ? row.current_meta_node_id
                  )
            )
            UPDATE workflow_approval_approver row
               SET status = 'closed',
                   activity_event_at = %s
              FROM stale_rows
             WHERE row.id = stale_rows.id
         RETURNING row.id
            """,
            params,
        )
        repaired_ids = [row[0] for row in self.env.cr.fetchall()]
        repaired_rows = self.browse(repaired_ids)
        if repaired_rows and sync_blocked:
            repaired_rows.mapped("request_id").sudo().with_context(
                wf_skip_block_sync=False
            )._sync_blocked_state_from_approvers()
        if repaired_rows and notify:
            repaired_rows.mapped("request_id")._notify_mini_update_bus(reason="approver_repaired")
        return repaired_rows

    def _compute_called_workflows(self):
        for rec in self:
            if rec.current_meta_id:
                rec.called_workflow_ids = rec.current_meta_id.workflow_map_ids.mapped("called_workflow_id")
            else:
                rec.called_workflow_ids = False

    def _get_auto_closed_decision_map(self):
        """Map auto-closed assignment rows to the decision row that closed them.

        Key: (request_id, iteration_no, source_meta_id)
        Value: first decision row for that source in that cycle.
        """
        rows = self.filtered(
            lambda r: r.request_id
            and r.current_meta_id
            and r.required
            and r.status == "closed"
            and not (r.user_decision or "").strip()
        )
        if not rows:
            return {}

        req_ids = rows.mapped("request_id").ids
        iteration_nos = list({(r.iteration_no or 1) for r in rows})
        source_meta_ids = rows.mapped("current_meta_id").ids
        if not req_ids or not iteration_nos or not source_meta_ids:
            return {}

        decisions = self.search(
            [
                ("request_id", "in", req_ids),
                ("iteration_no", "in", iteration_nos),
                "|",
                ("current_meta_id", "in", source_meta_ids),
                ("previous_meta_id", "in", source_meta_ids),
                ("counts_as_decided_user", "=", True),
            ],
            order="event_order asc, id asc",
        )

        result = {}
        source_meta_id_set = set(source_meta_ids)
        for rec in decisions:
            source_meta_id = (
                rec.current_meta_id.id
                if rec.current_meta_id.id in source_meta_id_set
                else rec.previous_meta_id.id
            )
            key = (rec.request_id.id, rec.iteration_no or 1, source_meta_id)
            if key not in result:
                result[key] = rec
        return result

    @api.model
    def _decision_text(self, decision):
        return (decision or "").strip()

    @api.model
    def _has_decision_text(self, decision):
        return bool(self._decision_text(decision))

    @api.model
    def _is_routed_audit_decision_value(self, decision):
        normalized = self._decision_text(decision).casefold()
        if not normalized:
            return False
        routed_labels = {
            "routed",
            self._decision_text(_("Routed")).casefold(),
        }
        return normalized in routed_labels

    @api.model
    def _is_delegation_history_decision_value(self, decision):
        normalized = self._decision_text(decision).casefold()
        if not normalized:
            return False
        delegation_labels = {
            self._decision_text("Shared").casefold(),
            self._decision_text(_("Shared")).casefold(),
            self._decision_text("Redirected").casefold(),
            self._decision_text(_("Redirected")).casefold(),
        }
        return normalized in delegation_labels

    @api.depends("user_decision")
    def _compute_has_decision(self):
        for rec in self:
            rec.has_decision = rec._has_decision_text(rec.user_decision)

    @api.depends("user_decision", "is_routed_audit")
    def _compute_decision_history_flags(self):
        for rec in self:
            has_decision = rec._has_decision_text(rec.user_decision)
            if not has_decision:
                rec.decision_history_kind = False
                rec.show_in_decision_history = False
                rec.counts_as_decided_user = False
                continue
            if rec.is_routed_audit or rec._is_routed_audit_decision_value(rec.user_decision):
                rec.decision_history_kind = "system_audit"
                rec.show_in_decision_history = False
                rec.counts_as_decided_user = False
                continue
            if rec._is_delegation_history_decision_value(rec.user_decision):
                rec.decision_history_kind = "delegation_decision"
                rec.show_in_decision_history = True
                rec.counts_as_decided_user = False
                continue
            rec.decision_history_kind = "workflow_decision"
            rec.show_in_decision_history = True
            rec.counts_as_decided_user = True

    @api.model
    def _to_utc_datetime(self, value):
        if not value:
            return None
        dt = fields.Datetime.to_datetime(value)
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @api.model
    def _format_duration_compact(self, total_minutes):
        minutes = max(int(total_minutes or 0), 0)
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        rem_minutes = minutes % 60
        if days:
            return _("%(days)sd %(hours)sh") % {"days": days, "hours": hours}
        if hours:
            return _("%(hours)sh %(minutes)sm") % {"hours": hours, "minutes": rem_minutes}
        return _("%sm") % rem_minutes

    @api.depends(
        "create_date",
        "write_date",
        "status",
        "user_decision",
        "iteration_no",
        "current_meta_id",
        "previous_meta_id",
        "request_id.current_node_id",
        "request_id.current_iteration_no",
        "request_id.approver_ids.create_date",
        "request_id.approver_ids.write_date",
        "request_id.approver_ids.user_decision",
        "request_id.approver_ids.counts_as_decided_user",
        "request_id.approver_ids.current_meta_id",
        "request_id.approver_ids.previous_meta_id",
        "request_id.approver_ids.iteration_no",
    )
    def _compute_stage_age(self):
        now_utc = self._to_utc_datetime(fields.Datetime.now())
        duration_by_row = {}

        for request in self.mapped("request_id"):
            rows = request.approver_ids.sorted(key=lambda r: ((r.create_date or fields.Datetime.now()), r.id))
            if not rows:
                continue

            stage_enter = {}
            stage_exit = {}
            for row in rows:
                if not row.current_meta_id:
                    continue
                iteration = row.iteration_no or 1
                stage_key = (iteration, row.current_meta_id.id)
                entered_at = self._to_utc_datetime(row.create_date) or now_utc
                if stage_key not in stage_enter or entered_at < stage_enter[stage_key]:
                    stage_enter[stage_key] = entered_at

                if row.counts_as_decided_user and (row.user_decision or "").strip():
                    decided_at = self._to_utc_datetime(row.write_date or row.create_date) or entered_at
                    current_exit = stage_exit.get(stage_key)
                    if not current_exit or decided_at < current_exit:
                        stage_exit[stage_key] = decided_at

                if row.previous_meta_id and row.counts_as_decided_user and (row.user_decision or "").strip():
                    previous_key = (iteration, row.previous_meta_id.id)
                    previous_exit_at = self._to_utc_datetime(row.write_date or row.create_date) or entered_at
                    current_previous_exit = stage_exit.get(previous_key)
                    if not current_previous_exit or previous_exit_at < current_previous_exit:
                        stage_exit[previous_key] = previous_exit_at

            current_iteration = request.current_iteration_no or 1
            current_node = request.current_node_id or ""
            active_stage_key = False
            if current_node:
                current_meta = request.version_id.meta_task_ids.filtered(lambda m: m.node_id == current_node)[:1]
                if current_meta:
                    active_stage_key = (current_iteration, current_meta.id)

            for row in rows:
                if not row.current_meta_id:
                    duration_by_row[row.id] = 0
                    continue
                key = ((row.iteration_no or 1), row.current_meta_id.id)
                started_at = stage_enter.get(key)
                if not started_at:
                    duration_by_row[row.id] = 0
                    continue
                ended_at = stage_exit.get(key)
                if not ended_at and active_stage_key and key == active_stage_key:
                    ended_at = now_utc
                if not ended_at:
                    ended_at = self._to_utc_datetime(row.write_date or row.create_date) or started_at
                minutes = max(int((ended_at - started_at).total_seconds() // 60), 0)
                if ended_at > started_at and minutes == 0:
                    minutes = 1
                duration_by_row[row.id] = minutes

        for rec in self:
            minutes = duration_by_row.get(rec.id, 0)
            rec.stage_age_minutes = minutes
            rec.stage_age_display = self._format_duration_compact(minutes)

    @api.model
    def _workflow_business_activity_node_types(self):
        return {
            NODE_TYPE["USER_TASK"],
            NODE_TYPE["MANUAL_TASK"],
            NODE_TYPE["TASK"],
            NODE_TYPE["CALL_ACTIVITY"],
        }

    @api.model
    def _workflow_boundary_activity_node_types(self):
        return {
            NODE_TYPE["START_EVENT"],
            NODE_TYPE["START_EVENT_WITH_MESSAGE"],
            NODE_TYPE["START_EVENT_WITH_TIMER"],
            NODE_TYPE["START_EVENT_WITH_SIGNAL"],
            NODE_TYPE["START_EVENT_WITH_CONDITIONAL"],
            NODE_TYPE["END_EVENT"],
            NODE_TYPE["END_EVENT_WITH_MESSAGE"],
            NODE_TYPE["END_EVENT_WITH_SIGNAL"],
            NODE_TYPE["END_EVENT_WITH_TERMINATE"],
        }

    @api.model
    def _build_activity_resolution_caches(self, versions):
        caches = {}
        for version in versions:
            if not version:
                continue
            engine = False
            reverse_edges = {}
            meta_by_node = {
                task.node_id: task
                for task in version.meta_task_ids
                if task.node_id
            }
            if version.bpmn_xml:
                try:
                    engine = BpmnEngine(version.bpmn_xml)
                except Exception:
                    engine = False
            if engine:
                for source_id, flows in (engine.sequence_flows or {}).items():
                    for flow in flows:
                        target_id = flow.get("target")
                        if source_id and target_id:
                            reverse_edges.setdefault(target_id, []).append(source_id)
            caches[version.id] = {
                "engine": engine,
                "meta_by_node": meta_by_node,
                "reverse_edges": reverse_edges,
            }
        return caches

    @api.model
    def _resolve_visible_activity_name(
        self,
        version=False,
        node_id=False,
        fallback_name=False,
        direction="auto",
        cache=False,
    ):
        fallback_name = (fallback_name or "").strip()
        if not version or not node_id:
            return fallback_name

        cache = cache or {}
        engine = cache.get("engine")
        meta_by_node = cache.get("meta_by_node") or {}
        reverse_edges = cache.get("reverse_edges") or {}
        business_types = self._workflow_business_activity_node_types()
        boundary_types = self._workflow_boundary_activity_node_types()

        def _node_info(candidate_id):
            meta = meta_by_node.get(candidate_id)
            element = engine.get_element_by_id(candidate_id) if engine and candidate_id else None
            node_type = (
                (meta.node_type or "")
                if meta
                else engine.get_element_type(element) if engine and element is not None else ""
            )
            node_name = (
                (meta.name or "").strip()
                if meta
                else ((element.attrib.get("name") or "").strip() if element is not None else "")
            )
            return node_type, node_name, element

        initial_type, initial_name, _initial_element = _node_info(node_id)
        if initial_type in business_types:
            return initial_name or fallback_name

        boundary_name = initial_name if initial_type in boundary_types else ""
        if not engine:
            return boundary_name or initial_name or fallback_name

        directions = [direction] if direction in ("forward", "backward") else ["backward", "forward"]
        visited = {node_id}

        for current_direction in directions:
            queue = deque([node_id])
            local_visited = set(visited)
            local_boundary_name = boundary_name
            while queue:
                candidate_id = queue.popleft()
                if current_direction == "forward":
                    neighbours = [
                        flow.get("target")
                        for flow in (engine.sequence_flows or {}).get(candidate_id, [])
                        if flow.get("target")
                    ]
                else:
                    neighbours = reverse_edges.get(candidate_id, [])

                for neighbour_id in neighbours:
                    if not neighbour_id or neighbour_id in local_visited:
                        continue
                    local_visited.add(neighbour_id)
                    node_type, node_name, _element = _node_info(neighbour_id)
                    if node_type in business_types and node_name:
                        return node_name
                    if not local_boundary_name and node_type in boundary_types and node_name:
                        local_boundary_name = node_name
                    queue.append(neighbour_id)
            boundary_name = boundary_name or local_boundary_name

        return boundary_name or initial_name or fallback_name

    @api.model
    def _normalize_decision_label(self, value):
        return (value or "").strip().lower()

    def _get_decision_transition_map(self, version_caches=False):
        """Resolve display transition for decision rows from engine action metadata.

        This keeps From/To labels aligned with the BPMN edge selected by the actor,
        even when legacy rows store current/previous metadata differently.
        """
        rows = self.filtered(
            lambda r: bool((r.user_decision or "").strip())
            and r.request_id
            and r.request_id.version_id
        )
        if not rows:
            return {}

        version_ids = rows.mapped("request_id.version_id").ids
        version_caches = version_caches or self._build_activity_resolution_caches(
            rows.mapped("request_id.version_id")
        )
        source_node_ids = set()
        for rec in rows:
            if rec.current_meta_node_id:
                source_node_ids.add(rec.current_meta_node_id)
            if rec.previous_meta_id and rec.previous_meta_id.node_id:
                source_node_ids.add(rec.previous_meta_id.node_id)
        if not version_ids or not source_node_ids:
            return {}

        action_model = self.env["workflow.category.version.meta.task.action"].sudo()
        actions = action_model.search(
            [
                ("version_id", "in", version_ids),
                ("source_id", "in", list(source_node_ids)),
            ],
            order="id asc",
        )

        action_lookup = {}
        for action in actions:
            labels = {
                self._normalize_decision_label(action.name),
                self._normalize_decision_label(action.attr_label),
            }
            labels.discard("")
            for label in labels:
                key = (action.version_id.id, action.source_id, label)
                if key not in action_lookup:
                    action_lookup[key] = action

        result = {}
        for rec in rows:
            version = rec.request_id.version_id
            version_id = version.id
            version_cache = version_caches.get(version_id, {})
            decision_key = self._normalize_decision_label(rec.user_decision)
            if not decision_key:
                continue

            current_node_id = rec.current_meta_node_id or ""
            previous_node_id = (rec.previous_meta_id.node_id or "") if rec.previous_meta_id else ""

            matched = None
            if current_node_id:
                matched = action_lookup.get((version_id, current_node_id, decision_key))
                if matched:
                    source_name = self._resolve_visible_activity_name(
                        version=version,
                        node_id=current_node_id,
                        fallback_name=(rec.current_meta_id.name or "").strip(),
                        direction="auto",
                        cache=version_cache,
                    )
                    target_name = self._resolve_visible_activity_name(
                        version=version,
                        node_id=matched.target_id,
                        fallback_name=(matched.target_name or "").strip(),
                        direction="forward",
                        cache=version_cache,
                    )
                    if source_name and target_name:
                        result[rec.id] = (source_name, target_name)
                        continue

            if previous_node_id:
                matched = action_lookup.get((version_id, previous_node_id, decision_key))
                if matched:
                    source_name = self._resolve_visible_activity_name(
                        version=version,
                        node_id=previous_node_id,
                        fallback_name=(rec.previous_meta_id.name or "").strip(),
                        direction="backward",
                        cache=version_cache,
                    )
                    target_name = self._resolve_visible_activity_name(
                        version=version,
                        node_id=matched.target_id,
                        fallback_name=(matched.target_name or "").strip(),
                        direction="forward",
                        cache=version_cache,
                    )
                    if source_name and target_name:
                        result[rec.id] = (source_name, target_name)

        return result

    @api.depends(
        "previous_meta_id.name",
        "previous_meta_id.node_id",
        "current_meta_id.name",
        "current_meta_node_id",
        "request_id.version_id",
        "user_decision",
        "required",
        "status",
    )
    def _compute_activity_flow(self):
        status_labels = dict(self._fields['status'].selection)
        auto_closed_decision_map = self._get_auto_closed_decision_map()
        auto_closed_decision_rows = self.browse(
            [row.id for row in auto_closed_decision_map.values()]
        )
        version_caches = self._build_activity_resolution_caches(
            (self | auto_closed_decision_rows).mapped("request_id.version_id")
        )
        decision_transition_map = (self | auto_closed_decision_rows)._get_decision_transition_map(
            version_caches=version_caches,
        )
        for rec in self:
            version = rec.request_id.version_id
            version_cache = version_caches.get(version.id, {}) if version else {}
            previous_name = self._resolve_visible_activity_name(
                version=version,
                node_id=(rec.previous_meta_id.node_id or "") if rec.previous_meta_id else "",
                fallback_name=(rec.previous_meta_id.name or "").strip() if rec.previous_meta_id else "",
                direction="backward",
                cache=version_cache,
            )
            current_name = self._resolve_visible_activity_name(
                version=version,
                node_id=rec.current_meta_node_id or "",
                fallback_name=(rec.current_meta_id.name or "").strip(),
                direction="forward",
                cache=version_cache,
            )
            decision = (rec.user_decision or "").strip()
            auto_closed_transition = False
            if rec.required and rec.status == "closed" and not decision and rec.request_id and rec.current_meta_id:
                key = (rec.request_id.id, rec.iteration_no or 1, rec.current_meta_id.id)
                decision_row = auto_closed_decision_map.get(key)
                if decision_row:
                    if decision_row.id in decision_transition_map:
                        previous_name, current_name = decision_transition_map[decision_row.id]
                    else:
                        previous_name = (decision_row.previous_meta_id.name or "").strip()
                        current_name = (decision_row.current_meta_id.name or "").strip()
                    auto_closed_transition = True

            if decision and rec.id in decision_transition_map:
                previous_name, current_name = decision_transition_map[rec.id]

            if decision and previous_name and current_name:
                rec.activity_flow = _("%(from_name)s -> %(to_name)s (%(decision)s)", from_name=previous_name, to_name=current_name, decision=decision)
                continue
            if rec.required and current_name:
                assignment_note = _("Assigned")
                if rec.status == 'closed':
                    assignment_note = _("Assigned, then auto-closed")
                if auto_closed_transition:
                    assignment_note = _("Auto-closed")
                if previous_name and previous_name != current_name:
                    rec.activity_flow = _("%(from_name)s -> %(to_name)s (%(note)s)", from_name=previous_name, to_name=current_name, note=assignment_note)
                else:
                    rec.activity_flow = _("%(to_name)s (%(note)s)", to_name=current_name, note=assignment_note)
                continue
            if previous_name and current_name:
                status_label = status_labels.get(rec.status, rec.status or _("Updated"))
                rec.activity_flow = _("%(from_name)s -> %(to_name)s (%(status)s)", from_name=previous_name, to_name=current_name, status=status_label)
                continue
            rec.activity_flow = current_name or previous_name or _("Activity updated")

    @api.depends(
        "previous_meta_id.name",
        "previous_meta_id.node_id",
        "current_meta_id.name",
        "current_meta_node_id",
        "request_id.version_id",
        "activity_kind",
        "status",
        "user_decision",
        "required",
    )
    def _compute_activity_labels(self):
        auto_closed_decision_map = self._get_auto_closed_decision_map()
        auto_closed_decision_rows = self.browse(
            [row.id for row in auto_closed_decision_map.values()]
        )
        version_caches = self._build_activity_resolution_caches(
            (self | auto_closed_decision_rows).mapped("request_id.version_id")
        )
        decision_transition_map = (self | auto_closed_decision_rows)._get_decision_transition_map(
            version_caches=version_caches,
        )
        for rec in self:
            version = rec.request_id.version_id
            version_cache = version_caches.get(version.id, {}) if version else {}
            from_name = self._resolve_visible_activity_name(
                version=version,
                node_id=(rec.previous_meta_id.node_id or "") if rec.previous_meta_id else "",
                fallback_name=(rec.previous_meta_id.name or "").strip() if rec.previous_meta_id else "",
                direction="backward",
                cache=version_cache,
            )
            to_name = self._resolve_visible_activity_name(
                version=version,
                node_id=rec.current_meta_node_id or "",
                fallback_name=(rec.current_meta_id.name or "").strip(),
                direction="forward",
                cache=version_cache,
            )

            if (rec.user_decision or "").strip() and rec.id in decision_transition_map:
                from_name, to_name = decision_transition_map[rec.id]

            if rec.required and rec.status == "closed" and not (rec.user_decision or "").strip() and rec.request_id and rec.current_meta_id:
                key = (rec.request_id.id, rec.iteration_no or 1, rec.current_meta_id.id)
                decision_row = auto_closed_decision_map.get(key)
                if decision_row:
                    if decision_row.id in decision_transition_map:
                        from_name, to_name = decision_transition_map[decision_row.id]
                    else:
                        from_name = (decision_row.previous_meta_id.name or "").strip()
                        to_name = (decision_row.current_meta_id.name or "").strip()

            rec.from_activity_label = from_name or "-"
            rec.to_activity_label = to_name or "-"

            if rec.activity_kind == "assignment" and to_name:
                if rec.status == "closed":
                    rec.to_activity_label = _("%s (Auto-closed)") % to_name
                elif rec.status in ("new", "pending", "waiting", "view"):
                    rec.to_activity_label = _("%s (Assigned)") % to_name

    @api.depends("user_decision", "required", "status")
    def _compute_activity_kind(self):
        for rec in self:
            if (rec.user_decision or "").strip():
                rec.activity_kind = "decision"
            elif rec.required:
                rec.activity_kind = "assignment"
            else:
                rec.activity_kind = "system"
        
    @api.depends('request_id', 'user_id')
    def _compute_is_owner(self):
        for rec in self:
            request = rec.env['workflow.base.approval.request'].browse(rec.request_id.id)
            rec.is_owner = request.create_uid == rec.user_id

    @api.depends("user_id", "employee_id", "employee_id.work_email")
    def _compute_work_email(self):
        user_model = self.env["res.users"]
        allowed_email_domains = user_model._workflow_request_owner_email_domains()
        for approver in self:
            approver.work_email = user_model._workflow_request_owner_pick_email(
                [approver.employee_id.work_email],
                allowed_email_domains=allowed_email_domains,
            )

    @api.depends('request_id')
    def _compute_company_id(self):
        for approver in self:
            approver.company_id = False
            if approver.request_id:
                try:
                    record = self.env['workflow.base.approval.request'].browse(approver.request_id.id)
                    if record.exists() and hasattr(record, 'company_id'):
                        approver.company_id = record.company_id.id
                except Exception:
                    approver.company_id = False

    def _create_activity(self):
        context = self.env.context or {}
        if any(
            context.get(flag)
            for flag in (
                "no_notification",
                "workflow_suppress_notifications",
                "workflow_skip_notifications",
                "workflow_silent_migration",
                "workflow_migration_mode",
            )
        ):
            return

        activity_type = self.env.ref(
            'workflow_engine.mail_activity_data_workflow_approval',
            raise_if_not_found=False,
        )
        if not activity_type:
            return
        if activity_type.res_model:
            activity_type.sudo().write({"res_model": False})

        base_requests = self.mapped("request_id").exists()
        if not base_requests:
            return
        base_by_id = {request.id: request for request in base_requests}

        base_as_child = self.env["workflow.base.approval.request"]
        child_ids_by_model = defaultdict(list)
        for base_request in base_requests:
            if not base_request.res_model_name or base_request.state in ['draft', 'new']:
                continue
            if base_request.res_model_name == base_request._name:
                base_as_child |= base_request
            else:
                child_ids_by_model[base_request.res_model_name].append(base_request.id)

        child_by_base_id = {request.id: request for request in base_as_child}
        for model_name, base_ids in child_ids_by_model.items():
            child_model = self.env[model_name]
            if "x_approval_base_id" not in child_model._fields:
                continue
            for child_request in child_model.search([("x_approval_base_id", "in", base_ids)]):
                child_by_base_id.setdefault(child_request.x_approval_base_id.id, child_request)

        activity_candidates = []
        activity_lookup = defaultdict(lambda: defaultdict(set))
        for approver in self:
            if not approver.request_id or not approver.user_id:
                continue
            if "wf_approval_push_enabled" in approver.user_id._fields and not approver.user_id.wf_approval_push_enabled:
                continue
            if (
                approver.current_meta_id
                and "push_notification_to_actor" in approver.current_meta_id._fields
                and approver.current_meta_id.push_notification_to_actor is False
            ):
                continue

            base_request = base_by_id.get(approver.request_id.id)
            if not base_request or base_request.state in ['draft', 'new']:
                continue

            # Only schedule activities for actionable approvers on current workflow node.
            if approver.status not in ['new', 'pending']:
                continue
            if approver.current_meta_node_id != base_request.current_node_id:
                continue

            child_request = child_by_base_id.get(base_request.id)
            if not child_request:
                continue

            summary = approver.current_meta_id.name or base_request.current_activity_name or _("Approval Task")
            note = _(
                "Approval requested for %(request)s at stage %(stage)s.",
                request=base_request.display_name or base_request.name or "",
                stage=summary,
            )
            activity_candidates.append((approver, child_request, summary, note))
            lookup_key = (child_request._name, child_request.id, approver.user_id.id)
            activity_lookup[lookup_key]["summaries"].add(summary)

        if not activity_candidates:
            return

        existing_by_key = defaultdict(set)
        stale_activities = self.env["mail.activity"].sudo()
        mail_activity = self.env["mail.activity"].sudo()
        model_names = sorted({model for model, _res_id, _user_id in activity_lookup})
        for model_name in model_names:
            res_ids = sorted({
                res_id
                for lookup_model, res_id, _user_id in activity_lookup
                if lookup_model == model_name
            })
            user_ids = sorted({
                user_id
                for lookup_model, _res_id, user_id in activity_lookup
                if lookup_model == model_name
            })
            activities = mail_activity.search([
                ("res_model", "=", model_name),
                ("res_id", "in", res_ids),
                ("user_id", "in", user_ids),
                ("activity_type_id", "=", activity_type.id),
                ("date_done", "=", False),
            ])
            for activity in activities:
                key = (activity.res_model, activity.res_id, activity.user_id.id)
                if key not in activity_lookup:
                    continue
                if activity.summary in activity_lookup[key]["summaries"]:
                    existing_by_key[key].add(activity.summary)
                else:
                    stale_activities |= activity

        if stale_activities:
            stale_activities.unlink()

        for approver, child_request, summary, note in activity_candidates:
            lookup_key = (child_request._name, child_request.id, approver.user_id.id)
            if summary in existing_by_key[lookup_key]:
                continue

            child_request.with_context(workflow_activity_no_email=True).activity_schedule(
                activity_type_id=activity_type.id,
                user_id=approver.user_id.id,
                summary=summary,
                note=note,
            )

    def _is_node_related_row(self, row, node_id):
        """Return True when an approver row is relevant to a node popup.

        Rules:
        - assignment rows: current node matches and row is required
        - decision audit rows: current node matches and decision exists

        ``previous_meta_id`` is the stage the workflow came from.  It must not
        decide popup ownership, otherwise decisions made on the next stage leak
        into the previous stage preview.
        """
        if not row or not node_id:
            return False
        if row.current_meta_node_id != node_id:
            return False
        return bool(row.required) or bool((row.user_decision or "").strip())

    def _get_node_related_rows(self, request_id, node_id):
        """Compute node-related approver rows for request popup."""
        if not request_id or not node_id:
            return self.browse()
        base_domain = [
            ('request_id', '=', request_id),
            ('user_id', '!=', False),
            ('current_meta_node_id', '=', node_id),
        ]
        candidate_rows = self.search(base_domain, order='iteration_no desc, create_date asc, id asc')
        return candidate_rows.filtered(lambda row: self._is_node_related_row(row, node_id))

    @api.model
    def action_open_node_approvers(
        self,
        request_id,
        node_id,
        node_name=False,
        is_current_node=False,
        force_view=False,
    ):
        """Open node-scoped approver popup with explicit list+kanban views."""
        if not request_id or not node_id:
            return False

        kept_rows = self._get_node_related_rows(request_id, node_id)
        kept_ids = kept_rows.ids

        list_view = self.env.ref('workflow_engine.workflow_approval_approver_view_compact_list', raise_if_not_found=False)
        kanban_view = self.env.ref('workflow_engine.workflow_approval_approver_view_kanban', raise_if_not_found=False)
        search_view = self.env.ref('workflow_engine.workflow_approval_approver_view_search', raise_if_not_found=False)
        if not kanban_view:
            kanban_view = self.env.ref('workflow_engine.workflow_approval_approver_view_kanban_mobile', raise_if_not_found=False)

        preferred = force_view if force_view in ('list', 'kanban') else False
        view_types = ['list', 'kanban']

        views = []
        for mode in view_types:
            if mode == 'list':
                views.append((list_view.id, 'list') if list_view else (False, 'list'))
            elif mode == 'kanban':
                views.append((kanban_view.id, 'kanban') if kanban_view else (False, 'kanban'))
        views.append((False, 'form'))

        title = _("User Activity")
        if node_name:
            title = _("User Activity - %s") % node_name

        view_mode = ",".join(view_types + ['form'])
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'workflow.approval.approver',
            'view_mode': view_mode,
            'views': views,
            'mobile_view_mode': preferred or 'kanban',
            'search_view_id': search_view.id if search_view else False,
            'target': 'new',
            'domain': [('id', 'in', kept_ids)] if kept_ids else [('id', '=', 0)],
            'context': {
                'search_default_node_related': 1,
                'search_default_decided_users_only': 1,
                'wf_allow_dialog_view_switch': True,
                'wf_node_popup_request_id': request_id,
                'wf_node_popup_node_id': node_id,
                'wf_node_popup_node_name': node_name or "",
                'wf_node_popup_is_current_node': bool(is_current_node),
                'wf_node_popup_default_view': preferred or view_types[0],
                'wf_node_popup_close_footer': True,
                'footer': True,
            },
        }
