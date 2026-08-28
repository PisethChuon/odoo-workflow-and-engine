# -*- coding: utf-8 -*-
import copy
import logging

from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_MODE_LABELS = {
    "mixed": "Mixed",
    "explicit_users": "Explicit Users",
    "groups": "Groups",
    "domain": "Domain",
    "previous_actor": "Users From Workflow Node",
    "reentry_previous_actor": "Re-entry: Previous Actor",
    "request_owner": "Request Owner",
}

_SYSTEM_NODE_TYPES = frozenset(
    {
        "startEvent",
        "endEvent",
        "intermediateThrowEvent",
        "intermediateEventMessage",
        "intermediateCatchEvent",
        "exclusiveGateway",
        "parallelGateway",
        "inclusiveGateway",
        "eventBasedGateway",
        "complexGateway",
        "serviceTask",
        "sendTask",
        "receiveTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "subProcess",
        "callActivity",
    }
)

_EXCLUDED_NODE_TYPES = frozenset(
    {
        "intermediateThrowEvent",
        "intermediateEventMessage",
    }
)

_FALLBACK_POLICY_LABELS = {
    "block": "Block",
    "escalate_manager": "Escalate to Manager",
    "route_admin_queue": "Route to Admin Queue",
}

_STATUS_LABELS = {
    "ok": "OK",
    "warning": "Warning",
    "needs_input": "Needs Input",
    "config_error": "Config Error",
    "fallback": "Fallback",
    "blocked": "Blocked",
    "system": "System Node",
}


def _dryrun_wizard_id_from_context(env):
    wizard_id = env.context.get("default_wizard_id")
    if not wizard_id and env.context.get("active_model") == "workflow.dryrun.wizard":
        wizard_id = env.context.get("active_id")
        if not wizard_id and env.context.get("active_ids"):
            wizard_id = env.context["active_ids"][0]
    try:
        return int(wizard_id) if wizard_id else False
    except (TypeError, ValueError):
        return False


class WorkflowDryRunWizard(models.TransientModel):
    _name = "workflow.dryrun.wizard"
    _description = "Workflow Assignment Dry Run"

    category_id = fields.Many2one(
        "workflow.approval.category",
        string="Workflow Category",
        required=True,
        ondelete="cascade",
    )
    version_id = fields.Many2one(
        "workflow.approval.category.version",
        string="Version to Simulate",
        domain="[('category_id', '=', category_id)]",
        required=True,
    )
    simulated_user_id = fields.Many2one(
        "res.users",
        string="Request Owner / Submitter",
        required=True,
        domain="[('share', '=', False), ('active', '=', True)]",
        help=(
            "The user who owns or submits the simulated request. Runtime domains that use "
            "request owner, requester, creator, manager, or department symbols are evaluated against this user."
        ),
    )
    snapshot_json = fields.Json(
        string="Advanced JSON Overrides",
        default=dict,
        help=(
            "Optional raw field values used only by the dry-run evaluator. "
            "Example: {'x_nurse_id': {'id': 10}, 'x_doctor_id': {'id': 12}}"
        ),
    )
    field_input_ids = fields.One2many(
        "workflow.dryrun.field.input",
        "wizard_id",
        string="Form Values",
    )
    node_input_ids = fields.One2many(
        "workflow.dryrun.node.input",
        "wizard_id",
        string="Simulated Node Users",
    )
    result_line_ids = fields.One2many(
        "workflow.dryrun.result.line",
        "wizard_id",
        string="Assignment Results",
        readonly=True,
    )
    has_results = fields.Boolean(default=False, readonly=True)
    has_snapshot = fields.Boolean(
        compute="_compute_session_flags",
        string="Has Snapshot",
    )
    target_model_name = fields.Char(
        compute="_compute_session_flags",
        string="Target Model",
    )

    @api.depends("snapshot_json", "category_id")
    def _compute_session_flags(self):
        for wizard in self:
            wizard.has_snapshot = bool(wizard.snapshot_json)
            wizard.target_model_name = wizard.category_id.res_model_name or ""

    @api.model
    def default_get(self, field_list):
        values = super().default_get(field_list)
        category_id = values.get("category_id")
        version_id = values.get("version_id")
        if not version_id and category_id:
            category = self.env["workflow.approval.category"].browse(category_id)
            version_id = category.active_version_id.id if category.active_version_id else False
            if version_id:
                values["version_id"] = version_id
        if "node_input_ids" in field_list or "node_input_ids" not in values:
            values["node_input_ids"] = self._build_node_input_commands(
                version_id=version_id,
            )
        return values

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            current = dict(vals)
            version_id = current.get("version_id")
            if not version_id and current.get("category_id"):
                category = self.env["workflow.approval.category"].browse(current["category_id"])
                version_id = category.active_version_id.id if category.active_version_id else False
                if version_id and not current.get("version_id"):
                    current["version_id"] = version_id
            if version_id and "node_input_ids" not in current:
                current["node_input_ids"] = self._build_node_input_commands(version_id=version_id)
            prepared.append(current)
        return super().create(prepared)

    @api.onchange("category_id")
    def _onchange_category_id(self):
        self.version_id = False
        if self.category_id and self.category_id.active_version_id:
            self.version_id = self.category_id.active_version_id
        self._sync_node_input_lines()

    @api.onchange("version_id")
    def _onchange_version_id(self):
        self._sync_node_input_lines()

    def _sync_node_input_lines(self):
        for wizard in self:
            wizard.node_input_ids = wizard._build_node_input_commands(
                version_id=wizard.version_id.id,
                existing_lines=wizard.node_input_ids,
            )

    def _meta_tasks_for_results(self):
        self.ensure_one()
        return self.version_id.meta_task_ids.sorted("sequence").filtered(
            lambda meta: meta.node_id and meta.node_type not in _EXCLUDED_NODE_TYPES
        )

    @api.model
    def _build_node_input_commands(self, version_id=False, existing_lines=False):
        if not version_id:
            return [Command.clear()]
        version = self.env["workflow.approval.category.version"].browse(version_id)
        existing_map = {}
        for line in existing_lines or self.env["workflow.dryrun.node.input"]:
            if not line.node_id:
                continue
            existing_map[line.node_id] = {
                "assigned_user_ids": line.assigned_user_ids.ids,
                "decided_user_ids": line.decided_user_ids.ids,
            }
        commands = [Command.clear()]
        meta_tasks = version.meta_task_ids.sorted("sequence").filtered(
            lambda meta: meta.node_id and meta.node_type not in _EXCLUDED_NODE_TYPES
        )
        for meta in meta_tasks:
            current = existing_map.get(meta.node_id, {})
            commands.append(
                Command.create(
                    {
                        "node_id": meta.node_id or "",
                        "node_name": meta.name or meta.node_id or _("Unnamed Node"),
                        "node_type": meta.node_type or "",
                        "assigned_user_ids": [
                            Command.set(current.get("assigned_user_ids") or [])
                        ],
                        "decided_user_ids": [
                            Command.set(current.get("decided_user_ids") or [])
                        ],
                    }
                )
            )
        return commands

    def _reopen_action(self):
        self.ensure_one()
        context = dict(self.env.context or {})
        context.update(
            {
                "active_model": "workflow.dryrun.wizard",
                "active_id": self.id,
                "default_wizard_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Workflow Dry Run"),
            "res_model": "workflow.dryrun.wizard",
            "res_id": self.id,
            "views": [(self.env.ref("workflow_engine.view_workflow_dryrun_wizard_form").id, "form")],
            "view_mode": "form",
            "target": "new",
            "context": context,
        }

    def action_reopen_session(self):
        self.ensure_one()
        return self._reopen_action()

    def _ensure_wizard_ready(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_("Please select a workflow category."))
        if not self.version_id:
            raise UserError(_("Please select a version to simulate."))
        if not self.simulated_user_id:
            raise UserError(_("Please select a simulated requester."))
        if not self.category_id.res_model_name:
            raise UserError(_("The selected category has no request model configured."))

    def _build_request_stub_values(self):
        self.ensure_one()
        return {
            "name": "[DRY RUN] %s" % (self.version_id.name or self.category_id.name or ""),
            "category_id": self.category_id.id,
            "version_id": self.version_id.id,
            "request_owner_id": self.simulated_user_id.id,
            "create_uid": self.simulated_user_id.id,
            "write_uid": self.simulated_user_id.id,
            "company_id": self.category_id.company_id.id if self.category_id.company_id else False,
            "current_node_id": False,
            "previous_node_id": False,
            "current_iteration_no": 1,
            "state": "draft",
        }

    def _apply_simulated_audit_defaults(self, target_model, vals):
        """Make virtual dry-run records behave like records created by the simulated user."""
        self.ensure_one()
        vals = dict(vals or {})
        if self.simulated_user_id:
            if "create_uid" in target_model._fields and not vals.get("create_uid"):
                vals["create_uid"] = self.simulated_user_id.id
            if "write_uid" in target_model._fields and not vals.get("write_uid"):
                vals["write_uid"] = self.simulated_user_id.id
        return vals

    def _clear_results(self):
        self.ensure_one()
        if self.result_line_ids:
            self.result_line_ids.sudo().unlink()
        self.has_results = False

    def _build_manual_simulated_history(self):
        self.ensure_one()
        history = {
            "by_node": {},
            "all_assigned_user_ids": [],
            "all_decided_user_ids": [],
            "all_pending_user_ids": [],
        }
        for line in self.node_input_ids:
            if not line.node_id:
                continue
            entry = history["by_node"].setdefault(
                line.node_id or "",
                {
                    "assigned_user_ids": [],
                    "decided_user_ids": [],
                    "pending_user_ids": [],
                    "manual_assigned": False,
                    "manual_decided": False,
                },
            )
            if line.assigned_user_ids:
                ids = line.assigned_user_ids.ids
                entry["assigned_user_ids"] = ids
                entry["pending_user_ids"] = ids
                entry["manual_assigned"] = True
            if line.decided_user_ids:
                ids = line.decided_user_ids.ids
                entry["decided_user_ids"] = ids
                entry["manual_decided"] = True
        self._recompute_simulated_history_totals(history)
        return history

    def _recompute_simulated_history_totals(self, history):
        assigned = []
        decided = []
        pending = []
        for entry in (history or {}).get("by_node", {}).values():
            assigned.extend(entry.get("assigned_user_ids") or [])
            decided.extend(entry.get("decided_user_ids") or [])
            pending.extend(entry.get("pending_user_ids") or [])
        history["all_assigned_user_ids"] = list(dict.fromkeys([uid for uid in assigned if uid]))
        history["all_decided_user_ids"] = list(dict.fromkeys([uid for uid in decided if uid]))
        history["all_pending_user_ids"] = list(dict.fromkeys([uid for uid in pending if uid]))
        return history

    def _append_derived_stage_history(self, history, meta_task, resolution):
        history = copy.deepcopy(history or {"by_node": {}})
        node_id = meta_task.node_id or ""
        if not node_id:
            return self._recompute_simulated_history_totals(history)
        entry = history.setdefault("by_node", {}).setdefault(
            node_id,
            {
                "assigned_user_ids": [],
                "decided_user_ids": [],
                "pending_user_ids": [],
                "manual_assigned": False,
                "manual_decided": False,
            },
        )
        final_user_ids = list(dict.fromkeys(resolution.get("final_user_ids") or []))
        if final_user_ids and not entry.get("manual_assigned"):
            entry["assigned_user_ids"] = final_user_ids
            entry["pending_user_ids"] = final_user_ids
        return self._recompute_simulated_history_totals(history)

    def _is_notification_meta_task(self, meta_task):
        return meta_task and meta_task.node_type == "sendTask"

    def _notification_record_for_dryrun(self, request_record, eval_record):
        return eval_record or request_record

    def _emails_from_users_for_dryrun(self, record, users):
        if record and hasattr(record, "_workflow_email_addresses_from_users"):
            return record._workflow_email_addresses_from_users(users)
        addresses = set()
        for user in users or self.env["res.users"]:
            email = user.partner_id.email if user.partner_id else user.email
            if email:
                addresses.add(email)
        return sorted(addresses)

    def _merge_notification_entry(self, payload, entry):
        payload["entries"].append(entry)
        payload["recipient_user_ids"].extend(entry.get("resolved_user_ids") or [])
        payload["resolved_emails"].extend(entry.get("resolved_emails") or [])
        for header_key in ("email_to", "email_cc", "email_bcc"):
            payload[header_key].extend(entry.get(header_key) or [])
        if entry.get("config_error") or entry.get("status") == "config_error":
            payload["config_errors"].append(entry.get("error_message") or _("Notification configuration error."))
        if entry.get("error_message") and entry.get("status") not in ("would_send", "would_execute", "would_log"):
            payload["warnings"].append(entry["error_message"])

    def _notification_dryrun_result(self, request_record, eval_record, meta_task, simulated_history):
        service = self.env["workflow.engine.assignment.domain.service"].sudo()
        notification_record = self._notification_record_for_dryrun(request_record, eval_record)
        memo = {}
        recipients = service.resolve_notification_recipients(
            notification_record,
            meta_task,
            memo=memo,
            simulated_history=simulated_history,
        )
        delivery_mode = (
            notification_record._resolve_send_task_delivery_mode(meta_task)
            if hasattr(notification_record, "_resolve_send_task_delivery_mode")
            else (getattr(meta_task, "notification_delivery_mode", False) or "email")
        )
        payload = {
            "delivery_mode": delivery_mode,
            "node_id": meta_task.node_id or "",
            "node_name": meta_task.name or "",
            "base_recipient_user_ids": recipients.ids,
            "recipient_user_ids": list(recipients.ids),
            "resolved_emails": [],
            "email_to": [],
            "email_cc": [],
            "email_bcc": [],
            "entries": [],
            "warnings": [],
            "config_errors": [],
        }
        if delivery_mode == "log":
            self._merge_notification_entry(
                payload,
                {
                    "status": "would_log",
                    "action_type": "log",
                    "resolved_user_ids": recipients.ids,
                    "resolved_emails": [],
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                },
            )
            return self._finalize_notification_payload(payload)

        if delivery_mode == "channels":
            action_pool = meta_task.sudo().activity_type_ids.sudo()
            if not action_pool:
                payload["warnings"].append(_("No notification channels are configured for this send task."))
            for action in action_pool:
                entry = {
                    "action_id": action.id,
                    "action_name": action.name or "",
                    "action_type": action.action_type or "",
                    "guard_domain": action.domain or "",
                    "guard_matched": True,
                    "status": "would_execute",
                    "template_id": False,
                    "template_name": "",
                    "recipient_lines": [],
                    "resolved_user_ids": recipients.ids,
                    "resolved_emails": self._emails_from_users_for_dryrun(notification_record, recipients),
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                }
                if action.domain and hasattr(notification_record, "check_domain"):
                    try:
                        entry["guard_matched"] = bool(notification_record.check_domain(action.domain, default=False))
                    except Exception as exc:
                        entry["guard_matched"] = False
                        entry["status"] = "config_error"
                        entry["error_message"] = str(exc)
                    if not entry["guard_matched"] and entry["status"] != "config_error":
                        entry["status"] = "skipped_guard"
                if entry["guard_matched"] and action.action_type == "email":
                    email_template = action.email_template_id
                    if not email_template and hasattr(notification_record, "_resolve_send_task_email_template"):
                        email_template = notification_record._resolve_send_task_email_template(meta_task).sudo()
                    if email_template:
                        entry["template_id"] = email_template.id
                        entry["template_name"] = email_template.name or ""
                        email_payload = notification_record._workflow_build_action_email_payload(
                            action,
                            recipients,
                            notification_record,
                            meta_task,
                            memo=memo,
                        )
                        entry["recipient_lines"] = email_payload["recipient_lines"]
                        entry["resolved_user_ids"] = sorted(
                            {
                                user_id
                                for line_details in email_payload["recipient_lines"]
                                for user_id in (line_details.get("resolved_user_ids") or [])
                            }
                        )
                        entry["resolved_emails"] = sorted(
                            {
                                address
                                for line_details in email_payload["recipient_lines"]
                                for address in (line_details.get("resolved_emails") or [])
                            }
                        )
                        entry["email_to"] = email_payload["headers"].get("to", [])
                        entry["email_cc"] = email_payload["headers"].get("cc", [])
                        entry["email_bcc"] = email_payload["headers"].get("bcc", [])
                        entry["status"] = "would_send" if email_payload["email_values"] else "skipped_no_recipients"
                    else:
                        entry["status"] = "skipped_no_template"
                        entry["error_message"] = _("No email template is configured for this notification action.")
                self._merge_notification_entry(payload, entry)
            return self._finalize_notification_payload(payload)

        template = (
            notification_record._resolve_send_task_email_template(meta_task).sudo()
            if hasattr(notification_record, "_resolve_send_task_email_template")
            else self.env["mail.template"]
        )
        emails = self._emails_from_users_for_dryrun(notification_record, recipients)
        entry = {
            "status": "would_send" if template and emails else "skipped_no_recipients",
            "action_type": "email",
            "template_id": template.id if template else False,
            "template_name": template.name if template else "",
            "recipient_lines": [],
            "resolved_user_ids": recipients.ids,
            "resolved_emails": emails,
            "email_to": emails,
            "email_cc": [],
            "email_bcc": [],
            "error_message": "",
        }
        if not template:
            entry["status"] = "skipped_no_template"
            entry["error_message"] = _("No email template is configured for this send task.")
        self._merge_notification_entry(payload, entry)
        return self._finalize_notification_payload(payload)

    def _finalize_notification_payload(self, payload):
        for key in ("recipient_user_ids", "resolved_emails", "email_to", "email_cc", "email_bcc", "warnings", "config_errors"):
            payload[key] = sorted(set(payload.get(key) or []))
        payload["recipient_count"] = len(payload["recipient_user_ids"])
        payload["email_count"] = len(set(payload["email_to"] + payload["email_cc"] + payload["email_bcc"]))
        return payload

    def _prepare_request_record(self):
        self.ensure_one()
        request_model = self.env["workflow.base.approval.request"].with_user(self.simulated_user_id).sudo()
        return request_model.new(self._build_request_stub_values())

    def _prepare_eval_record(self, request_record, snapshot_values):
        self.ensure_one()
        target_model_name = self.category_id.res_model_name
        target_model = self.env[target_model_name]
        virtual_vals = target_model._workflow_virtual_vals_from_snapshot(snapshot_values)
        if target_model_name == "workflow.base.approval.request":
            seed_vals = self._build_request_stub_values()
            seed_vals.update(virtual_vals)
            seed_vals.update(
                {
                    "category_id": self.category_id.id,
                    "version_id": self.version_id.id,
                    "request_owner_id": self.simulated_user_id.id,
                }
            )
            seed_vals = self._apply_simulated_audit_defaults(target_model, seed_vals)
            return target_model.with_user(self.simulated_user_id).sudo().new(seed_vals)
        if "x_approval_base_id" in target_model._fields:
            virtual_vals["x_approval_base_id"] = request_record
        virtual_vals = self._apply_simulated_audit_defaults(target_model, virtual_vals)
        return target_model.with_user(self.simulated_user_id).sudo().new(virtual_vals)

    def _snapshot_values_from_inputs(self):
        self.ensure_one()
        snapshot = dict(self.snapshot_json or {}) if isinstance(self.snapshot_json, dict) else {}
        for line in self.field_input_ids:
            value = line._snapshot_value()
            if line.field_name and value is not None:
                snapshot[line.field_name] = value
        return snapshot

    def _status_and_diagnosis(self, meta_task, resolution):
        debug = resolution.get("debug") or {}
        notification = resolution.get("notification") or debug.get("notification") or {}
        if notification:
            if notification.get("config_errors"):
                return "config_error", notification["config_errors"][0]
            if notification.get("email_count") or notification.get("recipient_count"):
                return "ok", _(
                    "Notification dry-run resolved %(users)s user recipient(s) and %(emails)s email address(es)."
                ) % {
                    "users": notification.get("recipient_count") or 0,
                    "emails": notification.get("email_count") or 0,
                }
            return "warning", _("No notification recipients or email addresses were resolved.")
        config_errors = debug.get("config_errors") or []
        needs_input = debug.get("needs_input") or []
        warnings = resolution.get("warnings") or []
        assignee_count = len(resolution.get("final_user_ids") or [])
        eligible_count = len(resolution.get("eligible_user_ids") or [])
        fallback_policy = resolution.get("fallback_policy") or meta_task.fallback_policy or "block"
        if meta_task.node_type in _SYSTEM_NODE_TYPES:
            return "system", _("Engine-managed node; no human assignee is expected.")
        if config_errors:
            return "config_error", config_errors[0].get("message") or _("One or more assignment domains are invalid.")
        if needs_input:
            item = needs_input[0]
            source_node = item.get("source_node_id") or _("unknown node")
            user_type = item.get("user_type") or _("required users")
            return "needs_input", _("Need simulated %s from node %s.") % (user_type, source_node)
        if resolution.get("blocked"):
            return "blocked", _("No assignee resolved and fallback policy '%s' did not recover.") % fallback_policy
        if assignee_count and not eligible_count:
            return "fallback", _("No eligible assignee matched; fallback policy '%s' supplied the final users.") % fallback_policy
        if warnings:
            return "warning", warnings[0]
        return "ok", _("%s assignee(s) resolved.") % assignee_count

    def _format_delegation_info(self, delegation_map):
        if not delegation_map:
            return ""
        users = self.env["res.users"].sudo()
        parts = []
        for entry in delegation_map:
            orig = users.browse(entry.get("original_user_id")).name if entry.get("original_user_id") else "?"
            delegate = users.browse(entry.get("delegate_user_id")).name if entry.get("delegate_user_id") else "?"
            strategy = entry.get("strategy") or "replace"
            parts.append("%s -> %s (%s)" % (orig, delegate, strategy))
        return "\n".join(parts)

    def _create_result_lines(self, collected):
        self.ensure_one()
        self._clear_results()
        line_values = []
        for item in collected:
            resolution = item["resolution"]
            meta = item["meta_task"]
            status, diagnosis = self._status_and_diagnosis(meta, resolution)
            debug = resolution.get("debug") or {}
            notification = resolution.get("notification") or debug.get("notification") or {}
            line_values.append(
                {
                    "wizard_id": self.id,
                    "sequence": item["sequence"],
                    "node_name": meta.name or meta.node_id or _("Unnamed Node"),
                    "node_id": meta.node_id or "",
                    "node_type": meta.node_type or "",
                    "assignment_mode": meta.assignment_mode or "mixed",
                    "assignment_mode_label": _MODE_LABELS.get(
                        meta.assignment_mode or "mixed",
                        meta.assignment_mode or "mixed",
                    ),
                    "fallback_policy": resolution.get("fallback_policy") or meta.fallback_policy or "block",
                    "fallback_policy_label": _FALLBACK_POLICY_LABELS.get(
                        resolution.get("fallback_policy") or meta.fallback_policy or "block",
                        resolution.get("fallback_policy") or meta.fallback_policy or "block",
                    ),
                    "assignee_user_ids": [Command.set(resolution.get("final_user_ids") or [])],
                    "candidate_count": len(resolution.get("candidate_user_ids") or []),
                    "eligible_count": len(resolution.get("eligible_user_ids") or []),
                    "status": status,
                    "status_label": _STATUS_LABELS.get(status, status),
                    "diagnosis": diagnosis,
                    "warnings": "\n".join(resolution.get("warnings") or []),
                    "delegation_info": self._format_delegation_info(
                        resolution.get("delegation_map") or []
                    ),
                    "debug_json": debug,
                    "is_blocked": bool(resolution.get("blocked")),
                    "notification_recipient_user_ids": [
                        Command.set(notification.get("recipient_user_ids") or [])
                    ],
                    "notification_delivery_mode": notification.get("delivery_mode") or "",
                    "notification_email_to": "\n".join(notification.get("email_to") or []),
                    "notification_email_cc": "\n".join(notification.get("email_cc") or []),
                    "notification_email_bcc": "\n".join(notification.get("email_bcc") or []),
                    "notification_debug_json": notification,
                }
            )
        if line_values:
            self.env["workflow.dryrun.result.line"].sudo().create(line_values)
        self.has_results = True

    def _run_assignment_dryrun(self, snapshot_values):
        self.ensure_one()
        self._ensure_wizard_ready()
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        service = self.env["workflow.engine.assignment.service"].sudo()
        meta_tasks = self._meta_tasks_for_results()
        manual_history = self._build_manual_simulated_history()
        collected = []
        try:
            request_record = self._prepare_request_record()
            eval_record = self._prepare_eval_record(request_record, snapshot_values)
            simulated_history = copy.deepcopy(manual_history)
            for sequence, meta_task in enumerate(meta_tasks, start=1):
                if self._is_notification_meta_task(meta_task):
                    notification = self._notification_dryrun_result(
                        request_record,
                        eval_record,
                        meta_task,
                        simulated_history,
                    )
                    resolution = {
                        "candidate_user_ids": [],
                        "eligible_user_ids": [],
                        "final_user_ids": [],
                        "delegation_map": [],
                        "fallback_policy": meta_task.fallback_policy or "block",
                        "blocked": False,
                        "warnings": notification.get("warnings") or [],
                        "debug": {"notification": notification},
                        "notification": notification,
                    }
                else:
                    resolution = service.resolve_assignees(
                        request_record=request_record,
                        meta_task=meta_task,
                        task_node_id=meta_task.node_id,
                        eval_record=eval_record,
                        snapshot_values=snapshot_values,
                        simulated_history=simulated_history,
                        debug=True,
                        actor_user=self.simulated_user_id,
                    )
                collected.append(
                    {
                        "sequence": sequence,
                        "meta_task": meta_task,
                        "resolution": resolution,
                    }
                )
                if not self._is_notification_meta_task(meta_task):
                    simulated_history = self._append_derived_stage_history(
                        simulated_history,
                        meta_task,
                        resolution,
                    )
        except Exception:
            _logger.exception(
                "Dry run failed for category '%s' version '%s' user '%s'",
                self.category_id.name,
                self.version_id.name,
                self.simulated_user_id.login,
            )
            raise
        return collected

    def action_run_dryrun(self):
        self.ensure_one()
        self._ensure_wizard_ready()
        snapshot = self._snapshot_values_from_inputs()
        collected = self._run_assignment_dryrun(snapshot)
        self._create_result_lines(collected)
        return self._reopen_action()

    def action_run_dryrun_from_snapshot(self, snapshot_values):
        self.ensure_one()
        self._ensure_wizard_ready()
        self.write({"snapshot_json": snapshot_values if isinstance(snapshot_values, dict) else {}})
        collected = self._run_assignment_dryrun(self.snapshot_json)
        self._create_result_lines(collected)
        return self._reopen_action()


class WorkflowDryRunNodeInput(models.TransientModel):
    _name = "workflow.dryrun.node.input"
    _description = "Workflow Dry Run Node Input"
    _order = "id asc"

    wizard_id = fields.Many2one(
        "workflow.dryrun.wizard",
        required=True,
        ondelete="cascade",
        default=lambda self: _dryrun_wizard_id_from_context(self.env),
    )
    node_id = fields.Char(string="Node ID", readonly=True)
    node_name = fields.Char(string="Node", readonly=True)
    node_type = fields.Char(string="Node Type", readonly=True)
    assigned_user_ids = fields.Many2many(
        "res.users",
        "wf_dryrun_node_input_assign_rel",
        "line_id",
        "user_id",
        string="Stage Assigned Users",
        domain="[('share', '=', False), ('active', '=', True)]",
    )
    decided_user_ids = fields.Many2many(
        "res.users",
        "wf_dryrun_node_input_decide_rel",
        "line_id",
        "user_id",
        string="Stage Decided Users",
        domain="[('share', '=', False), ('active', '=', True)]",
    )

    @api.model_create_multi
    def create(self, vals_list):
        wizard_id = _dryrun_wizard_id_from_context(self.env)
        prepared = []
        for vals in vals_list:
            current = dict(vals)
            if wizard_id and not current.get("wizard_id"):
                current["wizard_id"] = wizard_id
            prepared.append(current)
        return super().create(prepared)


class WorkflowDryRunFieldInput(models.TransientModel):
    _name = "workflow.dryrun.field.input"
    _description = "Workflow Dry Run Form Value"
    _order = "id asc"

    wizard_id = fields.Many2one(
        "workflow.dryrun.wizard",
        required=True,
        ondelete="cascade",
        default=lambda self: _dryrun_wizard_id_from_context(self.env),
    )
    target_model_name = fields.Char(
        related="wizard_id.target_model_name",
        readonly=True,
    )
    field_id = fields.Many2one(
        "ir.model.fields",
        string="Form Field",
        required=True,
        domain=(
            "[('model', '=', target_model_name), "
            "('ttype', 'not in', ['binary', 'one2many', 'many2many']), "
            "('name', 'not in', ['id', 'display_name', 'create_uid', 'create_date', 'write_uid', 'write_date'])]"
        ),
        ondelete="cascade",
    )
    field_name = fields.Char(related="field_id.name", string="Technical Name", readonly=True)
    field_label = fields.Char(related="field_id.field_description", string="Field", readonly=True)
    field_type = fields.Selection(related="field_id.ttype", string="Type", readonly=True)
    relation = fields.Char(related="field_id.relation", string="Relation", readonly=True)
    value_char = fields.Char(string="Text / Selection Value")
    value_text = fields.Text(string="Long Text Value")
    value_integer = fields.Integer(string="Integer / Record ID")
    value_float = fields.Float(string="Decimal Value")
    value_boolean = fields.Boolean(string="Boolean Value")
    value_date = fields.Date(string="Date Value")
    value_datetime = fields.Datetime(string="Datetime Value")
    value_user_id = fields.Many2one(
        "res.users",
        string="User Value",
        domain="[('share', '=', False), ('active', '=', True)]",
    )
    value_employee_id = fields.Many2one(
        "hr.employee",
        string="Employee Value",
    )
    value_partner_id = fields.Many2one(
        "res.partner",
        string="Partner Value",
    )
    value_display = fields.Char(
        string="Value",
        compute="_compute_value_display",
    )

    @api.model_create_multi
    def create(self, vals_list):
        wizard_id = _dryrun_wizard_id_from_context(self.env)
        prepared = []
        for vals in vals_list:
            current = dict(vals)
            if wizard_id and not current.get("wizard_id"):
                current["wizard_id"] = wizard_id
            prepared.append(current)
        return super().create(prepared)

    @api.depends(
        "field_type",
        "relation",
        "value_char",
        "value_text",
        "value_integer",
        "value_float",
        "value_boolean",
        "value_date",
        "value_datetime",
        "value_user_id",
        "value_employee_id",
        "value_partner_id",
    )
    def _compute_value_display(self):
        for line in self:
            value = line._snapshot_value()
            if isinstance(value, dict):
                line.value_display = value.get("display_name") or str(value.get("id") or "")
            elif value is None:
                line.value_display = ""
            else:
                line.value_display = str(value)

    @api.onchange("field_id")
    def _onchange_field_id(self):
        for line in self:
            line.value_char = False
            line.value_text = False
            line.value_integer = 0
            line.value_float = 0.0
            line.value_boolean = False
            line.value_date = False
            line.value_datetime = False
            line.value_user_id = False
            line.value_employee_id = False
            line.value_partner_id = False

    def _m2o_snapshot_value(self):
        self.ensure_one()
        if self.relation == "res.users" and self.value_user_id:
            return {"id": self.value_user_id.id, "display_name": self.value_user_id.display_name}
        if self.relation == "hr.employee" and self.value_employee_id:
            return {"id": self.value_employee_id.id, "display_name": self.value_employee_id.display_name}
        if self.relation == "res.partner" and self.value_partner_id:
            return {"id": self.value_partner_id.id, "display_name": self.value_partner_id.display_name}
        if self.value_integer:
            return {"id": self.value_integer, "display_name": str(self.value_integer)}
        return None

    def _snapshot_value(self):
        self.ensure_one()
        if not self.field_id:
            return None
        if self.field_type == "many2one":
            return self._m2o_snapshot_value()
        if self.field_type in ("char", "selection"):
            return self.value_char or None
        if self.field_type in ("text", "html"):
            return self.value_text or None
        if self.field_type == "boolean":
            return bool(self.value_boolean)
        if self.field_type == "integer":
            return self.value_integer
        if self.field_type in ("float", "monetary"):
            return self.value_float
        if self.field_type == "date":
            return fields.Date.to_string(self.value_date) if self.value_date else None
        if self.field_type == "datetime":
            return fields.Datetime.to_string(self.value_datetime) if self.value_datetime else None
        return self.value_char or self.value_text or None


class WorkflowDryRunResultLine(models.TransientModel):
    _name = "workflow.dryrun.result.line"
    _description = "Workflow Dry Run Result Line"
    _order = "sequence asc"

    wizard_id = fields.Many2one(
        "workflow.dryrun.wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="#", default=10)
    node_name = fields.Char(string="Node", readonly=True)
    node_id = fields.Char(string="Node ID", readonly=True)
    node_type = fields.Char(string="Type", readonly=True)
    assignment_mode = fields.Char(string="Mode Key", readonly=True)
    assignment_mode_label = fields.Char(string="Assignment Mode", readonly=True)
    fallback_policy = fields.Char(string="Fallback Policy Key", readonly=True)
    fallback_policy_label = fields.Char(string="Fallback Policy", readonly=True)
    assignee_user_ids = fields.Many2many(
        "res.users",
        "wf_dryrun_result_user_rel",
        "line_id",
        "user_id",
        string="Resolved Assignees",
        readonly=True,
    )
    assignee_count = fields.Integer(
        string="Count",
        compute="_compute_counts",
    )
    notification_recipient_user_ids = fields.Many2many(
        "res.users",
        "wf_dryrun_notification_user_rel",
        "line_id",
        "user_id",
        string="Notification Recipients",
        readonly=True,
    )
    notification_recipient_count = fields.Integer(
        string="Notification Count",
        compute="_compute_counts",
    )
    notification_delivery_mode = fields.Char(string="Notification Delivery", readonly=True)
    notification_email_to = fields.Text(string="Email To", readonly=True)
    notification_email_cc = fields.Text(string="Email CC", readonly=True)
    notification_email_bcc = fields.Text(string="Email BCC", readonly=True)
    notification_has_result = fields.Boolean(
        string="Has Notification Result",
        compute="_compute_counts",
    )
    candidate_count = fields.Integer(
        string="Candidates",
        readonly=True,
    )
    eligible_count = fields.Integer(
        string="Eligible",
        readonly=True,
    )
    is_blocked = fields.Boolean(string="Blocked", readonly=True)
    status = fields.Selection(
        [
            ("ok", "OK"),
            ("warning", "Warning"),
            ("needs_input", "Needs Input"),
            ("config_error", "Config Error"),
            ("fallback", "Fallback"),
            ("blocked", "Blocked"),
            ("system", "System Node"),
        ],
        string="Status",
        readonly=True,
    )
    status_label = fields.Char(string="Status Text", readonly=True)
    diagnosis = fields.Char(string="Diagnosis", readonly=True)
    warnings = fields.Text(string="Warnings", readonly=True)
    delegation_info = fields.Text(string="Delegation", readonly=True)
    debug_json = fields.Json(string="Debug Payload", readonly=True)
    notification_debug_json = fields.Json(string="Notification Debug", readonly=True)

    @api.depends(
        "assignee_user_ids",
        "notification_recipient_user_ids",
        "notification_email_to",
        "notification_email_cc",
        "notification_email_bcc",
        "notification_debug_json",
    )
    def _compute_counts(self):
        for line in self:
            line.assignee_count = len(line.assignee_user_ids)
            line.notification_recipient_count = len(line.notification_recipient_user_ids)
            line.notification_has_result = bool(
                line.notification_recipient_user_ids
                or line.notification_email_to
                or line.notification_email_cc
                or line.notification_email_bcc
                or line.notification_debug_json
            )
