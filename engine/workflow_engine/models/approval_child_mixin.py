import json
import logging
import requests
import datetime
import re
from uuid import uuid4
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from lxml import html
from lxml.builder import E
from odoo.addons.html_editor.tools import handle_history_divergence
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE, ACTION_TYPE
from odoo.tools import html_escape
from odoo.tools.mail import email_normalize
from odoo.tools.safe_eval import safe_eval
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class ApprovalChildMixin(models.AbstractModel):
    """
    This is approval mixin which will add child functionality to an approval base request.
    """
    _name = 'approval.child.mixin'
    _description = 'Approval Child Mixin'

    _inherit = ['approval.base.mixin']

    # ------------------------------------------------------------------
    # Activity tray filter injection
    # activity_menu.js sends search_default_activities_overdue / today /
    # upcoming_all as context keys when the user clicks a count in the
    # notification bell. Those keys activate search filters by name.
    # Auto-generated Studio search views for x_* models have none of
    # those names, so the filter is silently ignored and all records show.
    # We inject the 4 invisible filters at _get_view time so they are
    # present regardless of which view Odoo's default_view() picks.
    # This works for every model that inherits approval.child.mixin.
    # ------------------------------------------------------------------
    _ACTIVITY_FILTERS = [
        ('activities_overdue',      'Late Activities',
         "['&', ('activity_user_id', '=', uid), ('my_activity_date_deadline', '<', 'today')]"),
        ('activities_today',        'Today Activities',
         "['&', ('activity_user_id', '=', uid), ('my_activity_date_deadline', '=', 'today')]"),
        ('activities_upcoming_all', 'Future Activities',
         "['&', ('activity_user_id', '=', uid), ('my_activity_date_deadline', '>', 'today')]"),
    ]

    @api.model
    def _workflow_default_search_field_specs(self):
        return [
            ("name", {}),
            ("category_id", {"string": _("Workflow")}),
            ("request_owner_id", {"string": _("Request Owner")}),
            ("request_owner_department", {"string": _("Request Owner Department")}),
            ("current_activity_name", {"string": _("Activity")}),
            ("state", {"string": _("Status")}),
            ("request_status", {"string": _("Request Status")}),
            ("manager_user_id", {"string": _("Manager")}),
        ]

    @api.model
    def _workflow_default_search_filter_specs(self):
        return [
            {
                "name": "filter_my_request_owner",
                "string": _("My Request List"),
                "domain": "[('is_my_owned_request', '=', True)]",
                "required_fields": ("is_my_owned_request",),
            },
            {
                "name": "filter_my_work_list",
                "string": _("My Work List"),
                "domain": "[('is_my_work_item', '=', True)]",
                "required_fields": ("is_my_work_item",),
            },
            {
                "name": "filter_my_contribute_list",
                "string": _("My Contribute List"),
                "domain": "[('is_my_contribution', '=', True)]",
                "required_fields": ("is_my_contribution",),
            },
            {
                "name": "filter_shared_with_me",
                "string": _("Shared With Me"),
                "domain": "[('is_shared_with_me', '=', True)]",
                "required_fields": ("is_shared_with_me",),
            },
            {
                "name": "filter_create_date",
                "string": _("Request Date"),
                "date": "create_date",
                "required_fields": ("create_date",),
            },
            {
                "name": "filter_submit_date",
                "string": _("Submitted Date"),
                "date": "submit_date",
                "required_fields": ("submit_date",),
            },
            {
                "name": "filter_to_submit",
                "string": _("To Submit"),
                "domain": "[('state', '=', 'new')]",
                "required_fields": ("state",),
            },
            {
                "name": "filter_waiting",
                "string": _("Waiting Approval"),
                "domain": "[('state', '=', 'waiting')]",
                "required_fields": ("state",),
            },
            {
                "name": "filter_done",
                "string": _("Done"),
                "domain": "[('state', 'in', ['done', 'completed', 'auto_approved'])]",
                "required_fields": ("state",),
            },
            {
                "name": "filter_cancelled",
                "string": _("Cancelled"),
                "domain": "[('request_status', 'in', ['cancelled', 'auto_cancelled'])]",
                "required_fields": ("request_status",),
            },
        ]

    @api.model
    def _workflow_default_search_group_specs(self):
        return [
            ("groupby_category_id", _("Workflow"), "category_id"),
            ("groupby_request_owner", _("Request Owner"), "request_owner_id"),
            ("groupby_request_owner_department", _("Department"), "request_owner_department"),
            ("groupby_state", _("Status"), "state"),
            ("groupby_current_activity", _("Activity"), "current_activity_name"),
            ("groupby_manager", _("Manager"), "manager_user_id"),
            ("groupby_create_date", _("Request Date"), "create_date:month"),
            ("groupby_submit_date", _("Submitted Date"), "submit_date:month"),
        ]

    @api.model
    def _workflow_search_fields_exist(self, field_names):
        return all(field_name in self._fields for field_name in field_names)

    @api.model
    def _workflow_inject_default_search_view(self, arch):
        existing_fields = {node.get("name") for node in arch.xpath(".//field[@name]")}
        existing_filters = {node.get("name") for node in arch.xpath(".//filter[@name]")}

        for field_name, attrs in self._workflow_default_search_field_specs():
            if field_name not in self._fields or field_name in existing_fields:
                continue
            arch.append(E.field(name=field_name, **attrs))
            existing_fields.add(field_name)

        for spec in self._workflow_default_search_filter_specs():
            name = spec["name"]
            if name in existing_filters:
                continue
            if not self._workflow_search_fields_exist(spec.get("required_fields", ())):
                continue
            attrs = {
                "name": name,
                "string": spec["string"],
            }
            if spec.get("domain"):
                attrs["domain"] = spec["domain"]
            if spec.get("date"):
                attrs["date"] = spec["date"]
            arch.append(E.filter(**attrs))
            existing_filters.add(name)

        group = arch.find("group")
        if group is None:
            group = E.group()
            arch.append(group)

        for name, string, group_by in self._workflow_default_search_group_specs():
            field_name = group_by.split(":", 1)[0]
            if name in existing_filters or field_name not in self._fields:
                continue
            group.append(E.filter(
                name=name,
                string=string,
                context=repr({"group_by": group_by}),
            ))
            existing_filters.add(name)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        # Guard: if a search view record in the DB has arch=False (corrupt),
        # Odoo's _combine raises TypeError: memoryview: bytes-like required, not bool.
        # Detect and repair before calling super so the UI never crashes.
        if view_type == 'search' and view_id:
            v = self.env['ir.ui.view'].sudo().browse(view_id)
            if v.exists() and not v.arch:
                v.write({'arch': '<search/>'})
        arch, view = super()._get_view(view_id=view_id, view_type=view_type, **options)
        if view_type == 'search':
            if not view:
                self._workflow_inject_default_search_view(arch)
            existing = {f.get('name') for f in arch.findall('.//filter')}
            if 'activities_overdue' not in existing:
                for name, string, domain in self._ACTIVITY_FILTERS:
                    arch.append(E.filter(invisible="1", string=string,
                                         name=name, domain=domain))
        elif view_type == 'list' and self.env.context.get("workflow_history_mode"):
            arch.set("create", "false")
            arch.set("edit", "false")
            arch.set("delete", "false")
            arch.set("duplicate", "false")
            if not arch.get("action"):
                arch.set("action", "action_open_workflow_history_detail")
            if not arch.get("type"):
                arch.set("type", "object")
        elif view_type == 'form' and self.env.context.get("workflow_history_mode"):
            arch.set("edit", "false")
            arch.set("create", "false")
            arch.set("delete", "false")
            arch.set("duplicate", "false")
            for button in arch.xpath(".//button"):
                button.set("invisible", "1")
            for widget in arch.xpath(".//widget"):
                if widget.get("name") in {
                    "approval_buttons",
                    "delegate_button",
                    "attach_document",
                    "bpmn_button",
                }:
                    widget.set("invisible", "1")
            for button_box in arch.xpath(".//div[@name='button_box']"):
                button_box.set("invisible", "1")
        return arch, view

    @api.model
    def _search(
        self,
        domain,
        offset=0,
        limit=None,
        order=None,
        *,
        active_test=True,
        bypass_access=False,
    ):
        effective_domain = fields.Domain(domain)
        if self.env.context.get("workflow_history_mode"):
            allowed_ids = self._workflow_history_effective_allowed_record_ids()
            effective_domain &= fields.Domain("id", "in", allowed_ids or [0])
            return super(ApprovalChildMixin, self.sudo())._search(
                effective_domain,
                offset=offset,
                limit=limit,
                order=order,
                active_test=active_test,
                bypass_access=bypass_access,
            )
        return super()._search(
            effective_domain,
            offset=offset,
            limit=limit,
            order=order,
            active_test=active_test,
            bypass_access=bypass_access,
        )

    # this field is already defined in ir_model.py but we redefine it here to add string label
    x_approval_base_id = fields.Many2one(
        "workflow.base.approval.request",
        required=True,
        ondelete="cascade",
        string="Approval Base",
        index=True,
    )
    x_reject_reason = fields.Text(string="Rejection Reason")
    x_approve_reason = fields.Text(string="Approval Reason")
    x_current_stage = fields.Char(related="x_approval_base_id.current_activity_name", string="Current Stage", store=True)
    x_current_state = fields.Selection(related="x_approval_base_id.state", string="Current State", store=True)
    wf_history_enabled = fields.Boolean(
        string="WF History Enabled",
        related="x_approval_base_id.category_id.enable_request_history",
        readonly=True,
    )
    wf_history_count = fields.Integer(
        string="WF History Count",
        compute="_compute_workflow_history_state",
        readonly=True,
    )
    # x_rework_reason = fields.Text(string="Rework Reason")
   
    child_updated_date = fields.Datetime(string="Last Update On Child", store=True)

    def _compute_workflow_history_state(self):
        for record in self:
            base_request = record.sudo()._workflow_resolve_request_record()
            if (
                not base_request
                or not base_request.category_id.enable_request_history
                or not record.env.user.has_group("workflow_engine.group_workflow_view_history_user")
            ):
                record.wf_history_count = 0
                continue

            allowed_ids = record.with_context(
                workflow_history_mode=True,
                workflow_history_source_base_id=base_request.id,
            )._workflow_history_allowed_record_ids(source_request=base_request)
            record.wf_history_count = len(allowed_ids)

    def unlink(self):
        """
        Keep workflow base and child records consistent:
        when child form records are deleted, remove detached base requests
        for the same model to avoid orphan requests in reporting/list screens.
        """
        self._workflow_cleanup_force_transition_wizards_for_unlink()
        if self and self._workflow_should_archive_on_unlink():
            self._workflow_archive_on_unlink()
            return True
        base_requests = self.sudo().mapped("x_approval_base_id")
        res = super().unlink()
        if not base_requests:
            return res

        orphan_ids = []
        current_model = self.sudo().with_context(active_test=False)
        for base in base_requests.sudo():
            if not base.exists():
                continue
            if base.res_model_name != self._name:
                continue
            still_linked = current_model.search([("x_approval_base_id", "=", base.id)], limit=1)
            if not still_linked:
                orphan_ids.append(base.id)

        if orphan_ids:
            self.env["workflow.base.approval.request"].sudo().with_context(
                wf_include_archived_categories=True
            ).browse(orphan_ids).unlink()
        return res

    def _is_submission_meta_task(self, meta_task):
        """Return True when the meta task is the workflow submission task."""
        self.ensure_one()
        meta_task = meta_task[:1]
        if not meta_task:
            return False

        node_id = meta_task.node_id
        if not node_id:
            return False

        # Prefer BPMN-mapped submission node detection.
        try:
            engine = BpmnEngine(self.version_id.bpmn_xml)
            submission_node = engine.get_submission_task()
            if submission_node is not None and node_id == submission_node.attrib.get('id'):
                return True
        except Exception:
            _logger.debug("Failed to resolve submission task by BPMN for %s", self.id, exc_info=True)

        # Fallback for older BPMN naming.
        name = (meta_task.name or "").lower()
        return "submit" in name or "submission" in name

    @staticmethod
    def _workflow_normalize_folio_name(value):
        return (value or "").strip().lower()

    def _workflow_name_uses_draft_placeholder(self, value):
        normalized = self._workflow_normalize_folio_name(value)
        if not normalized:
            return True
        placeholders = {"new"}
        translated_new = self._workflow_normalize_folio_name(_("New"))
        if translated_new:
            placeholders.add(translated_new)
        return normalized in placeholders

    def _workflow_has_prior_submission_history(self, submission_node_id):
        self.ensure_one()
        if not submission_node_id:
            return False
        base_request = self._resolve_base_request_record()
        approver_rows = getattr(base_request, "approver_ids", []) or []
        for row in approver_rows:
            if getattr(row, "current_meta_node_id", False) != submission_node_id:
                continue
            if (getattr(row, "user_decision", "") or "").strip():
                return True
        return False

    def _workflow_assign_submission_folio_if_needed(self, source_meta_task=False):
        self.ensure_one()
        if self.env.context.get("automated_sequence") is False:
            return False
        if not source_meta_task or not self._is_submission_meta_task(source_meta_task):
            return False

        category = getattr(self, "category_id", False)
        if not category or not getattr(category, "automated_sequence", False):
            return False
        if not self._workflow_name_uses_draft_placeholder(getattr(self, "name", False)):
            return False

        submission_node_id = getattr(source_meta_task, "node_id", False)
        if self._workflow_has_prior_submission_history(submission_node_id):
            return False

        sequence = getattr(category, "sequence_id", False)
        if not sequence:
            category_label = (
                getattr(category, "display_name", False)
                or getattr(category, "name", False)
                or _("Unknown Category")
            )
            raise UserError(
                _(
                    "Automated sequence is enabled for category '%(category)s', "
                    "but no reference sequence is configured."
                ) % {"category": category_label}
            )

        sequence_record = sequence.sudo() if hasattr(sequence, "sudo") else sequence
        folio = sequence_record.next_by_id()
        if not folio:
            raise UserError(_("Could not generate a request folio from the configured sequence."))

        folio_record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(folio_record, "with_context"):
            folio_record = folio_record.with_context(
                workflow_skip_edit_scope=True,
                workflow_skip_field_policy=True,
            )
        if hasattr(folio_record, "write"):
            folio_record.write({"name": folio})
        else:
            self.name = folio
        if hasattr(self, "invalidate_recordset"):
            self.invalidate_recordset(["name"])
        return folio

    def _subscribe_request_owner_if_needed(self):
        """Ensure request owner follows the request when creator differs."""
        self.ensure_one()
        if not self.request_owner_id or self.request_owner_id == self.create_uid:
            return

        partner_ids = self.request_owner_id.partner_id.ids
        if not partner_ids:
            return

        # Subscribe on current record if mail.thread is available.
        self._workflow_safe_message_subscribe(partner_ids)

        # Always subscribe on base request (mail.thread) as the source of truth.
        base_request = self._resolve_base_request_record()
        if base_request:
            base_request._workflow_safe_message_subscribe(partner_ids)

    def _get_submission_assignee(self, previous_meta_task, submission_node_id):
        """
        Resolve who should own the next submission stage.
        - First cycle (from Start): current actor (creator flow).
        - Rework/back-to-submit: last user who previously submitted on this node.
        - Fallback: request_owner -> owner_user -> create_uid -> env.user.
        """
        self.ensure_one()

        prev_type = (previous_meta_task.node_type or "") if previous_meta_task else ""
        if prev_type in [NODE_TYPE['START_EVENT'], NODE_TYPE['START_EVENT_WITH_MESSAGE']]:
            forced_creator = self._workflow_resolve_force_created_user()
            return forced_creator or self.env.user or self.create_uid or self.request_owner_id

        submitter = self._get_latest_submission_actor_from_history(submission_node_id)
        if submitter:
            return submitter

        return self.request_owner_id or self.owner_user_id or self.create_uid or self.env.user

    def _should_reset_request_to_submit_on_entry(self, engine, current_node=None, next_node=None):
        """Return True when entering the target stage should reopen the request as To Submit."""
        self.ensure_one()
        if next_node is None or engine.is_end_event(next_node):
            return False
        if current_node is not None and engine.is_start_event(current_node):
            return True

        target_meta_task = self._resolve_meta_task_for_node(
            next_node.attrib.get("id"),
            next_node.attrib.get("name"),
        )
        if not target_meta_task:
            return False
        if self._is_submission_meta_task(target_meta_task):
            return True
        return bool(getattr(target_meta_task, "reset_request_to_submit", False))

    def _resolve_base_request_record(self):
        self.ensure_one()
        if self._name == "workflow.base.approval.request":
            return self
        try:
            return self.x_approval_base_id
        except AccessError:
            # Some approvers can execute workflow transitions but cannot read
            # the child model directly due business record rules.
            sudo_base = self.sudo().x_approval_base_id
            if not sudo_base:
                return self.env["workflow.base.approval.request"]
            return self.env["workflow.base.approval.request"].browse(sudo_base.id)

    def action_open_child(self):
        self.ensure_one()
        target = self.env.context.get("wf_open_target") or "current"
        child_label = getattr(self, "display_name", False) or getattr(self, "name", False) or _("Request")
        base_request = self.sudo()._workflow_resolve_request_record()
        base_label = getattr(base_request, "display_name", False) or getattr(base_request, "name", False) or False
        action_label = child_label
        if base_label and base_label != child_label:
            action_label = f"{base_label} / {child_label}"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "views": [[False, "form"]],
            "target": target,
            "name": f"Form: {action_label}",
        }

    def _get_max_iteration_no(self):
        self.ensure_one()
        values = [v for v in self.approver_ids.mapped("iteration_no") if v]
        return max(values) if values else 0

    def _is_iteration_revisit_loop_action(self, meta_action=False, previous_meta_task=False):
        """Return True for decisions that represent a loopback/resubmit intent."""
        action_label = ((meta_action.name if meta_action else "") or "").strip().lower()
        source_stage_label = ((previous_meta_task.name if previous_meta_task else "") or "").strip().lower()
        loop_keywords = ("rework", "resubmit", "submit", "return", "back")
        return any(
            keyword in action_label or keyword in source_stage_label
            for keyword in loop_keywords
        )

    def _has_stage_history_in_iteration(self, target_node_id, iteration_no):
        """Check whether target stage already has terminal history in the given iteration."""
        if not target_node_id:
            return False
        iteration_no = iteration_no or 1
        terminal_statuses = {"approved", "refused", "cancelled", "closed"}
        for row in self.approver_ids:
            row_iteration = getattr(row, "iteration_no", 0) or 1
            if row_iteration != iteration_no:
                continue
            if getattr(row, "current_meta_node_id", False) != target_node_id:
                continue
            if str(getattr(row, "status", "") or "").lower() in terminal_statuses:
                return True
        return False

    def _resolve_iteration_for_next_stage(
            self,
            is_submission_stage=False,
            previous_meta_task=False,
            current_meta_task=False,
            meta_action=False,
    ):
        """
        Resolve iteration number for newly assigned approvers.
        - Submission stage always starts a new iteration.
        - Revisit loopbacks (rework/resubmit) to already-completed stages open a new iteration.
        - Other stages reuse the request's current iteration.
        """
        self.ensure_one()
        base_request = self._resolve_base_request_record()
        max_iteration = self._get_max_iteration_no()
        current_iteration = (base_request.current_iteration_no or 0) if base_request else 0

        if is_submission_stage:
            start_types = {
                NODE_TYPE["START_EVENT"],
                NODE_TYPE["START_EVENT_WITH_MESSAGE"],
                NODE_TYPE["START_EVENT_WITH_TIMER"],
                NODE_TYPE["START_EVENT_WITH_SIGNAL"],
                NODE_TYPE["START_EVENT_WITH_CONDITIONAL"],
            }
            previous_type = (previous_meta_task.node_type or "") if previous_meta_task else ""
            is_first_cycle_submission = (
                previous_type in start_types
                and max_iteration <= 1
                and current_iteration <= 1
            )
            if is_first_cycle_submission:
                next_iteration = 1
            else:
                next_iteration = max(max_iteration, current_iteration, 1) + 1
            if base_request and base_request.current_iteration_no != next_iteration:
                base_request.sudo().write({"current_iteration_no": next_iteration})
            return next_iteration

        resolved_iteration = current_iteration or max_iteration or 1
        if (
            current_meta_task
            and self._is_iteration_revisit_loop_action(
                meta_action=meta_action,
                previous_meta_task=previous_meta_task,
            )
            and self._has_stage_history_in_iteration(current_meta_task.node_id, resolved_iteration)
        ):
            next_iteration = max(max_iteration, current_iteration, resolved_iteration, 1) + 1
            if base_request and base_request.current_iteration_no != next_iteration:
                base_request.sudo().write({"current_iteration_no": next_iteration})
            return next_iteration

        if base_request and not base_request.current_iteration_no:
            base_request.sudo().write({"current_iteration_no": resolved_iteration})
        return resolved_iteration

    def _resolve_iteration_for_action(self, source_node_id=None):
        """
        Resolve iteration number for decision rows/updates.
        Prefer active rows on source node, fallback to request current iteration.
        """
        self.ensure_one()
        base_request = self._resolve_base_request_record()
        current_iteration = (base_request.current_iteration_no or 0) if base_request else 0

        if source_node_id:
            active_rows = self.approver_ids.filtered(
                lambda a: a.current_meta_node_id == source_node_id and a.status in ["new", "pending", "waiting"]
            )
            active_values = [v for v in active_rows.mapped("iteration_no") if v]
            if active_values:
                return max(active_values)

        if current_iteration:
            return current_iteration

        return self._get_max_iteration_no() or 1

    def _close_open_source_stage_approvers(self, source_node):
        """
        Close sibling open approver rows on the source stage once a transition leaves that stage.
        """
        self.ensure_one()
        if source_node is None:
            return
        source_node_id = source_node.attrib.get("id")
        source_meta_task = self._resolve_meta_task_for_node(
            source_node_id,
            source_node.attrib.get("name"),
        )
        # ODOO_ORM
        # if not source_meta_task:
        if not source_meta_task.exists():
            return
        active_iteration_no = self._resolve_iteration_for_action(source_node_id)
        self.close_approver(source_meta_task, iteration_no=active_iteration_no)
        base_request = self._resolve_base_request_record()
        self.env["workflow.engine.assignment.service"]._close_business_action_assignments(
            base_request,
            node_id=source_node_id,
            iteration_no=active_iteration_no,
            reason=_("Closed when the workflow left the source stage."),
        )

    def _resolve_meta_task_for_node(self, node_id, node_name=None, prefer_submission=None):
        """
        Resolve a single canonical meta task for a BPMN node.

        Why:
        - some environments contain duplicate meta rows for the same node_id
          (for example legacy name 'Task' and newer name 'Submission')
        - selecting with plain search(..., limit=1) can pick the wrong row

        Strategy:
        1) filter by node_id in current version
        2) if node_name is provided, prefer exact name match
        3) optionally prefer submission/non-submission task
        4) fallback to newest row (highest id)
        """
        self.ensure_one()
        MetaTask = self.env['workflow.category.version.meta.task']
        if not self.version_id or not node_id:
            return MetaTask.browse()

        candidates = self.version_id.meta_task_ids.filtered(lambda m: m.node_id == node_id)
        if not candidates:
            return MetaTask.browse()

        generic_names = {"", "task", "usertask", "activity"}
        if node_name:
            wanted = (node_name or "").strip().lower()
            # Generic technical labels are ambiguous, do not force exact match.
            if wanted in generic_names:
                wanted = ""
            name_matches = candidates.filtered(lambda m: (m.name or "").strip().lower() == wanted)
            if name_matches:
                candidates = name_matches

        # Auto-canonicalize duplicate submission nodes when action metadata carries
        # a generic technical name like "Task".
        if prefer_submission is None and len(candidates) > 1:
            wanted = (node_name or "").strip().lower()
            if wanted in generic_names:
                submission_candidates = candidates.filtered(lambda m: self._is_submission_meta_task(m))
                if submission_candidates:
                    candidates = submission_candidates

        if prefer_submission is True:
            submission_candidates = candidates.filtered(lambda m: self._is_submission_meta_task(m))
            if submission_candidates:
                candidates = submission_candidates
        elif prefer_submission is False:
            non_submission_candidates = candidates.filtered(lambda m: not self._is_submission_meta_task(m))
            if non_submission_candidates:
                candidates = non_submission_candidates

        return candidates.sorted(key=lambda m: m.id, reverse=True)[:1]

    def _update_tracking_fields(self, engine, form_data, current_node, next_node, meta_action=None):
        self.ensure_one()
        if next_node is None:
            raise UserError(_("No executable next node was resolved for this workflow transition."))
        # Suppress block-sync during tracking field updates.  The sync fires on
        # every write() and at this point approver rows for the new stage have not
        # been created yet, causing a spurious "no pending approver" block.
        # The sync runs normally in _assign_dynamic_approvers_from_meta once the
        # rows exist, which is where the correct blocked/unblocked state is set.
        tracking_record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(tracking_record, "with_context"):
            tracking_record = tracking_record.with_context(
                wf_skip_block_sync=True,
                workflow_skip_edit_scope=True,
                workflow_skip_field_policy=True,
            )
        vals = {
            "previous_node_id": tracking_record.current_node_id,
            "previous_activity_name": tracking_record.current_activity_name,
            "current_node_id": next_node.attrib['id'],
            "current_activity_name": next_node.attrib.get('name'),
        }

        # check if the next node is already end node
        if engine.is_end_event(next_node):
            state_value, request_status = self._resolve_terminal_status(next_node)
            vals.update({
                "state": state_value,
                "request_status": request_status,
            })
        else:
            next_nodes = engine.get_next_elements(next_node, form_data=form_data)
            next_node_id = next_nodes[0].attrib['id'] if next_nodes else None
            next_activity_name = next_nodes[0].attrib.get('name') if next_nodes else None
            next_is_end_event = engine.is_end_event(next_nodes[0]) if next_nodes else False
            vals.update({
                "next_node_id": next_node_id,
                "next_activity_name": next_activity_name,
                "next_is_end_event": next_is_end_event,
            })
            if (
                not next_is_end_event
                and tracking_record._should_reset_request_to_submit_on_entry(
                    engine=engine,
                    current_node=current_node,
                    next_node=next_node,
                )
            ):
                vals.update({
                    "state": "new",
                    "request_status": "new",
                })
            elif next_is_end_event:
                state_value, request_status = self._resolve_terminal_status(next_nodes[0])
                vals.update({
                    "state": state_value,
                    "request_status": request_status,
                })
            else:
                vals.update({
                    "state": "waiting",
                    "request_status": "pending",
                })
        if hasattr(tracking_record, "write"):
            tracking_record.write(vals)
        else:
            for field_name, value in vals.items():
                setattr(self, field_name, value)
        if hasattr(self, "invalidate_recordset"):
            self.invalidate_recordset(list(vals))

    def _clear_active_branch_state(self):
        self.ensure_one()
        self.active_branch_node_ids = []
        self.branch_gateway_node_id = False
        self.branch_join_node_id = False
        self.branch_mode = False

    def _resolve_terminal_status(self, next_node):
        self.ensure_one()
        node_name = ((next_node.attrib.get("name") if next_node is not None else "") or "").strip().lower()
        if "auto cancel" in node_name:
            return "auto_cancelled", "auto_cancelled"
        if "cancel" in node_name:
            return "cancelled", "cancelled"
        if "refuse" in node_name or "reject" in node_name:
            return "refused", "refused"
        if "auto approve" in node_name:
            return "auto_approved", "approved"
        return "completed", "approved"

    def _workflow_is_runtime_v2(self):
        self.ensure_one()
        return bool(self.version_id and getattr(self.version_id, "execution_profile", "legacy") == "runtime_v2")

    def _workflow_find_runtime_automation_node(self, node_id=False, trigger_type=False):
        self.ensure_one()
        if not self.version_id or not node_id:
            return self.env["workflow.automation.node"]
        domain = [
            ("active", "=", True),
            ("version_id", "=", self.version_id.id),
            ("node_id", "=", node_id),
        ]
        if trigger_type:
            domain.append(("trigger_type", "=", trigger_type))
        return self.env["workflow.automation.node"].sudo().search(domain, order="id desc", limit=1)

    def _workflow_parse_iso_duration(self, expression):
        expression = ((expression or "") or "").strip().upper()
        if not expression or not expression.startswith("P"):
            return False
        match = re.fullmatch(
            r"P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
            expression,
        )
        if not match:
            return False
        parts = {key: int(value or 0) for key, value in match.groupdict().items()}
        if not any(parts.values()):
            return False
        return datetime.timedelta(
            weeks=parts["weeks"],
            days=parts["days"],
            hours=parts["hours"],
            minutes=parts["minutes"],
            seconds=parts["seconds"],
        )

    def _workflow_parse_duration_from_label(self, label):
        text = ((label or "") or "").strip().lower()
        if not text:
            return False
        total = datetime.timedelta()
        matched = False
        for amount_text, unit in re.findall(
                r"(\d+)\s*(week|weeks|day|days|hour|hours|hr|hrs|minute|minutes|min|mins)",
                text,
        ):
            matched = True
            amount = int(amount_text)
            if unit.startswith("week"):
                total += datetime.timedelta(weeks=amount)
            elif unit.startswith("day"):
                total += datetime.timedelta(days=amount)
            elif unit.startswith(("hour", "hr")):
                total += datetime.timedelta(hours=amount)
            else:
                total += datetime.timedelta(minutes=amount)
        return total if matched else False

    def _workflow_timer_due_at(self, timer_node, reference_dt=False, source_node_id=False):
        self.ensure_one()
        reference_dt = reference_dt or fields.Datetime.now()
        automation_node = self._workflow_find_runtime_automation_node(
            timer_node.attrib.get("id"),
            trigger_type="schedule",
        )
        if automation_node:
            return automation_node._compute_next_run_value(reference_dt)

        # Studio-configured timer: look for a meta action whose target is this timer node.
        timer_node_id = timer_node.attrib.get("id")
        if self.version_id and timer_node_id:
            meta_action = self._workflow_find_meta_action_for_transition(
                timer_node_id,
                source_node_id=source_node_id,
            )
            if meta_action:
                return meta_action._compute_automation_due_at(reference_dt=reference_dt)

        timer_definition = None
        for child in timer_node.iter():
            if getattr(child, "tag", "").endswith(NODE_TYPE["TIMER_EVENT_DEFINITION"]):
                timer_definition = child
                break
        if timer_definition is not None:
            for child in timer_definition:
                tag = getattr(child, "tag", "")
                raw_value = (child.text or "").strip()
                if not raw_value:
                    continue
                if tag.endswith("timeDuration"):
                    duration = self._workflow_parse_iso_duration(raw_value)
                    if duration:
                        return reference_dt + duration
                if tag.endswith("timeDate"):
                    parsed = fields.Datetime.to_datetime(raw_value)
                    if parsed:
                        return parsed
                if tag.endswith("timeCycle"):
                    parts = [part.strip() for part in raw_value.split("/") if part.strip()]
                    if parts:
                        duration = self._workflow_parse_iso_duration(parts[-1])
                        if duration:
                            return reference_dt + duration
                        parsed = fields.Datetime.to_datetime(parts[-1])
                        if parsed:
                            return parsed

        label_due = self._workflow_parse_duration_from_label(timer_node.attrib.get("name"))
        if label_due:
            return reference_dt + label_due
        raise UserError(
            _(
                "Timer node '%s' does not define a supported schedule. Configure an automation node or add a BPMN timer expression."
            )
            % (timer_node.attrib.get("name") or timer_node.attrib.get("id"))
        )

    def _workflow_post_activate_runtime_node(self, engine, next_node):
        self.ensure_one()
        if not self._workflow_is_runtime_v2() or next_node is None:
            return
        node_type = engine.get_element_type(next_node)
        if node_type not in [NODE_TYPE["USER_TASK"], NODE_TYPE["MANUAL_TASK"], NODE_TYPE["TASK"]]:
            return
        self._workflow_schedule_runtime_timers_for_user_task(engine, next_node)

    def _workflow_schedule_runtime_timers_for_user_task(self, engine, task_node):
        self.ensure_one()
        if not self._workflow_is_runtime_v2():
            return self.env["workflow.request.automation.instance"]
        base_request = self._resolve_base_request_record()
        iteration_no = base_request.current_iteration_no or 1
        current_meta_task = self._resolve_meta_task_for_node(
            task_node.attrib.get("id"),
            task_node.attrib.get("name"),
        )
        task_instance = self.env["workflow.request.task.instance"].sudo().search(
            [
                ("request_id", "=", base_request.id),
                ("node_id", "=", task_node.attrib.get("id")),
                ("iteration_no", "=", iteration_no),
                ("status", "in", ["new", "pending", "in_progress", "blocked", "rework"]),
            ],
            order="id desc",
            limit=1,
        )
        instances = self.env["workflow.request.automation.instance"]
        rearm_on_reentry = bool(self.env.context.get("force_transit"))
        for timer_candidate in engine.get_next_elements(task_node, form_data=self._get_form_data(),
                                                        evaluate_conditions=False):
            if engine.get_element_type(timer_candidate) != NODE_TYPE["TIMER_EVENT"]:
                continue
            source_node_id = task_node.attrib.get("id")
            meta_action = self._workflow_find_meta_action_for_transition(
                timer_candidate.attrib.get("id"),
                source_node_id=source_node_id,
            )
            due_at = self._workflow_timer_due_at(timer_candidate, source_node_id=source_node_id)
            automation_node = self._workflow_find_runtime_automation_node(
                timer_candidate.attrib.get("id"),
                trigger_type="schedule",
            )
            idempotency_key = self.env["workflow.request.automation.instance"].build_idempotency_key(
                request_id=base_request.id,
                node_id=timer_candidate.attrib.get("id"),
                iteration_no=iteration_no,
                branch_node_id=task_node.attrib.get("id"),
                trigger_type="timer",
                action_type="transition",
            )
            payload = {
                "execution_mode": "timer_transition",
                "source_node_id": task_node.attrib.get("id"),
                "source_node_name": task_node.attrib.get("name"),
                "meta_task_id": current_meta_task.id if current_meta_task else False,
            }
            instances |= self.env["workflow.request.automation.instance"].create_or_get(
                request_record=base_request,
                task_instance=task_instance,
                automation_node=automation_node,
                node_id=timer_candidate.attrib.get("id"),
                node_name=timer_candidate.attrib.get("name"),
                node_type=engine.get_element_type(timer_candidate),
                branch_node_id=task_node.attrib.get("id"),
                trigger_type="timer",
                action_type="transition",
                due_at=due_at,
                failure_policy=(automation_node.failure_policy if automation_node else "retry"),
                timeout_seconds=(automation_node.timeout_seconds if automation_node else 30),
                required=True,
                iteration_no=iteration_no,
                payload_json=payload,
                idempotency_key=idempotency_key,
                rearm_on_reentry=rearm_on_reentry,
                recurrence_enabled=bool(meta_action and meta_action._is_automation_recurring_enabled()),
                recurrence_mode=(meta_action.automation_recurrence_end_mode if meta_action else False) or "forever",
                recurrence_count=(meta_action.automation_recurrence_count if meta_action else 0) or 0,
                recurrence_until=(meta_action.automation_recurrence_until if meta_action else False) or False,
            )
        return instances

    def _workflow_cancel_runtime_instances(self, *, branch_node_id=False, node_id=False, reason=False,
                                           exclude_instance_ids=False):
        self.ensure_one()
        base_request = self._resolve_base_request_record()
        domain = [
            ("request_id", "=", base_request.id),
            ("status", "in", ["new", "scheduled", "running"]),
        ]
        if branch_node_id:
            domain.append(("branch_node_id", "=", branch_node_id))
        if node_id:
            domain.append(("node_id", "=", node_id))
        if exclude_instance_ids:
            domain.append(("id", "not in", list(exclude_instance_ids)))
        instances = self.env["workflow.request.automation.instance"].sudo().search(domain)
        if instances:
            instances.mark_cancelled(reason or _("Cancelled by workflow transition."))
        return instances

    def _workflow_close_runtime_branch(
        self,
        branch_node_id,
        reason=False,
        iteration_no=False,
        decision_if_blank=False,
        comment_if_blank=False,
    ):
        self.ensure_one()
        base_request = self._resolve_base_request_record()
        return self.env["workflow.engine.runtime.service"]._close_runtime_branch_state(
            base_request,
            branch_node_id,
            reason=reason,
            iteration_no=iteration_no,
            decision_if_blank=decision_if_blank,
            comment_if_blank=comment_if_blank,
        )

    def _workflow_schedule_retry_instance(self, automation_instance, error_message):
        self.ensure_one()
        retry_count = (automation_instance.retry_count or 0) + 1
        if automation_instance.max_retries and retry_count > automation_instance.max_retries:
            automation_instance.mark_failed(error_message, retry_count=retry_count)
            return
        automation_instance.schedule_retry(error_message)

    def _workflow_should_execute_meta_task(self, meta_task):
        self.ensure_one()
        condition_domain = (meta_task.automation_condition_domain or "").strip() if meta_task else ""
        if not meta_task or not condition_domain or condition_domain in ("[]", "[ ]"):
            return True
        return self.check_domain(condition_domain, default=False)

    def _workflow_active_node_ids_for_runtime_instance(self, base_request):
        active_nodes = set(base_request.active_branch_node_ids or [])
        if base_request.current_node_id:
            active_nodes.add(base_request.current_node_id)
        return active_nodes

    def _workflow_skip_or_rearm_runtime_instance(self, automation_instance, schedule_provider, reason, *, meta_task=False, meta_action=False):
        self.ensure_one()
        if not automation_instance.recurrence_enabled or not schedule_provider:
            automation_instance.mark_cancelled(reason)
            return False
        recurrence_plan = automation_instance._prepare_recurrence_after_success(
            meta_task=meta_task,
            meta_action=meta_action,
            execution_succeeded=False,
        )
        next_due_at = recurrence_plan.get("next_due_at")
        if not next_due_at:
            automation_instance.mark_cancelled(reason)
            automation_instance.sudo().write({"run_count": recurrence_plan.get("completed_runs") or automation_instance.run_count})
            return False
        automation_instance.mark_success(
            {
                "skipped": True,
                "reason": reason,
            },
            run_count=recurrence_plan.get("completed_runs"),
            next_due_at=next_due_at,
        )
        return True

    def _workflow_get_next_elements(self, engine, node, form_data=None, evaluate_conditions=True):
        self.ensure_one()
        if node is None:
            return []

        node_type = engine.get_element_type(node)
        if node_type != NODE_TYPE["CONDITIONAL_EVENT_DEFINITION"]:
            return engine.get_next_elements(node, form_data=form_data, evaluate_conditions=evaluate_conditions)

        if not evaluate_conditions:
            return engine.get_next_elements(node, form_data=form_data, evaluate_conditions=False)

        meta_task = self._resolve_meta_task_for_node(node.attrib.get("id"), node.attrib.get("name"))
        condition_domain = meta_task.automation_condition_domain if meta_task else False
        return self._workflow_get_conditional_event_next_elements(
            engine,
            node,
            condition_domain=condition_domain,
        )

    def _workflow_run_or_schedule_runtime_actions(self, engine, node, meta_task, current_previous, meta_action=False):
        self.ensure_one()
        if meta_task and not self._workflow_should_execute_meta_task(meta_task):
            return {"status": "skipped", "instance": False}

        automation_node = self._workflow_find_runtime_automation_node(node.attrib.get("id"))
        node_type = engine.get_element_type(node)
        action_type = (
            "send_email"
            if node_type == NODE_TYPE["SEND_TASK"] or self._workflow_is_message_notification_node_type(node_type)
            else "enqueue_job"
        )
        iteration_no = self._resolve_base_request_record().current_iteration_no or 1
        rearm_on_reentry = bool(self.env.context.get("force_transit"))
        due_at = False
        if meta_task and getattr(meta_task, "automation_run_mode", "immediate") == "scheduled":
            due_at = meta_task._compute_automation_due_at()

        idempotency_action_type = automation_node.action_type if automation_node else action_type
        execute_path_execution_id = self.env.context.get("workflow_execute_path_execution_id")
        if execute_path_execution_id:
            idempotency_action_type = "%s:%s" % (idempotency_action_type, execute_path_execution_id)

        automation_instance = self.env["workflow.request.automation.instance"].create_or_get(
            request_record=self._resolve_base_request_record(),
            automation_node=automation_node,
            node_id=node.attrib.get("id"),
            node_name=node.attrib.get("name"),
            node_type=node_type,
            branch_node_id=node.attrib.get("id"),
            trigger_type="automation",
            action_type=automation_node.action_type if automation_node else action_type,
            due_at=due_at,
            failure_policy=(automation_node.failure_policy if automation_node else "retry"),
            timeout_seconds=(automation_node.timeout_seconds if automation_node else 30),
            required=False,
            iteration_no=iteration_no,
            payload_json={
                "execution_mode": "side_effect",
                "source_node_id": current_previous.attrib.get("id") if current_previous is not None else False,
                "execute_path_execution_id": execute_path_execution_id or False,
            },
            rearm_on_reentry=rearm_on_reentry,
            recurrence_enabled=bool(meta_task and meta_task._is_automation_recurring_enabled()),
            recurrence_mode=(meta_task.automation_recurrence_end_mode if meta_task else False) or "forever",
            recurrence_count=(meta_task.automation_recurrence_count if meta_task else 0) or 0,
            recurrence_until=(meta_task.automation_recurrence_until if meta_task else False) or False,
            idempotency_key=self.env["workflow.request.automation.instance"].build_idempotency_key(
                request_id=self._resolve_base_request_record().id,
                node_id=node.attrib.get("id"),
                iteration_no=iteration_no,
                branch_node_id=node.attrib.get("id"),
                trigger_type="automation",
                action_type=idempotency_action_type,
                due_at=due_at,
            ),
        )
        if due_at:
            return {"status": "scheduled", "instance": automation_instance}
        if automation_instance.status == "success":
            return {"status": "success", "instance": automation_instance}

        automation_instance.mark_running()
        try:
            execution_result = self._workflow_execute_runtime_actions(
                engine,
                node,
                meta_task,
                automation_instance=automation_instance,
                meta_action=meta_action,
            )
            result_json = {
                "node_id": node.attrib.get("id"),
                "node_type": node_type,
            }
            if isinstance(execution_result, dict):
                result_json.update(execution_result)
            automation_instance.mark_success(
                result_json
            )
            return {"status": "success", "instance": automation_instance}
        except Exception as error:
            failure_policy = automation_instance.failure_policy or "retry"
            if failure_policy == "ignore":
                automation_instance.mark_failed(str(error))
                return {"status": "failed", "instance": automation_instance}
            if failure_policy == "retry":
                self._workflow_schedule_retry_instance(automation_instance, str(error))
                return {"status": "scheduled", "instance": automation_instance}
            automation_instance.mark_failed(str(error))
            raise

    def _workflow_execute_runtime_actions(self, engine, node, meta_task, automation_instance=False, meta_action=False):
        self.ensure_one()
        node_type = engine.get_element_type(node)
        if node_type == NODE_TYPE["SEND_TASK"] or self._workflow_is_message_notification_node_type(node_type):
            return self._handle_send_task(meta_task, meta_action)
        if node_type == NODE_TYPE["SCRIPT_TASK"]:
            return self._handle_script_task(meta_task, meta_action)
        if node_type == NODE_TYPE["SERVICE_TASK"]:
            return self._execute_workflow_actions(meta_task)
        return None

    def _workflow_execute_timer_reminder_path(self, engine, timer_node, meta_action, automation_instance):
        """Execute the side-effect branch after a timer without moving workflow state."""
        self.ensure_one()
        executed = []
        queue = list(self._workflow_get_next_elements(engine, timer_node, form_data=self._get_form_data()))
        visited = set()
        hops = 0
        while queue:
            current = queue.pop(0)
            hops += 1
            if hops > 60:
                raise UserError(_("Timer reminder path exceeded maximum hops."))
            if current is None:
                continue
            node_id = current.attrib.get("id")
            if not node_id or node_id in visited:
                continue
            visited.add(node_id)
            current_type = engine.get_element_type(current)
            if self._workflow_is_message_notification_node_type(current_type):
                meta_task = self._resolve_meta_task_for_node(node_id, current.attrib.get("name"))
                self._handle_send_task(meta_task, meta_action)
                executed.append(node_id)
                if engine.is_end_event(current):
                    continue
            if engine.is_end_event(current) or current_type in [
                NODE_TYPE["USER_TASK"],
                NODE_TYPE["MANUAL_TASK"],
                NODE_TYPE["TASK"],
                NODE_TYPE["CALL_ACTIVITY"],
            ]:
                continue
            meta_task = self._resolve_meta_task_for_node(node_id, current.attrib.get("name"))
            if current_type == NODE_TYPE["SERVICE_TASK"] and meta_task and meta_task.service_behavior != "executor":
                continue
            if current_type in [NODE_TYPE["SEND_TASK"], NODE_TYPE["SCRIPT_TASK"], NODE_TYPE["SERVICE_TASK"]]:
                if meta_task and not self._workflow_should_execute_meta_task(meta_task):
                    continue
                self._workflow_execute_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    automation_instance=automation_instance,
                    meta_action=meta_action,
                )
                executed.append(node_id)
            queue.extend(self._workflow_get_next_elements(engine, current, form_data=self._get_form_data()))
        return executed

    def _workflow_is_execute_path_action(self, meta_action):
        return bool(meta_action and getattr(meta_action, "action_mode", "route") == "execute_path")

    def _workflow_is_activation_node(self, engine, node):
        if node is None:
            return False
        return engine.get_element_type(node) in [
            NODE_TYPE["USER_TASK"],
            NODE_TYPE["MANUAL_TASK"],
            NODE_TYPE["TASK"],
            NODE_TYPE["CALL_ACTIVITY"],
        ]

    def _workflow_collect_execute_path_targets(self, engine, start_node, source_node, form_data=None, max_hops=60):
        """Return reachable user/call tasks before executing side effects."""
        self.ensure_one()
        queue = [(start_node, source_node)]
        visited_edges = set()
        activations = []
        activated_node_ids = set()
        hops = 0
        while queue:
            current, previous = queue.pop(0)
            if current is None:
                continue
            node_id = current.attrib.get("id")
            previous_id = previous.attrib.get("id") if previous is not None else ""
            edge_key = (previous_id, node_id)
            if not node_id or edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)
            hops += 1
            if hops > max_hops:
                raise UserError(_("Execute Path traversal exceeded maximum hops."))

            if engine.is_end_event(current):
                continue
            if self._workflow_is_activation_node(engine, current):
                if node_id not in activated_node_ids:
                    activated_node_ids.add(node_id)
                    activations.append((current, previous))
                continue

            current_type = engine.get_element_type(current)
            if current_type == NODE_TYPE["SERVICE_TASK"]:
                meta_task = self._resolve_meta_task_for_node(node_id, current.attrib.get("name"))
                if meta_task and meta_task.service_behavior != "executor":
                    # Router services are treated as pass-through in execute-path precheck.
                    pass
            for next_node in self._workflow_get_next_elements(engine, current, form_data=form_data):
                queue.append((next_node, current))
        return activations

    def _workflow_precheck_execute_path_assignments(self, engine, activations):
        self.ensure_one()
        for activation_node, previous_node in activations:
            blocked_action = self._precheck_next_stage_assignment(
                engine=engine,
                current_node=previous_node,
                next_node=activation_node,
            )
            if blocked_action:
                return blocked_action
        return None

    def _workflow_write_engine_owned_fields(self, vals):
        self.ensure_one()
        vals = {key: value for key, value in (vals or {}).items() if key in self._fields}
        if not vals:
            return True
        record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(record, "with_context"):
            record = record.with_context(
                wf_skip_block_sync=True,
                workflow_skip_edit_scope=True,
                workflow_skip_field_policy=True,
                workflow_allow_runtime_tracking_write=True,
            )
        if hasattr(record, "write"):
            record.write(vals)
        else:
            for field_name, value in vals.items():
                setattr(self, field_name, value)
        if hasattr(self, "invalidate_recordset"):
            self.invalidate_recordset(list(vals))
        return True

    def _workflow_set_execute_path_wait_state(self, engine, source_node, active_node_ids):
        self.ensure_one()
        active_node_ids = list(dict.fromkeys([node_id for node_id in (active_node_ids or []) if node_id]))
        if not active_node_ids:
            raise UserError(_("Execute Path did not activate any user task."))

        display_node = engine.get_element_by_id(active_node_ids[0]) if len(active_node_ids) == 1 else source_node
        vals = {
            "previous_node_id": self.current_node_id,
            "previous_activity_name": self.current_activity_name,
            "current_node_id": display_node.attrib.get("id"),
            "current_activity_name": display_node.attrib.get("name") or source_node.attrib.get("name"),
            "next_node_id": False,
            "next_activity_name": False,
            "next_is_end_event": False,
            "state": "waiting",
        }
        if self.request_status != "approved":
            vals["request_status"] = "pending"
        if len(active_node_ids) > 1:
            vals.update({
                "active_branch_node_ids": active_node_ids,
                "branch_gateway_node_id": source_node.attrib.get("id"),
                "branch_join_node_id": False,
                "branch_mode": "parallel",
            })
        else:
            vals.update({
                "active_branch_node_ids": [],
                "branch_gateway_node_id": False,
                "branch_join_node_id": False,
                "branch_mode": False,
            })
        self._workflow_write_engine_owned_fields(vals)

    def _workflow_execute_path_traversal(
            self,
            engine,
            start_node,
            source_node,
            meta_action,
            form_data,
            re_assign_approvals,
            is_need_to_send_email,
            max_hops=60,
    ):
        self.ensure_one()
        queue = [(start_node, source_node)]
        visited_edges = set()
        active_node_ids = []
        activated_node_ids = set()
        executed_node_ids = []
        hops = 0
        while queue:
            current, previous = queue.pop(0)
            if current is None:
                continue
            node_id = current.attrib.get("id")
            previous_id = previous.attrib.get("id") if previous is not None else ""
            edge_key = (previous_id, node_id)
            if not node_id or edge_key in visited_edges:
                continue
            visited_edges.add(edge_key)
            hops += 1
            if hops > max_hops:
                raise UserError(_("Execute Path traversal exceeded maximum hops."))

            current_type = engine.get_element_type(current)
            meta_task = self._resolve_meta_task_for_node(node_id, current.attrib.get("name"))
            if self._workflow_is_message_notification_node_type(current_type):
                self._handle_send_task(meta_task, meta_action)
                executed_node_ids.append(node_id)
                if engine.is_end_event(current):
                    continue
            if engine.is_end_event(current):
                continue

            if current_type == NODE_TYPE["CALL_ACTIVITY"]:
                self._handle_call_activity(
                    engine,
                    form_data,
                    meta_action,
                    previous,
                    current,
                    update_tracking=False,
                )
                if node_id not in activated_node_ids:
                    activated_node_ids.add(node_id)
                    active_node_ids.append(node_id)
                continue

            if current_type in [NODE_TYPE["USER_TASK"], NODE_TYPE["MANUAL_TASK"], NODE_TYPE["TASK"]]:
                if node_id not in activated_node_ids:
                    activated_node_ids.add(node_id)
                    if re_assign_approvals:
                        self._assign_dynamic_approvers_from_meta(
                            meta_action,
                            previous,
                            current,
                            is_need_to_send_email,
                        )
                    self._workflow_post_activate_runtime_node(engine, current)
                    active_node_ids.append(node_id)
                continue

            should_execute = current_type in [NODE_TYPE["SEND_TASK"], NODE_TYPE["SCRIPT_TASK"]]
            should_execute = should_execute or (
                current_type == NODE_TYPE["SERVICE_TASK"]
                and meta_task
                and meta_task.service_behavior == "executor"
            )
            if should_execute:
                self._workflow_run_or_schedule_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    previous,
                    meta_action=meta_action,
                )
                executed_node_ids.append(node_id)

            for next_node in self._workflow_get_next_elements(engine, current, form_data=form_data):
                queue.append((next_node, current))
        return {
            "active_node_ids": active_node_ids,
            "executed_node_ids": executed_node_ids,
        }

    def _workflow_execute_path_action(
            self,
            engine,
            current_node,
            start_node,
            form_data=None,
            meta_action=False,
            re_assign_approvals=True,
            is_need_to_send_email=True,
    ):
        self.ensure_one()
        form_data = form_data or self._get_form_data()
        activations = self._workflow_collect_execute_path_targets(
            engine=engine,
            start_node=start_node,
            source_node=current_node,
            form_data=form_data,
        )
        if not activations:
            raise UserError(
                _("Execute Path action '%s' must reach at least one User Task or Call Activity.")
                % (meta_action.name or meta_action.display_name or "")
            )
        if re_assign_approvals:
            blocked_action = self._workflow_precheck_execute_path_assignments(engine, activations)
            if blocked_action:
                return blocked_action

        is_business_action = bool(
            meta_action
            and (meta_action.authorization_mode or "approval_actor") == "business_actor"
        )
        if not is_business_action:
            if not self.env.context.get("no_approval"):
                self._approve(meta_action)
            self._close_open_source_stage_approvers(current_node)
            self.cancel_activities()

        execution_id = "%s:%s:%s" % (
            meta_action.id if meta_action else "action",
            uuid4().hex,
            self.env.user.id,
        )
        result = self.with_context(
            workflow_execute_path_execution_id=execution_id,
        )._workflow_execute_path_traversal(
            engine=engine,
            start_node=start_node,
            source_node=current_node,
            meta_action=meta_action,
            form_data=form_data,
            re_assign_approvals=re_assign_approvals,
            is_need_to_send_email=is_need_to_send_email,
        )
        self._workflow_set_execute_path_wait_state(engine, current_node, result.get("active_node_ids") or [])
        return None

    def _workflow_execute_runtime_branch(self, engine, start_node, previous_node, meta_action, form_data,
                                         re_assign_approvals, is_need_to_send_email):
        self.ensure_one()
        current = start_node
        current_previous = previous_node
        hops = 0
        while current is not None:
            hops += 1
            if hops > 60:
                raise UserError(_("Runtime branch execution exceeded maximum hops."))

            current_type = engine.get_element_type(current)
            if self._workflow_is_message_notification_node_type(current_type):
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                self._workflow_run_or_schedule_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    current_previous,
                    meta_action=meta_action,
                )
                if engine.is_end_event(current):
                    return {"active_branch_ids": [], "terminal_node": current}
                next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
                current_previous = current
                current = self._resolve_runtime_next_node(
                    engine,
                    next_candidates[0] if next_candidates else None,
                    form_data=form_data,
                    preserve_side_effect_nodes=True,
                )
                continue

            if engine.is_end_event(current):
                return {"active_branch_ids": [], "terminal_node": current}

            if current_type == NODE_TYPE["CALL_ACTIVITY"]:
                self._handle_call_activity(
                    engine,
                    form_data,
                    meta_action,
                    current_previous,
                    current,
                    update_tracking=False,
                )
                return {"active_branch_ids": [current.attrib.get("id")]}

            if current_type in [NODE_TYPE["USER_TASK"], NODE_TYPE["MANUAL_TASK"], NODE_TYPE["TASK"]]:
                if re_assign_approvals:
                    self._assign_dynamic_approvers_from_meta(
                        meta_action,
                        current_previous,
                        current,
                        is_need_to_send_email,
                    )
                self._workflow_post_activate_runtime_node(engine, current)
                return {"active_branch_ids": [current.attrib.get("id")]}

            if current_type == NODE_TYPE["SERVICE_TASK"]:
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                if meta_task and meta_task.service_behavior != "executor":
                    service_result = self._handle_service_task(
                        engine,
                        form_data,
                        meta_action,
                        current,
                        re_assign_approvals,
                        is_need_to_send_email,
                    )
                    if not service_result:
                        return {"active_branch_ids": []}
                    current_previous = current
                    current = self._resolve_runtime_next_node(
                        engine,
                        service_result.get("next_node"),
                        form_data=form_data,
                        preserve_side_effect_nodes=True,
                    )
                    continue

            if current_type in [NODE_TYPE["SEND_TASK"], NODE_TYPE["SCRIPT_TASK"], NODE_TYPE["SERVICE_TASK"]]:
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                self._workflow_run_or_schedule_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    current_previous,
                    meta_action=meta_action,
                )
                next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
                current_previous = current
                current = self._resolve_runtime_next_node(
                    engine,
                    next_candidates[0] if next_candidates else None,
                    form_data=form_data,
                    preserve_side_effect_nodes=True,
                )
                continue

            if self._is_split_gateway(engine, current):
                raise UserError(
                    _("Nested runtime_v2 split gateways are not supported from node '%s'.")
                    % (current.attrib.get("name") or current.attrib.get("id"))
                )

            next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
            current_previous = current
            current = self._resolve_runtime_next_node(
                engine,
                next_candidates[0] if next_candidates else None,
                form_data=form_data,
                preserve_side_effect_nodes=True,
            )

        return {"active_branch_ids": []}

    def _workflow_run_runtime_transition_path(
            self,
            engine,
            current_node,
            start_node,
            form_data=None,
            re_assign_approvals=True,
            is_need_to_send_email=True,
            meta_action=False,
            source_stage_node=False,
    ):
        self.ensure_one()

        def _first_available_node(*nodes):
            for node in nodes:
                if node is not None and node is not False:
                    return node
            return False

        source_stage_node = _first_available_node(source_stage_node, current_node)
        current = self._resolve_runtime_transition_entry_node(
            engine,
            start_node,
            form_data=form_data,
            preserve_side_effect_nodes=True,
        )
        previous = current_node
        hops = 0
        while current is not None:
            hops += 1
            if hops > 60:
                raise UserError(_("Runtime transition execution exceeded maximum hops."))

            current_type = engine.get_element_type(current)
            if self._workflow_is_message_notification_node_type(current_type):
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                self._workflow_run_or_schedule_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    previous,
                    meta_action=meta_action,
                )
                if engine.is_end_event(current):
                    self._close_open_source_stage_approvers(
                        _first_available_node(source_stage_node, current_node, previous)
                    )
                    self._update_tracking_fields(
                        engine=engine,
                        form_data=form_data,
                        current_node=previous,
                        next_node=current,
                        meta_action=meta_action,
                    )
                    self.cancel_activities()
                    return {"waiting": False, "next_node": current}
                next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
                previous = current
                current = self._resolve_runtime_next_node(
                    engine,
                    next_candidates[0] if next_candidates else None,
                    form_data=form_data,
                    preserve_side_effect_nodes=True,
                )
                continue

            if self._is_split_gateway(engine, current):
                if re_assign_approvals:
                    blocked_action = self._precheck_parallel_split_assignment(
                        engine=engine,
                        split_node=current,
                        form_data=form_data,
                    )
                    if blocked_action:
                        raise UserError(blocked_action.get("params", {}).get("message") or _("Workflow is blocked."))
                self._close_open_source_stage_approvers(
                    _first_available_node(source_stage_node, current_node, previous)
                )
                split_result = self._process_parallel_split(
                    engine=engine,
                    split_node=current,
                    previous_node=previous,
                    meta_action=meta_action,
                    form_data=form_data,
                    re_assign_approvals=re_assign_approvals,
                    is_need_to_send_email=is_need_to_send_email,
                )
                if split_result.get("waiting"):
                    return split_result
                current = split_result.get("next_node")
                previous = current
                continue

            if current_type == NODE_TYPE["CALL_ACTIVITY"]:
                self._close_open_source_stage_approvers(
                    _first_available_node(source_stage_node, current_node, previous)
                )
                self._handle_call_activity(
                    engine,
                    form_data,
                    False,
                    previous,
                    current,
                    update_tracking=True,
                )
                return {"waiting": True, "next_node": current}

            if current_type in [NODE_TYPE["USER_TASK"], NODE_TYPE["MANUAL_TASK"], NODE_TYPE["TASK"]]:
                if re_assign_approvals:
                    blocked_action = self._precheck_next_stage_assignment(
                        engine=engine,
                        current_node=_first_available_node(source_stage_node, previous),
                        next_node=current,
                    )
                    if blocked_action:
                        raise UserError(blocked_action.get("params", {}).get("message") or _("Workflow is blocked."))
                self._close_open_source_stage_approvers(
                    _first_available_node(source_stage_node, current_node, previous)
                )
                self._update_tracking_fields(
                    engine=engine,
                    form_data=form_data,
                    current_node=previous,
                    next_node=current,
                    meta_action=meta_action,
                )
                self.cancel_activities()
                if re_assign_approvals:
                    self._assign_dynamic_approvers_from_meta(
                        meta_action,
                        _first_available_node(source_stage_node, previous),
                        current,
                        is_need_to_send_email,
                    )
                    self._workflow_post_activate_runtime_node(engine, current)
                return {"waiting": True, "next_node": current}

            if current_type == NODE_TYPE["SERVICE_TASK"]:
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                if meta_task and meta_task.service_behavior != "executor":
                    service_result = self._handle_service_task(
                        engine,
                        form_data or self._get_form_data(),
                        False,
                        current,
                        True,
                        True,
                    )
                    if not service_result:
                        return {"waiting": False, "next_node": False}
                    previous = current
                    current = self._resolve_runtime_next_node(
                        engine,
                        service_result.get("next_node"),
                        form_data=form_data,
                        preserve_side_effect_nodes=True,
                    )
                    continue

            if current_type in [NODE_TYPE["SEND_TASK"], NODE_TYPE["SCRIPT_TASK"], NODE_TYPE["SERVICE_TASK"]]:
                meta_task = self._resolve_meta_task_for_node(
                    current.attrib.get("id"),
                    current.attrib.get("name"),
                )
                self._workflow_run_or_schedule_runtime_actions(
                    engine,
                    current,
                    meta_task,
                    previous,
                    meta_action=meta_action,
                )
                next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
                previous = current
                current = self._resolve_runtime_next_node(
                    engine,
                    next_candidates[0] if next_candidates else None,
                    form_data=form_data,
                    preserve_side_effect_nodes=True,
                )
                continue

            if engine.is_end_event(current):
                self._close_open_source_stage_approvers(
                    _first_available_node(source_stage_node, current_node, previous)
                )
                self._update_tracking_fields(
                    engine=engine,
                    form_data=form_data,
                    current_node=previous,
                    next_node=current,
                    meta_action=meta_action,
                )
                self.cancel_activities()
                return {"waiting": False, "next_node": current}

            next_candidates = self._workflow_get_next_elements(engine, current, form_data=form_data)
            previous = current
            current = self._resolve_runtime_next_node(
                engine,
                next_candidates[0] if next_candidates else None,
                form_data=form_data,
                preserve_side_effect_nodes=True,
            )
        return {"waiting": False, "next_node": False}

    def _workflow_run_runtime_automation_instance(self, automation_instance):
        self.ensure_one()
        if not automation_instance:
            return False
        automation_instance = automation_instance.sudo()
        base_request = self._resolve_base_request_record()
        if not base_request or not self.version_id:
            automation_instance.mark_cancelled(_("Workflow request is no longer available."))
            return False

        payload = automation_instance.payload_json or {}
        execution_mode = payload.get("execution_mode") or ""
        engine = BpmnEngine(self.version_id.bpmn_xml)
        if execution_mode == "timer_transition":
            active_nodes = self._workflow_active_node_ids_for_runtime_instance(base_request)
            branch_node_id = automation_instance.branch_node_id or payload.get("source_node_id")
            if branch_node_id and branch_node_id not in active_nodes:
                automation_instance.mark_cancelled(_("Timer superseded by a manual transition."))
                return False
            node = engine.get_element_by_id(automation_instance.node_id)
            if node is None:
                automation_instance.mark_failed(
                    _("Runtime automation node '%s' was not found.") % (automation_instance.node_id or ""))
                return False
            # Evaluate studio-configured condition domains before committing the transition.
            # A false guard is a skipped run for recurring schedules because the same domain
            # may become true on a later interval.
            timer_node_id = automation_instance.node_id
            meta_action = self._workflow_find_meta_action_for_transition(
                timer_node_id,
                source_node_id=branch_node_id,
            )
            if meta_action:
                if meta_action.auto_action_condition:
                    if not self.check_domain(meta_action.auto_action_condition, default=False):
                        return self._workflow_skip_or_rearm_runtime_instance(
                            automation_instance,
                            meta_action,
                            _("Timer condition domain did not match. Execution skipped."),
                            meta_action=meta_action,
                        )
                if not self._workflow_action_execution_guard_matches(meta_action):
                    return self._workflow_skip_or_rearm_runtime_instance(
                        automation_instance,
                        meta_action,
                        _("Runtime Domain Guard did not match. Execution skipped."),
                        meta_action=meta_action,
                    )
            automation_instance.mark_running()
            try:
                is_reminder_mode = bool(meta_action and meta_action.automation_trigger_mode == "reminder")
                if is_reminder_mode:
                    executed_node_ids = self._workflow_execute_timer_reminder_path(
                        engine,
                        node,
                        meta_action,
                        automation_instance,
                    )
                    recurrence_plan = automation_instance._prepare_recurrence_after_success(meta_action=meta_action)
                    automation_instance.mark_success(
                        {
                            "transition_node_id": automation_instance.node_id,
                            "trigger_mode": "reminder",
                            "executed_node_ids": executed_node_ids,
                        },
                        run_count=recurrence_plan.get("completed_runs"),
                        next_due_at=recurrence_plan.get("next_due_at"),
                    )
                    return True

                if branch_node_id:
                    self._workflow_close_runtime_branch(
                        branch_node_id,
                        reason=_("Closed by timer transition '%s'.") % (
                                    automation_instance.node_name or automation_instance.node_id),
                    )
                    self._workflow_cancel_runtime_instances(
                        branch_node_id=branch_node_id,
                        reason=_("Timer superseded by workflow automation."),
                        exclude_instance_ids=[automation_instance.id],
                    )
                    if branch_node_id in (self.active_branch_node_ids or []):
                        remaining_nodes = [node_id for node_id in (self.active_branch_node_ids or []) if
                                           node_id != branch_node_id]
                        self.active_branch_node_ids = remaining_nodes
                next_candidates = engine.get_next_elements(node, form_data=self._get_form_data())
                transition_result = self._workflow_run_runtime_transition_path(
                    engine=engine,
                    current_node=engine.get_element_by_id(branch_node_id) if branch_node_id else node,
                    start_node=next_candidates[0] if next_candidates else None,
                    form_data=self._get_form_data(),
                )
                recurrence_plan = {"completed_runs": (automation_instance.run_count or 0) + 1, "next_due_at": False}
                base_request.invalidate_recordset(["current_node_id", "active_branch_node_ids"])
                active_after_transition = set(base_request.active_branch_node_ids or [])
                if base_request.current_node_id:
                    active_after_transition.add(base_request.current_node_id)
                can_rearm_timer = bool(
                    meta_action
                    and meta_action._is_automation_recurring_enabled()
                    and branch_node_id
                    and branch_node_id in active_after_transition
                )
                if can_rearm_timer:
                    recurrence_plan = automation_instance._prepare_recurrence_after_success(meta_action=meta_action)
                automation_instance.mark_success(
                    {
                        "transition_node_id": automation_instance.node_id,
                        "next_node_id": transition_result.get("next_node").attrib.get("id") if transition_result.get(
                            "next_node") is not None else False,
                    },
                    run_count=recurrence_plan.get("completed_runs"),
                    next_due_at=recurrence_plan.get("next_due_at"),
                )
                return True
            except Exception as error:
                if automation_instance.failure_policy == "retry":
                    self._workflow_schedule_retry_instance(automation_instance, str(error))
                    return False
                if automation_instance.failure_policy == "ignore":
                    automation_instance.mark_failed(str(error))
                    return False
                automation_instance.mark_failed(str(error))
                raise

        active_nodes = self._workflow_active_node_ids_for_runtime_instance(base_request)
        source_node_id = automation_instance.branch_node_id or payload.get("source_node_id")
        if source_node_id and source_node_id not in active_nodes:
            automation_instance.mark_cancelled(_("Automation superseded because the source activity is no longer active."))
            return False
        meta_task = self._resolve_meta_task_for_node(automation_instance.node_id, automation_instance.node_name)
        if meta_task and not self._workflow_should_execute_meta_task(meta_task):
            return self._workflow_skip_or_rearm_runtime_instance(
                automation_instance,
                meta_task,
                _("Automation condition does not match. Execution skipped."),
                meta_task=meta_task,
            )

        node = engine.get_element_by_id(automation_instance.node_id)
        if node is None:
            automation_instance.mark_failed(
                _("Runtime automation node '%s' was not found.") % (automation_instance.node_id or ""))
            return False

        automation_instance.mark_running()
        try:
            execution_result = self._workflow_execute_runtime_actions(
                engine,
                node,
                meta_task,
                automation_instance=automation_instance,
            )
            recurrence_plan = automation_instance._prepare_recurrence_after_success(meta_task)
            result_json = {"node_id": node.attrib.get("id"), "node_type": engine.get_element_type(node)}
            if isinstance(execution_result, dict):
                result_json.update(execution_result)
            automation_instance.mark_success(
                result_json,
                run_count=recurrence_plan.get("completed_runs"),
                next_due_at=recurrence_plan.get("next_due_at"),
            )
            return True
        except Exception as error:
            if automation_instance.failure_policy == "retry":
                self._workflow_schedule_retry_instance(automation_instance, str(error))
                return False
            if automation_instance.failure_policy == "ignore":
                automation_instance.mark_failed(str(error))
                return False
            automation_instance.mark_failed(str(error))
            raise

    def _is_split_gateway(self, engine, node):
        if node is None:
            return False
        node_type = engine.get_element_type(node)
        return node_type in [NODE_TYPE['PARALLEL_GATEWAY'], NODE_TYPE['INCLUSIVE_GATEWAY']]

    def _resolve_runtime_next_nodes(self, engine, node, form_data=None, max_hops=60):
        """
        Resolve pass-through nodes and return all executable next nodes.
        """
        if node is None:
            return []
        current_level = [node]
        visited = set()
        hops = 0
        while current_level:
            resolved = []
            next_level = []
            for current in current_level:
                if current is None:
                    continue
                node_id = current.attrib.get("id")
                if not node_id:
                    continue
                if node_id in visited:
                    continue
                visited.add(node_id)
                if engine.is_end_event(current) or not engine.is_pass_through_node(current):
                    resolved.append(current)
                    continue
                next_level.extend(self._workflow_get_next_elements(engine, current, form_data=form_data))
            if resolved:
                dedup = []
                seen = set()
                for item in resolved:
                    node_id = item.attrib.get("id")
                    if node_id and node_id not in seen:
                        dedup.append(item)
                        seen.add(node_id)
                return dedup
            current_level = next_level
            hops += 1
            if hops > max_hops:
                raise UserError(_("BPMN routing exceeded maximum hops (%s).") % max_hops)
        return []

    def _guess_join_node_for_split(self, engine, branch_nodes):
        """
        Best-effort join detection:
        1) common meta join_key on branch tasks
        2) common direct outgoing gateway id from all branches
        """
        self.ensure_one()
        if not branch_nodes:
            return None
        join_ids = []
        for branch in branch_nodes:
            meta_task = self._resolve_meta_task_for_node(
                branch.attrib.get("id"),
                branch.attrib.get("name"),
            )
            if meta_task and meta_task.join_key:
                join_ids.append(meta_task.join_key)
        if join_ids and len(set(join_ids)) == 1:
            return engine.get_element_by_id(join_ids[0])

        candidate_sets = []
        for branch in branch_nodes:
            outgoing = engine.get_next_elements(branch, evaluate_conditions=False)
            candidate_ids = {
                n.attrib.get("id")
                for n in outgoing
                if engine.get_element_type(n) in [
                    NODE_TYPE['PARALLEL_GATEWAY'],
                    NODE_TYPE['INCLUSIVE_GATEWAY'],
                    NODE_TYPE['EXCLUSIVE_GATEWAY'],
                    NODE_TYPE['COMPLEX_GATEWAY'],
                ]
            }
            if candidate_ids:
                candidate_sets.append(candidate_ids)
        if not candidate_sets:
            return None
        common = set.intersection(*candidate_sets) if len(candidate_sets) > 1 else candidate_sets[0]
        if not common:
            return None
        join_id = sorted(common)[0]
        return engine.get_element_by_id(join_id)

    def _set_parallel_wait_state(self, split_node, join_node, active_branch_ids, display_node=False):
        self.ensure_one()
        # ODOO_ORM
        #projected_node = display_node or split_node
        projected_node = display_node if display_node is not None else split_node
        vals = {
            "previous_node_id": self.current_node_id,
            "previous_activity_name": self.current_activity_name,
            "current_node_id": projected_node.attrib.get("id"),
            "current_activity_name": projected_node.attrib.get("name") or split_node.attrib.get("name") or _(
                "Parallel Review"),
            "next_node_id": join_node.attrib.get("id") if join_node is not None else False,
            "next_activity_name": join_node.attrib.get("name") if join_node is not None else False,
            "next_is_end_event": False,
            "state": "waiting",
            "active_branch_node_ids": active_branch_ids,
            "branch_gateway_node_id": split_node.attrib.get("id"),
            "branch_join_node_id": join_node.attrib.get("id") if join_node is not None else False,
            "branch_mode": "parallel" if split_node.tag.endswith(NODE_TYPE['PARALLEL_GATEWAY']) else "inclusive",
        }
        if self.request_status != "approved":
            vals["request_status"] = "pending"
        self._workflow_write_engine_owned_fields(vals)

    def _resolve_parallel_display_node(self, engine, split_node, active_branch_ids):
        self.ensure_one()
        active_branch_ids = [node_id for node_id in (active_branch_ids or []) if node_id]
        if len(active_branch_ids) == 1:
            # ODOO_ORM
            #return engine.get_element_by_id(active_branch_ids[0]) or split_node
            display_node = engine.get_element_by_id(active_branch_ids[0])
            return display_node if display_node is not None else split_node
        return split_node

    def _process_parallel_split(
            self,
            engine,
            split_node,
            previous_node,
            meta_action,
            form_data,
            re_assign_approvals,
            is_need_to_send_email,
    ):
        """
        Activate branch tasks concurrently for parallel/inclusive split.
        """
        self.ensure_one()
        if self._workflow_is_runtime_v2():
            branch_candidates = engine.get_next_elements(split_node, form_data=form_data)
            branch_nodes = []
            seen = set()
            for candidate in branch_candidates:
                for resolved in self._resolve_runtime_next_nodes(engine, candidate, form_data=form_data):
                    node_id = resolved.attrib.get("id")
                    if node_id and node_id not in seen:
                        seen.add(node_id)
                        branch_nodes.append(resolved)
            if not branch_nodes:
                raise UserError(_("No executable branches found after gateway '%s'.") % (
                            split_node.attrib.get("name") or split_node.attrib.get("id")))

            join_node = self._guess_join_node_for_split(engine, branch_nodes)
            active_branch_ids = []
            for branch_node in branch_nodes:
                result = self._workflow_execute_runtime_branch(
                    engine=engine,
                    start_node=branch_node,
                    previous_node=split_node,
                    meta_action=meta_action,
                    form_data=form_data,
                    re_assign_approvals=re_assign_approvals,
                    is_need_to_send_email=is_need_to_send_email,
                )
                active_branch_ids.extend(result.get("active_branch_ids") or [])

            active_branch_ids = [node_id for node_id in active_branch_ids if node_id]
            if not active_branch_ids and join_node is not None:
                next_candidates = engine.get_next_elements(join_node, form_data=form_data)
                next_node = self._resolve_runtime_next_node(
                    engine,
                    next_candidates[0] if next_candidates else None,
                    form_data=form_data,
                )
                if next_node is None:
                    raise UserError(_("No executable node found after join gateway '%s'.") % (
                                join_node.attrib.get("name") or join_node.attrib.get("id")))
                self._clear_active_branch_state()
                self._update_tracking_fields(
                    engine=engine,
                    form_data=form_data,
                    current_node=previous_node,
                    next_node=next_node,
                    meta_action=meta_action,
                )
                if re_assign_approvals:
                    self._assign_dynamic_approvers_from_meta(meta_action, previous_node, next_node,
                                                             is_need_to_send_email)
                    self._workflow_post_activate_runtime_node(engine, next_node)
                return {"waiting": False, "next_node": next_node}

            display_node = self._resolve_parallel_display_node(engine, split_node, active_branch_ids)
            self._set_parallel_wait_state(split_node, join_node, active_branch_ids, display_node=display_node)
            return {"waiting": bool(active_branch_ids), "join_node": join_node}

        branch_candidates = engine.get_next_elements(split_node, form_data=form_data)
        branch_nodes = []
        seen = set()
        for candidate in branch_candidates:
            for resolved in self._resolve_runtime_next_nodes(engine, candidate, form_data=form_data):
                node_id = resolved.attrib.get("id")
                if node_id and node_id not in seen:
                    seen.add(node_id)
                    branch_nodes.append(resolved)
        if not branch_nodes:
            raise UserError(_("No executable branches found after gateway '%s'.") % (
                        split_node.attrib.get("name") or split_node.attrib.get("id")))

        join_node = self._guess_join_node_for_split(engine, branch_nodes)
        active_branch_ids = []
        for index, branch_node in enumerate(branch_nodes):
            branch_type = engine.get_element_type(branch_node)
            if branch_type == NODE_TYPE['CALL_ACTIVITY']:
                self._handle_call_activity(
                    engine,
                    form_data,
                    meta_action,
                    split_node,
                    branch_node,
                    update_tracking=False,
                )
                active_branch_ids.append(branch_node.attrib.get("id"))
                continue

            if branch_type in [NODE_TYPE['USER_TASK'], NODE_TYPE['MANUAL_TASK'], NODE_TYPE['TASK']]:
                if re_assign_approvals:
                    assignee_target = self.with_context(
                        workflow_skip_owner_notify=index > 0,
                    )
                    assignee_target._assign_dynamic_approvers_from_meta(
                        meta_action,
                        split_node,
                        branch_node,
                        is_need_to_send_email,
                    )
                active_branch_ids.append(branch_node.attrib.get("id"))
                continue

            if branch_type == NODE_TYPE['SCRIPT_TASK']:
                meta_task = self._resolve_meta_task_for_node(
                    branch_node.attrib.get('id'),
                    branch_node.attrib.get('name'),
                )
                self._handle_script_task(meta_task, meta_action)
                continue

            if branch_type == NODE_TYPE['SEND_TASK']:
                meta_task = self._resolve_meta_task_for_node(
                    branch_node.attrib.get('id'),
                    branch_node.attrib.get('name'),
                )
                self._handle_send_task(meta_task, meta_action)
                continue

        if not active_branch_ids and join_node is not None:
            next_candidates = engine.get_next_elements(join_node, form_data=form_data)
            next_node = self._resolve_runtime_next_node(
                engine,
                next_candidates[0] if next_candidates else None,
                form_data=form_data,
            )
            if next_node is None:
                raise UserError(_("No executable node found after join gateway '%s'.") % (
                            join_node.attrib.get("name") or join_node.attrib.get("id")))
            self._clear_active_branch_state()
            self._update_tracking_fields(
                engine=engine,
                form_data=form_data,
                current_node=previous_node,
                next_node=next_node,
                meta_action=meta_action,
            )
            if re_assign_approvals:
                self._assign_dynamic_approvers_from_meta(meta_action, previous_node, next_node, is_need_to_send_email)
            return {"waiting": False, "next_node": next_node}

        self._set_parallel_wait_state(split_node, join_node, [node_id for node_id in active_branch_ids if node_id])
        return {"waiting": True, "join_node": join_node}

    def _complete_parallel_branch_and_resolve(self, engine, form_data, meta_action):
        """
        Mark current branch complete. When all branches complete, return next node after join.
        """
        self.ensure_one()
        source_node_id = meta_action.source_id
        active_branch_ids = list(self.active_branch_node_ids or [])
        if source_node_id in active_branch_ids:
            active_branch_ids.remove(source_node_id)
        self.active_branch_node_ids = active_branch_ids

        if active_branch_ids:
            if self._workflow_is_runtime_v2():
                split_node = engine.get_element_by_id(
                    self.branch_gateway_node_id) if self.branch_gateway_node_id else None
                display_node = self._resolve_parallel_display_node(engine, split_node, active_branch_ids)
                if display_node is not None:
                    self.current_node_id = display_node.attrib.get("id")
                    self.current_activity_name = display_node.attrib.get("name") or self.current_activity_name
            return {"waiting": True, "next_node": None}

        join_node = engine.get_element_by_id(self.branch_join_node_id) if self.branch_join_node_id else None
        self._clear_active_branch_state()
        if join_node is None:
            next_node = self._resolve_runtime_next_node(
                engine,
                engine.get_element_by_id(meta_action.target_id),
                form_data=form_data,
            )
            return {"waiting": False, "next_node": next_node}

        next_candidates = engine.get_next_elements(join_node, form_data=form_data)
        next_node = self._resolve_runtime_next_node(
            engine,
            next_candidates[0] if next_candidates else None,
            form_data=form_data,
        )
        return {"waiting": False, "next_node": next_node, "join_node": join_node}

    def _workflow_resume_parallel_join(self, branch_node_id=False):
        """
        Resume parent workflow after child/sub-process branch completion.
        Returns True when workflow was resumed/advanced.
        """
        self.ensure_one()
        base_request = self._resolve_base_request_record()
        if not self.active_branch_node_ids:
            return False

        active_nodes = list(self.active_branch_node_ids or [])
        if branch_node_id and branch_node_id in active_nodes:
            active_nodes.remove(branch_node_id)

        child_requests = base_request.child_ids if base_request else self.env["workflow.base.approval.request"]
        completed_branch_nodes = {
            child.parent_meta_node_id
            for child in child_requests.filtered(lambda c: c.execution_mode == "sync" and c.state == "completed")
            if child.parent_meta_node_id
        }
        if completed_branch_nodes:
            active_nodes = [node_id for node_id in active_nodes if node_id not in completed_branch_nodes]

        self.active_branch_node_ids = active_nodes
        engine = BpmnEngine(self.version_id.bpmn_xml)

        if active_nodes:
            if self._workflow_is_runtime_v2():
                split_node = engine.get_element_by_id(
                    self.branch_gateway_node_id) if self.branch_gateway_node_id else None
                display_node = self._resolve_parallel_display_node(engine, split_node, active_nodes)
                if display_node is not None:
                    self.current_node_id = display_node.attrib.get("id")
                    self.current_activity_name = display_node.attrib.get("name") or self.current_activity_name
            self.state = "waiting"
            if self.request_status != "approved":
                self.request_status = "pending"
            return True

        join_node = engine.get_element_by_id(self.branch_join_node_id) if self.branch_join_node_id else None
        self._clear_active_branch_state()
        if not join_node:
            return False

        next_candidates = engine.get_next_elements(join_node, form_data=self._get_form_data())
        next_node = self._resolve_runtime_next_node(
            engine,
            next_candidates[0] if next_candidates else None,
            form_data=self._get_form_data(),
        )
        if not next_node:
            return False

        blocked_action = self._precheck_next_stage_assignment(
            engine=engine,
            current_node=join_node,
            next_node=next_node,
        )
        if blocked_action:
            return True

        self._update_tracking_fields(
            engine=engine,
            form_data=self._get_form_data(),
            current_node=join_node,
            next_node=next_node,
            meta_action=False,
        )
        self.cancel_activities()
        self._assign_dynamic_approvers_from_meta(
            meta_action=False,
            current_node=join_node,
            next_node=next_node,
            is_need_to_send_mail=True,
        )
        self._workflow_post_activate_runtime_node(engine, next_node)
        return True

    def _first_time_run(self, engine, form_data, meta_action, re_assign_approvals, is_need_to_send_email):
        """
        Engine runs from start node
        """
        initial_current_node_id = self.current_node_id
        initial_current_activity_name = self.current_activity_name
        start_node = engine.get_start_event()
        self.current_node_id = start_node.attrib['id']
        self.current_activity_name = start_node.attrib.get('name')

        next_nodes = engine.get_next_elements(start_node, form_data=form_data)
        raw_next_node = next_nodes[0] if next_nodes else None
        if self._is_split_gateway(engine, raw_next_node):
            if re_assign_approvals:
                blocked_action = self._precheck_parallel_split_assignment(
                    engine=engine,
                    split_node=raw_next_node,
                    form_data=form_data,
                )
                if blocked_action:
                    self.current_node_id = initial_current_node_id
                    self.current_activity_name = initial_current_activity_name
                    return blocked_action
            split_result = self._process_parallel_split(
                engine=engine,
                split_node=raw_next_node,
                previous_node=start_node,
                meta_action=meta_action,
                form_data=form_data,
                re_assign_approvals=re_assign_approvals,
                is_need_to_send_email=is_need_to_send_email,
            )
            if split_result.get("waiting"):
                return None
            next_node = split_result.get("next_node")
        else:
            next_node = self._resolve_runtime_next_node(engine, raw_next_node, form_data=form_data)

        if next_node is None:
            raise UserError("No executable node found after StartEvent.")

        next_node_type = engine.get_element_type(next_node)
        if next_node_type in [NODE_TYPE['SCRIPT_TASK']]:
            meta_task = self._resolve_meta_task_for_node(
                next_node.attrib.get('id'),
                next_node.attrib.get('name'),
            )
            self._handle_script_task(meta_task, meta_action)
            return None
        if next_node_type == NODE_TYPE['SERVICE_TASK']:
            service_result = self._handle_service_task(
                engine,
                form_data,
                meta_action,
                next_node,
                re_assign_approvals,
                is_need_to_send_email,
            )
            if not service_result:
                return None
            next_node = service_result.get("next_node")
            next_node = self._resolve_runtime_next_node(engine, next_node, form_data=form_data)
            next_node_type = engine.get_element_type(next_node) if next_node is not None else ""

        if next_node_type == NODE_TYPE['SEND_TASK']:
            meta_task = self._resolve_meta_task_for_node(
                next_node.attrib.get('id'),
                next_node.attrib.get('name'),
            )
            self._handle_send_task(meta_task, meta_action)
            next_nodes = engine.get_next_elements(next_node, form_data=form_data)
            next_node = self._resolve_runtime_next_node(
                engine,
                next_nodes[0] if next_nodes else None,
                form_data=form_data,
            )
            if next_node is None:
                raise UserError(_("No executable node found after notification task '%s'.") % (meta_task.name or ""))

        if re_assign_approvals:
            blocked_action = self._precheck_next_stage_assignment(
                engine=engine,
                current_node=start_node,
                next_node=next_node,
            )
            if blocked_action:
                self.current_node_id = initial_current_node_id
                self.current_activity_name = initial_current_activity_name
                return blocked_action

        self._update_tracking_fields(engine=engine, form_data=form_data, current_node=start_node, next_node=next_node,
                                     meta_action=meta_action)

        if re_assign_approvals:
            self._assign_dynamic_approvers_from_meta(meta_action, start_node, next_node, is_need_to_send_email)
            self._workflow_post_activate_runtime_node(engine, next_node)

        # add follower if the request owner is not the request creator
        self._subscribe_request_owner_if_needed()

    def _workflow_effective_required_approval_count(self, meta_action, assigned_approvals):
        configured_required = max(1, int(meta_action.approval_require_number or 1))
        return min(configured_required, max(1, len(assigned_approvals)))

    def _handle_multiple_approvers(self, current_node, meta_action):
        node_id = current_node.attrib["id"]
        active_iteration_no = self._resolve_iteration_for_action(node_id)
        current_approval = self.approver_ids.filtered(
            lambda a: a.current_meta_id.node_id == node_id
            and (a.iteration_no or 1) == active_iteration_no
        )
        if not current_approval:
            return None

        if not self.env.context.get("no_approval"):
            self._approve(meta_action)

        assigned_approvals = current_approval.filtered(lambda a: a.required) or current_approval
        configured_required = max(1, int(meta_action.approval_require_number or 1))
        effective_required = self._workflow_effective_required_approval_count(
            meta_action,
            assigned_approvals,
        )
        req_id = self._resolve_base_request_record().id
        terminal_statuses = ("approved", "refused", "cancelled", "closed")
        decided = self.env["workflow.approval.approver"].sudo().search([
            ("status", "in", terminal_statuses),
            ("request_id", "=", req_id),
            ("current_meta_node_id", "=", node_id),
            ("iteration_no", "=", active_iteration_no),
            ("verified_version", "=", 1),
            ("counts_as_decided_user", "=", True),
        ])
        same_decision = len(decided.filtered(lambda app: app.user_decision == meta_action.name))
        if same_decision < effective_required:
            _logger.info(
                "Waiting for more same-decision approvals (%s/%s; configured=%s, assigned=%s). "
                "Not moving forward yet.",
                same_decision,
                effective_required,
                configured_required,
                len(assigned_approvals),
            )
            return False
        return True

    def _handle_call_activity(self, engine, form_data, meta_action, current_node, next_node, update_tracking=True):
        # 🔑 Find meta task for this callActivity node
        meta_task = self.version_id.meta_task_ids.filtered(
            lambda m: m.node_id == next_node.attrib['id']
        )
        if not meta_task:
            raise UserError(f"No meta_task found for callActivity {next_node.attrib['id']}")

        # Use the Many2many field called_workflow_ids
        if not meta_task.workflow_map_ids:
            raise UserError(f"callActivity {next_node.attrib['id']} is not mapped to any workflow")

        # update tracking to callActivity node first
        if update_tracking:
            self._update_tracking_fields(engine=engine, form_data=form_data, current_node=current_node,
                                         next_node=next_node, meta_action=meta_action)
        # if re_assign_approvals:
        #     self._assign_dynamic_approvers_from_meta(current_node, next_node, is_need_to_send_email)
        # Then create subprocess instances
        self_env = None
        parent_id = None

        # if not hasattr(self, 'x_approval_base_id'):
        #     self_env = self.env(user=self.create_uid.id) 
        #     parent_id = self
        # else: 
        #     self_env = self.env(user=self.x_approval_base_id.create_uid.id)
        #     parent_id = self.x_approval_base_id

        self_env = self.env(user=self.x_approval_base_id.create_uid.id)
        parent_id = self.x_approval_base_id

        for mapping in meta_task.workflow_map_ids:
            sub_version = mapping.called_workflow_id
            # if self.x_approval_base_id.check_domain(mapping.domain, default = True) == True:
            if self.check_domain(mapping.domain, default=True) == True:
                field_map = json.loads(mapping.field_mapping or "{}")
                frm_data = {
                    "category_id": sub_version.category_id.id,
                    "version_id": sub_version.id,
                    "state": "waiting",
                    "parent_id": parent_id.id,
                    "parent_meta_node_id": next_node.attrib.get('id'),
                    "owner_user_id": parent_id.owner_user_id.id if parent_id.owner_user_id else False,
                    "owner_user_ids": [(6, 0, parent_id.owner_user_ids.ids)],
                    "request_owner_id": parent_id.request_owner_id.id if parent_id.request_owner_id else False,
                    "execution_mode": mapping.execution_mode.strip()
                }
                for parent_field, child_field in field_map.items():
                    if hasattr(self, parent_field):
                        value = getattr(self, parent_field)
                        if isinstance(value, models.BaseModel):
                            frm_data[child_field] = value.id
                        elif isinstance(value, models.Model):
                            frm_data[child_field] = [(6, 0, value.ids)]
                        else:
                            frm_data[child_field] = value
                    else:
                        frm_data[child_field] = False

                is_existing = self_env[sub_version.res_model_name].sudo().search([
                    ('parent_id', '=', parent_id.id)
                ])

                if is_existing:
                    # update status engine
                    for re in is_existing:
                        sub_engine = BpmnEngine(re.bpmn_xml)
                        submit_node = sub_engine.get_submission_task()
                        sub_meta_action = self.env['workflow.category.version.meta.task.action'].sudo().search([
                            ('source_id', '=', submit_node.attrib['id'])
                        ], limit=1)
                        if sub_meta_action is None:
                            raise UserError("No outgoing transitions found for the current node.")
                        re.action_move_transition(sub_meta_action.id, True)
                    _logger.info(
                        f"Skipping creation, {sub_version.res_model_name} already has child for parent ID {parent_id.id}")
                    continue

                sub_request = self_env[sub_version.res_model_name].sudo().create(frm_data)
                sub_request = sub_request.with_context(
                    auto_subworkflow_submit=True
                )
                # sub_request.x_approval_base_id.action_do_transition(sub_request.visible_buttons[0], show_dialog=False)
                sub_request.action_do_transition(sub_request.visible_buttons[0], show_dialog=False)

    def _handle_service_task(self, engine, form_data, meta_action, next_node, re_assign_approvals,
                             is_need_to_send_email):
        meta_task = self.version_id.meta_task_ids.filtered(
            lambda m: m.node_id == next_node.attrib['id']
        )
        if not meta_task:
            raise UserError(f"No meta task found for serviceTask node {next_node.attrib['id']}")
        meta_task = meta_task[:1]
        # Get all possible next nodes
        action_flows = engine.get_next_elements(next_node, form_data=form_data)
        if not action_flows:
            raise UserError(_(
                "Service Task '%(name)s' is configured as a router but has no outgoing path. "
                "Add an outgoing BPMN transition, or set Service Behavior to 'Executor' and select a Server Action."
            ) % {
                "name": next_node.attrib.get("name") or next_node.attrib['id'],
            })
        selected_next = None
        if meta_task:
            _logger.warning("meta_task=%s meta_task.node_id=%s meta_action_ids=%s", meta_task, meta_task.node_id,
                            meta_task.meta_action_ids.ids)

            for ma in meta_task.meta_action_ids:
                _logger.info("Checking meta_action id=%s, domain=%s", ma.id, ma.domain)
                domain_str = ma.domain
                # if self.x_approval_base_id.check_domain(domain_str, default = False):
                if self.check_domain(domain_str, default=False):
                    act_elm = engine.get_element_by_id(ma.node_id)
                    target_ref = act_elm.attrib.get('targetRef')  # safe access
                    if target_ref:
                        selected_next = engine.get_element_by_id(target_ref)
                        if selected_next is not None:
                            _logger.info("Selected next node by domain: %s", target_ref)
                            break
        # If nothing matched, just stay on the current node
        if selected_next is None:
            note_1 = Markup("<p class='text-warning'>%s</p>") % (
                _("No domain matched, staying on current node")
            )
            self._workflow_safe_message_post(
                body=note_1,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            return None
        return {
            "next_node": selected_next
        }

    def _handle_end_event_in_sub_process(self):
        # if is subprocess and end event, we need to move to next node of parent
        if self._siblings_completed():
            print(">>> All siblings complete, waiting only for this one. Parent can continue after update.")
            # run as user=1 (superuser)
            self_env = self.env(user=1)
            # get parent request in that env
            parent_as_creator = self_env['workflow.base.approval.request'].browse(self.parent_id.id)
            print(">>> resuming parent")
            delegate_parent = parent_as_creator._get_transition_delegate_record()
            if hasattr(delegate_parent, "_workflow_resume_parallel_join"):
                resumed = delegate_parent.with_context(
                    workflow_skip_field_policy=True,
                    workflow_skip_owner_notify=True,
                )._workflow_resume_parallel_join(branch_node_id=self.parent_meta_node_id or False)
                if resumed:
                    return None
            if parent_as_creator.visible_buttons:
                parent_as_creator.action_do_transition(parent_as_creator.visible_buttons[0], show_dialog=False)
        else:
            print("-------------------- waiting: not all subprocesses complete ---------------------")
            # return None  # pause until all child are done

    def _to_plain_text(self, body):
        if not body:
            return ""
        try:
            return html.fromstring(str(body)).text_content().strip()
        except Exception:
            return str(body).strip()

    def _resolve_notification_recipients(self, meta_task, memo=False):
        base_request = self._resolve_base_request_record()
        return self.env["workflow.engine.assignment.domain.service"].resolve_notification_recipients(
            base_request,
            meta_task,
            memo=memo,
        )

    def _workflow_is_message_notification_node_type(self, node_type):
        return node_type in {
            NODE_TYPE["END_EVENT_WITH_MESSAGE"],
            NODE_TYPE["INTERMEDIATE_THROW_EVENT_WITH_MESSAGE"],
        }

    def _resolve_send_task_email_template(self, meta_task):
        if not meta_task or (
            meta_task.node_type != "sendTask"
            and not self._workflow_is_message_notification_node_type(meta_task.node_type)
        ):
            return self.env["mail.template"]
        return (
            meta_task.notification_email_template_id
            or meta_task.email_template_external_id
            or self.env["mail.template"]
        )

    def _workflow_email_addresses_from_users(self, users):
        addresses = set()
        for user in users or self.env["res.users"]:
            email = user.partner_id.email if user.partner_id else user.email
            normalized = email_normalize(email or "")
            if normalized:
                addresses.add(normalized)
        return sorted(addresses)

    def _workflow_split_raw_email_addresses(self, raw_emails):
        addresses = set()
        for token in re.split(r"[,;\n\r]+", raw_emails or ""):
            normalized = email_normalize((token or "").strip())
            if normalized:
                addresses.add(normalized)
        return sorted(addresses)

    def _workflow_resolve_action_email_recipient_line_details(
        self,
        line,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        service = self.env["workflow.engine.assignment.domain.service"]
        detail = {
            "header": line.header or "to",
            "source": line.source or "send_task",
            "domain": (line.domain or "").strip(),
            "node_ref": (line.node_ref or "").strip(),
            "node_user_type": line.node_user_type or "assigned",
            "approval_group_ids": line.approval_group_ids.ids,
            "group_ids": line.group_ids.ids,
            "configured_user_ids": line.user_ids.ids,
            "resolved_user_ids": [],
            "resolved_emails": [],
            "config_error": False,
            "error_message": "",
        }
        if line.source == "direct":
            detail["resolved_emails"] = self._workflow_split_raw_email_addresses(line.raw_emails)
            return detail
        if line.source == "send_task":
            detail["resolved_user_ids"] = send_task_recipients.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(send_task_recipients)
            return detail
        if line.source == "specific_users":
            users = line.user_ids.sudo()
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "approval_group_users":
            users = line.approval_group_ids.sudo().mapped("user_ids")
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "group_users":
            group_user_field = "user_ids" if "user_ids" in self.env["res.groups"]._fields else "users"
            users = line.group_ids.sudo().mapped(group_user_field)
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "node_users":
            users = service.node_approver_users(
                request_record,
                (line.node_ref or "").strip(),
                user_type=line.node_user_type or "assigned",
            )
            if users:
                users, domain_details = service.eval_routing_user_domain(
                    users,
                    detail["domain"],
                    request_record=request_record,
                    memo=memo,
                    return_details=True,
                )
                detail["config_error"] = bool(domain_details.get("config_error"))
                detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        if line.source == "domain":
            users, domain_details = service.eval_routing_user_domain(
                service._memoized_all_active_non_portal_users(memo),
                detail["domain"],
                request_record=request_record,
                memo=memo,
                return_details=True,
            )
            detail["config_error"] = bool(domain_details.get("config_error"))
            detail["error_message"] = domain_details.get("error_message") or ""
            detail["resolved_user_ids"] = users.ids
            detail["resolved_emails"] = self._workflow_email_addresses_from_users(users)
            return detail
        return detail

    def _workflow_resolve_action_email_recipient_line(
        self,
        line,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        return self._workflow_resolve_action_email_recipient_line_details(
            line,
            send_task_recipients,
            request_record,
            meta_task,
            memo=memo,
        )["resolved_emails"]

    def _workflow_build_action_email_values(self, action, send_task_recipients, request_record, meta_task):
        return self._workflow_build_action_email_payload(
            action,
            send_task_recipients,
            request_record,
            meta_task,
        )["email_values"]

    def _workflow_build_action_email_payload(
        self,
        action,
        send_task_recipients,
        request_record,
        meta_task,
        memo=False,
    ):
        recipient_lines = action.email_recipient_line_ids.sudo() if action else self.env["workflow.approval.action.email.recipient"]
        if not recipient_lines:
            to_addresses = self._workflow_email_addresses_from_users(send_task_recipients)
            return {
                "email_values": {"email_to": ",".join(to_addresses)} if to_addresses else None,
                "headers": {"to": to_addresses, "cc": [], "bcc": []},
                "recipient_lines": [
                    {
                        "header": "to",
                        "source": "send_task",
                        "domain": "",
                        "node_ref": "",
                        "node_user_type": "assigned",
                        "approval_group_ids": [],
                        "group_ids": [],
                        "configured_user_ids": [],
                        "resolved_user_ids": send_task_recipients.ids,
                        "resolved_emails": to_addresses,
                        "config_error": False,
                        "error_message": "",
                    }
                ],
            }

        headers = {"to": set(), "cc": set(), "bcc": set()}
        resolved_lines = []
        for line in recipient_lines:
            line_details = self._workflow_resolve_action_email_recipient_line_details(
                line,
                send_task_recipients,
                request_record,
                meta_task,
                memo=memo,
            )
            resolved_lines.append(line_details)
            for address in line_details["resolved_emails"]:
                headers.setdefault(line_details["header"], set()).add(address)
        email_values = {}
        if headers["to"]:
            email_values["email_to"] = ",".join(sorted(headers["to"]))
        if headers["cc"]:
            email_values["email_cc"] = ",".join(sorted(headers["cc"]))
        if headers["bcc"]:
            email_values["headers"] = repr({"Bcc": sorted(headers["bcc"])})
        return {
            "email_values": email_values or None,
            "headers": {key: sorted(values) for key, values in headers.items()},
            "recipient_lines": resolved_lines,
        }

    def _resolve_send_task_delivery_mode(self, meta_task):
        mode = getattr(meta_task, "notification_delivery_mode", False)
        if mode:
            return mode
        return "channels" if meta_task.sudo().activity_type_ids else "email"

    def _workflow_empty_notification_audit(self, delivery_mode, meta_task):
        return {
            "delivery_mode": delivery_mode or "",
            "node_id": meta_task.node_id if meta_task else "",
            "node_name": meta_task.name if meta_task else "",
            "entries": [],
        }

    def _send_task_template_email(self, meta_task, recipients, memo=False):
        if not meta_task:
            return None
        suppress_notifications = self._workflow_notifications_suppressed()
        audit = self._workflow_empty_notification_audit("email", meta_task)
        for rec in self:
            entry = {
                "status": "",
                "record_id": rec.id,
                "template_id": False,
                "template_name": "",
                "recipient_user_ids": recipients.ids,
                "recipient_emails": [],
            }
            if suppress_notifications:
                entry["status"] = "suppressed"
                audit["entries"].append(entry)
                continue
            task_email_template = rec._resolve_send_task_email_template(meta_task).sudo()
            if not task_email_template:
                entry["status"] = "skipped_no_template"
                audit["entries"].append(entry)
                continue
            entry["template_id"] = task_email_template.id
            entry["template_name"] = task_email_template.name or ""
            emails = rec._workflow_email_addresses_from_users(recipients)
            entry["recipient_emails"] = emails
            if not emails:
                entry["status"] = "skipped_no_recipients"
                audit["entries"].append(entry)
                continue
            sent = rec._workflow_safe_send_mail_template(
                template=task_email_template,
                render_record=rec,
                email_values={"email_to": ",".join(emails)},
                warning_label=meta_task.name or meta_task.node_id or _("send task notification"),
            )
            if sent:
                rec._workflow_grant_notification_read_scopes(
                    recipients,
                    reason="notification_recipient:%s" % (meta_task.node_id or meta_task.name or "send_task"),
                    request_record=rec._resolve_base_request_record(),
                )
                rec._workflow_safe_message_post(
                    body=f"Task email sent: {task_email_template.name}",
                    message_type='notification',
                    subtype_xmlid='mail.mt_note'
                )
                entry["status"] = "sent"
            else:
                entry["status"] = "failed"
            audit["entries"].append(entry)
        return {"notification_audit": audit}

    def _execute_send_task_log(self, meta_task):
        if not meta_task or self._workflow_notifications_suppressed():
            return None
        for rec in self:
            template = meta_task.activity_message_template
            body = False
            if template:
                body = template.sudo()._render_field('body_html', rec.ids).get(rec.id)
                body = Markup(body or "")
            rec._workflow_safe_message_post(
                body=body or f"Send task logged: {meta_task.name or meta_task.node_id}",
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
        return None

    def _execute_workflow_actions(self, meta_task, recipients=False, allow_template_fallback=True, memo=False):
        if not meta_task:
            return None
        recipients = recipients or self.env["res.users"]
        suppress_notifications = self._workflow_notifications_suppressed()
        action_pool = meta_task.sudo().activity_type_ids.sudo()
        partner_ids = recipients.mapped("partner_id").ids if recipients else []
        guard_cache = {}
        audit = self._workflow_empty_notification_audit("channels", meta_task)
        for rec in self:
            template = meta_task.activity_message_template
            html_template = False
            if template:
                html_template = template.sudo()._render_field('body_html', rec.ids).get(rec.id)
                html_template = Markup(html_template or "")
            plain_template = self._to_plain_text(html_template)
            task_email_template = rec._resolve_send_task_email_template(meta_task).sudo()
            if allow_template_fallback and not action_pool and task_email_template:
                entry = {
                    "action_id": False,
                    "action_name": task_email_template.name or "",
                    "action_type": "email",
                    "record_id": rec.id,
                    "guard_domain": "",
                    "guard_matched": True,
                    "status": "",
                    "template_id": task_email_template.id,
                    "template_name": task_email_template.name or "",
                    "recipient_lines": [],
                    "resolved_user_ids": recipients.ids,
                    "resolved_emails": [],
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                }
                if suppress_notifications:
                    entry["status"] = "suppressed"
                    audit["entries"].append(entry)
                    continue
                emails = sorted(
                    {
                        u.partner_id.email
                        for u in recipients
                        if u.partner_id and u.partner_id.email
                    }
                )
                entry["resolved_emails"] = emails
                entry["email_to"] = emails
                if emails:
                    task_email_template.send_mail(
                        rec.id,
                        force_send=False,
                        email_values={"email_to": ",".join(emails)},
                    )
                    rec._workflow_grant_notification_read_scopes(
                        recipients,
                        reason="notification_recipient:%s" % (meta_task.node_id or meta_task.name or "send_task"),
                        request_record=rec._resolve_base_request_record(),
                    )
                    rec._workflow_safe_message_post(
                        body=f"Task email sent: {task_email_template.name}",
                        message_type='notification',
                        subtype_xmlid='mail.mt_note'
                    )
                    entry["status"] = "sent"
                else:
                    entry["status"] = "skipped_no_recipients"
                audit["entries"].append(entry)
                continue
            for action in action_pool:
                audit_entry = {
                    "action_id": action.id,
                    "action_name": action.name or "",
                    "action_type": action.action_type or "",
                    "record_id": rec.id,
                    "guard_domain": action.domain or "",
                    "guard_matched": True,
                    "status": "",
                    "template_id": False,
                    "template_name": "",
                    "recipient_lines": [],
                    "resolved_user_ids": [],
                    "resolved_emails": [],
                    "email_to": [],
                    "email_cc": [],
                    "email_bcc": [],
                    "error_message": "",
                }
                if action.domain:
                    cache_key = (rec.id, action.id, action.domain)
                    if cache_key not in guard_cache:
                        guard_cache[cache_key] = rec.check_domain(action.domain, default=False)
                    audit_entry["guard_matched"] = bool(guard_cache[cache_key])
                    if not guard_cache[cache_key]:
                        audit_entry["status"] = "skipped_guard"
                        audit["entries"].append(audit_entry)
                        continue
                try:
                    match action.action_type:
                        case 'log':
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            rec._workflow_safe_message_post(
                                body=html_template or f"Action executed: {action.name}",
                                message_type='notification',
                                subtype_xmlid='mail.mt_note'
                            )
                            audit_entry["status"] = "sent"
                        case 'email':
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            email_template = action.email_template_id or task_email_template
                            if not email_template:
                                audit_entry["status"] = "skipped_no_template"
                                audit["entries"].append(audit_entry)
                                continue
                            audit_entry["template_id"] = email_template.id
                            audit_entry["template_name"] = email_template.name or ""
                            base_request = rec._resolve_base_request_record()
                            email_payload = rec._workflow_build_action_email_payload(
                                action,
                                recipients,
                                base_request,
                                meta_task,
                                memo=memo,
                            )
                            audit_entry["recipient_lines"] = email_payload["recipient_lines"]
                            audit_entry["resolved_user_ids"] = sorted(
                                {
                                    user_id
                                    for line_details in email_payload["recipient_lines"]
                                    for user_id in (line_details.get("resolved_user_ids") or [])
                                }
                            )
                            audit_entry["resolved_emails"] = sorted(
                                {
                                    address
                                    for line_details in email_payload["recipient_lines"]
                                    for address in (line_details.get("resolved_emails") or [])
                                }
                            )
                            audit_entry["email_to"] = email_payload["headers"].get("to", [])
                            audit_entry["email_cc"] = email_payload["headers"].get("cc", [])
                            audit_entry["email_bcc"] = email_payload["headers"].get("bcc", [])
                            email_values = email_payload["email_values"]
                            if not email_values:
                                audit_entry["status"] = "skipped_no_recipients"
                                audit["entries"].append(audit_entry)
                                continue
                            sent = email_template.sudo().send_mail(
                                rec.id, force_send=False, email_values=email_values
                            )
                            if sent:
                                recipient_users = self.env["res.users"].browse(
                                    audit_entry["resolved_user_ids"]
                                )
                                rec._workflow_grant_notification_read_scopes(
                                    recipient_users,
                                    reason="notification_recipient:%s"
                                    % (
                                        getattr(action, "node_id", False)
                                        or action.name
                                        or meta_task.node_id
                                        or meta_task.name
                                        or "email_action"
                                    ),
                                    request_record=base_request,
                                )
                                rec._workflow_safe_message_post(
                                    body=f"Action email sent: {action.name}",
                                    message_type='notification',
                                    subtype_xmlid='mail.mt_note'
                                )
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "failed"
                        case 'sms':
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            sms_body = action.message_body or plain_template or action.name or ""
                            if hasattr(rec, "_message_sms") and sms_body and partner_ids:
                                rec._message_sms(
                                    body=sms_body,
                                    partner_ids=partner_ids,
                                )
                                audit_entry["status"] = "sent"
                            else:
                                rec._workflow_safe_message_post(
                                    body=f"SMS action skipped (missing sms support/recipients/body): {action.name}",
                                    message_type='notification',
                                    subtype_xmlid='mail.mt_note'
                                )
                                audit_entry["status"] = "skipped_no_recipients"
                        case 'telegram':
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            endpoint = action.telegram_webhook_url or action.webhook_url
                            if endpoint:
                                payload = {
                                    "model": rec._name,
                                    "res_id": rec.id,
                                    "action_name": action.name,
                                    "message": action.message_body or plain_template or action.name,
                                    "recipient_ids": recipients.ids if recipients else [],
                                    "recipient_logins": recipients.mapped("login") if recipients else [],
                                }
                                requests.post(endpoint, json=payload, timeout=8)
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case 'webhook':
                            if suppress_notifications:
                                audit_entry["status"] = "suppressed"
                                audit["entries"].append(audit_entry)
                                continue
                            if action.webhook_url:
                                payload = {
                                    "model": rec._name,
                                    "res_id": rec.id,
                                    "action_name": action.name,
                                    "recipient_ids": recipients.ids if recipients else [],
                                }
                                requests.post(action.webhook_url, json=payload, timeout=8)
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case 'server_action':
                            if action.server_action_id:
                                action.server_action_id.sudo().with_context(
                                    active_model=rec._name,
                                    active_id=rec.id,
                                    active_ids=[rec.id],
                                    active_domain=[("id", "=", rec.id)],
                                ).run()
                                audit_entry["status"] = "sent"
                            else:
                                audit_entry["status"] = "skipped_no_template"
                        case _:
                            audit_entry["status"] = "sent"
                    if action.code:
                        env = {
                            'record': rec,
                            'self': self,
                            'env': self.env,
                            'recipients': recipients,
                        }
                        safe_eval(action.code, env, mode="exec")
                        audit_entry["status"] = audit_entry["status"] or "sent"
                except Exception as e:
                    audit_entry["status"] = "failed"
                    audit_entry["error_message"] = str(e)
                    rec._workflow_safe_message_post(
                        body=f"Action failed ({action.name}): {e}",
                        message_type='notification',
                        subtype_xmlid='mail.mt_note'
                    )
                audit["entries"].append(audit_entry)
        return {"notification_audit": audit}

    def _handle_send_task(self, meta_task, meta_action):
        if not meta_task:
            return None
        memo = {}
        recipients = self._resolve_notification_recipients(meta_task, memo=memo)
        delivery_mode = self._resolve_send_task_delivery_mode(meta_task)
        if delivery_mode == "log":
            return self._execute_send_task_log(meta_task)
        if delivery_mode == "channels":
            return self._execute_workflow_actions(
                meta_task,
                recipients=recipients,
                allow_template_fallback=False,
                memo=memo,
            )
        return self._send_task_template_email(meta_task, recipients, memo=memo)

    def _handle_script_task(self, meta_task, meta_action):
        if not meta_task:
            return None
        return self._execute_workflow_actions(meta_task)

    def _node_requires_assignment(self, engine, node):
        if node is None:
            return False
        node_type = engine.get_element_type(node)
        return node_type in [NODE_TYPE['USER_TASK'], NODE_TYPE['MANUAL_TASK'], NODE_TYPE['TASK']]

    def _build_existing_assignment_keys(self):
        self.ensure_one()
        open_statuses = {'new', 'pending', 'waiting'}
        return set(
            (
                a.user_id.id,
                a.current_meta_id.id,
                a.previous_meta_id.id or False,
                a.iteration_no or 1,
            )
            for a in self.approver_ids
            if a.status in open_statuses
        )

    def _preview_assignment_for_transition_stage(self, current_node, next_node):
        self.ensure_one()
        if next_node is None:
            return {"ready": True, "current_meta_task": False, "resolution": {}}

        current_meta_task = self._resolve_meta_task_for_node(
            next_node.attrib.get("id"),
            next_node.attrib.get("name"),
        )
        if not current_meta_task:
            return {"ready": True, "current_meta_task": False, "resolution": {}}

        if self._is_submission_meta_task(current_meta_task):
            return {"ready": True, "current_meta_task": current_meta_task, "resolution": {}}

        base_request = self._resolve_base_request_record()
        previous_meta_task = self._resolve_meta_task_for_node(
            current_node.attrib.get("id"),
            current_node.attrib.get("name"),
        ) if current_node is not None else False
        iteration_no = base_request.current_iteration_no or self._get_max_iteration_no() or 1

        adapter_service = self.env["workflow.engine.legacy.adapter.service"]
        preview = adapter_service.prepare_legacy_approver_rows(
            request_record=base_request,
            current_meta_task=current_meta_task,
            previous_meta_task=previous_meta_task,
            iteration_no=iteration_no,
            existing_keys=self._build_existing_assignment_keys(),
            eval_record=self if self._name != "workflow.base.approval.request" else None,
        )
        resolution = preview.get("resolution") or {}
        open_rows = self.approver_ids.filtered(
            lambda a: a.current_meta_id.id == current_meta_task.id
                      and (a.iteration_no or 1) == iteration_no
                      and a.status in ["new", "pending", "waiting"]
        )
        ready = bool((preview.get("approver_data_list") or []) or open_rows)
        return {
            "ready": ready,
            "current_meta_task": current_meta_task,
            "resolution": resolution,
        }

    def _build_blocked_transition_action(self, current_meta_task, resolution=False):
        self.ensure_one()
        adapter_service = self.env["workflow.engine.legacy.adapter.service"]
        blocked_reason = adapter_service.build_unassigned_stage_reason(
            current_meta_task=current_meta_task,
            resolution=resolution or {},
        )
        self._workflow_safe_message_post(
            body=blocked_reason,
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )
        base_request = self._resolve_base_request_record()
        should_notify_admins = not (
                base_request.wf_is_blocked
                and base_request.wf_block_reason == blocked_reason
        )
        base_request.sudo().with_context(wf_skip_block_sync=True).write({
            'wf_is_blocked': True,
            'wf_block_reason': blocked_reason,
        })
        if should_notify_admins:
            self._notify_missing_assignment_admins(
                base_request=base_request,
                current_meta_task=current_meta_task,
                blocked_reason=blocked_reason,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Workflow Blocked"),
                'message': blocked_reason,
                'type': 'warning',
                'sticky': True,
            }
        }

    def _notify_missing_assignment_admins(self, base_request, current_meta_task, blocked_reason):
        self.ensure_one()
        if not base_request:
            return
        users = self.env["res.users"]
        category = base_request.category_id
        if category and category.admin_queue_user_id:
            users |= category.admin_queue_user_id
        workflow_admin_group = self.env.ref(
            "workflow_engine.group_workflow_approval_admin",
            raise_if_not_found=False,
        )
        if workflow_admin_group:
            users |= workflow_admin_group.user_ids
        it_admin_group = self.env.ref("base.group_system", raise_if_not_found=False)
        if it_admin_group:
            users |= it_admin_group.user_ids
        partner_ids = list(dict.fromkeys(users.filtered(lambda u: u.active and not u.share).mapped("partner_id").ids))
        if not partner_ids:
            return

        stage_label = (
            current_meta_task.name
            if current_meta_task and current_meta_task.name
            else current_meta_task.node_id if current_meta_task else _("Unknown Stage")
        )
        request_label = base_request.display_name or base_request.name or _("Unknown Request")
        body = _(
            "Request %(request)s is blocked at stage '%(stage)s'. "
            "No approvers matched the assignment policy. "
            "Please update workflow approval configuration and ask the requester to submit again. "
            "Reason: %(reason)s"
        ) % {
                   "request": request_label,
                   "stage": stage_label,
                   "reason": blocked_reason,
               }
        subject = _("Workflow blocked: missing approver configuration")
        base_request._workflow_safe_message_notify(
            body=body,
            subject=subject,
            partner_ids=partner_ids,
        )

    def _precheck_next_stage_assignment(self, engine, current_node, next_node):
        self.ensure_one()
        if not self._node_requires_assignment(engine, next_node):
            return None

        preview = self._preview_assignment_for_transition_stage(current_node, next_node)
        if preview.get("ready"):
            base_request = self._resolve_base_request_record()
            if base_request.wf_is_blocked or base_request.wf_block_reason:
                base_request.sudo().write({
                    "wf_is_blocked": False,
                    "wf_block_reason": False,
                })
            return None
        return self._build_blocked_transition_action(
            current_meta_task=preview.get("current_meta_task"),
            resolution=preview.get("resolution"),
        )

    def _precheck_parallel_split_assignment(self, engine, split_node, form_data=None):
        self.ensure_one()
        branch_candidates = engine.get_next_elements(split_node, form_data=form_data)
        seen = set()
        for candidate in branch_candidates:
            for resolved in self._resolve_runtime_next_nodes(engine, candidate, form_data=form_data):
                node_id = resolved.attrib.get("id")
                if not node_id or node_id in seen:
                    continue
                seen.add(node_id)
                blocked_action = self._precheck_next_stage_assignment(
                    engine=engine,
                    current_node=split_node,
                    next_node=resolved,
                )
                if blocked_action:
                    return blocked_action
        return None

    def _workflow_process_actor_action(self, meta_action, execute_path=False):
        """Apply actor accounting before routing an interactive action."""
        if execute_path:
            return True
        return self._approve(meta_action)

    def _run_engine(self, form_data=None, meta_action_id=None, re_assign_approvals=True):
        self.ensure_one()
        # Engine-driven writes happen after the actor decision may already have
        # closed the current approver row. Those internal state transitions must
        # not be re-validated as end-user form edits.
        self = self.with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_notification_actor_user_id=(
                self.env.context.get("workflow_notification_actor_user_id")
                or self.env.user.id
            ),
        )

        engine = BpmnEngine(self.version_id.bpmn_xml)

        is_need_to_send_email = False
        meta_action = None
        if meta_action_id:
            meta_action = self.env['workflow.category.version.meta.task.action'].sudo().browse(meta_action_id)
            if not meta_action:
                raise UserError("Invalid meta_action_id.")
            self._workflow_validate_action_execution_guard(meta_action)
            is_need_to_send_email = meta_action.flow_type != ACTION_TYPE['NO_EMAIL_ACTION']

        # Step 1: Start flow if no current node
        if not self.current_node_id:
            return self._first_time_run(engine, form_data, meta_action, re_assign_approvals, is_need_to_send_email)

        # Step 2: Continue flow
        current_node_id = self.current_node_id
        if meta_action and meta_action.source_id:
            current_node_id = meta_action.source_id
        current_node = engine.get_element_by_id(current_node_id)
        if current_node is None:
            raise UserError("No valid current node found in BPMN.")

        # Step 3: Find next node based on meta_action
        if meta_action:
            is_execute_path_action = self._workflow_is_execute_path_action(meta_action)
            approval_recorded = False
            # Handle multiple approver case.
            if (
                not is_execute_path_action
                and (meta_action.authorization_mode or "approval_actor") == "approval_actor"
                and meta_action.approval_require_number > 1
            ):
                multi_approval_result = self._handle_multiple_approvers(current_node, meta_action)
                if multi_approval_result is False:
                    return None
                approval_recorded = multi_approval_result is True
            if self._workflow_is_runtime_v2() and meta_action.source_id and not is_execute_path_action:
                self._workflow_cancel_runtime_instances(
                    branch_node_id=meta_action.source_id,
                    reason=_("Cancelled by manual action '%s'.") % (meta_action.name or ""),
                )

            raw_next_node = engine.get_element_by_id(meta_action.target_id)
            if raw_next_node is None:
                raise UserError(f"Target node '{meta_action.target_id}' not found in BPMN.")

            if is_execute_path_action:
                self._workflow_process_actor_action(meta_action, execute_path=True)
                return self._workflow_execute_path_action(
                    engine=engine,
                    current_node=current_node,
                    start_node=raw_next_node,
                    form_data=form_data,
                    meta_action=meta_action,
                    re_assign_approvals=re_assign_approvals,
                    is_need_to_send_email=is_need_to_send_email,
                )

            active_parallel_branch = bool(
                self.active_branch_node_ids and meta_action.source_id in (self.active_branch_node_ids or [])
            )
            # Split-gateway precheck must happen before any approval is recorded.
            if self._is_split_gateway(engine, raw_next_node):
                if re_assign_approvals:
                    blocked_action = self._precheck_parallel_split_assignment(
                        engine=engine,
                        split_node=raw_next_node,
                        form_data=form_data,
                    )
                    if blocked_action:
                        return blocked_action
                if not self.env.context.get('no_approval') and not approval_recorded:
                    self._workflow_process_actor_action(meta_action)
                self._close_open_source_stage_approvers(current_node)
                split_result = self._process_parallel_split(
                    engine=engine,
                    split_node=raw_next_node,
                    previous_node=current_node,
                    meta_action=meta_action,
                    form_data=form_data,
                    re_assign_approvals=re_assign_approvals,
                    is_need_to_send_email=is_need_to_send_email,
                )
                if split_result.get("waiting"):
                    return None
                next_node = split_result.get("next_node")
            elif (
                self._workflow_is_runtime_v2()
                and not active_parallel_branch
                and engine.is_pass_through_node(raw_next_node)
            ):
                source_stage_node = current_node
                if not self.env.context.get('no_approval') and not approval_recorded:
                    self._workflow_process_actor_action(meta_action)
                transition_result = self._workflow_run_runtime_transition_path(
                    engine=engine,
                    current_node=current_node,
                    start_node=raw_next_node,
                    form_data=form_data,
                    re_assign_approvals=re_assign_approvals,
                    is_need_to_send_email=is_need_to_send_email,
                    meta_action=meta_action,
                    source_stage_node=source_stage_node,
                )
                next_node = transition_result.get("next_node")
                if next_node not in (None, False) and self.parent_id and engine.is_end_event(next_node):
                    self._handle_end_event_in_sub_process()
                if transition_result.get("waiting"):
                    return None
                if next_node not in (None, False) and engine.is_end_event(next_node):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _("Approved"),
                            'message': _("This request has reached the end of the workflow."),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                return None
            else:
                next_node = self._resolve_runtime_next_node(engine, raw_next_node, form_data=form_data)
                if next_node is None:
                    raise UserError(_("No executable node found after transition '%s'.") % (meta_action.name or ""))

                # Handle script task case.
                next_node_type = engine.get_element_type(next_node)
                if next_node_type == NODE_TYPE['SCRIPT_TASK']:
                    meta_task = self._resolve_meta_task_for_node(
                        next_node.attrib.get('id'),
                        next_node.attrib.get('name'),
                    )
                    return self._handle_script_task(meta_task, meta_action)

                # Handle service task.
                if next_node_type == NODE_TYPE['SERVICE_TASK']:
                    service_result = self._handle_service_task(
                        engine, form_data, meta_action, next_node, re_assign_approvals, is_need_to_send_email
                    )
                    if not service_result:
                        return None
                    next_node = service_result.get("next_node")
                    next_node = self._resolve_runtime_next_node(engine, next_node, form_data=form_data)
                    next_node_type = engine.get_element_type(next_node)

                if next_node_type == NODE_TYPE['SEND_TASK']:
                    meta_task = self._resolve_meta_task_for_node(
                        next_node.attrib.get('id'),
                        next_node.attrib.get('name'),
                    )
                    self._handle_send_task(meta_task, meta_action)
                    next_candidates = engine.get_next_elements(next_node, form_data=form_data)
                    next_node = self._resolve_runtime_next_node(
                        engine,
                        next_candidates[0] if next_candidates else None,
                        form_data=form_data,
                    )
                    if next_node is not None:
                        next_node_type = engine.get_element_type(next_node)

                if re_assign_approvals:
                    blocked_action = self._precheck_next_stage_assignment(
                        engine=engine,
                        current_node=current_node,
                        next_node=next_node,
                    )
                    if blocked_action:
                        return blocked_action

                # Handle call activity.
                if next_node_type == NODE_TYPE['CALL_ACTIVITY']:
                    self._handle_call_activity(engine, form_data, meta_action, current_node, next_node)
                # for not assign approval for migrate old data
                if not self.env.context.get('no_approval') and not approval_recorded:
                    self._workflow_process_actor_action(meta_action)

                source_node_id = current_node.attrib.get("id") if current_node is not None else False
                next_node_id = next_node.attrib.get("id") if next_node is not None else False
                if source_node_id and next_node_id and source_node_id != next_node_id:
                    self._close_open_source_stage_approvers(current_node)
                    
                if self.active_branch_node_ids and meta_action.source_id in (self.active_branch_node_ids or []):
                    branch_result = self._complete_parallel_branch_and_resolve(
                        engine=engine,
                        form_data=form_data,
                        meta_action=meta_action,
                    )
                    if branch_result.get("waiting"):
                        return None
                    if branch_result.get("join_node"):
                        current_node = branch_result.get("join_node")
                    next_node = branch_result.get("next_node") or next_node

            # Handle end event in sub process.
            if self.parent_id and engine.is_end_event(next_node):
                self._handle_end_event_in_sub_process()
        else:
            # fallback if no meta_action (legacy safety)
            transitions = engine.get_current_buttons(current_node)
            if len(transitions) == 0:
                raise UserError("No outgoing transitions found for the current node.")
            next_node = self._resolve_runtime_next_node(
                engine,
                transitions[0]['target_node'],
                form_data=form_data,
            )

        self._update_tracking_fields(engine=engine, form_data=form_data, current_node=current_node, next_node=next_node,
                                     meta_action=meta_action)

        # self.x_approval_base_id.cancel_activities()
        self.cancel_activities()
        if re_assign_approvals:
            self._assign_dynamic_approvers_from_meta(meta_action, current_node, next_node, is_need_to_send_email)
            self._workflow_post_activate_runtime_node(engine, next_node)

        if engine.is_end_event(next_node):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Approved"),
                    'message': _("This request has reached the end of the workflow."),
                    'type': 'success',
                    'sticky': False,
                }
            }

    def _siblings_completed(self):
        """Check if all siblings except self are completed."""
        parent = self.parent_id
        if not parent:
            return False

        child_requests = self.env['workflow.base.approval.request'].sudo().search([
            ('parent_id', '=', parent.id),
            ('execution_mode', '=', 'sync')
        ])
        if self.x_approval_base_id is None:
            return False
        return all(
            child.state == 'completed'
            for child in child_requests
            if child.id != self.x_approval_base_id.id
        )

    def _get_form_data(self):
        return {
            f.name: self[f.name]
            for f in self._fields.values()
            if not f.compute and not f.related and f.store and f.name.startswith('x_')
        }

    def _resolve_runtime_next_node(
            self,
            engine,
            node,
            form_data=None,
            max_hops=60,
            preserve_side_effect_nodes=False,
    ):
        """
        Resolve pass-through BPMN elements (gateways/events) to the next executable node.
        """
        current = node
        visited = set()
        hops = 0
        while (
            current is not None
            and not engine.is_end_event(current)
            and engine.is_pass_through_node(current)
            and not (
                preserve_side_effect_nodes
                and self._workflow_is_message_notification_node_type(engine.get_element_type(current))
            )
        ):
            node_id = current.attrib.get("id")
            if not node_id:
                break
            if node_id in visited:
                raise UserError(_("Infinite BPMN routing loop detected at node '%s'.") % node_id)
            visited.add(node_id)
            hops += 1
            if hops > max_hops:
                raise UserError(_("BPMN routing exceeded maximum hops (%s).") % max_hops)
            next_nodes = self._workflow_get_next_elements(engine, current, form_data=form_data)
            if not next_nodes:
                break
            current = next_nodes[0]
        return current

    def _resolve_runtime_transition_entry_node(
            self,
            engine,
            node,
            form_data=None,
            max_hops=60,
            preserve_side_effect_nodes=False,
    ):
        """
        Resolve pass-through nodes for a transition path while preserving split
        gateways so the runtime branch executor can fan out correctly.
        """
        current = node
        visited = set()
        hops = 0
        while (
            current is not None
            and not engine.is_end_event(current)
            and engine.is_pass_through_node(current)
            and not (
                preserve_side_effect_nodes
                and self._workflow_is_message_notification_node_type(engine.get_element_type(current))
            )
        ):
            if self._is_split_gateway(engine, current):
                return current
            node_id = current.attrib.get("id")
            if not node_id:
                break
            if node_id in visited:
                raise UserError(_("Infinite BPMN routing loop detected at node '%s'.") % node_id)
            visited.add(node_id)
            hops += 1
            if hops > max_hops:
                raise UserError(_("BPMN routing exceeded maximum hops (%s).") % max_hops)
            next_nodes = self._workflow_get_next_elements(engine, current, form_data=form_data)
            if not next_nodes:
                break
            current = next_nodes[0]
        return current

    def _expand_approver_data_with_cc_delegation(
            self,
            approver_data_list,
            current_meta_task,
            previous_meta_task,
            iteration_no,
    ):
        """Append delegated approver rows for keep-assignee delegation strategy."""
        self.ensure_one()
        if not approver_data_list:
            return approver_data_list

        base_request = self._resolve_base_request_record()
        delegation_model = self.env["workflow.approval.delegation"].sudo()
        now = fields.Datetime.now()
        previous_meta_id = previous_meta_task.id if previous_meta_task else False

        existing_keys = set(
            (
                a.user_id.id,
                a.current_meta_id.id,
                a.previous_meta_id.id or False,
                a.iteration_no or 1,
            )
            for a in self.approver_ids
            if a.status in ['new', 'pending', 'waiting']
        )
        for row in approver_data_list:
            existing_keys.add(
                (
                    row.get("user_id"),
                    row.get("current_meta_id"),
                    row.get("previous_meta_id") or False,
                    row.get("iteration_no") or 1,
                )
            )

        delegated_rows = []
        for row in list(approver_data_list):
            original_user_id = row.get("user_id")
            if not original_user_id:
                continue

            delegations = delegation_model.search(
                [
                    ("delegator_user_id", "=", original_user_id),
                    ("active", "=", True),
                    ("date_from", "<=", now),
                    ("date_to", ">=", now),
                    ("assignment_strategy", "=", "cc_delegate"),
                ],
                order="date_from desc, id desc",
            )
            delegation = delegations.select_best_for_category(base_request.category_id)
            if not delegation:
                continue

            delegate_user = delegation.delegate_user_id
            if not delegate_user or not delegate_user.active or delegate_user.share:
                continue
            if delegate_user.id == original_user_id:
                continue

            row_iteration = row.get("iteration_no") or iteration_no or 1
            delegate_key = (
                delegate_user.id,
                current_meta_task.id,
                previous_meta_id,
                row_iteration,
            )
            if delegate_key in existing_keys:
                continue

            delegator_name = self.env["res.users"].browse(original_user_id).name or _("Unknown User")
            delegation_note = _(
                "Delegated from %(delegator)s (OOO %(from_dt)s -> %(to_dt)s).",
                delegator=delegator_name,
                from_dt=fields.Datetime.to_string(delegation.date_from),
                to_dt=fields.Datetime.to_string(delegation.date_to),
            )
            delegated_row = dict(row)
            delegated_row["user_id"] = delegate_user.id
            delegated_row["delegated_from_user_id"] = original_user_id
            delegated_row["remark"] = delegation_note
            delegated_rows.append(delegated_row)
            existing_keys.add(delegate_key)

        if delegated_rows:
            approver_data_list.extend(delegated_rows)
        return approver_data_list

    def _assign_dynamic_approvers_from_meta(self, meta_action, current_node, next_node, is_need_to_send_mail):
        """"
        After action is clicked, this function is called to calculate the approver list of the next stage.

        current_node: current node
        next_node: next node
        is_need_to_send_mail: a flag to tell if need to send email
        """
        self.ensure_one()
        if not self.version_id:
            return
        # Suppress block-sync for the entire method.  Several intermediate writes
        # happen here (close_approver, create rows, approver_ids +=) before the new
        # stage approver rows are fully committed.  Running the sync mid-way sees
        # zero open rows and incorrectly sets a block.  We trigger it exactly once
        # at the end via _sync_blocked_state_from_approvers on the base request.
        self = self.with_context(wf_skip_block_sync=True)

        # if self._name == "workflow.base.approval.request":
        #     request_id = self.id
        # else:
        #     request_id = self.x_approval_base_id.id

        base_request = self._resolve_base_request_record()

        current_meta_task = self._resolve_meta_task_for_node(
            next_node.attrib.get('id'),
            next_node.attrib.get('name'),
        )
        if not current_meta_task:
            return

        previous_meta_task = self._resolve_meta_task_for_node(
            current_node.attrib.get('id'),
            current_node.attrib.get('name'),
        )

        # Prepare new approvers
        approver_data_list = []
        assignment_resolution = {}

        active_iteration_no = self._resolve_iteration_for_action(current_node.attrib['id'])
        is_submission_stage = self._is_submission_meta_task(current_meta_task)
        iteration_no = self._resolve_iteration_for_next_stage(
            is_submission_stage=is_submission_stage,
            previous_meta_task=previous_meta_task,
            current_meta_task=current_meta_task,
            meta_action=meta_action,
        )

        # Avoid duplicates only inside the same iteration + stage pair.
        # For a same-stage loop (for example Notify -> sendTask -> current
        # userTask), the open rows on the target stage are about to be closed
        # below. They must not suppress creation of the fresh assignment row,
        # otherwise the user cannot click the same action repeatedly.
        is_same_stage_reentry = bool(
            previous_meta_task
            and current_meta_task
            and previous_meta_task.id == current_meta_task.id
        )
        existing_keys = set(
            (
                a.user_id.id,
                a.current_meta_id.id,
                a.previous_meta_id.id or False,
                a.iteration_no or 1,
            )
            for a in self.approver_ids
            if a.status in ['new', 'pending', 'waiting']
            and not (
                is_same_stage_reentry
                and a.current_meta_id.id == current_meta_task.id
                and (a.iteration_no or 1) == iteration_no
            )
        )

        # Update status close for admin force activities
        if self.env.context.get('force_transit') and self.env.context.get('res_asign_user_req'):
            self.close_approver(
                previous_meta_task,
                iteration_no=active_iteration_no,
                include_current_user=True,
                decision_if_blank=_("Routed"),
                comment_if_blank=(self.env.context.get("force_transition_comment") or False),
            )

        # for reset current approver status to new when re-assigning to submit only
        if self.env.context.get('re_submit') and self.env.context.get('res_asign_user_req'):
            target_node_id = current_meta_task.node_id if current_meta_task else False
            reusable_rows = self.approver_ids.filtered(
                lambda a: a.current_meta_node_id == target_node_id
                          and (a.iteration_no or 1) == iteration_no
                          and not a.user_decision
            )
            if reusable_rows:
                reusable_rows.sudo().write({
                    'status': 'new',
                })
                return None

        # set approver to closed for previous meta task, if he is not the one who approved.
        # self.x_approval_base_id.close_approver(previous_meta_task)
        self.close_approver(previous_meta_task, iteration_no=active_iteration_no)

        if self.state != 'completed':
            if is_submission_stage:
                # Submission stage must be assigned to the submission assignee.
                submitter = self._get_submission_assignee(previous_meta_task, current_meta_task.node_id)[:1]
                if not submitter or not submitter.exists():
                    submitter = (self.request_owner_id or self.create_uid or self.env.user)[:1]

                if submitter:
                    # Keep exactly one active submission assignee row without decision.
                    submission_active_rows = self.approver_ids.filtered(
                        lambda a: a.current_meta_node_id == current_meta_task.node_id
                                  and (a.iteration_no or 1) == iteration_no
                                  and a.status in ['new', 'pending', 'waiting']
                    )
                    reusable_row = submission_active_rows.filtered(
                        lambda a: a.user_id.id == submitter.id and not a.user_decision
                    )[:1]
                    rows_to_close = submission_active_rows - reusable_row
                    if rows_to_close:
                        rows_to_close.sudo().write({'status': 'closed'})

                    if reusable_row:
                        if reusable_row.status != 'new':
                            reusable_row.sudo().write({'status': 'new'})
                    else:
                        approver_data_list.append({
                            'user_id': submitter.id,
                            'status': 'new',
                            'required': True,
                            'sequence': 10,
                            'iteration_no': iteration_no,
                            'request_id': base_request.id,
                            'current_meta_id': current_meta_task.id,
                            'previous_meta_id': previous_meta_task.id if previous_meta_task else False,
                            'remark': _("Submission owner for stage '%s'") % (
                                    current_meta_task.name or 'Unknown Stage'
                            ),
                        })

                # Ensure request owner is follower when different from creator.
                self._subscribe_request_owner_if_needed()
            else:
                adapter_service = self.env["workflow.engine.legacy.adapter.service"]
                assignment_result = adapter_service.prepare_legacy_approver_rows(
                    request_record=base_request,
                    current_meta_task=current_meta_task,
                    previous_meta_task=previous_meta_task,
                    iteration_no=iteration_no,
                    existing_keys=existing_keys,
                    # Pass the child record so link.domain expressions that reference
                    # child-model fields (e.g. x_it_session_id) are evaluated correctly.
                    # The base request does not carry these fields.
                    eval_record=self if self._name != "workflow.base.approval.request" else None,
                )
                assignment_resolution = assignment_result.get("resolution") or {}
                approver_data_list.extend(assignment_result.get("approver_data_list") or [])

        # Add approval for subprocess status
        if current_meta_task.node_type == NODE_TYPE['CALL_ACTIVITY']:
            # prevent from showing button submit: closed
            for item in approver_data_list:
                item['status'] = 'closed'
            approver_data_list.append({
                'user_id': 1,
                'status': 'new',
                'required': True,
                'sequence': 10,
                'iteration_no': iteration_no,
                'request_id': base_request.id,
                'current_meta_id': current_meta_task.id,
                'previous_meta_id': previous_meta_task.id if previous_meta_task else False,
                'remark': _("System approval to track subprocess '%s'") % (current_meta_task.name or 'Unknown Stage'),
            })

        # -------------------------------------------
        # ⭐ ADD APPROVERS FROM PARENT ACTIVITY, TO SUB WORKFLOW FOR ABLE TO VIEW RECORD
        # -------------------------------------------
        parent_request = False
        # if getattr(self, "x_approval_base_id", False):
        #     parent_request = self.x_approval_base_id.parent_id
        # else:
        #     parent_request = self.parent_id
        parent_request = self.x_approval_base_id.parent_id

        if self.env.context.get('auto_subworkflow_submit'):
            # and self.previous_activity_name in ["Submit", "Submission"]
            if parent_request:
                parent_request_sudo = parent_request.sudo()
                parent_meta = self.env['workflow.category.version.meta.task'].sudo().search([
                    ('node_id', '=', parent_request_sudo.current_node_id)
                ], limit=1)

                parent_approvals = parent_meta.sudo().approval_group_link_ids
                # 3. Add every mapped user to the approval list
                for pa in parent_approvals:
                    for usr in pa.user_ids:
                        approver_data_list.append({
                            'user_id': usr.id,
                            'status': 'closed',
                            'required': False,
                            'sequence': 1,
                            'iteration_no': iteration_no,
                            'request_id': base_request.id,
                            'current_meta_id': current_meta_task.id,  # sub workflow node
                            'previous_meta_id': previous_meta_task.id if previous_meta_task else False,
                            'remark': _("Inherited approval from parent activity '%s'") % (parent_meta.name),
                        })

        # 🧾 Assign and notify
        approver_data_list = self._expand_approver_data_with_cc_delegation(
            approver_data_list=approver_data_list,
            current_meta_task=current_meta_task,
            previous_meta_task=previous_meta_task,
            iteration_no=iteration_no,
        )

        existing_open_rows = self.approver_ids.filtered(
            lambda a: a.current_meta_id.id == current_meta_task.id
                      and (a.iteration_no or 1) == iteration_no
                      and a.status in ['new', 'pending', 'waiting']
        )

        if approver_data_list or existing_open_rows:
            # Clear previous blocked marker once at least one approver is resolved.
            if base_request.wf_is_blocked or base_request.wf_block_reason:
                base_request.sudo().write({
                    'wf_is_blocked': False,
                    'wf_block_reason': False,
                })

            if approver_data_list:
                # --- Update existing approved approvers (same node + user) ---
                for data in approver_data_list:
                    user_id = data.get('user_id')
                    current_node_id = data.get('current_meta_id')

                    if user_id and current_node_id:
                        existing_approved = self.env['workflow.approval.approver'].sudo().search([
                            ('request_id', '=', base_request.id),
                            ('user_id', '=', user_id),
                            ('current_meta_id', '=', current_node_id),
                            ('status', '=', 'approved')
                        ])
                        if existing_approved:
                            existing_approved.write({'verified_version': 2})
                            _logger.info(
                                "Updated verified_version=2 for existing approved approver(s): user=%s, node=%s",
                                user_id, current_node_id
                            )

                new_approvers = self.env['workflow.approval.approver'].sudo().create(approver_data_list)

                # The approver rows are already linked through request_id on the
                # sudo-created records above. Writing approver_ids again from the
                # child request can fail after the workflow has already advanced
                # to the next stage and the current actor no longer has edit
                # access on that new stage. Refresh caches instead of issuing a
                # second relational write.
                if "approver_ids" in base_request._fields:
                    base_request.invalidate_recordset(["approver_ids"])
                if "approver_ids" in self._fields:
                    self.invalidate_recordset(["approver_ids"])
                if not current_meta_task.is_end_node and not self._workflow_notifications_suppressed():
                    new_approvers._create_activity()

                # 📧 Send email notification
                if (
                    current_meta_task.email_template_external_id
                    and is_need_to_send_mail
                    and not self._workflow_notifications_suppressed()
                ):
                    self._notify_approvers_by_email(new_approvers, current_meta_task)
        # End nodes have no approvers by design — do not block.
        elif not current_meta_task.is_end_node:
            adapter_service = self.env["workflow.engine.legacy.adapter.service"]
            blocked_reason = adapter_service.build_unassigned_stage_reason(
                current_meta_task=current_meta_task,
                resolution=assignment_resolution,
            )

            # 📭 Post message if no user matched
            self._workflow_safe_message_post(
                body=blocked_reason,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            base_request.sudo().with_context(wf_skip_block_sync=True).write({
                'wf_is_blocked': True,
                'wf_block_reason': blocked_reason,
            })
            self._notify_missing_assignment_admins(
                base_request=base_request,
                current_meta_task=current_meta_task,
                blocked_reason=blocked_reason,
            )

        # Run the sync exactly once now that all approver rows are in place.
        # wf_skip_block_sync was active throughout to prevent premature blocks.
        base_request.sudo().with_context(wf_skip_block_sync=False)._sync_blocked_state_from_approvers()
        self._workflow_send_owner_update_notification(current_meta_task=current_meta_task)

    def _resolve_approver_status_from_action(self, action_name):
        """
        Map action label to approver status.
        Decision audit rows should reflect terminal intent for reporting.
        """
        name = (action_name or "").strip().lower()
        if "refuse" in name or "reject" in name:
            return "refused"
        if "cancel" in name:
            return "cancelled"
        return "approved"

    def _approve(self, meta_action):
        """
        To approve a request

        :param engine: engine to be used
        :param meta_action: current action
        :param approver: approver
        """
        # check if the login user can click buttons on or not
        # self.x_approval_base_id.ensure_can_approve()
        self.ensure_can_approve(meta_action)

        for request in self:

            # if request._name == "workflow.base.approval.request":
            #     request_id = request.id
            # else:
            #     request_id = request.x_approval_base_id.id

            base_request = request._resolve_base_request_record()
            active_iteration_no = request._resolve_iteration_for_action(meta_action.source_id)
            decision_status = request._resolve_approver_status_from_action(meta_action.name)
            open_current_actor_rows = request.approver_ids.filtered(
                lambda a: a.user_id == self.env.user
                          and a.current_meta_id == meta_action.meta_task_id
                          and (a.iteration_no or 1) == active_iteration_no
                          and a.status in ['new', 'pending', 'waiting']
            )

            source_meta_task = request._resolve_meta_task_for_node(
                meta_action.source_id,
                meta_action.source_name,
            )
            is_submission_action = bool(source_meta_task) and request._is_submission_meta_task(source_meta_task)

            if is_submission_action:
                request._workflow_assign_submission_folio_if_needed(source_meta_task)
                # Submission logic:
                # 1) If actor already has open row on submission node -> update it.
                # 2) If actor is different from assigned open rows -> close those rows and add actor audit row.
                open_submission_rows = request.approver_ids.filtered(
                    lambda a: a.user_id == self.env.user
                              and a.current_meta_node_id == meta_action.source_id
                              and (a.iteration_no or 1) == active_iteration_no
                              and a.status in ['new', 'pending', 'waiting']
                              and not a.user_decision
                )
                approver_rec = open_submission_rows[:1]

                all_open_submission_rows = request.approver_ids.filtered(
                    lambda a: a.current_meta_node_id == meta_action.source_id
                              and (a.iteration_no or 1) == active_iteration_no
                              and a.status in ['new', 'pending', 'waiting']
                )

                if approver_rec:
                    (all_open_submission_rows - approver_rec).sudo().write({'status': 'closed'})
                    approver_rec.write({
                        'status': 'closed',
                        'user_decision': meta_action.name,
                        'comment': request.comment or '',
                    })
                else:
                    if all_open_submission_rows:
                        all_open_submission_rows.sudo().write({'status': 'closed'})

                    canonical_meta = source_meta_task or all_open_submission_rows[:1].current_meta_id
                    previous_meta_id = request._resolve_meta_task_for_node(
                        request.previous_node_id,
                        request.previous_activity_name,
                    ) or canonical_meta

                    approver_rec = self.env['workflow.approval.approver'].create({
                        'user_id': self.env.user.id,
                        'status': 'closed',
                        'user_decision': meta_action.name,
                        'required': True,
                        'sequence': 10,
                        'iteration_no': active_iteration_no,
                        'request_id': base_request.id,
                        'previous_meta_id': previous_meta_id.id,
                        'current_meta_id': canonical_meta.id,
                        'remark': _("Submission by '%s'") % (self.env.user.name,),
                        'comment': request.comment or '',
                    })
            elif request._workflow_user_is_on_behalf_admin(user=self.env.user) and not open_current_actor_rows:
                # If workflow/category admin acts on behalf, add an explicit audit row.
                previous_meta_id = request._resolve_meta_task_for_node(
                    meta_action.source_id,
                    meta_action.source_name,
                )
                if not previous_meta_id:
                    raise ValidationError(
                        f"Previous Meta Task: there is no meta task by node id: {meta_action.source_id}")

                current_meta_task_id = request._resolve_meta_task_for_node(
                    meta_action.target_id,
                    meta_action.target_name,
                    prefer_submission='rework' in (meta_action.name or '').lower(),
                )
                if not current_meta_task_id:
                    raise ValidationError(
                        f"Current Meta Task: there is no meta task by node id: {meta_action.target_id}")

                approver_rec = self.env['workflow.approval.approver'].create({
                    'user_id': self.env.user.id,
                    'status': decision_status,
                    'user_decision': meta_action.name,
                    'required': False,
                    'sequence': 1,
                    'iteration_no': active_iteration_no,
                    'request_id': base_request.id,
                    'previous_meta_id': previous_meta_id.id,
                    'current_meta_id': current_meta_task_id.id,
                    'remark': _("workflow admin on behalf: %s acted on request: %s")
                              % (self.env.user.name, request.name),
                    'comment': request.comment or ''
                })
            else:
                # if not, just update the existing approver
                approver_rec = open_current_actor_rows[:1]

                if not approver_rec:
                    return

                approver_rec.write({
                    'status': decision_status,
                    'user_decision': meta_action.name,
                    'comment': request.comment or ''
                })

            # cleanup, example: set comment on request to empty
            self._cleanup_fields_after_approve(request)

            # Move to next approvers
            request.sudo()._update_next_approvers('pending', approver_rec, only_next_approver=True)
            request.sudo()._get_user_approval_activities(user=self.env.user).action_feedback()

    def _update_next_approvers(self, new_status, approver, only_next_approver, cancel_activities=False):
        approvers_updated = self.env['workflow.approval.approver']
        for approval in self.filtered('approver_sequence'):
            current_approver = approval.approver_ids & approver
            current_approver = current_approver[:1]
            if not current_approver:
                continue

            iteration_no = current_approver.iteration_no or approval.current_iteration_no or 1
            approvers_to_update = approval.approver_ids.filtered(
                lambda a: (a.iteration_no or 1) == iteration_no
                          and a.status in ['new', 'waiting']
                          and (
                                  a.sequence > current_approver.sequence
                                  or (a.sequence == current_approver.sequence and a.id > current_approver.id)
                          )
            )

            if only_next_approver and approvers_to_update:
                approvers_to_update = approvers_to_update[0]
            approvers_updated |= approvers_to_update

        approvers_updated.sudo().status = new_status
        if new_status == 'pending' and not self._workflow_notifications_suppressed():
            approvers_updated._create_activity()
        if cancel_activities:
            # approvers_updated.request_id.x_approval_base_id.cancel_activities()
            approvers_updated.request_id.cancel_activities()

    def _get_user_approval_activities(self, user):
        activities = []
        mail_activity_type = self.env.ref('workflow_engine.mail_activity_data_workflow_approval')
        domain = [
            ('res_model', '=', self.res_model_name),
            ('res_id', 'in', self.ids),
            ('activity_type_id', '=', mail_activity_type.id),
            ('user_id', '=', user.id)
        ]
        activities = self.env['mail.activity'].search(domain)
        return activities

    def _cleanup_fields_after_approve(self, request):
        """
        clean up some fields before next stage
        """
        request.sudo().with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
        ).write({
            'comment': '',
        })
        request.invalidate_recordset(["comment"])

    def _get_state_label_from_selected(self, selection_field_name, selected_key):
        return dict(self.env["workflow.base.approval.request"]._fields[selection_field_name].selection).get(
            selected_key)

    def _notify_approvers_by_email(self, new_approvers, meta_task):
        self.ensure_one()
        if self._workflow_notifications_suppressed():
            return
        template = meta_task.email_template_external_id
        if not template:
            return

        for approver in new_approvers:
            partner = approver.user_id.partner_id
            email = partner.email if partner else None

            if not email:
                message = Markup("<p class='text-warning'>%s <b>%s</b></p>") % (
                    _("Could not send email to User %s: missing email address."), approver.user_id.name
                )

                self._workflow_safe_message_post(
                    body=message,
                    message_type='notification',
                    subtype_xmlid='mail.mt_note'
                )
                continue

            try:

                self._workflow_safe_message_post(
                    body=_("Request is sent to %s") % (approver.name),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )

                template.with_context(
                    lang=approver.user_id.lang or 'en_US',
                    user=approver.user_id,
                    user_name=approver.user_id.name,
                    partner=partner,
                    request=self,
                ).send_mail(
                    self.id,
                    email_values={
                        'email_to': email,
                    },
                    force_send=False,
                    raise_exception=True,  # Useful in dev/test to debug template errors
                )
            except Exception as e:
                _logger.error(_("Failed to send email to %s: %s") % (approver.user_id.name, str(e)))
                # self.message_post(
                #     body=_("Failed to send email to %s: %s") % (approver.user_id.name, str(e)),
                #     message_type='comment',
                #     subtype_xmlid='mail.mt_note'
                # )

    def _category_count_recompute(self):
        """Recompute category counters safely across old/new counter implementations."""
        for rec in self:
            category = rec.category_id
            if not category:
                continue

            # New implementation in workflow_approval_category.py
            if hasattr(category, "_compute_request_stats"):
                category._compute_request_stats()
                continue

            # Backward-compatibility with older split compute methods.
            for method_name in (
                    "_compute_request_all_count",
                    "_compute_request_waiting_count",
                    "_compute_request_completed_count",
                    "_compute_request_tosubmit_count",
            ):
                method = getattr(category, method_name, None)
                if callable(method):
                    method()

    def action_move_transition(self, meta_action_id, re_assign_approvals):
        self.ensure_one()
        if meta_action_id is None:
            raise UserError("Node ID not found in BPMN.")

        return self._run_engine(
            form_data=self._get_form_data(),
            meta_action_id=meta_action_id,
            re_assign_approvals=re_assign_approvals
        )

    def _resolve_force_transition_meta_action(self, target_node_id):
        """Pick a deterministic transition action for force-jump bookkeeping."""
        self.ensure_one()
        Action = self.env["workflow.category.version.meta.task.action"].sudo()
        if not self.version_id or not target_node_id:
            return Action.browse()

        base_domain = [
            ("version_id", "=", self.version_id.id),
            ("target_id", "=", target_node_id),
        ]
        if self.current_node_id:
            return Action.search(base_domain + [("source_id", "=", self.current_node_id)], limit=1)
        return Action.search(base_domain, order="id", limit=1)

    def _force_jump_without_meta_action(self, engine, next_node, re_assign_approvals, audit_comment=False):
        """
        Fallback path when no metadata action maps to the target node.
        Force transition must still move the request and reassign approvers.
        """
        self.ensure_one()
        self = self.with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_allow_runtime_tracking_write=True,
        )
        current_node = engine.get_element_by_id(self.current_node_id) if self.current_node_id else None
        if current_node is None:
            current_node = engine.get_start_event()
        if current_node is None:
            raise UserError(_("No valid current node found for force transition."))

        source_node_ids = list(
            dict.fromkeys(
                node_id
                for node_id in [self.current_node_id, *(self.active_branch_node_ids or [])]
                if node_id
            )
        )
        runtime_v2 = self._workflow_is_runtime_v2()
        for source_node_id in source_node_ids:
            source_iteration_no = self._resolve_iteration_for_action(source_node_id)
            self._workflow_close_runtime_branch(
                source_node_id,
                reason=_("Closed by forced transition override."),
                iteration_no=source_iteration_no,
                decision_if_blank=_("Routed"),
                comment_if_blank=audit_comment or False,
            )
            if runtime_v2:
                self._workflow_cancel_runtime_instances(
                    branch_node_id=source_node_id,
                    reason=_("Cancelled by forced transition override."),
                )

        self._clear_active_branch_state()
        form_data = self._get_form_data()
        self._update_tracking_fields(
            engine=engine,
            form_data=form_data,
            current_node=current_node,
            next_node=next_node,
            meta_action=False,
        )
        self.cancel_activities()
        if re_assign_approvals:
            self._assign_dynamic_approvers_from_meta(
                meta_action=False,
                current_node=current_node,
                next_node=next_node,
                is_need_to_send_mail=False,
            )
        self._workflow_post_activate_runtime_node(engine, next_node)
        if engine.is_end_event(next_node):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Approved"),
                    'message': _("This request has reached the end of the workflow."),
                    'type': 'success',
                    'sticky': False,
                }
            }
        return None

    def action_force_transition(self, target_node_id, re_assign_approvals, audit_comment=False):
        self.ensure_one()
        audit_comment = (audit_comment or "").strip()
        engine = BpmnEngine(self.version_id.bpmn_xml)
        ActionModel = self.env["workflow.category.version.meta.task.action"].sudo()
        target_node_code = target_node_id["code"] if target_node_id else False
        next_node = engine.get_element_by_id(target_node_code)
        if next_node is None:
            raise UserError("Node ID not found in BPMN.")
        current_node = engine.get_element_by_id(self.current_node_id) if self.current_node_id else None
        if current_node is None:
            current_node = engine.get_start_event()
        target_label = (
            (target_node_id["name"] if target_node_id and target_node_id["name"] else "")
            or (next_node.attrib.get("name") or "")
        ).strip()
        re_submit = self._should_reset_request_to_submit_on_entry(
            engine=engine,
            current_node=current_node,
            next_node=next_node,
        )
        meta_action = self._resolve_force_transition_meta_action(next_node.attrib.get("id"))
        if self.active_branch_node_ids:
            meta_action = ActionModel.browse()
        elif meta_action and self.current_node_id and (meta_action.source_id or "") != self.current_node_id:
            meta_action = ActionModel.browse()

        from_label = self.current_activity_name or self.previous_activity_name or _("Unknown")
        to_label = target_label or _("Unknown")
        body = Markup(
            "<p class='text-warning'>⚠ <b>%s</b> manually forced transition "
            "from <span class='text-danger'><i>%s</i></span> to "
            "<span class='text-success'><i>%s</i></span></p>"
        ) % (
                   _("Admin Override:"),
                   from_label,
                   to_label,
               )

        if audit_comment:
            body += Markup("<p><b>%s</b> %s</p>") % (
                _("Comment:"),
                html_escape(audit_comment),
            )

        form_rec = self.with_context(
            force_transit=True,
            res_asign_user_req=re_assign_approvals,
            re_submit=re_submit,
            force_transition_comment=audit_comment,
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
            workflow_allow_runtime_tracking_write=True,
        )

        form_rec._workflow_safe_message_post(
            body=body,
            message_type="comment",
        )
        result = False
        if meta_action:
            result = form_rec._run_engine(
                form_data=form_rec._get_form_data(),
                meta_action_id=meta_action.id,
                re_assign_approvals=re_assign_approvals
            )
        else:
            result = form_rec._force_jump_without_meta_action(
                engine=engine,
                next_node=next_node,
                re_assign_approvals=re_assign_approvals,
                audit_comment=audit_comment,
            )
        audit_request = False
        resolve_base_request = getattr(self, "_resolve_base_request_record", None)
        if callable(resolve_base_request):
            audit_request = resolve_base_request()
        else:
            resolve_request_record = getattr(self, "_workflow_resolve_request_record", None)
            if callable(resolve_request_record):
                audit_request = resolve_request_record()
        if audit_request:
            self.env["workflow.engine.audit.service"].log_event(
                request_record=audit_request,
                event_type="admin_override",
                action_key=_("Force Transition"),
                from_node_id=current_node.attrib.get("id") if current_node is not None else False,
                to_node_id=next_node.attrib.get("id") if next_node is not None else False,
                actor_user=self.env.user,
                comment=audit_comment or False,
                payload={
                    "re_assign_approvals": bool(re_assign_approvals),
                    "target_node_code": target_node_code or False,
                    "target_node_name": target_label or False,
                    "meta_action_id": meta_action.id if meta_action else False,
                },
            )
        return result

    @staticmethod
    def _workflow_normalize_action_key(value):
        return (value or "").strip().lower()

    def _workflow_action_name_tokens(self, meta_action):
        if not meta_action:
            return set()
        technical_key = self._workflow_normalize_action_key(
            meta_action.name or meta_action.attr_label
        )
        return {technical_key} if technical_key else set()

    def _workflow_resolve_meta_action_from_payload(self, button):
        self.ensure_one()
        button = button if isinstance(button, dict) else {}
        action_model = self.env["workflow.category.version.meta.task.action"].sudo()

        request_record = (
            self.x_approval_base_id
            if "x_approval_base_id" in self._fields and self.x_approval_base_id
            else self
        )
        version = request_record.version_id
        button_meta_action_id = int(button.get("meta_action_id") or 0)
        button_action_key = self._workflow_normalize_action_key(
            button.get("action_key")
            or button.get("action_button_label")
            or button.get("label")
        )
        button_source_node = (
            button.get("source_node_id")
            or request_record.current_node_id
            or ""
        ).strip()

        meta_action = action_model.browse(button_meta_action_id).exists() if button_meta_action_id else action_model.browse()
        if meta_action:
            if button_source_node and (meta_action.source_id or "") != button_source_node:
                meta_action = action_model.browse()
            elif button_action_key and button_action_key not in self._workflow_action_name_tokens(meta_action):
                meta_action = action_model.browse()

        if not meta_action and version:
            candidates = (
                version._get_user_action_by_node_id(button_source_node)
                if button_source_node
                else version.meta_task_ids.mapped("meta_action_ids")
            )
            if button_action_key:
                candidates = candidates.filtered(
                    lambda action: button_action_key in self._workflow_action_name_tokens(action)
                )
            if button_meta_action_id:
                preferred = candidates.filtered(lambda action: action.id == button_meta_action_id)
                if preferred:
                    candidates = preferred
            if len(candidates) == 1:
                meta_action = candidates[:1]

        if not meta_action:
            raise UserError(_("Invalid workflow action payload. Please refresh and try again."))
        return meta_action[:1]

    def action_do_transition(self, button, show_dialog=True):
        """
        to be called by action buttons
        """
        self.ensure_one()
        if not button:
            raise UserError("No button_name found in context.")

        meta_action = self._workflow_resolve_meta_action_from_payload(button)
        guard_failure_action = self._workflow_action_execution_guard_failure_action(
            meta_action,
            show_dialog=show_dialog,
        )
        if guard_failure_action:
            return guard_failure_action

        view_id = self.env.ref('workflow_engine.view_workflow_confirm_wizard_form').id
        current_view_id = self.env.context.get("view_id") or False
        workflow_action_key = meta_action.name or meta_action.attr_label
        workflow_task_node_id = meta_action.source_id or False

        input_required = self._workflow_requires_action_input_dialog(meta_action, show_dialog=show_dialog)
        config_confirm = self._workflow_should_open_confirmation_dialog(meta_action, show_dialog=show_dialog)
        if input_required or config_confirm:
            wizard_context = {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'meta_action_id': meta_action.id,
                'view_id': current_view_id,
                'workflow_action_key': workflow_action_key,
                'workflow_task_node_id': workflow_task_node_id,
                'dialog_type': meta_action.dialog_type,
                'dialog_size': 'medium',
                'action_type': meta_action.name,
                'show_reason': self._workflow_action_shows_reason(meta_action),
                'require_reason': self._workflow_action_requires_reason(meta_action),
                'show_comment': self._workflow_action_shows_comment(meta_action),
                'require_comment': self._workflow_action_requires_comment(meta_action),
                'show_attachment': self._workflow_action_shows_attachment(meta_action),
                'require_attachment': self._workflow_action_requires_attachment(meta_action),
                'required_attachment_count': meta_action.required_attachment_count or 1,
                'workflow_input_required': input_required,
                'workflow_show_config_confirm': config_confirm,
                'confirm_message': meta_action.confirm_message,
                'default_confirm_message': meta_action.confirm_message,
            }
            if config_confirm:
                wizard_context['dialog_mobile_mode'] = 'sheet'
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'workflow.confirm.wizard',
                'view_mode': 'form',
                'views': [(view_id, 'form')],
                'view_id': view_id,
                'target': 'new',
                'name': _("Confirmation"),
                'context': wizard_context,
            }

        # 2FA: open client dialog only when action is configured and condition domain matches
        twofa_service = self.env["workflow.engine.twofactor.service"]
        request_record = self.x_approval_base_id if "x_approval_base_id" in self._fields and self.x_approval_base_id else self
        if twofa_service.action_requires_twofactor(
                request_record=request_record,
                meta_action=meta_action,
                target_record=self,
        ):
            challenge = twofa_service.issue_action_challenge(
                request_record=request_record,
                meta_action=meta_action,
                action_key=meta_action.name or meta_action.attr_label,
                target_record=self,
            )
            return {
                "type": "ir.actions.client",
                "tag": "workflow_engine_twofa_dialog",
                "target": "new",
                'name': _("2FA Confirmation"),
                "params": {
                    "challenge_id": challenge.id,
                    "meta_action_id": meta_action.id,
                    "res_model": self._name,
                    "res_id": self.id,
                    "view_id": current_view_id,
                },
            }

        # for handle validation of domain, then showing pop up
        # if self.x_approval_base_id.check_domain(meta_action.domain, False) and show_dialog: 
        if False and self.check_domain(meta_action.domain, False) and show_dialog:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'workflow.confirm.wizard',
                'view_mode': 'form',
                'views': [(view_id, 'form')],
                'view_id': view_id,
                'target': 'new',
                'name': _("Confirmation"),
                'context': {
                    'default_res_model': self._name,
                    'default_res_id': self.id,
                    'meta_action_id': meta_action.id,
                    'view_id': current_view_id,
                    'workflow_action_key': workflow_action_key,
                    'workflow_task_node_id': workflow_task_node_id,
                    'dialog_type': meta_action.dialog_type,
                    'dialog_size': 'medium',  # ✅ small / medium / large / xlarge
                    'show_reason': self._workflow_action_shows_reason(meta_action),
                    'require_reason': self._workflow_action_requires_reason(meta_action),
                    'show_comment': self._workflow_action_shows_comment(meta_action),
                    'require_comment': self._workflow_action_requires_comment(meta_action),
                    'show_attachment': self._workflow_action_shows_attachment(meta_action),
                    'require_attachment': self._workflow_action_requires_attachment(meta_action),
                    'action_type': meta_action.name,
                    'confirm_message': meta_action.confirm_message,
                    'default_confirm_message': meta_action.confirm_message,  # ✅ Correct
                }
            }

        if False and meta_action.show_confirm_dialog and show_dialog:
            # if dmain empty it will return all True, if you have condtion do not show it , just put domain to faild
            # if self.x_approval_base_id.check_domain(meta_action.domain, True): 
            if self.check_domain(meta_action.domain, True):
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'workflow.confirm.wizard',
                    'view_mode': 'form',
                    'views': [(view_id, 'form')],
                    'view_id': view_id,
                    'target': 'new',
                    'name': _("Confirmation"),
                    'context': {
                        'default_res_model': self._name,
                        'default_res_id': self.id,
                        'meta_action_id': meta_action.id,
                        'view_id': current_view_id,
                        'workflow_action_key': workflow_action_key,
                        'workflow_task_node_id': workflow_task_node_id,
                        'dialog_type': meta_action.dialog_type,
                        'dialog_size': 'medium',  # ✅ small / medium / large / xlarge
                        'action_type': meta_action.name,
                        'show_reason': self._workflow_action_shows_reason(meta_action),
                        'require_reason': self._workflow_action_requires_reason(meta_action),
                        'show_comment': self._workflow_action_shows_comment(meta_action),
                        'require_comment': self._workflow_action_requires_comment(meta_action),
                        'show_attachment': self._workflow_action_shows_attachment(meta_action),
                        'require_attachment': self._workflow_action_requires_attachment(meta_action),
                        'confirm_message': meta_action.confirm_message,
                        'default_confirm_message': meta_action.confirm_message,  # ✅ Correct
                        'dialog_mobile_mode': 'sheet'
                    }
                }

        # No-dialog path still needs server-side required validation.
        self.env["workflow.engine.field.rule.service"].validate_action_required_fields(
            request_record=self,
            action_key=meta_action.name or meta_action.attr_label,
            task_node_id=meta_action.source_id,
            view_id=self.env.context.get("view_id"),
        )

        workflow_record = self._workflow_elevated_action_record()

        # default for run engine
        return workflow_record.with_context(
            view_id=current_view_id,
            meta_action_id=meta_action.id,
            workflow_action_key=workflow_action_key,
            workflow_task_node_id=workflow_task_node_id,
            workflow_notification_actor_user_id=self.env.user.id,
        )._run_engine(
            form_data=workflow_record._get_form_data(),
            meta_action_id=button.get('meta_action_id')
        )

    @api.model
    def _workflow_history_source_base_request(self):
        base_request_model = self.env["workflow.base.approval.request"]
        if not self.env.context.get("workflow_history_mode"):
            return base_request_model

        source_base_id = self.env.context.get("workflow_history_source_base_id")
        try:
            source_base_id = int(source_base_id or 0)
        except (TypeError, ValueError):
            source_base_id = 0
        if not source_base_id:
            return base_request_model

        source_request = base_request_model.sudo().browse(source_base_id).exists()
        if not source_request or source_request.res_model_name != self._name:
            return base_request_model
        return source_request

    @api.model
    def _workflow_history_allowed_record_ids(self, source_request=False):
        source_request = source_request or self._workflow_history_source_base_request()
        if not source_request:
            return []

        category = source_request.category_id.sudo()
        if not category or not category.enable_request_history:
            return []
        if not self.env.user.has_group("workflow_engine.group_workflow_view_history_user"):
            return []

        permission_service = self.env["workflow.engine.permission.service"]
        if not permission_service.can_access_request(source_request, user=self.env.user, scope="read"):
            return []

        base_requests = self.env["workflow.base.approval.request"].sudo().with_context(
            wf_include_archived_categories=True,
            workflow_history_mode=False,
            workflow_history_source_base_id=False,
            workflow_history_allowed_ids=False,
        ).search(
            [
                ("category_id", "=", source_request.category_id.id),
                ("request_owner_id", "=", source_request.request_owner_id.id),
                ("id", "!=", source_request.id),
            ],
            order="submit_date desc, create_date desc, id desc",
        )
        if not base_requests:
            return []

        child_records = self.sudo().with_context(
            workflow_history_mode=False,
            workflow_history_source_base_id=False,
        ).search([("x_approval_base_id", "in", base_requests.ids)])
        if not child_records:
            return []

        child_by_base_id = {record.x_approval_base_id.id: record for record in child_records if record.x_approval_base_id}
        history_domain = (category.request_history_domain or "").strip()
        normalized_history_domain = history_domain.replace(" ", "")
        allowed_ids = []
        for request in base_requests:
            child_record = child_by_base_id.get(request.id)
            if not child_record:
                continue
            if history_domain and normalized_history_domain not in ("[]", "[(1,'=',1)]"):
                if not child_record.sudo().with_context(
                    workflow_history_mode=False,
                    workflow_history_source_base_id=False,
                ).check_domain(
                    history_domain,
                    default=False,
                    target_record=child_record.sudo(),
                    user=self.env.user,
                ):
                    continue
            allowed_ids.append(child_record.id)
        return allowed_ids

    @api.model
    def _workflow_history_effective_allowed_record_ids(self, source_request=False):
        allowed_ids = set(self._workflow_history_allowed_record_ids(source_request=source_request))
        context_ids = self.env.context.get("workflow_history_allowed_ids")
        if context_ids is None:
            return sorted(allowed_ids)

        if not isinstance(context_ids, (list, tuple, set)):
            context_ids = [context_ids]
        narrowed_ids = set()
        for record_id in context_ids:
            try:
                narrowed_ids.add(int(record_id))
            except (TypeError, ValueError):
                continue
        return sorted(allowed_ids & narrowed_ids)

    def _workflow_validate_history_source_request(self, source_request):
        if not self.env.user.has_group("workflow_engine.group_workflow_view_history_user"):
            raise AccessError(_("You are not allowed to view workflow history."))
        if not source_request or source_request.res_model_name != self._name:
            raise AccessError(_("You are not allowed to view workflow history."))
        if not source_request.category_id.enable_request_history:
            raise UserError(_("History is not enabled for this workflow category."))

        permission_service = self.env["workflow.engine.permission.service"]
        if not permission_service.can_access_request(source_request, user=self.env.user, scope="read"):
            raise AccessError(_("You are not allowed to view workflow history."))
        return source_request

    def action_open_workflow_history(self):
        self.ensure_one()
        base_request = self._workflow_validate_history_source_request(
            self.sudo()._workflow_resolve_request_record()
        )

        allowed_ids = self.with_context(
            workflow_history_mode=True,
            workflow_history_source_base_id=base_request.id,
        )._workflow_history_effective_allowed_record_ids(source_request=base_request)

        list_view_id = self.env.context.get("workflow_history_list_view_id") or False
        try:
            list_view_id = int(list_view_id or 0)
        except (TypeError, ValueError):
            list_view_id = 0
        views = []
        if list_view_id:
            views.append([list_view_id, "list"])
        views.append([False, "form"])
        return {
            "type": "ir.actions.act_window",
            "name": _("Request History"),
            "res_model": self._name,
            "view_mode": "list,form",
            "views": views,
            "target": "new",
            "domain": [("id", "in", allowed_ids)],
            "context": {
                "workflow_history_mode": True,
                "workflow_history_source_base_id": base_request.id,
                "workflow_history_allowed_ids": allowed_ids,
                "form_view_initial_mode": "view",
            },
        }

    def action_open_workflow_history_detail(self):
        self.ensure_one()
        source_request = self._workflow_validate_history_source_request(
            self._workflow_history_source_base_request()
        )
        allowed_ids = set(
            self.with_context(
                workflow_history_mode=True,
                workflow_history_source_base_id=source_request.id,
            )._workflow_history_effective_allowed_record_ids(source_request=source_request)
        )
        if self.id not in allowed_ids:
            raise AccessError(_("You are not allowed to access one or more workflow history records."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Request History"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "workflow_history_mode": True,
                "workflow_history_source_base_id": source_request.id,
                "workflow_history_allowed_ids": sorted(allowed_ids),
                "form_view_initial_mode": "view",
            },
        }

    @api.model
    def action_find_existing_requests_by_request_owner_id(self, category_id, request_owner_id):
        """
        check if there is already the record for that request_owner.
        also check if the duplicate is allowed in that workflow or not.

        @param category_id: id of the particular approval category
        @param request_owner_id: id of the particular request owner
        """

        if not category_id or not request_owner_id:
            return []

        category = self.env['workflow.approval.category'].sudo().browse(category_id)
        if not category:
            raise ValidationError(f"approval category id = {category_id} is not found")
        if category.allowed_duplicate:
            return []

        search_domain = [
            ('category_id', '=', category.id),
            ('request_owner_id', '=', request_owner_id),
            ('state', 'not in', ['completed', 'cancelled', 'auto_cancelled', 'refused', 'auto_approved']),
        ]

        # If the current record exists in the DB, exclude it from the "duplicate" check
        if self.id and isinstance(self.id, int):
            search_domain.append(('id', '!=', self.id))
        
        existing_requests = self.env['workflow.base.approval.request'].sudo().search(search_domain, order='id desc')
        if not existing_requests:
            return []
        block_domain = (category.allow_duplicate_domain or "").strip()
        if block_domain and block_domain not in ("[]", "[ ]"):
            matching_requests = self.env["workflow.base.approval.request"]
            for request in existing_requests:
                eval_record = request
                if self._name != "workflow.base.approval.request" and "x_approval_base_id" in self._fields:
                    eval_record = self.sudo().search(
                        [("x_approval_base_id", "=", request.id)],
                        limit=1,
                    ) or request
                elif hasattr(request, "_get_transition_delegate_record"):
                    eval_record = request.sudo()._get_transition_delegate_record()
                if request.sudo().check_domain(
                    block_domain,
                    default=False,
                    target_record=eval_record,
                ):
                    matching_requests |= request
            existing_requests = matching_requests
        if not existing_requests:
            return []

        return existing_requests.mapped(lambda r: {
            'id': r.id, 
            'name': r.name, 
            'create_date': r.create_date, 
            'create_uid': r.create_uid.name
        })

    @api.model
    def action_complete_existing_request(self, request_ids):
        """
        Cancel existing base requests so that a new request can be created.

        @param request_ids: an array of workflow.base.approval.request ids
        """
        if not request_ids:
            return

        requests = self.env["workflow.base.approval.request"].sudo().browse(request_ids).exists()
        target_temp_node = None
        if requests and len(requests) > 0:
            first_request = requests[0]
            version = first_request.version_id
            if version:
                category = version.category_id
                if category:
                    target_task = self.env["workflow.category.version.meta.task"].sudo().search([
                        ('version_id','=', version.id),('category_id','=', category.id),
                        ('name','=', 'Cancelled')], limit=1)
                    if target_task:
                        target_temp_node = self.env["workflow.bpmn.temp.node"].sudo().create({
                            'code': target_task.node_id,
                            'name': target_task.name,
                            'node_type': target_task.node_type,
                            'category_id': category.id                            
                        })
        if target_temp_node:
            for request in requests:
                child_request = self.env[request.res_model_name].sudo().search([('x_approval_base_id', '=', request.id)],limit=1)
                if child_request:
                    child_request.action_force_transition(target_temp_node, True)

    def get_email_already_approval(self, activity_name):
        """Return a comma-separated string of emails for given activity name"""
        result = {}
        for rec in self:
            emails = []

            # Filter approvers by activity name + department check
            approved = rec.already_approved_user_ids.filtered(
                lambda a: a.current_meta_id.name == activity_name
            )
            # Add approvers’ emails
            emails += approved.mapped("user_id.email")

            # Clean up duplicates and empties
            emails = list(set(filter(None, emails)))
            email_cc = ",".join(emails)

            result[rec.id] = email_cc

        # If called on a single record → return string directly
        return result[self.id] if len(self) == 1 else result

    # def action_get_attachment_view(self):
    #     self.ensure_one()
    #     res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
    #     res['domain'] = [('res_model', '=', self._name), ('res_id', 'in', self.ids)]
    #     res['context'] = {'default_res_model': 'approval.request', 'default_res_id': self.id}
    #     return res
    # @api.model_create_multi
    def create(self, vals_list):
        # if self._name != "workflow.base.approval.request":
        access_vals_list = [vals_list] if isinstance(vals_list, dict) else vals_list
        self._workflow_check_create_access_from_vals_list(access_vals_list)
        created_requests = super().create(vals_list)
        created_requests._workflow_force_created_uid_on_records()
        for request in created_requests:
            if request._workflow_should_autorun_on_create():
                request._run_engine()
        return created_requests

    def _workflow_should_autorun_on_create(self):
        self.ensure_one()
        if self.env.context.get("workflow_skip_create_autorun"):
            return False
        base_request = getattr(self, "x_approval_base_id", False)
        if not base_request:
            return True
        if getattr(base_request, "current_node_id", False):
            return False
        return getattr(base_request, "state", False) in (False, "draft", "new")

    def write(self, vals):
        # unsubscribe the previous request_owner if he is not the creator
        if 'request_owner_id' in vals:
            for approval in self:
                if approval.request_owner_id != approval.create_uid:
                    approval._workflow_safe_message_unsubscribe(approval.request_owner_id.partner_id.ids)

        result = super().write(vals)

        if len(self) == 1:
            handle_history_divergence(self, 'note', vals)
            """
            put a validation to check if required fields are not empty when updating the record.
            if the field is html type, it will check if there is any text inside the html tags.    
            """
            # chhai: 2026-01-26: it error when update and add new items line
            if self.required_fields:
                for require_field in self.required_fields:
                    if require_field in vals:
                        raw_val = vals.get(require_field)
                        field = self._fields.get(require_field)

                        if field and field.type == 'html' and isinstance(raw_val, str):
                            text = html.fromstring(raw_val).text_content().strip()
                            if not text:
                                raise ValidationError(
                                    f"{field.string} is required"
                                )
                    field = self._fields.get(require_field)
                    if field and field.type in ['many2many', 'one2many']:
                        raw_val = getattr(self, require_field)
                        if not raw_val and not vals.get(require_field):
                            raise ValidationError(
                                f"{field.string} is required"
                            )
            # subscribe reques owner if he is different from create uid
            # because system already subscribed create uid
            if 'request_owner_id' in vals:
                for approval in self:
                    if approval.request_owner_id != approval.create_uid:
                        approval._workflow_safe_message_subscribe(approval.request_owner_id.partner_id.ids)

            if 'approver_ids' in vals:
                to_resequence = self.filtered_domain(
                    [('approver_sequence', '=', True), ('request_status', '=', 'pending')])
                for approval in to_resequence:
                    if not approval.approver_ids.filtered(lambda a: a.status == 'pending'):
                        approver = approval.approver_ids.filtered(lambda a: a.status == 'waiting')
                        if approver:
                            approver[0].status = 'pending'
                            if not approval._workflow_notifications_suppressed():
                                approver[0]._create_activity()

            if 'state' in vals and vals.get('state') in ['new', 'waiting', 'completed']:
                self._category_count_recompute()
        return result
