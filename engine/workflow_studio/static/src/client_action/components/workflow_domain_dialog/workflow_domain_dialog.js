/** @odoo-module **/

import {_t} from "@web/core/l10n/translation";
import {Component, onWillStart, onWillUpdateProps, useRef, useState} from "@odoo/owl";
import {Dialog} from "@web/core/dialog/dialog";
import {DomainSelector} from "@web/core/domain_selector/domain_selector";
import {ModelFieldSelector} from "@web/core/model_field_selector/model_field_selector";
import {SelectMenu} from "@web/core/select_menu/select_menu";
import {useService} from "@web/core/utils/hooks";
import {Domain} from "@web/core/domain";
import {router} from "@web/core/browser/router";

const PRESETS = {
    generic: [
        {
            key: "always",
            label: _t("Always"),
            domain: "[]",
            help: _t("Apply unconditionally."),
        },
        {
            key: "none",
            label: _t("Never"),
            domain: "[('id', '=', 0)]",
            help: _t("Never matches any record."),
        },
    ],
    assignment_users: [
        {
            key: "internal_active",
            label: _t("Active Internal Users"),
            domain: "[('share', '=', False), ('active', '=', True)]",
            help: _t("Only active internal users."),
        },
        {
            key: "request_owner",
            label: _t("Request Owner"),
            domain: "[('id', '=', request_owner_id)]",
            help: _t("Assign only request owner."),
        },
        {
            key: "request_manager",
            label: _t("Creator Manager (Legacy)"),
            domain: "[('id', '=', manager_user_id)]",
            help: _t(
                "Uses creator manager symbol (manager_user_id). Prefer request owner line/department manager symbols."
            ),
        },
        {
            key: "request_creator",
            label: _t("Request Creator"),
            domain: "[('id', '=', request_creator_id)]",
            help: _t("Assign only request creator."),
        },
        {
            key: "request_creator_manager",
            label: _t("Creator Manager"),
            domain: "[('id', '=', request_creator_manager_user_id)]",
            help: _t("Assign manager of request creator."),
        },
        {
            key: "request_owner_manager_user",
            label: _t("Request Owner Manager User"),
            domain: "[('id', '=', request_owner_manager_user_id)]",
            help: _t("Assign request owner's manager user."),
        },
        {
            key: "request_owner_line_manager_user",
            label: _t("Request Owner Line Manager"),
            domain: "[('id', '=', request_owner_line_manager_user_id)]",
            help: _t("Assign direct line manager of request owner."),
        },
        {
            key: "request_owner_department_manager_user",
            label: _t("Request Owner Department Manager"),
            domain: "[('id', '=', request_owner_department_manager_user_id)]",
            help: _t("Assign manager of request owner's department."),
        },
        {
            key: "request_owner_manager_chain",
            label: _t("Request Owner Manager Chain"),
            domain: "[('id', 'in', request_owner_manager_chain_user_ids)]",
            help: _t("Assign all managers in request owner's reporting chain."),
        },
        {
            key: "request_owner_or_manager",
            label: _t("Request Owner Or Manager"),
            domain: "[('id', 'in', [request_owner_id, manager_user_id])]",
            help: _t("Assign request owner and manager when available."),
        },
        {
            key: "same_team_code_as_owner",
            label: _t("Same Team Code As Owner"),
            domain:
                "[('employee_ids.x_team_code', '!=', False), ('employee_ids.x_team_code', '=', request_owner_team_code)]",
            help: _t("Assign users whose employee team code matches request owner."),
        },
        {
            key: "same_line_code_as_owner",
            label: _t("Same Line Code As Owner"),
            domain:
                "[('employee_ids.x_line_code', '!=', False), ('employee_ids.x_line_code', '=', request_owner_line_code)]",
            help: _t("Assign users whose employee line code matches request owner."),
        },
        {
            key: "decided_approvers",
            label: _t("Approvers Who Decided"),
            domain: "[('id', 'in', decided_approver_user_ids)]",
            help: _t("Users who already made a decision on this request."),
        },
        {
            key: "pending_approvers",
            label: _t("Current Pending Approvers"),
            domain: "[('id', 'in', pending_approver_user_ids)]",
            help: _t("Users currently pending/new/waiting on this request."),
        },
        {
            key: "submitter_and_decided",
            label: _t("Submitter + Decided Approvers"),
            domain: "[('id', 'in', notification_submitter_and_decided_user_ids)]",
            help: _t("Request owner plus users who already made a decision."),
        },
        {
            key: "current_actor",
            label: _t("Current Actor"),
            domain: "[('id', '=', uid)]",
            help: _t("Assign only current actor."),
        },
        {
            key: "current_actor_or_owner",
            label: _t("Current Actor Or Owner"),
            domain: "[('id', 'in', [uid, request_owner_id])]",
            help: _t("Assign current actor or request owner."),
        },
        {
            key: "same_company",
            label: _t("Same Company As Actor"),
            domain: "[('company_id', '=', user.company_id.id)]",
            help: _t("Keep assignees in the actor company."),
        },
        {
            key: "exclude_request_owner",
            label: _t("Exclude Request Owner"),
            domain: "[('id', '!=', request_owner_id)]",
            help: _t("Useful when owner should not self-approve."),
        },
    ],
    request_scope: [
        {
            key: "always",
            label: _t("Always"),
            domain: "[]",
            help: _t("Always match request records."),
        },
        {
            key: "owner_is_current_actor",
            label: _t("Owner = Current Actor"),
            domain: "[('request_owner_id', '=', uid)]",
            help: _t("Apply rule only when actor is request owner."),
        },
        {
            key: "manager_is_current_actor",
            label: _t("Manager = Current Actor"),
            domain: "[('manager_user_id', '=', uid)]",
            help: _t("Apply rule only when actor is request manager."),
        },
        {
            key: "manager_available",
            label: _t("Manager Is Set"),
            domain: "[('manager_user_id', '!=', False)]",
            help: _t("Apply only when manager exists on request."),
        },
        {
            key: "same_company",
            label: _t("Request In Actor Company"),
            domain: "[('company_id', '=', user.company_id.id)]",
            help: _t("Useful in multi-company routing."),
        },
        {
            key: "draft_new",
            label: _t("Draft/New Requests"),
            domain: "[('state', 'in', ['draft', 'new'])]",
            help: _t("Apply only for draft/new requests."),
        },
        {
            key: "waiting_only",
            label: _t("Waiting Requests"),
            domain: "[('state', '=', 'waiting')]",
            help: _t("Apply only for waiting requests."),
        },
        {
            key: "date_overdue",
            label: _t("Date Field Overdue"),
            domain: "[('x_expect_return_date', '<', current_date)]",
            help: _t("Replace x_expect_return_date with any Date/Datetime field. current_date is evaluated when automation runs."),
        },
        {
            key: "date_today",
            label: _t("Date Field Today"),
            domain: "[('x_expect_return_date', '=', 'today')]",
            help: _t("Matches records whose date field is today. Replace x_expect_return_date with your field."),
        },
        {
            key: "date_tomorrow",
            label: _t("Date Field Tomorrow"),
            domain: "[('x_expect_return_date', '=', 'today +1d')]",
            help: _t("Matches records whose date field is tomorrow. Replace x_expect_return_date with your field."),
        },
        {
            key: "date_last_7_days",
            label: _t("Date Last 7 Days"),
            domain: "['&', ('x_expect_return_date', '>=', 'today -7d'), ('x_expect_return_date', '<', 'today')]",
            help: _t("Odoo-style relative range. Replace x_expect_return_date with your field."),
        },
        {
            key: "current_stage_older_than_1_day",
            label: _t("Current Stage > 1 Day"),
            domain: "[('wf_current_stage_age_minutes', '>=', 1440)]",
            help: _t("Simple Odoo-style domain for the actor/current stage age."),
        },
        {
            key: "specific_node_older_than_1_day",
            label: _t("Specific Node > 1 Day"),
            domain: "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 1440",
            help: _t("Advanced, parallel-safe expression. Replace Task_HOD with the BPMN node id."),
        },
        {
            key: "specific_node_older_than_1_week",
            label: _t("Specific Node > 1 Week"),
            domain: "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 10080",
            help: _t("Use as an automation guard when a specific active node has stayed open for 7 days."),
        },
        {
            key: "high_amount_example",
            label: _t("High Amount (Example)"),
            domain: "[('x_amount_total', '>=', 1000)]",
            help: _t("Example threshold, adjust to your request model."),
        },
    ],
    twofa: [
        {
            key: "always",
            label: _t("Always Require 2FA"),
            domain: "[]",
            help: _t("2FA is required whenever this action is executed."),
        },
        {
            key: "actor_name_hod",
            label: _t("Actor Name = HOD"),
            domain: "[('id', '!=', 0)] if actor_name_is('HOD') else [('id', '=', 0)]",
            help: _t("Require 2FA only when the acting user name is HOD."),
        },
        {
            key: "actor_department_financial",
            label: _t("Actor Dept = Financial"),
            domain: "[('id', '!=', 0)] if actor_in_department('Financial') else [('id', '=', 0)]",
            help: _t("Require 2FA only when acting user department is Financial."),
        },
        {
            key: "actor_is_manager",
            label: _t("Actor Is Manager"),
            domain: "[('id', '!=', 0)] if actor_is_request_manager() else [('id', '=', 0)]",
            help: _t("Require 2FA when the actor is the request manager."),
        },
        {
            key: "actor_position_hod",
            label: _t("Actor Position = HOD"),
            domain: "[('id', '!=', 0)] if actor_in_position('HOD') else [('id', '=', 0)]",
            help: _t("Require 2FA when actor job position is HOD."),
        },
        {
            key: "finance_department",
            label: _t("Finance Requests"),
            domain: "[('department_id.name', 'ilike', 'Finance')]",
            help: _t("Require 2FA for Finance department requests."),
        },
        {
            key: "high_amount",
            label: _t("High Amount"),
            domain: "[('x_amount_total', '>', 100)]",
            help: _t("Example threshold condition (adjust field/value as needed)."),
        },
    ],
    field_modifiers: [
        {
            key: "never",
            label: _t("Keep Hidden"),
            domain: "[('id', '=', 0)]",
            help: _t("Always hidden, readonly, and optional."),
        },
        {
            key: "always",
            label: _t("Always Editable"),
            domain: "[]",
            help: _t("Always visible, editable, and required."),
        },
        {
            key: "actor_login_hod",
            label: _t("Actor Login = hod"),
            domain: "[('wf_actor_login', '=', 'hod')]",
            help: _t("Match only when current actor login is hod."),
        },
        {
            key: "actor_is_hod",
            label: _t("Actor Is HOD"),
            domain: "[('wf_actor_is_hod', '=', True)]",
            help: _t("Match when current actor has HOD role."),
        },
        {
            key: "actor_department_financial",
            label: _t("Actor Dept = Financial"),
            domain: "[('wf_actor_department_name', 'ilike', 'financial')]",
            help: _t("Match when actor department contains Financial."),
        },
        {
            key: "actor_is_manager",
            label: _t("Actor Is Manager"),
            domain: "[('wf_actor_is_manager', '=', True)]",
            help: _t("Match when actor is request manager."),
        },
        {
            key: "action_approve",
            label: _t("Action = Approve"),
            domain: "[('wf_action_key', 'ilike', 'approve')]",
            help: _t("Match when workflow action key is Approve."),
        },
        {
            key: "action_reject",
            label: _t("Action = Reject"),
            domain: "[('wf_action_key', 'ilike', 'reject')]",
            help: _t("Match when workflow action key is Reject."),
        },
        {
            key: "high_amount",
            label: _t("High Amount"),
            domain: "[('x_amount_total', '>', 100)]",
            help: _t("Example business threshold condition."),
        },
    ],
};

PRESETS.assignment_users_routing = [
    {
        key: "always",
        label: _t("Always"),
        domain: "[(1, '=', 1)]",
        help: _t("Intentionally keep all users from the selected routing source."),
    },
    {
        key: "never",
        label: _t("Never"),
        domain: "[(0, '=', 1)]",
        help: _t("Intentionally contribute no users from this routing source."),
    },
    ...PRESETS.assignment_users,
];

PRESETS.request_scope_routing = [
    {
        key: "always",
        label: _t("Always"),
        domain: "[(1, '=', 1)]",
        help: _t("Intentionally match all request records for this routing rule."),
    },
    {
        key: "never",
        label: _t("Never"),
        domain: "[(0, '=', 1)]",
        help: _t("Intentionally match no request records for this routing rule."),
    },
    ...PRESETS.request_scope.filter((preset) => !["always", "never"].includes(preset.key)),
];

const FIELD_MODIFIER_COMMON_PRESETS = [
    {
        key: "actor_login_hod",
        label: _t("Actor Login = hod"),
        domain: "[('wf_actor_login', '=', 'hod')]",
        help: _t("Match only when current actor login is hod."),
    },
    {
        key: "actor_is_hod",
        label: _t("Actor Is HOD"),
        domain: "[('wf_actor_is_hod', '=', True)]",
        help: _t("Match when current actor has HOD role."),
    },
    {
        key: "actor_department_financial",
        label: _t("Actor Dept = Financial"),
        domain: "[('wf_actor_department_name', 'ilike', 'financial')]",
        help: _t("Match when actor department contains Financial."),
    },
    {
        key: "actor_is_manager",
        label: _t("Actor Is Manager"),
        domain: "[('wf_actor_is_manager', '=', True)]",
        help: _t("Match when actor is request manager."),
    },
    {
        key: "current_stage_older_than_1_day",
        label: _t("Current Stage > 1 Day"),
        domain: "[('wf_current_stage_age_minutes', '>=', 1440)]",
        help: _t("Match when the current stage has been active for at least 1 day."),
    },
    {
        key: "high_amount",
        label: _t("High Amount"),
        domain: "[('x_amount_total', '>', 100)]",
        help: _t("Example business threshold condition."),
    },
];

const FIELD_MODIFIER_ACTION_PRESETS = [
    {
        key: "action_approve",
        label: _t("Action = Approve"),
        domain: "[('wf_action_key', 'ilike', 'approve')]",
        help: _t("Require the field when the selected workflow action is Approve."),
    },
    {
        key: "action_rework",
        label: _t("Action = Rework"),
        domain: "[('wf_action_key', 'ilike', 'rework')]",
        help: _t("Require the field when the selected workflow action is Rework."),
    },
    {
        key: "action_reject",
        label: _t("Action = Reject"),
        domain: "[('wf_action_key', 'ilike', 'reject')]",
        help: _t("Require the field when the selected workflow action is Reject."),
    },
    {
        key: "action_submit",
        label: _t("Action = Submit"),
        domain: "[('wf_action_key', 'ilike', 'submit')]",
        help: _t("Require the field when the selected workflow action is Submit."),
    },
];

const FIELD_MODIFIER_PRESETS_BY_KIND = {
    visible: [
        {
            key: "always_visible",
            label: _t("Always Visible"),
            domain: "[]",
            help: _t("Show the field whenever the form is open."),
        },
        {
            key: "always_hidden",
            label: _t("Always Hidden"),
            domain: "[('id', '=', 0)]",
            help: _t("Never show the field."),
        },
        ...FIELD_MODIFIER_COMMON_PRESETS,
    ],
    readonly: [
        {
            key: "always_readonly",
            label: _t("Always Readonly"),
            domain: "[]",
            help: _t("Lock the field whenever it is visible."),
        },
        {
            key: "always_editable",
            label: _t("Always Editable"),
            domain: "[('id', '=', 0)]",
            help: _t("Never lock the field through this workflow rule."),
        },
        ...FIELD_MODIFIER_COMMON_PRESETS,
    ],
    required: [
        {
            key: "always_required",
            label: _t("Always Required"),
            domain: "[]",
            help: _t("Require the field whenever it is visible and editable."),
        },
        {
            key: "never_required",
            label: _t("Never Required"),
            domain: "[('id', '=', 0)]",
            help: _t("Never require the field through this workflow rule."),
        },
        ...FIELD_MODIFIER_COMMON_PRESETS,
        ...FIELD_MODIFIER_ACTION_PRESETS,
    ],
};

const HELP_TEXT = {
    generic: _t("Use the builder or advanced editor to define a domain expression."),
    assignment_users: _t(
        "This domain is evaluated on users. Request form values and actor context are merged into evaluation symbols."
    ),
    assignment_users_routing: _t(
        "This routing domain is evaluated on users. Blank, [], and invalid expressions are accepted but ignored safely; use [(1, '=', 1)] or [(0, '=', 1)] for explicit all/none behavior."
    ),
    request_scope: _t(
        "This domain is evaluated on request records. Use Simple Odoo-style domains for the current stage age, or Advanced helper functions for a specific active node in parallel flows."
    ),
    request_scope_routing: _t(
        "This routing domain is evaluated on request records. Blank, [], and invalid expressions are accepted but ignored safely; use [(1, '=', 1)] or [(0, '=', 1)] for explicit all/none behavior."
    ),
    twofa: _t(
        "2FA domain is evaluated on the approval request record. You can use helper functions: actor_name_is, actor_in_department, actor_in_position, actor_has_group, actor_is_request_manager, actor_is_hod."
    ),
    field_modifiers: _t(
        "Workflow field condition is evaluated on runtime form data. Visible and readonly rules ignore action key; required rules may use wf_action_key, wf_current_node_id, actor symbols, and request form fields."
    ),
};

const BASE_SIMPLE_CONDITION_FIELDS = [
    {value: "wf_actor_login", label: _t("Actor Login"), type: "text", defaultOperator: "="},
    {value: "wf_actor_name", label: _t("Actor Name"), type: "text", defaultOperator: "ilike"},
    {
        value: "wf_actor_department_name",
        label: _t("Actor Department"),
        type: "text",
        defaultOperator: "ilike",
    },
    {
        value: "wf_actor_position_name",
        label: _t("Actor Position"),
        type: "text",
        defaultOperator: "ilike",
    },
    {
        value: "wf_actor_group_xmlids",
        label: _t("Actor Group XMLIDs (Legacy)"),
        type: "text",
        defaultOperator: "ilike",
    },
    {value: "wf_actor_is_hod", label: _t("Actor Is HOD"), type: "boolean", defaultOperator: "="},
    {
        value: "wf_actor_is_manager",
        label: _t("Actor Is Manager"),
        type: "boolean",
        defaultOperator: "=",
    },
    {value: "wf_action_key", label: _t("Action Key"), type: "text", defaultOperator: "ilike"},
    {
        value: "wf_current_node_id",
        label: _t("Current Node ID"),
        type: "text",
        inputKind: "activity_node",
        defaultOperator: "=",
    },
    {
        value: "current_node_id",
        label: _t("Current Node ID (Alias)"),
        type: "text",
        inputKind: "activity_node",
        defaultOperator: "=",
    },
    {
        value: "wf_current_stage_age_minutes",
        label: _t("Current Stage Age (Minutes)"),
        type: "number",
        dataType: "integer",
        defaultOperator: ">=",
    },
    {
        value: "current_stage_age_minutes",
        label: _t("Current Stage Age (Alias)"),
        type: "number",
        dataType: "integer",
        defaultOperator: ">=",
    },
    {
        value: "current_meta_task_id",
        label: _t("Current Meta Task ID"),
        type: "text",
        dataType: "integer",
        defaultOperator: "=",
    },
];

const SIMPLE_REQUEST_ALLOWED_TYPES = new Set([
    "char",
    "text",
    "html",
    "selection",
    "boolean",
    "integer",
    "float",
    "monetary",
    "date",
    "datetime",
    "many2one",
    "one2many",
    "many2many",
]);

const SIMPLE_TEXT_OPERATORS = [
    {value: "=", label: _t("is equal to")},
    {value: "!=", label: _t("is not equal to")},
    {value: "ilike", label: _t("contains")},
    {value: "not ilike", label: _t("does not contain")},
    {value: "in", label: _t("is in list")},
    {value: "not in", label: _t("is not in list")},
];

const SIMPLE_BOOLEAN_OPERATORS = [
    {value: "=", label: _t("is")},
    {value: "!=", label: _t("is not")},
];

const SIMPLE_SCALAR_OPERATORS = [
    {value: "=", label: _t("is equal to")},
    {value: "!=", label: _t("is not equal to")},
    {value: "in", label: _t("is in list")},
    {value: "not in", label: _t("is not in list")},
];

const SIMPLE_X2MANY_OPERATORS = [
    {value: "in", label: _t("contains any of")},
    {value: "not in", label: _t("does not contain any of")},
];

const SIMPLE_NUMERIC_OPERATORS = [
    {value: "=", label: _t("is equal to")},
    {value: "!=", label: _t("is not equal to")},
    {value: ">", label: _t("greater than")},
    {value: ">=", label: _t("greater or equal")},
    {value: "<", label: _t("less than")},
    {value: "<=", label: _t("less or equal")},
    {value: "in", label: _t("is in list")},
    {value: "not in", label: _t("is not in list")},
];

const RUNTIME_VALUE_OPERATORS = [
    {value: "is_set", label: _t("is set")},
    {value: "is_not_set", label: _t("is not set")},
    {value: "=", label: _t("equals")},
    {value: "!=", label: _t("not equal")},
    {value: "in", label: _t("in")},
    {value: "not in", label: _t("not in")},
    {value: ">", label: _t("greater than")},
    {value: ">=", label: _t("greater or equal")},
    {value: "<", label: _t("less than")},
    {value: "<=", label: _t("less or equal")},
];

const RUNTIME_VALUE_PRESENCE_OPERATORS = new Set(["is_set", "is_not_set"]);

const RUNTIME_REFERENCE_RECOMMENDED_KEYS = new Set([
    "request_owner_id",
    "request_owner_line_manager_user_id",
    "uid",
    "current_date",
    "wf_action_key",
    "wf_current_node_id",
    "wf_current_stage_age_minutes",
    "pending_approver_user_ids",
    "decided_approver_user_ids",
    "wf_actor_is_manager",
    "wf_actor_is_hod",
]);

const LINE_MATCH_MODE_OPTIONS = [
    {value: "any", label: _t("At least one line matches")},
    {value: "all", label: _t("Every line matches")},
    {value: "has_lines", label: _t("Line list is not empty")},
    {value: "no_lines", label: _t("Line list is empty")},
];

const LINE_MATCH_OPERATORS = [
    {value: "is_set", label: _t("has a value")},
    {value: "is_not_set", label: _t("is empty")},
    {value: "=", label: _t("equals")},
    {value: "!=", label: _t("not equal")},
    {value: "ilike", label: _t("contains")},
    {value: "not ilike", label: _t("does not contain")},
    {value: "in", label: _t("in list")},
    {value: "not in", label: _t("not in list")},
    {value: ">", label: _t("greater than")},
    {value: ">=", label: _t("greater or equal")},
    {value: "<", label: _t("less than")},
    {value: "<=", label: _t("less or equal")},
];

export function buildWorkflowRuntimeClause({
    fieldName = "",
    operator = "=",
    valueExpression = "",
} = {}) {
    const normalizedFieldName = `${fieldName || ""}`.trim();
    const normalizedOperator = `${operator || ""}`.trim() || "=";
    if (!normalizedFieldName) {
        return "";
    }
    if (normalizedOperator === "is_set") {
        return `[(${JSON.stringify(normalizedFieldName)}, "!=", False)]`;
    }
    if (normalizedOperator === "is_not_set") {
        return `[(${JSON.stringify(normalizedFieldName)}, "=", False)]`;
    }
    const normalizedValueExpression = `${valueExpression || ""}`.trim();
    if (!normalizedValueExpression) {
        return "";
    }
    return `[(${JSON.stringify(normalizedFieldName)}, ${JSON.stringify(normalizedOperator)}, ${normalizedValueExpression})]`;
}

export function buildWorkflowLineMatchExpression({
    relation = "",
    mode = "any",
    path = "",
    operator = "=",
    valueLiteral = "",
} = {}) {
    const normalizedRelation = `${relation || ""}`.trim();
    if (!normalizedRelation) {
        return "";
    }
    if (mode === "has_lines") {
        return `wf_any(${JSON.stringify(normalizedRelation)}, True)`;
    }
    if (mode === "no_lines") {
        return `not wf_any(${JSON.stringify(normalizedRelation)}, True)`;
    }

    const normalizedPath = `${path || ""}`.trim();
    let normalizedOperator = `${operator || ""}`.trim() || "=";
    let normalizedValueLiteral = `${valueLiteral || ""}`.trim();
    if (normalizedOperator === "is_set") {
        normalizedOperator = "!=";
        normalizedValueLiteral = "False";
    } else if (normalizedOperator === "is_not_set") {
        normalizedOperator = "=";
        normalizedValueLiteral = "False";
    }
    if (!normalizedPath || !normalizedValueLiteral) {
        return "";
    }

    const helper = mode === "all" ? "wf_all" : "wf_any";
    return `${helper}(${JSON.stringify(normalizedRelation)}, [(${JSON.stringify(normalizedPath)}, ${JSON.stringify(normalizedOperator)}, ${normalizedValueLiteral})])`;
}

export class WorkflowStudioRuntimeReferenceDialog extends Component {
    static template = "workflow_studio.RuntimeReferenceDialog";
    static components = {Dialog, SelectMenu};
    static props = {
        close: Function,
        rows: Array,
        categoryOptions: Array,
        referenceState: Object,
        showRuntimePathBuilder: {type: Boolean, optional: true},
        openRuntimeBuilder: {type: Function, optional: true},
    };
    static defaultProps = {
        showRuntimePathBuilder: false,
    };

    get runtimeReferenceCategorySelectProps() {
        return {
            choices: this.props.categoryOptions,
            value: this.props.referenceState.runtimeReferenceCategory || "recommended",
            onSelect: (value) => {
                this.props.referenceState.runtimeReferenceCategory = value || "recommended";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_reference_category",
            togglerClass: "form-select o_wfs_runtime_value_select_toggler",
        };
    }

    get runtimeReferenceRows() {
        const category =
            this.props.referenceState.runtimeReferenceCategory || "recommended";
        const query = `${
            this.props.referenceState.runtimeReferenceQuery || ""
        }`.trim().toLowerCase();
        return this.props.rows.filter((row) => {
            const categoryMatches =
                category === "all" ||
                (category === "recommended"
                    ? row.recommended
                    : row.category === category);
            if (!categoryMatches) {
                return false;
            }
            if (!query) {
                return true;
            }
            const haystack = `${
                row.symbol || ""
            } ${row.meaning || ""} ${row.sample || ""}`.toLowerCase();
            return haystack.includes(query);
        });
    }

    get runtimeReferenceCountLabel() {
        return `${this.runtimeReferenceRows.length} of ${this.props.rows.length} ${_t(
            "symbols"
        )}`;
    }

    onRuntimeReferenceSearchInput(event) {
        this.props.referenceState.runtimeReferenceQuery =
            event?.target?.value || "";
    }

    onOpenRuntimeBuilder() {
        this.props.close();
        this.props.openRuntimeBuilder?.();
    }
}

export class WorkflowStudioDomainDialog extends Component {
    static template = "workflow_studio.WorkflowStudioDomainDialog";
    static components = {
        Dialog,
        DomainSelector,
        ModelFieldSelector,
        SelectMenu,
    };
    static props = {
        close: Function,
        onConfirm: Function,
        resModel: String,
        requestModel: {type: String, optional: true},
        requestFields: {type: Array, optional: true},
        workflowVersionId: {type: Number, optional: true},
        workflowCategoryId: {type: Number, optional: true},
        workflowMetaTaskOptions: {type: Array, optional: true},
        domain: {type: String, optional: true},
        className: {type: String, optional: true},
        defaultConnector: {type: [{value: "&"}, {value: "|"}], optional: true},
        isDebugMode: {type: Boolean, optional: true},
        readonly: {type: Boolean, optional: true},
        context: {type: Object, optional: true},
        title: {type: String, optional: true},
        helpText: {type: String, optional: true},
        contextType: {type: String, optional: true},
        presets: {type: Array, optional: true},
        domainKind: {type: String, optional: true},
        onApplyWorkflowScenario: {type: Function, optional: true},
        allowBlankDomain: {type: Boolean, optional: true},
    };
    static defaultProps = {
        domain: "[]",
        isDebugMode: false,
        readonly: false,
        context: {},
        contextType: "generic",
        allowBlankDomain: false,
    };

    _defaultRuntimeTargetField(props = this.props) {
        return `${props?.resModel || ""}`.trim() === "res.users" ? "id" : "";
    }

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.confirmButtonRef = useRef("confirm");
        this._simpleConditionSeq = 0;
        const initialDomain = this._normalizeDomainInput(this.props.domain) || this.emptyDomainFallback;
        this.state = useState({
            domain: initialDomain,
            mode: this._resolveInitialMode(initialDomain),
            validationError: "",
            validating: false,
            actorField: "department",
            actorValue: "",
            simpleConnector: "&",
            simpleConditions: this._buildInitialSimpleConditions(initialDomain),
            scenarioActorType: "request_owner",
            scenarioActorLogin: "",
            scenarioActorGroupXmlid: "",
            scenarioNodeId: "",
            scenarioActionKey: "approve",
            scenarioRequireOnAction: true,
            workflowNodeId: "",
            workflowActionKey: "",
            runtimeObject: "request",
            runtimePath: "",
            runtimeTargetField: this._defaultRuntimeTargetField(this.props),
            runtimeOperator: "=",
            lineMatchRelation: "",
            lineMatchMode: "any",
            lineMatchPath: "",
            lineMatchOperator: "ilike",
            lineMatchValue: "",
            presetApplyMode: "and",
            showRuntimeBuilderModal: false,
            runtimeReferenceQuery: "",
            runtimeReferenceCategory: "recommended",
        });
        this.requestFieldState = useState({rows: []});
        this.activityNodeState = useState({
            rows: [],
            loading: false,
            contextKey: "",
            loaded: false,
        });
        this.workflowActionState = useState({
            rows: [],
            loading: false,
            contextKey: "",
            loaded: false,
        });

        onWillStart(async () => {
            await this._ensureRequestFields(this.props);
            await this._ensureActivityNodeOptions(this.props);
            await this._ensureWorkflowActionOptions(this.props);
        });

        onWillUpdateProps(async (nextProps) => {
            await this._ensureRequestFields(nextProps);
            await this._ensureActivityNodeOptions(nextProps);
            await this._ensureWorkflowActionOptions(nextProps);
            if (!`${this.state.runtimeTargetField || ""}`.trim()) {
                this.state.runtimeTargetField = this._defaultRuntimeTargetField(nextProps);
            }
        });
    }

    async _ensureRequestFields(props = this.props) {
        const explicitRows = Array.isArray(props?.requestFields) ? props.requestFields : [];
        const model = `${props?.requestModel || props?.resModel || ""}`.trim();
        const mergedByName = new Map();
        for (const row of explicitRows) {
            const name = `${row?.name || ""}`.trim();
            if (!name) {
                continue;
            }
            mergedByName.set(name, {
                name,
                field_description: row?.field_description || row?.string || row?.label || name,
                ttype: `${row?.ttype || row?.type || ""}`.trim().toLowerCase(),
                relation: row?.relation || "",
                selection: this._normalizeSelectionOptions(row?.selection),
            });
        }

        if (!model) {
            this.requestFieldState.rows = Array.from(mergedByName.values());
            return;
        }
        try {
            const records = await this.orm.searchRead(
                "ir.model.fields",
                [["model", "=", model]],
                ["name", "field_description", "ttype", "relation"],
                {order: "field_description,name", limit: 500}
            );
            const normalizedRecords = Array.isArray(records) ? records : [];
            for (const row of normalizedRecords) {
                const name = `${row?.name || ""}`.trim();
                if (!name) {
                    continue;
                }
                const existing = mergedByName.get(name) || {};
                mergedByName.set(name, {
                    ...existing,
                    name,
                    field_description: existing.field_description || row?.field_description || name,
                    ttype: (existing.ttype || `${row?.ttype || ""}`.trim().toLowerCase()) || "",
                    relation: existing.relation || row?.relation || "",
                    selection: existing.selection || [],
                });
            }
        } catch {
            // Fall through to model.fields_get when ir.model.fields is not accessible.
        }
        try {
            const fieldDefs = await this.orm.call(model, "fields_get", [], {
                attributes: ["string", "type", "relation", "selection"],
            });
            for (const [name, meta] of Object.entries(fieldDefs || {})) {
                const existing = mergedByName.get(name) || {};
                mergedByName.set(name, {
                    ...existing,
                    name,
                    field_description: existing.field_description || meta?.string || name,
                    ttype: (existing.ttype || `${meta?.type || ""}`.trim().toLowerCase()) || "",
                    relation: existing.relation || meta?.relation || "",
                    selection: existing.selection?.length
                        ? existing.selection
                        : this._normalizeSelectionOptions(meta?.selection),
                });
            }
        } catch {
            // Keep merged rows from explicit/searchRead.
        }
        const rows = Array.from(mergedByName.values());
        rows.sort((left, right) => {
            const l = `${left.field_description || left.name || ""}`.toLowerCase();
            const r = `${right.field_description || right.name || ""}`.toLowerCase();
            return l.localeCompare(r);
        });
        this.requestFieldState.rows = rows;
    }

    _toPositiveInt(value) {
        const normalized = Number(value || 0);
        if (!Number.isInteger(normalized) || normalized <= 0) {
            return false;
        }
        return normalized;
    }

    _extractWorkflowContextFromProps(props = this.props) {
        const directContext = props?.context || {};
        const studioContext = this.env?.viewEditorModel?._studio?.editedAction?.context || {};
        const routeState = router?.current?.search || {};

        const workflowVersionId =
            this._toPositiveInt(props?.workflowVersionId) ||
            this._toPositiveInt(directContext.workflow_version_id) ||
            this._toPositiveInt(studioContext.workflow_version_id) ||
            this._toPositiveInt(routeState.workflow_version_id);
        const workflowCategoryId =
            this._toPositiveInt(props?.workflowCategoryId) ||
            this._toPositiveInt(directContext.workflow_category_id) ||
            this._toPositiveInt(studioContext.workflow_category_id) ||
            this._toPositiveInt(routeState.workflow_category_id);
        return {
            workflowVersionId,
            workflowCategoryId,
        };
    }

    _normalizeActivityNodeOptions(rows = [], versionLabelsById = {}) {
        const unique = new Map();
        const rawRows = Array.isArray(rows) ? rows : [];
        for (const row of rawRows) {
            const nodeId = `${row?.node_id || row?.value || ""}`.trim();
            if (!nodeId) {
                continue;
            }
            const nodeName = `${row?.name || row?.label || nodeId}`.trim();
            const versionId =
                this._toPositiveInt(Array.isArray(row?.version_id) ? row.version_id[0] : row?.version_id) ||
                false;
            const versionLabel =
                `${versionLabelsById[versionId] || (Array.isArray(row?.version_id) ? row.version_id[1] : "") || ""}`.trim();
            let label = nodeName === nodeId ? nodeId : `${nodeName} (${nodeId})`;
            if (versionLabel) {
                label = `${label} - ${versionLabel}`;
            }
            if (!unique.has(nodeId)) {
                unique.set(nodeId, {
                    value: nodeId,
                    label,
                    node_id: nodeId,
                    node_name: nodeName,
                    version_id: versionId,
                });
            }
        }
        return Array.from(unique.values());
    }

    _normalizeWorkflowActionKey(row = {}) {
        return `${row?.name || row?.action_key || row?.attr_label || row?.action_button_label || ""}`
            .trim()
            .toLowerCase();
    }

    _normalizeWorkflowActionOptions(rows = [], versionLabelsById = {}) {
        const unique = new Map();
        const rawRows = Array.isArray(rows) ? rows : [];
        for (const row of rawRows) {
            const actionKey = this._normalizeWorkflowActionKey(row);
            if (!actionKey) {
                continue;
            }
            const sourceId = `${row?.source_id || row?.source_node_id || ""}`.trim();
            const sourceName = `${row?.source_name || ""}`.trim();
            const targetName = `${row?.target_name || ""}`.trim();
            const labelText = `${row?.action_button_label || row?.attr_label || row?.name || actionKey}`.trim();
            const versionId =
                this._toPositiveInt(Array.isArray(row?.version_id) ? row.version_id[0] : row?.version_id) ||
                false;
            const versionLabel =
                `${versionLabelsById[versionId] || (Array.isArray(row?.version_id) ? row.version_id[1] : "") || ""}`.trim();
            const labelParts = [labelText];
            if (sourceName || sourceId) {
                labelParts.push(sourceName && sourceId ? `${sourceName} (${sourceId})` : sourceName || sourceId);
            }
            if (targetName) {
                labelParts.push(`to ${targetName}`);
            }
            if (versionLabel) {
                labelParts.push(versionLabel);
            }
            const uniqueKey = [versionId || "global", sourceId || "", actionKey].join(":");
            if (!unique.has(uniqueKey)) {
                unique.set(uniqueKey, {
                    value: actionKey,
                    label: labelParts.join(" - "),
                    action_key: actionKey,
                    source_id: sourceId,
                    source_name: sourceName,
                    target_id: `${row?.target_id || ""}`.trim(),
                    target_name: targetName,
                    version_id: versionId,
                });
            }
        }
        return Array.from(unique.values());
    }

    async _resolveVersionIdsForActivityOptions(workflowContext = {}, modelName = "") {
        const versionIds = new Set();
        const workflowVersionId = this._toPositiveInt(workflowContext.workflowVersionId);
        const workflowCategoryId = this._toPositiveInt(workflowContext.workflowCategoryId);
        if (workflowVersionId) {
            versionIds.add(workflowVersionId);
            return [...versionIds];
        }

        if (workflowCategoryId) {
            try {
                const [category] = await this.orm.read(
                    "workflow.approval.category",
                    [workflowCategoryId],
                    ["active_version_id"]
                );
                const activeVersionId = this._toPositiveInt(category?.active_version_id?.[0]);
                if (activeVersionId) {
                    versionIds.add(activeVersionId);
                }
            } catch {
                // Fallback to version search below.
            }
            if (!versionIds.size) {
                try {
                    const categoryVersions = await this.orm.searchRead(
                        "workflow.approval.category.version",
                        [["category_id", "=", workflowCategoryId]],
                        ["id"],
                        {order: "is_active desc, id desc", limit: 10}
                    );
                    for (const row of categoryVersions || []) {
                        const id = this._toPositiveInt(row?.id);
                        if (id) {
                            versionIds.add(id);
                        }
                    }
                } catch {
                    // Keep empty when query is unavailable.
                }
            }
            return [...versionIds];
        }

        if (!modelName) {
            return [];
        }

        let modelVersions = [];
        try {
            modelVersions = await this.orm.searchRead(
                "workflow.approval.category.version",
                [["res_model_name", "=", modelName], ["is_active", "=", true]],
                ["id"],
                {order: "id desc", limit: 20}
            );
        } catch {
            modelVersions = [];
        }
        if (!modelVersions.length) {
            try {
                modelVersions = await this.orm.searchRead(
                    "workflow.approval.category.version",
                    [["res_model_name", "=", modelName]],
                    ["id"],
                    {order: "is_active desc, id desc", limit: 20}
                );
            } catch {
                modelVersions = [];
            }
        }
        for (const row of modelVersions || []) {
            const id = this._toPositiveInt(row?.id);
            if (id) {
                versionIds.add(id);
            }
        }
        return [...versionIds];
    }

    async _ensureActivityNodeOptions(props = this.props) {
        const inlineOptions = this._normalizeActivityNodeOptions(props?.workflowMetaTaskOptions || []);
        if (inlineOptions.length) {
            this.activityNodeState.rows = inlineOptions;
            this.activityNodeState.contextKey = "inline";
            this.activityNodeState.loaded = true;
            return;
        }

        const modelName = `${props?.requestModel || props?.resModel || ""}`.trim();
        const workflowContext = this._extractWorkflowContextFromProps(props);
        const contextKey = [
            this._toPositiveInt(workflowContext.workflowVersionId) || 0,
            this._toPositiveInt(workflowContext.workflowCategoryId) || 0,
            modelName || "",
        ].join(":");
        if (this.activityNodeState.loaded && this.activityNodeState.contextKey === contextKey) {
            return;
        }
        this.activityNodeState.contextKey = contextKey;
        this.activityNodeState.loaded = true;
        this.activityNodeState.loading = true;
        this.activityNodeState.rows = [];

        try {
            const versionIds = await this._resolveVersionIdsForActivityOptions(workflowContext, modelName);
            if (!versionIds.length) {
                this.activityNodeState.rows = [];
                return;
            }
            let versionRows = [];
            try {
                versionRows = await this.orm.read("workflow.approval.category.version", versionIds, ["name"]);
            } catch {
                versionRows = [];
            }
            const versionLabelsById = {};
            for (const version of versionRows || []) {
                const versionId = this._toPositiveInt(version?.id);
                if (versionId) {
                    versionLabelsById[versionId] = `${version?.name || ""}`.trim();
                }
            }
            const metaTasks = await this.orm.searchRead(
                "workflow.category.version.meta.task",
                [["version_id", "in", versionIds], ["node_id", "!=", false]],
                ["node_id", "name", "node_type", "version_id"],
                {order: "sequence,id", limit: 500}
            );
            this.activityNodeState.rows = this._normalizeActivityNodeOptions(
                metaTasks || [],
                versionLabelsById
            );
        } catch {
            this.activityNodeState.rows = [];
        } finally {
            this.activityNodeState.loading = false;
        }
    }

    async _ensureWorkflowActionOptions(props = this.props) {
        const inlineOptions = this._normalizeWorkflowActionOptions(props?.workflowMetaActionOptions || []);
        if (inlineOptions.length) {
            this.workflowActionState.rows = inlineOptions;
            this.workflowActionState.contextKey = "inline";
            this.workflowActionState.loaded = true;
            return;
        }

        const modelName = `${props?.requestModel || props?.resModel || ""}`.trim();
        const workflowContext = this._extractWorkflowContextFromProps(props);
        const contextKey = [
            this._toPositiveInt(workflowContext.workflowVersionId) || 0,
            this._toPositiveInt(workflowContext.workflowCategoryId) || 0,
            modelName || "",
        ].join(":");
        if (this.workflowActionState.loaded && this.workflowActionState.contextKey === contextKey) {
            return;
        }
        this.workflowActionState.contextKey = contextKey;
        this.workflowActionState.loaded = true;
        this.workflowActionState.loading = true;
        this.workflowActionState.rows = [];

        try {
            const versionIds = await this._resolveVersionIdsForActivityOptions(workflowContext, modelName);
            if (!versionIds.length) {
                this.workflowActionState.rows = [];
                return;
            }
            let versionRows = [];
            try {
                versionRows = await this.orm.read("workflow.approval.category.version", versionIds, ["name"]);
            } catch {
                versionRows = [];
            }
            const versionLabelsById = {};
            for (const version of versionRows || []) {
                const versionId = this._toPositiveInt(version?.id);
                if (versionId) {
                    versionLabelsById[versionId] = `${version?.name || ""}`.trim();
                }
            }
            const actions = await this.orm.searchRead(
                "workflow.category.version.meta.task.action",
                [["version_id", "in", versionIds]],
                [
                    "name",
                    "attr_label",
                    "action_button_label",
                    "source_id",
                    "source_name",
                    "target_id",
                    "target_name",
                    "version_id",
                ],
                {order: "sequence,id", limit: 1000}
            );
            this.workflowActionState.rows = this._normalizeWorkflowActionOptions(
                actions || [],
                versionLabelsById
            );
        } catch {
            this.workflowActionState.rows = [];
        } finally {
            this.workflowActionState.loading = false;
        }
    }

    _normalizeSelectionOptions(selectionValue) {
        if (!Array.isArray(selectionValue)) {
            return [];
        }
        return selectionValue
            .map((row) => {
                if (Array.isArray(row) && row.length >= 2) {
                    const value = `${row[0] ?? ""}`;
                    const label = `${row[1] ?? row[0] ?? ""}`;
                    if (!value) {
                        return false;
                    }
                    return {value, label};
                }
                return false;
            })
            .filter(Boolean);
    }

    get allRequestFields() {
        const explicitRows = Array.isArray(this.props.requestFields) ? this.props.requestFields : [];
        const fetchedRows = Array.isArray(this.requestFieldState?.rows) ? this.requestFieldState.rows : [];
        if (fetchedRows.length) {
            return fetchedRows;
        }
        return explicitRows;
    }

    _newSimpleCondition(partial = {}) {
        const firstField = this.simpleConditionFields[0] || BASE_SIMPLE_CONDITION_FIELDS[0];
        const nextId = `cond_${++this._simpleConditionSeq}`;
        const fieldName = partial.fieldName || firstField.value;
        const fieldMeta = this.getSimpleFieldMeta(fieldName);
        const operator = partial.operator || fieldMeta.defaultOperator || "=";
        const valueType = partial.valueType || fieldMeta.type || "text";
        const inputKind = fieldMeta.inputKind || fieldMeta.type || "text";
        return {
            id: partial.id || nextId,
            fieldName,
            operator,
            value: partial.value ?? (inputKind === "boolean" ? "true" : inputKind === "x2many" ? [] : ""),
            valueType,
        };
    }

    _buildInitialSimpleConditions() {
        return [this._newSimpleCondition()];
    }

    // _resolveInitialMode(domain) {
    //     const value = (domain || "").trim();
    //     if (!value || value === "[]") {
    //         return "builder";
    //     }
    //     const isExpression = value.includes(" if ") || value.includes("actor_") || value.includes("user.");
    //     return isExpression ? "advanced" : "builder";
    // }
    _resolveInitialMode(domain) {
        const value = (domain || "").trim();
        if (!value || value === "[]") {
            return "builder";
        }

        // Standalone boolean/python helper expressions are valid for workflow
        // runtime domains, but they cannot be represented by the Simple builder.
        if (!value.startsWith("[") && !value.startsWith("(")) {
            return "advanced";
        }

        // Force Advanced for python-like expressions.
        const isExpression =
            value.includes(" if ") ||
            value.includes("env.") ||
            value.includes("user.") ||
            value.includes("record.");
        if (isExpression) {
            return "advanced";
        }

        // If the domain contains fields/operators that the simple builder can't represent,
        // force Advanced.
        //
        // Otherwise the dialog can't map it back to simple conditions, falls back to an
        // empty builder state, and when you confirm it overwrites your domain with the
        // "keep hidden" domain: [('id', '=', 0)].
        try {
            const list = Domain.fromString(value).toList();
            const supportedFields = new Set(this.simpleConditionFields.map((f) => f.value));
            const supportedOperators = new Set([
                "=",
                "!=",
                "in",
                "not in",
                "ilike",
                "not ilike",
                "=like",
                "not like",
                ">",
                ">=",
                "<",
                "<=",
            ]);

            for (const token of list) {
                if (Array.isArray(token) && token.length >= 3) {
                    const [field, op] = token;
                    if (!supportedFields.has(field) || !supportedOperators.has(op)) {
                        return "advanced";
                    }
                }
            }
        } catch (e) {
            return "advanced";
        }

        return "builder";
    }

    get dialogTitle() {
        return this.props.title || _t("Domain");
    }

    get effectiveContextType() {
        return {
            assignment_users_routing: "assignment_users",
            request_scope_routing: "request_scope",
        }[this.props.contextType || ""] || (this.props.contextType || "generic");
    }

    get emptyDomainFallback() {
        return this.props.allowBlankDomain ? "" : "[]";
    }

    get modelLabel() {
        return this.props.resModel || "";
    }

    get helperText() {
        return (
            this.props.helpText ||
            (this.effectiveContextType === "field_modifiers" ? this.workflowKindSummaryBody : "") ||
            HELP_TEXT[this.props.contextType] ||
            HELP_TEXT[this.effectiveContextType] ||
            HELP_TEXT.generic
        );
    }

    get validationRequestModel() {
        const requestModel = (this.props.requestModel || "").trim();
        if (requestModel) {
            return requestModel;
        }
        return (this.props.resModel || "").trim();
    }

    get showRuntimeVariableGuide() {
        return ["assignment_users", "request_scope", "field_modifiers"].includes(this.effectiveContextType);
    }

    get runtimeVariableRows() {
        if (!this.showRuntimeVariableGuide) {
            return [];
        }
        const contextType = this.effectiveContextType;
        const isFieldModifierScope = contextType === "field_modifiers";
        const isRequestScope = contextType === "request_scope" || isFieldModifierScope;
        const rows = [
            {
                key: "request_owner_id",
                symbol: "request_owner_id",
                meaning: _t("Request owner user ID from request data."),
                sample: isRequestScope
                    ? "[('request_owner_id', '=', uid)]"
                    : "[('id', '=', request_owner_id)]",
            },
            {
                key: "manager_user_id",
                symbol: "manager_user_id",
                meaning: _t("Creator manager user ID from request data (legacy symbol)."),
                sample: isRequestScope
                    ? "[('manager_user_id', '=', uid)]"
                    : "[('id', '=', manager_user_id)]",
            },
            {
                key: "request_creator_id",
                symbol: "request_creator_id",
                meaning: _t("Request creator user ID."),
                sample: isRequestScope
                    ? "[('create_uid', '=', request_creator_id)]"
                    : "[('id', '=', request_creator_id)]",
            },
            {
                key: "request_creator_manager_user_id",
                symbol: "request_creator_manager_user_id",
                meaning: _t("Request creator manager user ID."),
                sample: isRequestScope
                    ? "[('uid', '=', request_creator_manager_user_id)]"
                    : "[('id', '=', request_creator_manager_user_id)]",
            },
            {
                key: "uid",
                symbol: "uid",
                meaning: _t("Current actor user ID."),
                sample: isRequestScope
                    ? "[('request_owner_id', '=', uid)]"
                    : "[('id', '=', uid)]",
            },
            {
                key: "current_date",
                symbol: "current_date",
                meaning: _t("Current date when the domain is evaluated. Use for overdue automation guards."),
                sample: "[('x_expect_return_date', '<', current_date)]",
            },
            {
                key: "today_tokens",
                symbol: "\"today\", \"today +1d\", \"today -7d\"",
                meaning: _t("Odoo dynamic date strings for Date/Datetime fields."),
                sample: "[('x_expect_return_date', '=', 'today +1d')]",
            },
            {
                key: "user.id",
                symbol: "user.id",
                meaning: _t("Current actor user ID via actor user record."),
                sample: isRequestScope
                    ? "[('company_id', '=', user.company_id.id)]"
                    : "[('id', '=', user.id)]",
            },
            {
                key: "current_user.id",
                symbol: "current_user.id",
                meaning: _t("Current actor user ID via current_user alias."),
                sample: isRequestScope
                    ? "[('create_uid', '=', current_user.id)]"
                    : "[('id', '=', current_user.id)]",
            },
            {
                key: "actual_user_id",
                symbol: "actual_user_id",
                meaning: _t("User ID that initiated the action, including delegated execution."),
                sample: isRequestScope
                    ? "[('create_uid', '=', actual_user_id)]"
                    : "[('id', '=', actual_user_id)]",
            },
            {
                key: "delegated_from_user_id",
                symbol: "delegated_from_user_id",
                meaning: _t("Original delegated user ID when an action is executed on behalf of another user."),
                sample: isRequestScope
                    ? "[('request_owner_id', '=', delegated_from_user_id)]"
                    : "[('id', '=', delegated_from_user_id)]",
            },
            {
                key: "all_approver_user_ids",
                symbol: "all_approver_user_ids",
                meaning: _t("All users assigned as approvers on the request, including simulated history."),
                sample: isRequestScope
                    ? "[('request_owner_id', 'in', all_approver_user_ids)]"
                    : "[('id', 'in', all_approver_user_ids)]",
            },
            {
                key: "decided_approver_user_ids",
                symbol: "decided_approver_user_ids",
                meaning: _t("Approver users who already made a decision on this request."),
                sample: isRequestScope
                    ? "[('request_owner_id', 'in', decided_approver_user_ids)]"
                    : "[('id', 'in', decided_approver_user_ids)]",
            },
            {
                key: "pending_approver_user_ids",
                symbol: "pending_approver_user_ids",
                meaning: _t("Approver users currently in new, pending, or waiting status."),
                sample: isRequestScope
                    ? "[('request_owner_id', 'in', pending_approver_user_ids)]"
                    : "[('id', 'in', pending_approver_user_ids)]",
            },
            {
                key: "node_pending_approver_user_ids_fn",
                symbol: "node_pending_approver_user_ids('Task_HOD')",
                meaning: _t("Pending approver user IDs for one workflow node."),
                sample: isRequestScope
                    ? "[('request_owner_id', 'in', node_pending_approver_user_ids('Task_HOD'))]"
                    : "[('id', 'in', node_pending_approver_user_ids('Task_HOD'))]",
            },
            {
                key: "wf_action_key",
                symbol: "wf_action_key",
                meaning: _t("Normalized workflow action key currently being evaluated."),
                sample: "[('wf_action_key', '=', 'approve')]",
            },
            {
                key: "wf_current_node_id",
                symbol: "wf_current_node_id",
                meaning: _t("Current workflow activity node ID."),
                sample: "[('wf_current_node_id', 'in', ['Task_Submission', 'Task_HOD'])]",
            },
            {
                key: "current_node_id",
                symbol: "current_node_id",
                meaning: _t("Alias of current workflow activity node ID."),
                sample: "[('current_node_id', '=', 'Task_HOD')]",
            },
            {
                key: "wf_current_stage_age_minutes",
                symbol: "wf_current_stage_age_minutes",
                meaning: _t(
                    "Live age in minutes for the current actor/current workflow stage. " +
                    "Use this for simple single-stage rules."
                ),
                sample: "[('wf_current_stage_age_minutes', '>=', 1440)]",
            },
            {
                key: "wf_active_node_ids",
                symbol: "wf_active_node_ids",
                meaning: _t("List of active workflow node IDs, including active parallel branches."),
                sample: "[('wf_active_node_ids', 'in', ['Task_HOD'])]",
            },
            {
                key: "wf_has_active_node_fn",
                symbol: "wf_has_active_node('Task_HOD')",
                meaning: _t(
                    "Advanced helper. True when the selected BPMN node is currently active. " +
                    "Use this for parallel flows."
                ),
                sample: "wf_has_active_node('Task_HOD')",
            },
            {
                key: "wf_node_age_minutes_fn",
                symbol: "wf_node_age_minutes('Task_HOD')",
                meaning: _t(
                    "Advanced helper. Live stage age in minutes for a specific active BPMN node. " +
                    "Returns 0 when that node is not active."
                ),
                sample: "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 1440",
            },
            {
                key: "wf_oldest_active_stage_age_minutes",
                symbol: "wf_oldest_active_stage_age_minutes",
                meaning: _t("Oldest live age in minutes across all active workflow nodes."),
                sample: "[('wf_oldest_active_stage_age_minutes', '>=', 10080)]",
            },
            {
                key: "wf_youngest_active_stage_age_minutes",
                symbol: "wf_youngest_active_stage_age_minutes",
                meaning: _t("Youngest live age in minutes across all active workflow nodes."),
                sample: "[('wf_youngest_active_stage_age_minutes', '>=', 60)]",
            },
            {
                key: "current_meta_task_id",
                symbol: "current_meta_task_id",
                meaning: _t("Current meta task database ID when available."),
                sample: "[('current_meta_task_id', '!=', False)]",
            },
            {
                key: "request_owner_manager_user_id",
                symbol: "request_owner_manager_user_id",
                meaning: _t("Request owner's manager user ID (helper symbol)."),
                sample: isRequestScope
                    ? "[('uid', '=', request_owner_manager_user_id)]"
                    : "[('id', '=', request_owner_manager_user_id)]",
            },
            {
                key: "request_owner_line_manager_user_id",
                symbol: "request_owner_line_manager_user_id",
                meaning: _t("Request owner's direct line manager user ID."),
                sample: isRequestScope
                    ? "[('uid', '=', request_owner_line_manager_user_id)]"
                    : "[('id', '=', request_owner_line_manager_user_id)]",
            },
            {
                key: "request_owner_department_manager_user_id",
                symbol: "request_owner_department_manager_user_id",
                meaning: _t("Request owner's department manager user ID."),
                sample: isRequestScope
                    ? "[('uid', '=', request_owner_department_manager_user_id)]"
                    : "[('id', '=', request_owner_department_manager_user_id)]",
            },
            {
                key: "request_owner_manager_chain_user_ids",
                symbol: "request_owner_manager_chain_user_ids",
                meaning: _t("List of all manager user IDs in request owner's reporting chain."),
                sample: isRequestScope
                    ? "[('uid', 'in', request_owner_manager_chain_user_ids)]"
                    : "[('id', 'in', request_owner_manager_chain_user_ids)]",
            },
            {
                key: "request_owner_team_code",
                symbol: "request_owner_team_code",
                meaning: _t("Request owner employee team code."),
                sample:
                    "[('employee_ids.x_team_code', '!=', False), ('employee_ids.x_team_code', '=', request_owner_team_code)]",
            },
            {
                key: "request_owner_line_code",
                symbol: "request_owner_line_code",
                meaning: _t("Request owner employee line code."),
                sample:
                    "[('employee_ids.x_line_code', '!=', False), ('employee_ids.x_line_code', '=', request_owner_line_code)]",
            },
            {
                key: "request_owner_manager_path",
                symbol: "request.request_owner_id.employee_id.parent_id.user_id.id",
                meaning: _t("Legacy deep object path (avoid for new configs)."),
                sample: isRequestScope
                    ? "[('uid', '=', request.request_owner_id.employee_id.parent_id.user_id.id)]"
                    : "[('id', '=', request.request_owner_id.employee_id.parent_id.user_id.id)]",
            },
            {
                key: "user_id_alias",
                symbol: "user_id",
                meaning: _t("Alias supported for backward compatibility (mapped to id)."),
                sample: "[('user_id', '=', request_owner_id)]",
            },
        ];

        // Actor helper functions are available in request-scope and field-rule domains
        // (invisible_domain, action execution domain, auto_action_condition, workflow policies).
        // These are evaluated at runtime against the current acting user.
        if (isRequestScope) {
            rows.push(
                {
                    key: "actor_has_group_legacy_fn",
                    symbol: "actor_has_group('xml.group.id')",
                    meaning: _t(
                        "Legacy helper shortcut. Prefer [('wf_actor_group_ids', 'in', [group_id])] " +
                        "for standard request-scope list-domain syntax."
                    ),
                    sample: "[('wf_actor_group_ids', 'in', [3])]",
                },
                {
                    key: "is_manager_of_requester",
                    symbol: "is_manager_of_requester",
                    meaning: _t(
                        "Legacy helper shortcut. Prefer [('uid', '=', request_owner_manager_user_id)] " +
                        "or [('wf_actor_is_manager', '=', True)] for standard list-domain syntax."
                    ),
                    sample: "is_manager_of_requester",
                },
                {
                    key: "wf_actor_is_manager",
                    symbol: "wf_actor_is_manager",
                    meaning: _t("Boolean flag — True when actor is the request owner's manager (same as is_manager_of_requester)."),
                    sample: "[('wf_actor_is_manager', '=', True)]",
                },
                {
                    key: "wf_actor_is_hod",
                    symbol: "wf_actor_is_hod",
                    meaning: _t("True when the actor's position is HOD or Head of Department."),
                    sample: "[('wf_actor_is_hod', '=', True)]",
                },
                {
                    key: "wf_actor_login",
                    symbol: "wf_actor_login",
                    meaning: _t("Lowercase login of the current workflow actor."),
                    sample: "[('wf_actor_login', '=', 'hod.user')]",
                },
                {
                    key: "wf_actor_department_name",
                    symbol: "wf_actor_department_name",
                    meaning: _t("Lowercase HR department name of the current workflow actor."),
                    sample: "[('wf_actor_department_name', 'ilike', 'financial')]",
                },
                {
                    key: "actor_in_department_fn",
                    symbol: "actor_in_department('Dept Name')",
                    meaning: _t(
                        "True when the acting user's HR department name matches (case-insensitive). " +
                        "Use in Advanced mode."
                    ),
                    sample: "actor_in_department('IT Department')",
                },
                {
                    key: "actor_in_position_fn",
                    symbol: "actor_in_position('Job Title')",
                    meaning: _t(
                        "True when the acting user's job position name matches (case-insensitive). " +
                        "Use in Advanced mode."
                    ),
                    sample: "actor_in_position('Head of Department')",
                },
                {
                    key: "wf_actor_group_ids",
                    symbol: "wf_actor_group_ids",
                    meaning: _t(
                        "List of Odoo res.groups IDs the acting user belongs to. " +
                        "Preferred clean syntax when you want domains aligned with actual group records."
                    ),
                    sample: "[('wf_actor_group_ids', 'in', [3])]",
                },
                {
                    key: "wf_actor_group_xmlids",
                    symbol: "wf_actor_group_xmlids",
                    meaning: _t(
                        "Comma-delimited string of all group XML IDs the actor belongs to. " +
                        "Legacy compatibility form. Prefer wf_actor_group_ids for new configuration."
                    ),
                    sample: "[('wf_actor_group_xmlids', 'ilike', ',workflow_engine.group_workflow_approval_admin,')]",
                },
                {
                    key: "actor_has_group_fn",
                    symbol: "[('wf_actor_group_ids', 'in', [group_id])]",
                    meaning: _t(
                        "Standard Odoo-domain tuple syntax for Odoo security-group membership by res.groups record ID. " +
                        "Recommended for Button Visibility and request-scope domains."
                    ),
                    sample: "[('wf_actor_group_ids', 'in', [3])]",
                },
                {
                    key: "wf_actor_approval_group_ids",
                    symbol: "wf_actor_approval_group_ids",
                    meaning: _t(
                        "List of workflow approval-group IDs the actor belongs to. " +
                        "Preferred clean syntax for workflow approval-group membership."
                    ),
                    sample: "[('wf_actor_approval_group_ids', 'in', [12])]",
                },
                {
                    key: "actor_has_approval_group_fn",
                    symbol: "[('wf_actor_approval_group_ids', 'in', [12])]",
                    meaning: _t(
                        "Standard Odoo-domain tuple syntax for workflow approval-group membership. " +
                        "Recommended for Button Visibility and request-scope domains."
                    ),
                    sample: "[('wf_actor_approval_group_ids', 'in', [12])]",
                },
                {
                    key: "snapshot_field_hint",
                    symbol: "[('x_field', 'op', value)]  ← live form",
                    meaning: isFieldModifierScope
                        ? _t(
                            "For Workflow Field Rules: domain fields are read from the request form snapshot. " +
                            "The field state updates from workflow runtime policy evaluation. " +
                            "Supports =, !=, >, >=, <, <=, in, not in, ilike operators."
                        )
                        : _t(
                            "For Button Visibility: domain fields are read from the unsaved form snapshot. " +
                            "The button shows/hides on onChange without requiring a save. " +
                            "Supports =, !=, >, >=, <, <=, in, not in, ilike operators."
                        ),
                    sample: "[('x_amount', '>', 200)]",
                }
            );
        }

        const requestFields = (this.allRequestFields || [])
            .filter((field) => field?.name)
            .slice(0, 10)
            .map((field) => ({
                key: `field_${field.name}`,
                symbol: field.name,
                meaning: `${field.field_description || field.name} (${field.ttype || "field"})`,
                sample: false,
            }));
        return [...rows, ...requestFields].map((row) => ({
            ...row,
            category: this._runtimeReferenceCategory(row),
            recommended: RUNTIME_REFERENCE_RECOMMENDED_KEYS.has(row.key),
        }));
    }

    _runtimeReferenceCategory(row = {}) {
        const key = `${row.key || ""}`.toLowerCase();
        const symbol = `${row.symbol || ""}`.toLowerCase();
        if (key.startsWith("field_")) {
            return "request_fields";
        }
        if (key.includes("approver")) {
            return "approvals";
        }
        if (key.includes("actor") || symbol.includes("actor_")) {
            return "actor";
        }
        if (key.includes("date") || key.includes("today") || key.includes("now")) {
            return "dates";
        }
        if (key.endsWith("_fn") || symbol.includes("(")) {
            return "helpers";
        }
        if (
            key.includes("node")
            || key.includes("stage")
            || key.includes("action_key")
            || key.includes("meta_task")
        ) {
            return "workflow";
        }
        if (
            key.includes("owner")
            || key.includes("creator")
            || key.includes("manager")
            || key.includes("user")
            || key === "uid"
        ) {
            return "people";
        }
        return "other";
    }

    get runtimeReferenceCategoryOptions() {
        return [
            {value: "recommended", label: _t("Recommended")},
            {value: "all", label: _t("All Symbols")},
            {value: "people", label: _t("People & Managers")},
            {value: "approvals", label: _t("Approval History")},
            {value: "workflow", label: _t("Workflow State")},
            {value: "actor", label: _t("Current Actor")},
            {value: "dates", label: _t("Dates & Time")},
            {value: "request_fields", label: _t("Request Fields")},
            {value: "helpers", label: _t("Advanced Helpers")},
        ];
    }

    get runtimeReferenceCategorySelectProps() {
        return {
            choices: this.runtimeReferenceCategoryOptions,
            value: this.state.runtimeReferenceCategory || "recommended",
            onSelect: (value) => {
                this.state.runtimeReferenceCategory = value || "recommended";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_reference_category",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    get runtimeReferenceRows() {
        const category = this.state.runtimeReferenceCategory || "recommended";
        const query = `${this.state.runtimeReferenceQuery || ""}`.trim().toLowerCase();
        return this.runtimeVariableRows.filter((row) => {
            const categoryMatches = category === "all"
                || (category === "recommended" ? row.recommended : row.category === category);
            if (!categoryMatches) {
                return false;
            }
            if (!query) {
                return true;
            }
            const haystack = `${row.symbol || ""} ${row.meaning || ""} ${row.sample || ""}`.toLowerCase();
            return haystack.includes(query);
        });
    }

    get runtimeReferenceCountLabel() {
        return `${this.runtimeReferenceRows.length} of ${this.runtimeVariableRows.length} ${_t("symbols")}`;
    }

    onRuntimeReferenceSearchInput(event) {
        this.state.runtimeReferenceQuery = event?.target?.value || "";
    }

    onBrowseRuntimeReference() {
        this.dialog.add(WorkflowStudioRuntimeReferenceDialog, {
            rows: this.runtimeVariableRows,
            categoryOptions: this.runtimeReferenceCategoryOptions,
            referenceState: this.state,
            showRuntimePathBuilder: this.showRuntimePathBuilder,
            openRuntimeBuilder: () => this.openRuntimeBuilderModal(),
        });
    }

    get showRuntimePathBuilder() {
        return this.showRuntimeVariableGuide;
    }

    get runtimeObjectOptions() {
        return [
            {value: "request", label: _t("Request Object")},
            {value: "user", label: _t("Actor User Object")},
            {value: "current_user", label: _t("Current User Alias")},
            {value: "actual_user", label: _t("Actual User (Delegation)")},
            {value: "delegated_from_user", label: _t("Delegated From User")},
            {value: "employee", label: _t("Actor Employee")},
            {value: "department", label: _t("Actor Department")},
            {value: "company", label: _t("Request Company")},
            {value: "uid", label: _t("uid Symbol")},
        ];
    }

    _normalizeRuntimePath(path) {
        return `${path || ""}`.trim().replace(/^\.+/, "");
    }

    _deduplicateRuntimePaths(rows = []) {
        const seen = new Set();
        const ordered = [];
        for (const row of rows) {
            const key = `${row?.value || ""}`.trim();
            if (!key || seen.has(key)) {
                continue;
            }
            seen.add(key);
            ordered.push(row);
        }
        return ordered;
    }

    _requestRuntimePathOptions() {
        const staticRows = [
            {value: "request_owner_id.id", label: _t("Request owner user ID")},
            {value: "request_owner_id.employee_id.id", label: _t("Request owner employee")},
            {
                value: "request_owner_id.employee_id.parent_id.user_id.id",
                label: _t("Request owner manager user"),
            },
            {
                value: "request_owner_id.employee_id.manager_id.user_id.id",
                label: _t("Request owner manager user (custom manager_id)"),
            },
            {
                value: "request_owner_id.employee_id.department_id.id",
                label: _t("Request owner department"),
            },
            {value: "manager_id.user_id.id", label: _t("Manager user")},
            {value: "manager_user_id.id", label: _t("Manager user ID")},
            {value: "create_uid.id", label: _t("Created by user")},
        ];
        const requestFieldRows = (this.allRequestFields || [])
            .filter((field) => !!field?.name)
            .map((field) => {
                const label = field.field_description || field.name;
                const base = {
                    value: field.name,
                    label: `${label} (${field.ttype || "field"})`,
                };
                if (field.ttype === "many2one") {
                    return [
                        base,
                        {
                            value: `${field.name}.id`,
                            label: `${label} -> ID`,
                        },
                    ];
                }
                return [base];
            })
            .flat();
        return this._deduplicateRuntimePaths([...staticRows, ...requestFieldRows]);
    }

    _userRuntimePathOptions(objectKey = "user") {
        const rows = [
            {value: "id", label: _t("User ID")},
            {value: "login", label: _t("Login")},
            {value: "name", label: _t("Display Name")},
            {value: "company_id", label: _t("Company ID")},
            {value: "department_id", label: _t("Department ID")},
            {value: "group_ids", label: _t("Odoo Group IDs")},
            {value: "group_xmlids", label: _t("Odoo Group XML IDs")},
        ];
        if (objectKey !== "delegated_from_user") {
            rows.push({value: "manager_id", label: _t("Manager User ID")});
        }
        if (objectKey !== "actual_user") {
            rows.push({value: "approval_group_ids", label: _t("Workflow Approval Group IDs")});
        }
        if (objectKey === "user") {
            rows.push({value: "position_name", label: _t("Job Position Name")});
        }
        return this._deduplicateRuntimePaths(rows);
    }

    _employeeRuntimePathOptions() {
        return [
            {value: "id", label: _t("Employee ID")},
            {value: "department_id", label: _t("Department ID")},
            {value: "job_id", label: _t("Job Position ID")},
            {value: "manager_id", label: _t("Manager Employee ID")},
        ];
    }

    _namedRuntimePathOptions(recordLabel) {
        return [
            {value: "id", label: `${recordLabel} ${_t("ID")}`},
            {value: "name", label: `${recordLabel} ${_t("Name")}`},
        ];
    }

    get runtimePathOptions() {
        const obj = this.state.runtimeObject || "request";
        let options = [];
        if (obj === "request") {
            options = this._requestRuntimePathOptions();
        } else if (["user", "current_user", "actual_user", "delegated_from_user"].includes(obj)) {
            options = this._userRuntimePathOptions(obj);
        } else if (obj === "employee") {
            options = this._employeeRuntimePathOptions();
        } else if (obj === "department") {
            options = this._namedRuntimePathOptions(_t("Department"));
        } else if (obj === "company") {
            options = this._namedRuntimePathOptions(_t("Company"));
        } else {
            options = [];
        }
        const currentPath = this._normalizeRuntimePath(this.state.runtimePath);
        if (currentPath && !options.some((option) => option.value === currentPath)) {
            options = [
                {
                    value: currentPath,
                    label: `${_t("Custom")}: ${currentPath}`,
                },
                ...options,
            ];
        }
        return options;
    }

    get runtimeObjectSelectProps() {
        return {
            choices: this.runtimeObjectOptions,
            value: this.state.runtimeObject || "request",
            onSelect: (value) => this.onRuntimeObjectSelect(value),
            searchable: false,
            autoSort: false,
            placeholder: _t("Select object"),
            class: "o_wfs_runtime_value_select",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    get runtimeFieldSelectorModel() {
        return this.validationRequestModel || this.props.resModel || "workflow.base.approval.request";
    }

    get showRuntimeFieldSelector() {
        return this.state.runtimeObject !== "uid";
    }

    get showRuntimeModelFieldSelector() {
        return this.state.runtimeObject === "request";
    }

    get runtimeFieldSelectorProps() {
        return {
            resModel: this.runtimeFieldSelectorModel,
            path: this.state.runtimePath || "",
            readonly: false,
            allowEmpty: true,
            showSearchInput: true,
            isDebugMode: true,
            showDebugInput: true,
            update: (path) => this.onRuntimePathSelect(path),
            filter: (fieldDef) => fieldDef.type !== "json" && fieldDef.type !== "separator",
        };
    }

    get runtimeTargetFieldSelectorModel() {
        return `${this.props.resModel || this.validationRequestModel || ""}`.trim();
    }

    get runtimeTargetFieldLabel() {
        return `${this.props.resModel || ""}`.trim() === "res.users"
            ? _t("Compare User Field")
            : _t("Compare Field");
    }

    get runtimeTargetFieldHelp() {
        return `${this.props.resModel || ""}`.trim() === "res.users"
            ? _t("Usually id when filtering users or recipients.")
            : _t("Choose the field on the current record that should be compared to the dynamic value.");
    }

    get runtimeTargetFieldPlaceholder() {
        return `${this.props.resModel || ""}`.trim() === "res.users"
            ? _t("id")
            : _t("Select a field");
    }

    get runtimeTargetFieldSelectorProps() {
        return {
            resModel: this.runtimeTargetFieldSelectorModel,
            path: this.state.runtimeTargetField || "",
            readonly: false,
            allowEmpty: true,
            showSearchInput: true,
            isDebugMode: true,
            showDebugInput: true,
            update: (path) => this.onRuntimeTargetFieldSelect(path),
            filter: (fieldDef) => fieldDef.type !== "json" && fieldDef.type !== "separator",
        };
    }

    get canApplyRuntimeClause() {
        return Boolean(`${this.runtimeClauseTemplate || ""}`.trim());
    }

    get runtimePathSelectProps() {
        return {
            choices: this.runtimePathOptions,
            value: this.state.runtimePath || "",
            onSelect: (value) => this.onRuntimePathSelect(value),
            searchable: true,
            autoSort: false,
            placeholder: _t("Search or select a field path"),
            searchPlaceholder: _t("Search field paths..."),
            class: "o_wfs_runtime_value_select o_wfs_runtime_path_select",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    get runtimeOperatorSelectProps() {
        return {
            choices: this.runtimeOperatorOptions,
            value: this.state.runtimeOperator || "=",
            onSelect: (value) => this.onRuntimeOperatorSelect(value),
            searchable: false,
            autoSort: false,
            placeholder: _t("Select operator"),
            class: "o_wfs_runtime_value_select",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    onRuntimeObjectChange(event) {
        this.onRuntimeObjectSelect(event?.target?.value || "request");
    }

    onRuntimeObjectSelect(value) {
        this.state.runtimeObject = value || "request";
        this.state.runtimePath = "";
    }

    onRuntimePathChange(event) {
        this.state.runtimePath = this._normalizeRuntimePath(event?.target?.value || "");
    }

    onRuntimePathSelect(value) {
        this.state.runtimePath = this._normalizeRuntimePath(value || "");
    }

    onRuntimeTargetFieldChange(event) {
        this.state.runtimeTargetField = this._normalizeRuntimePath(event?.target?.value || "");
    }

    onRuntimeTargetFieldSelect(value) {
        this.state.runtimeTargetField = this._normalizeRuntimePath(value || "");
    }

    onRuntimeOperatorChange(event) {
        this.onRuntimeOperatorSelect(event?.target?.value || "=");
    }

    onRuntimeOperatorSelect(value) {
        this.state.runtimeOperator = value || "=";
    }

    openRuntimeBuilderModal() {
        this.state.showRuntimeBuilderModal = true;
    }

    closeRuntimeBuilderModal() {
        this.state.showRuntimeBuilderModal = false;
    }

    get runtimeOperatorOptions() {
        return RUNTIME_VALUE_OPERATORS;
    }

    get runtimeOperatorUsesValue() {
        return !RUNTIME_VALUE_PRESENCE_OPERATORS.has(
            `${this.state.runtimeOperator || ""}`.trim()
        );
    }

    get runtimeValueExpression() {
        const objectKey = this.state.runtimeObject || "request";
        const path = this._normalizeRuntimePath(this.state.runtimePath);
        if (objectKey === "uid") {
            return "uid";
        }
        return path ? `${objectKey}.${path}` : objectKey;
    }

    get runtimeClauseTemplate() {
        return buildWorkflowRuntimeClause({
            fieldName: this.state.runtimeTargetField,
            operator: this.state.runtimeOperator,
            valueExpression: this.runtimeValueExpression,
        });
    }

    applyRuntimeClauseTemplate(mode = "replace") {
        const clause = this.runtimeClauseTemplate;
        if (!clause) {
            this.notification.add(_t("Select a compare field before generating a clause."), {
                type: "warning",
            });
            return;
        }
        if (mode === "and" || mode === "or") {
            this.state.domain = this._combineDomainExpressions(this.state.domain, clause, mode);
        } else {
            this.state.domain = clause;
        }
        this.state.mode = "advanced";
        this.state.validationError = "";
        this.closeRuntimeBuilderModal();
    }

    insertRuntimeValueToken() {
        const token = this.runtimeValueExpression;
        if (!token) {
            return;
        }
        this.state.mode = "advanced";
        const current = (this.state.domain || "").trim();
        if (!current || current === "[]") {
            this.state.domain = token;
        } else {
            this.state.domain = `${current} ${token}`;
        }
        this.state.validationError = "";
        this.closeRuntimeBuilderModal();
    }

    get lineMatchRelationOptions() {
        return (this.allRequestFields || [])
            .filter((field) => ["one2many", "many2many"].includes(`${field?.ttype || field?.type || ""}`.trim().toLowerCase()))
            .filter((field) => `${field?.name || ""}`.trim() && `${field?.relation || ""}`.trim())
            .map((field) => {
                const name = `${field.name}`.trim();
                const label = `${field.field_description || field.string || field.label || name}`.trim();
                return {
                    value: name,
                    label: `${label} (${name})`,
                    displayLabel: label,
                    relation: `${field.relation || ""}`.trim(),
                };
            });
    }

    get showLineItemsMatchBuilder() {
        return this.showRuntimeVariableGuide && this.lineMatchRelationOptions.length > 0;
    }

    get lineMatchRelation() {
        const current = `${this.state.lineMatchRelation || ""}`.trim();
        if (current && this.lineMatchRelationOptions.some((option) => option.value === current)) {
            return current;
        }
        return this.lineMatchRelationOptions[0]?.value || "";
    }

    get lineMatchRelationMeta() {
        return this.lineMatchRelationOptions.find((option) => option.value === this.lineMatchRelation) || {};
    }

    get lineMatchRelationSelectProps() {
        return {
            choices: this.lineMatchRelationOptions,
            value: this.lineMatchRelation,
            onSelect: (value) => this.onLineMatchRelationSelect(value),
            searchable: true,
            autoSort: false,
            placeholder: _t("Select line field"),
            searchPlaceholder: _t("Search line fields..."),
            class: "o_wfs_runtime_value_select",
            togglerClass: "form-select o_wfs_runtime_value_select_toggler",
        };
    }

    get lineMatchModeSelectProps() {
        return {
            choices: LINE_MATCH_MODE_OPTIONS,
            value: this.state.lineMatchMode || "any",
            onSelect: (value) => this.onLineMatchModeSelect(value),
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_value_select",
            togglerClass: "form-select o_wfs_runtime_value_select_toggler",
        };
    }

    get lineMatchOperatorSelectProps() {
        return {
            choices: LINE_MATCH_OPERATORS,
            value: this.state.lineMatchOperator || "ilike",
            onSelect: (value) => this.onLineMatchOperatorSelect(value),
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_value_select",
            togglerClass: "form-select o_wfs_runtime_value_select_toggler",
        };
    }

    get lineMatchFieldSelectorProps() {
        return {
            resModel: this.lineMatchRelationMeta.relation || "",
            path: this.state.lineMatchPath || "",
            readonly: false,
            allowEmpty: true,
            showSearchInput: true,
            isDebugMode: true,
            showDebugInput: false,
            update: (path) => this.onLineMatchPathSelect(path),
            filter: (fieldDef) => fieldDef.type !== "json" && fieldDef.type !== "separator",
        };
    }

    get canApplyLineMatchExpression() {
        return Boolean(this.lineMatchExpression);
    }

    get lineMatchUsesFieldCondition() {
        return !["has_lines", "no_lines"].includes(this.state.lineMatchMode || "any");
    }

    get lineMatchNeedsValue() {
        return this.lineMatchUsesFieldCondition &&
            !["is_set", "is_not_set"].includes(this.state.lineMatchOperator || "");
    }

    _lineMatchValueLiteral() {
        const raw = `${this.state.lineMatchValue ?? ""}`.trim();
        const operator = `${this.state.lineMatchOperator || ""}`.trim().toLowerCase();
        if (operator === "in" || operator === "not in") {
            const values = raw
                .split(",")
                .map((value) => value.trim())
                .filter(Boolean);
            if (!values.length) {
                return "";
            }
            return `[${values.map((value) => JSON.stringify(value)).join(", ")}]`;
        }
        if (!raw) {
            return "";
        }
        const numeric = Number(raw);
        if (Number.isFinite(numeric) && /^-?\d+(\.\d+)?$/.test(raw)) {
            return `${numeric}`;
        }
        return JSON.stringify(raw);
    }

    get lineMatchExpression() {
        const relation = this.lineMatchRelation;
        const path = this._normalizeRuntimePath(this.state.lineMatchPath || "");
        const operator = `${this.state.lineMatchOperator || ""}`.trim() || "=";
        const valueLiteral = this.lineMatchNeedsValue ? this._lineMatchValueLiteral() : "";
        return buildWorkflowLineMatchExpression({
            relation,
            mode: this.state.lineMatchMode || "any",
            path,
            operator,
            valueLiteral,
        });
    }

    onLineMatchRelationSelect(value) {
        this.state.lineMatchRelation = `${value || ""}`.trim();
        this.state.lineMatchPath = "";
        this.state.validationError = "";
    }

    onLineMatchModeSelect(value) {
        this.state.lineMatchMode = ["any", "all", "has_lines", "no_lines"].includes(value)
            ? value
            : "any";
        this.state.validationError = "";
    }

    onLineMatchPathSelect(value) {
        this.state.lineMatchPath = this._normalizeRuntimePath(value || "");
        this.state.validationError = "";
    }

    onLineMatchPathChange(event) {
        this.state.lineMatchPath = this._normalizeRuntimePath(event?.target?.value || "");
        this.state.validationError = "";
    }

    onLineMatchOperatorSelect(value) {
        this.state.lineMatchOperator = value || "ilike";
        this.state.validationError = "";
    }

    onLineMatchValueChange(event) {
        this.state.lineMatchValue = event?.target?.value ?? "";
        this.state.validationError = "";
    }

    applyLineMatchExpression(mode = "and") {
        const expression = this.lineMatchExpression;
        if (!expression) {
            this.notification.add(_t("Select a line field and complete the selected line check first."), {
                type: "warning",
            });
            return;
        }
        if (mode === "replace") {
            this.state.domain = expression;
        } else {
            this.state.domain = this._combineDomainExpressions(this.state.domain, expression, mode === "or" ? "or" : "and");
        }
        this.state.mode = "advanced";
        this.state.validationError = "";
    }

    get showWorkflowKindSummary() {
        return this.props.contextType === "field_modifiers";
    }

    get workflowKindSummaryTitle() {
        if (this.effectiveDomainKind === "readonly") {
            return _t("Readonly Rule");
        }
        if (this.effectiveDomainKind === "required") {
            return _t("Required Rule");
        }
        return _t("Visible Rule");
    }

    get workflowKindSummaryBody() {
        if (this.effectiveDomainKind === "readonly") {
            return _t(
                "When this condition matches, the field is visible but locked from editing. This rule is evaluated without workflow action context."
            );
        }
        if (this.effectiveDomainKind === "required") {
            return _t(
                "When this condition matches, the field must be filled before the workflow action can proceed. Required rules may depend on wf_action_key, unless workflow visibility or readonly rules make the field hidden or locked."
            );
        }
        return _t(
            "When this condition matches, the field is shown on the workflow request form. This rule is evaluated without workflow action context."
        );
    }

    get availablePresets() {
        if (this.props.presets?.length) {
            return this.props.presets;
        }
        if (this.effectiveContextType === "field_modifiers") {
            return FIELD_MODIFIER_PRESETS_BY_KIND[this.effectiveDomainKind] || FIELD_MODIFIER_PRESETS_BY_KIND.visible;
        }
        return PRESETS[this.props.contextType] || PRESETS.generic;
    }

    get hasDomainExpression() {
        return !this._isEmptyDomainExpression(this.state.domain);
    }

    get presetApplyModeLabel() {
        if (!this.hasDomainExpression || this.state.presetApplyMode === "replace") {
            return _t("clicking a preset will replace the expression.");
        }
        if (this.state.presetApplyMode === "or") {
            return _t("clicking a preset will combine it with OR.");
        }
        return _t("clicking a preset will combine it with AND.");
    }

    get domainSelectorProps() {
        return {
            className: this.props.className,
            resModel: this.validationRequestModel,
            readonly: this.props.readonly,
            isDebugMode: this.props.isDebugMode,
            defaultConnector: this.props.defaultConnector,
            domain: this.state.domain,
            update: (domain) => {
                this.state.domain = this._normalizeDomainInput(domain);
                this.state.validationError = "";
            },
        };
    }

    _normalizeDomainInput(domainValue) {
        const stripInvisibleChars = (value) =>
            `${value || ""}`.replace(/[\u200B-\u200D\uFEFF]/g, "").trim();
        const normalizeLegacyActorMembership = (input) => {
            const text = stripInvisibleChars(input);
            if (!text) {
                return text;
            }
            const exactGroup = text.match(/^actor_has_group\(\s*(['"])([^'"]+)\1\s*\)$/);
            if (exactGroup) {
                return `[('wf_actor_group_xmlids', 'ilike', ${JSON.stringify(`,${exactGroup[2]},`)})]`;
            }
            const exactApprovalGroup = text.match(/^actor_has_approval_group\(\s*(\d+)\s*\)$/);
            if (exactApprovalGroup) {
                return `[('wf_actor_approval_group_ids', 'in', [${exactApprovalGroup[1]}])]`;
            }
            const combined = text.match(
                /^actor_has_group\(\s*(['"])([^'"]+)\1\s*\)\s*(and|or)\s*actor_has_approval_group\(\s*(\d+)\s*\)$/i
            );
            if (combined) {
                const operator = combined[3].toLowerCase() === "and" ? "&" : "|";
                const groupClause = `('wf_actor_group_xmlids', 'ilike', ${JSON.stringify(`,${combined[2]},`)})`;
                const approvalGroupClause = `('wf_actor_approval_group_ids', 'in', [${combined[4]}])`;
                return `['${operator}', ${groupClause}, ${approvalGroupClause}]`;
            }
            return text;
        };
        if (typeof domainValue === "string") {
            return normalizeLegacyActorMembership(stripInvisibleChars(domainValue));
        }
        if (Array.isArray(domainValue)) {
            try {
                // Preserve explicit operator structure (including OR/AND chains) from builder input.
                return JSON.stringify(domainValue);
            } catch {
                try {
                    return new Domain(domainValue).toString();
                } catch {
                    return "[]";
                }
            }
        }
        if (domainValue && typeof domainValue === "object") {
            const candidateArray =
                (Array.isArray(domainValue.domain) && domainValue.domain) ||
                (Array.isArray(domainValue.ast) && domainValue.ast) ||
                (Array.isArray(domainValue.value) && domainValue.value) ||
                false;
            if (candidateArray) {
                try {
                    return JSON.stringify(candidateArray);
                } catch {
                    // fall through to Domain parser
                }
            }
            try {
                return new Domain(domainValue).toString();
            } catch {
                try {
                    return JSON.stringify(domainValue);
                } catch {
                    return "[]";
                }
            }
        }
        return "[]";
    }

    setMode(mode) {
        this.state.mode = mode;
    }

    setPresetApplyMode(mode) {
        this.state.presetApplyMode = ["and", "or", "replace"].includes(mode) ? mode : "and";
    }

    _isEmptyDomainExpression(expression) {
        const text = `${expression || ""}`.trim();
        return !text || text === "[]";
    }

    _constantDomainValue(expression) {
        const text = `${expression || ""}`.trim();
        if (text === "True" || text === "true") {
            return true;
        }
        if (text === "False" || text === "false") {
            return false;
        }
        const compact = text.replace(/\s+/g, "").replaceAll('"', "'");
        if (compact === "[(1,'=',1)]") {
            return true;
        }
        if (compact === "[(0,'=',1)]") {
            return false;
        }
        return null;
    }

    _isDomainListExpression(expression) {
        const text = `${expression || ""}`.trim();
        return text.startsWith("[") && text.endsWith("]");
    }

    _domainListBody(expression) {
        const text = `${expression || ""}`.trim();
        return this._isDomainListExpression(text) ? text.slice(1, -1).trim() : "";
    }

    _splitTopLevelDomainItems(body) {
        const items = [];
        let current = "";
        let depth = 0;
        let quote = "";
        let escaped = false;

        for (const char of `${body || ""}`) {
            if (quote) {
                current += char;
                if (escaped) {
                    escaped = false;
                } else if (char === "\\") {
                    escaped = true;
                } else if (char === quote) {
                    quote = "";
                }
                continue;
            }
            if (char === "'" || char === '"') {
                quote = char;
                current += char;
                continue;
            }
            if (char === "[" || char === "(" || char === "{") {
                depth += 1;
                current += char;
                continue;
            }
            if (char === "]" || char === ")" || char === "}") {
                depth = Math.max(depth - 1, 0);
                current += char;
                continue;
            }
            if (char === "," && depth === 0) {
                const item = current.trim();
                if (item) {
                    items.push(item);
                }
                current = "";
                continue;
            }
            current += char;
        }

        const tail = current.trim();
        if (tail) {
            items.push(tail);
        }
        return items;
    }

    _domainBodyAsPrefixItems(body) {
        const items = this._splitTopLevelDomainItems(body);
        if (items.length <= 1) {
            return items;
        }
        const first = `${items[0] || ""}`.trim();
        if (["'&'", '"&"', "'|'", '"|"', "'!'", '"!"'].includes(first)) {
            return items;
        }
        return [...Array(items.length - 1).fill("'&'"), ...items];
    }

    _combineListDomainExpressions(leftExpression, rightExpression, mode = "and") {
        const leftBody = this._domainListBody(leftExpression);
        const rightBody = this._domainListBody(rightExpression);
        if (!leftBody) {
            return rightExpression || "[]";
        }
        if (!rightBody) {
            return leftExpression || "[]";
        }
        if (mode === "or") {
            const leftItems = this._domainBodyAsPrefixItems(leftBody);
            const rightItems = this._domainBodyAsPrefixItems(rightBody);
            return `['|', ${[...leftItems, ...rightItems].join(", ")}]`;
        }
        return `[${leftBody}, ${rightBody}]`;
    }

    _combineDomainExpressions(leftExpression, rightExpression, mode = "and") {
        const left = this._normalizeDomainInput(leftExpression);
        const right = this._normalizeDomainInput(rightExpression);
        const leftConstant = this._constantDomainValue(left);
        const rightConstant = this._constantDomainValue(right);
        if (mode === "or") {
            if (leftConstant === true) {
                return left;
            }
            if (rightConstant === true) {
                return right;
            }
            if (leftConstant === false) {
                return right;
            }
            if (rightConstant === false) {
                return left;
            }
        } else {
            if (leftConstant === false) {
                return left;
            }
            if (rightConstant === false) {
                return right;
            }
            if (leftConstant === true) {
                return right;
            }
            if (rightConstant === true) {
                return left;
            }
        }
        if (this._isEmptyDomainExpression(left)) {
            return right || "[]";
        }
        if (this._isEmptyDomainExpression(right)) {
            return left || "[]";
        }
        const leftIsList = this._isDomainListExpression(left);
        const rightIsList = this._isDomainListExpression(right);
        if (leftIsList && rightIsList) {
            return this._combineListDomainExpressions(left, right, mode);
        }
        if (leftIsList || rightIsList) {
            const listExpression = leftIsList ? left : right;
            const booleanExpression = leftIsList ? right : left;
            if (mode === "or") {
                return `[] if (${booleanExpression}) else ${listExpression}`;
            }
            return `${listExpression} if (${booleanExpression}) else [('id', '=', 0)]`;
        }
        const operator = mode === "or" ? "or" : "and";
        return `(${left}) ${operator} (${right})`;
    }

    applyPreset(preset) {
        const domain = preset.domain || "[]";
        const shouldReplace =
            this.state.presetApplyMode === "replace" ||
            this._isEmptyDomainExpression(this.state.domain);
        const nextDomain = shouldReplace
            ? domain
            : this._combineDomainExpressions(
                this.state.domain,
                domain,
                this.state.presetApplyMode
            );
        this.state.domain = nextDomain;
        this.state.mode = shouldReplace ? this._resolveInitialMode(nextDomain) : "advanced";
        this.state.validationError = "";
    }

    onAdvancedInput(event) {
        this.state.domain = event.target.value;
        this.state.validationError = "";
    }

    onActorFieldChange(event) {
        this.state.actorField = event.target.value || "department";
    }

    onActorValueChange(event) {
        this.state.actorValue = event.target.value || "";
    }

    get showSimpleConditionBuilder() {
        return false;
    }

    get simpleConditionFields() {
        const requestRows = this.requestSimpleConditionFields;
        const runtimeRows = BASE_SIMPLE_CONDITION_FIELDS.filter((field) => {
            if (field.value === "wf_action_key" && this.effectiveDomainKind !== "required") {
                return false;
            }
            return true;
        });
        return [...requestRows, ...runtimeRows];
    }

    get requestSimpleConditionFields() {
        const rows = this.allRequestFields;
        const used = new Set(BASE_SIMPLE_CONDITION_FIELDS.map((field) => field.value));
        const fields = [];
        for (const row of rows) {
            const fieldName = `${row?.name || ""}`.trim();
            if (!fieldName || used.has(fieldName) || fieldName.startsWith("wf_")) {
                continue;
            }
            const ttype = `${row?.ttype || row?.type || ""}`.trim().toLowerCase();
            if (!ttype || !SIMPLE_REQUEST_ALLOWED_TYPES.has(ttype)) {
                continue;
            }
            const fieldLabel = `${row?.field_description || row?.string || row?.label || fieldName}`.trim();
            const isBoolean = ttype === "boolean";
            const selectionOptions = this._normalizeSelectionOptions(row?.selection);
            const inputKind = isBoolean
                ? "boolean"
                : ttype === "selection" && selectionOptions.length
                    ? "selection"
                    : ttype === "many2one"
                        ? "many2one"
                        : ["many2many", "one2many"].includes(ttype)
                            ? "x2many"
                        : "text";
            const defaultOperator = isBoolean
                ? "="
                : inputKind === "selection" || inputKind === "many2one"
                    ? "="
                    : inputKind === "x2many"
                        ? "in"
                    : ["char", "text", "html"].includes(ttype)
                        ? "ilike"
                        : "=";
            fields.push({
                value: fieldName,
                label: _t("Request: %s (%s)", fieldLabel, fieldName),
                type: isBoolean ? "boolean" : "text",
                dataType: ttype,
                relation: row?.relation || "",
                selectionOptions,
                inputKind,
                defaultOperator,
            });
            used.add(fieldName);
        }
        fields.sort((left, right) => {
            const l = `${left.label || ""}`.toLowerCase();
            const r = `${right.label || ""}`.toLowerCase();
            return l.localeCompare(r);
        });
        return fields;
    }

    get simpleConnectorOptions() {
        return [
            {value: "&", label: _t("Match all (AND)")},
            {value: "|", label: _t("Match any (OR)")},
        ];
    }

    get simpleConnectorSelectProps() {
        return {
            choices: this.simpleConnectorOptions,
            value: this.state.simpleConnector,
            onSelect: (value) => this.onSimpleConnectorSelect(value),
            searchable: false,
            autoSort: false,
            class: "o_wfs_dd_simple_select o_wfs_dd_connector_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleFieldSelectProps(condition) {
        return {
            choices: this.simpleConditionFields,
            value: condition?.fieldName,
            onSelect: (value) => this.onSimpleConditionFieldSelect(condition.id, value),
            searchable: true,
            autoSort: false,
            placeholder: _t("Select field"),
            searchPlaceholder: _t("Search fields..."),
            class: "o_wfs_dd_simple_select o_wfs_dd_field_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleOperatorSelectProps(condition) {
        const choices = this.getSimpleOperatorOptions(condition?.fieldName);
        const value = choices.some((choice) => choice.value === condition?.operator)
            ? condition?.operator
            : choices[0]?.value;
        return {
            choices,
            value,
            onSelect: (value) => this.onSimpleConditionOperatorSelect(condition.id, value),
            searchable: false,
            autoSort: false,
            placeholder: _t("Operator"),
            class: "o_wfs_dd_simple_select o_wfs_dd_operator_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleBooleanSelectProps(condition) {
        return {
            choices: [
                {value: "true", label: _t("True")},
                {value: "false", label: _t("False")},
            ],
            value: condition?.value || "true",
            onSelect: (value) => this.onSimpleConditionBooleanSelect(condition.id, value),
            searchable: false,
            autoSort: false,
            class: "o_wfs_dd_simple_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleActivityNodeSelectProps(condition) {
        return {
            choices: this.activityNodeOptions,
            value: this.getSimpleActivityNodeSingleValue(condition),
            onSelect: (value) => this.onSimpleActivityNodeSingleSelect(condition.id, value),
            searchable: true,
            autoSort: false,
            placeholder: _t("Select activity"),
            searchPlaceholder: _t("Search activities..."),
            class: "o_wfs_dd_simple_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleActivityNodeMultiSelectProps(condition) {
        return {
            choices: this.activityNodeOptions,
            value: this.getSimpleActivityNodeMultiValues(condition),
            onSelect: (values) => this.onSimpleActivityNodeMultiSelect(condition.id, values),
            multiSelect: true,
            searchable: true,
            autoSort: false,
            placeholder: _t("Select activities"),
            searchPlaceholder: _t("Search activities..."),
            class: "o_wfs_dd_simple_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleSelectionSelectProps(condition) {
        return {
            choices: this.getSimpleSelectionOptions(condition),
            value: condition?.value || "",
            onSelect: (value) => this.onSimpleConditionValueSelect(condition.id, value),
            searchable: true,
            autoSort: false,
            placeholder: _t("Select value"),
            searchPlaceholder: _t("Search values..."),
            class: "o_wfs_dd_simple_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleSelectionMultiSelectProps(condition) {
        return {
            choices: this.getSimpleSelectionOptions(condition),
            value: this.getSimpleSelectionMultiValues(condition),
            onSelect: (values) => this.onSimpleSelectionMultiSelect(condition.id, values),
            multiSelect: true,
            searchable: true,
            autoSort: false,
            placeholder: _t("Select values"),
            searchPlaceholder: _t("Search values..."),
            class: "o_wfs_dd_simple_select",
            togglerClass: "o_wfs_dd_simple_select_toggler",
        };
    }

    getSimpleFieldMeta(fieldName) {
        return (
            this.simpleConditionFields.find((option) => option.value === fieldName) ||
            this.simpleConditionFields[0] ||
            BASE_SIMPLE_CONDITION_FIELDS[0]
        );
    }

    getSimpleOperatorOptions(fieldName) {
        const meta = this.getSimpleFieldMeta(fieldName);
        const inputKind = meta.inputKind || meta.type || "text";
        if (inputKind === "boolean") {
            return SIMPLE_BOOLEAN_OPERATORS;
        }
        if (
            inputKind === "selection" ||
            inputKind === "many2one" ||
            inputKind === "activity_node"
        ) {
            return SIMPLE_SCALAR_OPERATORS;
        }
        if (inputKind === "x2many") {
            return SIMPLE_X2MANY_OPERATORS;
        }
        if (["integer", "float", "monetary"].includes(`${meta.dataType || ""}`.toLowerCase())) {
            return SIMPLE_NUMERIC_OPERATORS;
        }
        return SIMPLE_TEXT_OPERATORS;
    }

    isSimpleBooleanField(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return (meta.type || "text") === "boolean";
    }

    onSimpleConnectorChange(event) {
        this.state.simpleConnector = event?.target?.value || "&";
    }

    onSimpleConnectorSelect(value) {
        this.state.simpleConnector = value === "|" ? "|" : "&";
    }

    onSimpleConditionFieldChange(conditionId, event) {
        this.onSimpleConditionFieldSelect(
            conditionId,
            event?.target?.value || (this.simpleConditionFields[0] && this.simpleConditionFields[0].value)
        );
    }

    onSimpleConditionFieldSelect(conditionId, value) {
        const fieldName = value || (this.simpleConditionFields[0] && this.simpleConditionFields[0].value);
        const fieldMeta = this.getSimpleFieldMeta(fieldName);
        this.state.simpleConditions = this.state.simpleConditions.map((condition) => {
            if (condition.id !== conditionId) {
                return condition;
            }
            const inputKind = fieldMeta.inputKind || fieldMeta.type || "text";
            return {
                ...condition,
                fieldName,
                operator: fieldMeta.defaultOperator || "=",
                valueType: fieldMeta.type || "text",
                value: inputKind === "boolean" ? "true" : inputKind === "x2many" ? [] : "",
            };
        });
        this.state.validationError = "";
    }

    onSimpleConditionOperatorChange(conditionId, event) {
        this.onSimpleConditionOperatorSelect(conditionId, event?.target?.value || "=");
    }

    onSimpleConditionOperatorSelect(conditionId, value) {
        const operator = value || "=";
        this.state.simpleConditions = this.state.simpleConditions.map((condition) => {
            if (condition.id !== conditionId) {
                return condition;
            }
            const next = {...condition, operator};
            const meta = this.getSimpleFieldMeta(condition.fieldName);
            const inputKind = meta?.inputKind || meta?.type || "text";
            if (inputKind === "x2many" && !this.isSimpleListOperator(next)) {
                next.operator = "in";
            }
            const toList = this.isSimpleListOperator({operator});
            if (toList) {
                if (Array.isArray(next.value)) {
                    return next;
                }
                const scalar = `${next.value ?? ""}`.trim();
                next.value = scalar ? [scalar] : [];
                return next;
            }
            if (Array.isArray(next.value)) {
                if (inputKind === "x2many") {
                    next.value = next.value;
                } else {
                    next.value = next.value[0] ?? "";
                }
            }
            return next;
        });
        this.state.validationError = "";
    }

    onSimpleConditionValueInput(conditionId, event) {
        const value = event?.target?.value ?? "";
        this.onSimpleConditionValueSelect(conditionId, value);
    }

    onSimpleConditionValueSelect(conditionId, value) {
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value} : condition
        );
        this.state.validationError = "";
    }

    onSimpleConditionBooleanChange(conditionId, event) {
        const value = event?.target?.value ?? "true";
        this.onSimpleConditionBooleanSelect(conditionId, value);
    }

    onSimpleConditionBooleanSelect(conditionId, value) {
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value} : condition
        );
        this.state.validationError = "";
    }

    addSimpleCondition() {
        const condition = this._newSimpleCondition();
        this.state.simpleConditions = [...this.state.simpleConditions, condition];
        this.state.validationError = "";
    }

    removeSimpleCondition(conditionId) {
        const remaining = this.state.simpleConditions.filter((condition) => condition.id !== conditionId);
        this.state.simpleConditions = remaining.length ? remaining : [this._newSimpleCondition()];
        this.state.validationError = "";
    }

    _coerceSimpleScalarValue(rawValue, meta, {forList = false} = {}) {
        const normalized = `${rawValue ?? ""}`.trim();
        const inputKind = meta?.inputKind || meta?.type || "text";
        const dataType = `${meta?.dataType || ""}`.toLowerCase();
        if (inputKind === "boolean") {
            return normalized.toLowerCase() === "false" ? "False" : "True";
        }
        if (inputKind === "activity_node") {
            return JSON.stringify(normalized);
        }
        if (
            inputKind === "many2one" ||
            inputKind === "x2many" ||
            ["integer", "float", "monetary"].includes(dataType)
        ) {
            const number = Number(normalized);
            if (Number.isFinite(number)) {
                return `${number}`;
            }
            if (forList) {
                return JSON.stringify(normalized);
            }
            return JSON.stringify(normalized);
        }
        return JSON.stringify(normalized);
    }

    _simpleListValues(condition) {
        if (Array.isArray(condition?.value)) {
            return condition.value
                .map((item) => `${item ?? ""}`.trim())
                .filter(Boolean);
        }
        return `${condition?.value ?? ""}`
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    }

    _simpleValueLiteral(condition) {
        const operator = (condition.operator || "=").toLowerCase();
        const meta = this.getSimpleFieldMeta(condition.fieldName);
        if (operator === "in" || operator === "not in") {
            const parts = this._simpleListValues(condition);
            return `[${parts
                .map((item) => this._coerceSimpleScalarValue(item, meta, {forList: true}))
                .join(", ")}]`;
        }
        if (Array.isArray(condition?.value)) {
            if ((meta?.inputKind || "") === "x2many") {
                const parts = this._simpleListValues(condition);
                return `[${parts
                    .map((item) => this._coerceSimpleScalarValue(item, meta, {forList: true}))
                    .join(", ")}]`;
            }
            const first = condition.value[0];
            return this._coerceSimpleScalarValue(first, meta, {forList: false});
        }
        const rawValue = `${condition.value ?? ""}`.trim();
        return this._coerceSimpleScalarValue(rawValue, meta, {forList: false});
    }

    _simpleClause(condition) {
        const fieldName = (condition.fieldName || "").trim();
        const meta = this.getSimpleFieldMeta(fieldName);
        const inputKind = meta?.inputKind || meta?.type || "text";
        let operator = (condition.operator || "=").trim();
        if (inputKind === "x2many" && !this.isSimpleListOperator(condition)) {
            operator = "in";
        }
        if (!fieldName || !operator) {
            return "";
        }
        if (condition.valueType !== "boolean") {
            const isListOperator = this.isSimpleListOperator(condition);
            if (isListOperator) {
                if (!this._simpleListValues(condition).length) {
                    return "";
                }
            } else if (Array.isArray(condition.value)) {
                if (!condition.value.length) {
                    return "";
                }
            } else if (`${condition.value ?? ""}`.trim() === "") {
                return "";
            }
        }
        return `(${JSON.stringify(fieldName)}, ${JSON.stringify(operator)}, ${this._simpleValueLiteral(
            condition
        )})`;
    }

    _buildLogicalDomain(tupleClauses = [], connector = "&") {
        const clauses = (tupleClauses || []).filter(Boolean);
        if (!clauses.length) {
            return "";
        }
        if (clauses.length === 1) {
            return `[${clauses[0]}]`;
        }
        const normalizedConnector = connector === "|" ? "|" : "&";
        let expr = `['${normalizedConnector}', ${clauses[0]}, ${clauses[1]}]`;
        for (let index = 2; index < clauses.length; index++) {
            expr = `['${normalizedConnector}', ${expr}, ${clauses[index]}]`;
        }
        return expr;
    }

    buildSimpleConditionDomain() {
        const clauses = (this.state.simpleConditions || [])
            .map((condition) => this._simpleClause(condition))
            .filter(Boolean);
        return this._buildLogicalDomain(clauses, this.state.simpleConnector);
    }

    applySimpleConditionDomain() {
        const expression = this.buildSimpleConditionDomain();
        if (!expression) {
            this.notification.add(_t("Please complete at least one condition."), {type: "warning"});
            return;
        }
        this.state.domain = expression;
        this.state.validationError = "";
    }

    isSimpleListOperator(condition) {
        const operator = `${condition?.operator || ""}`.trim().toLowerCase();
        return operator === "in" || operator === "not in";
    }

    isSimpleSelectionField(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return (meta.inputKind || meta.type || "text") === "selection";
    }

    isSimpleActivityNodeField(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return (meta.inputKind || "") === "activity_node";
    }

    isSimpleActivityNodeMultiField(condition) {
        return this.isSimpleActivityNodeField(condition) && this.isSimpleListOperator(condition);
    }

    get activityNodeOptions() {
        return Array.isArray(this.activityNodeState.rows) ? this.activityNodeState.rows : [];
    }

    get hasActivityNodeOptions() {
        return !!this.activityNodeOptions.length;
    }

    getSimpleActivityNodeSingleValue(condition) {
        if (Array.isArray(condition?.value)) {
            return `${condition.value[0] ?? ""}`.trim();
        }
        return `${condition?.value ?? ""}`.trim();
    }

    onSimpleActivityNodeSingleChange(conditionId, event) {
        const value = `${event?.target?.value ?? ""}`.trim();
        this.onSimpleActivityNodeSingleSelect(conditionId, value);
    }

    onSimpleActivityNodeSingleSelect(conditionId, value) {
        const normalizedValue = `${value ?? ""}`.trim();
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value: normalizedValue} : condition
        );
        this.state.validationError = "";
    }

    getSimpleActivityNodeMultiValues(condition) {
        return this._simpleListValues(condition);
    }

    isSimpleActivityNodeTagSelected(condition, nodeId) {
        const selected = this.getSimpleActivityNodeMultiValues(condition);
        return selected.includes(`${nodeId || ""}`);
    }

    toggleSimpleActivityNodeTag(conditionId, nodeId) {
        const normalizedNodeId = `${nodeId || ""}`.trim();
        if (!normalizedNodeId) {
            return;
        }
        this.state.simpleConditions = this.state.simpleConditions.map((condition) => {
            if (condition.id !== conditionId) {
                return condition;
            }
            const current = new Set(this.getSimpleActivityNodeMultiValues(condition));
            if (current.has(normalizedNodeId)) {
                current.delete(normalizedNodeId);
            } else {
                current.add(normalizedNodeId);
            }
            return {...condition, value: Array.from(current)};
        });
        this.state.validationError = "";
    }

    onSimpleActivityNodeMultiSelect(conditionId, values) {
        const normalizedValues = Array.isArray(values)
            ? values.map((value) => `${value ?? ""}`.trim()).filter(Boolean)
            : [];
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value: normalizedValues} : condition
        );
        this.state.validationError = "";
    }

    isSimpleSelectionMultiField(condition) {
        return this.isSimpleSelectionField(condition) && this.isSimpleListOperator(condition);
    }

    getSimpleSelectionOptions(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return Array.isArray(meta.selectionOptions) ? meta.selectionOptions : [];
    }

    getSimpleSelectionMultiValues(condition) {
        return this._simpleListValues(condition);
    }

    onSimpleSelectionMultiChange(conditionId, event) {
        const values = Array.from(event?.target?.selectedOptions || [])
            .map((option) => `${option?.value ?? ""}`.trim())
            .filter(Boolean);
        this.onSimpleSelectionMultiSelect(conditionId, values);
    }

    onSimpleSelectionMultiSelect(conditionId, values) {
        const normalizedValues = Array.isArray(values)
            ? values.map((value) => `${value ?? ""}`.trim()).filter(Boolean)
            : [];
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value: normalizedValues} : condition
        );
        this.state.validationError = "";
    }

    isSimpleMany2oneField(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return (meta.inputKind || meta.type || "text") === "many2one";
    }

    isSimpleX2ManyField(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return (meta.inputKind || "") === "x2many";
    }

    isSimpleSingleRecordSelectorField(condition) {
        return this.isSimpleMany2oneField(condition) && !this.isSimpleListOperator(condition);
    }

    isSimpleMultiRecordSelectorField(condition) {
        if (this.isSimpleX2ManyField(condition)) {
            return true;
        }
        return this.isSimpleMany2oneField(condition) && this.isSimpleListOperator(condition);
    }

    getSimpleRelationModel(condition) {
        const meta = this.getSimpleFieldMeta(condition?.fieldName);
        return `${meta?.relation || ""}`.trim();
    }

    hasSimpleRelationModel(condition) {
        return !!this.getSimpleRelationModel(condition);
    }

    getSimpleRecordSelectorValue(condition) {
        if (Array.isArray(condition?.value)) {
            const first = condition.value[0];
            const id = Number(first);
            return Number.isFinite(id) ? id : false;
        }
        const id = Number(`${condition?.value ?? ""}`.trim());
        return Number.isFinite(id) ? id : false;
    }

    onSimpleRecordSelect(conditionId, resId) {
        const value = Number.isFinite(Number(resId)) ? Number(resId) : "";
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value} : condition
        );
        this.state.validationError = "";
    }

    getSimpleMultiRecordIds(condition) {
        const values = this._simpleListValues(condition)
            .map((item) => Number(item))
            .filter((id) => Number.isFinite(id));
        return [...new Set(values)];
    }

    onSimpleMultiRecordSelect(conditionId, resIds) {
        const values = Array.isArray(resIds)
            ? [...new Set(resIds.map((id) => Number(id)).filter((id) => Number.isFinite(id)))]
            : [];
        this.state.simpleConditions = this.state.simpleConditions.map((condition) =>
            condition.id === conditionId ? {...condition, value: values} : condition
        );
        this.state.validationError = "";
    }

    get actorFieldOptions() {
        return [
            {value: "name", label: _t("Actor Name")},
            {value: "login", label: _t("Actor Login")},
            {value: "department", label: _t("Actor Department")},
            {value: "position", label: _t("Actor Position")},
            {value: "group", label: _t("Actor Group XMLID")},
            {value: "action_key", label: _t("Workflow Action Key")},
            {value: "request_manager", label: _t("Actor Is Request Manager")},
            {value: "hod", label: _t("Actor Is HOD")},
        ];
    }

    get actorFieldSelectProps() {
        return {
            choices: this.actorFieldOptions,
            value: this.state.actorField || "department",
            onSelect: (value) => {
                this.state.actorField = value || "department";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_value_select",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    get scenarioActorTypeSelectProps() {
        return {
            choices: [
                {value: "request_owner", label: _t("Request Owner")},
                {value: "hod", label: _t("HOD User")},
                {value: "manager", label: _t("Manager User")},
                {value: "login", label: _t("Specific Login")},
                {value: "group", label: _t("Specific Group XMLID")},
            ],
            value: this.state.scenarioActorType || "request_owner",
            onSelect: (value) => {
                this.state.scenarioActorType = value || "request_owner";
            },
            searchable: false,
            autoSort: false,
            class: "o_wfs_runtime_value_select",
            togglerClass: "o_wfs_runtime_value_select_toggler",
        };
    }

    get actorValuePlaceholder() {
        if (this.state.actorField === "group") {
            return "module.group_xmlid";
        }
        if (this.state.actorField === "position") {
            return _t("e.g. HOD");
        }
        if (this.state.actorField === "department") {
            return _t("e.g. Financial");
        }
        if (this.state.actorField === "name") {
            return _t("e.g. hod");
        }
        if (this.state.actorField === "login") {
            return _t("e.g. hod");
        }
        if (this.state.actorField === "action_key") {
            return _t("e.g. approve");
        }
        return "";
    }

    get actorFieldNeedsValue() {
        return !["request_manager", "hod"].includes(this.state.actorField);
    }

    get showActorBuilder() {
        return this.props.contextType === "twofa";
    }

    get showWorkflowScenarioBuilder() {
        return false;
    }

    get showWorkflowRuntimeClauseBuilder() {
        return this.props.contextType === "field_modifiers";
    }

    get workflowNodeOptions() {
        return Array.isArray(this.activityNodeState.rows) ? this.activityNodeState.rows : [];
    }

    get workflowActionOptions() {
        const rows = Array.isArray(this.workflowActionState.rows) ? this.workflowActionState.rows : [];
        const nodeId = `${this.state.workflowNodeId || ""}`.trim();
        if (!nodeId) {
            return rows;
        }
        const filtered = rows.filter((row) => `${row.source_id || ""}`.trim() === nodeId);
        return filtered.length ? filtered : rows;
    }

    get canUseWorkflowActionClause() {
        return this.effectiveDomainKind === "required";
    }

    get workflowNodeSelectProps() {
        return {
            choices: this.workflowNodeOptions,
            value: this.state.workflowNodeId,
            onSelect: (value) => this.onWorkflowRuntimeNodeSelect(value),
            searchable: true,
            autoSort: false,
            placeholder: this.activityNodeState.loading ? _t("Loading activities...") : _t("Select workflow activity"),
            searchPlaceholder: _t("Search activities..."),
            class: "o_wfs_runtime_clause_select",
            togglerClass: "o_wfs_runtime_clause_select_toggler",
            disabled: !!this.activityNodeState.loading,
        };
    }

    get workflowActionSelectProps() {
        return {
            choices: this.workflowActionOptions,
            value: this.state.workflowActionKey,
            onSelect: (value) => this.onWorkflowRuntimeActionSelect(value),
            searchable: true,
            autoSort: false,
            placeholder: this.workflowActionState.loading ? _t("Loading actions...") : _t("Select workflow action"),
            searchPlaceholder: _t("Search actions..."),
            class: "o_wfs_runtime_clause_select",
            togglerClass: "o_wfs_runtime_clause_select_toggler",
            disabled: !this.canUseWorkflowActionClause || !!this.workflowActionState.loading,
        };
    }

    onWorkflowRuntimeNodeSelect(value) {
        const nodeId = `${value || ""}`.trim();
        this.state.workflowNodeId = nodeId;
        const actionStillValid = this.workflowActionOptions.some(
            (option) => option.value === this.state.workflowActionKey
        );
        if (!actionStillValid) {
            this.state.workflowActionKey = "";
        }
    }

    onWorkflowRuntimeActionSelect(value) {
        this.state.workflowActionKey = `${value || ""}`.trim().toLowerCase();
    }

    _workflowNodeClause() {
        const nodeId = `${this.state.workflowNodeId || ""}`.trim();
        return nodeId ? `('wf_current_node_id', '=', ${JSON.stringify(nodeId)})` : "";
    }

    _workflowActionClause() {
        if (!this.canUseWorkflowActionClause) {
            return "";
        }
        const actionKey = `${this.state.workflowActionKey || ""}`.trim().toLowerCase();
        return actionKey ? `('wf_action_key', 'ilike', ${JSON.stringify(actionKey)})` : "";
    }

    _setWorkflowRuntimeClause(clauses = []) {
        const domain = this._buildAndDomain((clauses || []).filter(Boolean));
        if (!domain) {
            this.notification.add(_t("Please select at least one workflow value."), {type: "warning"});
            return;
        }
        this.state.domain = domain;
        this.state.mode = "advanced";
        this.state.validationError = "";
    }

    applyWorkflowNodeClause() {
        this._setWorkflowRuntimeClause([this._workflowNodeClause()]);
    }

    applyWorkflowActionClause() {
        if (!this.canUseWorkflowActionClause) {
            this.notification.add(_t("Workflow action is only available for Required when rules."), {
                type: "warning",
            });
            return;
        }
        this._setWorkflowRuntimeClause([this._workflowActionClause()]);
    }

    applyWorkflowNodeAndActionClause() {
        if (!this.canUseWorkflowActionClause) {
            this.applyWorkflowNodeClause();
            return;
        }
        this._setWorkflowRuntimeClause([this._workflowNodeClause(), this._workflowActionClause()]);
    }

    get effectiveDomainKind() {
        const kind = (this.props.domainKind || "").trim();
        if (["visible", "readonly", "required"].includes(kind)) {
            return kind;
        }
        return "visible";
    }

    onScenarioInputChange(fieldName, event) {
        this.state[fieldName] = event?.target?.value || "";
    }

    onScenarioRequireToggle(value) {
        this.state.scenarioRequireOnAction = !!value;
    }

    _quoted(value) {
        return JSON.stringify((value || "").trim());
    }

    _buildAndDomain(tupleClauses = []) {
        return this._buildLogicalDomain(tupleClauses, "&");
    }

    _scenarioActorClause() {
        const actorType = (this.state.scenarioActorType || "").trim();
        if (actorType === "request_owner") {
            return "('request_owner_id', '=', wf_actor_uid)";
        }
        if (actorType === "hod") {
            return "('wf_actor_is_hod', '=', True)";
        }
        if (actorType === "manager") {
            return "('wf_actor_is_manager', '=', True)";
        }
        if (actorType === "login") {
            const login = (this.state.scenarioActorLogin || "").trim().toLowerCase();
            if (!login) {
                return "";
            }
            return `('wf_actor_login', '=', ${JSON.stringify(login)})`;
        }
        if (actorType === "group") {
            const groupXmlid = (this.state.scenarioActorGroupXmlid || "").trim();
            if (!groupXmlid) {
                return "";
            }
            return `('wf_actor_group_xmlids', 'ilike', ${JSON.stringify(`,${groupXmlid},`)})`;
        }
        return "";
    }

    _scenarioBaseDomain() {
        const actorClause = this._scenarioActorClause();
        if (!actorClause) {
            return "";
        }
        const clauses = [actorClause];
        const nodeId = (this.state.scenarioNodeId || "").trim();
        if (nodeId) {
            clauses.push(`('wf_current_node_id', '=', ${this._quoted(nodeId)})`);
        }
        return this._buildAndDomain(clauses);
    }

    _scenarioRequiredDomain(baseDomain) {
        const base = (baseDomain || "").trim();
        if (!base) {
            return "";
        }
        if (!this.state.scenarioRequireOnAction) {
            return base;
        }
        const actionKey = (this.state.scenarioActionKey || "").trim().toLowerCase();
        if (!actionKey) {
            return "";
        }
        const actionClause = `('wf_action_key', 'ilike', ${JSON.stringify(actionKey)})`;
        return `['&', ${base}, ${actionClause}]`;
    }

    _buildScenarioDomains() {
        const baseDomain = this._scenarioBaseDomain();
        const requiredDomain = this._scenarioRequiredDomain(baseDomain);
        return {baseDomain, requiredDomain};
    }

    _validateScenarioInputs({forRequired = false} = {}) {
        const actorType = (this.state.scenarioActorType || "").trim();
        if (actorType === "login" && !(this.state.scenarioActorLogin || "").trim()) {
            this.notification.add(_t("Please enter actor login."), {type: "warning"});
            return false;
        }
        if (actorType === "group" && !(this.state.scenarioActorGroupXmlid || "").trim()) {
            this.notification.add(_t("Please enter group XMLID."), {type: "warning"});
            return false;
        }
        const baseDomain = this._scenarioBaseDomain();
        if (!baseDomain) {
            this.notification.add(_t("Please complete scenario inputs."), {type: "warning"});
            return false;
        }
        if (forRequired && this.state.scenarioRequireOnAction && !(this.state.scenarioActionKey || "").trim()) {
            this.notification.add(_t("Please enter action key for required rule."), {
                type: "warning",
            });
            return false;
        }
        return true;
    }

    applyScenarioToCurrentCondition() {
        const currentKind = this.effectiveDomainKind;
        const requiresAction = currentKind === "required";
        if (!this._validateScenarioInputs({forRequired: requiresAction})) {
            return;
        }
        const {baseDomain, requiredDomain} = this._buildScenarioDomains();
        this.state.domain = currentKind === "required" ? requiredDomain || baseDomain : baseDomain;
        this.state.mode = "advanced";
        this.state.validationError = "";
    }

    applyScenarioToAllConditions() {
        if (!this._validateScenarioInputs({forRequired: true})) {
            return;
        }
        if (typeof this.props.onApplyWorkflowScenario !== "function") {
            this.notification.add(_t("Scenario apply is unavailable in this context."), {
                type: "warning",
            });
            return;
        }
        const {baseDomain, requiredDomain} = this._buildScenarioDomains();
        const domainsByKind = {
            visible: baseDomain,
            readonly: baseDomain,
            required: requiredDomain || baseDomain,
        };
        this.props.onApplyWorkflowScenario(domainsByKind);
        this.props.close();
    }

    _buildActorCondition() {
        const value = (this.state.actorValue || "").trim();
        const quoted = JSON.stringify(value);
        switch (this.state.actorField) {
            case "name":
                if (!value) {
                    return "";
                }
                return `actor_name_is(${quoted})`;
            case "department":
                if (!value) {
                    return "";
                }
                return `actor_in_department(${quoted})`;
            case "position":
                if (!value) {
                    return "";
                }
                return `actor_in_position(${quoted})`;
            case "group":
                if (!value) {
                    return "";
                }
                return `actor_has_group(${quoted})`;
            case "request_manager":
                return "actor_is_request_manager()";
            case "hod":
                return "actor_is_hod()";
            default:
                return "";
        }
    }

    applyActorCondition() {
        if (this.props.contextType === "field_modifiers") {
            this._applyActorConditionForFieldModifiers();
            return;
        }
        const condition = this._buildActorCondition();
        if (!condition) {
            this.notification.add(_t("Please provide a value for the selected actor filter."), {
                type: "warning",
            });
            return;
        }
        this.state.domain = `[('id', '!=', 0)] if (${condition}) else [('id', '=', 0)]`;
        this.state.mode = "advanced";
        this.state.validationError = "";
    }

    _applyActorConditionForFieldModifiers() {
        const rawValue = (this.state.actorValue || "").trim();
        let domain = "";

        switch (this.state.actorField) {
            case "name":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_actor_name', 'ilike', ${JSON.stringify(rawValue.toLowerCase())})]`;
                break;
            case "department":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_actor_department_name', 'ilike', ${JSON.stringify(rawValue.toLowerCase())})]`;
                break;
            case "login":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_actor_login', '=', ${JSON.stringify(rawValue.toLowerCase())})]`;
                break;
            case "position":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_actor_position_name', 'ilike', ${JSON.stringify(rawValue.toLowerCase())})]`;
                break;
            case "group":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_actor_group_xmlids', 'ilike', ${JSON.stringify(`,${rawValue},`)})]`;
                break;
            case "action_key":
                if (!rawValue) {
                    domain = "";
                    break;
                }
                domain = `[('wf_action_key', 'ilike', ${JSON.stringify(rawValue.toLowerCase())})]`;
                break;
            case "request_manager":
                domain = "[('wf_actor_is_manager', '=', True)]";
                break;
            case "hod":
                domain = "[('wf_actor_is_hod', '=', True)]";
                break;
            default:
                domain = "";
        }

        if (!domain) {
            this.notification.add(_t("Please provide a value for the selected actor filter."), {
                type: "warning",
            });
            return;
        }
        this.state.domain = domain;
        this.state.mode = "advanced";
        this.state.validationError = "";
    }

    async _validateDomainExpression() {
        const expression = this._normalizeDomainInput(this.state.domain) || this.emptyDomainFallback;
        // Keep quick local parser validation for immediate UX feedback.
        try {
            const parsed = new Domain(expression);
            parsed.toString();
        } catch (error) {
            // For workflow-specific contexts, rely on server validator because
            // runtime helper symbols/functions are intentionally supported there.
            if (!["field_modifiers", "twofa", "assignment_users", "request_scope"].includes(this.effectiveContextType)) {
                return {
                    valid: false,
                    error: error?.message || _t("Invalid domain expression."),
                };
            }
        }
        const result = await this.orm.call(
            "workflow.approval.category.version",
            "workflow_studio_validate_domain_expression",
            [
                this.props.resModel,
                expression,
                this.props.contextType || "generic",
                this.validationRequestModel,
            ]
        );
        return result || {valid: false, error: _t("Invalid domain expression.")};
    }

    async onConfirm() {
        if (this.props.readonly) {
            this.props.close();
            return;
        }
        if (this.confirmButtonRef.el) {
            this.confirmButtonRef.el.disabled = true;
        }
        this.state.validationError = "";
        this.state.validating = true;

        try {
            if (this.state.mode === "builder" && this.showSimpleConditionBuilder) {
                const builtDomain = this.buildSimpleConditionDomain();
                const normalizedCurrent = this._normalizeDomainInput(this.state.domain) || this.emptyDomainFallback;
                const normalizedInitial = this._normalizeDomainInput(this.props.domain) || this.emptyDomainFallback;
                // Preserve manual edits in "Generated domain" textarea. Auto-build only when
                // dialog content is still unchanged from initial value.
                if (
                    builtDomain
                    && (
                        normalizedCurrent === this.emptyDomainFallback
                        || normalizedCurrent === normalizedInitial
                    )
                ) {
                    this.state.domain = builtDomain;
                }
            }
            const validation = await this._validateDomainExpression();
            if (!validation.valid) {
                this.state.validationError = validation.error || _t("Domain is invalid.");
                this.notification.add(_t("Domain is invalid. Please correct it."), {
                    type: "danger",
                });
                return;
            }
            const cleanedDomain = this._normalizeDomainInput(this.state.domain) || this.emptyDomainFallback;
            this.props.onConfirm(cleanedDomain);
            this.props.close();
        } catch (_error) {
            this.state.validationError =
                _error?.data?.message || _error?.message || _t("Failed to validate domain.");
            this.notification.add(_t("Failed to validate domain expression."), {type: "danger"});
        } finally {
            this.state.validating = false;
            if (this.confirmButtonRef.el) {
                this.confirmButtonRef.el.disabled = false;
            }
        }
    }
}
