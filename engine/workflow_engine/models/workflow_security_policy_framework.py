# -*- coding: utf-8 -*-
import logging
from datetime import date, datetime, time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html_escape
from odoo.tools.safe_eval import safe_eval

from .workflow_security_and_meta_extensions import CREATE_ACCESS_MODE_SELECTION

_logger = logging.getLogger(__name__)


LIVE_POLICY_FIELD_MAP = {
    "zero_trust_enforced": "security_policy_draft_zero_trust_enforced",
    "allow_requester_read": "security_policy_draft_allow_requester_read",
    "allow_manager_access": "security_policy_draft_allow_manager_access",
    "allow_assignee_without_category_access": "security_policy_draft_allow_assignee_without_category_access",
    "default_fallback_policy": "security_policy_draft_default_fallback_policy",
    "admin_queue_user_id": "security_policy_draft_admin_queue_user_id",
    "group_can_share_id": "security_policy_draft_group_can_share_id",
    "allowed_user_ids": "security_policy_draft_allowed_user_ids",
    "allowed_group_ids": "security_policy_draft_allowed_group_ids",
    "allowed_department_ids": "security_policy_draft_allowed_department_ids",
    "create_access_mode": "security_policy_draft_create_access_mode",
    "create_allowed_user_ids": "security_policy_draft_create_allowed_user_ids",
    "create_allowed_group_ids": "security_policy_draft_create_allowed_group_ids",
    "create_allowed_department_ids": "security_policy_draft_create_allowed_department_ids",
}

WORKFLOW_CATEGORY_CREATE_AUDIENCE_DOMAIN = """
                ['|',
                    ('create_access_mode', '!=', 'restricted'),
                    '&',
                        ('create_access_mode', '=', 'restricted'),
                        '|','|',
                            ('create_allowed_user_ids', 'in', [user.id]),
                            ('create_allowed_group_ids', 'in', user.all_group_ids.ids),
                            '&',
                                ('create_allowed_department_ids', '!=', False),
                                ('create_allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""

WORKFLOW_BASE_CREATE_AUDIENCE_DOMAIN = """
                ['|',
                    ('category_id.create_access_mode', '!=', 'restricted'),
                    '&',
                        ('category_id.create_access_mode', '=', 'restricted'),
                        '|','|',
                            ('category_id.create_allowed_user_ids', 'in', [user.id]),
                            ('category_id.create_allowed_group_ids', 'in', user.all_group_ids.ids),
                            '&',
                                ('category_id.create_allowed_department_ids', '!=', False),
                                ('category_id.create_allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""

WORKFLOW_BASE_APPROVER_DOMAIN = """
                ['&',
                    '|',
                        ('approver_ids.user_id', 'in', [user.id]),
                        ('task_instance_ids.assignee_ids.assignee_user_id', 'in', [user.id]),
                    '|',
                        ('category_id.zero_trust_enforced', '=', False),
                        '|',
                            ('category_id.allow_assignee_without_category_access', '=', True),
                            '|','|',
                                ('category_id.allowed_user_ids', 'in', [user.id]),
                                ('category_id.allowed_group_ids', 'in', user.all_group_ids.ids),
                                '&',
                                    ('category_id.allowed_department_ids', '!=', False),
                                    ('category_id.allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""

WORKFLOW_BASE_REQUEST_OWNER_DOMAIN = """
                ['&',
                    '|', ('create_uid', '=', user.id), ('request_owner_id', '=', user.id),
                    '|',
                        ('category_id.zero_trust_enforced', '=', False),
                        '|','|',
                            ('category_id.allowed_user_ids', 'in', [user.id]),
                            ('category_id.allowed_group_ids', 'in', user.all_group_ids.ids),
                            '&',
                                ('category_id.allowed_department_ids', '!=', False),
                                ('category_id.allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""

WORKFLOW_BASE_VISIBILITY_SCOPE_READ_DOMAIN = """
                ['|',
                    ('visibility_scope_user_ids', 'in', [user.id]),
                    ('visibility_scope_group_ids', 'in', user.all_group_ids.ids)
                ]
"""

WORKFLOW_BASE_CATEGORY_READ_AUDIENCE_DOMAIN = """
                ['|','|','|',
                    ('category_id.zero_trust_enforced', '=', False),
                    ('category_id.allowed_user_ids', 'in', [user.id]),
                    ('category_id.allowed_group_ids', 'in', user.all_group_ids.ids),
                    '&',
                        ('category_id.allowed_department_ids', '!=', False),
                        ('category_id.allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""

WORKFLOW_BASE_REQUEST_READER_EXCEPTION_DOMAIN = """
                ['|',
                    '&',
                        ('category_id.allow_requester_read', '=', True),
                        '|',
                            ('create_uid', '=', user.id),
                            ('request_owner_id', '=', user.id),
                    '&',
                        ('category_id.allow_manager_access', '=', True),
                        ('manager_user_id', '=', user.id)
                ]
"""

WORKFLOW_CATEGORY_BY_DEFAULT_DOMAIN = """
                ['|','|','|','|',
                    '&',
                        ('zero_trust_enforced', '=', True),
                        '|','|','|',
                            ('allowed_user_ids', 'in', [user.id]),
                            ('allowed_group_ids', 'in', user.all_group_ids.ids),
                            '&',
                                ('allowed_department_ids', '!=', False),
                                ('allowed_department_ids', 'in', [user.department_id.id or 0]),
                            '&',
                                ('allow_assignee_without_category_access', '=', True),
                                ('request_ids.task_instance_ids.assignee_ids.assignee_user_id', '=', user.id),
                    '&',
                        ('zero_trust_enforced', '=', False),
                        '|', '|', '|', '|',
                            ('approver_ids.user_id', '=', user.id),
                            ('request_ids.task_instance_ids.assignee_ids.assignee_user_id', '=', user.id),
                            ('request_ids.approver_ids.user_id', '=', user.id),
                            ('request_ids.request_owner_id', '=', user.id),
                            ('request_ids.create_uid', '=', user.id),
                    ('request_ids.visibility_scope_user_ids', 'in', [user.id]),
                    ('request_ids.visibility_scope_group_ids', 'in', user.all_group_ids.ids),
                    ('request_ids.message_partner_ids.user_ids', '=', user.id)
                ]
"""

WORKFLOW_TASK_INSTANCE_USER_SCOPE_DOMAIN = """
                ['|','|','|','|','|',
                    ('request_id.request_owner_id', '=', user.id),
                    ('request_id.create_uid', '=', user.id),
                    ('request_id.approver_ids.user_id', '=', user.id),
                    ('assignee_ids.assignee_user_id', '=', user.id),
                    ('request_id.visibility_scope_user_ids', 'in', [user.id]),
                    ('request_id.visibility_scope_group_ids', 'in', user.all_group_ids.ids)
                ]
"""

WORKFLOW_REQUEST_AUTOMATION_INSTANCE_USER_SCOPE_DOMAIN = """
                ['|','|','|','|','|',
                    ('request_id.request_owner_id', '=', user.id),
                    ('request_id.create_uid', '=', user.id),
                    ('request_id.approver_ids.user_id', '=', user.id),
                    ('task_instance_id.assignee_ids.assignee_user_id', '=', user.id),
                    ('request_id.visibility_scope_user_ids', 'in', [user.id]),
                    ('request_id.visibility_scope_group_ids', 'in', user.all_group_ids.ids)
                ]
"""

POLICY_PRESET_SELECTION = [
    ("all_requests", "All Requests"),
    ("request_owner_department", "Request Owner Department"),
    ("request_owner_user", "Specific Request Owners"),
    ("request_owner_manager", "Request Owner Manager"),
    ("request_owner_line", "Request Owner Line"),
    ("request_owner_team", "Request Owner Team"),
]

POLICY_MODE_SELECTION = [
    ("preset", "Preset"),
    ("domain_builder", "Safe Domain Builder"),
    ("raw_domain", "Technical Raw Domain"),
]

POLICY_ACCESS_LEVEL_SELECTION = [
    ("read", "Read Only"),
    ("read_share", "Read + Share"),
]

SAFE_DOMAIN_FIELD_WHITELIST = {
    "id",
    "category_id",
    "company_id",
    "request_owner_id",
    "request_owner_department",
    "request_owner_manager_user_id",
    "request_owner_line_id",
    "request_owner_team_id",
    "request_owner_line_code",
    "request_owner_team_code",
    "request_status",
    "state",
    "create_date",
    "date",
    "date_start",
    "date_end",
    "active",
}

SAFE_CHILD_DOMAIN_FIELD_MAP = {
    field_name: ("x_approval_base_id.%s" % field_name if field_name != "id" else "x_approval_base_id.id")
    for field_name in SAFE_DOMAIN_FIELD_WHITELIST
}


def _rule_eval_symbols(user):
    return {
        "False": False,
        "True": True,
        "None": None,
        "uid": user.id if user else 0,
        "user": user.sudo() if user else False,
        "datetime": datetime,
        "date": date,
        "time": time,
        "context_today": fields.Date.today,
    }


def _normalize_policy_domain(value):
    return " ".join((value or "").split())


def _iter_domain_leaves(domain):
    if isinstance(domain, tuple):
        domain = list(domain)
    if not isinstance(domain, list):
        return
    if len(domain) >= 3 and isinstance(domain[0], str) and domain[0] not in ("&", "|", "!"):
        yield domain
        return
    for item in domain:
        if isinstance(item, tuple):
            item = list(item)
        if isinstance(item, list):
            yield from _iter_domain_leaves(item)


def _translate_domain_fields(domain, field_map):
    if isinstance(domain, tuple):
        domain = list(domain)
    if isinstance(domain, list):
        if len(domain) >= 3 and isinstance(domain[0], str) and domain[0] not in ("&", "|", "!"):
            translated = list(domain)
            translated[0] = field_map.get(translated[0], translated[0])
            return translated
        return [_translate_domain_fields(item, field_map) for item in domain]
    return domain


class WorkflowSecurityPolicyRuleMixin(models.AbstractModel):
    _name = "workflow.security.policy.rule.mixin"
    _description = "Workflow Security Policy Rule Mixin"
    _abstract = True

    active = fields.Boolean(
        default=True,
        help="Disable this rule without deleting it.",
    )
    sequence = fields.Integer(
        default=10,
        help="Lower numbers appear first and are compiled first.",
    )
    name = fields.Char(
        required=True,
        help="Short admin-facing name for this rule.",
    )
    description = fields.Char(
        help="Internal note for admins. Use it to explain the business case or exception.",
    )
    audience_group_id = fields.Many2one(
        "res.groups",
        string="Audience Group",
        required=True,
        ondelete="restrict",
        help="Users in this Odoo group receive the rule when its visibility condition matches.",
    )
    access_level = fields.Selection(
        POLICY_ACCESS_LEVEL_SELECTION,
        string="Access Level",
        default="read",
        required=True,
        help="Read Only grants visibility. Read + Share also marks the group as the share-authorized audience.",
    )
    mode = fields.Selection(
        POLICY_MODE_SELECTION,
        string="Rule Mode",
        default="preset",
        required=True,
        help=(
            "Preset is safest for standard business cases. Safe Domain Builder uses only approved "
            "request fields. Technical Raw Domain is for advanced technical filters."
        ),
    )
    preset_scope = fields.Selection(
        POLICY_PRESET_SELECTION,
        string="Preset Scope",
        default="all_requests",
        required=True,
        help=(
            "For Preset mode, choose how matching requests are selected. Some presets use fixed "
            "selectors when provided, or the current user's own department/manager/line/team when left empty."
        ),
    )
    domain_builder = fields.Char(
        string="Safe Domain",
        help=(
            "Literal Odoo domain limited to approved request snapshot fields. "
            "Example: [('request_status', '=', 'pending')]. Use [] to match all requests in the category."
        ),
    )
    base_request_domain = fields.Char(
        string="Raw Base Request Domain",
        groups="workflow_engine.group_workflow_technical_admin,base.group_system",
        help=(
            "Advanced Odoo domain for workflow.base.approval.request. The category filter is added "
            "automatically, so [] means all requests in this category."
        ),
    )
    child_request_domain = fields.Char(
        string="Raw Child Request Domain",
        groups="workflow_engine.group_workflow_technical_admin,base.group_system",
        help=(
            "Advanced Odoo domain for the child request model opened by the category, usually "
            "using x_approval_base_id.* fields. Use [] to match all child records in this category."
        ),
    )
    scope_summary = fields.Char(
        string="Scope Summary",
        compute="_compute_scope_summary",
        store=False,
        help="Computed summary of the current rule scope.",
    )

    @api.depends(
        "preset_scope",
        "mode",
        "department_ids",
        "request_owner_user_ids",
        "manager_user_ids",
        "line_ids",
        "team_ids",
        "domain_builder",
        "base_request_domain",
    )
    def _compute_scope_summary(self):
        for rule in self:
            if rule.mode == "domain_builder":
                rule.scope_summary = rule.domain_builder or _("Any request in category")
                continue
            if rule.mode == "raw_domain":
                rule.scope_summary = rule.base_request_domain or _("Technical raw domain")
                continue
            label_map = dict(POLICY_PRESET_SELECTION)
            selector_names = []
            if rule.preset_scope == "request_owner_department":
                selector_names = rule.department_ids.mapped("display_name")
            elif rule.preset_scope == "request_owner_user":
                selector_names = rule.request_owner_user_ids.mapped("display_name")
            elif rule.preset_scope == "request_owner_manager":
                selector_names = rule.manager_user_ids.mapped("display_name")
            elif rule.preset_scope == "request_owner_line":
                selector_names = rule.line_ids.mapped("display_name")
            elif rule.preset_scope == "request_owner_team":
                selector_names = rule.team_ids.mapped("display_name")
            if selector_names:
                rule.scope_summary = "%s: %s" % (
                    label_map.get(rule.preset_scope, rule.preset_scope),
                    ", ".join(selector_names),
                )
            else:
                rule.scope_summary = label_map.get(rule.preset_scope, rule.preset_scope)

    def _safe_domain_literal(self, expression, field_label):
        if not expression:
            return []
        try:
            domain = safe_eval(expression, {"False": False, "True": True, "None": None}, mode="eval")
        except Exception as exc:
            raise ValidationError(_("Invalid %s: %s") % (field_label, exc)) from exc
        if isinstance(domain, tuple):
            domain = list(domain)
        if not isinstance(domain, list):
            raise ValidationError(_("%s must evaluate to a domain list.") % field_label)
        for leaf in _iter_domain_leaves(domain):
            field_name = (leaf[0] or "").strip()
            if "." in field_name or field_name not in SAFE_DOMAIN_FIELD_WHITELIST:
                raise ValidationError(
                    _(
                        "Field '%(field)s' is not allowed in %(label)s. Allowed fields: %(allowed)s"
                    )
                    % {
                        "field": field_name,
                        "label": field_label,
                        "allowed": ", ".join(sorted(SAFE_DOMAIN_FIELD_WHITELIST)),
                    }
                )
        return domain

    def _validate_raw_domain_expression(self, expression, field_label, user=False):
        if not expression:
            return "[]"
        try:
            safe_eval(expression, _rule_eval_symbols(user or self.env.user), mode="eval")
        except Exception as exc:
            raise ValidationError(_("Invalid %s: %s") % (field_label, exc)) from exc
        return expression.strip()

    def _selector_codes(self, records, attr_name):
        missing = records.filtered(lambda record: not getattr(record, attr_name, False))
        if missing:
            raise ValidationError(
                _(
                    "Missing HR mapping code on %(records)s. Please complete the line/team mapping before publish."
                )
                % {"records": ", ".join(missing.mapped("display_name"))}
            )
        return sorted(set(filter(None, records.mapped(attr_name))))

    def _preset_domain_expressions(self):
        self.ensure_one()
        base_field_map = {
            "request_owner_department": "request_owner_department",
            "request_owner_user": "request_owner_id",
            "request_owner_manager": "request_owner_manager_user_id",
            "request_owner_line": "request_owner_line_code",
            "request_owner_team": "request_owner_team_code",
        }
        child_field_map = {
            key: ("x_approval_base_id.%s" % value)
            for key, value in base_field_map.items()
        }

        if self.preset_scope == "all_requests":
            return "[]", "[]"

        if self.preset_scope == "request_owner_department":
            if self.department_ids:
                return (
                    repr([("request_owner_department", "in", self.department_ids.ids)]),
                    repr([("x_approval_base_id.request_owner_department", "in", self.department_ids.ids)]),
                )
            return (
                "[('request_owner_department', '=', user.department_id.id)]",
                "[('x_approval_base_id.request_owner_department', '=', user.department_id.id)]",
            )

        if self.preset_scope == "request_owner_user":
            if self.request_owner_user_ids:
                ids = self.request_owner_user_ids.ids
                return (
                    repr([("request_owner_id", "in", ids)]),
                    repr([("x_approval_base_id.request_owner_id", "in", ids)]),
                )
            return (
                "[('request_owner_id', '=', user.id)]",
                "[('x_approval_base_id.request_owner_id', '=', user.id)]",
            )

        if self.preset_scope == "request_owner_manager":
            if self.manager_user_ids:
                ids = self.manager_user_ids.ids
                return (
                    repr([("request_owner_manager_user_id", "in", ids)]),
                    repr([("x_approval_base_id.request_owner_manager_user_id", "in", ids)]),
                )
            return (
                "[('request_owner_manager_user_id', '=', user.id)]",
                "[('x_approval_base_id.request_owner_manager_user_id', '=', user.id)]",
            )

        if self.preset_scope == "request_owner_line":
            if self.line_ids:
                codes = self._selector_codes(self.line_ids, "hr_line_code")
                return (
                    repr([("request_owner_line_code", "in", codes)]),
                    repr([("x_approval_base_id.request_owner_line_code", "in", codes)]),
                )
            return (
                "[('request_owner_line_code', '=', user.employee_id.x_line_code)]",
                "[('x_approval_base_id.request_owner_line_code', '=', user.employee_id.x_line_code)]",
            )

        if self.preset_scope == "request_owner_team":
            if self.team_ids:
                codes = self._selector_codes(self.team_ids, "hr_team_code")
                return (
                    repr([("request_owner_team_code", "in", codes)]),
                    repr([("x_approval_base_id.request_owner_team_code", "in", codes)]),
                )
            return (
                "[('request_owner_team_code', '=', user.employee_id.x_team_code)]",
                "[('x_approval_base_id.request_owner_team_code', '=', user.employee_id.x_team_code)]",
            )

        raise ValidationError(_("Unsupported preset scope: %s") % self.preset_scope)

    def _safe_builder_domain_expressions(self):
        self.ensure_one()
        domain = self._safe_domain_literal(
            self.domain_builder,
            _("Safe Domain"),
        )
        child_domain = _translate_domain_fields(domain, SAFE_CHILD_DOMAIN_FIELD_MAP)
        return repr(domain), repr(child_domain)

    def _raw_domain_expressions(self, category):
        self.ensure_one()
        base_expr = self._validate_raw_domain_expression(
            self.base_request_domain,
            _("Raw Base Request Domain"),
        )
        child_model_name = category._security_policy_child_model_name()
        if child_model_name and child_model_name != "workflow.base.approval.request" and not self.child_request_domain:
            raise ValidationError(
                _(
                    "Rule '%(rule)s' requires a Raw Child Request Domain because category '%(category)s' opens the child model."
                )
                % {
                    "rule": self.display_name,
                    "category": category.display_name,
                }
            )
        child_expr = self._validate_raw_domain_expression(
            self.child_request_domain,
            _("Raw Child Request Domain"),
        )
        return base_expr, child_expr

    def _domain_expressions_for_category(self, category):
        self.ensure_one()
        if self.mode == "preset":
            return self._preset_domain_expressions()
        if self.mode == "domain_builder":
            return self._safe_builder_domain_expressions()
        if self.mode == "raw_domain":
            return self._raw_domain_expressions(category)
        raise ValidationError(_("Unsupported rule mode: %s") % self.mode)

    def _compose_domain_expression(self, prefix_domain, extra_expression):
        extra_expression = extra_expression or "[]"
        return "%s + (%s)" % (repr(prefix_domain), extra_expression)

    def _compiled_payload_for_category(self, category):
        self.ensure_one()
        category_for_domain = category._origin if category._origin and category._origin.id else category
        category_id = category_for_domain.id
        if not isinstance(category_id, int):
            raise ValidationError(_("Security policies can only be published for saved workflow categories."))
        base_extra_expr, child_extra_expr = self._domain_expressions_for_category(category)
        child_model_name = category_for_domain._security_policy_child_model_name()
        payload = {
            "rule_name": self.display_name,
            "rule_id": self.id,
            "group_id": self.audience_group_id.id,
            "group_name": self.audience_group_id.display_name,
            "access_level": self.access_level,
            "mode": self.mode,
            "preset_scope": self.preset_scope,
            "base_domain_expression": self._compose_domain_expression(
                [("category_id", "=", category_id)],
                base_extra_expr,
            ),
            "child_model_name": child_model_name if child_model_name != "workflow.base.approval.request" else False,
            "child_domain_expression": False,
            "description": self.description or False,
        }
        if child_model_name and child_model_name != "workflow.base.approval.request":
            payload["child_domain_expression"] = self._compose_domain_expression(
                [("x_approval_base_id.category_id", "=", category_id)],
                child_extra_expr,
            )
        return payload

    def _payload_dict(self):
        self.ensure_one()
        return {
            "sequence": self.sequence,
            "name": self.name,
            "description": self.description,
            "active": self.active,
            "audience_group_id": self.audience_group_id.id or False,
            "access_level": self.access_level,
            "mode": self.mode,
            "preset_scope": self.preset_scope,
            "department_ids": self.department_ids.ids,
            "request_owner_user_ids": self.request_owner_user_ids.ids,
            "manager_user_ids": self.manager_user_ids.ids,
            "line_ids": self.line_ids.ids,
            "team_ids": self.team_ids.ids,
            "domain_builder": self.domain_builder or False,
            "base_request_domain": self.base_request_domain or False,
            "child_request_domain": self.child_request_domain or False,
        }


class WorkflowAccessPolicyTemplateExtension(models.Model):
    _inherit = "workflow.access.policy.template"

    create_access_mode = fields.Selection(
        CREATE_ACCESS_MODE_SELECTION,
        string="Request Creation Access",
        default="inherit_current_behavior",
        required=True,
        help=(
            "Template default for who may submit new requests. Apply copies this "
            "to category draft data; publish makes it active."
        ),
    )
    create_allowed_user_ids = fields.Many2many(
        "res.users",
        "wf_policy_template_create_user_rel",
        "template_id",
        "user_id",
        string="Create Allowed Users",
        help="Users allowed to submit requests when request creation is restricted.",
    )
    create_allowed_group_ids = fields.Many2many(
        "res.groups",
        "wf_policy_template_create_group_rel",
        "template_id",
        "group_id",
        string="Create Allowed Groups",
        help="Groups allowed to submit requests when request creation is restricted.",
    )
    create_allowed_department_ids = fields.Many2many(
        "hr.department",
        "wf_policy_template_create_department_rel",
        "template_id",
        "department_id",
        string="Create Allowed Departments",
        help="Departments allowed to submit requests when request creation is restricted.",
    )
    rule_ids = fields.One2many(
        "workflow.access.policy.template.rule",
        "template_id",
        string="Template Rules",
        copy=True,
    )
    rule_count = fields.Integer(
        string="Rule Count",
        compute="_compute_rule_count",
    )

    @api.depends("rule_ids")
    def _compute_rule_count(self):
        for template in self:
            template.rule_count = len(template.rule_ids.filtered("active"))

    def action_open_security_policy_apply_wizard(self):
        self.ensure_one()
        action = self.env.ref("workflow_engine.action_workflow_access_policy_apply_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_template_id": self.id,
        }
        return action

    def action_view_linked_categories(self):
        self.ensure_one()
        action = self.env.ref("workflow_engine.workflow_approval_category_action").read()[0]
        action["domain"] = [("access_policy_template_id", "=", self.id)]
        action["context"] = {
            **self.env.context,
            "default_access_policy_template_id": self.id,
        }
        return action

    def _prepare_category_draft_values(self):
        self.ensure_one()
        return {
            LIVE_POLICY_FIELD_MAP["zero_trust_enforced"]: self.zero_trust_enforced,
            LIVE_POLICY_FIELD_MAP["allow_requester_read"]: self.allow_requester_read,
            LIVE_POLICY_FIELD_MAP["allow_manager_access"]: self.allow_manager_access,
            LIVE_POLICY_FIELD_MAP["allow_assignee_without_category_access"]: self.allow_assignee_without_category_access,
            LIVE_POLICY_FIELD_MAP["default_fallback_policy"]: self.default_fallback_policy,
            LIVE_POLICY_FIELD_MAP["admin_queue_user_id"]: self.admin_queue_user_id.id or False,
            LIVE_POLICY_FIELD_MAP["group_can_share_id"]: self.group_can_share_id.id or False,
            LIVE_POLICY_FIELD_MAP["allowed_user_ids"]: [(6, 0, self.allowed_user_ids.ids)],
            LIVE_POLICY_FIELD_MAP["allowed_group_ids"]: [(6, 0, self.allowed_group_ids.ids)],
            LIVE_POLICY_FIELD_MAP["allowed_department_ids"]: [(6, 0, self.allowed_department_ids.ids)],
            LIVE_POLICY_FIELD_MAP["create_access_mode"]: self.create_access_mode,
            LIVE_POLICY_FIELD_MAP["create_allowed_user_ids"]: [(6, 0, self.create_allowed_user_ids.ids)],
            LIVE_POLICY_FIELD_MAP["create_allowed_group_ids"]: [(6, 0, self.create_allowed_group_ids.ids)],
            LIVE_POLICY_FIELD_MAP["create_allowed_department_ids"]: [(6, 0, self.create_allowed_department_ids.ids)],
            "security_policy_draft_initialized": True,
        }

    def _prepare_category_rule_payload(self):
        self.ensure_one()
        return [rule._payload_dict() for rule in self.rule_ids.sorted(key=lambda rec: (rec.sequence, rec.id))]


class WorkflowAccessPolicyTemplateRule(models.Model):
    _name = "workflow.access.policy.template.rule"
    _description = "Workflow Access Policy Template Rule"
    _inherit = "workflow.security.policy.rule.mixin"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "workflow.access.policy.template",
        required=True,
        ondelete="cascade",
    )
    department_ids = fields.Many2many(
        "hr.department",
        "wf_policy_template_rule_department_rel",
        "rule_id",
        "department_id",
        string="Departments",
        help=(
            "Used with the Request Owner Department preset. Leave empty to match the current "
            "user's own department, or select departments to use fixed departments instead."
        ),
    )
    request_owner_user_ids = fields.Many2many(
        "res.users",
        "wf_policy_template_rule_owner_rel",
        "rule_id",
        "user_id",
        string="Request Owners",
        help=(
            "Used with the Specific Request Owners preset. Leave empty to match the current "
            "user as request owner, or select users to use fixed owners instead."
        ),
    )
    manager_user_ids = fields.Many2many(
        "res.users",
        "wf_policy_template_rule_manager_rel",
        "rule_id",
        "user_id",
        string="Manager Users",
        help=(
            "Used with the Request Owner Manager preset. Leave empty to match the current "
            "user as manager, or select users to use fixed managers instead."
        ),
    )
    line_ids = fields.Many2many(
        "workflow.approval.group.line",
        "wf_policy_template_rule_line_rel",
        "rule_id",
        "line_id",
        string="Lines",
        help=(
            "Used with the Request Owner Line preset. Leave empty to match the current user's "
            "HR line code, or select lines to use fixed lines instead."
        ),
    )
    team_ids = fields.Many2many(
        "workflow.approval.group.team",
        "wf_policy_template_rule_team_rel",
        "rule_id",
        "team_id",
        string="Teams",
        help=(
            "Used with the Request Owner Team preset. Leave empty to match the current user's "
            "HR team code, or select teams to use fixed teams instead."
        ),
    )


class WorkflowCategoryAccessPolicyRule(models.Model):
    _name = "workflow.category.access.policy.rule"
    _description = "Workflow Category Access Policy Rule"
    _inherit = "workflow.security.policy.rule.mixin"
    _order = "sequence, id"

    category_id = fields.Many2one(
        "workflow.approval.category",
        required=True,
        ondelete="cascade",
    )
    department_ids = fields.Many2many(
        "hr.department",
        "wf_policy_category_rule_department_rel",
        "rule_id",
        "department_id",
        string="Departments",
        help=(
            "Used with the Request Owner Department preset. Leave empty to match the current "
            "user's own department, or select departments to use fixed departments instead."
        ),
    )
    request_owner_user_ids = fields.Many2many(
        "res.users",
        "wf_policy_category_rule_owner_rel",
        "rule_id",
        "user_id",
        string="Request Owners",
        help=(
            "Used with the Specific Request Owners preset. Leave empty to match the current "
            "user as request owner, or select users to use fixed owners instead."
        ),
    )
    manager_user_ids = fields.Many2many(
        "res.users",
        "wf_policy_category_rule_manager_rel",
        "rule_id",
        "user_id",
        string="Manager Users",
        help=(
            "Used with the Request Owner Manager preset. Leave empty to match the current "
            "user as manager, or select users to use fixed managers instead."
        ),
    )
    line_ids = fields.Many2many(
        "workflow.approval.group.line",
        "wf_policy_category_rule_line_rel",
        "rule_id",
        "line_id",
        string="Lines",
        help=(
            "Used with the Request Owner Line preset. Leave empty to match the current user's "
            "HR line code, or select lines to use fixed lines instead."
        ),
    )
    team_ids = fields.Many2many(
        "workflow.approval.group.team",
        "wf_policy_category_rule_team_rel",
        "rule_id",
        "team_id",
        string="Teams",
        help=(
            "Used with the Request Owner Team preset. Leave empty to match the current user's "
            "HR team code, or select teams to use fixed teams instead."
        ),
    )


class WorkflowCategoryAccessPolicySnapshot(models.Model):
    _name = "workflow.category.access.policy.snapshot"
    _description = "Workflow Category Access Policy Snapshot"
    _order = "published_at desc, id desc"

    name = fields.Char(required=True)
    category_id = fields.Many2one(
        "workflow.approval.category",
        required=True,
        index=True,
        ondelete="cascade",
    )
    template_id = fields.Many2one("workflow.access.policy.template", ondelete="set null")
    published_at = fields.Datetime(required=True, index=True, default=fields.Datetime.now)
    published_by = fields.Many2one("res.users", required=True, ondelete="restrict", default=lambda self: self.env.user)
    note = fields.Char()
    runtime_payload = fields.Json(default=dict)
    rule_payload = fields.Json(default=list)
    generated_rule_count = fields.Integer(default=0)
    is_current_snapshot = fields.Boolean(
        string="Current",
        compute="_compute_is_current_snapshot",
    )

    @api.depends("category_id.security_policy_last_published_snapshot_id")
    def _compute_is_current_snapshot(self):
        for snapshot in self:
            snapshot.is_current_snapshot = (
                snapshot.category_id.security_policy_last_published_snapshot_id == snapshot
            )

    def action_open_security_policy_rollback_wizard(self):
        self.ensure_one()
        action = self.env.ref("workflow_engine.action_workflow_access_policy_rollback_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_category_id": self.category_id.id,
            "default_snapshot_id": self.id,
        }
        return action


class WorkflowIrRuleSecurityPolicyExtension(models.Model):
    _inherit = "ir.rule"

    workflow_security_policy_generated = fields.Boolean(default=False, index=True, copy=False)
    workflow_security_category_id = fields.Many2one(
        "workflow.approval.category",
        string="Workflow Security Category",
        index=True,
        copy=False,
        ondelete="cascade",
    )
    workflow_security_snapshot_id = fields.Many2one(
        "workflow.category.access.policy.snapshot",
        string="Workflow Security Snapshot",
        index=True,
        copy=False,
        ondelete="cascade",
    )
    workflow_security_rule_key = fields.Char(index=True, copy=False)

    def init(self):
        super().init()
        approval_user_group = "workflow_engine.group_workflow_approval_user"
        request_reader_group = "workflow_engine.group_workflow_request_reader"
        desired_rules = {
            "workflow_engine.rule_workflow_base_for_approver": {
                "domain_force": WORKFLOW_BASE_APPROVER_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": True, "perm_write": True, "perm_create": True, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_request_owner_and_creator": {
                "domain_force": WORKFLOW_BASE_REQUEST_OWNER_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": True, "perm_write": True, "perm_create": True, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_create_audience": {
                "domain_force": WORKFLOW_BASE_CREATE_AUDIENCE_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": False, "perm_write": False, "perm_create": True, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_visibility_scope_read": {
                "domain_force": WORKFLOW_BASE_VISIBILITY_SCOPE_READ_DOMAIN,
                "groups": [request_reader_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_follower_read": {
                "domain_force": "[('message_partner_ids.user_ids', 'in', [user.id])]",
                "groups": [request_reader_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_category_read_audience": {
                "domain_force": WORKFLOW_BASE_CATEGORY_READ_AUDIENCE_DOMAIN,
                "groups": [request_reader_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_base_for_request_reader_exception_read": {
                "domain_force": WORKFLOW_BASE_REQUEST_READER_EXCEPTION_DOMAIN,
                "groups": [request_reader_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_category_by_default": {
                "domain_force": WORKFLOW_CATEGORY_BY_DEFAULT_DOMAIN,
                "groups": [request_reader_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_category_for_create_audience": {
                "domain_force": WORKFLOW_CATEGORY_CREATE_AUDIENCE_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_task_instance_user_scope": {
                "domain_force": WORKFLOW_TASK_INSTANCE_USER_SCOPE_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
            "workflow_engine.rule_workflow_request_automation_instance_user_scope": {
                "domain_force": WORKFLOW_REQUEST_AUTOMATION_INSTANCE_USER_SCOPE_DOMAIN,
                "groups": [approval_user_group],
                "perms": {"perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False},
            },
        }
        IrModelData = self.env["ir.model.data"].sudo()
        for xmlid, rule_spec in desired_rules.items():
            module, name = xmlid.split(".", 1)
            imd = IrModelData.search(
                [("module", "=", module), ("name", "=", name)],
                limit=1,
            )
            if not imd or imd.model != "ir.rule" or not imd.res_id:
                continue
            rule = self.sudo().browse(imd.res_id).exists()
            if not rule:
                continue
            vals = {}
            domain_force = rule_spec.get("domain_force")
            if domain_force and _normalize_policy_domain(rule.domain_force) != _normalize_policy_domain(domain_force):
                vals["domain_force"] = domain_force
            group_xmlids = rule_spec.get("groups")
            if group_xmlids is not None:
                groups = self.env["res.groups"]
                for group_xmlid in group_xmlids:
                    group = self.env.ref(group_xmlid, raise_if_not_found=False)
                    if group:
                        groups |= group
                if groups and set(rule.groups.ids) != set(groups.ids):
                    vals["groups"] = [(6, 0, groups.ids)]
            for field_name, expected in rule_spec.get("perms", {}).items():
                if rule[field_name] != expected:
                    vals[field_name] = expected
            if not rule.active:
                vals["active"] = True
            if vals:
                rule.write(vals)


class WorkflowApprovalGroupLineSecurityPolicy(models.Model):
    _inherit = "workflow.approval.group.line"

    hr_line_code = fields.Char(string="HR Line Code", index=True)


class WorkflowApprovalGroupTeamSecurityPolicy(models.Model):
    _inherit = "workflow.approval.group.team"

    hr_team_code = fields.Char(string="HR Team Code", index=True)


class WorkflowBaseApprovalRequestSecurityPolicy(models.Model):
    _inherit = "workflow.base.approval.request"

    request_owner_manager_user_id = fields.Many2one(
        "res.users",
        string="Request Owner Manager",
        related="request_owner_emp_id.parent_id.user_id",
        store=True,
        readonly=True,
        index=True,
    )
    request_owner_line_code = fields.Char(
        string="Request Owner Line Code",
        related="request_owner_emp_id.x_line_code",
        store=True,
        readonly=True,
        index=True,
    )
    request_owner_team_code = fields.Char(
        string="Request Owner Team Code",
        related="request_owner_emp_id.x_team_code",
        store=True,
        readonly=True,
        index=True,
    )
    request_owner_line_id = fields.Many2one(
        "workflow.approval.group.line",
        string="Request Owner Line",
        compute="_compute_request_owner_structure_snapshot",
        store=True,
        index=True,
        readonly=True,
    )
    request_owner_team_id = fields.Many2one(
        "workflow.approval.group.team",
        string="Request Owner Team",
        compute="_compute_request_owner_structure_snapshot",
        store=True,
        index=True,
        readonly=True,
    )

    @api.depends("request_owner_line_code", "request_owner_team_code")
    def _compute_request_owner_structure_snapshot(self):
        Line = self.env["workflow.approval.group.line"].sudo()
        Team = self.env["workflow.approval.group.team"].sudo()
        for request in self:
            line = Line.search([("hr_line_code", "=", request.request_owner_line_code)], limit=1) if request.request_owner_line_code else Line.browse()
            team = Team.search([("hr_team_code", "=", request.request_owner_team_code)], limit=1) if request.request_owner_team_code else Team.browse()
            request.request_owner_line_id = line.id or False
            request.request_owner_team_id = team.id or False

class WorkflowApprovalCategorySecurityPolicy(models.Model):
    _inherit = "workflow.approval.category"

    security_policy_draft_initialized = fields.Boolean(default=False, copy=False)
    security_policy_draft_zero_trust_enforced = fields.Boolean(
        default=True,
        help=(
            "When enabled, category access starts from the working-copy access list below "
            "instead of being open to all workflow users."
        ),
    )
    security_policy_draft_allowed_user_ids = fields.Many2many(
        "res.users",
        "wf_category_policy_draft_user_rel",
        "category_id",
        "user_id",
        string="Draft Allowed Users",
        help=(
            "Users granted category-level access in the working copy. "
            "This does not filter which individual requests they can read."
        ),
    )
    security_policy_draft_allowed_group_ids = fields.Many2many(
        "res.groups",
        "wf_category_policy_draft_group_rel",
        "category_id",
        "group_id",
        string="Draft Allowed Groups",
        help=(
            "Groups granted category-level access in the working copy. "
            "This does not filter which individual requests they can read."
        ),
    )
    security_policy_draft_allowed_department_ids = fields.Many2many(
        "hr.department",
        "wf_category_policy_draft_department_rel",
        "category_id",
        "department_id",
        string="Draft Allowed Departments",
        help=(
            "Departments granted category-level access in the working copy. "
            "This does not filter which individual requests they can read."
        ),
    )
    security_policy_draft_allow_requester_read = fields.Boolean(
        default=True,
        help="Allow requester or creator to read their own requests after publish.",
    )
    security_policy_draft_allow_manager_access = fields.Boolean(
        default=False,
        help="Allow the request owner's manager to read matching requests after publish.",
    )
    security_policy_draft_allow_assignee_without_category_access = fields.Boolean(
        default=False,
        help="Allow assignees to work on requests even if they are outside the category access list.",
    )
    security_policy_draft_default_fallback_policy = fields.Selection(
        [
            ("escalate_manager", "Escalate to Manager"),
            ("route_admin_queue", "Route to Workflow Admin Queue"),
            ("block", "Block Task"),
        ],
        default="route_admin_queue",
        required=True,
        help="Fallback action when the runtime cannot resolve the next responsible user.",
    )
    security_policy_draft_admin_queue_user_id = fields.Many2one(
        "res.users",
        string="Draft Admin Queue Owner",
        help="Fallback user used when the fallback policy routes work to the admin queue.",
    )
    security_policy_draft_group_can_share_id = fields.Many2one(
        "res.groups",
        string="Draft Share Permission Group",
        help="Optional group that will become the share-authorized audience after publish.",
    )
    security_policy_draft_create_access_mode = fields.Selection(
        CREATE_ACCESS_MODE_SELECTION,
        string="Draft Request Creation Access",
        default="inherit_current_behavior",
        required=True,
        help=(
            "Working-copy create policy. Publish to make this active for new request submission."
        ),
    )
    security_policy_draft_create_allowed_user_ids = fields.Many2many(
        "res.users",
        "wf_category_policy_draft_create_user_rel",
        "category_id",
        "user_id",
        string="Draft Create Allowed Users",
        help="Users allowed to submit new requests after publish when create access is restricted.",
    )
    security_policy_draft_create_allowed_group_ids = fields.Many2many(
        "res.groups",
        "wf_category_policy_draft_create_group_rel",
        "category_id",
        "group_id",
        string="Draft Create Allowed Groups",
        help="Groups allowed to submit new requests after publish when create access is restricted.",
    )
    security_policy_draft_create_allowed_department_ids = fields.Many2many(
        "hr.department",
        "wf_category_policy_draft_create_department_rel",
        "category_id",
        "department_id",
        string="Draft Create Allowed Departments",
        help="Departments allowed to submit new requests after publish when create access is restricted.",
    )
    security_policy_rule_ids = fields.One2many(
        "workflow.category.access.policy.rule",
        "category_id",
        string="Draft Security Rules",
        copy=True,
        help="Working-copy read rules. Save and publish the category to make them active.",
    )
    security_policy_snapshot_ids = fields.One2many(
        "workflow.category.access.policy.snapshot",
        "category_id",
        string="Publish History",
        readonly=True,
    )
    security_policy_live_runtime_payload = fields.Json(copy=False, readonly=True)
    security_policy_live_rule_payload = fields.Json(copy=False, readonly=True)
    security_policy_last_published_snapshot_id = fields.Many2one(
        "workflow.category.access.policy.snapshot",
        string="Last Published Snapshot",
        readonly=True,
        copy=False,
    )
    security_policy_last_published_at = fields.Datetime(readonly=True, copy=False)
    security_policy_last_published_by = fields.Many2one("res.users", readonly=True, copy=False)
    security_policy_draft_rule_count = fields.Integer(
        string="Draft Rule Count",
        compute="_compute_security_policy_counts",
    )
    security_policy_publish_count = fields.Integer(
        string="Publish Count",
        compute="_compute_security_policy_counts",
    )
    security_policy_current_rule_summary_html = fields.Html(
        string="Current Published Read Visibility Rules",
        compute="_compute_security_policy_current_rule_summary_html",
        sanitize=False,
    )

    @api.depends("security_policy_rule_ids", "security_policy_snapshot_ids")
    def _compute_security_policy_counts(self):
        for category in self:
            category.security_policy_draft_rule_count = len(category.security_policy_rule_ids.filtered("active"))
            category.security_policy_publish_count = len(category.security_policy_snapshot_ids)

    def _security_policy_names_for_payload(self, model_name, record_ids):
        if not record_ids:
            return []
        if isinstance(record_ids, int):
            record_ids = [record_ids]
        records = self.env[model_name].sudo().browse(record_ids).exists()
        names = records.mapped("display_name")
        missing_ids = sorted(set(record_ids) - set(records.ids))
        names.extend(_("Missing ID %s") % missing_id for missing_id in missing_ids)
        return names

    def _security_policy_payload_scope_summary(self, payload):
        mode = payload.get("mode")
        if mode == "domain_builder":
            return payload.get("domain_builder") or _("Any request in category")
        if mode == "raw_domain":
            return (
                payload.get("base_request_domain")
                or payload.get("child_request_domain")
                or _("Technical raw domain")
            )

        preset_scope = payload.get("preset_scope")
        label = dict(POLICY_PRESET_SELECTION).get(preset_scope, preset_scope or "-")
        selector_map = {
            "request_owner_department": ("hr.department", "department_ids"),
            "request_owner_user": ("res.users", "request_owner_user_ids"),
            "request_owner_manager": ("res.users", "manager_user_ids"),
            "request_owner_line": ("workflow.approval.group.line", "line_ids"),
            "request_owner_team": ("workflow.approval.group.team", "team_ids"),
        }
        selector = selector_map.get(preset_scope)
        if not selector:
            return label
        names = self._security_policy_names_for_payload(
            selector[0],
            payload.get(selector[1]) or [],
        )
        return "%s: %s" % (label, ", ".join(names)) if names else label

    @api.depends(
        "security_policy_last_published_snapshot_id",
        "security_policy_last_published_snapshot_id.name",
        "security_policy_last_published_snapshot_id.published_at",
        "security_policy_last_published_snapshot_id.published_by",
        "security_policy_last_published_snapshot_id.rule_payload",
    )
    def _compute_security_policy_current_rule_summary_html(self):
        mode_labels = dict(POLICY_MODE_SELECTION)
        access_labels = dict(POLICY_ACCESS_LEVEL_SELECTION)
        Group = self.env["res.groups"].sudo()
        for category in self:
            snapshot = category.security_policy_last_published_snapshot_id.sudo()
            if not snapshot:
                category.security_policy_current_rule_summary_html = (
                    '<div class="text-muted">No security policy has been published for this category yet.</div>'
                )
                continue

            payloads = sorted(
                snapshot.rule_payload or [],
                key=lambda payload: (payload.get("sequence") or 0, payload.get("name") or ""),
            )
            snapshot_name = html_escape(snapshot.display_name)
            published_at = (
                html_escape(fields.Datetime.to_string(snapshot.published_at))
                if snapshot.published_at
                else "-"
            )
            published_by = html_escape(snapshot.published_by.display_name or "-")
            header = (
                '<div class="mb-2 text-muted">'
                'Current snapshot: <strong>%s</strong> &middot; Published at %s &middot; Published by %s'
                "</div>"
            ) % (snapshot_name, published_at, published_by)
            if not payloads:
                category.security_policy_current_rule_summary_html = (
                    header
                    + '<div class="alert alert-secondary mb-0">'
                    "No published read visibility rules are configured in this snapshot."
                    "</div>"
                )
                continue

            rows = []
            for payload in payloads:
                active = payload.get("active", True)
                audience_group = Group.browse(payload.get("audience_group_id") or 0).exists()
                audience_group_name = audience_group.display_name if audience_group else "-"
                active_badge = (
                    '<span class="badge text-bg-success">Yes</span>'
                    if active
                    else '<span class="badge text-bg-secondary">No</span>'
                )
                row_class = ' class="text-muted"' if not active else ""
                rows.append(
                    (
                        "<tr%s>"
                        "<td>%s</td>"
                        "<td>%s</td>"
                        "<td>%s</td>"
                        "<td>%s</td>"
                        "<td>%s</td>"
                        "<td>%s</td>"
                        "</tr>"
                    )
                    % (
                        row_class,
                        active_badge,
                        html_escape(payload.get("name") or "-"),
                        html_escape(audience_group_name),
                        html_escape(
                            access_labels.get(
                                payload.get("access_level"),
                                payload.get("access_level") or "-",
                            )
                        ),
                        html_escape(
                            mode_labels.get(
                                payload.get("mode"),
                                payload.get("mode") or "-",
                            )
                        ),
                        html_escape(category._security_policy_payload_scope_summary(payload)),
                    )
                )
            category.security_policy_current_rule_summary_html = (
                header
                + '<table class="table table-sm table-hover mb-0">'
                "<thead><tr>"
                "<th>Active</th>"
                "<th>Name</th>"
                "<th>Audience Group</th>"
                "<th>Access Level</th>"
                "<th>Rule Mode</th>"
                "<th>Scope Summary</th>"
                "</tr></thead>"
                "<tbody>%s</tbody>"
                "</table>"
            ) % "".join(rows)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_security_policy_draft_initialized()
        return records

    def _security_policy_child_model_name(self):
        self.ensure_one()
        model_name = (
            (self.res_model.model if self.res_model else False)
            or self.res_model_name
            or ""
        ).strip()
        return model_name or "workflow.base.approval.request"

    def _security_policy_preview_user(self, group):
        group = group.sudo()
        if self.env.user in group.user_ids:
            return self.env.user
        user = group.user_ids.filtered(lambda rec: rec.active and not rec.share)[:1]
        return user or self.env.user

    def _prepare_draft_values_from_live(self):
        self.ensure_one()
        values = {"security_policy_draft_initialized": True}
        for live_field, draft_field in LIVE_POLICY_FIELD_MAP.items():
            field = self._fields[live_field]
            value = self[live_field]
            if field.type == "many2many":
                values[draft_field] = [(6, 0, value.ids)]
            elif field.type == "many2one":
                values[draft_field] = value.id or False
            else:
                values[draft_field] = value
        return values

    def _prepare_live_values_from_draft(self):
        self.ensure_one()
        values = {}
        for live_field, draft_field in LIVE_POLICY_FIELD_MAP.items():
            field = self._fields[draft_field]
            value = self[draft_field]
            if field.type == "many2many":
                values[live_field] = [(6, 0, value.ids)]
            elif field.type == "many2one":
                values[live_field] = value.id or False
            else:
                values[live_field] = value
        return values

    def _ensure_security_policy_draft_initialized(self):
        for category in self:
            if category.security_policy_draft_initialized:
                continue
            category.write(category._prepare_draft_values_from_live())

    def _draft_allowed_principal_users(self):
        self.ensure_one()
        users = self.env["res.users"].sudo()
        users |= self.security_policy_draft_allowed_user_ids.sudo()
        users |= self.security_policy_draft_allowed_group_ids.sudo().mapped("all_user_ids")
        if self.security_policy_draft_allowed_department_ids and "department_id" in self.env["res.users"]._fields:
            users |= self.env["res.users"].sudo().search(
                [
                    ("department_id", "in", self.security_policy_draft_allowed_department_ids.ids),
                    ("active", "=", True),
                    ("share", "=", False),
                ]
            )
        if self.security_policy_draft_create_access_mode == "restricted":
            users |= self.security_policy_draft_create_allowed_user_ids.sudo()
            users |= self.security_policy_draft_create_allowed_group_ids.sudo().mapped("all_user_ids")
            if (
                self.security_policy_draft_create_allowed_department_ids
                and "department_id" in self.env["res.users"]._fields
            ):
                users |= self.env["res.users"].sudo().search(
                    [
                        ("department_id", "in", self.security_policy_draft_create_allowed_department_ids.ids),
                        ("active", "=", True),
                        ("share", "=", False),
                    ]
                )
        return users.filtered(lambda user: user.active and not user.share)

    def _ensure_draft_workflow_user_group_membership(self):
        workflow_user_group = self.env.ref(
            "workflow_engine.group_workflow_approval_user",
            raise_if_not_found=False,
        )
        if not workflow_user_group:
            return 0
        group_field = "group_ids" if "group_ids" in self.env["res.users"]._fields else "groups_id"
        updated = 0
        for category in self:
            template = category.access_policy_template_id
            if template and not template.auto_grant_workflow_user_group:
                continue
            users = category._draft_allowed_principal_users()
            users_to_update = users.filtered(
                lambda user: not user.has_group("workflow_engine.group_workflow_approval_user")
            )
            if users_to_update:
                users_to_update.sudo().write({group_field: [(4, workflow_user_group.id)]})
                updated += len(users_to_update)
        return updated

    def _draft_runtime_payload(self):
        self.ensure_one()
        return {
            "zero_trust_enforced": self.security_policy_draft_zero_trust_enforced,
            "allow_requester_read": self.security_policy_draft_allow_requester_read,
            "allow_manager_access": self.security_policy_draft_allow_manager_access,
            "allow_assignee_without_category_access": self.security_policy_draft_allow_assignee_without_category_access,
            "default_fallback_policy": self.security_policy_draft_default_fallback_policy,
            "admin_queue_user_id": self.security_policy_draft_admin_queue_user_id.id or False,
            "group_can_share_id": self.security_policy_draft_group_can_share_id.id or False,
            "allowed_user_ids": self.security_policy_draft_allowed_user_ids.ids,
            "allowed_group_ids": self.security_policy_draft_allowed_group_ids.ids,
            "allowed_department_ids": self.security_policy_draft_allowed_department_ids.ids,
            "create_access_mode": self.security_policy_draft_create_access_mode,
            "create_allowed_user_ids": self.security_policy_draft_create_allowed_user_ids.ids,
            "create_allowed_group_ids": self.security_policy_draft_create_allowed_group_ids.ids,
            "create_allowed_department_ids": self.security_policy_draft_create_allowed_department_ids.ids,
        }

    def _draft_rule_payload(self):
        self.ensure_one()
        return [
            rule._payload_dict()
            for rule in self.security_policy_rule_ids.sorted(key=lambda rec: (rec.sequence, rec.id))
        ]

    def _replace_draft_rule_payload(self, payload):
        self.ensure_one()
        commands = [(5, 0, 0)]
        for values in payload or []:
            create_values = dict(values)
            for field_name in (
                "department_ids",
                "request_owner_user_ids",
                "manager_user_ids",
                "line_ids",
                "team_ids",
            ):
                create_values[field_name] = [(6, 0, create_values.get(field_name) or [])]
            commands.append((0, 0, create_values))
        self.write({"security_policy_rule_ids": commands})

    def _restore_runtime_payload_to_draft(self, payload):
        self.ensure_one()
        payload = payload or {}
        values = {"security_policy_draft_initialized": True}
        for live_field, draft_field in LIVE_POLICY_FIELD_MAP.items():
            field = self._fields[draft_field]
            if live_field in payload:
                raw_value = payload.get(live_field)
            elif live_field == "create_access_mode":
                raw_value = "inherit_current_behavior"
            elif field.type == "many2many":
                raw_value = []
            else:
                raw_value = self[live_field]
            if field.type == "many2many":
                values[draft_field] = [(6, 0, raw_value or [])]
            else:
                values[draft_field] = raw_value or False if field.type == "many2one" else raw_value
        self.write(values)

    def _apply_access_policy_template(self, template):
        template = template.sudo()
        for category in self:
            values = template._prepare_category_draft_values()
            values.update(
                {
                    "access_policy_template_id": template.id,
                    "access_policy_last_applied_at": fields.Datetime.now(),
                    "access_policy_last_applied_by": self.env.user.id,
                }
            )
            category.write(values)
            category._replace_draft_rule_payload(template._prepare_category_rule_payload())

    def action_apply_access_policy_template(self):
        return self.action_open_security_policy_apply_wizard()

    def action_open_access_policy_wizard(self):
        return self.action_open_security_policy_apply_wizard()

    def action_open_security_policy_workspace(self):
        self.ensure_one()
        self._ensure_security_policy_draft_initialized()
        action = self.env.ref("workflow_engine.action_workflow_security_policy_workspace").read()[0]
        action["res_id"] = self.id
        action["context"] = {
            **self.env.context,
            "default_category_id": self.id,
        }
        return action

    def action_open_security_policy_apply_wizard(self):
        action = self.env.ref("workflow_engine.action_workflow_access_policy_apply_wizard").read()[0]
        selected_ids = (
            self.env.context.get("active_ids")
            if self.env.context.get("active_model") == "workflow.approval.category"
            else self.ids
        ) or self.ids
        default_template = self[:1].access_policy_template_id.id if self[:1] else False
        action["context"] = {
            **self.env.context,
            "default_category_ids": [(6, 0, selected_ids)],
            "default_template_id": default_template,
        }
        return action

    def action_open_security_policy_publish_wizard(self):
        action = self.env.ref("workflow_engine.action_workflow_access_policy_publish_wizard").read()[0]
        selected_ids = (
            self.env.context.get("active_ids")
            if self.env.context.get("active_model") == "workflow.approval.category"
            else self.ids
        ) or self.ids
        for category in self.browse(selected_ids):
            category._ensure_security_policy_draft_initialized()
        action["context"] = {
            **self.env.context,
            "default_category_ids": [(6, 0, selected_ids)],
        }
        return action

    def action_open_security_policy_rollback_wizard(self):
        self.ensure_one()
        action = self.env.ref("workflow_engine.action_workflow_access_policy_rollback_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_category_id": self.id,
            "default_snapshot_id": self.security_policy_last_published_snapshot_id.id or False,
        }
        return action

    def action_open_security_policy_diagnostic(self):
        self.ensure_one()
        action = self.env.ref("workflow_engine.action_workflow_security_access_diagnostic_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_category_id": self.id,
        }
        return action

    def _compile_security_policy_payloads(self):
        compiled = {}
        for category in self:
            category._ensure_security_policy_draft_initialized()
            share_groups = set()
            payloads = []
            for rule in category.security_policy_rule_ids.filtered("active").sorted(key=lambda rec: (rec.sequence, rec.id)):
                payload = rule._compiled_payload_for_category(category)
                payloads.append(payload)
                if rule.access_level == "read_share":
                    share_groups.add(rule.audience_group_id.id)
            if len(share_groups) > 1:
                group_names = ", ".join(
                    self.env["res.groups"].sudo().browse(list(share_groups)).mapped("display_name")
                )
                raise ValidationError(
                    _(
                        "Category '%(category)s' has multiple Read + Share audience groups (%(groups)s). "
                        "The current runtime supports a single share group."
                    )
                    % {
                        "category": category.display_name,
                        "groups": group_names,
                    }
                )
            compiled[category.id] = {
                "payloads": payloads,
                "share_group_id": next(iter(share_groups)) if share_groups else False,
            }
        return compiled

    def _clear_generated_security_rules(self):
        self.env["ir.rule"].sudo().search(
            [
                ("workflow_security_policy_generated", "=", True),
                ("workflow_security_category_id", "in", self.ids),
            ]
        ).unlink()

    def _create_generated_security_rules(self, snapshot, compiled_bundle):
        self.ensure_one()
        Rule = self.env["ir.rule"].sudo()
        Model = self.env["ir.model"].sudo()
        created = 0
        category_model = Model._get("workflow.approval.category")
        category_rule_group_ids = set()
        for index, payload in enumerate(compiled_bundle.get("payloads") or [], start=1):
            group_id = payload["group_id"]
            category_rule_group_ids.add(group_id)
            base_model = Model._get("workflow.base.approval.request")
            base_values = {
                "name": "WF Security Policy | %s | %s | Base" % (self.display_name, payload["rule_name"]),
                "model_id": base_model.id,
                "domain_force": payload["base_domain_expression"],
                "groups": [(6, 0, [group_id])],
                "perm_read": True,
                "perm_write": False,
                "perm_create": False,
                "perm_unlink": False,
                "workflow_security_policy_generated": True,
                "workflow_security_category_id": self.id,
                "workflow_security_snapshot_id": snapshot.id,
                "workflow_security_rule_key": "cat_%s_rule_%s_base_%s" % (self.id, payload["rule_id"], index),
            }
            Rule.create(base_values)
            created += 1
            child_model_name = payload.get("child_model_name")
            child_domain_expression = payload.get("child_domain_expression")
            if child_model_name and child_domain_expression:
                child_model = Model._get(child_model_name)
                Rule.create(
                    {
                        "name": "WF Security Policy | %s | %s | Child" % (self.display_name, payload["rule_name"]),
                        "model_id": child_model.id,
                        "domain_force": child_domain_expression,
                        "groups": [(6, 0, [group_id])],
                        "perm_read": True,
                        "perm_write": False,
                        "perm_create": False,
                        "perm_unlink": False,
                        "workflow_security_policy_generated": True,
                        "workflow_security_category_id": self.id,
                        "workflow_security_snapshot_id": snapshot.id,
                        "workflow_security_rule_key": "cat_%s_rule_%s_child_%s" % (self.id, payload["rule_id"], index),
                    }
                )
                created += 1
        for group_id in sorted(category_rule_group_ids):
            Rule.create(
                {
                    "name": "WF Security Policy | %s | Category Read" % self.display_name,
                    "model_id": category_model.id,
                    "domain_force": repr([("id", "=", self.id)]),
                    "groups": [(6, 0, [group_id])],
                    "perm_read": True,
                    "perm_write": False,
                    "perm_create": False,
                    "perm_unlink": False,
                    "workflow_security_policy_generated": True,
                    "workflow_security_category_id": self.id,
                    "workflow_security_snapshot_id": snapshot.id,
                    "workflow_security_rule_key": "cat_%s_category_%s" % (self.id, group_id),
                }
            )
            created += 1
        snapshot.sudo().write({"generated_rule_count": created})
        return created

    def _publish_security_policy(self, note=False):
        compiled_by_category = self._compile_security_policy_payloads()
        self._ensure_draft_workflow_user_group_membership()
        snapshots = self.env["workflow.category.access.policy.snapshot"]
        self._clear_generated_security_rules()
        for category in self:
            compiled_bundle = compiled_by_category.get(category.id, {})
            runtime_payload = category._draft_runtime_payload()
            share_group_id = compiled_bundle.get("share_group_id")
            live_values = category._prepare_live_values_from_draft()
            if share_group_id:
                live_values["group_can_share_id"] = share_group_id
                runtime_payload["group_can_share_id"] = share_group_id
            snapshot = self.env["workflow.category.access.policy.snapshot"].sudo().create(
                {
                    "name": "%s - %s" % (
                        category.display_name,
                        fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                    "category_id": category.id,
                    "template_id": category.access_policy_template_id.id or False,
                    "published_at": fields.Datetime.now(),
                    "published_by": self.env.user.id,
                    "note": note or False,
                    "runtime_payload": runtime_payload,
                    "rule_payload": category._draft_rule_payload(),
                }
            )
            self.browse(category.id)._create_generated_security_rules(snapshot, compiled_bundle)
            live_values.update(
                {
                    "security_policy_live_runtime_payload": runtime_payload,
                    "security_policy_live_rule_payload": compiled_bundle.get("payloads") or [],
                    "security_policy_last_published_snapshot_id": snapshot.id,
                    "security_policy_last_published_at": snapshot.published_at,
                    "security_policy_last_published_by": self.env.user.id,
                }
            )
            category.write(live_values)
            category._sync_category_request_model_security()
            snapshots |= snapshot
        return snapshots

    def _restore_security_policy_snapshot(self, snapshot):
        self.ensure_one()
        if snapshot.category_id != self:
            raise UserError(_("The selected snapshot does not belong to this category."))
        self._restore_runtime_payload_to_draft(snapshot.runtime_payload)
        self._replace_draft_rule_payload(snapshot.rule_payload)
        values = {
            "access_policy_template_id": snapshot.template_id.id or False,
            "access_policy_last_applied_at": fields.Datetime.now(),
            "access_policy_last_applied_by": self.env.user.id,
        }
        self.write(values)


class WorkflowCategoryAccessPolicyWizardCompatExtension(models.TransientModel):
    _inherit = "workflow.category.access.policy.wizard"

    def action_apply(self):
        self.ensure_one()
        if not self.category_ids:
            raise UserError(_("Please select at least one category."))
        self.category_ids._apply_access_policy_template(self.template_id)
        message = _(
            "Applied template '%(template)s' to %(count)s categories as draft policy data."
        ) % {
            "template": self.template_id.display_name,
            "count": len(self.category_ids),
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Security Template Applied"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WorkflowAccessPolicyApplyWizard(models.TransientModel):
    _name = "workflow.access.policy.apply.wizard"
    _description = "Apply Workflow Security Template"

    template_id = fields.Many2one(
        "workflow.access.policy.template",
        string="Security Policy Template",
        required=True,
    )
    category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_security_apply_wizard_category_rel",
        "wizard_id",
        "category_id",
        string="Categories",
        required=True,
    )
    changed_category_count = fields.Integer(compute="_compute_preview", readonly=True)
    changed_rule_count = fields.Integer(compute="_compute_preview", readonly=True)
    preview_html = fields.Html(compute="_compute_preview", sanitize=False, readonly=True)

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        if (
            self.env.context.get("active_model") == "workflow.approval.category"
            and "category_ids" in fields_list
            and active_ids
            and not result.get("category_ids")
        ):
            result["category_ids"] = [(6, 0, active_ids)]
        return result

    @api.depends("template_id", "category_ids")
    def _compute_preview(self):
        for wizard in self:
            changed_category_count = 0
            changed_rule_count = 0
            preview_html = _(
                "<p class='text-muted'>Select a template and categories to preview draft changes.</p>"
            )
            template = wizard.template_id.sudo().exists()
            categories = wizard.category_ids.sudo().exists()
            if not template or not categories:
                wizard.changed_category_count = changed_category_count
                wizard.changed_rule_count = changed_rule_count
                wizard.preview_html = preview_html
                continue
            items = []
            template_values = template._prepare_category_draft_values()
            template_rules = template.rule_ids
            template_rule_count = len(template_rules.filtered("active"))
            for category in categories:
                category._ensure_security_policy_draft_initialized()
                changed_fields = []
                for draft_field, value in template_values.items():
                    if draft_field == "security_policy_draft_initialized":
                        continue
                    category_field = category._fields[draft_field]
                    current_value = category[draft_field]
                    if category_field.type == "many2many":
                        if set(current_value.ids) != set(value[0][2]):
                            changed_fields.append(category_field.string)
                    elif category_field.type == "many2one":
                        if (current_value.id or False) != (value or False):
                            changed_fields.append(category_field.string)
                    elif current_value != value:
                        changed_fields.append(category_field.string)
                rule_changed = len(category.security_policy_rule_ids) != len(template_rules)
                if changed_fields or rule_changed:
                    changed_category_count += 1
                    if rule_changed:
                        changed_rule_count += abs(
                            len(category.security_policy_rule_ids) - len(template_rules)
                        )
                    item_parts = changed_fields[:]
                    if template_rule_count:
                        item_parts.append(_("Template rules: %s") % template_rule_count)
                    items.append(
                        "<li><strong>%s</strong>: %s</li>"
                        % (
                            html_escape(category.display_name),
                            html_escape(", ".join(item_parts) or _("Rules only")),
                        )
                    )
            if not items:
                preview_html = _(
                    "<p class='text-success'>Selected categories already match this template draft.</p>"
                )
            else:
                preview_html = (
                    "<p><strong>%s</strong></p><ul>%s</ul>"
                    % (
                        _(
                            "Apply will update draft policy settings only. Live access changes only after Publish Security Policy."
                        ),
                        "".join(items),
                    )
                )
            wizard.changed_category_count = changed_category_count
            wizard.changed_rule_count = changed_rule_count
            wizard.preview_html = preview_html

    def action_apply(self):
        self.ensure_one()
        self.category_ids._apply_access_policy_template(self.template_id)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Security Template Applied"),
                "message": _(
                    "Draft policy settings were copied to %(count)s categories."
                )
                % {"count": len(self.category_ids)},
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WorkflowAccessPolicyPublishWizard(models.TransientModel):
    _name = "workflow.access.policy.publish.wizard"
    _description = "Publish Workflow Security Policy"

    category_ids = fields.Many2many(
        "workflow.approval.category",
        "wf_security_publish_wizard_category_rel",
        "wizard_id",
        "category_id",
        string="Categories",
        required=True,
    )
    note = fields.Char()
    preview_html = fields.Html(compute="_compute_preview_html", sanitize=False, readonly=True)
    validation_error = fields.Text(compute="_compute_preview_html", readonly=True)
    compiled_rule_count = fields.Integer(compute="_compute_preview_html", readonly=True)

    @api.depends("category_ids")
    def _compute_preview_html(self):
        Request = self.env["workflow.base.approval.request"].sudo()
        for wizard in self:
            wizard.compiled_rule_count = 0
            wizard.validation_error = False
            if not wizard.category_ids:
                wizard.preview_html = _(
                    "<p class='text-muted'>Select categories to validate and preview the generated rules.</p>"
                )
                continue
            try:
                compiled = wizard.category_ids._compile_security_policy_payloads()
            except ValidationError as exc:
                wizard.validation_error = exc.args[0]
                wizard.preview_html = "<p class='text-danger'>%s</p>" % html_escape(exc.args[0])
                continue

            items = []
            try:
                for category in wizard.category_ids:
                    category_payload = compiled.get(category.id, {})
                    rule_items = []
                    for payload in category_payload.get("payloads") or []:
                        wizard.compiled_rule_count += 1
                        group = self.env["res.groups"].sudo().browse(payload["group_id"])
                        preview_user = category._security_policy_preview_user(group)
                        sample_domain = safe_eval(
                            payload["base_domain_expression"],
                            _rule_eval_symbols(preview_user),
                            mode="eval",
                        )
                        samples = Request.search(sample_domain, limit=5)
                        sample_names = ", ".join(samples.mapped("display_name")) or _("No sample records")
                        rule_items.append(
                            "<li><strong>%s</strong> (%s): %s</li>"
                            % (
                                html_escape(payload["rule_name"]),
                                html_escape(payload["group_name"]),
                                html_escape(sample_names),
                            )
                        )
                    items.append(
                        "<li><strong>%s</strong><ul>%s</ul></li>"
                        % (
                            html_escape(category.display_name),
                            "".join(rule_items) or "<li>%s</li>" % html_escape(_("No static read rules configured.")),
                        )
                    )
                wizard.preview_html = (
                    "<p><strong>%s</strong></p><ul>%s</ul>"
                    % (
                        _(
                            "Publish will replace generated read rules for the selected categories and move draft runtime settings to live runtime access."
                        ),
                        "".join(items),
                    )
                )
            except Exception as exc:
                wizard.validation_error = str(exc)
                wizard.preview_html = "<p class='text-danger'>%s</p>" % html_escape(str(exc))

    def action_publish(self):
        self.ensure_one()
        if self.validation_error:
            raise ValidationError(self.validation_error)
        snapshots = self.category_ids._publish_security_policy(note=self.note)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Security Policy Published"),
                "message": _(
                    "Published %(count)s category policies and generated %(snapshots)s snapshot entries."
                )
                % {
                    "count": len(self.category_ids),
                    "snapshots": len(snapshots),
                },
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WorkflowAccessPolicyRollbackWizard(models.TransientModel):
    _name = "workflow.access.policy.rollback.wizard"
    _description = "Rollback Workflow Security Policy"

    category_id = fields.Many2one(
        "workflow.approval.category",
        required=True,
        string="Category",
    )
    snapshot_id = fields.Many2one(
        "workflow.category.access.policy.snapshot",
        string="Snapshot",
        required=True,
        domain="[('category_id', '=', category_id)]",
    )
    preview_html = fields.Html(compute="_compute_preview_html", sanitize=False, readonly=True)

    @api.depends("snapshot_id")
    def _compute_preview_html(self):
        for wizard in self:
            if not wizard.snapshot_id:
                wizard.preview_html = _(
                    "<p class='text-muted'>Choose a published snapshot to restore.</p>"
                )
                continue
            wizard.preview_html = (
                "<p><strong>%s</strong></p><p>%s</p>"
                % (
                    html_escape(_("This rollback restores the selected snapshot into draft and republishes it immediately.")),
                    html_escape(
                        _(
                            "Published on %(date)s by %(user)s."
                        )
                        % {
                            "date": fields.Datetime.to_string(wizard.snapshot_id.published_at),
                            "user": wizard.snapshot_id.published_by.display_name,
                        }
                    ),
                )
            )

    def action_rollback(self):
        self.ensure_one()
        self.category_id._restore_security_policy_snapshot(self.snapshot_id)
        self.category_id._publish_security_policy(
            note=_("Rollback to snapshot %s") % self.snapshot_id.display_name
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Security Policy Rolled Back"),
                "message": _(
                    "Category %(category)s is now republished from snapshot %(snapshot)s."
                )
                % {
                    "category": self.category_id.display_name,
                    "snapshot": self.snapshot_id.display_name,
                },
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WorkflowSecurityAccessDiagnosticWizard(models.TransientModel):
    _name = "workflow.security.access.diagnostic.wizard"
    _description = "Workflow Security Access Diagnostic Wizard"

    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    category_id = fields.Many2one("workflow.approval.category", string="Category")
    request_id = fields.Many2one("workflow.base.approval.request", string="Request")
    access_granted = fields.Boolean(compute="_compute_analysis", readonly=True)
    analysis_html = fields.Html(compute="_compute_analysis", sanitize=False, readonly=True)

    @api.depends("user_id", "category_id", "request_id")
    def _compute_analysis(self):
        service = self.env["workflow.engine.permission.service"]

        def _badge(label, ok):
            css = "text-bg-success" if ok else "text-bg-secondary"
            return "<span class='badge %s'>%s</span>" % (css, html_escape(label))

        def _section(title, rows):
            if not rows:
                return ""
            return (
                "<div class='mt-3'>"
                "<div class='fw-bold mb-1'>%s</div>"
                "<ul class='mb-0'>%s</ul>"
                "</div>"
            ) % (html_escape(title), "".join("<li>%s</li>" % row for row in rows))

        def _source_label(source):
            labels = {
                "admin": "User is workflow/system admin.",
                "inherit_current_behavior": "All Workflow Users can create requests in this category.",
                "create_allowed_user": "User is listed in Create Allowed Users.",
                "create_allowed_group": "User belongs to a Create Allowed Group, including inherited/implied groups.",
                "create_allowed_department": "User belongs to a Create Allowed Department.",
            }
            return labels.get(source, source)

        def _has_live_access(recordset, operation):
            try:
                return bool(recordset.has_access(operation))
            except AccessError:
                return False

        def _rule_matches_expected(xmlid, expected_domain):
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if not rule:
                return False
            return _normalize_policy_domain(rule.domain_force) == _normalize_policy_domain(expected_domain)

        for wizard in self:
            if not wizard.user_id:
                wizard.analysis_html = _(
                    "<p class='text-muted'>Select a user to analyze access.</p>"
                )
                wizard.access_granted = False
                continue
            category = wizard.category_id or wizard.request_id.category_id
            if not category:
                wizard.analysis_html = _(
                    "<p class='text-muted'>Select a category or request to analyze.</p>"
                )
                wizard.access_granted = False
                continue

            user = wizard.user_id.sudo()
            category_access = service.can_access_category(category, user=user)
            static_category_access = service._has_static_policy_category_access(category, user)
            scope_category_access = service._has_visibility_category_access(category, user, scope="read")
            follower_category_access = service._has_follower_category_access(category, user)
            create_sources = category._create_access_match_sources(user=user)
            create_allowed = bool(create_sources)
            category_policy_visible = (
                category_access
                or create_allowed
                or static_category_access
                or scope_category_access
                or follower_category_access
            )
            category_record_rule_visible = _has_live_access(category.with_user(user), "read")
            category_visible = category_policy_visible and category_record_rule_visible
            base_model_create_access = _has_live_access(
                self.env["workflow.base.approval.request"].with_user(user).browse(),
                "create",
            )
            base_create_rule_ready = _rule_matches_expected(
                "workflow_engine.rule_workflow_base_for_create_audience",
                WORKFLOW_BASE_CREATE_AUDIENCE_DOMAIN,
            )
            save_new_request_allowed = create_allowed and base_model_create_access and base_create_rule_ready

            matched = []
            not_matched = []
            recommendations = []

            if category_access:
                matched.append(html_escape(_("Category allowlist matched: user/group/department can read this category.")))
            else:
                not_matched.append(
                    html_escape(
                        _(
                            "Category allowlist did not match. The user is not in Allowed Users, "
                            "Allowed Groups, or Allowed Departments for this category."
                        )
                    )
                )
            if category_record_rule_visible:
                matched.append(html_escape(_("Live Odoo category record rule allows this user to see the category.")))
            else:
                not_matched.append(
                    html_escape(
                        _(
                            "Live Odoo category record rule denies this category. The dashboard will not show it "
                            "even if a draft or policy explanation looks correct."
                        )
                    )
                )
                if category_policy_visible:
                    recommendations.append(
                        html_escape(
                            _(
                                "Policy sources matched, but the live category record rule did not. "
                                "Upgrade workflow_engine and republish/refresh this category policy."
                            )
                        )
                    )

            if create_allowed:
                matched.append(
                    html_escape(_("Create request access matched: %s"))
                    % html_escape(", ".join(_source_label(source) for source in create_sources))
                )
                if base_model_create_access:
                    matched.append(html_escape(_("Odoo model access allows creating workflow base requests.")))
                else:
                    not_matched.append(
                        html_escape(
                            _(
                                "Odoo model access denies create on Approval Base Request "
                                "(workflow.base.approval.request)."
                            )
                        )
                    )
                    recommendations.append(
                        html_escape(
                            _(
                                "Give the user's workflow group create access on Approval Base Request, "
                                "or add the user to the correct Workflow Approval User group."
                            )
                        )
                    )
                if base_create_rule_ready:
                    matched.append(html_escape(_("Base request create record rule matches the current engine policy.")))
                else:
                    not_matched.append(
                        html_escape(
                            _(
                                "Base request create record rule is stale or manually changed, so save/submit may fail "
                                "after the user clicks New Request."
                            )
                        )
                    )
                    recommendations.append(
                        html_escape(
                            _(
                                "Upgrade workflow_engine so WF: Request Create Audience Rule is refreshed. "
                                "Do not fix this by manually editing only one database."
                            )
                        )
                    )
                if save_new_request_allowed:
                    matched.append(html_escape(_("Save new request gate passed. The user should not hit a base-request create Access Error.")))
            else:
                not_matched.append(
                    html_escape(
                        _(
                            "Create request access did not match. Add the user/group/department "
                            "to Request Creation access if they should create requests."
                        )
                    )
                )

            if static_category_access:
                matched.append(html_escape(_("Published static read policy targets this user for the category.")))
            else:
                not_matched.append(
                    html_escape(_("No published static read policy currently targets this user."))
                )
            if scope_category_access:
                matched.append(html_escape(_("A visibility scope grants category read access.")))
            if follower_category_access:
                matched.append(html_escape(_("Follower access grants category read access.")))

            if save_new_request_allowed and not (
                category_access or static_category_access or scope_category_access or follower_category_access
            ):
                recommendations.append(
                    html_escape(
                        _(
                            "No extra config is needed for the dashboard/create button. "
                            "This user can see the category because they can create requests in it."
                        )
                    )
                )
                recommendations.append(
                    html_escape(
                        _(
                            "This does not allow reading all existing requests. To read existing requests, "
                            "publish a read visibility rule for the intended group and scope."
                        )
                    )
                )
            elif not category_visible:
                recommendations.append(
                    html_escape(
                        _(
                            "To show this category on the dashboard, add the user/group/department to "
                            "Create Allowed access or publish a static read policy for this category."
                        )
                    )
                )

            if wizard.request_id:
                request = wizard.request_id.sudo()
                policy_read_allowed = service.can_access_request(request, user=user, scope="read")
                granted = _has_live_access(request.with_user(user), "read")
                wizard.access_granted = granted
                request_matches = []
                request_misses = []
                if granted:
                    request_matches.append(html_escape(_("Live Odoo request record rule allows this user to read the request.")))
                else:
                    request_misses.append(
                        html_escape(
                            _(
                                "Live Odoo request record rule denies this request. This is the same gate used "
                                "when the user opens the form."
                            )
                        )
                    )
                if policy_read_allowed and not granted:
                    recommendations.append(
                        html_escape(
                            _(
                                "Workflow policy sources matched, but the live request record rule did not. "
                                "Upgrade workflow_engine, clear rule caches, and retest this request."
                            )
                        )
                    )
                if service.can_access_category(request.category_id, user=user):
                    request_matches.append(html_escape(_("Matched category read audience.")))
                if request.category_id.allow_requester_read and (
                    request.request_owner_id.id == user.id or request.create_uid.id == user.id
                ):
                    request_matches.append(html_escape(_("Matched requester/creator readonly access.")))
                if request.category_id.allow_manager_access and request.manager_user_id.id == user.id:
                    request_matches.append(html_escape(_("Matched creator manager readonly access.")))
                if request.request_owner_manager_user_id.id == user.id:
                    request_matches.append(html_escape(_("User is the request owner's manager snapshot.")))
                if service._has_scope_access(request, user, scope="read"):
                    request_matches.append(html_escape(_("Matched visibility scope access.")))
                if service._has_static_policy_access(request, user):
                    request_matches.append(html_escape(_("Matched published static read policy.")))
                if request.approver_ids.filtered(lambda row: row.user_id.id == user.id):
                    request_matches.append(html_escape(_("Matched approver row.")))
                if request.task_instance_ids.assignee_ids.filtered(
                    lambda row: row.assignee_user_id.id == user.id and row.status in ("new", "pending", "in_progress")
                ):
                    request_matches.append(html_escape(_("Matched active task assignee.")))
                if service._has_delegated_access(request, user):
                    request_matches.append(html_escape(_("Matched delegated access.")))
                if service._is_request_follower(request, user):
                    request_matches.append(html_escape(_("Matched follower access.")))
                if not request_matches:
                    request_misses.append(html_escape(_("No request-level read source matched.")))
                    recommendations.append(
                        html_escape(
                            _(
                                "If this user should read this existing request, grant requester/owner access, "
                                "visibility scope, follower access, assignment, or a published static read policy."
                            )
                        )
                    )
            else:
                wizard.access_granted = (
                    category_visible and save_new_request_allowed
                    if create_allowed
                    else category_visible
                )
                rule_matches = []
                for payload in category.security_policy_live_rule_payload or []:
                    if payload.get("group_id") in service._user_effective_group_ids(user):
                        rule_matches.append(payload.get("rule_name"))
                if rule_matches:
                    matched.append(
                        html_escape(_("Published static read policy groups: %s"))
                        % html_escape(", ".join(rule_matches))
                    )

            if wizard.request_id:
                verdict = _("Access granted") if wizard.access_granted else _("Access denied")
                alert_class = "alert-success" if wizard.access_granted else "alert-danger"
                headline = (
                    _("The user can read this request.")
                    if wizard.access_granted
                    else _("The user cannot read this request.")
                )
            else:
                if category_visible and create_allowed and save_new_request_allowed:
                    verdict = _("Ready")
                    alert_class = "alert-success"
                    headline = _("The user can see this category and save a new request.")
                elif category_visible and create_allowed:
                    verdict = _("Needs attention")
                    alert_class = "alert-warning"
                    headline = _("The user can see this category, but saving/submitting a new request may fail.")
                elif category_visible:
                    verdict = _("Access granted")
                    alert_class = "alert-success"
                    headline = _("The user can see this category, but cannot create new requests in it.")
                else:
                    verdict = _("Access denied")
                    alert_class = "alert-danger"
                    headline = _("The user cannot see this category on the dashboard.")

            summary_rows = [
                "%s %s" % (html_escape(_("Dashboard shows this category:")), _badge(_("Yes") if category_visible else _("No"), category_visible)),
                "%s %s" % (html_escape(_("New Request button allowed:")), _badge(_("Yes") if create_allowed else _("No"), create_allowed)),
                "%s %s" % (html_escape(_("Save new request allowed:")), _badge(_("Yes") if save_new_request_allowed else _("No"), save_new_request_allowed)),
                "%s %s" % (html_escape(_("Category allowlist/read audience:")), _badge(_("Yes") if category_access else _("No"), category_access)),
                "%s %s" % (html_escape(_("Published read visibility rule:")), _badge(_("Yes") if static_category_access else _("No"), static_category_access)),
            ]
            if create_allowed:
                summary_rows.append(
                    "%s %s"
                    % (
                        html_escape(_("Base request model create access:")),
                        _badge(_("Yes") if base_model_create_access else _("No"), base_model_create_access),
                    )
                )
                summary_rows.append(
                    "%s %s"
                    % (
                        html_escape(_("Base request create record rule:")),
                        _badge(_("Ready") if base_create_rule_ready else _("Needs module upgrade"), base_create_rule_ready),
                    )
                )
            if wizard.request_id:
                summary_rows.append(
                    "%s %s" % (html_escape(_("Can read selected request:")), _badge(_("Yes") if wizard.access_granted else _("No"), wizard.access_granted))
                )

            html = [
                "<div class='alert %s mb-3'><strong>%s:</strong> %s</div>"
                % (
                    alert_class,
                    html_escape(verdict),
                    html_escape(headline),
                ),
                _section(_("Summary"), summary_rows),
                _section(_("Matched Access Paths"), matched),
                _section(_("Not Matched / Why"), not_matched),
            ]
            if wizard.request_id:
                html.append(_section(_("Request Read Paths"), request_matches))
                html.append(_section(_("Request Read Misses"), request_misses))
            html.append(_section(_("Recommended Config"), recommendations))
            wizard.analysis_html = "".join(html)


class WorkflowRequestVisibilityScopeBulkWizard(models.TransientModel):
    _name = "workflow.request.visibility.scope.bulk.wizard"
    _description = "Workflow Request Visibility Scope Bulk Wizard"

    operation = fields.Selection(
        [("grant", "Grant"), ("revoke", "Revoke")],
        default="grant",
        required=True,
    )
    scope = fields.Selection(
        [("read", "Read"), ("edit", "Edit"), ("decision", "Decision")],
        default="read",
        required=True,
    )
    request_ids = fields.Many2many(
        "workflow.base.approval.request",
        "wf_visibility_scope_bulk_request_rel",
        "wizard_id",
        "request_id",
        string="Requests",
        required=True,
    )
    user_ids = fields.Many2many("res.users", string="Users")
    group_ids = fields.Many2many("res.groups", string="Groups")
    reason = fields.Char()
    expires_at = fields.Datetime()

    @api.model
    def default_get(self, fields_list):
        result = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        if (
            self.env.context.get("active_model") == "workflow.base.approval.request"
            and "request_ids" in fields_list
            and active_ids
            and not result.get("request_ids")
        ):
            result["request_ids"] = [(6, 0, active_ids)]
        return result

    def action_apply(self):
        self.ensure_one()
        if not self.user_ids and not self.group_ids:
            raise UserError(_("Please select at least one target user or group."))
        Scope = self.env["workflow.request.visibility.scope"].sudo()
        if self.operation == "grant":
            values_list = []
            for request in self.request_ids:
                for user in self.user_ids:
                    values_list.append(
                        {
                            "request_id": request.id,
                            "scope": self.scope,
                            "allowed_user_id": user.id,
                            "reason": self.reason or False,
                            "expires_at": self.expires_at or False,
                            "granted_by_user_id": self.env.user.id,
                            "active": True,
                        }
                    )
                for group in self.group_ids:
                    values_list.append(
                        {
                            "request_id": request.id,
                            "scope": self.scope,
                            "allowed_group_id": group.id,
                            "reason": self.reason or False,
                            "expires_at": self.expires_at or False,
                            "granted_by_user_id": self.env.user.id,
                            "active": True,
                        }
                    )
            if values_list:
                Scope.create(values_list)
            message = _("Granted %(scope)s visibility on %(count)s requests.") % {
                "scope": self.scope,
                "count": len(self.request_ids),
            }
        else:
            domain = [
                ("request_id", "in", self.request_ids.ids),
                ("scope", "=", self.scope),
                ("active", "=", True),
            ]
            if self.user_ids:
                domain.append(("allowed_user_id", "in", self.user_ids.ids))
            if self.group_ids:
                domain.append(("allowed_group_id", "in", self.group_ids.ids))
            Scope.search(domain).write({"active": False})
            message = _("Revoked %(scope)s visibility on %(count)s requests.") % {
                "scope": self.scope,
                "count": len(self.request_ids),
            }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Visibility Scope Updated"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class WorkflowApprovalBaseMixinSecurityTools(models.AbstractModel):
    _inherit = "approval.base.mixin"

    def _workflow_security_base_requests(self):
        if self._name == "workflow.base.approval.request":
            return self.sudo().exists()
        if "x_approval_base_id" in self._fields:
            return self.sudo().mapped("x_approval_base_id").exists()
        return self.env["workflow.base.approval.request"]

    @api.model
    def _workflow_resolve_create_access_category(self, vals=False):
        vals = dict(vals or {})
        category_id = vals.get("category_id") or self.env.context.get("default_category_id")
        if not category_id and "x_approval_base_id" in self._fields:
            base_request_id = vals.get("x_approval_base_id") or self.env.context.get("default_x_approval_base_id")
            if base_request_id:
                base_request = self.env["workflow.base.approval.request"].sudo().browse(base_request_id).exists()
                category_id = base_request.category_id.id if base_request else False
        if not category_id:
            return self.env["workflow.approval.category"]
        return self.env["workflow.approval.category"].sudo().browse(category_id).exists()

    @api.model
    def _workflow_check_create_access_from_vals_list(self, vals_list):
        if self.env.su or self.env.context.get("workflow_skip_category_create_access"):
            return True
        for vals in vals_list or []:
            category = self._workflow_resolve_create_access_category(vals=vals)
            if category:
                category.check_create_request_access(user=self.env.user)
        return True

    def _workflow_grant_notification_read_scopes(self, users, reason=False, request_record=False):
        request_record = (request_record or self._workflow_resolve_request_record()).sudo().exists()
        if not request_record:
            return self.env["workflow.request.visibility.scope"]

        users = (users or self.env["res.users"]).sudo().filtered(
            lambda user: user.active and not user.share
        )
        if not users:
            return self.env["workflow.request.visibility.scope"]

        Scope = self.env["workflow.request.visibility.scope"].sudo()
        existing = Scope.search(
            [
                ("request_id", "=", request_record.id),
                ("scope", "=", "read"),
                ("allowed_user_id", "in", users.ids),
            ],
            order="active desc, id asc",
        )
        winners = {}
        duplicates = Scope.browse()
        for row in existing:
            user_id = row.allowed_user_id.id
            if user_id in winners:
                duplicates |= row
                continue
            winners[user_id] = row

        if duplicates:
            duplicates.write({"active": False})

        values_list = []
        for user in users:
            row = winners.get(user.id)
            if row:
                update_vals = {}
                if not row.active:
                    update_vals["active"] = True
                if row.expires_at:
                    update_vals["expires_at"] = False
                if reason and row.reason != reason:
                    update_vals["reason"] = reason
                if row.granted_by_user_id.id != self.env.user.id:
                    update_vals["granted_by_user_id"] = self.env.user.id
                if update_vals:
                    row.write(update_vals)
                continue
            values_list.append(
                {
                    "request_id": request_record.id,
                    "scope": "read",
                    "allowed_user_id": user.id,
                    "granted_by_user_id": self.env.user.id,
                    "reason": reason or False,
                    "expires_at": False,
                    "active": True,
                }
            )
        if values_list:
            return Scope.create(values_list)
        return Scope.browse([row.id for row in winners.values()])

    def action_open_visibility_scopes(self):
        base_requests = self._workflow_security_base_requests()
        if not base_requests:
            raise UserError(_("No workflow base request is linked to this record."))
        action = self.env.ref("workflow_engine.action_workflow_request_visibility_scope").read()[0]
        if len(base_requests) == 1:
            action["domain"] = [("request_id", "=", base_requests.id)]
            action["context"] = {
                **self.env.context,
                "default_request_id": base_requests.id,
                "search_default_request_id": base_requests.id,
            }
        else:
            action["domain"] = [("request_id", "in", base_requests.ids)]
            action["context"] = self.env.context
        return action

    def action_open_security_access_diagnostic(self):
        base_request = self._workflow_security_base_requests()[:1]
        action = self.env.ref("workflow_engine.action_workflow_security_access_diagnostic_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_request_id": base_request.id if base_request else False,
            "default_category_id": base_request.category_id.id if base_request else False,
        }
        return action

    def action_open_visibility_scope_bulk_wizard(self):
        base_requests = self._workflow_security_base_requests()
        action = self.env.ref("workflow_engine.action_workflow_request_visibility_scope_bulk_wizard").read()[0]
        action["context"] = {
            **self.env.context,
            "default_request_ids": [(6, 0, base_requests.ids)],
        }
        return action
