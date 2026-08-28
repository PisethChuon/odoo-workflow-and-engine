from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.exceptions import UserError, ValidationError

DEFAULT_WORKFLOW_REQUEST_OWNER_EMAIL_DOMAINS = "nagaworld.com,nagworld.com"


class User(models.Model):
    _inherit = 'res.users'

    employee_parent_id = fields.Many2one(related='employee_id.parent_id', readonly=False, related_sudo=False)

    department_id = fields.Many2one(related='employee_id.department_id', readonly=False, related_sudo=False)

    wf_request_owner_emp_code = fields.Char(
        string="Emp Code",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_employee_name = fields.Char(
        string="Employee Name",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_department = fields.Char(
        string="Request Owner Department",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_position = fields.Char(
        string="Position",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_extension = fields.Char(
        string="Extension",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_work_mobile = fields.Char(
        string="Request Owner Work Mobile",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_phone = fields.Char(
        string="Request Owner Phone Number",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_email = fields.Char(
        string="Request Owner Email",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_request_owner_job_position = fields.Char(
        string="Request Owner Job Position",
        compute="_compute_wf_request_owner_picker_fields",
        compute_sudo=True,
    )
    wf_hide_from_workflow_picker = fields.Boolean(
        string="Hide From Workflow Picker",
        help="Exclude this user from workflow request owner and approver/delegate selections.",
    )
    wf_request_owner_has_employee = fields.Boolean(
        string="Has Employee Profile",
        compute="_compute_wf_request_owner_grouping_fields",
        compute_sudo=True,
        store=True,
        index=True,
    )
    wf_request_owner_employee_profile = fields.Selection(
        [
            ("employee", "Employee"),
            ("non_employee", "Non Employee"),
        ],
        string="Employee Profile",
        compute="_compute_wf_request_owner_grouping_fields",
        compute_sudo=True,
        store=True,
        index=True,
    )
    wf_request_owner_department_id = fields.Many2one(
        "hr.department",
        string="Request Owner Department Group",
        compute="_compute_wf_request_owner_grouping_fields",
        compute_sudo=True,
        store=True,
        index=True,
    )
    wf_request_owner_job_id = fields.Many2one(
        "hr.job",
        string="Request Owner Position",
        compute="_compute_wf_request_owner_grouping_fields",
        compute_sudo=True,
        store=True,
        index=True,
    )

    wf_ooo_enabled = fields.Boolean(
        string="Workflow Out of Office",
        help="Enable temporary delegation for workflow approvals.",
    )
    wf_ooo_delegate_user_id = fields.Many2one(
        "res.users",
        string="Delegate Approver",
        domain="[('id', '!=', id), ('active', '=', True), ('share', '=', False), ('wf_hide_from_workflow_picker', '=', False)]",
        help="User who can approve on your behalf during your out-of-office period.",
    )
    wf_ooo_date_from = fields.Datetime(string="Out From")
    wf_ooo_date_to = fields.Datetime(string="Out To")
    wf_ooo_scope = fields.Selection(
        [("approvals", "Approvals"), ("all", "All")],
        string="Delegation Scope",
        default="approvals",
        required=True,
    )
    wf_ooo_category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_user_ooo_category_rel",
        "user_id",
        "category_id",
        string="Workflow Categories",
        help="Optional: if set, delegation applies only to these workflow categories.",
    )
    wf_ooo_note = fields.Char(string="Delegation Note")
    wf_ooo_delegation_id = fields.Many2one(
        "workflow.approval.delegation",
        string="Out of Office Delegation",
        compute="_compute_wf_ooo_delegation_id",
        compute_sudo=True,
    )
    wf_ooo_delegation_history_ids = fields.One2many(
        "workflow.approval.delegation",
        "delegator_user_id",
        string="Out of Office Delegation History",
        domain=[("delegation_source", "=", "out_of_office")],
        readonly=True,
    )
    wf_ooo_is_active_now = fields.Boolean(
        string="OOO Active Now",
        compute="_compute_wf_ooo_is_active_now",
        compute_sudo=True,
    )
    wf_approval_push_enabled = fields.Boolean(
        string="Workflow Approval Push",
        default=True,
        help="Receive workflow approval push and inbox notifications when an approval is assigned to you.",
    )

    _wf_ooo_sync_fields = {
        "wf_ooo_enabled",
        "wf_ooo_delegate_user_id",
        "wf_ooo_date_from",
        "wf_ooo_date_to",
        "wf_ooo_scope",
        "wf_ooo_note",
        "wf_ooo_category_ids",
    }

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            UPDATE res_users
               SET wf_approval_push_enabled = TRUE
             WHERE wf_approval_push_enabled IS NULL
            """
        )

    @api.model
    def action_get(self):
        current_user = self.env.user
        if (
            current_user.employee_id
            and not current_user.has_group("hr.group_hr_user")
            and not current_user.has_group("base.group_system")
        ):
            return self.env["ir.actions.act_window"]._for_xml_id("base.action_res_users_my")
        return super().action_get()

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            "wf_ooo_enabled",
            "wf_ooo_delegate_user_id",
            "wf_ooo_date_from",
            "wf_ooo_date_to",
            "wf_ooo_scope",
            "wf_ooo_category_ids",
            "wf_ooo_note",
            "wf_ooo_delegation_id",
            "wf_ooo_delegation_history_ids",
            "wf_ooo_is_active_now",
            "wf_approval_push_enabled",
        ]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + [
            "wf_ooo_enabled",
            "wf_ooo_delegate_user_id",
            "wf_ooo_date_from",
            "wf_ooo_date_to",
            "wf_ooo_scope",
            "wf_ooo_category_ids",
            "wf_ooo_note",
            "wf_approval_push_enabled",
        ]

    @api.depends(
        "wf_ooo_enabled",
        "wf_ooo_delegate_user_id",
        "wf_ooo_date_from",
        "wf_ooo_date_to",
    )
    def _compute_wf_ooo_is_active_now(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.wf_ooo_is_active_now = bool(
                rec.wf_ooo_enabled
                and rec.wf_ooo_delegate_user_id
                and rec.wf_ooo_date_from
                and rec.wf_ooo_date_to
                and rec.wf_ooo_date_from <= now <= rec.wf_ooo_date_to
            )

    @api.depends(
        "name",
        "login",
        "email",
        "phone",
        "mobile_phone",
        "work_phone",
        "work_email",
        "function",
        "partner_id.name",
        "partner_id.email",
        "partner_id.phone",
        "partner_id.function",
        "employee_id.name",
        "employee_id.x_emp_code",
        "employee_id.department_id.name",
        "employee_id.job_id.name",
        "employee_id.job_title",
        "employee_id.x_ext_phone",
        "employee_id.mobile_phone",
        "employee_id.work_phone",
        "employee_id.phone",
        "employee_id.work_email",
    )
    def _compute_wf_request_owner_picker_fields(self):
        allowed_email_domains = self._workflow_request_owner_email_domains()
        for user in self:
            employee = user.employee_id.sudo() if user.employee_id else self.env["hr.employee"]
            partner = user.partner_id.sudo() if user.partner_id else self.env["res.partner"]

            user.wf_request_owner_emp_code = employee.x_emp_code or ""
            user.wf_request_owner_employee_name = employee.name or partner.name or user.name or ""
            user.wf_request_owner_department = employee.department_id.display_name or ""
            user.wf_request_owner_position = employee.job_id.display_name or employee.job_title or ""
            user.wf_request_owner_extension = employee.x_ext_phone or ""
            user.wf_request_owner_work_mobile = employee.mobile_phone or user.mobile_phone or ""
            user.wf_request_owner_phone = (
                employee.work_phone
                or employee.phone
                or user.work_phone
                or user.phone
                or partner.phone
                or ""
            )
            user.wf_request_owner_email = self._workflow_request_owner_pick_email(
                [
                    employee.work_email,
                    user.email,
                    partner.email,
                ],
                allowed_email_domains=allowed_email_domains,
            )
            user.wf_request_owner_job_position = employee.job_title or user.function or partner.function or ""

    @api.model
    def _workflow_request_owner_email_domains(self):
        raw_value = self.env["ir.config_parameter"].sudo().get_param(
            "workflow_engine.request_owner_email_domains"
        ) or DEFAULT_WORKFLOW_REQUEST_OWNER_EMAIL_DOMAINS
        domains = set()
        for value in raw_value.replace(";", ",").replace("\n", ",").split(","):
            normalized = value.strip().lower()
            if not normalized:
                continue
            if "@" in normalized:
                normalized = normalized.rsplit("@", 1)[-1]
            domains.add(normalized)
        return domains

    @api.model
    def _workflow_request_owner_pick_email(self, email_candidates, allowed_email_domains=None):
        allowed_email_domains = (
            allowed_email_domains
            if allowed_email_domains is not None
            else self._workflow_request_owner_email_domains()
        )
        for email in email_candidates:
            normalized_email = (email or "").strip()
            if not normalized_email or "@" not in normalized_email:
                continue
            email_domain = normalized_email.rsplit("@", 1)[-1].lower()
            if email_domain in allowed_email_domains:
                return normalized_email
        return ""

    def _workflow_request_owner_group_employee(self):
        self.ensure_one()
        employees = self.employee_ids.sudo()
        if not employees:
            return self.env["hr.employee"]
        company = self.company_id or self.env.company
        employee = employees.filtered(lambda emp: emp.company_id == company)[:1]
        return employee or employees[:1]

    @api.depends(
        "company_id",
        "employee_ids",
        "employee_ids.company_id",
        "employee_ids.department_id",
        "employee_ids.job_id",
    )
    def _compute_wf_request_owner_grouping_fields(self):
        for user in self:
            employee = user._workflow_request_owner_group_employee()
            user.wf_request_owner_has_employee = bool(employee)
            user.wf_request_owner_employee_profile = "employee" if employee else "non_employee"
            user.wf_request_owner_department_id = employee.department_id if employee else False
            user.wf_request_owner_job_id = employee.job_id if employee else False

    @api.model
    def _workflow_picker_domain(self):
        if self.env.context.get("workflow_request_owner_picker") or self.env.context.get("workflow_delegate_picker"):
            return Domain("wf_hide_from_workflow_picker", "=", False)
        return Domain.TRUE

    def _workflow_picker_domain_for_search(self, domain=None):
        return list(Domain(domain or Domain.TRUE) & self._workflow_picker_domain())

    @api.depends(
        "wf_ooo_enabled",
        "wf_ooo_delegate_user_id",
        "wf_ooo_date_from",
        "wf_ooo_date_to",
        "wf_ooo_scope",
        "wf_ooo_note",
        "wf_ooo_category_ids",
    )
    def _compute_wf_ooo_delegation_id(self):
        Delegation = self.env["workflow.approval.delegation"].sudo()
        for rec in self:
            rec.wf_ooo_delegation_id = Delegation.search(
                [
                    ("delegator_user_id", "=", rec.id),
                    ("delegation_source", "=", "out_of_office"),
                ],
                order="active desc, date_to desc, id desc",
                limit=1,
            )

    @api.constrains("wf_ooo_enabled", "wf_ooo_delegate_user_id", "wf_ooo_date_from", "wf_ooo_date_to")
    def _check_wf_ooo_config(self):
        for rec in self:
            if not rec.wf_ooo_enabled:
                continue
            has_partial_config = bool(rec.wf_ooo_delegate_user_id or rec.wf_ooo_date_from or rec.wf_ooo_date_to)
            if not has_partial_config:
                continue
            if not rec.wf_ooo_delegate_user_id:
                raise ValidationError("Please select a delegate approver for Out of Office.")
            if rec.wf_ooo_delegate_user_id == rec:
                raise ValidationError("Delegate approver cannot be the same user.")
            if rec.wf_ooo_delegate_user_id.wf_hide_from_workflow_picker:
                raise ValidationError("Selected delegate approver is hidden from workflow selections.")
            if not rec.wf_ooo_date_from or not rec.wf_ooo_date_to:
                raise ValidationError("Please set both Out From and Out To for Out of Office.")
            if rec.wf_ooo_date_to < rec.wf_ooo_date_from:
                raise ValidationError("Out To must be after Out From.")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_workflow_ooo_delegations(changed_fields=self._wf_ooo_sync_fields)
        return records

    def write(self, vals):
        res = super().write(vals)
        changed_fields = set(vals.keys()) & self._wf_ooo_sync_fields
        if changed_fields and not self.env.context.get("workflow_skip_ooo_sync"):
            self._sync_workflow_ooo_delegations(changed_fields=changed_fields)
        return res

    def _prepare_workflow_ooo_delegation_vals(self):
        self.ensure_one()
        note = self.wf_ooo_note or ""
        if note:
            note = f"[OOO] {note}"
        else:
            note = "[OOO] Delegation from user preference"
        return {
            "delegator_user_id": self.id,
            "delegate_user_id": self.wf_ooo_delegate_user_id.id,
            "date_from": self.wf_ooo_date_from,
            "date_to": self.wf_ooo_date_to,
            "scope": self.wf_ooo_scope or "approvals",
            "active": True,
            "delegation_source": "out_of_office",
            "assignment_strategy": "cc_delegate",
            "note": note,
            "category_ids": [(6, 0, self.wf_ooo_category_ids.ids)],
        }

    def _sync_workflow_ooo_delegations(self, changed_fields=None):
        if changed_fields and not (set(changed_fields) & self._wf_ooo_sync_fields):
            return
        Delegation = self.env["workflow.approval.delegation"].sudo()
        for rec in self:
            is_workflow_user = rec.has_group("workflow_engine.group_workflow_approval_user") or rec.has_group(
                "workflow_engine.group_workflow_approval_admin"
            )
            domain = [
                ("delegator_user_id", "=", rec.id),
                ("delegation_source", "=", "out_of_office"),
            ]
            existing = Delegation.search(domain, order="id desc")

            if not is_workflow_user:
                if existing:
                    existing.write({"active": False})
                continue

            if not rec.wf_ooo_enabled:
                if existing:
                    existing.write({"active": False})
                continue

            if not (rec.wf_ooo_delegate_user_id and rec.wf_ooo_date_from and rec.wf_ooo_date_to):
                if existing:
                    existing.write({"active": False})
                continue

            vals = rec._prepare_workflow_ooo_delegation_vals()
            if existing:
                primary = existing[:1]
                primary.write(vals)
                (existing - primary).write({"active": False})
            else:
                Delegation.create(vals)

    def action_open_workflow_ooo_wizard(self):
        self.ensure_one()
        if self != self.env.user and not self.env.user.has_group("base.group_system"):
            raise UserError(_("You can only configure Out of Office for your own account."))

        action = self.env["ir.actions.actions"]._for_xml_id(
            "workflow_engine.action_workflow_ooo_preference_wizard"
        )
        action_context = dict(self.env.context or {})
        action_context.update(
            {
                "default_user_id": self.id,
                "form_view_initial_mode": "edit",
            }
        )
        action["context"] = action_context
        return action

    @api.model
    def _get_activity_groups(self):
        """Override to use the approval category image as the systray activity icon
        for models that have a workflow.approval.category configured.

        Only models with a matching category are affected — all others keep the
        default module icon returned by the parent method.
        """
        groups = super()._get_activity_groups()

        # Collect model names that appear in the activity groups
        model_names = [g["model"] for g in groups if g.get("model")]
        if not model_names:
            return groups

        # Look up approval categories for these models (one per model is enough)
        categories = self.env["workflow.approval.category"].sudo().search(
            [("res_model_name", "in", model_names), ("image", "!=", False)],
            order="id asc",
        )
        # Build a map: res_model_name → image URL (first category wins)
        icon_by_model = {}
        for cat in categories:
            if cat.res_model_name and cat.res_model_name not in icon_by_model:
                icon_by_model[cat.res_model_name] = (
                    f"/web/image/workflow.approval.category/{cat.id}/image"
                )

        if not icon_by_model:
            return groups

        for group in groups:
            model_name = group.get("model")
            if model_name and model_name in icon_by_model:
                group["icon"] = icon_by_model[model_name]

        return groups

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        user_domain = Domain(self._workflow_picker_domain_for_search(domain))
        result = super().name_search(name=name, domain=list(user_domain), operator=operator, limit=limit)
        if not name or operator in Domain.NEGATIVE_OPERATORS:
            return result

        extra_domains = []
        if self.env.context.get("workflow_request_owner_picker") or self.env.context.get("workflow_delegate_picker"):
            employee_model = self.env["hr.employee"]
            if "x_emp_code" in employee_model._fields:
                extra_domains.append(Domain("employee_ids.x_emp_code", operator, name))
            extra_domains.extend(
                [
                    Domain("employee_ids.name", operator, name),
                    Domain("name", operator, name),
                    Domain("login", operator, name),
                    Domain("email", operator, name),
                    Domain("partner_id.name", operator, name),
                    Domain("partner_id.email", operator, name),
                ]
            )

        if not extra_domains:
            return result

        remaining = None if limit is None else limit - len(result)
        if remaining is not None and remaining <= 0:
            return result

        existing_ids = {user_id for user_id, _label in result}
        user_domain &= Domain.OR(extra_domains)
        if existing_ids:
            user_domain &= Domain("id", "not in", list(existing_ids))

        extra_users = self.search(user_domain, limit=remaining)
        if extra_users:
            result.extend((user.id, user.display_name) for user in extra_users)
        return result

    @api.model
    @api.readonly
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        domain = self._workflow_picker_domain_for_search(domain)
        return super().web_search_read(
            domain,
            specification,
            offset=offset,
            limit=limit,
            order=order,
            count_limit=count_limit,
        )

    @api.model
    @api.readonly
    def web_read_group(
        self,
        domain,
        groupby,
        aggregates=(),
        limit=None,
        offset=0,
        order=None,
        *,
        auto_unfold=False,
        opening_info=None,
        unfold_read_specification=None,
        unfold_read_default_limit=80,
        groupby_read_specification=None,
    ):
        domain = self._workflow_picker_domain_for_search(domain)
        return super().web_read_group(
            domain,
            groupby,
            aggregates=aggregates,
            limit=limit,
            offset=offset,
            order=order,
            auto_unfold=auto_unfold,
            opening_info=opening_info,
            unfold_read_specification=unfold_read_specification,
            unfold_read_default_limit=unfold_read_default_limit,
            groupby_read_specification=groupby_read_specification,
        )
