from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class WorkflowOOOPreferenceWizard(models.TransientModel):
    _name = "workflow.ooo.preference.wizard"
    _description = "Workflow Out of Office Preference Wizard"

    user_id = fields.Many2one("res.users", string="User", required=True, readonly=True, default=lambda self: self.env.user)

    wf_ooo_enabled = fields.Boolean(
        string="Enable Out of Office",
        help="When enabled, workflow approvals can be handled by your delegate in the selected period.",
    )
    wf_ooo_delegate_user_id = fields.Many2one(
        "res.users",
        string="Assign To",
        domain="[('id', '!=', user_id), ('active', '=', True), ('share', '=', False), ('wf_hide_from_workflow_picker', '=', False)]",
        help="Approvals assigned to you during this period will also be assigned to this delegate.",
    )
    wf_ooo_date_from = fields.Datetime(string="From")
    wf_ooo_date_to = fields.Datetime(string="To")
    wf_ooo_scope = fields.Selection(
        [("approvals", "Approvals"), ("all", "All")],
        string="Delegation Scope",
        default="approvals",
        required=True,
    )
    wf_ooo_category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_ooo_preference_wizard_category_rel",
        "wizard_id",
        "category_id",
        string="Workflow Categories",
        help="Optional: if set, delegation applies only to these workflow categories.",
    )
    wf_ooo_note = fields.Char(string="Delegation Note")
    wf_ooo_delegation_history_ids = fields.One2many(
        related="user_id.wf_ooo_delegation_history_ids",
        readonly=True,
        string="Out of Office History",
    )
    wf_ooo_line_ids = fields.One2many(
        "workflow.ooo.preference.wizard.line",
        "wizard_id",
        string="Delegation Rules",
    )
    wf_ooo_is_active_now = fields.Boolean(
        string="OOO Active Now",
        compute="_compute_wf_ooo_is_active_now",
    )

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

    @api.model
    def _prepare_line_from_delegation(self, delegation):
        return {
            "delegation_id": delegation.id,
            "active": delegation.active,
            "wf_ooo_delegate_user_id": delegation.delegate_user_id.id,
            "wf_ooo_date_from": delegation.date_from,
            "wf_ooo_date_to": delegation.date_to,
            "wf_ooo_scope": delegation.scope or "approvals",
            "wf_ooo_category_ids": [(6, 0, delegation.category_ids.ids)],
            "wf_ooo_note": (delegation.note or "").removeprefix("[OOO] ").strip(),
        }

    @api.model
    def _prepare_legacy_line_from_user(self, user):
        if not (user.wf_ooo_delegate_user_id and user.wf_ooo_date_from and user.wf_ooo_date_to):
            return False
        return {
            "active": True,
            "wf_ooo_delegate_user_id": user.wf_ooo_delegate_user_id.id,
            "wf_ooo_date_from": user.wf_ooo_date_from,
            "wf_ooo_date_to": user.wf_ooo_date_to,
            "wf_ooo_scope": user.wf_ooo_scope or "approvals",
            "wf_ooo_category_ids": [(6, 0, user.wf_ooo_category_ids.ids)],
            "wf_ooo_note": user.wf_ooo_note,
        }

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        user = self.env.user
        if "user_id" in fields_list and not vals.get("user_id"):
            vals["user_id"] = user.id

        if "wf_ooo_enabled" in fields_list:
            vals["wf_ooo_enabled"] = user.wf_ooo_enabled
        if "wf_ooo_delegate_user_id" in fields_list:
            vals["wf_ooo_delegate_user_id"] = user.wf_ooo_delegate_user_id.id
        if "wf_ooo_date_from" in fields_list:
            vals["wf_ooo_date_from"] = user.wf_ooo_date_from
        if "wf_ooo_date_to" in fields_list:
            vals["wf_ooo_date_to"] = user.wf_ooo_date_to
        if "wf_ooo_scope" in fields_list:
            vals["wf_ooo_scope"] = user.wf_ooo_scope or "approvals"
        if "wf_ooo_note" in fields_list:
            vals["wf_ooo_note"] = user.wf_ooo_note
        if "wf_ooo_category_ids" in fields_list:
            vals["wf_ooo_category_ids"] = [(6, 0, user.wf_ooo_category_ids.ids)]
        if "wf_ooo_line_ids" in fields_list:
            delegations = self.env["workflow.approval.delegation"].sudo().search(
                [
                    ("delegator_user_id", "=", user.id),
                    ("delegation_source", "=", "out_of_office"),
                    ("active", "=", True),
                ],
                order="date_from desc, id desc",
            )
            line_vals = [self._prepare_line_from_delegation(delegation) for delegation in delegations]
            if not line_vals:
                legacy_line = self._prepare_legacy_line_from_user(user)
                if legacy_line:
                    line_vals.append(legacy_line)
            vals["wf_ooo_line_ids"] = [(0, 0, line) for line in line_vals]
        return vals

    def _active_lines(self):
        self.ensure_one()
        return self.wf_ooo_line_ids.filtered("active")

    @staticmethod
    def _date_ranges_overlap(left, right):
        return left.wf_ooo_date_from <= right.wf_ooo_date_to and right.wf_ooo_date_from <= left.wf_ooo_date_to

    @staticmethod
    def _same_specific_category_scope(left, right):
        left_categories = left.wf_ooo_category_ids
        right_categories = right.wf_ooo_category_ids
        if not left_categories and not right_categories:
            return True
        if left_categories and right_categories and (left_categories & right_categories):
            return True
        return False

    def _validate_active_lines(self, target_user):
        self.ensure_one()
        active_lines = self._active_lines()
        if not active_lines:
            raise ValidationError(_("Please add at least one active Out of Office delegation rule."))
        for line in active_lines:
            line._validate_for_user(target_user)
        for index, line in enumerate(active_lines):
            for other in active_lines[index + 1:]:
                if not self._date_ranges_overlap(line, other):
                    continue
                if not self._same_specific_category_scope(line, other):
                    continue
                if line.wf_ooo_delegate_user_id != other.wf_ooo_delegate_user_id:
                    raise ValidationError(
                        _(
                            "Two Out of Office rules overlap for the same workflow category scope "
                            "but assign to different delegates. Please split the dates or categories."
                        )
                    )

    def _sync_delegation_rules(self, target_user):
        self.ensure_one()
        Delegation = self.env["workflow.approval.delegation"].sudo()
        existing = Delegation.search(
            [
                ("delegator_user_id", "=", target_user.id),
                ("delegation_source", "=", "out_of_office"),
            ]
        )
        if not self.wf_ooo_enabled:
            if existing:
                existing.write({"active": False})
            return Delegation.browse()

        active_lines = self._active_lines()
        kept = Delegation.browse()
        for line in active_lines:
            vals = line._prepare_delegation_vals(target_user)
            delegation = line.delegation_id if line.delegation_id in existing else Delegation.browse()
            if delegation:
                delegation.write(vals)
            else:
                delegation = Delegation.create(vals)
            kept |= delegation
        stale = existing - kept
        if stale:
            stale.write({"active": False})
        return kept

    def action_apply(self):
        self.ensure_one()
        target_user = self.user_id
        if target_user != self.env.user and not self.env.user.has_group("base.group_system"):
            raise UserError(_("You can only configure Out of Office for your own account."))
        if self.wf_ooo_enabled:
            self._validate_active_lines(target_user)

        delegations = self._sync_delegation_rules(target_user)
        primary = delegations.sorted(key=lambda d: (d.active, d.date_from, d.id), reverse=True)[:1]

        vals = {
            "wf_ooo_enabled": self.wf_ooo_enabled,
            "wf_ooo_delegate_user_id": primary.delegate_user_id.id if primary else False,
            "wf_ooo_date_from": primary.date_from if primary else False,
            "wf_ooo_date_to": primary.date_to if primary else False,
            "wf_ooo_scope": primary.scope if primary else "approvals",
            "wf_ooo_note": (primary.note or "").removeprefix("[OOO] ").strip() if primary else False,
            "wf_ooo_category_ids": [(6, 0, primary.category_ids.ids if primary else [])],
        }
        target_user.with_context(workflow_skip_ooo_sync=True).write(vals)
        return {"type": "ir.actions.client", "tag": "reload"}


class WorkflowOOOPreferenceWizardLine(models.TransientModel):
    _name = "workflow.ooo.preference.wizard.line"
    _description = "Workflow Out of Office Preference Wizard Line"
    _order = "active desc, wf_ooo_date_from desc, id desc"

    wizard_id = fields.Many2one("workflow.ooo.preference.wizard", required=True, ondelete="cascade")
    user_id = fields.Many2one(related="wizard_id.user_id", readonly=True)
    delegation_id = fields.Many2one("workflow.approval.delegation", readonly=True)
    active = fields.Boolean(string="Enabled", default=True)
    wf_ooo_delegate_user_id = fields.Many2one(
        "res.users",
        string="Assign To",
        domain="[('id', '!=', user_id), ('active', '=', True), ('share', '=', False), ('wf_hide_from_workflow_picker', '=', False)]",
    )
    wf_ooo_date_from = fields.Datetime(string="From")
    wf_ooo_date_to = fields.Datetime(string="To")
    wf_ooo_scope = fields.Selection(
        [("approvals", "Approvals"), ("all", "All")],
        string="Scope",
        default="approvals",
        required=True,
    )
    wf_ooo_category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_ooo_preference_wizard_line_category_rel",
        "line_id",
        "category_id",
        string="Workflow Categories",
        help="Leave empty to apply this rule to all workflow categories.",
    )
    wf_ooo_note = fields.Char(string="Note")

    def _validate_for_user(self, target_user):
        self.ensure_one()
        if not self.wf_ooo_delegate_user_id:
            raise ValidationError(_("Please select a delegate approver for every active Out of Office rule."))
        if self.wf_ooo_delegate_user_id == target_user:
            raise ValidationError(_("Delegate approver cannot be the same user."))
        if self.wf_ooo_delegate_user_id.share or not self.wf_ooo_delegate_user_id.active:
            raise ValidationError(_("Delegate approver must be an active internal user."))
        if self.wf_ooo_delegate_user_id.wf_hide_from_workflow_picker:
            raise ValidationError(_("Selected delegate approver is hidden from workflow selections."))
        if not self.wf_ooo_date_from or not self.wf_ooo_date_to:
            raise ValidationError(_("Please set both From and To for every active Out of Office rule."))
        if self.wf_ooo_date_to < self.wf_ooo_date_from:
            raise ValidationError(_("Out of Office rule To date must be after From date."))

    def _prepare_delegation_vals(self, target_user):
        self.ensure_one()
        note = self.wf_ooo_note or ""
        note = f"[OOO] {note}" if note else "[OOO] Delegation from user preference"
        return {
            "delegator_user_id": target_user.id,
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
