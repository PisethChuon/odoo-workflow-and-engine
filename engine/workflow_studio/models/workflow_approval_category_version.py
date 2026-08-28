# -*- coding: utf-8 -*-
import base64
import datetime as py_datetime
import html
import io
import json
import pprint
import re
import zipfile
from collections import defaultdict
from types import SimpleNamespace

from lxml import etree
from dateutil.relativedelta import relativedelta
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.orm.domains import Domain
from odoo.addons.workflow_studio.controllers.export_utils import StudioExportSerializer
from odoo.tools.safe_eval import datetime as safe_eval_datetime
from odoo.tools.safe_eval import safe_eval


TASK_WRITE_FIELDS = {
    "name",
    "description",
    "sequence",
    "attr_class",
    "attr_label",
    "element",
    "approval_group_domain",
    "notification_delivery_mode",
    "notification_recipient_domain",
    "notification_recipient_mode",
    "notification_recipient_source",
    "notification_recipient_node_ref",
    "notification_recipient_node_user_type",
    "notification_recipient_filter_domain",
    "notification_approval_group_ids",
    "notification_group_ids",
    "activity_type",
    "activity_message_template",
    "assignment_mode",
    "assignment_user_domain",
    "assignment_source_user_type",
    "completion_mode",
    "fallback_policy",
    "fallback_user_id",
    "join_key",
    "gateway_node_id",
    "join_policy",
    "join_min_n",
    "parallel_reject_policy",
    "assign_to_previous_actor",
    "previous_actor_node_ref",
    "assign_to_request_owner",
    "reset_request_to_submit",
    "push_notification_to_actor",
    "notify_request_owner_email",
    "notify_request_creator_email",
    "confidentiality_level",
    "department_id",
    "requires_department_payload",
    "enable_share_override",
    "service_behavior",
    "automation_run_mode",
    "automation_condition_domain",
    "automation_schedule_mode",
    "automation_interval_number",
    "automation_interval_type",
    "automation_fixed_time",
    "automation_cron_expr",
    "automation_is_recurring",
    "automation_recurrence_end_mode",
    "automation_recurrence_count",
    "automation_recurrence_until",
}

ACTION_WRITE_FIELDS = {
    "name",
    "description",
    "attr_class",
    "icon_class",
    "attr_label",
    "auto_action_condition",
    "action_button_label",
    "invisible_domain",
    "domain",
    "action_mode",
    "authorization_mode",
    "authorization_scope",
    "business_actor_include_owner",
    "business_actor_include_creator",
    "business_actor_include_node_assignees",
    "business_actor_user_ids",
    "business_actor_group_ids",
    "business_actor_approval_group_ids",
    "business_actor_user_domain",
    "show_validation_dialog",
    "validation_message",
    "show_confirm_dialog",
    "dialog_type",
    "require_reason",
    "require_reason_domain",
    "comment_required_domain",
    "require_attachment",
    "require_attachment_domain",
    "required_attachment_count",
    "confirm_message",
    "approval_require_number",
    "comment_required",
    "idempotency_required",
    "require_2fa",
    "twofa_method",
    "twofa_condition_domain",
    "required_rule_set_id",
    "timer_duration_number",
    "timer_duration_unit",
    "automation_schedule_mode",
    "automation_interval_number",
    "automation_interval_type",
    "automation_fixed_time",
    "automation_cron_expr",
    "automation_is_recurring",
    "automation_recurrence_end_mode",
    "automation_recurrence_count",
    "automation_recurrence_until",
    "automation_trigger_mode",
}

NODE_LABELS = {
    "startEvent": "Start Event",
    "startEventMessage": "Start Event (Message)",
    "startEventTimer": "Start Event (Timer)",
    "startEventSignal": "Start Event (Signal)",
    "startEventConditional": "Start Event (Conditional)",
    "userTask": "User Task",
    "manualTask": "Manual Task",
    "task": "Generic Task",
    "serviceTask": "Service Task",
    "sendTask": "Send Task",
    "receiveTask": "Receive Task",
    "scriptTask": "Script Task",
    "businessRuleTask": "Business Rule Task",
    "callActivity": "Call Activity",
    "subProcess": "Sub Process",
    "endEvent": "End Event",
    "endEventMessage": "End Event (Message)",
    "endEventSignal": "End Event (Signal)",
    "endEventTerminate": "End Event (Terminate)",
    "conditionalEventDefinition": "Conditional Event",
    "intermediateCatchEvent": "Intermediate Catch Event",
    "intermediateEventMessage": "Intermediate Event (Message)",
    "intermediateEventSignal": "Intermediate Event (Signal)",
    "timerEvent": "Intermediate Event (Timer)",
    "intermediateThrowEvent": "Intermediate Throw Event",
    "intermediateThrowEventMessage": "Intermediate Throw Event (Message)",
    "intermediateThrowEventSignal": "Intermediate Throw Event (Signal)",
    "exclusiveGateway": "Exclusive Gateway",
    "parallelGateway": "Parallel Gateway",
    "inclusiveGateway": "Inclusive Gateway",
    "eventBasedGateway": "Event-Based Gateway",
    "complexGateway": "Complex Gateway",
}

NODE_METADATA_HINTS = {
    "startEvent": {
        "use_for": "Workflow initiation point. Configure the Initiation Form to set the Odoo form that opens when a user clicks New Request.",
        "meta_focus": ["action_id"],
    },
    "userTask": {
        "use_for": "Human approval/decision step.",
        "meta_focus": [
            "approval_group_link_ids",
            "assignment_mode",
            "push_notification_to_actor",
            "notify_request_owner_email",
            "notify_request_creator_email",
            "meta_action_ids",
            "field_ids",
        ],
    },
    "intermediateEventMessage": {
        "use_for": "Approval button transition event (email/no-email action semantics).",
        "meta_focus": ["meta_action_ids", "notification_recipient_ids"],
    },
    "sendTask": {
        "use_for": "Notification node (CC/Broadcast).",
        "meta_focus": ["notification_recipient_ids", "notification_recipient_domain", "activity_type_ids"],
    },
    "intermediateThrowEventMessage": {
        "use_for": "Mid-flow message notification. Configure an Email Template and recipients when this event should send email; leave the template empty to route only.",
        "meta_focus": ["email_template_external_id", "notification_recipient_ids", "activity_type_ids"],
    },
    "scriptTask": {
        "use_for": "Server-side automation node.",
        "meta_focus": ["activity_type_ids"],
    },
    "serviceTask": {
        "use_for": "Single-path conditional router.",
        "meta_focus": ["meta_action_ids.domain"],
    },
    "inclusiveGateway": {
        "use_for": "Multi-branch conditional router (one or more true branches).",
        "meta_focus": ["meta_action_ids.domain"],
    },
    "parallelGateway": {
        "use_for": "Parallel split/join routing.",
        "meta_focus": ["join_key", "join_policy", "parallel_reject_policy"],
    },
    "endEvent": {
        "use_for": "Terminal workflow node. Configure Meta Fields so completed requests still show the intended readonly fields.",
        "meta_focus": ["field_ids"],
    },
    "endEventMessage": {
        "use_for": "Terminal notification node. Configure an Email Template and recipients when the workflow should send a final message; leave the template empty to close only.",
        "meta_focus": ["field_ids", "email_template_external_id", "notification_recipient_ids"],
    },
    "endEventSignal": {
        "use_for": "Terminal signal node. Configure Meta Fields so completed requests still show the intended readonly fields.",
        "meta_focus": ["field_ids"],
    },
    "endEventTerminate": {
        "use_for": "Terminal force-stop node. Configure Meta Fields so completed requests still show the intended readonly fields.",
        "meta_focus": ["field_ids"],
    },
}


WORKFLOW_ACTION_TYPE_OPTIONS = [
    {"value": "log", "label": "Log Message"},
    {"value": "email", "label": "Send Email"},
    {"value": "sms", "label": "Send SMS"},
    {"value": "telegram", "label": "Send Telegram"},
    {"value": "webhook", "label": "Webhook"},
    {"value": "server_action", "label": "Run Server Action"},
    {"value": "workflow", "label": "Workflow Action"},
]

DOMAIN_PRESET_OPTIONS = {
    "generic": [
        {
            "key": "always",
            "label": "Always",
            "domain": "[]",
            "help": "Always matches.",
        },
        {
            "key": "never",
            "label": "Never",
            "domain": "[('id', '=', 0)]",
            "help": "Never matches.",
        },
    ],
    "user_assignment": [
        {
            "key": "active_internal",
            "label": "Active Internal Users",
            "domain": "[('share', '=', False), ('active', '=', True)]",
            "help": "Internal active users only.",
        },
        {
            "key": "request_owner",
            "label": "Request Owner",
            "domain": "[('id', '=', request_owner_id)]",
            "help": "Assign only the request owner user.",
        },
        {
            "key": "request_manager",
            "label": "Creator Manager",
            "domain": "[('id', '=', manager_user_id)]",
            "help": "Assign manager of request creator (legacy manager_user_id symbol).",
        },
        {
            "key": "request_owner_manager_user",
            "label": "Request Owner Manager User",
            "domain": "[('id', '=', request_owner_manager_user_id)]",
            "help": "Assign request owner's manager user.",
        },
        {
            "key": "request_owner_line_manager_user",
            "label": "Request Owner Line Manager",
            "domain": "[('id', '=', request_owner_line_manager_user_id)]",
            "help": "Assign direct line manager of request owner.",
        },
        {
            "key": "request_owner_department_manager_user",
            "label": "Request Owner Department Manager",
            "domain": "[('id', '=', request_owner_department_manager_user_id)]",
            "help": "Assign manager of request owner's HR department.",
        },
        {
            "key": "request_owner_manager_chain",
            "label": "Request Owner Manager Chain",
            "domain": "[('id', 'in', request_owner_manager_chain_user_ids)]",
            "help": "Assign all managers in request owner's reporting chain.",
        },
        {
            "key": "request_owner_or_manager",
            "label": "Request Owner Or Manager",
            "domain": "[('id', 'in', [request_owner_id, manager_user_id])]",
            "help": "Assign request owner and manager when available.",
        },
        {
            "key": "same_team_code_as_owner",
            "label": "Same Team Code As Owner",
            "domain": (
                "[('employee_ids.x_team_code', '!=', False), "
                "('employee_ids.x_team_code', '=', request_owner_team_code)]"
            ),
            "help": "Assign users whose employee team code matches request owner (safe on empty owner code).",
        },
        {
            "key": "same_line_code_as_owner",
            "label": "Same Line Code As Owner",
            "domain": (
                "[('employee_ids.x_line_code', '!=', False), "
                "('employee_ids.x_line_code', '=', request_owner_line_code)]"
            ),
            "help": "Assign users whose employee line code matches request owner (safe on empty owner code).",
        },
        {
            "key": "decided_approvers",
            "label": "Approvers Who Decided",
            "domain": "[('id', 'in', decided_approver_user_ids)]",
            "help": "Users who already made a decision on this request.",
        },
        {
            "key": "node_assigned_approvers",
            "label": "Node Assigned Approvers",
            "domain": "[('id', 'in', node_assigned_approver_user_ids('Task_Node'))]",
            "help": "Users assigned to a selected workflow node. Replace Task_Node with the node id.",
        },
        {
            "key": "node_pending_approvers",
            "label": "Node Pending Approvers",
            "domain": "[('id', 'in', node_pending_approver_user_ids('Task_Node'))]",
            "help": "Users still waiting on a selected workflow node. Replace Task_Node with the node id.",
        },
        {
            "key": "node_decided_approvers",
            "label": "Node Decided Approvers",
            "domain": "[('id', 'in', node_decided_approver_user_ids('Task_Node'))]",
            "help": "Users who made a decision on a selected workflow node. Replace Task_Node with the node id.",
        },
        {
            "key": "pending_approvers",
            "label": "Current Pending Approvers",
            "domain": "[('id', 'in', pending_approver_user_ids)]",
            "help": "Users currently pending/new/waiting on this request.",
        },
        {
            "key": "submitter_and_decided",
            "label": "Submitter + Decided Approvers",
            "domain": "[('id', 'in', notification_submitter_and_decided_user_ids)]",
            "help": "Request owner plus all users who already decided.",
        },
        {
            "key": "current_actor",
            "label": "Current Actor",
            "domain": "[('id', '=', uid)]",
            "help": "Assign only the currently logged in actor.",
        },
        {
            "key": "current_actor_or_owner",
            "label": "Current Actor Or Owner",
            "domain": "[('id', 'in', [uid, request_owner_id])]",
            "help": "Assign either current actor or request owner.",
        },
        {
            "key": "same_company",
            "label": "Same Company As Actor",
            "domain": "[('company_id', '=', user.company_id.id)]",
            "help": "Keep assignment inside actor company.",
        },
        {
            "key": "exclude_request_owner",
            "label": "Exclude Request Owner",
            "domain": "[('id', '!=', request_owner_id)]",
            "help": "Useful when owner should not approve their own request.",
        },
    ],
    "request_scope": [
        {
            "key": "always",
            "label": "Always",
            "domain": "[]",
            "help": "Always matches request records.",
        },
        {
            "key": "owner_is_current_actor",
            "label": "Owner = Current Actor",
            "domain": "[('request_owner_id', '=', uid)]",
            "help": "Apply this group rule only when actor is the request owner.",
        },
        {
            "key": "manager_is_current_actor",
            "label": "Manager = Current Actor",
            "domain": "[('manager_user_id', '=', uid)]",
            "help": "Apply this group rule only when actor is the request manager.",
        },
        {
            "key": "manager_available",
            "label": "Manager Is Set",
            "domain": "[('manager_user_id', '!=', False)]",
            "help": "Apply only when manager user is present on request.",
        },
        {
            "key": "same_company",
            "label": "Request In Actor Company",
            "domain": "[('company_id', '=', user.company_id.id)]",
            "help": "Useful in multi-company routing.",
        },
        {
            "key": "new_or_draft",
            "label": "Draft/New Requests",
            "domain": "[('state', 'in', ['draft', 'new'])]",
            "help": "Matches only draft/new requests.",
        },
        {
            "key": "waiting_only",
            "label": "Waiting Requests",
            "domain": "[('state', '=', 'waiting')]",
            "help": "Apply only on waiting requests.",
        },
        {
            "key": "date_overdue",
            "label": "Date Field Overdue",
            "domain": "[('x_expect_return_date', '<', current_date)]",
            "help": "Use for reminders: replace x_expect_return_date with any Date/Datetime field. current_date is evaluated when automation runs.",
        },
        {
            "key": "date_today",
            "label": "Date Field Today",
            "domain": "[('x_expect_return_date', '=', 'today')]",
            "help": "Matches records whose date field is today. Replace x_expect_return_date with your field.",
        },
        {
            "key": "date_tomorrow",
            "label": "Date Field Tomorrow",
            "domain": "[('x_expect_return_date', '=', 'today +1d')]",
            "help": "Matches records whose date field is tomorrow. Replace x_expect_return_date with your field.",
        },
        {
            "key": "date_last_7_days",
            "label": "Date Last 7 Days",
            "domain": "['&', ('x_expect_return_date', '>=', 'today -7d'), ('x_expect_return_date', '<', 'today')]",
            "help": "Odoo-style relative range. Replace x_expect_return_date with your field.",
        },
        {
            "key": "current_stage_older_than_1_day",
            "label": "Current Stage > 1 Day",
            "domain": "[('wf_current_stage_age_minutes', '>=', 1440)]",
            "help": "Simple Odoo-style domain. Matches when the current actor/current stage has been active for at least 1 day.",
        },
        {
            "key": "specific_node_older_than_1_day",
            "label": "Specific Node > 1 Day",
            "domain": "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 1440",
            "help": "Advanced, parallel-safe expression. Replace Task_HOD with the BPMN node id.",
        },
        {
            "key": "specific_node_older_than_1_week",
            "label": "Specific Node > 1 Week",
            "domain": "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 10080",
            "help": "Use for automation guards when a specific active node has stayed open for 7 days. Replace Task_HOD.",
        },
        {
            "key": "high_amount_example",
            "label": "High Amount (Example)",
            "domain": "[('x_amount_total', '>=', 1000)]",
            "help": "Example threshold. Adjust field and value for your model.",
        },
        {
            "key": "field_equals_value",
            "label": "Field Equals Value",
            "domain": "[('x_item_line_id', '=', 1)]",
            "help": "Route this approval-group rule only when a specific request field matches a value. "
                    "Example: x_item_line_id = 1 for Hotel App, x_item_line_id = 2 for Casino App.",
        },
        {
            "key": "field_in_values",
            "label": "Field In Values",
            "domain": "[('x_item_line_id', 'in', [1, 2])]",
            "help": "Route this approval-group rule when a request field matches any value in the list. "
                    "Useful for grouping several form choices under one approval group.",
        },
    ],
    "action_visibility": [
        # ── Always / state presets ────────────────────────────────────────────
        {
            "key": "always",
            "label": "Always Show",
            "domain": "[(1, '=', 1)]",
            "help": "Button is always visible to any user with stage permission.",
        },
        {
            "key": "pending_only",
            "label": "Pending Only",
            "domain": "[('state', 'in', ['new', 'waiting'])]",
            "help": "Show only while the request is active (new or waiting stage).",
        },
        {
            "key": "waiting_only",
            "label": "Workflow Waiting Only",
            "domain": "[('state', '=', 'waiting')]",
            "help": "Show only when request is in waiting state.",
        },
        {
            "key": "current_stage_under_1_day",
            "label": "Current Stage < 1 Day",
            "domain": "[('wf_current_stage_age_minutes', '<', 1440)]",
            "help": "Show while the current stage age is below 1 day. Use this when the button should disappear after 1 day.",
        },
        {
            "key": "specific_node_under_1_day",
            "label": "Specific Node < 1 Day",
            "domain": "(not wf_has_active_node('Task_HOD')) or wf_node_age_minutes('Task_HOD') < 1440",
            "help": "Advanced, parallel-safe show condition. Replace Task_HOD; the button hides once that active node reaches 1 day.",
        },
        {
            "key": "specific_node_older_than_1_day",
            "label": "Specific Node > 1 Day",
            "domain": "wf_has_active_node('Task_HOD') and wf_node_age_minutes('Task_HOD') >= 1440",
            "help": "Advanced condition for actions that should only show after a selected active node is older than 1 day.",
        },
        {
            "key": "date_overdue",
            "label": "Date Field Overdue",
            "domain": "[('x_expect_return_date', '<', current_date)]",
            "help": "Use for automation guards/reminders. Replace x_expect_return_date; current_date is evaluated when automation runs.",
        },
        {
            "key": "date_today",
            "label": "Date Field Today",
            "domain": "[('x_expect_return_date', '=', 'today')]",
            "help": "Matches records whose date field is today. Replace x_expect_return_date with your field.",
        },
        {
            "key": "date_tomorrow",
            "label": "Date Field Tomorrow",
            "domain": "[('x_expect_return_date', '=', 'today +1d')]",
            "help": "Matches records whose date field is tomorrow. Replace x_expect_return_date with your field.",
        },
        # ── Business case 3: user group ───────────────────────────────────────
        {
            "key": "actor_has_group_example",
            "label": "Group Gated",
            "domain": "[('wf_actor_group_ids', 'in', [3])]",
            "help": "Show only when the acting user belongs to the specified Odoo security group. "
                    "Use standard Odoo-domain tuple syntax and replace 3 with your res.groups record ID.",
        },
        {
            "key": "actor_has_approval_group_example",
            "label": "Approval Group Gated",
            "domain": "[('wf_actor_approval_group_ids', 'in', [12])]",
            "help": "Show only when the acting user belongs to the specified workflow approval group. "
                    "Use standard Odoo-domain tuple syntax and replace 12 with your workflow.approval.group ID.",
        },
        {
            "key": "actor_is_admin",
            "label": "Admin Only",
            "domain": "[('wf_actor_group_ids', 'in', [4])]",
            "help": "Show only to Workflow Admin users using standard Odoo-domain tuple syntax. "
                    "Replace 4 with your res.groups record ID.",
        },
        # ── Business case 4: manager relationship ────────────────────────────
        {
            "key": "manager_only",
            "label": "Manager of Requester",
            "domain": "[('uid', '=', request_owner_manager_user_id)]",
            "help": "Show only to the direct manager of the request owner "
                    "by comparing current actor ID against the request owner's manager user ID.",
        },
        {
            "key": "in_manager_chain",
            "label": "In Manager Chain",
            "domain": "[('uid', 'in', request_owner_manager_chain_user_ids)]",
            "help": "Show to any user in the request owner's full management reporting chain.",
        },
        # ── Business case 2 & 5: field value / amount threshold ───────────────
        {
            "key": "amount_threshold_example",
            "label": "Amount > Threshold",
            "domain": "[('x_amount_total', '>=', 1000)]",
            "help": "Show button when the record amount meets a threshold. "
                    "Adjust the field name and value for your model. "
                    "When used as Button Visibility, the field is read from the "
                    "live form snapshot (no save required).",
        },
        {
            "key": "field_value_example",
            "label": "Field Equals Value",
            "domain": "[('x_section', '=', 'hotel')]",
            "help": "Show button only when a specific field equals a value. "
                    "For Button Visibility the value is read from the unsaved form snapshot — "
                    "updates live on onChange without requiring a save.",
        },
    ],
}

DOMAIN_PRESET_OPTIONS["routing_user_assignment"] = [
    {
        "key": "always",
        "label": "Always",
        "domain": "[(1, '=', 1)]",
        "help": "Intentionally keep all users from the selected routing source.",
    },
    {
        "key": "never",
        "label": "Never",
        "domain": "[(0, '=', 1)]",
        "help": "Intentionally contribute no users from this routing source.",
    },
    *DOMAIN_PRESET_OPTIONS["user_assignment"],
]

DOMAIN_PRESET_OPTIONS["routing_request_scope"] = [
    {
        "key": "always",
        "label": "Always",
        "domain": "[(1, '=', 1)]",
        "help": "Intentionally match all request records for this routing rule.",
    },
    {
        "key": "never",
        "label": "Never",
        "domain": "[(0, '=', 1)]",
        "help": "Intentionally match no request records for this routing rule.",
    },
    *[
        preset
        for preset in DOMAIN_PRESET_OPTIONS["request_scope"]
        if preset.get("key") not in {"always", "never"}
    ],
]

WORKFLOW_MAP_FIELD_MAPPING_TEMPLATES = [
    {
        "key": "empty",
        "label": "Start Empty",
        "value": "{}",
        "help": "Start with empty mapping JSON.",
    },
    {
        "key": "owner",
        "label": "Map Request Owner",
        "value": "{\"request_owner_id\": \"request_owner_id\"}",
        "help": "Pass request owner to child workflow owner.",
    },
    {
        "key": "basic",
        "label": "Common Basic Fields",
        "value": "{\"name\": \"name\", \"request_owner_id\": \"request_owner_id\", \"category_id\": \"category_id\"}",
        "help": "Starter template for common workflow fields.",
    },
]

LIFECYCLE_STATE_LABELS = {
    "draft": "Draft",
    "deployed": "Deployed",
    "published": "Published",
    "retired": "Retired",
}


class WorkflowApprovalCategoryVersion(models.Model):
    _inherit = "workflow.approval.category.version"

    _WF_DOMAIN_ALLOWED_OPERATORS = {
        "=",
        "==",
        "!=",
        "<>",
        ">",
        ">=",
        "<",
        "<=",
        "in",
        "not in",
        "like",
        "not like",
        "ilike",
        "not ilike",
        "=like",
        "not =like",
        "=ilike",
        "not =ilike",
        "contains",
        "not contains",
        "icontains",
        "not icontains",
    }
    _WF_DOMAIN_MAX_EXPR_LENGTH = 4096
    _WF_DOMAIN_MAX_DEPTH = 16
    _WF_DOMAIN_MAX_LEAFS = 120
    _WF_DOMAIN_MAX_ITEMS = 256
    _WF_DOMAIN_MAX_STRING_LENGTH = 512
    _WF_INLINE_DOMAIN_MAX_EXPR_LENGTH = 1024
    _WF_UNSUPPORTED_REQUIRED_OPTION_KEYS = (
        "wf_required_domain",
        "wf_require_domain",
        "required_domain",
        "require_domain",
    )
    _WF_WORKFLOW_DOMAIN_ATTR_KEYS = (
        "wf_visible_domain",
        "visible_domain",
        "wf_readonly_domain",
        "readonly_domain",
        "wf_modifier_domain",
        "wf_domain",
        "wf_required_domain",
        "wf_require_domain",
        "required_domain",
        "require_domain",
    )
    _WF_USER_DOMAIN_FIELD_ALIASES = {
        # Backward-compatible alias frequently used in customer expressions.
        "user_id": "id",
    }
    _WF_RUNTIME_DOMAIN_FIELDS = {
        "id",
        "uid",
        "user_id",
        "wf_actor_uid",
        "wf_actor_name",
        "wf_actor_login",
        "wf_actor_department_name",
        "wf_actor_position_name",
        "wf_actor_group_ids",
        "wf_actor_group_xmlids",
        "wf_actor_approval_group_ids",
        "wf_actor_approval_group_names",
        "wf_actor_approval_group_csv",
        "wf_actor_is_manager",
        "wf_actor_is_hod",
        "wf_action_key",
        "wf_current_node_id",
        "wf_active_node_ids",
        "wf_current_stage_age_minutes",
        "wf_current_stage_age_display",
        "wf_oldest_active_stage_age_minutes",
        "wf_youngest_active_stage_age_minutes",
        "action_key",
        "current_action_key",
        "current_node_id",
        "active_node_ids",
        "current_stage_age_minutes",
        "current_stage_age_display",
        "current_meta_task_id",
        "current_meta_task",
        "is_it_department",
        "is_manager_of_requester",
    }

    is_published = fields.Boolean(string="Published", default=False, copy=False, readonly=True)
    deployed_at = fields.Datetime(string="Deployed At", copy=False, readonly=True)
    published_at = fields.Datetime(string="Published At", copy=False, readonly=True)

    def action_activate_workflow_studio(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_("This workflow version is not linked to any category."))
        context = dict(
            self.env.context,
            active_model="workflow.approval.category.version",
            active_id=self.id,
            active_ids=[self.id],
            workflow_category_id=self.category_id.id,
            workflow_version_id=self.id,
        )
        return self.category_id.with_context(context).action_activate_workflow_studio()

    def _workflow_studio_check_designer_access(self):
        if not (
            self.env.user.has_group("workflow_engine.group_workflow_approval_admin")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Only Workflow Approval Admin users can configure BPMN metadata."))

    def _workflow_studio_get_version(self, require_write=False, allow_locked=False):
        self.ensure_one()
        self._workflow_studio_check_designer_access()
        version = self.sudo()
        if require_write and version.is_locked and not allow_locked:
            raise UserError(
                _(
                    "This workflow version is locked. Unlock it or duplicate it before editing."
                )
            )
        return version

    @api.model
    def _workflow_studio_actor_eval_helpers(self, actor, sample_record=False):
        def _norm(value):
            return (value or "").strip().lower()

        def _actor_department():
            department = getattr(actor, "department_id", False)
            if department:
                return department
            employee = getattr(actor, "employee_id", False)
            return employee.department_id if employee else False

        def _actor_position_name():
            employee = getattr(actor, "employee_id", False)
            if not employee or not employee.job_id:
                return ""
            return employee.job_id.name or ""

        def actor_has_group(xmlid):
            if not xmlid:
                return False
            try:
                return bool(actor.has_group(str(xmlid)))
            except Exception:
                return False

        actor_approval_groups = self.env["workflow.approval.group"].sudo().search(
            [("user_ids", "in", actor.id)]
        )
        actor_approval_group_ids = actor_approval_groups.ids
        actor_approval_group_names = [
            (group.name or "").strip().lower()
            for group in actor_approval_groups
            if (group.name or "").strip()
        ]

        def actor_has_approval_group(group_ref):
            if group_ref in (None, False, ""):
                return False
            try:
                return int(group_ref) in actor_approval_group_ids
            except Exception:
                return _norm(group_ref) in actor_approval_group_names

        def actor_name_is(name):
            return _norm(actor.name) == _norm(name)

        def actor_in_department(name):
            department = _actor_department()
            return bool(department and _norm(department.name) == _norm(name))

        def actor_in_position(name):
            return _norm(_actor_position_name()) == _norm(name)

        def actor_is_request_manager():
            manager = getattr(sample_record, "manager_user_id", False) if sample_record else False
            return bool(manager and manager.id == actor.id)

        def actor_is_hod():
            if actor_is_request_manager():
                return True
            position = _norm(_actor_position_name())
            if "hod" in position or "head of department" in position:
                return True
            department = _actor_department()
            dept_manager = (
                department.manager_id.user_id
                if department and getattr(department, "manager_id", False)
                else False
            )
            return bool(dept_manager and dept_manager.id == actor.id)

        return {
            "actor": actor,
            "actor_has_group": actor_has_group,
            "actor_name_is": actor_name_is,
            "actor_in_department": actor_in_department,
            "actor_in_position": actor_in_position,
            "actor_has_approval_group": actor_has_approval_group,
            "actor_is_request_manager": actor_is_request_manager,
            "actor_is_hod": actor_is_hod,
        }

    @api.model
    def _workflow_studio_collect_record_eval_values(self, record):
        values = {}
        if not record:
            return values
        record = record.sudo()
        for field_name, field in record._fields.items():
            field_type = field.type or ""
            if field_type in ("binary", "html", "one2many"):
                continue
            try:
                field_value = record[field_name]
            except Exception:
                continue
            if field_type == "many2one":
                values[field_name] = field_value.id if field_value else False
                continue
            if field_type == "many2many":
                values[field_name] = list(field_value.ids)
                continue
            if field_type == "date":
                values[field_name] = fields.Date.to_string(field_value) if field_value else False
                continue
            if field_type == "datetime":
                values[field_name] = (
                    fields.Datetime.to_string(field_value) if field_value else False
                )
                continue
            values[field_name] = field_value
        values.setdefault("record_id", record.id or False)
        return values

    @api.model
    def _workflow_studio_domain_eval_symbols(self, sample_record=False, request_sample_record=False):
        actor = self.env.user.sudo()
        company = actor.company_id.sudo() if actor.company_id else self.env["res.company"]
        department = actor.department_id.sudo() if actor.department_id else self.env["hr.department"]
        employee = actor.employee_id.sudo() if actor.employee_id else self.env["hr.employee"]
        position_name = employee.job_id.name if employee and employee.job_id else ""
        request_record = request_sample_record or sample_record
        group_xmlids = self.env["ir.model.data"].sudo().search(
            [("model", "=", "res.groups"), ("res_id", "in", actor.group_ids.ids)]
        ).mapped("complete_name")
        actor_group_ids = actor.group_ids.ids
        actor_group_csv = f",{','.join(group_xmlids)}," if group_xmlids else ","
        actor_approval_groups = self.env["workflow.approval.group"].sudo().search(
            [("user_ids", "in", actor.id)]
        )
        actor_approval_group_ids = actor_approval_groups.ids
        actor_approval_group_names = [
            (group.name or "").strip().lower()
            for group in actor_approval_groups
            if (group.name or "").strip()
        ]
        request_owner = (
            getattr(request_record, "request_owner_id", False)
            if request_record and "request_owner_id" in request_record._fields
            else False
        )
        manager_user = (
            getattr(request_record, "manager_user_id", False)
            if request_record and "manager_user_id" in request_record._fields
            else False
        )
        request_creator = (
            getattr(request_record, "create_uid", False)
            if request_record and "create_uid" in request_record._fields
            else False
        )
        request_owner_employee = (
            request_owner.employee_id
            if request_owner and request_owner.employee_id
            else self.env["hr.employee"]
        )
        request_owner_department = (
            request_owner_employee.department_id
            if request_owner_employee and request_owner_employee.department_id
            else self.env["hr.department"]
        )
        request_owner_manager_user = (
            request_owner.employee_id.parent_id.user_id
            if request_owner
            and request_owner.employee_id
            and request_owner.employee_id.parent_id
            and request_owner.employee_id.parent_id.user_id
            else False
        )
        request_owner_line_manager_user = (
            request_owner_employee.parent_id.user_id
            if request_owner_employee
            and request_owner_employee.parent_id
            and request_owner_employee.parent_id.user_id
            else False
        )
        request_owner_department_manager_user = (
            request_owner_department.manager_id.user_id
            if request_owner_department
            and request_owner_department.manager_id
            and request_owner_department.manager_id.user_id
            else False
        )
        request_owner_manager_chain_user_ids = []
        current_manager = request_owner_employee.parent_id if request_owner_employee else self.env["hr.employee"]
        visited = set()
        while current_manager and current_manager.id and current_manager.id not in visited:
            visited.add(current_manager.id)
            if current_manager.user_id and current_manager.user_id.id:
                request_owner_manager_chain_user_ids.append(current_manager.user_id.id)
            current_manager = current_manager.parent_id
        request_owner_team = (
            getattr(request_owner_employee, "x_team", False)
            if request_owner_employee
            else False
        )
        request_owner_team_code = (
            getattr(request_owner_employee, "x_team_code", False)
            if request_owner_employee
            else False
        )
        request_owner_line = (
            getattr(request_owner_employee, "x_line", False)
            if request_owner_employee
            else False
        )
        request_owner_line_code = (
            getattr(request_owner_employee, "x_line_code", False)
            if request_owner_employee
            else False
        )
        user_namespace = SimpleNamespace(
            id=actor.id,
            login=actor.login or "",
            name=actor.name or "",
            company_id=SimpleNamespace(id=company.id if company else False),
            department_id=SimpleNamespace(id=department.id if department else False),
            group_ids=tuple(actor_group_ids),
            approval_group_ids=tuple(actor_approval_group_ids),
        )
        is_actor_request_owner_manager = bool(
            (manager_user and manager_user.id == actor.id)
            or (
                request_owner_line_manager_user
                and request_owner_line_manager_user.id == actor.id
            )
        )

        def wf_has_active_node(node_id):
            return bool((node_id or "").strip() in {"Task_1", "Task_HOD"})

        def wf_node_age_minutes(node_id):
            return 1440 if wf_has_active_node(node_id) else 0

        def wf_oldest_active_node_age_minutes():
            return 1440

        def wf_youngest_active_node_age_minutes():
            return 30

        eval_symbols = {}
        field_rule_service = self.env["workflow.engine.field.rule.service"].sudo()

        def validate_line_domain(relation_path, line_domain):
            related_records = field_rule_service._resolve_workflow_relation_path(
                target_record=sample_record,
                request_record=request_record or sample_record,
                relation_path=relation_path,
            )
            normalized_domain = field_rule_service._safe_eval_domain_expression(
                line_domain,
                eval_symbols,
            )
            if isinstance(normalized_domain, bool):
                return normalized_domain

            def validate_field_paths(node):
                if not isinstance(node, (list, tuple)) or not node:
                    return
                if (
                    len(node) >= 3
                    and isinstance(node[0], str)
                    and node[0] not in ("&", "|", "!")
                ):
                    field_path = node[0].strip()
                    if not field_rule_service._domain_field_path_exists(
                        related_records._name,
                        field_path,
                    ):
                        raise ValidationError(
                            self.env._(
                                "Unknown line-item field path '%(field_path)s' on model '%(model)s'.",
                                field_path=field_path,
                                model=related_records._name,
                            )
                        )
                    return
                for item in node:
                    if item not in ("&", "|", "!"):
                        validate_field_paths(item)

            validate_field_paths(normalized_domain)
            return normalized_domain

        def wf_any(relation_path, line_domain):
            line_domain = validate_line_domain(relation_path, line_domain)
            return field_rule_service._match_related_domain_quantifier(
                target_record=sample_record,
                request_record=request_record or sample_record,
                relation_path=relation_path,
                line_domain=line_domain,
                eval_ctx={
                    "runtime_values": {},
                    "safe_symbols": eval_symbols,
                },
                quantifier="any",
            )

        def wf_all(relation_path, line_domain):
            line_domain = validate_line_domain(relation_path, line_domain)
            return field_rule_service._match_related_domain_quantifier(
                target_record=sample_record,
                request_record=request_record or sample_record,
                relation_path=relation_path,
                line_domain=line_domain,
                eval_ctx={
                    "runtime_values": {},
                    "safe_symbols": eval_symbols,
                },
                quantifier="all",
            )

        today_date = fields.Date.context_today(self)
        current_date = fields.Date.to_string(today_date)
        eval_symbols = {
            "uid": actor.id,
            "current_date": current_date,
            "today": current_date,
            "now": fields.Datetime.to_string(fields.Datetime.now()),
            "context_today": lambda *args, **kwargs: today_date,
            "datetime": safe_eval_datetime,
            "time": py_datetime.time,
            "relativedelta": relativedelta,
            "user": actor,
            "current_user": actor,
            "actor_user": actor,
            "user_ns": user_namespace,
            "env": self.env,
            "context": dict(self.env.context),
            "object": sample_record,
            "request": request_record or sample_record,
            "wf_actor_uid": actor.id,
            "wf_actor_name": (actor.name or "").strip().lower(),
            "wf_actor_login": (actor.login or "").strip().lower(),
            "wf_actor_department_name": (department.name or "").strip().lower() if department else "",
            "wf_actor_position_name": (position_name or "").strip().lower(),
            "wf_actor_group_ids": actor_group_ids,
            "wf_actor_group_xmlids": actor_group_csv,
            "wf_actor_approval_group_ids": actor_approval_group_ids,
            "wf_actor_approval_group_names": actor_approval_group_names,
            "wf_actor_approval_group_csv": (
                f",{','.join(str(group_id) for group_id in actor_approval_group_ids)},"
                if actor_approval_group_ids
                else ","
            ),
            "wf_actor_is_manager": is_actor_request_owner_manager,
            "wf_actor_is_hod": bool(
                "hod" in (position_name or "").strip().lower()
                or "head of department" in (position_name or "").strip().lower()
            ),
            "wf_action_key": "submit",
            "action_key": "submit",
            "current_action_key": "submit",
            "wf_current_node_id": "Task_1",
            "current_node_id": "Task_1",
            "wf_active_node_ids": ["Task_1", "Task_HOD"],
            "active_node_ids": ["Task_1", "Task_HOD"],
            "wf_current_stage_age_minutes": 1440,
            "current_stage_age_minutes": 1440,
            "wf_current_stage_age_display": "1d 0h",
            "current_stage_age_display": "1d 0h",
            "wf_oldest_active_stage_age_minutes": 1440,
            "wf_youngest_active_stage_age_minutes": 30,
            "wf_has_active_node": wf_has_active_node,
            "wf_node_age_minutes": wf_node_age_minutes,
            "wf_oldest_active_node_age_minutes": wf_oldest_active_node_age_minutes,
            "wf_youngest_active_node_age_minutes": wf_youngest_active_node_age_minutes,
            "wf_any": wf_any,
            "wf_all": wf_all,
            "current_meta_task_id": False,
            "current_meta_task": False,
            "is_it_department": bool(
                department
                and department.name
                and "it" in (department.name or "").strip().lower()
            ),
            "is_manager_of_requester": is_actor_request_owner_manager,
        }
        eval_symbols.update(self._workflow_studio_collect_record_eval_values(sample_record))
        request_values = self._workflow_studio_collect_record_eval_values(request_record)
        for key, value in request_values.items():
            eval_symbols.setdefault(key, value)
        eval_symbols.setdefault("request_model", request_record._name if request_record else "")
        eval_symbols.setdefault("request_id", request_record.id if request_record else False)
        eval_symbols.setdefault("request_owner_id", request_owner.id if request_owner else False)
        eval_symbols.setdefault("request_owner_user_id", request_owner.id if request_owner else False)
        eval_symbols.setdefault("request_creator_id", request_creator.id if request_creator else False)
        eval_symbols.setdefault("request_creator_user_id", request_creator.id if request_creator else False)
        eval_symbols.setdefault("manager_user_id", manager_user.id if manager_user else False)
        eval_symbols.setdefault(
            "request_creator_manager_user_id",
            manager_user.id if manager_user else False,
        )
        eval_symbols.setdefault(
            "request_owner_manager_user_id",
            request_owner_manager_user.id if request_owner_manager_user else False,
        )
        eval_symbols.setdefault(
            "request_owner_line_manager_user_id",
            request_owner_line_manager_user.id if request_owner_line_manager_user else False,
        )
        eval_symbols.setdefault(
            "request_owner_department_id",
            request_owner_department.id if request_owner_department else False,
        )
        eval_symbols.setdefault(
            "request_owner_department_manager_user_id",
            request_owner_department_manager_user.id
            if request_owner_department_manager_user
            else False,
        )
        eval_symbols.setdefault(
            "request_owner_manager_chain_user_ids",
            request_owner_manager_chain_user_ids,
        )
        eval_symbols.setdefault("request_owner_team", request_owner_team or False)
        eval_symbols.setdefault("request_owner_team_code", request_owner_team_code or False)
        eval_symbols.setdefault("request_owner_line", request_owner_line or False)
        eval_symbols.setdefault("request_owner_line_code", request_owner_line_code or False)
        approver_rows = self.env["workflow.approval.approver"]
        if request_record and "approver_ids" in request_record._fields:
            try:
                approver_rows = request_record.approver_ids.sudo()
            except Exception:
                approver_rows = self.env["workflow.approval.approver"]
        decided_rows = approver_rows.filtered(
            lambda row: bool((getattr(row, "user_decision", "") or "").strip())
        )
        pending_rows = approver_rows.filtered(
            lambda row: getattr(row, "status", False) in ("new", "pending", "waiting")
        )
        all_user_ids = [uid for uid in approver_rows.mapped("user_id").ids if uid]
        decided_user_ids = [uid for uid in decided_rows.mapped("user_id").ids if uid]
        pending_user_ids = [uid for uid in pending_rows.mapped("user_id").ids if uid]
        submitter_and_decided = list(
            dict.fromkeys(
                ([request_owner.id] if request_owner else []) + decided_user_ids
            )
        )
        eval_symbols.setdefault("all_approver_user_ids", all_user_ids)
        eval_symbols.setdefault("decided_approver_user_ids", decided_user_ids)
        eval_symbols.setdefault("has_decision_user_ids", decided_user_ids)
        eval_symbols.setdefault("pending_approver_user_ids", pending_user_ids)
        eval_symbols.setdefault(
            "notification_submitter_and_decided_user_ids",
            submitter_and_decided,
        )

        domain_service = self.env["workflow.engine.assignment.domain.service"]

        def node_assigned_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="assigned",
            )

        def node_pending_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="pending",
            )

        def node_decided_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="decided",
            )

        eval_symbols.setdefault("node_assigned_approver_user_ids", node_assigned_approver_user_ids)
        eval_symbols.setdefault("node_pending_approver_user_ids", node_pending_approver_user_ids)
        eval_symbols.setdefault("node_decided_approver_user_ids", node_decided_approver_user_ids)
        eval_symbols.setdefault("create_uid", actor.id)
        eval_symbols.setdefault("write_uid", actor.id)
        return eval_symbols

    @api.model
    def _workflow_studio_normalize_domain_for_validation(
        self,
        domain,
        model_name,
        validation_scope=False,
    ):
        if isinstance(domain, tuple):
            domain = list(domain)
        if not isinstance(domain, list):
            return domain
        if (
            len(domain) >= 3
            and isinstance(domain[0], str)
            and domain[0] not in ("&", "|", "!")
        ):
            normalized = list(domain)
            if model_name == "res.users" or validation_scope == "assignment_users":
                normalized[0] = self._WF_USER_DOMAIN_FIELD_ALIASES.get(
                    normalized[0],
                    normalized[0],
                )
            return normalized
        return [
            self._workflow_studio_normalize_domain_for_validation(
                item,
                model_name,
                validation_scope=validation_scope,
            )
            for item in domain
        ]

    @api.model
    def _workflow_studio_validate_domain_literal(self, value, depth=1):
        if depth > self._WF_DOMAIN_MAX_DEPTH:
            raise UserError(_("Domain value nesting is too deep."))
        if isinstance(value, str):
            if len(value) > self._WF_DOMAIN_MAX_STRING_LENGTH:
                raise UserError(_("Domain literal value is too long."))
            return
        if isinstance(value, (int, float, bool, py_datetime.date, py_datetime.datetime)) or value is None:
            return
        if isinstance(value, (list, tuple, set)):
            if len(value) > self._WF_DOMAIN_MAX_ITEMS:
                raise UserError(_("Domain list value contains too many items."))
            for item in value:
                self._workflow_studio_validate_domain_literal(item, depth=depth + 1)
            return
        if isinstance(value, dict):
            if len(value) > self._WF_DOMAIN_MAX_ITEMS:
                raise UserError(_("Domain dictionary value contains too many keys."))
            for key, item in value.items():
                self._workflow_studio_validate_domain_literal(key, depth=depth + 1)
                self._workflow_studio_validate_domain_literal(item, depth=depth + 1)
            return
        raise UserError(_("Unsupported domain literal type: %s", type(value).__name__))

    @api.model
    def _workflow_studio_validate_domain_structure(self, model, domain, validation_scope=False):
        leaf_count = 0

        def _validate_leaf(leaf):
            nonlocal leaf_count
            if len(leaf) < 3:
                raise UserError(_("Domain condition is incomplete: %s", leaf))
            field_expr = leaf[0]
            operator = str(leaf[1] or "").strip().lower()
            expected = leaf[2]
            if not isinstance(field_expr, str) or not field_expr.strip():
                raise UserError(_("Domain field name must be a non-empty string."))
            if operator not in self._WF_DOMAIN_ALLOWED_OPERATORS:
                raise UserError(_("Unsupported domain operator: %s", operator))
            if validation_scope == "field_modifiers":
                root = field_expr.split(".")[0]
                if root not in model._fields and root not in self._WF_RUNTIME_DOMAIN_FIELDS:
                    raise UserError(_("Unknown runtime/domain field: %s", field_expr))
            self._workflow_studio_validate_domain_literal(expected, depth=1)
            leaf_count += 1
            if leaf_count > self._WF_DOMAIN_MAX_LEAFS:
                raise UserError(_("Domain has too many conditions. Please simplify it."))

        def _walk(node, depth=1):
            if depth > self._WF_DOMAIN_MAX_DEPTH:
                raise UserError(_("Domain nesting is too deep."))
            if isinstance(node, bool):
                return
            if not isinstance(node, (list, tuple)):
                raise UserError(_("Invalid domain token type: %s", type(node).__name__))
            if not node:
                return
            if (
                len(node) >= 3
                and isinstance(node[0], str)
                and node[0] not in ("&", "|", "!")
            ):
                _validate_leaf(node[:3])
                return
            head = node[0]
            if head in ("&", "|"):
                tokens = list(node)

                def _consume_token(token_depth):
                    if not tokens:
                        raise UserError(_("Domain logical operator is missing an operand."))
                    token = tokens.pop(0)
                    if token in ("&", "|"):
                        _consume_token(token_depth + 1)
                        _consume_token(token_depth + 1)
                        return
                    if token == "!":
                        _consume_token(token_depth + 1)
                        return
                    _walk(token, token_depth)

                _consume_token(depth + 1)
                while tokens:
                    _consume_token(depth + 1)
                return
            if head == "!":
                tokens = list(node)

                def _consume_not_token(token_depth):
                    if not tokens:
                        raise UserError(_("Domain logical operator is missing an operand."))
                    token = tokens.pop(0)
                    if token in ("&", "|"):
                        _consume_not_token(token_depth + 1)
                        _consume_not_token(token_depth + 1)
                        return
                    if token == "!":
                        _consume_not_token(token_depth + 1)
                        return
                    _walk(token, token_depth)

                _consume_not_token(depth + 1)
                while tokens:
                    _consume_not_token(depth + 1)
                return
            for item in node:
                _walk(item, depth + 1)

        _walk(domain, depth=1)

    @api.model
    def _workflow_studio_is_routing_validation_scope(self, validation_scope):
        return (validation_scope or "").strip() in {
            "assignment_users_routing",
            "request_scope_routing",
        }

    @api.model
    def _workflow_studio_base_validation_scope(self, validation_scope):
        normalized_scope = (validation_scope or "").strip()
        return {
            "assignment_users_routing": "assignment_users",
            "request_scope_routing": "request_scope",
        }.get(normalized_scope, normalized_scope)

    @api.model
    def _workflow_studio_routing_validation_warning(self, domain_state, error_message=""):
        if domain_state == "ignored_blank":
            return _(
                "Blank routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            )
        if domain_state == "ignored_empty":
            return _(
                "Empty [] routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            )
        if domain_state == "ignored_invalid":
            return (
                error_message
                or _(
                    "Invalid routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
                )
            )
        return ""

    @api.model
    def workflow_studio_validate_domain_expression(
        self,
        res_model_name,
        domain_expression,
        validation_scope=False,
        request_model_name=False,
    ):
        self._workflow_studio_check_designer_access()

        model_name = (res_model_name or "").strip()
        if not model_name:
            return {"valid": False, "error": _("Missing target model.")}

        normalized_scope = (validation_scope or "").strip()
        base_scope = self._workflow_studio_base_validation_scope(normalized_scope)
        is_routing_scope = self._workflow_studio_is_routing_validation_scope(normalized_scope)
        expression = self._workflow_studio_normalize_inline_domain_text(
            domain_expression,
            keep_false_literal=True,
        )
        if not expression and not is_routing_scope:
            expression = "[]"
        if len(expression) > self._WF_DOMAIN_MAX_EXPR_LENGTH:
            return {
                "valid": False,
                "error": _("Domain expression is too large. Please simplify it."),
            }
        try:
            Model = self.env[model_name].sudo()
        except KeyError:
            return {"valid": False, "error": _("Unknown target model: %s", model_name)}
        sample_record = Model.search([], limit=1)
        if not sample_record:
            sample_record = Model.new({})

        request_sample_record = sample_record
        request_model = (request_model_name or "").strip()
        if request_model:
            try:
                RequestModel = self.env[request_model].sudo()
            except KeyError:
                return {"valid": False, "error": _("Unknown request model: %s", request_model)}
            request_sample_record = RequestModel.search([], limit=1)
            if not request_sample_record:
                request_sample_record = RequestModel.new({})

        eval_context = self._workflow_studio_domain_eval_symbols(
            sample_record=sample_record,
            request_sample_record=request_sample_record,
        )
        eval_context.update(
            self._workflow_studio_actor_eval_helpers(
                self.env.user.sudo(),
                request_sample_record,
            )
        )
        domain_service = self.env["workflow.engine.assignment.domain.service"].sudo()
        field_rule_service = self.env["workflow.engine.field.rule.service"].sudo()
        if is_routing_scope:
            classification = domain_service._classify_routing_domain_literal(expression)
            state = classification.get("domain_state") or "active_valid"
            if state in {"ignored_blank", "ignored_empty", "always_true", "always_false"}:
                return {
                    "valid": True,
                    "error": "",
                    "warning": self._workflow_studio_routing_validation_warning(
                        state,
                        classification.get("error_message") or "",
                    ),
                    "ignored": state.startswith("ignored"),
                    "domain_state": state,
                }

        try:
            domain = safe_eval(expression, eval_context)
            if isinstance(domain, bool):
                return {"valid": True, "error": "", "warning": "", "ignored": False, "domain_state": "active_valid"}
            if isinstance(domain, tuple):
                domain = list(domain)
            if not isinstance(domain, (list, tuple)):
                raise UserError(_("Domain expression must return a list or tuple."))
            domain = domain_service._expand_domain_symbol_values(
                list(domain),
                eval_context,
            )
            normalized_domain = self._workflow_studio_normalize_domain_for_validation(
                list(domain),
                model_name,
                validation_scope=base_scope,
            )
            normalized_domain = field_rule_service._normalize_constant_workflow_domain(
                normalized_domain
            )
            if isinstance(normalized_domain, bool):
                return {
                    "valid": True,
                    "error": "",
                    "warning": "",
                    "ignored": False,
                    "domain_state": "active_valid",
                }
            self._workflow_studio_validate_domain_structure(
                Model,
                normalized_domain,
                validation_scope=base_scope,
            )
            if base_scope not in {"field_modifiers", "request_scope"}:
                Model.search(normalized_domain, limit=1)
        except Exception as exc:
            if is_routing_scope:
                warning = self._workflow_studio_routing_validation_warning(
                    "ignored_invalid",
                    str(exc),
                )
                return {
                    "valid": True,
                    "error": "",
                    "warning": warning,
                    "ignored": True,
                    "domain_state": "ignored_invalid",
                }
            return {"valid": False, "error": str(exc)}

        return {
            "valid": True,
            "error": "",
            "warning": "",
            "ignored": False,
            "domain_state": "active_valid",
        }

    @api.model
    def _workflow_studio_normalize_inline_domain_text(self, domain_value, keep_false_literal=True):
        if not domain_value:
            return ""
        if isinstance(domain_value, (list, tuple)):
            try:
                domain_value = json.dumps(domain_value)
            except Exception:
                return ""
        if not isinstance(domain_value, str):
            return ""
        normalized = re.sub(r"[\u200B-\u200D\uFEFF]", "", domain_value).strip()
        if not keep_false_literal and normalized.lower() in {"false", "0", "none", "null"}:
            return ""
        return normalized

    @api.model
    def _workflow_studio_routing_scope_for_model(self, model_name):
        return "assignment_users_routing" if (model_name or "").strip() == "res.users" else "request_scope_routing"

    @api.model
    def _workflow_studio_routing_field_label(self, field_name):
        labels = {
            "assignment_user_domain": _("Assignment user domain"),
            "approval_group_domain": _("Approval group fallback user domain"),
            "notification_recipient_domain": _("Notification recipient domain"),
            "notification_recipient_filter_domain": _("Notification recipient filter domain"),
            "user_domain": _("Approval link user filter domain"),
            "domain": _("Approval link record domain"),
        }
        return labels.get(field_name, field_name or _("Routing domain"))

    @api.model
    def _workflow_studio_routing_warning_label(self, field_name, context_name=False):
        label = self._workflow_studio_routing_field_label(field_name)
        context_name_text = (context_name or "").strip()
        if not context_name_text:
            return label
        return _("%(label)s (%(context)s)") % {
            "label": label,
            "context": context_name_text,
        }

    @api.model
    def _workflow_studio_append_unique_warning(self, warnings, message):
        if warnings is None or not message:
            return
        if message not in warnings:
            warnings.append(message)

    @api.model
    def _workflow_studio_prepare_routing_domain_value(
        self,
        field_name,
        domain_value,
        target_model_name,
        request_model_name,
        warnings=None,
        warning_label=False,
    ):
        normalized = self._workflow_studio_normalize_inline_domain_text(
            domain_value,
            keep_false_literal=True,
        )
        validation = self.workflow_studio_validate_domain_expression(
            target_model_name,
            normalized,
            self._workflow_studio_routing_scope_for_model(target_model_name),
            request_model_name,
        )
        if not validation.get("valid"):
            raise UserError(validation.get("error") or _("Domain is invalid."))
        warning = validation.get("warning") or ""
        if warning:
            self._workflow_studio_append_unique_warning(
                warnings,
                _("%(label)s: %(warning)s")
                % {
                    "label": warning_label or self._workflow_studio_routing_field_label(field_name),
                    "warning": warning,
                },
            )
        return normalized

    @api.model
    def _workflow_studio_parse_inline_options_mapping(self, raw_value):
        if isinstance(raw_value, dict):
            return dict(raw_value)
        if not raw_value or not isinstance(raw_value, str):
            return {}
        text = html.unescape(raw_value).strip()
        if not text:
            return {}

        parsed = {}
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            return parsed

        try:
            parsed = safe_eval(text, {"__builtins__": {}}, {})
        except Exception:
            parsed = {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @api.model
    def _workflow_studio_assert_inline_domain_size(self, domain_expression, domain_label):
        normalized = self._workflow_studio_normalize_inline_domain_text(
            domain_expression,
            keep_false_literal=True,
        )
        if not normalized:
            return
        if len(normalized) > self._WF_INLINE_DOMAIN_MAX_EXPR_LENGTH:
            raise ValidationError(
                _(
                    "Workflow domain (%(label)s) is too large (%(size)s chars). "
                    "Use node Meta Fields for visible/readonly/required rules.",
                    label=domain_label,
                    size=len(normalized),
                )
            )

    @api.model
    def _workflow_studio_assert_no_unsupported_required_domain(
        self,
        *,
        source_label,
        attrs,
        options_map=False,
        options_raw=False,
        policy_domains_map=False,
        policy_domains_raw=False,
    ):
        # Backward-compatible no-op. Runtime required fields are now configured
        # only through node Meta Fields.
        return

    def _workflow_studio_collect_publish_validation_views(self):
        self.ensure_one()
        if not self.res_model_name:
            return self.env["ir.ui.view"]
        View = self.env["ir.ui.view"].sudo()
        inline_views = View.search(
            [
                ("model", "=", self.res_model_name),
                ("type", "=", "form"),
                "|",
                "|",
                ("arch_db", "ilike", "wf_"),
                ("arch_db", "ilike", "wf_policy_id"),
                ("arch_db", "ilike", "wf_policy_domains"),
            ]
        )
        return inline_views.exists()

    def _workflow_studio_validate_publish_field_policy_guardrails(self):
        self.ensure_one()
        version = self.sudo()
        if not version.res_model_name:
            return

        views_to_check = version._workflow_studio_collect_publish_validation_views()
        if not views_to_check:
            return
        Model = self.env[version.res_model_name].sudo()
        checked_view_ids = set()
        for view in views_to_check:
            if view.id in checked_view_ids:
                continue
            checked_view_ids.add(view.id)
            arch_text = ""
            try:
                view_data = Model.get_view(view_id=view.id, view_type="form")
                arch_text = (view_data or {}).get("arch") or ""
            except Exception:
                arch_text = ""
            if not arch_text:
                arch_text = view.arch_db or ""
            if not arch_text:
                continue
            try:
                root = etree.fromstring(arch_text.encode("utf-8"))
            except Exception:
                continue

            for node in root.xpath(".//field|.//group"):
                attrs = dict(node.attrib or {})
                if not attrs:
                    continue
                options_raw = attrs.get("options") or ""
                policy_domains_raw = attrs.get("wf_policy_domains") or ""
                options_map = self._workflow_studio_parse_inline_options_mapping(options_raw)
                policy_domains_map = self._workflow_studio_parse_inline_options_mapping(
                    policy_domains_raw
                )
                is_workflow_modifier_node = (
                    (attrs.get("widget") in {"wf_field", "wf_group"})
                    or bool(attrs.get("wf_policy_id") or attrs.get("wf_group_policy_id"))
                    or bool(policy_domains_map)
                    or any(key in attrs for key in self._WF_WORKFLOW_DOMAIN_ATTR_KEYS)
                    or any(key in options_map for key in self._WF_WORKFLOW_DOMAIN_ATTR_KEYS)
                )
                if not is_workflow_modifier_node:
                    continue

                node_name = attrs.get("name") or attrs.get("string") or attrs.get("id") or node.tag
                source_label = _(
                    "view=%(view)s node=%(node)s",
                    view=view.display_name or view.name or view.id,
                    node=node_name,
                )
                self._workflow_studio_assert_no_unsupported_required_domain(
                    source_label=source_label,
                    attrs=attrs,
                    options_map=options_map,
                    options_raw=options_raw,
                    policy_domains_map=policy_domains_map,
                    policy_domains_raw=policy_domains_raw,
                )
                for key in ("wf_visible_domain", "visible_domain", "wf_modifier_domain", "wf_domain"):
                    if key in attrs:
                        self._workflow_studio_assert_inline_domain_size(
                            attrs.get(key),
                            f"{source_label}.{key}",
                        )
                    if key in options_map:
                        self._workflow_studio_assert_inline_domain_size(
                            options_map.get(key),
                            f"{source_label}.options.{key}",
                        )
                for key in ("wf_readonly_domain", "readonly_domain"):
                    if key in attrs:
                        self._workflow_studio_assert_inline_domain_size(
                            attrs.get(key),
                            f"{source_label}.{key}",
                        )
                    if key in options_map:
                        self._workflow_studio_assert_inline_domain_size(
                            options_map.get(key),
                            f"{source_label}.options.{key}",
                        )
                for key in ("wf_required_domain", "wf_require_domain", "required_domain", "require_domain"):
                    if key in attrs:
                        self._workflow_studio_assert_inline_domain_size(
                            attrs.get(key),
                            f"{source_label}.{key}",
                        )
                    if key in options_map:
                        self._workflow_studio_assert_inline_domain_size(
                            options_map.get(key),
                            f"{source_label}.options.{key}",
                        )
                for key in ("visible", "readonly", "required"):
                    if key in policy_domains_map:
                        self._workflow_studio_assert_inline_domain_size(
                            policy_domains_map.get(key),
                            f"{source_label}.wf_policy_domains.{key}",
                        )

    def _workflow_studio_next_sequence(self, category):
        sequence = max(category.version_ids.mapped("sequence") or [0]) + 10
        return sequence or 10

    def _workflow_studio_sanitize_login(self, raw_login):
        login = re.sub(r"[^a-zA-Z0-9._-]+", ".", (raw_login or "").strip().lower())
        return login.strip(".")

    def _workflow_studio_next_available_login(self, raw_login):
        User = self.env["res.users"].sudo()
        base_login = self._workflow_studio_sanitize_login(raw_login) or "workflow.user"
        login = base_login
        suffix = 1
        while User.search_count([("login", "=", login)]):
            suffix += 1
            login = f"{base_login}.{suffix}"
        return login

    def _workflow_studio_user_groups_field(self):
        User = self.env["res.users"]
        if "group_ids" in User._fields:
            return "group_ids"
        return "groups_id" if "groups_id" in User._fields else False

    @staticmethod
    def _workflow_studio_rewrite_context_markers(xml_content):
        if not xml_content:
            return xml_content, 0
        if isinstance(xml_content, bytes):
            text = xml_content.decode("utf-8", errors="ignore")
        else:
            text = str(xml_content)
        rewritten, count = re.subn(
            r"([\"'])studio\1\s*:",
            r"\1workflow_studio\1:",
            text,
        )
        return rewritten.encode("utf-8"), count

    def _workflow_studio_serialize_template_option(self, template):
        template.ensure_one()
        return {
            "id": template.id,
            "name": template.name or "",
            "model": template.model or "",
        }

    def _workflow_studio_serialize_action_option(self, action):
        action.ensure_one()
        return {
            "id": action.id,
            "name": action.name or "",
            "res_model": action.res_model or "",
        }

    def _workflow_studio_serialize_user_option(self, user):
        user.ensure_one()
        employee = user.employee_id.sudo() if user.employee_id else self.env["hr.employee"]
        employee_code = (
            getattr(employee, "x_emp_code", False)
            or getattr(employee, "identification_id", False)
            or ""
        ) if employee else ""
        return {
            "id": user.id,
            "name": user.name or user.login or "",
            "login": user.login or "",
            "email": user.email or "",
            "employee_code": employee_code,
        }

    def _workflow_studio_approval_group_display_path(self, group):
        group.ensure_one()
        path_parts = []
        current = group
        while current:
            if current.name:
                path_parts.append(current.name)
            current = current.parent_id
        if not path_parts:
            return group.display_name or ""
        return " > ".join(reversed(path_parts))

    def _workflow_studio_serialize_approval_group_option(self, group):
        group.ensure_one()
        return {
            "id": group.id,
            "name": group.name or "",
            "display_path": self._workflow_studio_approval_group_display_path(group),
            "parent_id": group.parent_id.id if group.parent_id else False,
            "parent_name": group.parent_id.name if group.parent_id else "",
            "department_id": group.department_id.id if group.department_id else False,
            "department_name": group.department_id.name if group.department_id else "",
            "user_ids": group.user_ids.ids,
            "user_names": [user.name or user.login or "" for user in group.user_ids],
        }

    def _workflow_studio_normalize_catalog_search_text(self, value):
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    def _workflow_studio_search_approval_group_records(self, query=False):
        normalized_query = self._workflow_studio_normalize_catalog_search_text(query)
        approval_group_model = self.env["workflow.approval.group"].sudo()
        if not normalized_query:
            return approval_group_model.search([], order="name,id")

        tokens = [token for token in normalized_query.split(" ") if token]
        candidate_domains = []
        descendant_group_ids = set()
        for token in tokens:
            candidate_domains.extend([
                [("name", "ilike", token)],
                [("department_id.name", "ilike", token)],
                [("user_ids.name", "ilike", token)],
                [("user_ids.login", "ilike", token)],
            ])
            matching_name_groups = approval_group_model.search([("name", "ilike", token)])
            if matching_name_groups:
                descendant_group_ids.update(
                    approval_group_model.search([("id", "child_of", matching_name_groups.ids)]).ids
                )

        search_domain = Domain.OR(candidate_domains) if candidate_domains else Domain.TRUE
        if descendant_group_ids:
            descendant_domain = Domain("id", "in", list(descendant_group_ids))
            search_domain = Domain.OR([search_domain, descendant_domain])
        groups = approval_group_model.search(search_domain, order="name,id")

        matched_groups = approval_group_model.browse()
        for group in groups:
            option = self._workflow_studio_serialize_approval_group_option(group)
            haystack = self._workflow_studio_normalize_catalog_search_text(
                " ".join([
                    option.get("display_path") or "",
                    option.get("name") or "",
                    option.get("department_name") or "",
                    *[user_name or "" for user_name in option.get("user_names", [])],
                ])
            )
            if normalized_query in haystack or all(token in haystack for token in tokens):
                matched_groups |= group
        return matched_groups

    def _workflow_studio_search_approval_group_options(self, query=False):
        return [
            self._workflow_studio_serialize_approval_group_option(group)
            for group in self._workflow_studio_search_approval_group_records(query=query)
        ]

    def workflow_studio_search_approval_groups(self, query=False):
        self.ensure_one()
        rows = self._workflow_studio_search_approval_group_options(query=query)
        return {
            "rows": rows,
            "total": len(rows),
        }

    @api.model
    def _workflow_studio_catalog_routing_audit_state(self, domain_literal):
        normalized = self._workflow_studio_normalize_inline_domain_text(
            domain_literal,
            keep_false_literal=True,
        )
        if not normalized:
            return "ignored_blank"
        if re.sub(r"\s+", "", normalized) == "[]":
            return "ignored_empty"
        return "active_valid"

    @api.model
    def _workflow_studio_catalog_routing_audit_message(self, domain_state):
        if domain_state == "ignored_blank":
            return _(
                "Blank routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            )
        if domain_state == "ignored_empty":
            return _(
                "Empty [] routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
            )
        return ""

    @api.model
    def _workflow_studio_catalog_member_names(self, group):
        group.ensure_one()
        member_names = []
        for user in group.user_ids:
            label = (user.name or user.login or "").strip()
            if label and label.lower() != "nan":
                member_names.append(label)
        return member_names

    @api.model
    def _workflow_studio_catalog_member_summary(self, member_names, limit=False):
        names = [name for name in member_names or [] if name]
        if not names:
            return _("No users assigned")
        if not limit or len(names) <= limit:
            return ", ".join(names)
        return _("%(names)s +%(count)s more") % {
            "names": ", ".join(names[:limit]),
            "count": len(names) - limit,
        }

    @api.model
    def _workflow_studio_normalize_browser_approval_link_rows(self, approval_link_rows=False):
        normalized_rows = []
        for row in approval_link_rows or []:
            if not isinstance(row, dict):
                continue
            raw_ref = row.get("approval_group_ref")
            group_id = False
            if isinstance(raw_ref, dict):
                try:
                    group_id = int(raw_ref.get("id") or 0) or False
                except Exception:
                    group_id = False
            if not group_id:
                try:
                    group_id = int(
                        row.get("approval_group_id")
                        or row.get("group_id")
                        or 0
                    ) or False
                except Exception:
                    group_id = False
            if not group_id:
                continue
            normalized_rows.append({
                "approval_group_id": group_id,
                "user_domain": self._workflow_studio_normalize_inline_domain_text(
                    row.get("user_domain"),
                    keep_false_literal=True,
                ),
                "domain": self._workflow_studio_normalize_inline_domain_text(
                    row.get("domain"),
                    keep_false_literal=True,
                ),
            })
        return normalized_rows

    @api.model
    def _workflow_studio_group_link_rows_by_group_id(self, approval_link_rows=False):
        rows_by_group_id = defaultdict(list)
        for row in self._workflow_studio_normalize_browser_approval_link_rows(approval_link_rows):
            rows_by_group_id[row["approval_group_id"]].append(row)
        return rows_by_group_id

    @api.model
    def _workflow_studio_build_approval_group_browser_warnings(self, linked_rows=False):
        linked_rows = linked_rows or []
        if not linked_rows:
            return []
        field_specs = [
            {
                "field_name": "user_domain",
                "blank_label": _("User Filter Blank"),
                "empty_label": _("User Filter []"),
            },
            {
                "field_name": "domain",
                "blank_label": _("Record Domain Blank"),
                "empty_label": _("Record Domain []"),
            },
        ]
        warnings = []
        for field_spec in field_specs:
            for domain_state in ("ignored_blank", "ignored_empty"):
                affected_count = len([
                    row for row in linked_rows
                    if self._workflow_studio_catalog_routing_audit_state(
                        row.get(field_spec["field_name"])
                    ) == domain_state
                ])
                if not affected_count:
                    continue
                base_message = self._workflow_studio_catalog_routing_audit_message(domain_state)
                warning_title = base_message
                if affected_count > 1:
                    warning_title = _(
                        "%(count)s linked rules on this node use this value. %(message)s"
                    ) % {
                        "count": affected_count,
                        "message": base_message,
                    }
                warnings.append({
                    "key": f"{field_spec['field_name']}:{domain_state}",
                    "label": (
                        field_spec["blank_label"]
                        if domain_state == "ignored_blank"
                        else field_spec["empty_label"]
                    ),
                    "title": warning_title,
                })
        return warnings

    @api.model
    def _workflow_studio_serialize_approval_group_browser_row(self, group, linked_rows=False):
        group.ensure_one()
        option = self._workflow_studio_serialize_approval_group_option(group)
        member_names = self._workflow_studio_catalog_member_names(group)
        linked_rows = linked_rows or []
        return {
            **option,
            "key": group.id,
            "is_linked": bool(linked_rows),
            "linked_count": len(linked_rows),
            "members_summary": self._workflow_studio_catalog_member_summary(member_names),
            "member_preview": self._workflow_studio_catalog_member_summary(member_names, limit=3),
            "user_count": len(member_names),
            "routing_warnings": self._workflow_studio_build_approval_group_browser_warnings(
                linked_rows
            ),
            "user_names": member_names,
        }

    @api.model
    def _workflow_studio_approval_group_browser_row_matches_filters(
        self,
        row,
        mode="all",
        routing_filter="all",
    ):
        mode = (mode or "all").strip() or "all"
        routing_filter = (routing_filter or "all").strip() or "all"
        is_linked = bool(row.get("is_linked"))
        if mode == "linked" and not is_linked:
            return False
        if mode == "available" and is_linked:
            return False
        warnings = row.get("routing_warnings") or []
        if routing_filter == "all":
            return True
        if routing_filter == "needs_config":
            return bool(warnings)
        return any(warning.get("key") == routing_filter for warning in warnings)

    def workflow_studio_browse_approval_groups(self, options=False):
        self.ensure_one()
        options = dict(options or {})
        query = options.get("query") or False
        mode = options.get("mode") or "all"
        routing_filter = options.get("routing_filter") or "all"
        try:
            offset = max(int(options.get("offset") or 0), 0)
        except Exception:
            offset = 0
        try:
            limit = max(int(options.get("limit") or 40), 1)
        except Exception:
            limit = 40

        approval_group_model = self.env["workflow.approval.group"].sudo()
        linked_rows_by_group_id = self._workflow_studio_group_link_rows_by_group_id(
            options.get("approval_link_rows")
        )
        rows = []
        for group in self._workflow_studio_search_approval_group_records(query=query):
            row = self._workflow_studio_serialize_approval_group_browser_row(
                group,
                linked_rows=linked_rows_by_group_id.get(group.id, []),
            )
            if self._workflow_studio_approval_group_browser_row_matches_filters(
                row,
                mode=mode,
                routing_filter=routing_filter,
            ):
                rows.append(row)

        rows.sort(
            key=lambda row: (
                0 if row.get("is_linked") else 1,
                self._workflow_studio_normalize_catalog_search_text(
                    row.get("display_path") or row.get("name") or ""
                ),
                int(row.get("id") or 0),
            )
        )
        total = len(rows)
        paged_rows = rows[offset: offset + limit]
        return {
            "rows": paged_rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(paged_rows) < total,
            "linked_count": len(linked_rows_by_group_id),
            "total_groups": approval_group_model.search_count([]),
        }

    def _workflow_studio_serialize_res_group_option(self, group):
        group.ensure_one()
        user_field = "user_ids" if "user_ids" in group._fields else "users"
        users = group[user_field] if user_field in group._fields else self.env["res.users"]
        return {
            "id": group.id,
            "name": group.display_name or group.name or "",
            "user_ids": users.ids,
            "user_names": [user.name or user.login or "" for user in users],
        }

    def _workflow_studio_serialize_email_recipient_line(self, line):
        line.ensure_one()
        return {
            "id": line.id,
            "sequence": line.sequence or 10,
            "header": line.header or "to",
            "source": line.source or "send_task",
            "raw_emails": line.raw_emails or "",
            "user_ids": line.user_ids.ids,
            "approval_group_ids": line.approval_group_ids.ids,
            "group_ids": line.group_ids.ids,
            "node_ref": line.node_ref or "",
            "node_user_type": line.node_user_type or "assigned",
            "domain": line.domain or "",
        }

    def _workflow_studio_has_email_recipient_line_table(self):
        self.env.cr.execute("SELECT to_regclass(%s)", ["workflow_approval_action_email_recipient"])
        return bool((self.env.cr.fetchone() or [False])[0])

    def _workflow_studio_serialize_workflow_action_email_recipient_lines(self, action):
        if action.action_type != "email":
            return []
        if not self._workflow_studio_has_email_recipient_line_table():
            return []
        return [
            self._workflow_studio_serialize_email_recipient_line(line)
            for line in action.email_recipient_line_ids.sorted(key=lambda row: (row.sequence or 10, row.id))
        ]

    def _workflow_studio_serialize_workflow_action_option(self, action):
        action.ensure_one()
        return {
            "id": action.id,
            "name": action.name or "",
            "action_type": action.action_type or "workflow",
            "message_body": action.message_body or "",
            "telegram_webhook_url": action.telegram_webhook_url or "",
            "webhook_url": action.webhook_url or "",
            "domain": action.domain or "",
            "domain_string": action.domain_string or "",
            "code": action.code or "",
            "version_id": action.version_id.id if action.version_id else False,
            "email_template_id": action.email_template_id.id if action.email_template_id else False,
            "email_template_name": action.email_template_id.name if action.email_template_id else "",
            "email_recipient_lines": self._workflow_studio_serialize_workflow_action_email_recipient_lines(action),
            "server_action_id": action.server_action_id.id if action.server_action_id else False,
            "server_action_name": action.server_action_id.name if action.server_action_id else "",
        }

    def _workflow_studio_serialize_server_action_option(self, server_action):
        server_action.ensure_one()
        return {
            "id": server_action.id,
            "name": server_action.name or "",
            "model_name": server_action.model_name or "",
            "state": server_action.state or "",
        }

    def _workflow_studio_lifecycle_state(self):
        self.ensure_one()
        if self.is_active and self.is_published:
            return "published"
        if self.is_active:
            return "deployed"
        if self.is_published:
            return "published"
        if self.deployed_at:
            return "retired"
        return "draft"

    def _workflow_studio_lifecycle_label(self):
        state = self._workflow_studio_lifecycle_state()
        return LIFECYCLE_STATE_LABELS.get(state, state.title())

    def _workflow_studio_find_rollback_candidate(self, category, current_version=False):
        domain = [("category_id", "=", category.id)]
        if current_version:
            domain.append(("id", "!=", current_version.id))
        domain += ["|", ("is_published", "=", True), ("deployed_at", "!=", False)]
        return self.sudo().search(
            domain,
            order="is_published desc, published_at desc, deployed_at desc, sequence desc, id desc",
            limit=1,
        )

    def _workflow_studio_validate_activation_target(self, target_version):
        target_version.ensure_one()
        if not (target_version.bpmn_xml or "").strip():
            raise UserError(
                _(
                    "Version '%(version)s' cannot be activated because BPMN XML is empty."
                )
                % {"version": target_version.display_name or target_version.name or target_version.id}
            )
        try:
            target_version.sync_meta_from_bpmn(target_version.bpmn_xml or "")
        except Exception as error:
            raise UserError(
                _(
                    "Version '%(version)s' cannot be activated because BPMN is invalid: %(error)s"
                )
                % {
                    "version": target_version.display_name or target_version.name or target_version.id,
                    "error": str(error),
                }
            ) from error
        target_version._workflow_studio_validate_conditional_events_for_activation()

    def _workflow_studio_validate_conditional_events_for_activation(self):
        self.ensure_one()
        version = self.sudo()
        if not (version.bpmn_xml or "").strip():
            return
        try:
            root = etree.fromstring(version.bpmn_xml.encode("utf-8"))
        except Exception as error:
            raise UserError(
                _("Version '%(version)s' has invalid BPMN XML: %(error)s")
                % {
                    "version": version.display_name or version.name or version.id,
                    "error": str(error),
                }
            ) from error

        conditional_events = root.xpath(
            ".//*[local-name()='intermediateCatchEvent'][./*[local-name()='conditionalEventDefinition']]"
        )
        for event in conditional_events:
            node_id = event.get("id") or ""
            node_name = event.get("name") or node_id or _("Unnamed Conditional Event")
            outgoing_ids = [
                (outgoing.text or "").strip()
                for outgoing in event.xpath("./*[local-name()='outgoing']")
                if (outgoing.text or "").strip()
            ]
            if len(outgoing_ids) != 2:
                raise UserError(
                    _(
                        "Conditional Event '%(node)s' must have exactly 2 outgoing flows before this version can be activated."
                    )
                    % {"node": node_name}
                )
            default_flow_id = event.get("default") or ""
            if not default_flow_id or default_flow_id not in outgoing_ids:
                raise UserError(
                    _(
                        "Conditional Event '%(node)s' must have exactly one BPMN default outgoing flow before this version can be activated."
                    )
                    % {"node": node_name}
                )

            meta_task = version.meta_task_ids.filtered(lambda task: task.node_id == node_id)[:1]
            condition_domain = (meta_task.automation_condition_domain or "").strip() if meta_task else ""
            if not condition_domain:
                continue
            validation = version.workflow_studio_validate_domain_expression(
                version.res_model_name,
                condition_domain,
                "field_modifiers",
                version.res_model_name,
            )
            if not validation.get("valid"):
                raise UserError(
                    _(
                        "Conditional Event '%(node)s' has an invalid condition domain: %(error)s"
                    )
                    % {
                        "node": node_name,
                        "error": validation.get("error") or _("Domain is invalid."),
                    }
                )

    def _workflow_studio_resolve_rollback_target(self, requested_target=False):
        current_version = self._workflow_studio_get_version(allow_locked=True)
        category = current_version.category_id.sudo()
        active_version = category.active_version_id.sudo()

        rollback_target = requested_target.sudo() if requested_target else self.browse()
        if rollback_target:
            if rollback_target.category_id.id != category.id:
                raise UserError(
                    _("Rollback target must belong to the same workflow category.")
                )
        elif current_version.is_active:
            rollback_target = current_version._workflow_studio_find_rollback_candidate(
                category, current_version=current_version
            )
            if not rollback_target:
                raise UserError(
                    _("No previously deployed or published version is available for rollback.")
                )
        else:
            rollback_target = current_version.sudo()

        if not (rollback_target.is_published or rollback_target.deployed_at):
            raise UserError(
                _(
                    "You can only rollback to a version that was previously deployed or published."
                )
            )
        if active_version and rollback_target.id == active_version.id:
            raise UserError(_("Selected version is already active."))
        return rollback_target, active_version

    def _workflow_studio_activate_version(self, target_version, *, publish=False):
        target_version = target_version.sudo()
        category = target_version.category_id.sudo()
        now = fields.Datetime.now()

        self.sudo().search(
            [
                ("category_id", "=", category.id),
                ("is_active", "=", True),
                ("id", "!=", target_version.id),
            ]
        ).write({"is_active": False})

        vals = {
            "is_active": True,
            "deployed_at": now,
        }
        if publish:
            vals.update(
                {
                    "is_published": True,
                    "published_at": now,
                    "is_locked": True,
                }
            )
        if publish:
            target_version.with_context(allow_version_lock_write=True).write(vals)
        else:
            target_version.write(vals)
        category.active_version_id = target_version.id
        return target_version

    def _workflow_studio_build_version_control(self, category):
        versions = self.sudo().search(
            [("category_id", "=", category.id)],
            order="sequence desc, id desc",
        )
        active_version = category.active_version_id.sudo()
        if not active_version:
            active_version = versions.filtered("is_active")[:1].sudo()
        rollback_candidate = self.browse()
        if active_version:
            rollback_candidate = self._workflow_studio_find_rollback_candidate(
                category, current_version=active_version
            )
        return {
            "active_version_id": active_version.id if active_version else False,
            "rollback_candidate_id": rollback_candidate.id if rollback_candidate else False,
            "versions": [
                {
                    "id": version.id,
                    "name": version.name or "",
                    "title": version.title or "",
                    "display_name": version.display_name or version.name or "",
                    "sequence": version.sequence or 0,
                    "is_active": bool(version.is_active),
                    "is_locked": bool(version.is_locked),
                    "is_published": bool(version.is_published),
                    "deployed_at": fields.Datetime.to_string(version.deployed_at)
                    if version.deployed_at
                    else False,
                    "published_at": fields.Datetime.to_string(version.published_at)
                    if version.published_at
                    else False,
                    "lifecycle_state": version._workflow_studio_lifecycle_state(),
                    "lifecycle_label": version._workflow_studio_lifecycle_label(),
                    "can_deploy": not bool(version.is_active),
                    "can_publish": not bool(version.is_published and version.is_active),
                    "can_rollback": (
                        (
                            not bool(version.is_active)
                            and bool(version.is_published or version.deployed_at)
                        )
                        or (
                            bool(version.is_active)
                            and bool(
                                self._workflow_studio_find_rollback_candidate(
                                    category, current_version=version
                                )
                            )
                        )
                    ),
                    "write_date": fields.Datetime.to_string(version.write_date)
                    if version.write_date
                    else False,
                }
                for version in versions
            ],
        }

    def workflow_studio_get_version_control(self):
        version = self._workflow_studio_get_version()
        return version._workflow_studio_build_version_control(version.category_id)

    def workflow_studio_create_version(self, values=False):
        version = self._workflow_studio_get_version()
        category = version.category_id.sudo()
        values = values or {}
        title = (values.get("title") or "").strip()
        copy_from_version_id = values.get("copy_from_version_id")

        source_version = self.browse()
        if copy_from_version_id:
            source_version = self.sudo().browse(int(copy_from_version_id)).exists()
            if not source_version:
                raise UserError(_("The selected source version does not exist."))
            if source_version.category_id.id != category.id:
                raise UserError(
                    _("The selected source version must belong to the same workflow category.")
                )

        default_vals = {
            "category_id": category.id,
            "name": "New",
            "title": title,
            "sequence": self._workflow_studio_next_sequence(category),
            "is_active": False,
            "is_locked": False,
            "is_published": False,
            "deployed_at": False,
            "published_at": False,
        }
        if source_version:
            new_version = source_version.copy(default=default_vals)
        else:
            new_version = self.sudo().create(default_vals)

        if not title and copy_from_version_id and source_version:
            new_version.title = source_version.title or ""

        return {
            "version_id": new_version.id,
            "version_control": new_version._workflow_studio_build_version_control(category),
        }

    def workflow_studio_duplicate_version(self):
        version = self._workflow_studio_get_version()
        category = version.category_id.sudo()
        duplicate_version = version.copy(
            default={
                "name": "New",
                "title": version.title or "",
                "sequence": self._workflow_studio_next_sequence(category),
                "is_active": False,
                "is_locked": False,
                "is_published": False,
                "deployed_at": False,
                "published_at": False,
            }
        )
        return {
            "version_id": duplicate_version.id,
            "version_control": duplicate_version._workflow_studio_build_version_control(category),
        }

    def workflow_studio_copy_to_version(self, target_version_id):
        source_version = self._workflow_studio_get_version()
        if not target_version_id:
            raise UserError(_("Please select a target version to copy into."))

        target_version = self.sudo().browse(int(target_version_id)).exists()
        if not target_version:
            raise UserError(_("Target version not found."))
        if target_version.id == source_version.id:
            raise UserError(_("Please select a different target version."))
        if target_version.category_id.id != source_version.category_id.id:
            raise UserError(_("You can only copy into versions from the same category."))

        target_version = target_version._workflow_studio_get_version(require_write=True)
        source_payload = source_version.workflow_studio_get_bpmn_payload()
        source_meta = source_payload.get("meta", {})

        target_version.write(
            {
                "title": source_version.title or "",
                "change_log": source_version.change_log or "",
                "bpmn_xml": source_version.bpmn_xml or "",
            }
        )
        target_version.sync_meta_from_bpmn(target_version.bpmn_xml or "")
        warnings = target_version._workflow_studio_apply_imported_metadata(source_meta or {})
        payload = target_version.workflow_studio_get_bpmn_payload()

        return {
            "payload": payload,
            "version_id": target_version.id,
            "warnings": warnings,
        }

    def workflow_studio_create_activity_template(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        values = values or {}
        name = (values.get("name") or "").strip()
        if not name:
            raise UserError(_("Template name is required."))

        model_name = "workflow.category.version.meta.task"
        model_id = self.env["ir.model"].sudo()._get_id(model_name)
        if not model_id:
            raise UserError(_("Cannot create template: target model was not found."))

        subject = (values.get("subject") or "").strip() or name
        body_html = (values.get("body_html") or "").strip() or "<div/>"
        template = self.env["mail.template"].sudo().create(
            {
                "name": name,
                "model_id": model_id,
                "subject": subject,
                "body_html": body_html,
            }
        )
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "template": self._workflow_studio_serialize_template_option(template),
            "payload": payload,
        }

    def workflow_studio_create_action_window(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        values = values or {}
        name = (values.get("name") or "").strip()
        if not name:
            raise UserError(_("Action name is required."))
        if not version.res_model_name:
            raise UserError(_("Cannot create action window because target model is missing."))

        model = version.res_model_id.sudo() if version.res_model_id else self.env["ir.model"].sudo()._get(version.res_model_name)
        default_view_mode = "form" if model and model.transient else "list,form"
        default_target = "new" if model and model.transient else "current"
        view_mode = (values.get("view_mode") or "").strip() or default_view_mode
        target = (values.get("target") or "").strip() or default_target
        if target not in {"current", "new"}:
            target = default_target

        action = self.env["ir.actions.act_window"].sudo().create(
            {
                "name": name,
                "res_model": version.res_model_name,
                "view_mode": view_mode,
                "target": target,
            }
        )
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "action": self._workflow_studio_serialize_action_option(action),
            "payload": payload,
        }

    def workflow_studio_create_email_template(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        values = values or {}
        name = (values.get("name") or "").strip()
        if not name:
            raise UserError(_("Template name is required."))
        if not version.res_model_name:
            raise UserError(_("Cannot create template: target model was not found."))

        model_id = version.res_model_id.id or self.env["ir.model"].sudo()._get_id(version.res_model_name)
        if not model_id:
            raise UserError(_("Cannot create template: target model was not found."))

        subject = (values.get("subject") or "").strip() or name
        body_html = (values.get("body_html") or "").strip() or "<div/>"
        template = self.env["mail.template"].sudo().create(
            {
                "name": name,
                "model_id": model_id,
                "subject": subject,
                "body_html": body_html,
            }
        )
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "template": self._workflow_studio_serialize_template_option(template),
            "payload": payload,
        }

    def workflow_studio_create_notification_recipient(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        values = values or {}
        name = (values.get("name") or "").strip()
        email = (values.get("email") or "").strip()
        login = self._workflow_studio_sanitize_login(values.get("login"))
        if not name:
            raise UserError(_("Recipient name is required."))

        User = self.env["res.users"].sudo().with_context(no_reset_password=True)
        existing_user = User.browse()
        if login:
            existing_user = User.search([("login", "=", login)], limit=1)
        if not existing_user and email:
            existing_user = User.search([("email", "=", email)], limit=1)

        if existing_user:
            payload = version.workflow_studio_get_bpmn_payload()
            return {
                "user": self._workflow_studio_serialize_user_option(existing_user),
                "existing": True,
                "payload": payload,
            }

        if not login:
            login_source = email.split("@")[0] if email and "@" in email else name
            login = self._workflow_studio_next_available_login(login_source)
        elif User.search_count([("login", "=", login)]):
            login = self._workflow_studio_next_available_login(login)

        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        groups_field = self._workflow_studio_user_groups_field()
        user_vals = {
            "name": name,
            "login": login,
            "email": email or False,
            "active": True,
        }
        if group_user and groups_field:
            user_vals[groups_field] = [(6, 0, [group_user.id])]
        if self.env.company:
            user_vals["company_id"] = self.env.company.id
            user_vals["company_ids"] = [(4, self.env.company.id)]

        user = User.create(user_vals)
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "user": self._workflow_studio_serialize_user_option(user),
            "existing": False,
            "payload": payload,
        }

    def _workflow_studio_prepare_workflow_action_values(self, values):
        values = values or {}
        if not isinstance(values, dict):
            return {}

        clean = {}
        if "name" in values:
            clean["name"] = (values.get("name") or "").strip()
        if "action_type" in values:
            clean["action_type"] = (values.get("action_type") or "").strip() or "workflow"
        if "message_body" in values:
            clean["message_body"] = values.get("message_body") or ""
        if "telegram_webhook_url" in values:
            clean["telegram_webhook_url"] = (values.get("telegram_webhook_url") or "").strip()
        if "webhook_url" in values:
            clean["webhook_url"] = (values.get("webhook_url") or "").strip()
        if "domain" in values:
            clean["domain"] = (values.get("domain") or "").strip()
        if "domain_string" in values:
            clean["domain_string"] = (values.get("domain_string") or "").strip()
        if "code" in values:
            clean["code"] = values.get("code") or ""

        if "email_template_ref" in values:
            template = self._workflow_studio_resolve_template_ref(values.get("email_template_ref"))
            clean["email_template_id"] = template.id if template else False
        elif "email_template_id" in values:
            template_id = int(values.get("email_template_id") or 0)
            template = self.env["mail.template"].sudo().browse(template_id).exists()
            clean["email_template_id"] = template.id if template else False

        if "server_action_id" in values:
            server_action_id = int(values.get("server_action_id") or 0)
            server_action = self.env["ir.actions.server"].sudo().browse(server_action_id).exists()
            clean["server_action_id"] = server_action.id if server_action else False

        if "email_recipient_lines" in values:
            clean["email_recipient_line_ids"] = self._workflow_studio_prepare_email_recipient_line_commands(
                values.get("email_recipient_lines") or []
            )
        if clean.get("action_type") and clean["action_type"] != "email":
            clean["email_template_id"] = False
            clean["email_recipient_line_ids"] = [(5, 0, 0)]

        allowed_action_types = {item["value"] for item in WORKFLOW_ACTION_TYPE_OPTIONS}
        action_type = clean.get("action_type")
        if action_type and action_type not in allowed_action_types:
            raise UserError(_("Unsupported workflow action type: %s") % action_type)
        return clean

    def _workflow_studio_prepare_email_recipient_line_commands(self, rows):
        if not isinstance(rows, list):
            return [(5, 0, 0)]
        allowed_headers = {"to", "cc", "bcc"}
        allowed_sources = {
            "direct",
            "send_task",
            "specific_users",
            "approval_group_users",
            "group_users",
            "node_users",
            "domain",
        }
        commands = [(5, 0, 0)]
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            header = (row.get("header") or "to").strip()
            source = (row.get("source") or "send_task").strip()
            if header not in allowed_headers:
                header = "to"
            if source not in allowed_sources:
                source = "send_task"
            line_values = {
                "sequence": int(row.get("sequence") or index * 10),
                "header": header,
                "source": source,
                "raw_emails": row.get("raw_emails") or "",
                "node_ref": (row.get("node_ref") or "").strip(),
                "node_user_type": (row.get("node_user_type") or "assigned").strip() or "assigned",
                "domain": (row.get("domain") or "").strip(),
                "user_ids": [(6, 0, row.get("user_ids") or [])],
                "approval_group_ids": [(6, 0, row.get("approval_group_ids") or [])],
                "group_ids": [(6, 0, row.get("group_ids") or [])],
            }
            commands.append((0, 0, line_values))
        return commands

    def workflow_studio_create_workflow_action(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        prepared = self._workflow_studio_prepare_workflow_action_values(values or {})
        if not prepared.get("name"):
            raise UserError(_("Action name is required."))
        prepared.setdefault("version_id", version.id)
        workflow_action = self.env["workflow.approval.action"].sudo().create(prepared)
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "workflow_action": self._workflow_studio_serialize_workflow_action_option(workflow_action),
            "payload": payload,
        }

    def _workflow_studio_build_task_scoped_workflow_action_name(self, version, workflow_action, task):
        WorkflowAction = self.env["workflow.approval.action"].sudo()
        base_name = (workflow_action.name or _("Workflow Action")).strip() or _("Workflow Action")
        task_scope = (task.name or task.node_id or "").strip()
        if not task_scope:
            return base_name
        candidate = f"{base_name} [{task_scope}]"
        if not WorkflowAction.search_count(
            [("version_id", "=", version.id), ("name", "=", candidate)]
        ):
            return candidate

        suffix = 2
        while True:
            fallback = f"{candidate} ({suffix})"
            if not WorkflowAction.search_count(
                [("version_id", "=", version.id), ("name", "=", fallback)]
            ):
                return fallback
            suffix += 1

    def _workflow_studio_isolate_workflow_action_for_task(self, version, workflow_action, task):
        MetaTask = self.env["workflow.category.version.meta.task"].sudo()
        linked_tasks = MetaTask.search(
            [
                ("version_id", "=", version.id),
                ("activity_type_ids", "in", workflow_action.id),
            ]
        )
        if len(linked_tasks) <= 1 or task not in linked_tasks:
            return workflow_action, False

        isolated_action = workflow_action.copy(
            {
                "name": self._workflow_studio_build_task_scoped_workflow_action_name(
                    version, workflow_action, task
                ),
                "version_id": version.id,
            }
        )
        replacement_ids = [action_id for action_id in task.activity_type_ids.ids if action_id != workflow_action.id]
        replacement_ids.append(isolated_action.id)
        task.write({"activity_type_ids": [(6, 0, replacement_ids)]})
        return isolated_action, True

    def workflow_studio_update_workflow_action(
        self, workflow_action_id, values=False, task_node_id=False
    ):
        version = self._workflow_studio_get_version(require_write=True)
        workflow_action = self.env["workflow.approval.action"].sudo().browse(int(workflow_action_id)).exists()
        if not workflow_action:
            raise UserError(_("Workflow action not found."))
        if workflow_action.version_id and workflow_action.version_id != version:
            raise UserError(_("This workflow action belongs to another workflow version."))

        update_values = values or {}
        isolate_if_shared = True
        task = self.env["workflow.category.version.meta.task"].browse()
        if isinstance(update_values, dict):
            update_values = dict(update_values)
            if not task_node_id:
                task_node_id = update_values.pop("task_node_id", False)
            isolate_if_shared = bool(update_values.pop("isolate_if_shared", True))

        isolated_from_shared = False
        if task_node_id:
            task = self.env["workflow.category.version.meta.task"].sudo().search(
                [("version_id", "=", version.id), ("node_id", "=", task_node_id)],
                limit=1,
            )
            if not task:
                raise UserError(
                    _("No metadata task found for node '%s'. Save and sync the diagram first.")
                    % task_node_id
                )
            if isolate_if_shared and workflow_action in task.activity_type_ids:
                workflow_action, isolated_from_shared = self._workflow_studio_isolate_workflow_action_for_task(
                    version, workflow_action, task
                )

        prepared = self._workflow_studio_prepare_workflow_action_values(update_values)
        if "name" in prepared and not prepared["name"]:
            raise UserError(_("Action name is required."))
        if prepared:
            workflow_action.write(prepared)

        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "workflow_action": self._workflow_studio_serialize_workflow_action_option(workflow_action),
            "payload": payload,
            "isolated_from_shared": isolated_from_shared,
        }

    def _workflow_studio_prepare_approval_group_values(self, values, current_group=False):
        prepared = {}
        values = values or {}
        if not isinstance(values, dict):
            return prepared

        if "name" in values:
            prepared["name"] = (values.get("name") or "").strip()

        if "parent_group_ref" in values or "parent_id" in values:
            parent = self._workflow_studio_resolve_approval_group_ref(values.get("parent_group_ref"))
            if not parent and values.get("parent_id"):
                parent = self._workflow_studio_resolve_approval_group_ref(values.get("parent_id"))
            if current_group and parent and parent.id == current_group.id:
                raise UserError(_("Approval group cannot be parent of itself."))
            prepared["parent_id"] = parent.id if parent else False

        if "department_ref" in values or "department_id" in values:
            department = self._workflow_studio_resolve_department_ref(values.get("department_ref"))
            if not department and values.get("department_id"):
                department = self._workflow_studio_resolve_department_ref(values.get("department_id"))
            prepared["department_id"] = department.id if department else False

        if "user_refs" in values:
            users = self._workflow_studio_resolve_user_refs(values.get("user_refs"))
            prepared["user_ids"] = [(6, 0, users.ids)]
        elif "user_ids" in values:
            prepared["user_ids"] = [(6, 0, values.get("user_ids") or [])]

        return prepared

    def workflow_studio_create_approval_group(self, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        prepared = self._workflow_studio_prepare_approval_group_values(values or {})
        if not prepared.get("name"):
            raise UserError(_("Approval group name is required."))

        approval_group = self.env["workflow.approval.group"].sudo().create(prepared)
        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "approval_group": self._workflow_studio_serialize_approval_group_option(approval_group),
            "payload": payload,
        }

    def workflow_studio_update_approval_group(self, approval_group_id, values=False):
        version = self._workflow_studio_get_version(require_write=True)
        approval_group = self.env["workflow.approval.group"].sudo().browse(int(approval_group_id)).exists()
        if not approval_group:
            raise UserError(_("Approval group not found."))

        prepared = self._workflow_studio_prepare_approval_group_values(values or {}, current_group=approval_group)
        if "name" in prepared and not prepared["name"]:
            raise UserError(_("Approval group name is required."))
        if prepared:
            approval_group.write(prepared)

        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "approval_group": self._workflow_studio_serialize_approval_group_option(approval_group),
            "payload": payload,
        }

    def _workflow_studio_validate_business_action_guardrails(self):
        self.ensure_one()
        actions = self.meta_task_ids.mapped("meta_action_ids").filtered(
            lambda action: action.authorization_mode == "business_actor"
        )
        for action in actions:
            if action.authorization_scope != "task":
                raise ValidationError(
                    _("Business action '%s' uses an unsupported whole-request scope.")
                    % (action.display_name or action.name)
                )
            has_source = bool(
                action.business_actor_include_owner
                or action.business_actor_include_creator
                or action.business_actor_include_node_assignees
                or action.business_actor_user_ids
                or action.business_actor_group_ids
                or action.business_actor_approval_group_ids
                or (action.business_actor_user_domain or "").strip()
            )
            if not has_source:
                raise ValidationError(
                    _("Business action '%s' must define at least one actor source.")
                    % (action.display_name or action.name)
                )
            if action.approval_require_number > 1:
                raise ValidationError(
                    _("Business action '%s' cannot use an approval-count threshold.")
                    % (action.display_name or action.name)
                )
            if action.business_actor_user_domain:
                validation = self.workflow_studio_validate_domain_expression(
                    "res.users",
                    action.business_actor_user_domain,
                    "assignment_users_routing",
                    self.res_model_name,
                )
                if not validation.get("valid") or validation.get("ignored"):
                    raise ValidationError(
                        _("Invalid user domain on business action '%(action)s': %(error)s")
                        % {
                            "action": action.display_name or action.name,
                            "error": (
                                validation.get("error")
                                or validation.get("warning")
                                or _("Unknown domain error")
                            ),
                        }
                    )

    def workflow_studio_deploy_version(self):
        version = self._workflow_studio_get_version()
        version._workflow_studio_validate_business_action_guardrails()
        self._workflow_studio_validate_activation_target(version)
        deployed = version._workflow_studio_activate_version(version, publish=False)
        payload = deployed.workflow_studio_get_bpmn_payload()
        return {"payload": payload, "version_id": deployed.id}

    def workflow_studio_publish_version(self):
        version = self._workflow_studio_get_version(allow_locked=True)
        version._workflow_studio_validate_publish_field_policy_guardrails()
        version._workflow_studio_validate_business_action_guardrails()
        self._workflow_studio_validate_activation_target(version)
        published = version._workflow_studio_activate_version(version, publish=True)
        payload = published.workflow_studio_get_bpmn_payload()
        return {"payload": payload, "version_id": published.id}

    def workflow_studio_rollback_version(self, target_version_id=False):
        requested_target = self.browse()
        if target_version_id:
            requested_target = self.sudo().browse(int(target_version_id)).exists()
            if not requested_target:
                raise UserError(_("Rollback target version not found."))
        rollback_target, active_version = self._workflow_studio_resolve_rollback_target(
            requested_target=requested_target
        )
        self._workflow_studio_validate_activation_target(rollback_target)
        rollback_target._workflow_studio_activate_version(rollback_target, publish=False)
        payload = rollback_target.workflow_studio_get_bpmn_payload()
        return {
            "payload": payload,
            "version_id": rollback_target.id,
            "rolled_back_from_version_id": active_version.id if active_version else False,
            "rolled_back_to_display_name": rollback_target.display_name or rollback_target.name or "",
            "rolled_back_from_display_name": (
                (active_version.display_name or active_version.name or "") if active_version else ""
            ),
        }

    def workflow_studio_lock_version(self):
        version = self._workflow_studio_get_version()
        version.action_lock_version()
        payload = version.workflow_studio_get_bpmn_payload()
        return {"payload": payload, "version_id": version.id}

    def workflow_studio_unlock_version(self):
        version = self._workflow_studio_get_version(allow_locked=True)
        version.write({"is_locked": False})
        payload = version.workflow_studio_get_bpmn_payload()
        return {"payload": payload, "version_id": version.id}

    def workflow_studio_delete_version(self):
        version = self._workflow_studio_get_version(allow_locked=True)
        category = version.category_id.sudo()
        other_versions = (category.version_ids - version).sudo()
        if not other_versions:
            raise UserError(_("You cannot delete the only workflow version."))
        if version.is_active or category.active_version_id == version:
            raise UserError(
                _(
                    "You cannot delete the deployed version. Deploy another version first."
                )
            )
        next_version = category.active_version_id or other_versions.sorted(
            key=lambda rec: (rec.sequence, rec.id), reverse=True
        )[:1]
        next_version_id = next_version.id if next_version else False
        version.unlink()
        return {
            "version_id": next_version_id,
            "version_control": self._workflow_studio_build_version_control(category),
        }

    def _workflow_studio_get_xmlid(self, record):
        if not record:
            return False
        record.ensure_one()
        return record.get_external_id().get(record.id)

    def _workflow_studio_action_key(self, source_id, target_id):
        return f"{source_id}|{target_id}"

    def _workflow_studio_serialize_ref(self, record, extra=None):
        if not record:
            return False
        record.ensure_one()
        payload = {
            "id": record.id,
            "xmlid": self._workflow_studio_get_xmlid(record),
        }
        if extra:
            payload.update(extra)
        return payload

    def _workflow_studio_serialize_meta_task(self, task):
        return {
            "id": task.id,
            "node_id": task.node_id or "",
            "name": task.name or "",
            "description": task.description or "",
            "node_type": task.node_type or "",
            "node_type_label": NODE_LABELS.get(task.node_type, task.node_type or ""),
            "node_metadata_hint": NODE_METADATA_HINTS.get(task.node_type, {}),
            "sequence": task.sequence or 10,
            "attr_class": task.attr_class or "",
            "attr_label": task.attr_label or "",
            "element": task.element or "",
            "approval_group_domain": task.approval_group_domain or "",
            "notification_delivery_mode": task.notification_delivery_mode or "",
            "notification_recipient_domain": task.notification_recipient_domain or "",
            "notification_recipient_mode": task.notification_recipient_mode or "specific_users",
            "notification_recipient_source": (
                task.notification_recipient_source
                or (
                    "domain"
                    if (task.notification_recipient_mode or "") == "domain"
                    else "specific_users"
                    if (task.notification_recipient_mode or "") == "specific_users"
                    else ""
                )
            ),
            "notification_recipient_node_ref": task.notification_recipient_node_ref or "",
            "notification_recipient_node_user_type": task.notification_recipient_node_user_type or "assigned",
            "notification_recipient_filter_domain": task.notification_recipient_filter_domain or "",
            "notification_approval_group_ids": task.notification_approval_group_ids.ids,
            "notification_approval_group_refs": [
                self._workflow_studio_serialize_ref(g, extra={"name": g.name})
                for g in task.notification_approval_group_ids
            ],
            "notification_group_ids": task.notification_group_ids.ids,
            "notification_group_refs": [
                self._workflow_studio_serialize_ref(g, extra={"name": g.display_name or g.name})
                for g in task.notification_group_ids
            ],
            "action_id": task.action_id.id if task.action_id else False,
            "action_ref": self._workflow_studio_serialize_ref(
                task.action_id,
                extra={
                    "name": task.action_id.name if task.action_id else "",
                    "res_model": task.action_id.res_model if task.action_id else "",
                },
            ),
            "email_template_external_id": task.email_template_external_id.id
            if task.email_template_external_id
            else False,
            "email_template_ref": self._workflow_studio_serialize_ref(
                task.email_template_external_id,
                extra={
                    "name": task.email_template_external_id.name
                    if task.email_template_external_id
                    else "",
                    "model": task.email_template_external_id.model
                    if task.email_template_external_id
                    else "",
                },
            ),
            "notification_recipient_ids": task.notification_recipient_ids.ids,
            "notification_recipient_refs": [
                self._workflow_studio_serialize_ref(
                    u, extra={"name": u.name, "login": u.login, "email": u.email}
                )
                for u in task.notification_recipient_ids
            ],
            "activity_type": task.activity_type or "",
            "activity_message_template": task.activity_message_template.id
            if task.activity_message_template
            else False,
            "activity_message_template_ref": self._workflow_studio_serialize_ref(
                task.activity_message_template,
                extra={
                    "name": task.activity_message_template.name
                    if task.activity_message_template
                    else "",
                    "model": task.activity_message_template.model
                    if task.activity_message_template
                    else "",
                },
            ),
            "activity_type_ids": task.activity_type_ids.ids,
            "activity_action_refs": [
                self._workflow_studio_serialize_ref(
                    a, extra={"name": a.name, "action_type": a.action_type}
                )
                for a in task.activity_type_ids
            ],
            "assignment_mode": task.assignment_mode or "mixed",
            "explicit_user_ids": task.explicit_user_ids.ids,
            "explicit_user_refs": [
                self._workflow_studio_serialize_ref(
                    u, extra={"name": u.name, "login": u.login, "email": u.email}
                )
                for u in task.explicit_user_ids
            ],
            "explicit_group_ids": task.explicit_group_ids.ids,
            "explicit_group_refs": [
                self._workflow_studio_serialize_ref(g, extra={"name": g.name})
                for g in task.explicit_group_ids
            ],
            "assignment_user_domain": task.assignment_user_domain or "",
            "assignment_source_user_type": task.assignment_source_user_type or "decided",
            "completion_mode": task.completion_mode or "any",
            "fallback_policy": task.fallback_policy or "route_admin_queue",
            "fallback_user_id": task.fallback_user_id.id if task.fallback_user_id else False,
            "fallback_user_ref": self._workflow_studio_serialize_ref(
                task.fallback_user_id,
                extra={
                    "name": task.fallback_user_id.name if task.fallback_user_id else "",
                    "login": task.fallback_user_id.login if task.fallback_user_id else "",
                    "email": task.fallback_user_id.email if task.fallback_user_id else "",
                },
            ),
            "join_key": task.join_key or "",
            "service_behavior": task.service_behavior or "router",
            "automation_run_mode": task.automation_run_mode or "immediate",
            "automation_condition_domain": task.automation_condition_domain or "",
            "automation_schedule_mode": task.automation_schedule_mode or "interval",
            "automation_interval_number": task.automation_interval_number or 5,
            "automation_interval_type": task.automation_interval_type or "minutes",
            "automation_fixed_time": task.automation_fixed_time if task.automation_fixed_time is not False else False,
            "automation_cron_expr": task.automation_cron_expr or "",
            "automation_is_recurring": bool(task.automation_is_recurring),
            "automation_recurrence_end_mode": task.automation_recurrence_end_mode or "forever",
            "automation_recurrence_count": task.automation_recurrence_count or 10,
            "automation_recurrence_until": fields.Datetime.to_string(task.automation_recurrence_until)
            if task.automation_recurrence_until
            else False,
            "gateway_node_id": task.gateway_node_id or "",
            "join_policy": task.join_policy or "all_of",
            "join_min_n": task.join_min_n or 0,
            "parallel_reject_policy": task.parallel_reject_policy or "strict",
            "assign_to_previous_actor": bool(task.assign_to_previous_actor),
            "previous_actor_node_ref": task.previous_actor_node_ref or "",
            "assign_to_request_owner": bool(task.assign_to_request_owner),
            "reset_request_to_submit": bool(task.reset_request_to_submit),
            "push_notification_to_actor": task.push_notification_to_actor is not False,
            "notify_request_owner_email": task.notify_request_owner_email is not False,
            "notify_request_creator_email": task.notify_request_creator_email is not False,
            "confidentiality_level": task.confidentiality_level or "public",
            "department_id": task.department_id.id if task.department_id else False,
            "department_ref": self._workflow_studio_serialize_ref(
                task.department_id, extra={"name": task.department_id.name if task.department_id else ""}
            ),
            "requires_department_payload": bool(task.requires_department_payload),
            "enable_share_override": bool(task.enable_share_override),
            "is_end_node": bool(task.is_end_node),
        }

    def _workflow_studio_serialize_meta_action(self, action):
        return {
            "id": action.id,
            "action_key": self._workflow_studio_action_key(action.source_id, action.target_id),
            "node_id": action.node_id or "",
            "name": action.name or "",
            "description": action.description or "",
            "source_id": action.source_id or "",
            "source_name": action.source_name or "",
            "source_node_type": action.source_node_type or "",
            "target_id": action.target_id or "",
            "target_name": action.target_name or "",
            "target_node_type": action.target_node_type or "",
            "attr_class": action.attr_class or "",
            "icon_class": action.icon_class or "",
            "attr_label": action.attr_label or "",
            "flow_type": action.flow_type or "",
            "auto_action_condition": action.auto_action_condition or "",
            "action_button_label": action.action_button_label or "",
            "invisible_domain": action.invisible_domain or "",
            "domain": action.domain or "",
            "action_mode": action.action_mode or "route",
            "authorization_mode": action.authorization_mode or "approval_actor",
            "authorization_scope": action.authorization_scope or "task",
            "business_actor_include_owner": bool(action.business_actor_include_owner),
            "business_actor_include_creator": bool(action.business_actor_include_creator),
            "business_actor_include_node_assignees": bool(
                action.business_actor_include_node_assignees
            ),
            "business_actor_user_ids": action.business_actor_user_ids.ids,
            "business_actor_user_refs": [
                self._workflow_studio_serialize_ref(
                    user,
                    extra={"name": user.name, "login": user.login, "email": user.email},
                )
                for user in action.business_actor_user_ids
            ],
            "business_actor_group_ids": action.business_actor_group_ids.ids,
            "business_actor_group_refs": [
                self._workflow_studio_serialize_ref(
                    group,
                    extra={"name": group.display_name or group.name},
                )
                for group in action.business_actor_group_ids
            ],
            "business_actor_approval_group_ids": action.business_actor_approval_group_ids.ids,
            "business_actor_approval_group_refs": [
                self._workflow_studio_serialize_ref(group, extra={"name": group.name})
                for group in action.business_actor_approval_group_ids
            ],
            "business_actor_user_domain": action.business_actor_user_domain or "",
            "show_validation_dialog": bool(action.show_validation_dialog),
            "validation_message": action.validation_message or "",
            "show_confirm_dialog": bool(action.show_confirm_dialog),
            "dialog_type": action.dialog_type or "",
            "require_reason": bool(action.require_reason),
            "require_reason_domain": action.require_reason_domain or "",
            "comment_required_domain": action.comment_required_domain or "",
            "require_attachment": bool(action.require_attachment),
            "require_attachment_domain": action.require_attachment_domain or "",
            "required_attachment_count": action.required_attachment_count or 1,
            "confirm_message": action.confirm_message or "",
            "approval_require_number": action.approval_require_number or 1,
            "comment_required": bool(action.comment_required),
            "idempotency_required": bool(action.idempotency_required),
            "require_2fa": bool(action.require_2fa),
            "twofa_method": action.twofa_method or "email_otp",
            "twofa_condition_domain": action.twofa_condition_domain or "",
            "required_rule_set_id": action.required_rule_set_id.id if action.required_rule_set_id else False,
            "required_rule_set_ref": self._workflow_studio_serialize_ref(
                action.required_rule_set_id,
                extra={"name": action.required_rule_set_id.name if action.required_rule_set_id else ""},
            ),
            "meta_task_node_id": action.meta_task_id.node_id if action.meta_task_id else "",
            "timer_duration_number": action.timer_duration_number or 1,
            "timer_duration_unit": action.timer_duration_unit or "days",
            "automation_schedule_mode": action.automation_schedule_mode or "interval",
            "automation_interval_number": action.automation_interval_number or action.timer_duration_number or 1,
            "automation_interval_type": action.automation_interval_type or action.timer_duration_unit or "days",
            "automation_fixed_time": (
                action.automation_fixed_time if action.automation_fixed_time is not False else False
            ),
            "automation_cron_expr": action.automation_cron_expr or "",
            "automation_is_recurring": bool(action.automation_is_recurring),
            "automation_recurrence_end_mode": action.automation_recurrence_end_mode or "forever",
            "automation_recurrence_count": action.automation_recurrence_count or 10,
            "automation_recurrence_until": fields.Datetime.to_string(action.automation_recurrence_until)
            if action.automation_recurrence_until
            else False,
            "automation_trigger_mode": action.automation_trigger_mode or "route",
        }

    def _workflow_studio_serialize_meta_field(self, meta_field):
        field_type = meta_field.field_type or "required"
        domain = meta_field.domain or "[]"
        return {
            "id": meta_field.id,
            "task_node_id": meta_field.meta_id.node_id if meta_field.meta_id else "",
            "field_type": field_type,
            "field_id": meta_field.field_id.id if meta_field.field_id else False,
            "field_ref": self._workflow_studio_serialize_ref(
                meta_field.field_id,
                extra={
                    "name": meta_field.field_id.name if meta_field.field_id else "",
                    "model": meta_field.field_id.model if meta_field.field_id else "",
                    "field_description": meta_field.field_id.field_description
                    if meta_field.field_id
                    else "",
                    "ttype": meta_field.field_id.ttype if meta_field.field_id else "",
                },
            ),
            "activity_action_keys": [
                self._workflow_studio_action_key(a.source_id, a.target_id)
                for a in meta_field.activity_action_ids
            ],
            "domain": domain,
            "condition_domain": domain,
            "domains_by_type": {field_type: domain},
            "visible_domain": domain if field_type == "visible" else "[]",
            "required_domain": domain if field_type == "required" else "[]",
            "readonly_domain": domain if field_type == "readonly" else "[]",
            "invisible_domain": domain if field_type == "invisible" else "[]",
        }

    def _workflow_studio_serialize_approval_group_link(self, link):
        return {
            "id": link.id,
            "task_node_id": link.meta_id.node_id if link.meta_id else "",
            "sequence": link.sequence or 10,
            "approval_group_ref": self._workflow_studio_serialize_ref(
                link.approval_group_id, extra={"name": link.approval_group_id.name}
            ),
            "user_domain": link.user_domain or "",
            "domain": link.domain or "",
            "note": link.note or "",
        }

    def _workflow_studio_serialize_workflow_map(self, workflow_map):
        return {
            "id": workflow_map.id,
            "task_node_id": workflow_map.meta_task_id.node_id if workflow_map.meta_task_id else "",
            "execution_mode": workflow_map.execution_mode or "sync",
            "field_mapping": workflow_map.field_mapping or "",
            "domain": workflow_map.domain or "",
            "called_workflow_ref": self._workflow_studio_serialize_ref(
                workflow_map.called_workflow_id,
                extra={
                    "name": workflow_map.called_workflow_id.name if workflow_map.called_workflow_id else "",
                    "display_name": workflow_map.called_workflow_id.display_name
                    if workflow_map.called_workflow_id
                    else "",
                    "category_name": workflow_map.called_workflow_id.category_id.display_name
                    if workflow_map.called_workflow_id and workflow_map.called_workflow_id.category_id
                    else "",
                },
            ),
        }

    def _workflow_studio_get_related_model_ids(self):
        version = self._workflow_studio_get_version()
        model_ids = set()
        if version.res_model_id:
            model_ids.add(version.res_model_id.id)

        if not version.res_model_name:
            return sorted(model_ids)

        ExcludedModel = {
            "hr.employee",
            "res.partner",
            "res.users",
            "res.company",
            "mail.activity",
            "mail.message",
            "ir.model",
            "ir.attachment",
            "mail.activity.type",
            "mail.followers",
        }
        Model = self.env[version.res_model_name]
        for field in Model._fields.values():
            if field.type in {"many2one", "many2many", "one2many"} and field.comodel_name:
                if field.comodel_name in ExcludedModel:
                    continue
                related_model = self.env["ir.model"].sudo()._get(field.comodel_name)
                if related_model:
                    model_ids.add(related_model.id)
        return sorted(model_ids)

    def _workflow_studio_resolve_ref_by_xmlid(self, model_name, xmlid):
        if not xmlid:
            return self.env[model_name]
        record = self.env.ref(xmlid, raise_if_not_found=False)
        if record and record._name == model_name:
            return record.sudo()
        return self.env[model_name]

    def _workflow_studio_resolve_action_ref(self, ref_data):
        Action = self.env["ir.actions.act_window"].sudo()
        if not ref_data:
            return Action
        if isinstance(ref_data, int):
            return Action.browse(ref_data).exists()
        if not isinstance(ref_data, dict):
            return Action
        action = self._workflow_studio_resolve_ref_by_xmlid("ir.actions.act_window", ref_data.get("xmlid"))
        if action:
            return action
        domain = []
        if ref_data.get("name"):
            domain.append(("name", "=", ref_data["name"]))
        if ref_data.get("res_model"):
            domain.append(("res_model", "=", ref_data["res_model"]))
        if domain:
            action = Action.search(domain, limit=1)
            if action:
                return action
        if ref_data.get("id"):
            action = Action.browse(ref_data["id"]).exists()
            if action:
                return action
        return Action

    def _workflow_studio_resolve_server_action_ref(self, ref_data):
        Action = self.env["ir.actions.server"].sudo()
        if not ref_data:
            return Action
        if isinstance(ref_data, int):
            return Action.browse(ref_data).exists()
        if not isinstance(ref_data, dict):
            return Action
        action = self._workflow_studio_resolve_ref_by_xmlid("ir.actions.server", ref_data.get("xmlid"))
        if action:
            return action
        domain = []
        if ref_data.get("name"):
            domain.append(("name", "=", ref_data["name"]))
        if ref_data.get("model"):
            domain = Domain.AND([
                domain,
                Domain.OR([
                    [("model_name", "=", ref_data["model"])],
                    [("model_id.model", "=", ref_data["model"])],
                ]),
            ])
            action = Action.search(list(domain), limit=1)
            if action:
                return action
        elif domain:
            action = Action.search(domain, limit=1)
            if action:
                return action
        if ref_data.get("id"):
            action = Action.browse(ref_data["id"]).exists()
            if action:
                return action
        return Action

    def _workflow_studio_resolve_template_ref(self, ref_data):
        Template = self.env["mail.template"].sudo()
        if not ref_data:
            return Template
        if isinstance(ref_data, int):
            return Template.browse(ref_data).exists()
        if not isinstance(ref_data, dict):
            return Template
        template = self._workflow_studio_resolve_ref_by_xmlid("mail.template", ref_data.get("xmlid"))
        if template:
            return template
        domain = []
        if ref_data.get("name"):
            domain.append(("name", "=", ref_data["name"]))
        if ref_data.get("model"):
            domain.append(("model", "=", ref_data["model"]))
        if domain:
            template = Template.search(domain, limit=1)
            if template:
                return template
        if ref_data.get("id"):
            template = Template.browse(ref_data["id"]).exists()
            if template:
                return template
        return Template

    def _workflow_studio_resolve_user_refs(self, users_data):
        User = self.env["res.users"].sudo()
        result = User.browse()
        create_missing = bool(self.env.context.get("workflow_studio_create_missing_refs"))
        group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        groups_field = self._workflow_studio_user_groups_field()
        for user_data in users_data or []:
            rec = User.browse()
            if isinstance(user_data, int):
                rec = User.browse(user_data).exists()
            elif isinstance(user_data, dict):
                rec = self._workflow_studio_resolve_ref_by_xmlid("res.users", user_data.get("xmlid"))
                if not rec and user_data.get("login"):
                    rec = User.search([("login", "=", user_data["login"])], limit=1)
                if not rec and user_data.get("email"):
                    rec = User.search([("email", "=", user_data["email"])], limit=1)
                if not rec and user_data.get("id"):
                    rec = User.browse(user_data["id"]).exists()
                if not rec and create_missing:
                    name = (
                        (user_data.get("name") or user_data.get("login") or user_data.get("email") or "").strip()
                    )
                    if name:
                        login_seed = (
                            user_data.get("login")
                            or user_data.get("email")
                            or name
                        )
                        login = self._workflow_studio_sanitize_login(login_seed)
                        if not login:
                            login = self._workflow_studio_next_available_login(name)
                        elif User.search_count([("login", "=", login)]):
                            login = self._workflow_studio_next_available_login(login)
                        user_vals = {
                            "name": name,
                            "login": login,
                            "email": (user_data.get("email") or "").strip() or False,
                            "active": True,
                        }
                        if group_user and groups_field:
                            user_vals[groups_field] = [(6, 0, [group_user.id])]
                        if self.env.company:
                            user_vals["company_id"] = self.env.company.id
                            user_vals["company_ids"] = [(4, self.env.company.id)]
                        rec = User.with_context(no_reset_password=True).create(user_vals)
            if rec:
                result |= rec
        return result

    def _workflow_studio_resolve_workflow_action_refs(self, action_refs):
        Action = self.env["workflow.approval.action"].sudo()
        result = Action.browse()
        create_missing = bool(self.env.context.get("workflow_studio_create_missing_refs"))
        version_id = self.env.context.get("workflow_studio_target_version_id")
        for action_ref in action_refs or []:
            action = Action.browse()
            if isinstance(action_ref, int):
                action = Action.browse(action_ref).exists()
            elif isinstance(action_ref, dict):
                action = self._workflow_studio_resolve_ref_by_xmlid(
                    "workflow.approval.action", action_ref.get("xmlid")
                )
                if not action and action_ref.get("name"):
                    domain = [("name", "=", action_ref["name"])]
                    if action_ref.get("action_type"):
                        domain.append(("action_type", "=", action_ref["action_type"]))
                    action = Action.search(domain, limit=1)
                if not action and action_ref.get("id"):
                    action = Action.browse(action_ref["id"]).exists()
                if not action and create_missing and action_ref.get("name"):
                    vals = {
                        "name": action_ref.get("name"),
                        "action_type": action_ref.get("action_type") or "workflow",
                    }
                    if version_id:
                        vals["version_id"] = int(version_id)
                    action = Action.create(vals)
            if action:
                result |= action
        return result

    def _workflow_studio_resolve_field_ref(self, field_data):
        Field = self.env["ir.model.fields"].sudo()
        if not field_data:
            return Field
        if isinstance(field_data, int):
            return Field.browse(field_data).exists()
        if not isinstance(field_data, dict):
            return Field
        field = self._workflow_studio_resolve_ref_by_xmlid("ir.model.fields", field_data.get("xmlid"))
        if field:
            return field
        name = field_data.get("name")
        model = field_data.get("model")
        if name and model:
            field = Field.search([("model", "=", model), ("name", "=", name)], limit=1)
            if field:
                return field
        if field_data.get("id"):
            field = Field.browse(field_data["id"]).exists()
            if field:
                return field
        return Field

    def _workflow_studio_resolve_approval_group_ref(self, group_data):
        Group = self.env["workflow.approval.group"].sudo()
        if not group_data:
            return Group.browse()
        create_missing = bool(self.env.context.get("workflow_studio_create_missing_refs"))

        if isinstance(group_data, int):
            return Group.browse(group_data).exists()
        if isinstance(group_data, str):
            raw_value = (group_data or "").strip()
            if not raw_value:
                return Group.browse()
            if raw_value.isdigit():
                return Group.browse(int(raw_value)).exists()
            group = Group.search([("name", "=", raw_value)], limit=1)
            if not group and create_missing:
                group = Group.create({"name": raw_value})
            return group
        if not isinstance(group_data, dict):
            return Group.browse()

        group_id = (
            group_data.get("id")
            or group_data.get("res_id")
            or group_data.get("approval_group_id")
        )
        if isinstance(group_id, str):
            group_id = group_id.strip()
            group_id = int(group_id) if group_id.isdigit() else False
        group = self._workflow_studio_resolve_ref_by_xmlid(
            "workflow.approval.group", group_data.get("xmlid")
        )
        if group:
            return group
        group_name = (
            (group_data.get("name") or "").strip()
            or (group_data.get("display_name") or "").strip()
        )
        if group_name:
            group = Group.search([("name", "=", group_name)], limit=1)
            if not group and create_missing:
                group = Group.create({"name": group_name})
            return group
        if group_id:
            group = Group.browse(group_id).exists()
            if group:
                return group
        return Group.browse()

    def _workflow_studio_resolve_called_workflow_ref(self, workflow_data):
        Version = self.env["workflow.approval.category.version"].sudo()
        if not workflow_data:
            return Version
        if isinstance(workflow_data, int):
            return Version.browse(workflow_data).exists()
        if not isinstance(workflow_data, dict):
            return Version
        version = self._workflow_studio_resolve_ref_by_xmlid(
            "workflow.approval.category.version", workflow_data.get("xmlid")
        )
        if version:
            return version
        domain = []
        if workflow_data.get("name"):
            domain.append(("name", "=", workflow_data["name"]))
        if workflow_data.get("category_name"):
            domain.append(("category_id.display_name", "=", workflow_data["category_name"]))
        if domain:
            version = Version.search(domain, limit=1)
            if version:
                return version
        if workflow_data.get("id"):
            version = Version.browse(workflow_data["id"]).exists()
            if version:
                return version
        return Version

    def _workflow_studio_prepare_task_values(self, values):
        clean = {}
        if not isinstance(values, dict):
            return clean
        for name in TASK_WRITE_FIELDS:
            if name in values:
                clean[name] = values[name]

        recipient_source = clean.get("notification_recipient_source")
        if recipient_source == "specific_users":
            clean["notification_recipient_mode"] = "specific_users"
            clean["notification_recipient_node_ref"] = False
            clean["notification_recipient_filter_domain"] = False
            clean["notification_approval_group_ids"] = [(5, 0, 0)]
            clean["notification_group_ids"] = [(5, 0, 0)]
        elif recipient_source == "approval_group_users":
            clean["notification_recipient_mode"] = "domain"
            clean["notification_recipient_ids"] = [(5, 0, 0)]
            clean["notification_group_ids"] = [(5, 0, 0)]
            clean["notification_recipient_node_ref"] = False
        elif recipient_source == "group_users":
            clean["notification_recipient_mode"] = "domain"
            clean["notification_recipient_ids"] = [(5, 0, 0)]
            clean["notification_approval_group_ids"] = [(5, 0, 0)]
            clean["notification_recipient_node_ref"] = False
        elif recipient_source == "node_users":
            clean["notification_recipient_mode"] = "domain"
            clean["notification_recipient_ids"] = [(5, 0, 0)]
            clean["notification_approval_group_ids"] = [(5, 0, 0)]
            clean["notification_group_ids"] = [(5, 0, 0)]
        elif recipient_source == "domain":
            clean["notification_recipient_mode"] = "domain"
            clean["notification_recipient_node_ref"] = False
            clean["notification_recipient_ids"] = [(5, 0, 0)]
            clean["notification_approval_group_ids"] = [(5, 0, 0)]
            clean["notification_group_ids"] = [(5, 0, 0)]

        if "action_ref" in values:
            action = self._workflow_studio_resolve_action_ref(values.get("action_ref"))
            clean["action_id"] = action.id if action else False
        elif "action_id" in values:
            clean["action_id"] = values.get("action_id") or False

        if "email_template_ref" in values:
            template = self._workflow_studio_resolve_template_ref(values.get("email_template_ref"))
            clean["email_template_external_id"] = template.id if template else False
        elif "email_template_external_id" in values:
            clean["email_template_external_id"] = values.get("email_template_external_id") or False

        if "activity_message_template_ref" in values:
            template = self._workflow_studio_resolve_template_ref(
                values.get("activity_message_template_ref")
            )
            clean["activity_message_template"] = template.id if template else False
        elif "activity_message_template" in values:
            clean["activity_message_template"] = values.get("activity_message_template") or False

        if "notification_recipient_refs" in values:
            users = self._workflow_studio_resolve_user_refs(values.get("notification_recipient_refs"))
            clean["notification_recipient_ids"] = [(6, 0, users.ids)]
        elif "notification_recipient_ids" in values:
            clean["notification_recipient_ids"] = [(6, 0, values.get("notification_recipient_ids") or [])]

        if "notification_approval_group_ids" in values:
            clean["notification_approval_group_ids"] = [
                (6, 0, values.get("notification_approval_group_ids") or [])
            ]

        if "notification_group_ids" in values:
            clean["notification_group_ids"] = [(6, 0, values.get("notification_group_ids") or [])]

        if "activity_action_refs" in values:
            actions = self._workflow_studio_resolve_workflow_action_refs(values.get("activity_action_refs"))
            clean["activity_type_ids"] = [(6, 0, actions.ids)]
        elif "activity_type_ids" in values:
            clean["activity_type_ids"] = [(6, 0, values.get("activity_type_ids") or [])]

        if "explicit_user_refs" in values:
            users = self._workflow_studio_resolve_user_refs(values.get("explicit_user_refs"))
            clean["explicit_user_ids"] = [(6, 0, users.ids)]
        elif "explicit_user_ids" in values:
            clean["explicit_user_ids"] = [(6, 0, values.get("explicit_user_ids") or [])]

        if "explicit_group_refs" in values:
            Group = self.env["res.groups"].sudo()
            groups = Group.browse()
            for group_ref in values.get("explicit_group_refs") or []:
                if isinstance(group_ref, int):
                    groups |= Group.browse(group_ref).exists()
                    continue
                if isinstance(group_ref, dict):
                    xmlid = group_ref.get("xmlid")
                    group = self._workflow_studio_resolve_ref_by_xmlid("res.groups", xmlid)
                    if not group and group_ref.get("id"):
                        group = Group.browse(group_ref["id"]).exists()
                    if not group and group_ref.get("name"):
                        group = Group.search([("name", "=", group_ref["name"])], limit=1)
                    if group:
                        groups |= group
            clean["explicit_group_ids"] = [(6, 0, groups.ids)]
        elif "explicit_group_ids" in values:
            clean["explicit_group_ids"] = [(6, 0, values.get("explicit_group_ids") or [])]

        if "fallback_user_ref" in values:
            users = self._workflow_studio_resolve_user_refs([values.get("fallback_user_ref")])
            clean["fallback_user_id"] = users[:1].id if users else False
        elif "fallback_user_id" in values:
            clean["fallback_user_id"] = values.get("fallback_user_id") or False

        if "department_ref" in values:
            department = self._workflow_studio_resolve_department_ref(values.get("department_ref"))
            clean["department_id"] = department.id if department else False
        elif "department_id" in values:
            clean["department_id"] = values.get("department_id") or False
        return clean

    def _workflow_studio_prepare_action_values(self, values):
        clean = {}
        if not isinstance(values, dict):
            return clean
        for name in ACTION_WRITE_FIELDS:
            if name in values:
                clean[name] = values[name]
        if "business_actor_user_refs" in values:
            users = self._workflow_studio_resolve_user_refs(
                values.get("business_actor_user_refs")
            )
            clean["business_actor_user_ids"] = [(6, 0, users.ids)]
        elif "business_actor_user_ids" in values:
            clean["business_actor_user_ids"] = [
                (6, 0, values.get("business_actor_user_ids") or [])
            ]

        if "business_actor_group_refs" in values:
            Group = self.env["res.groups"].sudo()
            groups = Group.browse()
            for group_ref in values.get("business_actor_group_refs") or []:
                if isinstance(group_ref, int):
                    groups |= Group.browse(group_ref).exists()
                    continue
                if not isinstance(group_ref, dict):
                    continue
                group = self._workflow_studio_resolve_ref_by_xmlid(
                    "res.groups", group_ref.get("xmlid")
                )
                if not group and group_ref.get("id"):
                    group = Group.browse(group_ref["id"]).exists()
                if not group and group_ref.get("name"):
                    group = Group.search([("name", "=", group_ref["name"])], limit=1)
                if group:
                    groups |= group
            clean["business_actor_group_ids"] = [(6, 0, groups.ids)]
        elif "business_actor_group_ids" in values:
            clean["business_actor_group_ids"] = [
                (6, 0, values.get("business_actor_group_ids") or [])
            ]

        if "business_actor_approval_group_refs" in values:
            Group = self.env["workflow.approval.group"].sudo()
            groups = Group.browse()
            for group_ref in values.get("business_actor_approval_group_refs") or []:
                if isinstance(group_ref, int):
                    groups |= Group.browse(group_ref).exists()
                    continue
                if not isinstance(group_ref, dict):
                    continue
                group = self._workflow_studio_resolve_ref_by_xmlid(
                    "workflow.approval.group", group_ref.get("xmlid")
                )
                if not group and group_ref.get("id"):
                    group = Group.browse(group_ref["id"]).exists()
                if not group and group_ref.get("name"):
                    group = Group.search([("name", "=", group_ref["name"])], limit=1)
                if group:
                    groups |= group
            clean["business_actor_approval_group_ids"] = [(6, 0, groups.ids)]
        elif "business_actor_approval_group_ids" in values:
            clean["business_actor_approval_group_ids"] = [
                (6, 0, values.get("business_actor_approval_group_ids") or [])
            ]
        if "required_rule_set_ref" in values:
            RuleSet = self.env["workflow.field.rule.set"].sudo()
            ref_data = values.get("required_rule_set_ref")
            rule_set = RuleSet.browse()
            if isinstance(ref_data, int):
                rule_set = RuleSet.browse(ref_data).exists()
            elif isinstance(ref_data, dict):
                xmlid = ref_data.get("xmlid")
                rule_set = self._workflow_studio_resolve_ref_by_xmlid(
                    "workflow.field.rule.set", xmlid
                )
                if not rule_set and ref_data.get("id"):
                    rule_set = RuleSet.browse(ref_data["id"]).exists()
                if not rule_set and ref_data.get("name"):
                    rule_set = RuleSet.search([("name", "=", ref_data["name"])], limit=1)
            clean["required_rule_set_id"] = rule_set.id if rule_set else False
        elif "required_rule_set_id" in values:
            clean["required_rule_set_id"] = values.get("required_rule_set_id") or False
        if "approval_require_number" in clean:
            try:
                clean["approval_require_number"] = max(1, int(clean["approval_require_number"] or 1))
            except Exception:
                clean["approval_require_number"] = 1
        if "required_attachment_count" in clean:
            try:
                clean["required_attachment_count"] = max(1, int(clean["required_attachment_count"] or 1))
            except Exception:
                clean["required_attachment_count"] = 1
        if "automation_interval_number" in clean:
            try:
                clean["automation_interval_number"] = max(1, int(clean["automation_interval_number"] or 1))
            except Exception:
                clean["automation_interval_number"] = 1
        if "automation_recurrence_count" in clean:
            try:
                clean["automation_recurrence_count"] = max(1, int(clean["automation_recurrence_count"] or 1))
            except Exception:
                clean["automation_recurrence_count"] = 10
        if "timer_duration_number" in clean:
            try:
                clean["timer_duration_number"] = max(1, int(clean["timer_duration_number"] or 1))
            except Exception:
                clean["timer_duration_number"] = 1
        if "automation_interval_number" in clean:
            clean.setdefault("timer_duration_number", clean["automation_interval_number"])
        if "automation_interval_type" in clean:
            clean.setdefault("timer_duration_unit", clean["automation_interval_type"] or "days")
        return clean

    def workflow_studio_get_bpmn_payload(self):
        version = self._workflow_studio_get_version()
        task_model = self.env["workflow.category.version.meta.task"].sudo()
        action_model = self.env["workflow.category.version.meta.task.action"].sudo()
        field_model = self.env["workflow.category.version.meta.field"].sudo()
        link_model = self.env["workflow.category.task.approval.group"].sudo()
        map_model = self.env["workflow.category.version.meta.task.workflow.map"].sudo()

        tasks = task_model.search([("version_id", "=", version.id)])
        actions = action_model.search([("version_id", "=", version.id)])
        meta_fields = field_model.search([("meta_id", "in", tasks.ids)])
        approval_links = link_model.search([("meta_id", "in", tasks.ids)])
        workflow_maps = map_model.search([("meta_task_id", "in", tasks.ids)])

        related_model_ids = self._workflow_studio_get_related_model_ids()
        fields_data = self.env["ir.model.fields"].sudo().search_read(
            [
                ("model_id", "in", related_model_ids),
                ("name", "not in", ["create_uid", "create_date", "write_uid", "write_date", "display_name"]),
            ],
            ["id", "name", "field_description", "ttype", "relation", "model", "model_id"],
            order="model,name",
        )

        model_fields = [
            {
                "id": item["id"],
                "name": item["name"],
                "field_description": item["field_description"],
                "ttype": item["ttype"],
                "relation": item.get("relation") or "",
                "model": item["model"],
                "model_id": item["model_id"][0] if item.get("model_id") else False,
                "display_name": f"{item['field_description']} ({item['model']}.{item['name']})",
                "key": f"{item['model']}::{item['name']}",
            }
            for item in fields_data
        ]

        action_options = self.env["ir.actions.act_window"].sudo().search_read(
            [("res_model", "=", version.res_model_name)],
            ["id", "name", "res_model"],
            order="name",
        )
        template_options = self.env["mail.template"].sudo().search_read(
            [("model", "in", [version.res_model_name, "workflow.category.version.meta.task"])],
            ["id", "name", "model"],
            order="name",
        )
        user_options = [
            self._workflow_studio_serialize_user_option(user)
            for user in self.env["res.users"].sudo().search([("active", "=", True)], order="name")
        ]
        approval_group_options = [
            self._workflow_studio_serialize_approval_group_option(group)
            for group in self.env["workflow.approval.group"].sudo().search([], order="name")
        ]
        group_options = [
            self._workflow_studio_serialize_res_group_option(group)
            for group in self.env["res.groups"].sudo().search([], order="name")
        ]
        workflow_action_model = self.env["workflow.approval.action"].sudo()
        workflow_actions = workflow_action_model.search(
            ["|", ("version_id", "=", False), ("version_id", "=", version.id)],
            order="name,id",
        )
        workflow_actions |= workflow_action_model.browse(tasks.mapped("activity_type_ids").ids).exists()
        workflow_actions = workflow_actions.sorted(key=lambda rec: ((rec.name or "").lower(), rec.id))
        workflow_action_options = [
            self._workflow_studio_serialize_workflow_action_option(action)
            for action in workflow_actions
        ]
        server_action_domain = []
        if version.res_model_id:
            server_action_domain = [("model_id", "=", version.res_model_id.id)]
        server_action_options = [
            self._workflow_studio_serialize_server_action_option(server_action)
            for server_action in self.env["ir.actions.server"].sudo().search(
                server_action_domain, order="name,id"
            )
        ]
        called_workflow_options = self.env["workflow.approval.category.version"].sudo().search_read(
            [("id", "!=", version.id)],
            ["id", "name", "display_name", "category_id"],
            order="id desc",
        )
        rule_set_options = self.env["workflow.field.rule.set"].sudo().search_read(
            [("active", "=", True)],
            ["id", "name", "category_id", "version_id"],
            order="sequence,id",
        )
        department_options = self.env["hr.department"].sudo().search_read(
            [],
            ["id", "name"],
            order="name",
        )

        return {
            "version": {
                "id": version.id,
                "name": version.name or "",
                "title": version.title or "",
                "display_name": version.display_name or "",
                "category_id": version.category_id.id if version.category_id else False,
                "category_name": version.category_id.display_name if version.category_id else "",
                "res_model_id": version.res_model_id.id if version.res_model_id else False,
                "res_model_name": version.res_model_name or "",
                "is_active": bool(version.is_active),
                "is_locked": bool(version.is_locked),
                "is_published": bool(version.is_published),
                "deployed_at": fields.Datetime.to_string(version.deployed_at)
                if version.deployed_at
                else False,
                "published_at": fields.Datetime.to_string(version.published_at)
                if version.published_at
                else False,
                "lifecycle_state": version._workflow_studio_lifecycle_state(),
                "lifecycle_label": version._workflow_studio_lifecycle_label(),
                "bpmn_xml": version.bpmn_xml or "",
            },
            "version_control": version._workflow_studio_build_version_control(version.category_id),
            "options": {
                "fields": model_fields,
                "field_types": [
                    {"value": "visible", "label": "Visible"},
                    {"value": "required", "label": "Required"},
                    {"value": "readonly", "label": "Readonly"},
                    {"value": "invisible", "label": "Invisible"},
                ],
                "activity_types": [
                    {"value": "logActivity", "label": "Log Activity"},
                ],
                "dialog_types": [
                    {"value": "confirm", "label": "Confirm"},
                    {"value": "proceed", "label": "Proceed"},
                    {"value": "reject", "label": "Reject with reason"},
                ],
                "actions": action_options,
                "templates": template_options,
                "users": user_options,
                "approval_groups": approval_group_options,
                "groups": group_options,
                "workflow_actions": workflow_action_options,
                "workflow_action_types": WORKFLOW_ACTION_TYPE_OPTIONS,
                "server_actions": server_action_options,
                "called_workflows": called_workflow_options,
                "rule_sets": rule_set_options,
                "departments": department_options,
                "assignment_modes": [
                    {"value": "mixed", "label": "Mixed"},
                    {"value": "explicit_users", "label": "Explicit Users"},
                    {"value": "groups", "label": "Groups"},
                    {"value": "domain", "label": "Domain"},
                    {"value": "previous_actor", "label": "Users From Workflow Node"},
                    {"value": "reentry_previous_actor", "label": "Re-entry: Previous Actor"},
                    {"value": "request_owner", "label": "Request Owner"},
                ],
                "node_user_types": [
                    {"value": "assigned", "label": "Assigned Users"},
                    {"value": "pending", "label": "Pending Users"},
                    {"value": "decided", "label": "Decided Users"},
                ],
                "notification_recipient_sources": [
                    {"value": "specific_users", "label": "Specific Users"},
                    {"value": "approval_group_users", "label": "Workflow Approval Group Users"},
                    {"value": "group_users", "label": "Odoo Group Users"},
                    {"value": "node_users", "label": "Users From Workflow Node"},
                    {"value": "domain", "label": "Domain Over Users"},
                ],
                "notification_delivery_modes": [
                    {"value": "email", "label": "Send Email"},
                    {"value": "log", "label": "Log Activity"},
                    {"value": "channels", "label": "Channels"},
                ],
                "email_recipient_headers": [
                    {"value": "to", "label": "To"},
                    {"value": "cc", "label": "CC"},
                    {"value": "bcc", "label": "BCC"},
                ],
                "email_recipient_sources": [
                    {"value": "direct", "label": "Raw Emails"},
                    {"value": "send_task", "label": "Send Task Recipients"},
                    {"value": "specific_users", "label": "Specific Users"},
                    {"value": "approval_group_users", "label": "Workflow Approval Group Users"},
                    {"value": "group_users", "label": "Odoo Group Users"},
                    {"value": "node_users", "label": "Users From Workflow Node"},
                    {"value": "domain", "label": "Domain Over Users"},
                ],
                "completion_modes": [
                    {"value": "any", "label": "Any"},
                    {"value": "all", "label": "All"},
                ],
                "fallback_policies": [
                    {"value": "escalate_manager", "label": "Escalate to Manager"},
                    {"value": "route_admin_queue", "label": "Route to Admin Queue"},
                    {"value": "block", "label": "Block Task"},
                ],
                "automation_run_modes": [
                    {"value": "immediate", "label": "Immediate"},
                    {"value": "scheduled", "label": "Scheduled"},
                ],
                "automation_schedule_modes": [
                    {"value": "interval", "label": "Interval"},
                    {"value": "fixed_time", "label": "Fixed Time"},
                    {"value": "cron", "label": "Cron"},
                ],
                "automation_interval_types": [
                    {"value": "minutes", "label": "Minutes"},
                    {"value": "hours", "label": "Hours"},
                    {"value": "days", "label": "Days"},
                    {"value": "weeks", "label": "Weeks"},
                ],
                "automation_recurrence_end_modes": [
                    {"value": "forever", "label": "Forever"},
                    {"value": "count", "label": "Fixed Count"},
                    {"value": "until", "label": "Until Date"},
                    {"value": "until_success", "label": "Until First Success"},
                ],
                "join_policies": [
                    {"value": "all_of", "label": "All Of"},
                    {"value": "any_of", "label": "Any Of"},
                    {"value": "min_n", "label": "Min N"},
                ],
                "parallel_reject_policies": [
                    {"value": "strict", "label": "Strict"},
                    {"value": "soft", "label": "Soft"},
                ],
                "confidentiality_levels": [
                    {"value": "public", "label": "Public"},
                    {"value": "department", "label": "Department"},
                    {"value": "restricted", "label": "Restricted"},
                ],
                "twofa_methods": [
                    {"value": "email_otp", "label": "Email OTP"},
                    {"value": "qr", "label": "QR"},
                ],
"domain_presets": DOMAIN_PRESET_OPTIONS,
                "workflow_map_field_mapping_templates": WORKFLOW_MAP_FIELD_MAPPING_TEMPLATES,
            },
            "meta": {
                "tasks": [self._workflow_studio_serialize_meta_task(task) for task in tasks],
                "actions": [self._workflow_studio_serialize_meta_action(action) for action in actions],
                "fields": [self._workflow_studio_serialize_meta_field(meta_field) for meta_field in meta_fields],
                "approval_group_links": [
                    self._workflow_studio_serialize_approval_group_link(link) for link in approval_links
                ],
                "workflow_maps": [
                    self._workflow_studio_serialize_workflow_map(workflow_map)
                    for workflow_map in workflow_maps
                ],
            },
        }

    def workflow_studio_write_meta_task(self, task_node_id, values):
        version = self._workflow_studio_get_version(require_write=True)
        task = self.env["workflow.category.version.meta.task"].sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", task_node_id)],
            limit=1,
        )
        if not task:
            raise UserError(_("No metadata task found for node '%s'. Save and sync the diagram first.") % task_node_id)

        warnings = []
        write_vals = self._workflow_studio_prepare_task_values(values or {})
        request_model_name = version.res_model_name or task.res_model_name or ""
        routing_models = {
            "assignment_user_domain": "res.users",
            "approval_group_domain": "res.users",
            "notification_recipient_domain": "res.users",
            "notification_recipient_filter_domain": "res.users",
        }
        for field_name, target_model_name in routing_models.items():
            if field_name in (values or {}) and field_name in write_vals:
                write_vals[field_name] = self._workflow_studio_prepare_routing_domain_value(
                    field_name,
                    write_vals.get(field_name),
                    target_model_name,
                    request_model_name,
                    warnings=warnings,
                )
        if write_vals:
            task.write(write_vals)
        result = self._workflow_studio_serialize_meta_task(task)
        result["warnings"] = warnings
        return result

    def workflow_studio_write_meta_action(self, source_id, target_id, values):
        version = self._workflow_studio_get_version(require_write=True)
        action = self.env["workflow.category.version.meta.task.action"].sudo().search(
            [
                ("version_id", "=", version.id),
                ("source_id", "=", source_id),
                ("target_id", "=", target_id),
            ],
            limit=1,
        )
        if not action:
            raise UserError(
                _("No metadata action found for transition '%s -> %s'. Save and sync the diagram first.")
                % (source_id, target_id)
            )
        write_vals = self._workflow_studio_prepare_action_values(values or {})
        if write_vals:
            action.write(write_vals)
        return self._workflow_studio_serialize_meta_action(action)

    def workflow_studio_set_meta_fields(self, task_node_id, rows):
        version = self._workflow_studio_get_version(require_write=True)
        task = self.env["workflow.category.version.meta.task"].sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", task_node_id)],
            limit=1,
        )
        if not task:
            raise UserError(_("No metadata task found for node '%s'.") % task_node_id)

        field_model = self.env["workflow.category.version.meta.field"].sudo()
        action_model = self.env["workflow.category.version.meta.task.action"].sudo()
        action_map = {
            self._workflow_studio_action_key(action.source_id, action.target_id): action
            for action in action_model.search([("version_id", "=", version.id)])
        }
        warnings = []
        task.field_ids.unlink()
        valid_field_types = {"visible", "required", "readonly", "invisible"}

        def _normalize_rule_domain(row, field_type, field_record):
            domains_by_type = row.get("domains_by_type")
            domain_expression = False
            if isinstance(domains_by_type, dict):
                domain_expression = domains_by_type.get(field_type)
            if domain_expression in (None, False, ""):
                domain_expression = row.get("%s_domain" % field_type)
            if domain_expression in (None, False, ""):
                domain_expression = row.get("condition_domain") or row.get("domain") or "[]"
            domain_expression = self._workflow_studio_normalize_inline_domain_text(
                domain_expression,
                keep_false_literal=True,
            ) or "[]"
            target_model_name = version.res_model_name or field_record.model
            validation = self.workflow_studio_validate_domain_expression(
                target_model_name,
                domain_expression,
                "field_modifiers",
                target_model_name,
            )
            if not validation.get("valid"):
                raise UserError(
                    _("Invalid %(type)s domain for field %(field)s: %(error)s")
                    % {
                        "type": field_type,
                        "field": field_record.field_description or field_record.name,
                        "error": validation.get("error") or _("Domain is invalid."),
                    }
                )
            return domain_expression

        def _normalize_row_field_types(row):
            raw_types = row.get("field_types")
            has_explicit_types = isinstance(raw_types, (list, tuple))
            if not has_explicit_types:
                raw_types = [row.get("field_type") or "visible"]
            normalized = []
            for field_type in raw_types:
                field_type = (field_type or "").strip()
                if field_type in valid_field_types and field_type not in normalized:
                    normalized.append(field_type)
            if has_explicit_types and (
                "required" in normalized or "readonly" in normalized
            ) and "visible" not in normalized and "invisible" not in normalized:
                normalized.insert(0, "visible")
            if "readonly" in normalized and "required" in normalized:
                normalized = [field_type for field_type in normalized if field_type != "required"]
            return normalized or ["visible"]

        for row in rows or []:
            field_ref = row.get("field_ref")
            if not field_ref and row.get("field_id"):
                field_ref = {"id": row["field_id"]}
            if not field_ref and row.get("field_name") and row.get("field_model"):
                field_ref = {"name": row["field_name"], "model": row["field_model"]}
            field_record = self._workflow_studio_resolve_field_ref(field_ref)
            if not field_record:
                warnings.append(
                    _("Skipped field row for '%(model)s.%(field)s': field not found.")
                    % {"model": row.get("field_model"), "field": row.get("field_name")}
                )
                continue

            field_types = _normalize_row_field_types(row)
            action_keys = row.get("activity_action_keys") or []
            action_ids = [action_map[key].id for key in action_keys if key in action_map]
            for field_type in field_types:
                vals = {
                    "meta_id": task.id,
                    "field_id": field_record.id,
                    "field_type": field_type,
                    "domain": _normalize_rule_domain(row, field_type, field_record),
                }
                if field_type == "required" and action_ids:
                    vals["activity_action_ids"] = [(6, 0, action_ids)]
                field_model.create(vals)

        updated_rows = [
            self._workflow_studio_serialize_meta_field(meta_field)
            for meta_field in field_model.search([("meta_id", "=", task.id)])
        ]
        return {"rows": updated_rows, "warnings": warnings}

    def workflow_studio_set_task_approval_links(self, task_node_id, rows):
        version = self._workflow_studio_get_version(require_write=True)
        task = self.env["workflow.category.version.meta.task"].sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", task_node_id)],
            limit=1,
        )
        if not task:
            raise UserError(_("No metadata task found for node '%s'.") % task_node_id)

        Link = self.env["workflow.category.task.approval.group"].sudo()
        warnings = []
        task.approval_group_link_ids.unlink()
        for row in rows or []:
            if not isinstance(row, dict):
                warnings.append(_("Skipped approval link: invalid row payload."))
                continue

            group_payload = row.get("approval_group_ref")
            if not group_payload:
                group_payload = row.get("approval_group_id")
            if (
                not group_payload
                and isinstance(row.get("approval_group_ref"), dict)
                and row.get("approval_group_ref", {}).get("id")
            ):
                group_payload = row.get("approval_group_ref", {}).get("id")

            group = self._workflow_studio_resolve_approval_group_ref(group_payload)
            if not group:
                has_user_input = bool(
                    group_payload
                    or row.get("user_domain")
                    or row.get("domain")
                    or row.get("note")
                )
                if has_user_input:
                    warnings.append(_("Skipped approval link: approval group not found."))
                continue

            try:
                sequence = int(row.get("sequence") or 10)
            except Exception:
                sequence = 10

            request_model_name = version.res_model_name or task.res_model_name or ""
            group_debug_name = group.display_name or group.name or (_("Approval Group #%(id)s") % {"id": group.id})
            normalized_user_domain = self._workflow_studio_prepare_routing_domain_value(
                "user_domain",
                row.get("user_domain"),
                "res.users",
                request_model_name,
                warnings=warnings,
                warning_label=self._workflow_studio_routing_warning_label("user_domain", group_debug_name),
            )
            normalized_domain = self._workflow_studio_prepare_routing_domain_value(
                "domain",
                row.get("domain"),
                request_model_name or "workflow.base.approval.request",
                request_model_name or "workflow.base.approval.request",
                warnings=warnings,
                warning_label=self._workflow_studio_routing_warning_label("domain", group_debug_name),
            )

            Link.create(
                {
                    "meta_id": task.id,
                    "approval_group_id": group.id,
                    "sequence": sequence,
                    "user_domain": normalized_user_domain,
                    "domain": normalized_domain,
                    "note": row.get("note") or "",
                }
            )
        updated = [
            self._workflow_studio_serialize_approval_group_link(link)
            for link in Link.search([("meta_id", "=", task.id)])
        ]
        return {"rows": updated, "warnings": warnings}

    def workflow_studio_set_task_workflow_maps(self, task_node_id, rows):
        version = self._workflow_studio_get_version(require_write=True)
        task = self.env["workflow.category.version.meta.task"].sudo().search(
            [("version_id", "=", version.id), ("node_id", "=", task_node_id)],
            limit=1,
        )
        if not task:
            raise UserError(_("No metadata task found for node '%s'.") % task_node_id)

        Map = self.env["workflow.category.version.meta.task.workflow.map"].sudo()
        warnings = []
        task.workflow_map_ids.unlink()
        for row in rows or []:
            called_workflow = self._workflow_studio_resolve_called_workflow_ref(
                row.get("called_workflow_ref")
            )
            if not called_workflow and row.get("called_workflow_id"):
                called_workflow = self._workflow_studio_resolve_called_workflow_ref(
                    row.get("called_workflow_id")
                )
            if not called_workflow:
                warnings.append(_("Skipped workflow map: called workflow not found."))
                continue
            if called_workflow.id == version.id:
                warnings.append(_("Skipped workflow map: called workflow cannot be itself."))
                continue
            Map.create(
                {
                    "meta_task_id": task.id,
                    "workflow_id": version.id,
                    "called_workflow_id": called_workflow.id,
                    "execution_mode": row.get("execution_mode") or "sync",
                    "field_mapping": row.get("field_mapping") or "",
                    "domain": row.get("domain") or "",
                }
            )
        updated = [
            self._workflow_studio_serialize_workflow_map(workflow_map)
            for workflow_map in Map.search([("meta_task_id", "=", task.id)])
        ]
        return {"rows": updated, "warnings": warnings}

    def workflow_studio_sync_from_bpmn(self, bpmn_xml=False):
        version = self._workflow_studio_get_version(require_write=True)
        if bpmn_xml:
            version.write({"bpmn_xml": bpmn_xml})
        else:
            version.sync_meta_from_bpmn(version.bpmn_xml or "")
        return version.workflow_studio_get_bpmn_payload()

    def _workflow_studio_record_is_exportable(self, record):
        xmlid = record.sudo().get_external_id().get(record.id)
        if not xmlid:
            return True
        return (
            xmlid.startswith("workflow_studio_customization.")
            or xmlid.startswith("__export__.")
        )

    def _workflow_studio_collect_menu_chain(self, menus):
        menu_chain = menus.sudo().exists()
        frontier = menu_chain
        while frontier:
            parents = frontier.mapped("parent_id").sudo().exists() - menu_chain
            if not parents:
                break
            menu_chain |= parents
            frontier = parents
        return menu_chain

    def _workflow_studio_collect_export_records(self):
        version = self._workflow_studio_get_version()
        records_by_model = defaultdict(lambda: self.env["ir.model"].browse())

        def add(model_name, records, *, filter_exportable=False):
            records = records.sudo().exists()
            if filter_exportable:
                records = records.filtered(lambda rec: self._workflow_studio_record_is_exportable(rec))
            if not records:
                return
            existing = records_by_model.get(model_name, self.env[model_name].browse())
            records_by_model[model_name] = (existing | records).sudo()

        model_name = version.res_model_name
        model_id = version.res_model_id.sudo()
        if not model_name or not model_id:
            return {}

        task_model = self.env["workflow.category.version.meta.task"].sudo()
        action_model = self.env["workflow.category.version.meta.task.action"].sudo()
        link_model = self.env["workflow.category.task.approval.group"].sudo()
        workflow_action_model = self.env["workflow.approval.action"].sudo()

        tasks = task_model.search([("version_id", "=", version.id)])
        transitions = action_model.search([("version_id", "=", version.id)])
        links = link_model.search([("meta_id", "in", tasks.ids)])
        workflow_actions = workflow_action_model.browse(tasks.mapped("activity_type_ids").ids)

        add("ir.model", model_id)
        add(
            "ir.model.fields",
            self.env["ir.model.fields"].sudo().search(
                [("model_id", "=", model_id.id), ("state", "!=", "base")]
            ),
        )

        action_windows = (
            self.env["ir.actions.act_window"].sudo().search([("res_model", "=", model_name)])
            | tasks.mapped("action_id").sudo().exists()
        )
        add("ir.actions.act_window", action_windows)
        add(
            "ir.actions.act_window.view",
            self.env["ir.actions.act_window.view"].sudo().search([("act_window_id", "in", action_windows.ids)]),
        )

        views = self.env["ir.ui.view"].sudo().search([("model", "=", model_name)])
        report_actions = self.env["ir.actions.report"].sudo().search([("model", "=", model_name)])
        if report_actions:
            report_views = self.env["ir.ui.view"].sudo().search([("key", "in", report_actions.mapped("report_name"))])
            views |= report_views
        add("ir.ui.view", views)
        add("ir.actions.report", report_actions)
        add("report.paperformat", report_actions.mapped("paperformat_id"))

        templates = (
            tasks.mapped("email_template_external_id")
            | tasks.mapped("activity_message_template")
            | workflow_actions.mapped("email_template_id")
        ).sudo().exists()
        add("mail.template", templates)

        automation = self.env["base.automation"].sudo().search([("model_id", "=", model_id.id)])
        add("base.automation", automation)
        add(
            "ir.actions.server",
            self.env["ir.actions.server"].sudo().search(
                ["|", ("model_id", "=", model_id.id), ("binding_model_id", "=", model_id.id)]
            )
            | automation.mapped("action_server_ids")
            | workflow_actions.mapped("server_action_id"),
        )

        access_rules = self.env["ir.model.access"].sudo().search([("model_id", "=", model_id.id)])
        record_rules = self.env["ir.rule"].sudo().search([("model_id", "=", model_id.id)])
        add("ir.model.access", access_rules)
        add("ir.rule", record_rules)
        add("ir.filters", self.env["ir.filters"].sudo().search([("model_id", "=", model_id.id)]))
        add("ir.default", self.env["ir.default"].sudo().search([("field_id.model_id", "=", model_id.id)]))
        add("workflow.studio.approval.rule", self.env["workflow.studio.approval.rule"].sudo().search([("model_id", "=", model_id.id)]))

        action_window_group_field = (
            "group_ids" if "group_ids" in action_windows._fields else "groups_id"
        )
        groups = (
            access_rules.mapped("group_id")
            | record_rules.mapped("groups")
            | action_windows.mapped(action_window_group_field)
            | report_actions.mapped("group_ids")
        ).sudo().exists()
        add("res.groups", groups)
        add("res.groups", groups.mapped("implied_ids"))
        add("res.groups.privilege", groups.mapped("privilege_id"))
        add("ir.module.category", groups.mapped("privilege_id.category_id"))

        action_refs = [f"ir.actions.act_window,{action_id}" for action_id in action_windows.ids]
        menu_records = self.env["ir.ui.menu"].sudo().search([("action", "in", action_refs)]) if action_refs else self.env["ir.ui.menu"]
        add("ir.ui.menu", self._workflow_studio_collect_menu_chain(menu_records))

        # Keep only models we actually support in StudioExportWizard
        supported_models = {
            "res.groups",
            "res.groups.privilege",
            "ir.module.category",
            "report.paperformat",
            "ir.model",
            "ir.model.fields",
            "ir.ui.view",
            "ir.actions.act_window",
            "ir.actions.act_window.view",
            "ir.actions.report",
            "mail.template",
            "ir.actions.server",
            "ir.ui.menu",
            "ir.filters",
            "base.automation",
            "ir.model.access",
            "ir.rule",
            "ir.default",
            "workflow.studio.approval.rule",
        }
        return {
            model_name: records
            for model_name, records in records_by_model.items()
            if model_name in supported_models and records
        }

    def _workflow_studio_export_customizations_zip(self):
        version = self._workflow_studio_get_version()
        records_by_model = version._workflow_studio_collect_export_records()
        if not records_by_model:
            return {"content": False, "warnings": [], "models": []}

        export_data_vals = []
        for model_name in sorted(records_by_model):
            for record in records_by_model[model_name]:
                export_data_vals.append({"model": model_name, "res_id": record.id, "workflow_studio": True})

        ExportData = self.env["workflow.studio.export.wizard.data"].sudo()
        wizard_model = self.env["workflow.studio.export.wizard"].sudo()
        module = self.env["ir.module.module"].sudo().get_studio_module()

        data_rows = ExportData.create(export_data_vals)
        # Make workflow bundle portable across databases/environments by forcing
        # local export xmlids (instead of source-module xmlids like it_request.*).
        for row in data_rows:
            row.xmlid = "__export__.%s_%s" % (row.model.replace(".", "_"), row.res_id)

        wizard = wizard_model.create(
            {
                "default_export_data": [(6, 0, data_rows.ids)],
                "include_additional_data": False,
                "include_demo_data": False,
            }
        )

        try:
            export_info = wizard.get_export_info()
            serializer = StudioExportSerializer(self.sudo().env, module, export_info)
            files = list(serializer.serialize())
            warnings = list(getattr(serializer, "warnings", []) or [])
            with io.BytesIO() as output:
                with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
                    for filename, content in files:
                        if filename.endswith(".xml"):
                            content, _rewritten = self._workflow_studio_rewrite_context_markers(content)
                        archive.writestr(f"{module.name}/{filename}", content)
                content = output.getvalue()
        finally:
            wizard.unlink()
            data_rows.unlink()

        return {
            "content": content,
            "warnings": warnings,
            "models": sorted(records_by_model.keys()),
        }

    def _workflow_studio_build_category_snapshot(self):
        version = self._workflow_studio_get_version()
        category = version.category_id.sudo()
        category_image = category.image or False
        if isinstance(category_image, memoryview):
            category_image = category_image.tobytes()
        if isinstance(category_image, bytearray):
            category_image = bytes(category_image)
        if isinstance(category_image, bytes):
            category_image = category_image.decode("utf-8")
        return {
            "name": category.name or "",
            "description": category.description or "",
            "guide_html": category.guide_html or "",
            "image": category_image,
            "sequence": category.sequence or 0,
            "department_ref": self._workflow_studio_serialize_ref(
                category.department_id, extra={"name": category.department_id.name if category.department_id else ""}
            ),
            "requirer_document": category.requirer_document or "optional",
            "approval_minimum": category.approval_minimum or 1,
            "approval_type": category.approval_type or False,
            "manager_approval": category.manager_approval or False,
            "approver_sequence": bool(category.approver_sequence),
            "automated_sequence": bool(category.automated_sequence),
            "sequence_code": category.sequence_code or "",
            "allowed_duplicate": bool(category.allowed_duplicate),
            "allow_duplicate_domain": category.allow_duplicate_domain or "",
            "auto_cancel_timeout": category.auto_cancel_timeout or 0,
            # "auto_approve_timeout": category.auto_approve_timeout or 0,
            # "allow_workflow_admin_edit_timeout": bool(category.allow_workflow_admin_edit_timeout),
            "approvers": [
                {
                    "sequence": approver.sequence or 10,
                    "required": bool(approver.required),
                    "user_ref": self._workflow_studio_serialize_ref(
                        approver.user_id,
                        extra={
                            "name": approver.user_id.name,
                            "login": approver.user_id.login,
                            "email": approver.user_id.email,
                        },
                    ),
                }
                for approver in category.approver_ids.sorted("sequence")
                if approver.user_id
            ],
        }

    def _workflow_studio_build_reference_snapshot(self):
        version = self._workflow_studio_get_version()
        task_model = self.env["workflow.category.version.meta.task"].sudo()
        link_model = self.env["workflow.category.task.approval.group"].sudo()
        tasks = task_model.search([("version_id", "=", version.id)])
        links = link_model.search([("meta_id", "in", tasks.ids)])
        workflow_actions = self.env["workflow.approval.action"].sudo().browse(tasks.mapped("activity_type_ids").ids)
        approval_groups = links.mapped("approval_group_id").sudo().exists()
        return {
            "approval_groups": [
                {
                    "ref": self._workflow_studio_serialize_ref(group, extra={"name": group.name or ""}),
                    "name": group.name or "",
                    "parent_ref": self._workflow_studio_serialize_ref(group.parent_id, extra={"name": group.parent_id.name if group.parent_id else ""}),
                    "department_ref": self._workflow_studio_serialize_ref(group.department_id, extra={"name": group.department_id.name if group.department_id else ""}),
                    "user_refs": [
                        self._workflow_studio_serialize_ref(
                            user, extra={"name": user.name, "login": user.login, "email": user.email}
                        )
                        for user in group.user_ids
                    ],
                }
                for group in approval_groups
            ],
            "workflow_actions": [
                {
                    "ref": self._workflow_studio_serialize_ref(
                        action,
                        extra={"name": action.name or "", "action_type": action.action_type or "workflow"},
                    ),
                    "name": action.name or "",
                    "action_type": action.action_type or "workflow",
                    "domain": action.domain or "",
                    "domain_string": action.domain_string or "",
                    "message_body": action.message_body or "",
                    "telegram_webhook_url": action.telegram_webhook_url or "",
                    "webhook_url": action.webhook_url or "",
                    "code": action.code or "",
                    "email_template_ref": self._workflow_studio_serialize_ref(
                        action.email_template_id,
                        extra={
                            "name": action.email_template_id.name if action.email_template_id else "",
                            "model": action.email_template_id.model if action.email_template_id else "",
                        },
                    ),
                    "server_action_ref": self._workflow_studio_serialize_ref(
                        action.server_action_id,
                        extra={
                            "name": action.server_action_id.name if action.server_action_id else "",
                            "model": action.server_action_id.model_name if action.server_action_id else "",
                        },
                    ),
                }
                for action in workflow_actions
            ],
        }

    def _workflow_studio_import_customizations_zip(self, zip_content):
        if not zip_content:
            return []
        importer = self.env["workflow.studio.import.zip.wizard"].sudo()
        try:
            return importer._pre_import_customizations_zip_content(
                zip_content,
                dry_run=bool(self.env.context.get("workflow_studio_dry_run")),
            )
        except Exception as error:
            raise UserError(_("Failed to import Workflow Studio customizations module: %s") % error) from error

    def _workflow_studio_resolve_department_ref(self, ref_data):
        try:
            Department = self.env["hr.department"].sudo()
        except KeyError:
            return False
        if not ref_data:
            return Department
        if isinstance(ref_data, int):
            return Department.browse(ref_data).exists()
        if not isinstance(ref_data, dict):
            return Department
        department = self._workflow_studio_resolve_ref_by_xmlid("hr.department", ref_data.get("xmlid"))
        if department:
            return department
        if ref_data.get("name"):
            department = Department.search([("name", "=", ref_data["name"])], limit=1)
            if department:
                return department
        if ref_data.get("id"):
            department = Department.browse(ref_data["id"]).exists()
            if department:
                return department
        return Department

    def _workflow_studio_apply_category_snapshot(self, category_snapshot):
        version = self._workflow_studio_get_version()
        category = version.category_id.sudo()
        if not isinstance(category_snapshot, dict) or not category_snapshot:
            return []

        warnings = []
        write_vals = {}
        allowed_fields = {
            "name",
            "description",
            "guide_html",
            "image",
            "sequence",
            "requirer_document",
            "approval_minimum",
            "approval_type",
            "manager_approval",
            "approver_sequence",
            "automated_sequence",
            "sequence_code",
            "allowed_duplicate",
            "allow_duplicate_domain",
            "auto_cancel_timeout",
            # "auto_approve_timeout",
            # "allow_workflow_admin_edit_timeout",
        }
        for field_name in allowed_fields:
            if field_name in category_snapshot:
                write_vals[field_name] = category_snapshot.get(field_name)

        if category_snapshot.get("department_ref"):
            department = self._workflow_studio_resolve_department_ref(category_snapshot.get("department_ref"))
            if department:
                write_vals["department_id"] = department.id

        if write_vals:
            category.write(write_vals)

        if "approvers" in category_snapshot:
            approver_model = self.env["workflow.approval.category.approver"].sudo()
            category.approver_ids.sudo().unlink()
            for row in category_snapshot.get("approvers") or []:
                users = self.with_context(
                    workflow_studio_create_missing_refs=True
                )._workflow_studio_resolve_user_refs([row.get("user_ref")])
                user = users[:1]
                if not user:
                    warnings.append(_("Skipped category approver row: user not found."))
                    continue
                approver_model.create(
                    {
                        "category_id": category.id,
                        "user_id": user.id,
                        "sequence": row.get("sequence") or 10,
                        "required": bool(row.get("required")),
                    }
                )
        return warnings

    def _workflow_studio_apply_reference_snapshot(self, references):
        if not isinstance(references, dict):
            return []
        warnings = []
        for group_data in references.get("approval_groups") or []:
            group = self.with_context(
                workflow_studio_create_missing_refs=True
            )._workflow_studio_resolve_approval_group_ref(group_data.get("ref"))
            if not group and group_data.get("name"):
                group = self.env["workflow.approval.group"].sudo().create({"name": group_data["name"]})
            if not group:
                warnings.append(_("Skipped approval group import row: unable to resolve group."))
                continue
            values = {}
            parent = self.with_context(
                workflow_studio_create_missing_refs=True
            )._workflow_studio_resolve_approval_group_ref(group_data.get("parent_ref"))
            if parent:
                values["parent_id"] = parent.id
            department = self._workflow_studio_resolve_department_ref(group_data.get("department_ref"))
            if department:
                values["department_id"] = department.id
            users = self.with_context(
                workflow_studio_create_missing_refs=True
            )._workflow_studio_resolve_user_refs(group_data.get("user_refs"))
            if users:
                values["user_ids"] = [(6, 0, users.ids)]
            if values:
                group.write(values)

        for action_data in references.get("workflow_actions") or []:
            action = self.with_context(
                workflow_studio_create_missing_refs=True,
                workflow_studio_target_version_id=self.id,
            )._workflow_studio_resolve_workflow_action_refs([action_data.get("ref")])[:1]
            if not action and action_data.get("name"):
                action = self.env["workflow.approval.action"].sudo().create(
                    {
                        "name": action_data.get("name"),
                        "action_type": action_data.get("action_type") or "workflow",
                        "version_id": self.id,
                    }
                )
            if not action:
                warnings.append(_("Skipped workflow action import row: unable to resolve action."))
                continue
            vals = {
                "name": action_data.get("name") or action.name,
                "action_type": action_data.get("action_type") or action.action_type,
                "domain": action_data.get("domain") or "",
                "domain_string": action_data.get("domain_string") or "",
                "message_body": action_data.get("message_body") or "",
                "telegram_webhook_url": action_data.get("telegram_webhook_url") or "",
                "webhook_url": action_data.get("webhook_url") or "",
                "code": action_data.get("code") or "",
            }
            template = self._workflow_studio_resolve_template_ref(action_data.get("email_template_ref"))
            vals["email_template_id"] = template.id if template else False
            server_action = self._workflow_studio_resolve_server_action_ref(action_data.get("server_action_ref"))
            vals["server_action_id"] = server_action.id if server_action else False
            action.write(vals)
        return warnings

    def _workflow_studio_build_export_module_name(self):
        self.ensure_one()
        category_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", (self.category_id.name or "workflow").strip())
        version_slug = re.sub(r"[^a-zA-Z0-9_]+", "_", (self.name or "version").strip())
        module_name = f"wf_{category_slug}_{version_slug}_studio".lower().strip("_")
        module_name = re.sub(r"_+", "_", module_name)
        if not module_name:
            module_name = "wf_workflow_studio_export"
        if module_name[0].isdigit():
            module_name = f"wf_{module_name}"
        return module_name[:63]

    def _workflow_studio_build_installable_manifest(self):
        self.ensure_one()
        return {
            "name": f"Workflow Studio Export - {self.category_id.display_name}",
            "summary": "Workflow Studio category package",
            "version": "19.0.1.0.0",
            "category": "Workflow",
            "author": self.env.company.name or "Workflow Studio",
            "license": "LGPL-3",
            "depends": ["workflow_engine", "workflow_studio"],
            "data": [],
            "post_init_hook": "post_init_hook",
            "installable": True,
            "application": False,
        }

    def _workflow_studio_build_post_init_hook(self, module_name, bundle_files):
        bundle_files_content = pprint.pformat(bundle_files, sort_dicts=False)
        return (
            "# -*- coding: utf-8 -*-\n"
            "import base64\n"
            "import io\n"
            "import os\n"
            "import zipfile\n"
            "\n"
            "from odoo import SUPERUSER_ID, api\n"
            "from odoo.modules.module import get_module_resource\n"
            "\n"
            f"MODULE_NAME = {module_name!r}\n"
            f"BUNDLE_FILES = {bundle_files_content}\n"
            "\n"
            "\n"
            "def _build_bundle_zip_bytes():\n"
            "    with io.BytesIO() as output:\n"
            "        with zipfile.ZipFile(output, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:\n"
            "            for rel_path in BUNDLE_FILES:\n"
            "                full_path = get_module_resource(MODULE_NAME, *rel_path.split('/'))\n"
            "                if not full_path or not os.path.exists(full_path):\n"
            "                    continue\n"
            "                archive.write(full_path, arcname=rel_path)\n"
            "        return output.getvalue()\n"
            "\n"
            "\n"
            "def post_init_hook(cr, registry):\n"
            "    env = api.Environment(cr, SUPERUSER_ID, {})\n"
            "    bundle_content = _build_bundle_zip_bytes()\n"
            "    if not bundle_content:\n"
            "        return\n"
            "\n"
            "    wizard = env['workflow.studio.import.zip.wizard'].sudo().create({\n"
            "        'bundle_file': base64.b64encode(bundle_content),\n"
            "        'bundle_filename': f'{MODULE_NAME}.zip',\n"
            "        'existing_model_mode': 'sync',\n"
            "        'create_category_if_missing': True,\n"
            "        'deploy_after_import': True,\n"
            "        'run_dry_run_before_import': False,\n"
            "        'force_init_customizations': True,\n"
            "    })\n"
            "    wizard.action_import_bundle()\n"
        ).encode("utf-8")

    def _workflow_studio_detect_archive_module_root(self, names, default="workflow_studio_customization"):
        normalized_names = [
            (name or "").lstrip("/").replace("\\", "/")
            for name in (names or [])
            if name and not name.endswith("/")
        ]
        for name in normalized_names:
            if name.endswith("__manifest__.py") and "/" in name:
                return name.split("/", 1)[0]
        roots = sorted({name.split("/", 1)[0] for name in normalized_names if "/" in name})
        return roots[0] if roots else default

    def _workflow_studio_build_legacy_bundle_files(
        self,
        manifest,
        payload,
        category_snapshot,
        reference_snapshot,
        customizations,
    ):
        files = {
            "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            "bpmn/workflow.bpmn": (self.bpmn_xml or "").encode("utf-8"),
            "data/metadata.json": json.dumps(
                payload.get("meta", {}), indent=2, ensure_ascii=False
            ).encode("utf-8"),
            "data/category.json": json.dumps(
                category_snapshot, indent=2, ensure_ascii=False
            ).encode("utf-8"),
            "data/references.json": json.dumps(
                reference_snapshot, indent=2, ensure_ascii=False
            ).encode("utf-8"),
        }
        if customizations.get("content"):
            try:
                with zipfile.ZipFile(io.BytesIO(customizations["content"]), mode="r") as custom_zip:
                    custom_names = custom_zip.namelist()
                    custom_module_root = self._workflow_studio_detect_archive_module_root(custom_names)
                    payload_files = []
                    for name in custom_names:
                        if not name or name.endswith("/"):
                            continue
                        normalized_name = name.lstrip("/").replace("\\", "/")
                        if not normalized_name or normalized_name.startswith("../"):
                            continue
                        if custom_module_root and normalized_name.startswith(f"{custom_module_root}/"):
                            relative_name = normalized_name[len(custom_module_root) + 1 :]
                        else:
                            relative_name = normalized_name
                        if not relative_name or relative_name.startswith("../") or "/../" in relative_name:
                            continue
                        if relative_name in {"__manifest__.py", "__manifest__.json", "__init__.py", "hooks.py"}:
                            continue
                        if relative_name in files:
                            customizations.setdefault("warnings", []).append(
                                _(
                                    "Skipped customization payload file '%s' because it conflicts with a workflow bundle file."
                                )
                                % relative_name
                            )
                            continue
                        files[relative_name] = custom_zip.read(name)
                        payload_files.append(relative_name)
                    if payload_files:
                        files["studio_customizations_manifest.json"] = json.dumps(
                            {
                                "module_root": custom_module_root or "workflow_studio_customization",
                                "files": sorted(set(payload_files)),
                            },
                            indent=2,
                            ensure_ascii=False,
                        ).encode("utf-8")
            except zipfile.BadZipFile:
                customizations.setdefault("warnings", []).append(
                    _("Customization payload is not a valid zip; customization files were skipped.")
                )
        if customizations.get("warnings"):
            files["workflow_studio/export_warnings.txt"] = "\n".join(
                customizations["warnings"]
            ).encode("utf-8")
        return files

    def _workflow_studio_build_installable_module_files(self, module_name, legacy_bundle_files):
        manifest = self._workflow_studio_build_installable_manifest()
        bundle_file_paths = sorted(legacy_bundle_files.keys())
        module_files = {
            f"{module_name}/__init__.py": b"from . import hooks\n",
            f"{module_name}/__manifest__.py": (
                pprint.pformat(manifest, sort_dicts=False) + "\n"
            ).encode("utf-8"),
            f"{module_name}/hooks.py": self._workflow_studio_build_post_init_hook(
                module_name, bundle_file_paths
            ),
            f"{module_name}/security/ir.model.access.csv": (
                b"id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
            ),
        }
        for rel_path, content in legacy_bundle_files.items():
            module_files[f"{module_name}/{rel_path}"] = content
        return module_files

    def workflow_studio_export_bundle(self):
        version = self._workflow_studio_get_version()
        payload = version.workflow_studio_get_bpmn_payload()
        category_snapshot = version._workflow_studio_build_category_snapshot()
        reference_snapshot = version._workflow_studio_build_reference_snapshot()
        customizations = version._workflow_studio_export_customizations_zip()

        manifest = {
            "format": "workflow_studio_bundle_v2",
            "exported_at": fields.Datetime.now().isoformat(),
            "category": {
                "id": version.category_id.id if version.category_id else False,
                "name": version.category_id.display_name if version.category_id else "",
            },
            "version": {
                "id": version.id,
                "name": version.name,
                "title": version.title,
                "display_name": version.display_name,
                "is_published": bool(version.is_published),
                "deployed_at": fields.Datetime.to_string(version.deployed_at)
                if version.deployed_at
                else False,
                "published_at": fields.Datetime.to_string(version.published_at)
                if version.published_at
                else False,
                "lifecycle_state": version._workflow_studio_lifecycle_state(),
            },
            "res_model_name": version.res_model_name,
            "features": {
                "bpmn": True,
                "metadata": True,
                "category": True,
                "references": True,
                "studio_customizations": bool(customizations.get("content")),
            },
            "customization_models": customizations.get("models", []),
            "warnings_count": len(customizations.get("warnings", [])),
        }
        legacy_bundle_files = version._workflow_studio_build_legacy_bundle_files(
            manifest,
            payload,
            category_snapshot,
            reference_snapshot,
            customizations,
        )
        export_module_name = version._workflow_studio_build_export_module_name()
        module_files = version._workflow_studio_build_installable_module_files(
            export_module_name,
            legacy_bundle_files,
        )
        filename = f"{export_module_name}.zip"

        with io.BytesIO() as output:
            with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path, content in module_files.items():
                    archive.writestr(path, content)
            content = base64.b64encode(output.getvalue()).decode()
        return {
            "filename": filename,
            "content": content,
            "warnings": customizations.get("warnings", []),
        }

    def _workflow_studio_apply_imported_metadata(self, metadata):
        version = self._workflow_studio_get_version()
        warnings = []

        task_model = self.env["workflow.category.version.meta.task"].sudo()
        action_model = self.env["workflow.category.version.meta.task.action"].sudo()
        field_model = self.env["workflow.category.version.meta.field"].sudo()
        link_model = self.env["workflow.category.task.approval.group"].sudo()
        map_model = self.env["workflow.category.version.meta.task.workflow.map"].sudo()

        tasks = task_model.search([("version_id", "=", version.id)])
        actions = action_model.search([("version_id", "=", version.id)])
        tasks_by_node = {task.node_id: task for task in tasks}
        actions_by_key = {
            self._workflow_studio_action_key(action.source_id, action.target_id): action
            for action in actions
        }

        imported_tasks = metadata.get("tasks", [])
        for task_data in imported_tasks:
            node_id = task_data.get("node_id")
            if not node_id or node_id not in tasks_by_node:
                warnings.append(_("Skipped task metadata for node '%s': node not found.") % node_id)
                continue
            task = tasks_by_node[node_id]
            task.write(self._workflow_studio_prepare_task_values(task_data))

        imported_actions = metadata.get("actions", [])
        for action_data in imported_actions:
            source_id = action_data.get("source_id")
            target_id = action_data.get("target_id")
            action_key = self._workflow_studio_action_key(source_id, target_id)
            action = actions_by_key.get(action_key)
            if not action:
                warnings.append(
                    _("Skipped transition metadata for '%(source)s -> %(target)s': transition not found.")
                    % {"source": source_id, "target": target_id}
                )
                continue
            action.write(self._workflow_studio_prepare_action_values(action_data))

        # Replace field/approval/workflow mappings from imported snapshot
        field_model.search([("meta_id", "in", tasks.ids)]).unlink()
        link_model.search([("meta_id", "in", tasks.ids)]).unlink()
        map_model.search([("meta_task_id", "in", tasks.ids)]).unlink()

        for field_data in metadata.get("fields", []):
            task = tasks_by_node.get(field_data.get("task_node_id"))
            if not task:
                warnings.append(_("Skipped field metadata: task node not found."))
                continue
            field_record = self._workflow_studio_resolve_field_ref(field_data.get("field_ref"))
            if not field_record:
                warnings.append(_("Skipped field metadata: field not found."))
                continue
            action_ids = []
            for key in field_data.get("activity_action_keys") or []:
                action = actions_by_key.get(key)
                if action:
                    action_ids.append(action.id)
            vals = {
                "meta_id": task.id,
                "field_id": field_record.id,
                "field_type": field_data.get("field_type") or "required",
                "domain": field_data.get("domain") or field_data.get("condition_domain") or "[]",
            }
            if action_ids:
                vals["activity_action_ids"] = [(6, 0, action_ids)]
            field_model.create(vals)

        for link_data in metadata.get("approval_group_links", []):
            task = tasks_by_node.get(link_data.get("task_node_id"))
            if not task:
                warnings.append(_("Skipped approval-group metadata: task node not found."))
                continue
            group = self._workflow_studio_resolve_approval_group_ref(link_data.get("approval_group_ref"))
            if not group:
                warnings.append(_("Skipped approval-group metadata: approval group not found."))
                continue
            link_model.create(
                {
                    "meta_id": task.id,
                    "approval_group_id": group.id,
                    "sequence": link_data.get("sequence") or 10,
                    "user_domain": link_data.get("user_domain") or "",
                    "domain": link_data.get("domain") or "",
                    "note": link_data.get("note") or "",
                }
            )

        for workflow_map_data in metadata.get("workflow_maps", []):
            task = tasks_by_node.get(workflow_map_data.get("task_node_id"))
            if not task:
                warnings.append(_("Skipped workflow-map metadata: task node not found."))
                continue
            called_workflow = self._workflow_studio_resolve_called_workflow_ref(
                workflow_map_data.get("called_workflow_ref")
            )
            if not called_workflow:
                warnings.append(_("Skipped workflow-map metadata: called workflow not found."))
                continue
            if called_workflow.id == version.id:
                warnings.append(_("Skipped workflow-map metadata: called workflow cannot be itself."))
                continue
            map_model.create(
                {
                    "meta_task_id": task.id,
                    "workflow_id": version.id,
                    "called_workflow_id": called_workflow.id,
                    "execution_mode": workflow_map_data.get("execution_mode") or "sync",
                    "field_mapping": workflow_map_data.get("field_mapping") or "",
                    "domain": workflow_map_data.get("domain") or "",
                }
            )

        return warnings

    def workflow_studio_import_bundle(self, bundle_content):
        version = self._workflow_studio_get_version(require_write=True)
        if not bundle_content:
            raise UserError(_("No ZIP content was provided."))

        try:
            raw_content = base64.b64decode(bundle_content)
            with zipfile.ZipFile(io.BytesIO(raw_content), mode="r") as archive:
                names = archive.namelist()
                bpmn_path = next((name for name in names if name.endswith(".bpmn")), False)
                metadata_path = next(
                    (
                        name
                        for name in names
                        if name.endswith("data/metadata.json") or name.endswith("metadata.json")
                    ),
                    False,
                )
                category_path = next((name for name in names if name.endswith("data/category.json")), False)
                references_path = next((name for name in names if name.endswith("data/references.json")), False)
                customizations_path = next(
                    (
                        name
                        for name in names
                        if name.endswith("workflow_studio/workflow_customizations.zip")
                        or name.endswith("studio/workflow_customizations.zip")
                        or name.endswith("workflow_customizations.zip")
                    ),
                    False,
                )
                payload_manifest_path = next(
                    (
                        name
                        for name in names
                        if name.endswith("studio_customizations_manifest.json")
                        or name.endswith("data/studio_payload_manifest.json")
                        or name.endswith("studio_payload_manifest.json")
                    ),
                    False,
                )
                archive_entries_by_relative = {}
                for name in names:
                    if not name or name.endswith("/"):
                        continue
                    normalized_name = name.lstrip("/").replace("\\", "/")
                    if not normalized_name:
                        continue
                    relative_name = normalized_name.split("/", 1)[1] if "/" in normalized_name else normalized_name
                    archive_entries_by_relative.setdefault(relative_name, name)
                payload_entries = []
                payload_module_root = False
                if payload_manifest_path:
                    try:
                        payload_meta = json.loads(archive.read(payload_manifest_path).decode("utf-8"))
                    except Exception:
                        payload_meta = {}
                    requested_root = (payload_meta.get("module_root") or "").strip()
                    if requested_root:
                        payload_module_root = requested_root
                    for relative_name in payload_meta.get("files") or []:
                        normalized_relative = (relative_name or "").lstrip("/").replace("\\", "/")
                        if (
                            not normalized_relative
                            or normalized_relative.startswith("../")
                            or "/../" in normalized_relative
                        ):
                            continue
                        entry_name = archive_entries_by_relative.get(normalized_relative)
                        if entry_name:
                            payload_entries.append((entry_name, normalized_relative))

                if not payload_entries:
                    for name in names:
                        if not name or name.endswith("/"):
                            continue
                        normalized_name = name.lstrip("/").replace("\\", "/")
                        relative_name = False
                        if "/data/studio_payload/" in normalized_name:
                            relative_name = normalized_name.split("/data/studio_payload/", 1)[1].lstrip("/")
                        elif normalized_name.startswith("data/studio_payload/"):
                            relative_name = normalized_name[len("data/studio_payload/") :].lstrip("/")
                        if relative_name:
                            payload_entries.append((name, relative_name))
                customizations_dir_entries = []
                for name in names:
                    if not name or name.endswith("/"):
                        continue
                    normalized_name = name.lstrip("/").replace("\\", "/")
                    relative_name = False
                    if "/customizations/" in normalized_name:
                        relative_name = normalized_name.split("/customizations/", 1)[1].lstrip("/")
                    elif normalized_name.startswith("customizations/"):
                        relative_name = normalized_name[len("customizations/") :].lstrip("/")
                    elif "/workflow_studio/customizations/" in normalized_name:
                        relative_name = normalized_name.split(
                            "/workflow_studio/customizations/", 1
                        )[1].lstrip("/")
                    elif normalized_name.startswith("workflow_studio/customizations/"):
                        relative_name = normalized_name[len("workflow_studio/customizations/") :].lstrip("/")
                    if relative_name:
                        customizations_dir_entries.append((name, relative_name))
                bpmn_xml = archive.read(bpmn_path).decode("utf-8") if bpmn_path else ""
                metadata = (
                    json.loads(archive.read(metadata_path).decode("utf-8"))
                    if metadata_path
                    else {}
                )
                category_snapshot = (
                    json.loads(archive.read(category_path).decode("utf-8"))
                    if category_path
                    else {}
                )
                references = (
                    json.loads(archive.read(references_path).decode("utf-8"))
                    if references_path
                    else {}
                )
                if customizations_path:
                    customizations_content = archive.read(customizations_path)
                elif payload_entries:
                    customizations_module_root = payload_module_root or "workflow_studio_customization"

                    customizations_entries = []
                    for entry_name, relative_name in payload_entries:
                        normalized_relative = relative_name.lstrip("/").replace("\\", "/")
                        if not normalized_relative or normalized_relative.startswith("../") or "/../" in normalized_relative:
                            continue
                        customizations_entries.append((entry_name, normalized_relative))

                    if not customizations_entries:
                        customizations_content = False
                    else:
                        data_files = []
                        with io.BytesIO() as customizations_output:
                            with zipfile.ZipFile(
                                customizations_output, mode="w", compression=zipfile.ZIP_DEFLATED
                            ) as customizations_archive:
                                customizations_archive.writestr(
                                    f"{customizations_module_root}/__init__.py",
                                    b"",
                                )
                                for entry_name, relative_name in customizations_entries:
                                    archive_name = f"{customizations_module_root}/{relative_name}"
                                    customizations_archive.writestr(
                                        archive_name,
                                        archive.read(entry_name),
                                    )
                                    if relative_name.endswith(".xml") or relative_name.endswith(".csv"):
                                        data_files.append(relative_name)
                                customizations_manifest = {
                                    "name": "Workflow Studio customizations",
                                    "version": "1.0",
                                    "depends": ["workflow_studio"],
                                    "data": sorted(set(data_files)),
                                    "installable": True,
                                    "application": False,
                                    "license": "OPL-1",
                                }
                                customizations_archive.writestr(
                                    f"{customizations_module_root}/__manifest__.py",
                                    (pprint.pformat(customizations_manifest, sort_dicts=False) + "\n").encode(
                                        "utf-8"
                                    ),
                                )
                            customizations_content = customizations_output.getvalue()
                elif customizations_dir_entries:
                    customizations_module_root = False
                    customizations_entries = []
                    for entry_name, relative_name in customizations_dir_entries:
                        normalized_relative = relative_name.lstrip("/").replace("\\", "/")
                        if not normalized_relative or normalized_relative.startswith("../") or "/../" in normalized_relative:
                            continue
                        if normalized_relative == ".module_root":
                            try:
                                marker = archive.read(entry_name).decode("utf-8", errors="ignore").strip()
                            except Exception:
                                marker = ""
                            if marker:
                                customizations_module_root = marker
                            continue
                        customizations_entries.append((entry_name, normalized_relative))
                    if not customizations_entries:
                        customizations_content = False
                    else:
                        with io.BytesIO() as customizations_output:
                            with zipfile.ZipFile(
                                customizations_output, mode="w", compression=zipfile.ZIP_DEFLATED
                            ) as customizations_archive:
                                for entry_name, relative_name in customizations_entries:
                                    if customizations_module_root and not relative_name.startswith(
                                        f"{customizations_module_root}/"
                                    ):
                                        archive_name = f"{customizations_module_root}/{relative_name}"
                                    else:
                                        archive_name = relative_name
                                    customizations_archive.writestr(
                                        archive_name, archive.read(entry_name)
                                    )
                            customizations_content = customizations_output.getvalue()
                else:
                    customizations_content = False
        except Exception as error:
            raise UserError(_("Invalid workflow ZIP file: %s") % error) from error

        warnings = []
        if customizations_content and not self.env.context.get("workflow_studio_skip_customization_import"):
            warnings += version._workflow_studio_import_customizations_zip(customizations_content)

        warnings += version._workflow_studio_apply_category_snapshot(category_snapshot or {})
        warnings += version._workflow_studio_apply_reference_snapshot(references or {})

        if bpmn_xml:
            version.write({"bpmn_xml": bpmn_xml})
        else:
            version.sync_meta_from_bpmn(version.bpmn_xml or "")

        warnings += version.with_context(
            workflow_studio_create_missing_refs=True,
            workflow_studio_target_version_id=version.id,
        )._workflow_studio_apply_imported_metadata(metadata or {})

        payload = version.workflow_studio_get_bpmn_payload()
        return {
            "payload": payload,
            "warnings": warnings,
            "bpmn_xml": version.bpmn_xml or "",
        }
