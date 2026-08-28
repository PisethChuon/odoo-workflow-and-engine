# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


POLICY_BOOL_FIELDS = [
    "zero_trust_enforced",
    "allow_requester_read",
    "allow_manager_access",
    "allow_assignee_without_category_access",
]
POLICY_SELECTION_FIELDS = ["default_fallback_policy"]
POLICY_M2O_FIELDS = ["admin_queue_user_id", "group_can_share_id"]
POLICY_M2M_FIELDS = ["allowed_user_ids", "allowed_group_ids", "allowed_department_ids"]

POLICY_FIELD_LABELS = {
    "zero_trust_enforced": "Zero Trust",
    "allow_requester_read": "Allow Requester Read",
    "allow_manager_access": "Allow Manager Access",
    "allow_assignee_without_category_access": "Allow Assignee Outside Category Allowlist",
    "default_fallback_policy": "Fallback Policy",
    "admin_queue_user_id": "Admin Queue Owner",
    "group_can_share_id": "Share Permission Group",
    "allowed_user_ids": "Allowed Users",
    "allowed_group_ids": "Allowed Groups",
    "allowed_department_ids": "Allowed Departments",
}


class WorkflowAccessPolicyTemplate(models.Model):
    _name = "workflow.access.policy.template"
    _description = "Workflow Access Policy Template"
    _order = "name"

    active = fields.Boolean(
        default=True,
        help="Disable this template without deleting it.",
    )
    name = fields.Char(
        required=True,
        help="Admin-facing template name.",
    )
    description = fields.Text(
        help="Internal note for admins. Describe the purpose, rollout notes, or exceptions.",
    )

    zero_trust_enforced = fields.Boolean(
        default=True,
        help=(
            "When enabled, category access starts from the allowed users, groups, and "
            "departments below instead of being open to all workflow users."
        ),
    )
    allowed_user_ids = fields.Many2many(
        "res.users",
        string="Allowed Users",
        help=(
            "Users granted category-level access when zero trust is enabled. "
            "This is not a per-request read filter."
        ),
    )
    allowed_group_ids = fields.Many2many(
        "res.groups",
        string="Allowed Groups",
        help=(
            "Groups granted category-level access when zero trust is enabled. "
            "This is not a per-request read filter."
        ),
    )
    allowed_department_ids = fields.Many2many(
        "hr.department",
        string="Allowed Departments",
        help=(
            "Departments granted category-level access when zero trust is enabled. "
            "This is not a per-request read filter."
        ),
    )
    allow_requester_read = fields.Boolean(
        default=True,
        help="Allow requester or creator to read their own requests.",
    )
    allow_manager_access = fields.Boolean(
        default=False,
        help="Allow the request owner's manager to read matching requests.",
    )
    allow_assignee_without_category_access = fields.Boolean(
        default=False,
        help="Allow assignees to work on requests even if they are outside the category access list.",
    )
    auto_grant_workflow_user_group = fields.Boolean(
        string="Auto Grant Workflow User Role",
        default=True,
        help=(
            "When enabled, applying this template will ensure selected allowed users, "
            "users from allowed groups, and users from allowed departments have the "
            "'Workflow Approval User' role so they can participate in approvals."
        ),
    )
    default_fallback_policy = fields.Selection(
        [
            ("escalate_manager", "Escalate to Manager"),
            ("route_admin_queue", "Route to Workflow Admin Queue"),
            ("block", "Block Task"),
        ],
        default="route_admin_queue",
        required=True,
        help="Fallback action when the runtime cannot resolve the next responsible user.",
    )
    admin_queue_user_id = fields.Many2one(
        "res.users",
        string="Admin Queue Owner",
        help="Fallback user used when the fallback policy routes work to the admin queue.",
    )
    group_can_share_id = fields.Many2one(
        "res.groups",
        string="Share Permission Group",
        help="Optional group treated as the share-authorized audience for this policy.",
    )

    category_ids = fields.One2many(
        "workflow.approval.category",
        "access_policy_template_id",
        string="Categories",
        readonly=True,
    )
    category_count = fields.Integer(
        compute="_compute_category_count",
        string="Linked Categories",
    )

    @api.depends("category_ids")
    def _compute_category_count(self):
        for record in self:
            record.category_count = len(record.category_ids)

    def _prepare_category_write_values(self):
        self.ensure_one()
        return {
            "zero_trust_enforced": self.zero_trust_enforced,
            "allow_requester_read": self.allow_requester_read,
            "allow_manager_access": self.allow_manager_access,
            "allow_assignee_without_category_access": self.allow_assignee_without_category_access,
            "default_fallback_policy": self.default_fallback_policy,
            "admin_queue_user_id": self.admin_queue_user_id.id or False,
            "group_can_share_id": self.group_can_share_id.id or False,
            "allowed_user_ids": [(6, 0, self.allowed_user_ids.ids)],
            "allowed_group_ids": [(6, 0, self.allowed_group_ids.ids)],
            "allowed_department_ids": [(6, 0, self.allowed_department_ids.ids)],
        }

    def _workflow_user_group_field_name(self):
        User = self.env["res.users"]
        if "group_ids" in User._fields:
            return "group_ids"
        if "groups_id" in User._fields:
            return "groups_id"
        return False

    def _collect_allowed_principal_users(self):
        self.ensure_one()
        users = self.env["res.users"].sudo()
        users |= self.allowed_user_ids.sudo()
        users |= self.allowed_group_ids.sudo().mapped("all_user_ids")
        if self.allowed_department_ids and "department_id" in self.env["res.users"]._fields:
            users |= self.env["res.users"].sudo().search(
                [
                    ("department_id", "in", self.allowed_department_ids.ids),
                    ("active", "=", True),
                    ("share", "=", False),
                ]
            )
        return users.filtered(lambda user: user.active and not user.share)

    def _ensure_workflow_user_group_membership(self):
        self.ensure_one()
        if not self.auto_grant_workflow_user_group:
            return 0
        workflow_user_group = self.env.ref(
            "workflow_engine.group_workflow_approval_user",
            raise_if_not_found=False,
        )
        if not workflow_user_group:
            return 0
        group_field = self._workflow_user_group_field_name()
        if not group_field:
            return 0
        users = self._collect_allowed_principal_users()
        users_to_update = users.filtered(lambda user: not user.has_group("workflow_engine.group_workflow_approval_user"))
        if users_to_update:
            users_to_update.sudo().write({group_field: [(4, workflow_user_group.id)]})
        return len(users_to_update)


class WorkflowApprovalCategoryAccessPolicy(models.Model):
    _inherit = "workflow.approval.category"

    admin_group_ids = fields.Many2many(
        "res.groups",
        "workflow_category_admin_group_rel",
        "category_id",
        "group_id",
        string="Workflow Admin Groups",
        help=(
            "Users in these groups can act on behalf of pending approvers for "
            "requests in this workflow category. Button Visibility domains are "
            "still evaluated."
        ),
    )
    access_policy_template_id = fields.Many2one(
        "workflow.access.policy.template",
        string="Access Policy Template",
        help="Reusable template for category access and visibility controls.",
    )
    access_policy_last_applied_at = fields.Datetime(
        string="Policy Last Applied At",
        readonly=True,
        copy=False,
    )
    access_policy_last_applied_by = fields.Many2one(
        "res.users",
        string="Policy Last Applied By",
        readonly=True,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_category_request_model_security()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._sync_category_request_model_security()
        return result

    def _sync_category_request_model_security(self):
        """Best-effort ACL/rule sync for child workflow request models.

        Handwritten child models need the request-reader ACL/rule bootstrap so
        read-only visibility features work without copied XML. Studio models may
        also expose extra approval-user/admin ACL/rules through optional
        workflow_studio helpers, so keep that sync path as a secondary step.
        """
        Rule = self.env["ir.rule"].sudo()
        for category in self:
            model = category.sudo().res_model
            if not model:
                continue
            model_name = (model.model or "").strip()
            if model_name == "workflow.base.approval.request":
                # Studio child-model rules reference `x_approval_base_id.*`.
                # They are valid for concrete approval child models, but they
                # break base-request searches because the compatibility field on
                # the base model is non-stored.
                Rule.search(
                    [
                        ("model_id", "=", model.id),
                        ("domain_force", "ilike", "x_approval_base_id."),
                    ]
                ).unlink()
                continue

            if not model._workflow_is_child_request_model():
                continue

            model.sudo()._workflow_sync_child_request_reader_security()
            setup_acl = getattr(model, "_workflow_studio_setup_approval_access_rights", None)
            setup_rules = getattr(model, "_workflow_studio_setup_approval_record_rules", None)
            if not callable(setup_acl) or not callable(setup_rules):
                continue

            try:
                model.sudo()._workflow_studio_setup_approval_access_rights()
                model.sudo()._workflow_studio_setup_approval_record_rules()
            except Exception:
                _logger.exception(
                    "Failed to sync workflow security for model %s while applying access policy template.",
                    model.model,
                )

    def _apply_access_policy_template(self, template):
        template.sudo()._ensure_workflow_user_group_membership()
        for category in self:
            values = template._prepare_category_write_values()
            values.update(
                {
                    "access_policy_template_id": template.id,
                    "access_policy_last_applied_at": fields.Datetime.now(),
                    "access_policy_last_applied_by": self.env.user.id,
                }
            )
            category.write(values)
            category._sync_category_request_model_security()

    def action_apply_access_policy_template(self):
        for category in self:
            template = category.access_policy_template_id
            if not template:
                raise UserError(_("Please select an Access Policy Template first."))
            category._apply_access_policy_template(template)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Access Policy Updated"),
                "message": _("Template has been applied successfully."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_open_access_policy_wizard(self):
        action = self.env.ref(
            "workflow_engine.action_workflow_category_access_policy_wizard"
        ).read()[0]
        selected_ids = (
            self.env.context.get("active_ids")
            if self.env.context.get("active_model") == "workflow.approval.category"
            else self.ids
        )
        selected_ids = selected_ids or self.ids
        default_template = self[:1].access_policy_template_id.id if self[:1] else False
        action["context"] = {
            **self.env.context,
            "default_category_ids": [(6, 0, selected_ids)],
            "default_template_id": default_template,
        }
        return action


class WorkflowCategoryAccessPolicyWizard(models.TransientModel):
    _name = "workflow.category.access.policy.wizard"
    _description = "Workflow Category Access Policy Wizard"

    template_id = fields.Many2one(
        "workflow.access.policy.template",
        string="Policy Template",
        required=True,
    )
    category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_policy_wizard_category_rel",
        "wizard_id",
        "category_id",
        string="Categories",
        required=True,
    )
    preview_html = fields.Html(
        string="Impact Preview",
        compute="_compute_preview_html",
        readonly=True,
        sanitize=False,
    )
    changed_category_count = fields.Integer(
        string="Changed Categories",
        compute="_compute_preview_html",
        readonly=True,
    )
    changed_field_count = fields.Integer(
        string="Changed Fields",
        compute="_compute_preview_html",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        active_model = self.env.context.get("active_model")
        active_ids = self.env.context.get("active_ids") or []
        if (
            active_model == "workflow.approval.category"
            and "category_ids" in fields_list
            and not result.get("category_ids")
            and active_ids
        ):
            result["category_ids"] = [(6, 0, active_ids)]
        return result

    def _collect_category_changes(self, category, template):
        changed_labels = []

        for field_name in POLICY_BOOL_FIELDS + POLICY_SELECTION_FIELDS:
            if category[field_name] != template[field_name]:
                changed_labels.append(POLICY_FIELD_LABELS[field_name])

        for field_name in POLICY_M2O_FIELDS:
            if (category[field_name].id or False) != (template[field_name].id or False):
                changed_labels.append(POLICY_FIELD_LABELS[field_name])

        for field_name in POLICY_M2M_FIELDS:
            if set(category[field_name].ids) != set(template[field_name].ids):
                changed_labels.append(POLICY_FIELD_LABELS[field_name])

        return changed_labels

    @api.depends("template_id", "category_ids")
    def _compute_preview_html(self):
        for wizard in self:
            wizard.changed_category_count = 0
            wizard.changed_field_count = 0
            if not wizard.template_id or not wizard.category_ids:
                wizard.preview_html = _(
                    "<p class='text-muted'>Select a policy template and categories to preview changes.</p>"
                )
                continue

            items = []
            for category in wizard.category_ids:
                changes = wizard._collect_category_changes(category, wizard.template_id)
                if not changes:
                    continue
                wizard.changed_category_count += 1
                wizard.changed_field_count += len(changes)
                label_list = ", ".join(html_escape(label) for label in changes)
                items.append(
                    "<li><strong>%s</strong>: %s</li>"
                    % (html_escape(category.display_name), label_list)
                )

            if not items:
                wizard.preview_html = _(
                    "<p class='text-success'>No changes detected. Selected categories already match this template.</p>"
                )
                continue

            wizard.preview_html = (
                "<p><strong>%s</strong></p><ul>%s</ul>"
                % (
                    _(
                        "This will update %(cat_count)s categories and %(field_count)s policy values."
                    )
                    % {
                        "cat_count": wizard.changed_category_count,
                        "field_count": wizard.changed_field_count,
                    },
                    "".join(items),
                )
            )

    def action_apply(self):
        self.ensure_one()
        if not self.category_ids:
            raise UserError(_("Please select at least one category."))

        self.category_ids._apply_access_policy_template(self.template_id)
        self.category_ids.write({"access_policy_template_id": self.template_id.id})

        message = _(
            "Applied template '%(template)s' to %(count)s categories."
        ) % {
            "template": self.template_id.display_name,
            "count": len(self.category_ids),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Access Policy Applied"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
