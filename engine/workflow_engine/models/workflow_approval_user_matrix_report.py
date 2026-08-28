# -*- coding: utf-8 -*-

from odoo import fields, models, tools
from odoo.tools import SQL


class WorkflowApprovalUserMatrixReport(models.Model):
    _name = "workflow.approval.user.matrix.report"
    _description = "Workflow Approval User Matrix Report"
    _auto = False
    _rec_name = "employee_name"
    _order = "category_id, usage_type, approval_group_id, employee_name"

    usage_type = fields.Selection(
        [
            ("group_member", "Group Membership"),
            ("approval", "Approval Activity"),
            ("notification", "Notification Group"),
            ("channel_notification", "Notification Channel"),
        ],
        string="Usage Type",
        readonly=True,
    )
    user_count = fields.Integer(string="Rows", readonly=True, aggregator="sum")

    user_id = fields.Many2one("res.users", string="User", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    employee_code = fields.Char(string="Emp Code", readonly=True)
    employee_name = fields.Char(string="Employee Name", readonly=True)
    employee_department_id = fields.Many2one("hr.department", string="Employee Department", readonly=True)
    employee_team = fields.Char(string="Employee Team", readonly=True)
    employee_line = fields.Char(string="Employee Line", readonly=True)
    employee_job_id = fields.Many2one("hr.job", string="Employee Position", readonly=True)
    employee_position = fields.Char(string="Employee Position Title", readonly=True)
    extension = fields.Char(string="Extension", readonly=True)
    work_email = fields.Char(string="Work Email", readonly=True)
    work_phone = fields.Char(string="Work Phone", readonly=True)
    mobile_phone = fields.Char(string="Mobile Phone", readonly=True)
    user_login = fields.Char(string="Login", readonly=True)
    user_active = fields.Boolean(string="Active User", readonly=True)
    user_share = fields.Boolean(string="Portal/Shared User", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    category_id = fields.Many2one("workflow.approval.category", string="Workflow Category", readonly=True)
    version_id = fields.Many2one("workflow.approval.category.version", string="Workflow Version", readonly=True)
    request_model_id = fields.Many2one("ir.model", string="Request Model", readonly=True)
    request_model_name = fields.Char(string="Request Model Name", readonly=True)

    approval_group_id = fields.Many2one("workflow.approval.group", string="Workflow Approval Group", readonly=True)
    parent_group_id = fields.Many2one("workflow.approval.group", string="Parent Workflow Approval Group", readonly=True)
    system_group_id = fields.Many2one("res.groups", string="System Security Group", readonly=True)
    group_department_id = fields.Many2one("hr.department", string="Workflow Approval Department", readonly=True)
    line_id = fields.Many2one("workflow.approval.group.line", string="Workflow Approval Line", readonly=True)
    team_id = fields.Many2one("workflow.approval.group.team", string="Workflow Approval Team", readonly=True)

    meta_task_id = fields.Many2one("workflow.category.version.meta.task", string="Workflow Activity", readonly=True)
    task_sequence = fields.Integer(string="Activity Sequence", readonly=True)
    node_id = fields.Char(string="BPMN Node ID", readonly=True)
    node_type = fields.Char(string="Workflow Node Type", readonly=True)
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
        string="Approval Assignment Mode",
        readonly=True,
    )
    completion_mode = fields.Selection(
        [("any", "Any"), ("all", "All")],
        string="Approval Completion Mode",
        readonly=True,
    )
    user_filter_domain = fields.Char(string="Approval User Filter Domain", readonly=True)
    record_domain = fields.Char(string="Approval Record Domain", readonly=True)
    notification_delivery_mode = fields.Selection(
        [
            ("email", "Send Email"),
            ("log", "Log Activity"),
            ("channels", "Channels"),
        ],
        string="Notification Delivery",
        readonly=True,
    )
    notification_recipient_source = fields.Selection(
        [
            ("specific_users", "Specific Users"),
            ("approval_group_users", "Workflow Approval Group Users"),
            ("group_users", "System Security Group Users"),
            ("node_users", "Users From Workflow Node"),
            ("domain", "Domain Over Users"),
        ],
        string="Notification Recipient Source",
        readonly=True,
    )
    notification_filter_domain = fields.Char(string="Notification Recipient Domain", readonly=True)
    notification_action_id = fields.Many2one("workflow.approval.action", string="Notification Channel", readonly=True)
    email_recipient_line_id = fields.Many2one(
        "workflow.approval.action.email.recipient",
        string="Email Recipient Line",
        readonly=True,
    )
    email_header = fields.Selection(
        [("to", "To"), ("cc", "CC"), ("bcc", "BCC")],
        string="Email Header",
        readonly=True,
    )
    email_recipient_source = fields.Selection(
        [
            ("direct", "Raw Emails"),
            ("send_task", "Send Task Recipients"),
            ("specific_users", "Specific Users"),
            ("approval_group_users", "Workflow Approval Group Users"),
            ("group_users", "System Security Group Users"),
            ("node_users", "Users From Workflow Node"),
            ("domain", "Domain Over Users"),
        ],
        string="Email Recipient Source",
        readonly=True,
    )
    note = fields.Text(string="Note", readonly=True)

    def init(self):
        group_user_field = self.env["workflow.approval.group"]._fields["user_ids"]
        group_user_rel = group_user_field.relation
        group_user_group_col = group_user_field.column1
        group_user_user_col = group_user_field.column2
        system_group_user_field = self.env["res.groups"]._fields["user_ids"]
        system_group_user_rel = system_group_user_field.relation
        system_group_group_col = system_group_user_field.column1
        system_group_user_col = system_group_user_field.column2

        meta_model = self.env["workflow.category.version.meta.task"]
        meta_user_field = meta_model._fields["notification_recipient_ids"]
        meta_user_rel = meta_user_field.relation
        meta_user_meta_col = meta_user_field.column1
        meta_user_user_col = meta_user_field.column2
        meta_approval_group_field = meta_model._fields["notification_approval_group_ids"]
        meta_approval_group_rel = meta_approval_group_field.relation
        meta_approval_group_meta_col = meta_approval_group_field.column1
        meta_approval_group_group_col = meta_approval_group_field.column2
        meta_group_field = meta_model._fields["notification_group_ids"]
        meta_group_rel = meta_group_field.relation
        meta_group_meta_col = meta_group_field.column1
        meta_group_group_col = meta_group_field.column2
        meta_action_field = meta_model._fields["activity_type_ids"]
        meta_action_rel = meta_action_field.relation
        meta_action_meta_col = meta_action_field.column1
        meta_action_action_col = meta_action_field.column2

        line_model = self.env["workflow.approval.action.email.recipient"]
        line_user_field = line_model._fields["user_ids"]
        line_user_rel = line_user_field.relation
        line_user_line_col = line_user_field.column1
        line_user_user_col = line_user_field.column2
        line_approval_group_field = line_model._fields["approval_group_ids"]
        line_approval_group_rel = line_approval_group_field.relation
        line_approval_group_line_col = line_approval_group_field.column1
        line_approval_group_group_col = line_approval_group_field.column2
        line_group_field = line_model._fields["group_ids"]
        line_group_rel = line_group_field.relation
        line_group_line_col = line_group_field.column1
        line_group_group_col = line_group_field.column2
        employee_model = self.env["hr.employee"]
        employee_line_expr = (
            SQL.identifier("emp", "x_line")
            if employee_model._fields.get("x_line")
            else SQL("NULL::varchar")
        )
        employee_team_expr = (
            SQL.identifier("emp", "x_team")
            if employee_model._fields.get("x_team")
            else SQL("NULL::varchar")
        )

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL(
                """
                CREATE OR REPLACE VIEW %(table)s AS (
                    WITH configured_send_task_recipients AS (
                        SELECT
                            meta.id AS meta_task_id,
                            NULL::integer AS approval_group_id,
                            NULL::integer AS system_group_id,
                            'specific_users'::varchar AS recipient_source,
                            meta.notification_recipient_filter_domain AS filter_domain,
                            NULL::text AS note,
                            rel.%(meta_user_user_col)s AS user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN %(meta_user_rel)s rel
                          ON rel.%(meta_user_meta_col)s = meta.id
                        WHERE (
                            meta.notification_recipient_source = 'specific_users'
                            OR (
                                COALESCE(meta.notification_recipient_source, '') = ''
                                AND meta.notification_recipient_mode IN ('specific_users', 'both')
                            )
                        )

                        UNION ALL

                        SELECT
                            meta.id AS meta_task_id,
                            ag.id AS approval_group_id,
                            NULL::integer AS system_group_id,
                            'approval_group_users'::varchar AS recipient_source,
                            meta.notification_recipient_filter_domain AS filter_domain,
                            NULL::text AS note,
                            gu.%(user_col)s AS user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN %(meta_approval_group_rel)s rel
                          ON rel.%(meta_approval_group_meta_col)s = meta.id
                        JOIN workflow_approval_group ag
                          ON ag.id = rel.%(meta_approval_group_group_col)s
                        JOIN %(group_user_rel)s gu
                          ON gu.%(group_col)s = ag.id
                        WHERE (
                            meta.notification_recipient_source = 'approval_group_users'
                            OR COALESCE(meta.notification_recipient_source, '') = ''
                        )

                        UNION ALL

                        SELECT
                            meta.id AS meta_task_id,
                            NULL::integer AS approval_group_id,
                            grp.id AS system_group_id,
                            'group_users'::varchar AS recipient_source,
                            meta.notification_recipient_filter_domain AS filter_domain,
                            NULL::text AS note,
                            sgu.%(system_group_user_col)s AS user_id
                        FROM workflow_category_version_meta_task meta
                        JOIN %(meta_group_rel)s rel
                          ON rel.%(meta_group_meta_col)s = meta.id
                        JOIN res_groups grp
                          ON grp.id = rel.%(meta_group_group_col)s
                        JOIN %(system_group_user_rel)s sgu
                          ON sgu.%(system_group_group_col)s = grp.id
                        WHERE meta.notification_recipient_source = 'group_users'
                    ),
                    channel_email_lines AS (
                        SELECT
                            meta.id AS meta_task_id,
                            action.id AS action_id,
                            line.id AS line_id,
                            line.header,
                            line.source,
                            line.domain
                        FROM workflow_category_version_meta_task meta
                        JOIN %(meta_action_rel)s task_action_rel
                          ON task_action_rel.%(meta_action_meta_col)s = meta.id
                        JOIN workflow_approval_action action
                          ON action.id = task_action_rel.%(meta_action_action_col)s
                        JOIN workflow_approval_action_email_recipient line
                          ON line.action_id = action.id
                        WHERE meta.node_type = 'sendTask'
                          AND action.action_type = 'email'
                    ),
                    approval_group_linked_category_source AS (
                        SELECT DISTINCT
                            tag.approval_group_id AS approval_group_id,
                            ver.category_id AS category_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id
                        FROM workflow_category_task_approval_group tag
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = tag.meta_id
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category cat
                          ON cat.id = ver.category_id
                        WHERE ver.category_id IS NOT NULL

                        UNION

                        SELECT DISTINCT
                            rel.%(meta_approval_group_group_col)s AS approval_group_id,
                            ver.category_id AS category_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id
                        FROM %(meta_approval_group_rel)s rel
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = rel.%(meta_approval_group_meta_col)s
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category cat
                          ON cat.id = ver.category_id
                        WHERE ver.category_id IS NOT NULL

                        UNION

                        SELECT DISTINCT
                            rel.%(line_approval_group_group_col)s AS approval_group_id,
                            ver.category_id AS category_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id
                        FROM %(line_approval_group_rel)s rel
                        JOIN workflow_approval_action_email_recipient line
                          ON line.id = rel.%(line_approval_group_line_col)s
                        JOIN workflow_approval_action action
                          ON action.id = line.action_id
                        JOIN %(meta_action_rel)s task_action_rel
                          ON task_action_rel.%(meta_action_action_col)s = action.id
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = task_action_rel.%(meta_action_meta_col)s
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category cat
                          ON cat.id = ver.category_id
                        WHERE ver.category_id IS NOT NULL
                    ),
                    group_member_category_map AS (
                        SELECT DISTINCT
                            src.approval_group_id AS approval_group_id,
                            src.category_id AS category_id,
                            src.request_model_id AS request_model_id
                        FROM approval_group_linked_category_source src

                        UNION ALL

                        SELECT
                            ag.id AS approval_group_id,
                            ag.category_id AS category_id,
                            cat.res_model AS request_model_id
                        FROM workflow_approval_group ag
                        LEFT JOIN workflow_approval_category cat
                          ON cat.id = ag.category_id
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM approval_group_linked_category_source src
                            WHERE src.approval_group_id = ag.id
                        )
                    ),
                    matrix_source AS (
                        SELECT
                            'group_member'::varchar AS usage_type,
                            ag.id AS approval_group_id,
                            NULL::integer AS system_group_id,
                            group_map.category_id AS category_id,
                            NULL::integer AS version_id,
                            group_map.request_model_id AS request_model_id,
                            NULL::integer AS meta_task_id,
                            NULL::integer AS task_sequence,
                            NULL::varchar AS node_id,
                            NULL::varchar AS node_type,
                            NULL::varchar AS assignment_mode,
                            NULL::varchar AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            NULL::varchar AS notification_delivery_mode,
                            NULL::varchar AS notification_recipient_source,
                            NULL::varchar AS notification_filter_domain,
                            NULL::integer AS notification_action_id,
                            NULL::integer AS email_recipient_line_id,
                            NULL::varchar AS email_header,
                            NULL::varchar AS email_recipient_source,
                            NULL::text AS note,
                            gu.%(user_col)s AS user_id
                        FROM workflow_approval_group ag
                        JOIN group_member_category_map group_map
                          ON group_map.approval_group_id = ag.id
                        JOIN %(group_user_rel)s gu
                          ON gu.%(group_col)s = ag.id

                        UNION ALL

                        SELECT
                            'approval'::varchar AS usage_type,
                            tag.approval_group_id AS approval_group_id,
                            NULL::integer AS system_group_id,
                            COALESCE(ver.category_id, ag.category_id) AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            tag.user_domain AS user_filter_domain,
                            tag.domain AS record_domain,
                            NULL::varchar AS notification_delivery_mode,
                            NULL::varchar AS notification_recipient_source,
                            NULL::varchar AS notification_filter_domain,
                            NULL::integer AS notification_action_id,
                            NULL::integer AS email_recipient_line_id,
                            NULL::varchar AS email_header,
                            NULL::varchar AS email_recipient_source,
                            tag.note AS note,
                            gu.%(user_col)s AS user_id
                        FROM workflow_category_task_approval_group tag
                        JOIN workflow_approval_group ag
                          ON ag.id = tag.approval_group_id
                        JOIN %(group_user_rel)s gu
                          ON gu.%(group_col)s = ag.id
                        LEFT JOIN workflow_category_version_meta_task meta
                          ON meta.id = tag.meta_id
                        LEFT JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        LEFT JOIN workflow_approval_category cat
                          ON cat.id = COALESCE(ver.category_id, ag.category_id)

                        UNION ALL

                        SELECT
                            'notification'::varchar AS usage_type,
                            src.approval_group_id AS approval_group_id,
                            src.system_group_id AS system_group_id,
                            COALESCE(ver.category_id, ag.category_id) AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            meta.notification_delivery_mode AS notification_delivery_mode,
                            src.recipient_source AS notification_recipient_source,
                            src.filter_domain AS notification_filter_domain,
                            NULL::integer AS notification_action_id,
                            NULL::integer AS email_recipient_line_id,
                            NULL::varchar AS email_header,
                            NULL::varchar AS email_recipient_source,
                            src.note AS note,
                            src.user_id AS user_id
                        FROM configured_send_task_recipients src
                        LEFT JOIN workflow_category_version_meta_task meta
                          ON meta.id = src.meta_task_id
                        LEFT JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        LEFT JOIN workflow_approval_group ag
                          ON ag.id = src.approval_group_id
                        LEFT JOIN workflow_approval_category cat
                          ON cat.id = COALESCE(ver.category_id, ag.category_id)

                        UNION ALL

                        SELECT
                            'channel_notification'::varchar AS usage_type,
                            NULL::integer AS approval_group_id,
                            NULL::integer AS system_group_id,
                            ver.category_id AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            'channels'::varchar AS notification_delivery_mode,
                            meta.notification_recipient_source AS notification_recipient_source,
                            line.domain AS notification_filter_domain,
                            line.action_id AS notification_action_id,
                            line.line_id AS email_recipient_line_id,
                            line.header AS email_header,
                            line.source AS email_recipient_source,
                            NULL::text AS note,
                            rel.%(line_user_user_col)s AS user_id
                        FROM channel_email_lines line
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = line.meta_task_id
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category cat
                          ON cat.id = ver.category_id
                        JOIN %(line_user_rel)s rel
                          ON rel.%(line_user_line_col)s = line.line_id
                        WHERE line.source = 'specific_users'

                        UNION ALL

                        SELECT
                            'channel_notification'::varchar AS usage_type,
                            ag.id AS approval_group_id,
                            NULL::integer AS system_group_id,
                            COALESCE(ver.category_id, ag.category_id) AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            'channels'::varchar AS notification_delivery_mode,
                            meta.notification_recipient_source AS notification_recipient_source,
                            line.domain AS notification_filter_domain,
                            line.action_id AS notification_action_id,
                            line.line_id AS email_recipient_line_id,
                            line.header AS email_header,
                            line.source AS email_recipient_source,
                            NULL::text AS note,
                            gu.%(user_col)s AS user_id
                        FROM channel_email_lines line
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = line.meta_task_id
                        JOIN %(line_approval_group_rel)s rel
                          ON rel.%(line_approval_group_line_col)s = line.line_id
                        JOIN workflow_approval_group ag
                          ON ag.id = rel.%(line_approval_group_group_col)s
                        JOIN %(group_user_rel)s gu
                          ON gu.%(group_col)s = ag.id
                        LEFT JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        LEFT JOIN workflow_approval_category cat
                          ON cat.id = COALESCE(ver.category_id, ag.category_id)
                        WHERE line.source = 'approval_group_users'

                        UNION ALL

                        SELECT
                            'channel_notification'::varchar AS usage_type,
                            NULL::integer AS approval_group_id,
                            grp.id AS system_group_id,
                            ver.category_id AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            'channels'::varchar AS notification_delivery_mode,
                            meta.notification_recipient_source AS notification_recipient_source,
                            line.domain AS notification_filter_domain,
                            line.action_id AS notification_action_id,
                            line.line_id AS email_recipient_line_id,
                            line.header AS email_header,
                            line.source AS email_recipient_source,
                            NULL::text AS note,
                            sgu.%(system_group_user_col)s AS user_id
                        FROM channel_email_lines line
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = line.meta_task_id
                        JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        JOIN workflow_approval_category cat
                          ON cat.id = ver.category_id
                        JOIN %(line_group_rel)s rel
                          ON rel.%(line_group_line_col)s = line.line_id
                        JOIN res_groups grp
                          ON grp.id = rel.%(line_group_group_col)s
                        JOIN %(system_group_user_rel)s sgu
                          ON sgu.%(system_group_group_col)s = grp.id
                        WHERE line.source = 'group_users'

                        UNION ALL

                        SELECT
                            'channel_notification'::varchar AS usage_type,
                            src.approval_group_id AS approval_group_id,
                            src.system_group_id AS system_group_id,
                            COALESCE(ver.category_id, ag.category_id) AS category_id,
                            meta.version_id AS version_id,
                            COALESCE(ver.res_model_id, cat.res_model) AS request_model_id,
                            meta.id AS meta_task_id,
                            meta.sequence AS task_sequence,
                            meta.node_id AS node_id,
                            meta.node_type AS node_type,
                            meta.assignment_mode AS assignment_mode,
                            meta.completion_mode AS completion_mode,
                            NULL::varchar AS user_filter_domain,
                            NULL::varchar AS record_domain,
                            'channels'::varchar AS notification_delivery_mode,
                            src.recipient_source AS notification_recipient_source,
                            COALESCE(line.domain, src.filter_domain) AS notification_filter_domain,
                            line.action_id AS notification_action_id,
                            line.line_id AS email_recipient_line_id,
                            line.header AS email_header,
                            line.source AS email_recipient_source,
                            src.note AS note,
                            src.user_id AS user_id
                        FROM channel_email_lines line
                        JOIN workflow_category_version_meta_task meta
                          ON meta.id = line.meta_task_id
                        JOIN configured_send_task_recipients src
                          ON src.meta_task_id = meta.id
                        LEFT JOIN workflow_approval_category_version ver
                          ON ver.id = meta.version_id
                        LEFT JOIN workflow_approval_group ag
                          ON ag.id = src.approval_group_id
                        LEFT JOIN workflow_approval_category cat
                          ON cat.id = COALESCE(ver.category_id, ag.category_id)
                        WHERE line.source = 'send_task'
                    )
                    SELECT
                        row_number() OVER (
                            ORDER BY
                                src.category_id NULLS LAST,
                                src.usage_type,
                                src.approval_group_id,
                                src.system_group_id,
                                src.meta_task_id NULLS LAST,
                                src.notification_action_id NULLS LAST,
                                src.email_recipient_line_id NULLS LAST,
                                src.user_id
                        ) AS id,
                        1 AS user_count,
                        src.usage_type,
                        src.user_id,
                        emp.id AS employee_id,
                        COALESCE(emp.x_emp_code, usr.emp_code) AS employee_code,
                        COALESCE(emp.name, partner.name, usr.login) AS employee_name,
                        emp_version.department_id AS employee_department_id,
                        %(employee_team_expr)s AS employee_team,
                        %(employee_line_expr)s AS employee_line,
                        emp_version.job_id AS employee_job_id,
                        COALESCE(emp_version.job_title, job.name->>'en_US') AS employee_position,
                        emp.x_ext_phone AS extension,
                        COALESCE(emp.work_email, partner.email) AS work_email,
                        emp.work_phone AS work_phone,
                        emp.mobile_phone AS mobile_phone,
                        usr.login AS user_login,
                        usr.active AS user_active,
                        usr.share AS user_share,
                        COALESCE(emp.company_id, usr.company_id) AS company_id,
                        src.category_id,
                        src.version_id,
                        src.request_model_id,
                        model.model AS request_model_name,
                        src.approval_group_id,
                        ag.parent_id AS parent_group_id,
                        src.system_group_id,
                        ag.department_id AS group_department_id,
                        ag.line_id,
                        ag.team_id,
                        src.meta_task_id,
                        src.task_sequence,
                        src.node_id,
                        src.node_type,
                        src.assignment_mode,
                        src.completion_mode,
                        src.user_filter_domain,
                        src.record_domain,
                        src.notification_delivery_mode,
                        src.notification_recipient_source,
                        src.notification_filter_domain,
                        src.notification_action_id,
                        src.email_recipient_line_id,
                        src.email_header,
                        src.email_recipient_source,
                        src.note
                    FROM matrix_source src
                    JOIN res_users usr
                      ON usr.id = src.user_id
                    LEFT JOIN workflow_approval_group ag
                      ON ag.id = src.approval_group_id
                    LEFT JOIN LATERAL (
                        SELECT he.*
                        FROM hr_employee he
                        WHERE he.user_id = usr.id
                        ORDER BY he.active DESC, he.id
                        LIMIT 1
                    ) emp ON TRUE
                    LEFT JOIN hr_version emp_version
                      ON emp_version.id = emp.current_version_id
                    LEFT JOIN hr_job job
                      ON job.id = emp_version.job_id
                    LEFT JOIN res_partner partner
                      ON partner.id = usr.partner_id
                    LEFT JOIN ir_model model
                      ON model.id = src.request_model_id
                )
                """,
                table=SQL.identifier(self._table),
                group_user_rel=SQL.identifier(group_user_rel),
                group_col=SQL.identifier(group_user_group_col),
                user_col=SQL.identifier(group_user_user_col),
                system_group_user_rel=SQL.identifier(system_group_user_rel),
                system_group_group_col=SQL.identifier(system_group_group_col),
                system_group_user_col=SQL.identifier(system_group_user_col),
                meta_user_rel=SQL.identifier(meta_user_rel),
                meta_user_meta_col=SQL.identifier(meta_user_meta_col),
                meta_user_user_col=SQL.identifier(meta_user_user_col),
                meta_approval_group_rel=SQL.identifier(meta_approval_group_rel),
                meta_approval_group_meta_col=SQL.identifier(meta_approval_group_meta_col),
                meta_approval_group_group_col=SQL.identifier(meta_approval_group_group_col),
                meta_group_rel=SQL.identifier(meta_group_rel),
                meta_group_meta_col=SQL.identifier(meta_group_meta_col),
                meta_group_group_col=SQL.identifier(meta_group_group_col),
                meta_action_rel=SQL.identifier(meta_action_rel),
                meta_action_meta_col=SQL.identifier(meta_action_meta_col),
                meta_action_action_col=SQL.identifier(meta_action_action_col),
                line_user_rel=SQL.identifier(line_user_rel),
                line_user_line_col=SQL.identifier(line_user_line_col),
                line_user_user_col=SQL.identifier(line_user_user_col),
                line_approval_group_rel=SQL.identifier(line_approval_group_rel),
                line_approval_group_line_col=SQL.identifier(line_approval_group_line_col),
                line_approval_group_group_col=SQL.identifier(line_approval_group_group_col),
                line_group_rel=SQL.identifier(line_group_rel),
                line_group_line_col=SQL.identifier(line_group_line_col),
                line_group_group_col=SQL.identifier(line_group_group_col),
                employee_line_expr=employee_line_expr,
                employee_team_expr=employee_team_expr,
            )
        )
