# -*- coding: utf-8 -*-
import ast
import copy
import datetime as py_datetime
import hashlib
import json
import logging
import re
import warnings
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace

from lxml import etree
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import date_utils, ormcache
from odoo.tools.safe_eval import datetime as safe_eval_datetime
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class _WorkflowAssignmentRequestProxy:
    """Safe-eval helper: prefer form fields, fallback to the base request."""

    def __init__(self, eval_record, request_record):
        self._eval_record = eval_record
        self._request_record = request_record

    def __bool__(self):
        return bool(self._eval_record or self._request_record)

    def __getattr__(self, name):
        for record in (self._eval_record, self._request_record):
            if not record:
                continue
            try:
                return getattr(record, name)
            except AttributeError:
                continue
        raise AttributeError(name)

    def __getitem__(self, name):
        for record in (self._eval_record, self._request_record):
            if not record:
                continue
            try:
                if name in record._fields:
                    return record[name]
            except Exception:
                continue
        raise KeyError(name)

    def sudo(self, *args, **kwargs):
        eval_record = (
            self._eval_record.sudo(*args, **kwargs)
            if getattr(self._eval_record, "sudo", False)
            else self._eval_record
        )
        request_record = (
            self._request_record.sudo(*args, **kwargs)
            if getattr(self._request_record, "sudo", False)
            else self._request_record
        )
        return self.__class__(eval_record, request_record)

    def with_user(self, *args, **kwargs):
        eval_record = (
            self._eval_record.with_user(*args, **kwargs)
            if getattr(self._eval_record, "with_user", False)
            else self._eval_record
        )
        request_record = (
            self._request_record.with_user(*args, **kwargs)
            if getattr(self._request_record, "with_user", False)
            else self._request_record
        )
        return self.__class__(eval_record, request_record)


class WorkflowEnginePermissionService(models.AbstractModel):
    _name = "workflow.engine.permission.service"
    _description = "Workflow Engine Permission Service"

    def _is_technical_admin(self, user):
        return bool(user and user.has_group("workflow_engine.group_workflow_technical_admin"))

    def _is_admin(self, user):
        return bool(
            user
            and (
                user.has_group("base.group_system")
                or user.has_group("workflow_engine.group_workflow_approval_admin")
            )
        )

    def _has_base_workflow_group(self, user):
        return bool(user and user.has_group("workflow_engine.group_workflow_request_reader"))

    def _has_approval_workflow_group(self, user):
        return bool(user and user.has_group("workflow_engine.group_workflow_approval_user"))

    def _user_effective_groups(self, user):
        if not user:
            return self.env["res.groups"]
        user = user.sudo()
        return user.all_group_ids if "all_group_ids" in user._fields else user.group_ids

    def _user_effective_group_ids(self, user):
        return self._user_effective_groups(user).ids

    def _has_global_category_read_access(self, user):
        return self._is_admin(user) or self._is_technical_admin(user)

    def can_access_category(self, category, user=False):
        user = user or self.env.user
        if not category:
            return False
        category = category.sudo()
        category.ensure_one()
        if self._is_admin(user):
            return True
        if not self._has_base_workflow_group(user):
            return False

        if not category.zero_trust_enforced:
            return True

        if user in category.allowed_user_ids:
            return True
        if category.allowed_group_ids & self._user_effective_groups(user):
            return True
        # Permission evaluation needs the target user's department identity even
        # when the caller cannot read private employee-version fields.
        department = user.sudo().department_id
        if department and department in category.allowed_department_ids:
            return True
        return False

    def _has_scope_access(self, request_record, user, scope="read"):
        scope_rank = {"read": 1, "edit": 2, "decision": 3}
        requested_rank = scope_rank.get(scope, 1)
        now = fields.Datetime.now()
        visibility = request_record.visibility_scope_ids.filtered(
            lambda s: s.active
            and (not s.expires_at or s.expires_at >= now)
            and (
                s.allowed_user_id.id == user.id
                or (s.allowed_group_id and s.allowed_group_id in self._user_effective_groups(user))
            )
        )
        for rule in visibility:
            if scope_rank.get(rule.scope, 1) >= requested_rank:
                return True
        return False

    def _has_delegated_access(self, request_record, user, source_node_id=False):
        if not user:
            return False
        manual_rows = request_record.approver_ids.filtered(
            lambda a: a.user_id.id == user.id
            and a.delegated_from_user_id
            and a.delegation_mode in ("shared", "redirected")
            and a.status in ("new", "pending", "waiting")
            and (not source_node_id or a.current_meta_node_id == source_node_id)
        )
        if manual_rows:
            return True
        delegation_model = self.env["workflow.approval.delegation"].sudo()
        domain = [
            ("delegate_user_id", "=", user.id),
            ("active", "=", True),
            ("date_from", "<=", fields.Datetime.now()),
            ("date_to", ">=", fields.Datetime.now()),
        ]
        delegations = delegation_model.search(domain)
        if request_record.category_id:
            delegations = delegations.filtered(
                lambda d: not d.category_ids or request_record.category_id in d.category_ids
            )
        if not delegations:
            return False
        delegator_ids = delegations.mapped("delegator_user_id").ids
        if not delegator_ids:
            return False

        approver_rows = request_record.approver_ids.filtered(
            lambda a: a.user_id.id in delegator_ids
            and a.status in ("new", "pending", "waiting")
            and (not source_node_id or a.current_meta_node_id == source_node_id)
        )
        if approver_rows:
            return True
        if request_record.task_instance_ids:
            assignee_rows = request_record.task_instance_ids.assignee_ids.filtered(
                lambda a: a.assignee_user_id.id in delegator_ids
                and a.status in ("new", "pending", "in_progress")
                and (not source_node_id or a.node_id == source_node_id)
            )
            if assignee_rows:
                return True
        return False

    def _is_request_follower(self, request_record, user):
        if not request_record or not user:
            return False
        return bool(
            request_record.message_partner_ids.filtered(lambda partner: user.id in partner.user_ids.ids)
        )

    def _static_policy_eval_symbols(self, user):
        return {
            "False": False,
            "True": True,
            "None": None,
            "uid": user.id if user else 0,
            "user": user.sudo() if user else False,
            "datetime": datetime,
            "date": py_datetime.date,
            "time": py_datetime.time,
            "context_today": fields.Date.today,
        }

    def _has_static_policy_category_access(self, category, user):
        if not category or not user:
            return False
        category = category.sudo()
        category.ensure_one()
        user_group_ids = set(self._user_effective_group_ids(user))
        if not user_group_ids:
            return False
        for payload in category.security_policy_live_rule_payload or []:
            if payload.get("group_id") in user_group_ids:
                return True
        return False

    def _has_visibility_category_access(self, category, user, scope="read"):
        if not category or not user:
            return False
        category = category.sudo()
        category.ensure_one()
        scope_rank = {"read": 1, "edit": 2, "decision": 3}
        requested_rank = scope_rank.get(scope, 1)
        allowed_scopes = [
            scope_name
            for scope_name, rank in scope_rank.items()
            if rank >= requested_rank
        ]
        now = fields.Datetime.now()
        domain = [
            ("request_id.category_id", "=", category.id),
            ("scope", "in", allowed_scopes),
            ("active", "=", True),
            "|",
            ("expires_at", "=", False),
            ("expires_at", ">=", now),
            "|",
            ("allowed_user_id", "=", user.id),
            ("allowed_group_id", "in", self._user_effective_group_ids(user) or [0]),
        ]
        return bool(self.env["workflow.request.visibility.scope"].sudo().search_count(domain))

    def _has_follower_category_access(self, category, user):
        if not category or not user or not user.partner_id:
            return False
        category = category.sudo()
        category.ensure_one()
        return bool(
            self.env["workflow.base.approval.request"].sudo().search_count(
                [
                    ("category_id", "=", category.id),
                    ("message_partner_ids", "in", [user.partner_id.id]),
                ]
            )
        )

    def _has_static_policy_access(self, request_record, user):
        if not request_record or not user:
            return False
        payloads = request_record.category_id.security_policy_live_rule_payload or []
        if not payloads:
            return False
        user_group_ids = set(self._user_effective_group_ids(user))
        eval_symbols = self._static_policy_eval_symbols(user)
        for payload in payloads:
            if payload.get("group_id") not in user_group_ids:
                continue
            expression = payload.get("base_domain_expression") or "[]"
            try:
                domain = safe_eval(expression, eval_symbols, mode="eval")
            except Exception:
                _logger.exception(
                    "Failed to evaluate published static policy '%s' for request %s",
                    payload.get("rule_name"),
                    request_record.id,
                )
                continue
            if request_record.filtered_domain(domain):
                return True
        return False

    def _batch_static_policy_request_ids(self, request_records, user):
        Request = self.env["workflow.base.approval.request"].sudo()
        request_records = request_records.sudo()
        user_group_ids = set(self._user_effective_group_ids(user))
        eval_symbols = self._static_policy_eval_symbols(user)
        allowed_ids = set()
        for category in request_records.mapped("category_id").sudo():
            category_request_ids = request_records.filtered(
                lambda record: record.category_id.id == category.id
            ).ids
            if not category_request_ids:
                continue
            for payload in category.security_policy_live_rule_payload or []:
                if payload.get("group_id") not in user_group_ids:
                    continue
                expression = payload.get("base_domain_expression") or "[]"
                try:
                    domain = safe_eval(expression, eval_symbols, mode="eval")
                except Exception:
                    _logger.exception(
                        "Failed to evaluate static policy '%s' while batching read access for category %s",
                        payload.get("rule_name"),
                        category.id,
                    )
                    continue
                allowed_ids.update(
                    Request.search([("id", "in", category_request_ids)] + list(domain)).ids
                )
        return allowed_ids

    def _batch_visibility_request_ids(self, request_records, user, scope="read"):
        scope_rank = {"read": 1, "edit": 2, "decision": 3}
        requested_rank = scope_rank.get(scope, 1)
        allowed_scopes = [
            scope_name
            for scope_name, rank in scope_rank.items()
            if rank >= requested_rank
        ]
        group_ids = self._user_effective_group_ids(user) or [0]
        now = fields.Datetime.now()
        rows = self.env["workflow.request.visibility.scope"].sudo().search(
            [
                ("request_id", "in", request_records.ids),
                ("active", "=", True),
                ("scope", "in", allowed_scopes),
                "|",
                ("expires_at", "=", False),
                ("expires_at", ">=", now),
                "|",
                ("allowed_user_id", "=", user.id),
                ("allowed_group_id", "in", group_ids),
            ]
        )
        return set(rows.mapped("request_id").ids)

    def _batch_open_actor_request_ids(self, request_records, user):
        allowed_ids = set()
        Approver = self.env["workflow.approval.approver"].sudo()
        TaskAssignee = self.env["workflow.request.task.assignee"].sudo()
        open_approver_statuses = ("new", "pending", "waiting")
        open_task_statuses = ("new", "pending", "in_progress")

        allowed_ids.update(
            Approver.search(
                [
                    ("request_id", "in", request_records.ids),
                    ("user_id", "=", user.id),
                ]
            ).mapped("request_id").ids
        )
        allowed_ids.update(
            TaskAssignee.search(
                [
                    ("task_instance_id.request_id", "in", request_records.ids),
                    ("assignee_user_id", "=", user.id),
                    ("status", "in", open_task_statuses),
                ]
            ).mapped("task_instance_id.request_id").ids
        )

        manual_delegate_ids = Approver.search(
            [
                ("request_id", "in", request_records.ids),
                ("user_id", "=", user.id),
                ("delegated_from_user_id", "!=", False),
                ("delegation_mode", "in", ("shared", "redirected")),
                ("status", "in", open_approver_statuses),
            ]
        ).mapped("request_id").ids
        allowed_ids.update(manual_delegate_ids)

        delegations = self.env["workflow.approval.delegation"].sudo().search(
            [
                ("delegate_user_id", "=", user.id),
                ("active", "=", True),
                ("date_from", "<=", fields.Datetime.now()),
                ("date_to", ">=", fields.Datetime.now()),
            ]
        )
        for delegation in delegations:
            if not delegation.delegator_user_id:
                continue
            approver_domain = [
                ("request_id", "in", request_records.ids),
                ("user_id", "=", delegation.delegator_user_id.id),
                ("status", "in", open_approver_statuses),
            ]
            assignee_domain = [
                ("task_instance_id.request_id", "in", request_records.ids),
                ("assignee_user_id", "=", delegation.delegator_user_id.id),
                ("status", "in", open_task_statuses),
            ]
            if delegation.category_ids:
                approver_domain.append(("request_id.category_id", "in", delegation.category_ids.ids))
                assignee_domain.append(("task_instance_id.request_id.category_id", "in", delegation.category_ids.ids))
            allowed_ids.update(Approver.search(approver_domain).mapped("request_id").ids)
            allowed_ids.update(
                TaskAssignee.search(assignee_domain).mapped("task_instance_id.request_id").ids
            )

        follower_rows = self.env["mail.followers"].sudo().search(
            [
                ("res_model", "=", "workflow.base.approval.request"),
                ("res_id", "in", request_records.ids),
                ("partner_id", "=", user.partner_id.id),
            ]
        )
        allowed_ids.update(follower_rows.mapped("res_id"))
        return allowed_ids

    def allowed_request_ids(self, request_records, user=False, scope="read"):
        user = user or self.env.user
        request_records = request_records.sudo().exists()
        if not request_records:
            return set()
        if self._is_admin(user):
            return set(request_records.ids)
        if scope == "read" and self._is_technical_admin(user):
            return set(request_records.ids)
        if scope == "read":
            if not self._has_base_workflow_group(user):
                return set()
        elif not self._has_approval_workflow_group(user):
            return set()
        if scope != "read":
            return {
                record.id
                for record in request_records
                if self.can_access_request(record, user=user, scope=scope)
            }

        allowed_ids = set()
        for request in request_records:
            category_ok = self.can_access_category(request.category_id, user=user)
            if category_ok:
                allowed_ids.add(request.id)
            if request.category_id.allow_requester_read and (
                request.request_owner_id.id == user.id or request.create_uid.id == user.id
            ):
                allowed_ids.add(request.id)
            if request.category_id.allow_manager_access and request.manager_user_id.id == user.id:
                allowed_ids.add(request.id)

        allowed_ids.update(self._batch_visibility_request_ids(request_records, user, scope="read"))
        allowed_ids.update(self._batch_static_policy_request_ids(request_records, user))
        allowed_ids.update(self._batch_open_actor_request_ids(request_records, user))
        return allowed_ids

    def _has_active_approver_access(self, request_record, user):
        """True only when user is an open approver on the current active stage."""
        if not request_record or not user:
            return False

        rows = request_record.approver_ids.filtered(
            lambda a: a.user_id.id == user.id and a.status in ("new", "pending", "waiting")
        )
        if not rows:
            return False

        current_iteration = getattr(request_record, "current_iteration_no", 0) or 0
        if current_iteration:
            iteration_rows = rows.filtered(lambda a: (a.iteration_no or 1) == current_iteration)
            if iteration_rows:
                rows = iteration_rows

        active_nodes = set()
        current_node_id = getattr(request_record, "current_node_id", False)
        if current_node_id:
            active_nodes.add(current_node_id)
        active_nodes |= set((getattr(request_record, "active_branch_node_ids", None) or []))

        if active_nodes:
            active_rows = rows.filtered(lambda a: a.current_meta_node_id in active_nodes)
            if active_rows:
                rows = active_rows
            else:
                rows = rows.filtered(lambda a: not a.current_meta_node_id)

        return bool(rows)

    def _manual_delegate_rows_for_action(self, request_record, source_node_id, user=False):
        user = user or self.env.user
        if not request_record or not source_node_id or not user:
            return self.env["workflow.approval.approver"]
        rows = request_record.approver_ids.filtered(
            lambda a: a.user_id.id == user.id
            and a.delegated_from_user_id
            and a.delegation_mode in ("shared", "redirected")
            and a.current_meta_node_id == source_node_id
            and a.status in ("new", "pending", "waiting")
        )
        current_iteration = getattr(request_record, "current_iteration_no", 0) or 0
        if current_iteration:
            iteration_rows = rows.filtered(lambda a: (a.iteration_no or 1) == current_iteration)
            if iteration_rows:
                rows = iteration_rows
        return rows.sorted(key=lambda row: (row.sequence, row.id))

    def can_access_request(self, request_record, user=False, scope="read"):
        user = user or self.env.user
        if not request_record:
            return False
        request_record = request_record.sudo()
        request_record.ensure_one()
        if self._is_admin(user):
            return True
        if scope == "read" and self._is_technical_admin(user):
            return True
        if scope == "read":
            if not self._has_base_workflow_group(user):
                return False
        elif not self._has_approval_workflow_group(user):
            return False

        category_ok = self.can_access_category(request_record.category_id, user=user)
        if scope == "read" and category_ok:
            return True
        if scope == "read" and request_record.category_id.allow_requester_read and (
            request_record.request_owner_id.id == user.id or request_record.create_uid.id == user.id
        ):
            return True
        if scope == "read" and request_record.category_id.allow_manager_access and request_record.manager_user_id.id == user.id:
            return True

        if self._has_scope_access(request_record, user, scope=scope):
            return True

        if scope == "read" and self._has_static_policy_access(request_record, user):
            return True

        # Edit scope must be strictly bound to active-stage actors (or explicit
        # scope grants above). Historical approvers are read-only.
        if scope == "edit":
            if self._has_active_approver_access(request_record, user):
                return True

            active_task_access = request_record.task_instance_ids.assignee_ids.filtered(
                lambda a: a.assignee_user_id.id == user.id and a.status in ("new", "pending", "in_progress")
            )
            if active_task_access:
                return True

            active_nodes = set()
            current_node_id = getattr(request_record, "current_node_id", False)
            if current_node_id:
                active_nodes.add(current_node_id)
            active_nodes |= set((getattr(request_record, "active_branch_node_ids", None) or []))
            if active_nodes:
                for node_id in active_nodes:
                    if self._has_delegated_access(request_record, user, source_node_id=node_id):
                        return True
            elif self._has_delegated_access(request_record, user):
                return True

            return False

        approver_rows = request_record.approver_ids.filtered(lambda a: a.user_id.id == user.id)
        if approver_rows:
            return True

        active_task_access = request_record.task_instance_ids.assignee_ids.filtered(
            lambda a: a.assignee_user_id.id == user.id and a.status in ("new", "pending", "in_progress")
        )
        if active_task_access:
            return True

        if self._has_delegated_access(request_record, user):
            return True

        if scope == "read" and self._is_request_follower(request_record, user):
            return True
        return False

    def resolve_delegate_for_action(self, request_record, source_node_id, user=False):
        user = user or self.env.user
        if not request_record or not source_node_id:
            return self.env["res.users"]
        manual_rows = self._manual_delegate_rows_for_action(
            request_record=request_record,
            source_node_id=source_node_id,
            user=user,
        )
        if manual_rows:
            return manual_rows[:1].delegated_from_user_id
        if request_record.approver_ids.filtered(
            lambda a: a.user_id.id == user.id
            and a.current_meta_node_id == source_node_id
            and a.status in ("new", "pending", "waiting")
        ):
            return self.env["res.users"]

        delegation_model = self.env["workflow.approval.delegation"].sudo()
        domain = [
            ("delegate_user_id", "=", user.id),
            ("active", "=", True),
            ("date_from", "<=", fields.Datetime.now()),
            ("date_to", ">=", fields.Datetime.now()),
        ]
        delegations = delegation_model.search(domain)
        if request_record.category_id:
            delegations = delegations.filtered(
                lambda d: not d.category_ids or request_record.category_id in d.category_ids
            )
        if not delegations:
            return self.env["res.users"]
        delegator_ids = delegations.mapped("delegator_user_id").ids
        if not delegator_ids:
            return self.env["res.users"]
        delegated_rows = request_record.approver_ids.filtered(
            lambda a: a.user_id.id in delegator_ids
            and a.current_meta_node_id == source_node_id
            and a.status in ("new", "pending", "waiting")
        )
        return delegated_rows[:1].user_id if delegated_rows else self.env["res.users"]

    def assert_can_execute_action(self, child_record, request_record, meta_action, user=False):
        user = user or self.env.user
        authorization_mode = getattr(meta_action, "authorization_mode", False) or "approval_actor"
        if authorization_mode == "business_actor":
            assignment_service = self.env["workflow.engine.assignment.service"]
            if not assignment_service._business_action_actor_enabled():
                raise AccessError(_("Business action actors are currently disabled."))
            if self._is_admin(user) or request_record._workflow_user_is_on_behalf_admin(user=user):
                return {
                    "allowed": True,
                    "on_behalf_user_id": False,
                    "authorization_mode": "business_actor",
                    "action_assignment_ids": [],
                    "admin_override": True,
                }
            if not self.can_access_request(request_record, user=user, scope="read"):
                raise AccessError(_("You do not have access to this workflow request."))
            assignments = assignment_service._open_business_action_assignments(
                request_record,
                user=user,
                node_id=meta_action.source_id,
                meta_action=meta_action,
            )
            if not assignments:
                raise AccessError(
                    _("You are not assigned to execute this business action for the active task.")
                )
            return {
                "allowed": True,
                "on_behalf_user_id": False,
                "authorization_mode": "business_actor",
                "action_assignment_ids": assignments.ids,
                "admin_override": False,
            }
        if self._is_admin(user):
            return {"allowed": True, "on_behalf_user_id": False}
        source_node_id = meta_action.source_id if meta_action else False
        if (
            request_record
            and source_node_id
            and request_record._workflow_user_is_on_behalf_admin(user=user)
            and request_record._workflow_can_execute_approval_actor_node(source_node_id, user=user)
        ):
            return {"allowed": True, "on_behalf_user_id": False}
        if not self.can_access_request(request_record, user=user, scope="decision"):
            raise AccessError(_("You do not have access to this workflow request."))

        direct = request_record.approver_ids.filtered(
            lambda a: a.user_id.id == user.id
            and a.current_meta_node_id == source_node_id
            and a.status in ("new", "pending", "waiting")
        )
        manual_direct = self._manual_delegate_rows_for_action(
            request_record=request_record,
            source_node_id=source_node_id,
            user=user,
        )
        if manual_direct:
            delegated_row = manual_direct[:1]
            return {
                "allowed": True,
                "on_behalf_user_id": delegated_row.delegated_from_user_id.id,
                "manual_delegated_approver_id": delegated_row.id,
                "source_approver_id": delegated_row.delegated_from_approver_id.id if delegated_row.delegated_from_approver_id else False,
                "delegation_mode": delegated_row.delegation_mode or False,
            }
        if direct:
            return {"allowed": True, "on_behalf_user_id": False}

        delegated_from = self.resolve_delegate_for_action(request_record, source_node_id, user=user)
        if delegated_from:
            return {"allowed": True, "on_behalf_user_id": delegated_from.id}

        raise AccessError(_("You are not allowed to execute this action for the active task."))

    def filter_authorized_actions(self, request_record, actions, user=False):
        user = user or self.env.user
        if not request_record or not actions:
            return actions.browse()
        approval_actions = actions.filtered(
            lambda action: (action.authorization_mode or "approval_actor") == "approval_actor"
        )
        business_actions = actions - approval_actions
        allowed = actions.browse()
        if approval_actions and request_record._workflow_can_execute_approval_actor_node(
            approval_actions[:1].source_id,
            user=user,
        ):
            allowed |= approval_actions
        assignment_service = self.env["workflow.engine.assignment.service"]
        if business_actions and assignment_service._business_action_actor_enabled():
            if self._is_admin(user) or request_record._workflow_user_is_on_behalf_admin(user=user):
                allowed |= business_actions
            else:
                rows = assignment_service._open_business_action_assignments(
                    request_record,
                    user=user,
                    node_id=business_actions[:1].source_id,
                ).filtered(lambda row: row.meta_action_id in business_actions)
                allowed |= rows.mapped("meta_action_id")
        return actions.filtered(lambda action: action in allowed)


class WorkflowEngineAuditService(models.AbstractModel):
    _name = "workflow.engine.audit.service"
    _description = "Workflow Engine Audit Service"

    def _http_metadata(self):
        ip_address = False
        request_host = False
        user_agent = False
        try:
            from odoo.http import request as http_request

            if http_request and getattr(http_request, "httprequest", False):
                headers = http_request.httprequest.headers
                forwarded_for = (headers.get("X-Forwarded-For") or "").strip()
                if forwarded_for:
                    ip_address = forwarded_for.split(",")[0].strip()
                ip_address = ip_address or http_request.httprequest.remote_addr
                request_host = (headers.get("X-Forwarded-Host") or headers.get("Host") or "").strip() or False
                user_agent = headers.get("User-Agent")
        except Exception:
            pass
        return ip_address, request_host, user_agent

    @api.model
    def log_event(
        self,
        request_record,
        event_type="system",
        task_instance=False,
        task_assignee=False,
        action_key=False,
        decision=False,
        from_node_id=False,
        to_node_id=False,
        actor_user=False,
        on_behalf_of_user=False,
        target_user=False,
        comment=False,
        payload=False,
        idempotency_key=False,
        challenge=False,
    ):
        if not request_record:
            return self.env["workflow.request.task.event"]
        request_record = request_record.sudo()
        ip_address, request_host, user_agent = self._http_metadata()
        actor_user = actor_user or self.env.user
        payload = payload or {}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)}
        values = {
            "request_id": request_record.id,
            "task_instance_id": task_instance.id if task_instance else False,
            "task_assignee_id": task_assignee.id if task_assignee else False,
            "event_type": event_type,
            "action_key": action_key or False,
            "decision": decision or False,
            "from_node_id": from_node_id or False,
            "to_node_id": to_node_id or False,
            "actor_user_id": actor_user.id if actor_user else False,
            "on_behalf_of_user_id": on_behalf_of_user.id if on_behalf_of_user else False,
            "target_user_id": target_user.id if target_user else False,
            "comment": comment or False,
            "payload_json": payload,
            "idempotency_key": idempotency_key or False,
            "request_ip": ip_address or False,
            "request_host": request_host or False,
            "user_agent": user_agent or False,
            "challenge_id": challenge.id if challenge else False,
            "challenge_method": challenge.method if challenge else "none",
            "challenge_verified": bool(challenge and challenge.state in ("verified", "approved")),
        }
        return self.env["workflow.request.task.event"].sudo().create(values)


class WorkflowEngineAssignmentDomainService(models.AbstractModel):
    _name = "workflow.engine.assignment.domain.service"
    _description = "Workflow Engine Assignment Domain Service"

    _USER_DOMAIN_FIELD_ALIASES = {
        # Backward-compatible alias frequently used in customer-configured expressions.
        "user_id": "id",
    }

    @api.model
    @ormcache("target_model_name", "field_path")
    def _domain_field_path_exists(self, target_model_name, field_path):
        """Return True when a dotted domain path exists on the target model."""
        if not target_model_name or not field_path:
            return False
        try:
            current_model = self.env[target_model_name]
        except KeyError:
            return False
        segments = field_path.split(".")
        for index, segment in enumerate(segments):
            field = current_model._fields.get(segment)
            if not field:
                return False
            if index == len(segments) - 1:
                return True
            if field.type not in ("many2one", "one2many", "many2many"):
                return False
            if not field.comodel_name:
                return False
            try:
                current_model = self.env[field.comodel_name]
            except KeyError:
                return False
        return False

    def _normalize_domain_field_for_target_model(self, field_name, target_model_name):
        if not isinstance(field_name, str):
            return field_name
        normalized = field_name
        if target_model_name == "res.users":
            normalized = self._USER_DOMAIN_FIELD_ALIASES.get(normalized, normalized)
        # Backward compatibility for legacy domains like request_owner_id.id
        # or manager_user_id.id configured in older flows.
        if normalized.endswith(".id"):
            candidate = normalized[:-3]
            if candidate and self._domain_field_path_exists(target_model_name, candidate):
                return candidate
        return normalized

    def _normalize_node_user_type(self, user_type):
        normalized = (user_type or "assigned").strip().lower()
        return normalized if normalized in {"assigned", "pending", "decided"} else "assigned"

    def _normalize_simulated_history(self, simulated_history):
        history = simulated_history if isinstance(simulated_history, dict) else {}
        by_node = {}
        for node_id, entry in (history.get("by_node") or {}).items():
            if not node_id or not isinstance(entry, dict):
                continue
            by_node[node_id] = {
                "assigned_user_ids": [int(uid) for uid in (entry.get("assigned_user_ids") or []) if uid],
                "pending_user_ids": [int(uid) for uid in (entry.get("pending_user_ids") or []) if uid],
                "decided_user_ids": [int(uid) for uid in (entry.get("decided_user_ids") or []) if uid],
                "manual_assigned": bool(entry.get("manual_assigned")),
                "manual_decided": bool(entry.get("manual_decided")),
            }
        all_assigned = []
        all_pending = []
        all_decided = []
        for entry in by_node.values():
            all_assigned.extend(entry.get("assigned_user_ids") or [])
            all_pending.extend(entry.get("pending_user_ids") or [])
            all_decided.extend(entry.get("decided_user_ids") or [])
        return {
            "by_node": by_node,
            "all_assigned_user_ids": list(dict.fromkeys(all_assigned)),
            "all_pending_user_ids": list(dict.fromkeys(all_pending)),
            "all_decided_user_ids": list(dict.fromkeys(all_decided)),
        }

    def _simulated_node_user_ids(self, simulated_history, node_id, user_type="assigned"):
        history = self._normalize_simulated_history(simulated_history)
        if not node_id:
            return []
        entry = (history.get("by_node") or {}).get(node_id) or {}
        normalized_type = self._normalize_node_user_type(user_type)
        if normalized_type == "decided":
            return entry.get("decided_user_ids") or []
        if normalized_type == "pending":
            return entry.get("pending_user_ids") or entry.get("assigned_user_ids") or []
        return entry.get("assigned_user_ids") or []

    def _node_approver_rows(self, request_record, node_id, user_type="assigned", simulated_history=False):
        if not request_record or not node_id:
            return self.env["workflow.approval.approver"]
        simulated_ids = self._simulated_node_user_ids(
            simulated_history,
            node_id,
            user_type=user_type,
        )
        if simulated_ids:
            return self.env["workflow.approval.approver"]
        approver_rows = getattr(
            request_record.sudo(),
            "approver_ids",
            self.env["workflow.approval.approver"],
        )
        if not approver_rows:
            return self.env["workflow.approval.approver"]

        normalized_type = self._normalize_node_user_type(user_type)
        node_rows = approver_rows.filtered(lambda row: row.current_meta_node_id == node_id)
        if normalized_type == "pending":
            node_rows = node_rows.filtered(lambda row: row.status in ("new", "pending", "waiting"))
        elif normalized_type == "decided":
            node_rows = node_rows.filtered("counts_as_decided_user")
        else:
            node_rows = node_rows.filtered(lambda row: row.status not in ("cancelled", "skipped"))
        if not node_rows:
            return self.env["workflow.approval.approver"]

        current_iteration = getattr(request_record, "current_iteration_no", 0) or 0
        if current_iteration:
            current_rows = node_rows.filtered(lambda row: (row.iteration_no or 1) == current_iteration)
            if current_rows:
                return current_rows

        latest_iteration = max([row.iteration_no or 1 for row in node_rows] or [1])
        return node_rows.filtered(lambda row: (row.iteration_no or 1) == latest_iteration)

    def node_approver_users(self, request_record, node_id, user_type="assigned", simulated_history=False):
        simulated_ids = self._simulated_node_user_ids(
            simulated_history,
            node_id,
            user_type=user_type,
        )
        if simulated_ids:
            return self.env["res.users"].browse(simulated_ids)
        rows = self._node_approver_rows(
            request_record,
            node_id,
            user_type=user_type,
            simulated_history=simulated_history,
        )
        users = self.env["res.users"]
        seen = set()
        for user in rows.mapped("user_id"):
            if user.id and user.id not in seen:
                users |= user
                seen.add(user.id)
        return users

    def node_approver_user_ids(self, request_record, node_id, user_type="assigned", simulated_history=False):
        return self.node_approver_users(
            request_record,
            node_id,
            user_type=user_type,
            simulated_history=simulated_history,
        ).ids

    def _resolution_memo_bucket(self, memo, bucket_name):
        if not isinstance(memo, dict):
            return {}
        return memo.setdefault(bucket_name, {})

    def _all_active_non_portal_users(self):
        return self.env["res.users"].sudo().search([("active", "=", True), ("share", "=", False)])

    def _memoized_all_active_non_portal_users(self, memo=False):
        bucket = self._resolution_memo_bucket(memo, "all_active_non_portal_users")
        cache_key = self.env.uid
        if cache_key not in bucket:
            bucket[cache_key] = self._all_active_non_portal_users()
        return bucket[cache_key]

    def resolve_notification_recipients(
        self,
        request_record,
        meta_task,
        memo=False,
        simulated_history=False,
    ):
        if not request_record or not meta_task:
            return self.env["res.users"]
        recipient_source = (getattr(meta_task, "notification_recipient_source", False) or "").strip()

        def _resolve_routing_domain_literal():
            if recipient_source == "domain":
                primary = getattr(meta_task, "notification_recipient_domain", False)
                secondary = getattr(meta_task, "notification_recipient_filter_domain", False)
            else:
                primary = getattr(meta_task, "notification_recipient_filter_domain", False)
                secondary = getattr(meta_task, "notification_recipient_domain", False)
            primary_text = self._normalize_routing_domain_text(primary)
            if primary_text:
                return primary
            return secondary

        if recipient_source == "specific_users":
            recipients = meta_task.notification_recipient_ids.sudo()
        elif recipient_source == "approval_group_users":
            recipients = meta_task.notification_approval_group_ids.sudo().mapped("user_ids")
            filter_domain = _resolve_routing_domain_literal()
            if recipients:
                recipients = self.eval_routing_user_domain(
                    recipients,
                    filter_domain,
                    request_record=request_record,
                    memo=memo,
                )
        elif recipient_source == "group_users":
            group_user_field = "user_ids" if "user_ids" in self.env["res.groups"]._fields else "users"
            recipients = meta_task.notification_group_ids.sudo().mapped(group_user_field)
            filter_domain = _resolve_routing_domain_literal()
            if recipients:
                recipients = self.eval_routing_user_domain(
                    recipients,
                    filter_domain,
                    request_record=request_record,
                    memo=memo,
                )
        elif recipient_source == "node_users":
            recipients = self.node_approver_users(
                request_record,
                (meta_task.notification_recipient_node_ref or "").strip(),
                user_type=meta_task.notification_recipient_node_user_type or "assigned",
                simulated_history=simulated_history,
            )
            filter_domain = _resolve_routing_domain_literal()
            if recipients:
                recipients = self.eval_routing_user_domain(
                    recipients,
                    filter_domain,
                    request_record=request_record,
                    memo=memo,
                )
        elif recipient_source == "domain":
            filter_domain = _resolve_routing_domain_literal()
            recipients = self.eval_routing_user_domain(
                self._memoized_all_active_non_portal_users(memo),
                filter_domain,
                request_record=request_record,
                memo=memo,
            )
        else:
            recipients = self.env["res.users"]
            recipient_mode = getattr(meta_task, "notification_recipient_mode", "specific_users") or "specific_users"
            if recipient_mode in ("specific_users", "both"):
                recipients |= meta_task.notification_recipient_ids.sudo()
            if recipient_mode in ("domain", "both"):
                legacy_domain = (
                    getattr(meta_task, "notification_recipient_domain", False)
                    or getattr(meta_task, "notification_recipient_filter_domain", False)
                )
                recipients |= self.eval_routing_user_domain(
                    self._memoized_all_active_non_portal_users(memo),
                    legacy_domain,
                    request_record=request_record,
                    memo=memo,
                )

        return recipients.filtered(lambda user: user.active and user.partner_id)

    @api.model
    def _collect_manager_chain_user_ids(self, employee, max_depth=20):
        """Return requester manager chain user ids from direct manager upward."""
        manager_user_ids = []
        visited_employee_ids = set()
        current = employee.parent_id if employee else self.env["hr.employee"]
        depth = 0
        while (
            current
            and current.id
            and current.id not in visited_employee_ids
            and depth < max_depth
        ):
            visited_employee_ids.add(current.id)
            if current.user_id and current.user_id.id:
                manager_user_ids.append(current.user_id.id)
            current = current.parent_id
            depth += 1
        return manager_user_ids

    def _coerce_assignment_eval_value(self, field, value):
        field_type = field.type or ""
        if field_type == "many2one":
            if isinstance(value, dict):
                return value.get("id") or False
            return value.id if hasattr(value, "id") else value or False
        if field_type in ("many2many", "one2many"):
            if hasattr(value, "ids"):
                return list(value.ids)
            if isinstance(value, list):
                ids = []
                for item in value:
                    if isinstance(item, dict) and item.get("id"):
                        ids.append(item["id"])
                    elif isinstance(item, int):
                        ids.append(item)
                return ids
        if field_type == "date":
            return fields.Date.to_string(value) if value else False
        if field_type == "datetime":
            return fields.Datetime.to_string(value) if value else False
        return value

    def _inject_request_eval_values(
        self,
        context,
        request_record,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
    ):
        """Merge request form values into safe-eval symbols for dynamic assignment domains."""
        if not request_record:
            return context
        request_record = request_record.sudo()
        eval_record = eval_record.sudo() if getattr(eval_record, "sudo", False) else eval_record
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        source_record = eval_record or request_record
        for field_name, field in source_record._fields.items():
            if field_name in context:
                continue
            field_type = field.type or ""
            if field_type in ("binary", "html"):
                continue
            try:
                value = (
                    snapshot_values[field_name]
                    if field_name in snapshot_values
                    else source_record[field_name]
                )
            except Exception:
                continue
            context[field_name] = self._coerce_assignment_eval_value(field, value)

        context.setdefault("request_model", (eval_record or request_record)._name)
        context.setdefault("request_id", request_record.id)
        request_owner = (
            request_record.request_owner_id
            if "request_owner_id" in request_record._fields
            else self.env["res.users"]
        )
        manager_user = (
            request_record.manager_user_id
            if "manager_user_id" in request_record._fields
            else self.env["res.users"]
        )
        request_creator = (
            request_record.create_uid
            if "create_uid" in request_record._fields
            else self.env["res.users"]
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
            else self.env["res.users"]
        )
        request_owner_line_manager_user = (
            request_owner_employee.parent_id.user_id
            if request_owner_employee
            and request_owner_employee.parent_id
            and request_owner_employee.parent_id.user_id
            else self.env["res.users"]
        )
        request_owner_department_manager_user = (
            request_owner_department.manager_id.user_id
            if request_owner_department
            and request_owner_department.manager_id
            and request_owner_department.manager_id.user_id
            else self.env["res.users"]
        )
        request_owner_manager_chain_user_ids = self._collect_manager_chain_user_ids(
            request_owner_employee
        )
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
        context["request_owner_id"] = request_owner.id if request_owner else False
        context["request_owner_user_id"] = request_owner.id if request_owner else False
        context["request_creator_id"] = request_creator.id if request_creator else False
        context["request_creator_user_id"] = request_creator.id if request_creator else False
        context["manager_user_id"] = manager_user.id if manager_user else False
        context["request_creator_manager_user_id"] = manager_user.id if manager_user else False
        context["request_owner_manager_user_id"] = (
            request_owner_manager_user.id if request_owner_manager_user else False
        )
        context["request_owner_line_manager_user_id"] = (
            request_owner_line_manager_user.id if request_owner_line_manager_user else False
        )
        context["request_owner_department_id"] = (
            request_owner_department.id if request_owner_department else False
        )
        context["request_owner_department_manager_user_id"] = (
            request_owner_department_manager_user.id
            if request_owner_department_manager_user
            else False
        )
        context["request_owner_manager_chain_user_ids"] = request_owner_manager_chain_user_ids
        context["request_owner_team"] = request_owner_team or False
        context["request_owner_team_code"] = request_owner_team_code or False
        context["request_owner_line"] = request_owner_line or False
        context["request_owner_line_code"] = request_owner_line_code or False
        approver_rows = self.env["workflow.approval.approver"]
        if "approver_ids" in request_record._fields:
            try:
                approver_rows = request_record.approver_ids.sudo()
            except Exception:
                approver_rows = self.env["workflow.approval.approver"]
        decided_rows = approver_rows.filtered("counts_as_decided_user")
        pending_rows = approver_rows.filtered(lambda row: row.status in ("new", "pending", "waiting"))
        all_user_ids = [uid for uid in approver_rows.mapped("user_id").ids if uid]
        decided_user_ids = [uid for uid in decided_rows.mapped("user_id").ids if uid]
        pending_user_ids = [uid for uid in pending_rows.mapped("user_id").ids if uid]
        submitter_and_decided = list(
            dict.fromkeys(
                ([request_owner.id] if request_owner else []) + decided_user_ids
            )
        )
        history = self._normalize_simulated_history(simulated_history)
        all_user_ids = list(dict.fromkeys(all_user_ids + (history.get("all_assigned_user_ids") or []) + (history.get("all_decided_user_ids") or [])))
        decided_user_ids = list(dict.fromkeys(decided_user_ids + (history.get("all_decided_user_ids") or [])))
        pending_user_ids = list(dict.fromkeys(pending_user_ids + (history.get("all_pending_user_ids") or [])))
        context["all_approver_user_ids"] = all_user_ids
        context["decided_approver_user_ids"] = decided_user_ids
        context["has_decision_user_ids"] = decided_user_ids
        context["pending_approver_user_ids"] = pending_user_ids
        context["notification_submitter_and_decided_user_ids"] = submitter_and_decided

        def node_assigned_approver_user_ids(node_id):
            return self.node_approver_user_ids(
                request_record,
                node_id,
                user_type="assigned",
                simulated_history=simulated_history,
            )

        def node_pending_approver_user_ids(node_id):
            return self.node_approver_user_ids(
                request_record,
                node_id,
                user_type="pending",
                simulated_history=simulated_history,
            )

        def node_decided_approver_user_ids(node_id):
            return self.node_approver_user_ids(
                request_record,
                node_id,
                user_type="decided",
                simulated_history=simulated_history,
            )

        context["node_assigned_approver_user_ids"] = node_assigned_approver_user_ids
        context["node_pending_approver_user_ids"] = node_pending_approver_user_ids
        context["node_decided_approver_user_ids"] = node_decided_approver_user_ids
        return context

    def _assignment_eval_context(
        self,
        request_record=False,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        actor_user=False,
    ):
        context = {}
        if request_record and hasattr(request_record, "get_safe_eval_context"):
            try:
                context = dict(request_record.get_safe_eval_context() or {})
            except Exception:
                context = {}
        if request_record:
            request_record = request_record.sudo()
            eval_record = eval_record.sudo() if getattr(eval_record, "sudo", False) else eval_record
            domain_record = eval_record or request_record
            if eval_record:
                request_proxy = _WorkflowAssignmentRequestProxy(eval_record, request_record)
                context["request"] = request_proxy
                context["object"] = request_proxy
                context.setdefault("form_record", eval_record)
                context.setdefault("eval_record", eval_record)
                context.setdefault("approval_request", request_record)
                context.setdefault("base_request", request_record)
            else:
                context.setdefault("request", domain_record)
                context.setdefault("object", domain_record)
            self._inject_request_eval_values(
                context,
                request_record,
                eval_record=eval_record,
                snapshot_values=snapshot_values,
                simulated_history=simulated_history,
            )
        context.setdefault("env", self.env)
        actor = (actor_user or self.env.user).sudo()
        context.setdefault("user", actor)
        context.setdefault("uid", actor.id)
        context.setdefault("current_user_id", actor.id)
        context.setdefault("context", dict(self.env.context))
        # Keep these symbols always available so save-time domain validation
        # and runtime evaluation behave consistently.
        context.setdefault("request_owner_id", False)
        context.setdefault("request_owner_user_id", False)
        context.setdefault("request_creator_id", False)
        context.setdefault("request_creator_user_id", False)
        context.setdefault("manager_user_id", False)
        context.setdefault("request_creator_manager_user_id", False)
        context.setdefault("request_owner_manager_user_id", False)
        context.setdefault("request_owner_line_manager_user_id", False)
        context.setdefault("request_owner_department_id", False)
        context.setdefault("request_owner_department_manager_user_id", False)
        context.setdefault("request_owner_manager_chain_user_ids", [])
        context.setdefault("request_owner_team", False)
        context.setdefault("request_owner_team_code", False)
        context.setdefault("request_owner_line", False)
        context.setdefault("request_owner_line_code", False)
        context.setdefault("all_approver_user_ids", [])
        context.setdefault("decided_approver_user_ids", [])
        context.setdefault("has_decision_user_ids", [])
        context.setdefault("pending_approver_user_ids", [])
        context.setdefault("notification_submitter_and_decided_user_ids", [])
        context.setdefault("node_assigned_approver_user_ids", lambda node_id: [])
        context.setdefault("node_pending_approver_user_ids", lambda node_id: [])
        context.setdefault("node_decided_approver_user_ids", lambda node_id: [])
        return context

    def _expand_domain_symbol_values(self, domain, context):
        """Resolve Studio/JSON domains that store runtime symbols as strings."""
        if isinstance(domain, tuple):
            domain = list(domain)
        if not isinstance(domain, list):
            return self._resolve_domain_symbol_value(domain, context)
        if (
            len(domain) >= 3
            and isinstance(domain[0], str)
            and domain[0] not in ("&", "|", "!")
        ):
            expanded = list(domain)
            expanded[2] = self._resolve_domain_symbol_value(expanded[2], context)
            return expanded
        return [self._expand_domain_symbol_values(item, context) for item in domain]

    def _resolve_domain_symbol_value(self, value, context):
        if isinstance(value, tuple):
            return [self._resolve_domain_symbol_value(item, context) for item in value]
        if isinstance(value, list):
            return [self._resolve_domain_symbol_value(item, context) for item in value]
        if not isinstance(value, str):
            return value
        token = value.strip()
        if not token:
            return value
        direct_symbols = {
            "all_approver_user_ids",
            "decided_approver_user_ids",
            "has_decision_user_ids",
            "pending_approver_user_ids",
            "notification_submitter_and_decided_user_ids",
            "request_owner_manager_chain_user_ids",
        }
        if token in direct_symbols and token in context:
            return context[token]
        if (
            token in context
            and not callable(context[token])
            and isinstance(context[token], (bool, int, float, str, list, tuple, dict))
        ):
            return context[token]
        callable_prefixes = (
            "node_assigned_approver_user_ids(",
            "node_pending_approver_user_ids(",
            "node_decided_approver_user_ids(",
        )
        if token.startswith(callable_prefixes) and token.endswith(")"):
            try:
                return safe_eval(token, context)
            except Exception:
                return value
        return value

    def _normalize_domain_for_target_model(self, domain, target_model_name):
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
            normalized[0] = self._normalize_domain_field_for_target_model(
                normalized[0],
                target_model_name,
            )
            return normalized
        return [
            self._normalize_domain_for_target_model(item, target_model_name)
            for item in domain
        ]

    def _normalize_constant_workflow_domain(self, domain):
        if not isinstance(domain, (list, tuple)):
            return domain
        tokens = list(domain)
        if len(tokens) != 1:
            return domain
        leaf = tokens[0]
        if isinstance(leaf, tuple):
            leaf = list(leaf)
        if not isinstance(leaf, list) or len(leaf) < 3:
            return domain
        field_expr = leaf[0]
        operator = str(leaf[1] or "").strip().lower()
        expected = leaf[2]
        if operator != "=" or expected != 1:
            return domain
        if field_expr == 0:
            return False
        if field_expr == 1:
            return True
        return domain

    def _normalize_routing_domain_text(self, domain_literal):
        if domain_literal in (None, False):
            return ""
        if isinstance(domain_literal, str):
            return re.sub(r"[\u200B-\u200D\uFEFF]", "", domain_literal).strip()
        if isinstance(domain_literal, (list, tuple)):
            try:
                return json.dumps(list(domain_literal))
            except Exception:
                return str(domain_literal).strip()
        return str(domain_literal).strip()

    def _is_explicit_constant_workflow_domain(self, domain):
        if not isinstance(domain, (list, tuple)):
            return False
        tokens = list(domain)
        if len(tokens) != 1:
            return False
        leaf = tokens[0]
        if isinstance(leaf, tuple):
            leaf = list(leaf)
        if not isinstance(leaf, list) or len(leaf) < 3:
            return False
        operator = str(leaf[1] or "").strip().lower()
        expected = leaf[2]
        return operator == "=" and expected == 1 and leaf[0] in (0, 1)

    def _is_shorthand_constant_workflow_domain(self, domain):
        if isinstance(domain, tuple):
            domain = list(domain)
        if not isinstance(domain, list) or len(domain) < 3:
            return False
        if isinstance(domain[0], (list, tuple)):
            return False
        operator = str(domain[1] or "").strip().lower()
        expected = domain[2]
        return operator == "=" and expected == 1 and domain[0] in (0, 1)

    def _constant_routing_domain_state(self, domain):
        if not self._is_explicit_constant_workflow_domain(domain):
            return False
        normalized = self._normalize_constant_workflow_domain(domain)
        if normalized is True:
            return "always_true"
        if normalized is False:
            return "always_false"
        return False

    def _classify_routing_domain_literal(self, domain_literal, memo=False):
        normalized_text = self._normalize_routing_domain_text(domain_literal)
        details = {
            "domain": normalized_text,
            "domain_state": "active_valid",
            "ignored": False,
            "config_error": False,
            "error_message": "",
        }
        if not normalized_text:
            details["domain_state"] = "ignored_blank"
            details["ignored"] = True
            return details
        if normalized_text == "[]":
            details["domain_state"] = "ignored_empty"
            details["ignored"] = True
            return details
        parsed_domain = self._parse_domain_literal(domain_literal, memo=memo)
        if self._is_shorthand_constant_workflow_domain(parsed_domain):
            details["domain_state"] = "ignored_invalid"
            details["ignored"] = True
            details["config_error"] = True
            details["error_message"] = _(
                "Routing domain shorthand constants are ignored. Use [(1, '=', 1)] or [(0, '=', 1)]."
            )
            return details
        constant_state = self._constant_routing_domain_state(parsed_domain)
        if constant_state:
            details["domain_state"] = constant_state
        return details

    def _parse_domain_literal(self, domain_literal, memo=False):
        if not domain_literal:
            return []
        if isinstance(domain_literal, (list, tuple)):
            return list(domain_literal)
        cache_key = domain_literal if isinstance(domain_literal, str) else False
        if cache_key:
            cached = self._resolution_memo_bucket(memo, "parsed_domain_literals").get(cache_key)
            if isinstance(cached, list):
                return list(cached)
        try:
            parsed = json.loads(domain_literal)
            if isinstance(parsed, list):
                if cache_key:
                    self._resolution_memo_bucket(memo, "parsed_domain_literals")[cache_key] = list(parsed)
                return parsed
        except Exception:
            pass
        try:
            parsed = ast.literal_eval(domain_literal)
            if isinstance(parsed, list):
                if cache_key:
                    self._resolution_memo_bucket(memo, "parsed_domain_literals")[cache_key] = list(parsed)
                return parsed
        except Exception:
            pass
        if cache_key:
            self._resolution_memo_bucket(memo, "parsed_domain_literals")[cache_key] = []
        return []

    def eval_routing_user_domain(
        self,
        users,
        domain_literal,
        request_record=False,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        task_node_id=False,
        actor_user=False,
        return_details=False,
        memo=False,
    ):
        details = {
            "domain": self._normalize_routing_domain_text(domain_literal),
            "matched_user_ids": [],
            "config_error": False,
            "error_message": "",
            "domain_state": "active_valid",
            "ignored": False,
        }
        classification = self._classify_routing_domain_literal(domain_literal, memo=memo)
        details.update(classification)
        state = details.get("domain_state")
        if state == "always_true":
            details["matched_user_ids"] = users.ids
            return (users, details) if return_details else users
        if state in {"always_false", "ignored_blank", "ignored_empty", "ignored_invalid"}:
            empty = self.env["res.users"]
            return (empty, details) if return_details else empty

        context = self._assignment_eval_context(
            request_record=request_record,
            eval_record=eval_record,
            snapshot_values=snapshot_values,
            simulated_history=simulated_history,
            actor_user=actor_user,
        )
        parsed_domain = self._parse_domain_literal(domain_literal, memo=memo)
        if parsed_domain:
            try:
                parsed_domain = self._expand_domain_symbol_values(parsed_domain, context)
                parsed_domain = self._normalize_constant_workflow_domain(parsed_domain)
                if isinstance(parsed_domain, bool):
                    matched = users if parsed_domain else self.env["res.users"]
                    details["matched_user_ids"] = matched.ids
                    return (matched, details) if return_details else matched
                normalized = self._normalize_domain_for_target_model(
                    parsed_domain,
                    "res.users",
                )
                matched = users.sudo().filtered_domain(normalized)
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
            except Exception as error:
                details["domain_state"] = "ignored_invalid"
                details["ignored"] = True
                details["config_error"] = True
                details["error_message"] = str(error)
                _logger.warning("Invalid assignment routing user domain literal: %s", domain_literal)
                empty = self.env["res.users"]
                return (empty, details) if return_details else empty
        try:
            evaluated = safe_eval(domain_literal, context)
            if isinstance(evaluated, tuple):
                evaluated = list(evaluated)
            evaluated = self._normalize_constant_workflow_domain(evaluated)
            if isinstance(evaluated, bool):
                matched = users if evaluated else self.env["res.users"]
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
            if isinstance(evaluated, list):
                normalized = self._normalize_domain_for_target_model(
                    evaluated,
                    "res.users",
                )
                matched = users.sudo().filtered_domain(normalized)
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
        except Exception as error:
            details["domain_state"] = "ignored_invalid"
            details["ignored"] = True
            details["config_error"] = True
            details["error_message"] = str(error)
            _logger.warning("Invalid assignment routing user domain expression: %s", domain_literal)
        empty = self.env["res.users"]
        return (empty, details) if return_details else empty

    def match_routing_request_domain(
        self,
        request_record,
        domain_literal,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        task_node_id=False,
        actor_user=False,
        return_details=False,
        memo=False,
    ):
        details = {
            "domain": self._normalize_routing_domain_text(domain_literal),
            "matched": False,
            "config_error": False,
            "error_message": "",
            "domain_state": "active_valid",
            "ignored": False,
        }
        classification = self._classify_routing_domain_literal(domain_literal, memo=memo)
        details.update(classification)
        state = details.get("domain_state")
        if state == "always_true":
            details["matched"] = True
            return (True, details) if return_details else True
        if state in {"always_false", "ignored_blank", "ignored_empty", "ignored_invalid"}:
            return (False, details) if return_details else False
        if not request_record:
            details["matched"] = True
            return (True, details) if return_details else True

        target_record = eval_record or request_record
        field_rule_service = self.env["workflow.engine.field.rule.service"]
        cache_key = False
        if isinstance(memo, dict):
            cache_key = (
                request_record._name,
                request_record.id,
                target_record._name if target_record else "",
                target_record.id if target_record else 0,
                domain_literal,
                task_node_id or "",
                (actor_user or self.env.user).id,
                json.dumps(snapshot_values or {}, sort_keys=True, default=str),
            )
            cached = self._resolution_memo_bucket(memo, "routing_request_domain_matches").get(cache_key)
            if cached is not None:
                details["matched"] = bool(cached)
                return (bool(cached), details) if return_details else bool(cached)
        try:
            matched = field_rule_service.match_domain_expression(
                request_record=request_record,
                domain_expression=domain_literal,
                target_record=target_record,
                task_node_id=task_node_id,
                snapshot_values=snapshot_values or {},
                user=actor_user or self.env.user,
                simulated_history=simulated_history,
                raise_on_error=True,
                default=True,
            )
            details["matched"] = bool(matched)
            if cache_key:
                self._resolution_memo_bucket(memo, "routing_request_domain_matches")[cache_key] = bool(matched)
            return (bool(matched), details) if return_details else bool(matched)
        except Exception as error:
            details["matched"] = False
            details["domain_state"] = "ignored_invalid"
            details["ignored"] = True
            details["config_error"] = True
            details["error_message"] = str(error)
            _logger.warning("Invalid request routing domain expression for assignment: %s", domain_literal)
            return (False, details) if return_details else False

    def eval_user_domain(
        self,
        users,
        domain_literal,
        request_record=False,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        task_node_id=False,
        actor_user=False,
        return_details=False,
        memo=False,
    ):
        details = {
            "domain": domain_literal or "",
            "matched_user_ids": [],
            "config_error": False,
            "error_message": "",
        }
        if not domain_literal:
            details["matched_user_ids"] = users.ids
            return (users, details) if return_details else users
        context = self._assignment_eval_context(
            request_record=request_record,
            eval_record=eval_record,
            snapshot_values=snapshot_values,
            simulated_history=simulated_history,
            actor_user=actor_user,
        )
        parsed_domain = self._parse_domain_literal(domain_literal, memo=memo)
        if parsed_domain:
            try:
                parsed_domain = self._expand_domain_symbol_values(parsed_domain, context)
                parsed_domain = self._normalize_constant_workflow_domain(parsed_domain)
                if isinstance(parsed_domain, bool):
                    matched = users if parsed_domain else self.env["res.users"]
                    details["matched_user_ids"] = matched.ids
                    return (matched, details) if return_details else matched
                normalized = self._normalize_domain_for_target_model(
                    parsed_domain,
                    "res.users",
                )
                matched = users.sudo().filtered_domain(normalized)
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
            except Exception as error:
                details["config_error"] = True
                details["error_message"] = str(error)
                _logger.warning("Invalid assignment user domain literal: %s", domain_literal)
                empty = self.env["res.users"]
                return (empty, details) if return_details else empty
        try:
            evaluated = safe_eval(domain_literal, context)
            if isinstance(evaluated, tuple):
                evaluated = list(evaluated)
            evaluated = self._normalize_constant_workflow_domain(evaluated)
            if isinstance(evaluated, bool):
                matched = users if evaluated else self.env["res.users"]
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
            if isinstance(evaluated, list):
                normalized = self._normalize_domain_for_target_model(
                    evaluated,
                    "res.users",
                )
                matched = users.sudo().filtered_domain(normalized)
                details["matched_user_ids"] = matched.ids
                return (matched, details) if return_details else matched
        except Exception as error:
            details["config_error"] = True
            details["error_message"] = str(error)
            _logger.warning("Invalid assignment user domain expression: %s", domain_literal)
        empty = self.env["res.users"]
        return (empty, details) if return_details else empty

    def match_request_domain(
        self,
        request_record,
        domain_literal,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        task_node_id=False,
        actor_user=False,
        return_details=False,
        memo=False,
    ):
        details = {
            "domain": domain_literal or "",
            "matched": True,
            "config_error": False,
            "error_message": "",
        }
        if not request_record or not domain_literal:
            return (True, details) if return_details else True
        target_record = eval_record or request_record
        field_rule_service = self.env["workflow.engine.field.rule.service"]
        cache_key = False
        if isinstance(memo, dict):
            cache_key = (
                request_record._name,
                request_record.id,
                target_record._name if target_record else "",
                target_record.id if target_record else 0,
                domain_literal,
                task_node_id or "",
                (actor_user or self.env.user).id,
                json.dumps(snapshot_values or {}, sort_keys=True, default=str),
            )
            cached = self._resolution_memo_bucket(memo, "request_domain_matches").get(cache_key)
            if cached is not None:
                details["matched"] = bool(cached)
                return (bool(cached), details) if return_details else bool(cached)
        try:
            matched = field_rule_service.match_domain_expression(
                request_record=request_record,
                domain_expression=domain_literal,
                target_record=target_record,
                task_node_id=task_node_id,
                snapshot_values=snapshot_values or {},
                user=actor_user or self.env.user,
                simulated_history=simulated_history,
                raise_on_error=True,
                default=True,
            )
            details["matched"] = bool(matched)
            if cache_key:
                self._resolution_memo_bucket(memo, "request_domain_matches")[cache_key] = bool(matched)
            return (bool(matched), details) if return_details else bool(matched)
        except Exception as error:
            details["matched"] = False
            details["config_error"] = True
            details["error_message"] = str(error)
            _logger.warning("Invalid request domain expression for assignment: %s", domain_literal)
            return (False, details) if return_details else False


class WorkflowEngineAssignmentService(models.AbstractModel):
    _name = "workflow.engine.assignment.service"
    _description = "Workflow Engine Assignment Service"

    def _deduplicate_users(self, users):
        user_set = self.env["res.users"]
        seen = set()
        for user in users:
            if user.id and user.id not in seen:
                user_set |= user
                seen.add(user.id)
        return user_set

    def _all_active_non_portal_users(self):
        return self.env["res.users"].sudo().search([("active", "=", True), ("share", "=", False)])

    def _resolution_memo_bucket(self, memo, bucket_name):
        if not isinstance(memo, dict):
            return {}
        return memo.setdefault(bucket_name, {})

    def _memoized_all_active_non_portal_users(self, memo=False):
        bucket = self._resolution_memo_bucket(memo, "all_active_non_portal_users")
        cache_key = self.env.uid
        if cache_key not in bucket:
            bucket[cache_key] = self._all_active_non_portal_users()
        return bucket[cache_key]

    def _new_resolution_context(
        self,
        request_record=False,
        meta_task=False,
        task_node_id=False,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        debug=False,
        actor_user=False,
    ):
        return {
            "request_record": request_record,
            "meta_task": meta_task,
            "task_node_id": task_node_id or getattr(meta_task, "node_id", False),
            "eval_record": eval_record,
            "snapshot_values": snapshot_values if isinstance(snapshot_values, dict) else {},
            "simulated_history": simulated_history if isinstance(simulated_history, dict) else {},
            "debug": bool(debug),
            "actor_user": actor_user or self.env.user,
            "diagnostics": {
                "assignment_mode": getattr(meta_task, "assignment_mode", False) or "mixed",
                "needs_input": [],
                "config_errors": [],
                "group_links": [],
                "filters": [],
                "collector": {},
                "fallback": {},
                "share_override_user_ids": [],
            } if debug else {},
        }

    def _debug_payload(self, resolution_context):
        if not resolution_context or not resolution_context.get("debug"):
            return {}
        return resolution_context.setdefault("diagnostics", {})

    def _debug_add_config_error(self, resolution_context, scope, message, **payload):
        debug = self._debug_payload(resolution_context)
        if not debug:
            return
        debug.setdefault("config_errors", []).append(
            {
                "scope": scope,
                "message": message,
                **payload,
            }
        )

    def _debug_add_needs_input(self, resolution_context, source_node_id, user_type, reason):
        debug = self._debug_payload(resolution_context)
        if not debug:
            return
        debug.setdefault("needs_input", []).append(
            {
                "source_node_id": source_node_id or "",
                "user_type": user_type or "",
                "reason": reason,
            }
        )

    def _resolve_target_record_for_acl(self, request_record, eval_record=False):
        if not request_record:
            return request_record
        if eval_record:
            return eval_record
        if hasattr(request_record, "_get_transition_delegate_record"):
            try:
                return request_record._get_transition_delegate_record() or request_record
            except Exception:
                return request_record
        return request_record

    def _user_can_read_target(self, target_record, user):
        if not target_record or not user:
            return False
        try:
            self.env[target_record._name].with_user(user).browse().check_access("read")
        except Exception:
            return False
        return True

    def _filter_eligible_users(
        self,
        request_record,
        users,
        require_category_access=True,
        eval_record=False,
        return_details=False,
    ):
        permission_service = self.env["workflow.engine.permission.service"]
        target_record = self._resolve_target_record_for_acl(request_record, eval_record=eval_record)
        result = self.env["res.users"]
        details = []
        for user in users.filtered(lambda u: u.active and not u.share):
            reasons = []
            if not permission_service._has_approval_workflow_group(user):
                reasons.append("missing_workflow_group")
            if request_record.sudo().company_id and request_record.sudo().company_id not in user.sudo().company_ids:
                reasons.append("company_mismatch")
            if require_category_access and not permission_service.can_access_category(request_record.category_id, user=user):
                reasons.append("missing_category_access")
            if not self._user_can_read_target(target_record, user):
                reasons.append("missing_read_access")
            if reasons:
                details.append(
                    {
                        "user_id": user.id,
                        "user_name": user.name or "",
                        "eligible": False,
                        "reasons": reasons,
                    }
                )
                continue
            result |= user
            details.append(
                {
                    "user_id": user.id,
                    "user_name": user.name or "",
                    "eligible": True,
                    "reasons": [],
                }
            )
        return (result, details) if return_details else result

    def _collect_request_owner_candidates(self, request_record, meta_task=False, warnings=None, resolution_context=None):
        return request_record.request_owner_id

    def _collect_previous_actor_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        source_node_id = (meta_task.previous_actor_node_ref or "").strip()
        if not source_node_id:
            if warnings is not None:
                warnings.append(
                    _("Users From Workflow Node assignment has no source node configured.")
                )
            self._debug_add_config_error(
                resolution_context,
                "previous_actor",
                _("Users From Workflow Node assignment has no source node configured."),
                node_id=getattr(meta_task, "node_id", "") or "",
            )
            return self.env["res.users"]
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        user_type = meta_task.assignment_source_user_type or "decided"
        users = domain_service.node_approver_users(
            request_record,
            source_node_id,
            user_type=user_type,
            simulated_history=(resolution_context or {}).get("simulated_history"),
        )
        if not users:
            self._debug_add_needs_input(
                resolution_context,
                source_node_id=source_node_id,
                user_type=user_type,
                reason="missing_source_node_users",
            )
        return users

    def _collect_reentry_previous_actor_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        """Use the previous decider for a revisited stage; use normal config on first entry."""
        previous_node_ref = meta_task.previous_actor_node_ref or meta_task.node_id
        simulated_history = (resolution_context or {}).get("simulated_history")
        simulated_deciders = self.env[
            "workflow.engine.assignment.domain.service"
        ].node_approver_users(
            request_record,
            previous_node_ref,
            user_type="decided",
            simulated_history=simulated_history,
        )
        if simulated_deciders:
            return simulated_deciders[:1]
        history_rows = request_record.approver_ids.filtered(
            lambda a: bool((a.user_decision or "").strip())
            and a.current_meta_node_id == previous_node_ref
        ).sorted(
            key=lambda r: (r.iteration_no or 0, r.create_date or fields.Datetime.now(), r.id),
            reverse=True,
        )
        if history_rows:
            return history_rows[0].user_id
        self._debug_add_needs_input(
            resolution_context,
            source_node_id=previous_node_ref,
            user_type="decided",
            reason="missing_reentry_previous_actor",
        )
        return self._collect_mixed_candidates(
            request_record,
            meta_task,
            warnings=warnings,
            resolution_context=resolution_context,
        )

    def _collect_explicit_user_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        debug = self._debug_payload(resolution_context)
        if debug:
            debug["collector"]["explicit_user_ids"] = meta_task.explicit_user_ids.ids
        return meta_task.explicit_user_ids

    def _collect_group_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        warnings = warnings if warnings is not None else []
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        candidates = self.env["res.users"]
        resolution_context = resolution_context or {}
        eval_record = resolution_context.get("eval_record") or request_record
        snapshot_values = resolution_context.get("snapshot_values")
        simulated_history = resolution_context.get("simulated_history")
        actor_user = resolution_context.get("actor_user")
        debug = self._debug_payload(resolution_context)
        if meta_task.explicit_group_ids:
            candidates |= meta_task.explicit_group_ids.mapped("user_ids")
            if debug:
                debug["collector"]["explicit_group_ids"] = meta_task.explicit_group_ids.ids
        for link in meta_task.approval_group_link_ids:
            link_detail = {
                "link_id": link.id,
                "group_id": link.approval_group_id.id,
                "group_name": link.approval_group_id.name or "",
                "request_domain": link.domain or "",
                "user_domain": link.user_domain or "",
            }
            domain_match, domain_detail = domain_service.match_routing_request_domain(
                request_record,
                link.domain,
                eval_record=eval_record,
                snapshot_values=snapshot_values,
                simulated_history=simulated_history,
                task_node_id=resolution_context.get("task_node_id"),
                actor_user=actor_user,
                return_details=True,
                memo=resolution_context.setdefault("_memo", {}),
            )
            link_detail["request_domain_match"] = bool(domain_match)
            link_detail["request_domain_state"] = domain_detail.get("domain_state") or "active_valid"
            if domain_detail.get("config_error"):
                self._debug_add_config_error(
                    resolution_context,
                    "group_request_domain",
                    domain_detail.get("error_message") or _("Invalid group request domain."),
                    group_id=link.approval_group_id.id,
                    group_name=link.approval_group_id.name or "",
                    domain=link.domain,
                )
            if not domain_match:
                if debug:
                    debug.setdefault("group_links", []).append(link_detail)
                continue
            link_users = link.approval_group_id.user_ids
            filtered_users, user_domain_detail = domain_service.eval_routing_user_domain(
                link_users,
                link.user_domain,
                request_record=request_record,
                eval_record=eval_record,
                snapshot_values=snapshot_values,
                simulated_history=simulated_history,
                task_node_id=resolution_context.get("task_node_id"),
                actor_user=actor_user,
                return_details=True,
                memo=resolution_context.setdefault("_memo", {}),
            )
            link_detail["user_domain_match_ids"] = user_domain_detail.get("matched_user_ids") or []
            link_detail["user_domain_state"] = user_domain_detail.get("domain_state") or "active_valid"
            if user_domain_detail.get("config_error"):
                self._debug_add_config_error(
                    resolution_context,
                    "group_user_domain",
                    user_domain_detail.get("error_message") or _("Invalid group user domain."),
                    group_id=link.approval_group_id.id,
                    group_name=link.approval_group_id.name or "",
                    domain=link.user_domain,
                )
            if not filtered_users:
                warnings.append(
                    _(
                        "Skipped users from group '%s' because user domain matched no users "
                        "(or expression is invalid)."
                    )
                    % (link.approval_group_id.name or "")
                )
            link_users = filtered_users
            link_detail["resolved_user_ids"] = link_users.ids
            if debug:
                debug.setdefault("group_links", []).append(link_detail)
            candidates |= link_users
        return candidates

    def _collect_domain_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        resolution_context = resolution_context or {}
        users, details = domain_service.eval_routing_user_domain(
            self._memoized_all_active_non_portal_users(resolution_context.setdefault("_memo", {})),
            meta_task.assignment_user_domain,
            request_record=request_record,
            eval_record=resolution_context.get("eval_record"),
            snapshot_values=resolution_context.get("snapshot_values"),
            simulated_history=resolution_context.get("simulated_history"),
            task_node_id=resolution_context.get("task_node_id"),
            actor_user=resolution_context.get("actor_user"),
            return_details=True,
            memo=resolution_context.setdefault("_memo", {}),
        )
        if details.get("config_error"):
            self._debug_add_config_error(
                resolution_context,
                "assignment_user_domain",
                details.get("error_message") or _("Invalid assignment user domain."),
                domain=meta_task.assignment_user_domain,
            )
        debug = self._debug_payload(resolution_context)
        if debug:
            debug["collector"]["assignment_user_domain"] = details
        return users

    def _collect_meta_fallback_domain_candidates(self, request_record, meta_task, resolution_context=None):
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        resolution_context = resolution_context or {}
        users, details = domain_service.eval_routing_user_domain(
            self._memoized_all_active_non_portal_users(resolution_context.setdefault("_memo", {})),
            meta_task.approval_group_domain,
            request_record=request_record,
            eval_record=resolution_context.get("eval_record"),
            snapshot_values=resolution_context.get("snapshot_values"),
            simulated_history=resolution_context.get("simulated_history"),
            task_node_id=resolution_context.get("task_node_id"),
            actor_user=resolution_context.get("actor_user"),
            return_details=True,
            memo=resolution_context.setdefault("_memo", {}),
        )
        if details.get("config_error"):
            self._debug_add_config_error(
                resolution_context,
                "fallback_user_domain",
                details.get("error_message") or _("Invalid fallback user domain."),
                domain=meta_task.approval_group_domain,
            )
        debug = self._debug_payload(resolution_context)
        if debug:
            debug["fallback"]["domain_eval"] = details
        return users

    def _collect_mixed_candidates(self, request_record, meta_task, warnings=None, resolution_context=None):
        warnings = warnings if warnings is not None else []
        candidates = self.env["res.users"]
        candidates |= self._collect_explicit_user_candidates(
            request_record,
            meta_task,
            warnings=warnings,
            resolution_context=resolution_context,
        )
        candidates |= self._collect_group_candidates(
            request_record,
            meta_task,
            warnings=warnings,
            resolution_context=resolution_context,
        )
        candidates |= self._collect_domain_candidates(
            request_record,
            meta_task,
            warnings=warnings,
            resolution_context=resolution_context,
        )
        return candidates

    def _assignment_mode_collectors(self):
        """Return assignment-mode collector map.

        Override and extend this map in downstream modules to add new
        assignment strategies without rewriting core resolution flow.
        """
        return {
            "mixed": self._collect_mixed_candidates,
            "explicit_users": self._collect_explicit_user_candidates,
            "groups": self._collect_group_candidates,
            "domain": self._collect_domain_candidates,
            "previous_actor": self._collect_previous_actor_candidates,
            "reentry_previous_actor": self._collect_reentry_previous_actor_candidates,
            "request_owner": self._collect_request_owner_candidates,
        }

    def _resolve_assignment_mode_collector(self, mode):
        collectors = self._assignment_mode_collectors()
        collector = collectors.get(mode) or collectors.get("mixed")
        return collector or self._collect_mixed_candidates

    def _assignment_modes_with_meta_fallback(self):
        return {"mixed", "groups", "domain"}

    def _collect_candidates_by_mode(self, request_record, meta_task, warnings, resolution_context=None):
        mode = meta_task.assignment_mode or "mixed"
        collector = self._resolve_assignment_mode_collector(mode)
        candidates = collector(
            request_record,
            meta_task,
            warnings=warnings,
            resolution_context=resolution_context,
        )

        # Backward compatibility: explicit checkboxes are additive hints.
        if mode not in ("request_owner", "reentry_previous_actor") and meta_task.assign_to_request_owner:
            candidates |= self._collect_request_owner_candidates(
                request_record,
                meta_task,
                warnings=warnings,
            )
        if mode not in ("previous_actor", "reentry_previous_actor") and meta_task.assign_to_previous_actor:
            candidates |= self._collect_previous_actor_candidates(
                request_record,
                meta_task,
                warnings=warnings,
                resolution_context=resolution_context,
            )

        # Preserve legacy fallback behavior for group/domain-driven stages.
        if mode in self._assignment_modes_with_meta_fallback() and not candidates:
            candidates |= self._collect_meta_fallback_domain_candidates(
                request_record,
                meta_task,
                resolution_context=resolution_context,
            )
        debug = self._debug_payload(resolution_context)
        if debug:
            debug["collector"]["mode"] = mode
            debug["collector"]["candidate_user_ids"] = candidates.ids
        return self._deduplicate_users(candidates)

    def _apply_delegation(self, request_record, users):
        delegation_model = self.env["workflow.approval.delegation"].sudo()
        final_users = self.env["res.users"]
        delegation_map = []
        now = fields.Datetime.now()
        for user in users:
            delegations = delegation_model.search(
                [
                    ("delegator_user_id", "=", user.id),
                    ("active", "=", True),
                    ("date_from", "<=", now),
                    ("date_to", ">=", now),
                ],
                order="date_from desc, id desc",
            )
            delegation = delegations.select_best_for_category(request_record.category_id)
            if not delegation or not delegation.delegate_user_id:
                final_users |= user
                continue

            delegate = delegation.delegate_user_id
            strategy = delegation.assignment_strategy or "replace"
            if strategy == "cc_delegate":
                final_users |= user
                final_users |= delegate
            else:
                final_users |= delegate
            delegation_map.append(
                {
                    "original_user_id": user.id,
                    "delegate_user_id": delegate.id,
                    "strategy": strategy,
                    "source": delegation.delegation_source or "manual",
                }
            )
        return self._deduplicate_users(final_users), delegation_map

    def _apply_share_overrides(self, request_record, task_node_id=False):
        now = fields.Datetime.now()
        scopes = request_record.visibility_scope_ids.filtered(
            lambda s: s.active
            and s.scope == "decision"
            and (not s.expires_at or s.expires_at >= now)
            and (not task_node_id or not s.task_instance_id or s.task_instance_id.node_id == task_node_id)
        )
        users = scopes.mapped("allowed_user_id")
        groups = scopes.mapped("allowed_group_id")
        if groups:
            users |= groups.mapped("user_ids")
        return self._deduplicate_users(users.filtered(lambda u: u.active and not u.share))

    def _fallback_policy_block(self, request_record, meta_task):
        return self.env["res.users"]

    def _fallback_policy_escalate_manager(self, request_record, meta_task):
        if request_record and request_record.manager_user_id:
            return request_record.manager_user_id
        return self.env["res.users"]

    def _fallback_policy_route_admin_queue(self, request_record, meta_task):
        category = request_record.category_id
        if meta_task and meta_task.fallback_user_id:
            return meta_task.fallback_user_id
        if category.admin_queue_user_id:
            return category.admin_queue_user_id
        admin_group = self.env.ref(
            "workflow_engine.group_workflow_approval_admin",
            raise_if_not_found=False,
        )
        return admin_group.user_ids[:1] if admin_group else self.env["res.users"]

    def _fallback_policy_handlers(self):
        """Return fallback-policy handler map for open/closed extension."""
        return {
            "block": self._fallback_policy_block,
            "escalate_manager": self._fallback_policy_escalate_manager,
            "route_admin_queue": self._fallback_policy_route_admin_queue,
        }

    def _fallback_users(self, request_record, meta_task, policy):
        handlers = self._fallback_policy_handlers()
        handler = handlers.get(policy) or handlers.get("block") or self._fallback_policy_block
        users = handler(request_record, meta_task)
        if not users:
            return self.env["res.users"]
        return self._deduplicate_users(users)

    @api.model
    def resolve_assignees(
        self,
        request_record,
        meta_task,
        task_node_id=False,
        eval_record=False,
        snapshot_values=False,
        simulated_history=False,
        debug=False,
        actor_user=False,
    ):
        if not request_record or not meta_task:
            return {
                "candidate_user_ids": [],
                "final_user_ids": [],
                "delegation_map": [],
                "fallback_policy": "block",
                "blocked": True,
                "warnings": [_("Missing request or metadata task for assignment.")],
                "debug": {
                    "config_errors": [],
                    "needs_input": [],
                } if debug else {},
            }
        task_node_id = task_node_id or meta_task.node_id
        warnings = []
        resolution_context = self._new_resolution_context(
            request_record=request_record,
            meta_task=meta_task,
            task_node_id=task_node_id,
            eval_record=eval_record,
            snapshot_values=snapshot_values,
            simulated_history=simulated_history,
            debug=debug,
            actor_user=actor_user,
        )
        candidates = self._collect_candidates_by_mode(
            request_record,
            meta_task,
            warnings,
            resolution_context=resolution_context,
        )
        require_category_access = not request_record.category_id.allow_assignee_without_category_access
        eligible_result = self._filter_eligible_users(
            request_record,
            candidates,
            require_category_access=require_category_access,
            eval_record=eval_record,
            return_details=debug,
        )
        if debug:
            eligible, filter_details = eligible_result
            resolution_context["diagnostics"]["filters"] = filter_details
        else:
            eligible = eligible_result

        # 5) Delegation substitution
        final_users, delegation_map = self._apply_delegation(request_record, eligible)
        if debug:
            resolution_context["diagnostics"]["delegation_map"] = delegation_map

        # 6) Share override
        share_users = self._apply_share_overrides(request_record, task_node_id=task_node_id)
        if share_users:
            final_users |= share_users
            final_users = self._deduplicate_users(final_users)
        if debug:
            resolution_context["diagnostics"]["share_override_user_ids"] = share_users.ids

        # 7) Fallback
        fallback_policy = meta_task.fallback_policy or request_record.category_id.default_fallback_policy or "block"
        blocked = False
        fallback_user_ids = []
        if not final_users:
            fallback_users = self._fallback_users(request_record, meta_task, fallback_policy)
            if fallback_users:
                final_users |= fallback_users
                final_users = self._deduplicate_users(final_users)
                fallback_user_ids = fallback_users.ids
            else:
                blocked = True
        if debug:
            resolution_context["diagnostics"]["fallback"] = {
                "policy": fallback_policy,
                "user_ids": fallback_user_ids,
                "blocked": blocked and not final_users,
            }
            resolution_context["diagnostics"]["warnings"] = list(warnings)
            resolution_context["diagnostics"]["candidate_user_ids"] = candidates.ids
            resolution_context["diagnostics"]["eligible_user_ids"] = eligible.ids
            resolution_context["diagnostics"]["final_user_ids"] = final_users.ids

        return {
            "candidate_user_ids": candidates.ids,
            "eligible_user_ids": eligible.ids,
            "final_user_ids": final_users.ids,
            "delegation_map": delegation_map,
            "fallback_policy": fallback_policy,
            "blocked": blocked and not final_users,
            "warnings": warnings,
            "debug": resolution_context.get("diagnostics") if debug else {},
        }

    def _business_action_actor_enabled(self):
        context_value = self.env.context.get("workflow_business_action_actor_enabled")
        if context_value is not None:
            return bool(context_value)
        value = self.env["ir.config_parameter"].sudo().get_param(
            "workflow_engine.business_action_actor_enabled",
            "False",
        )
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _business_actions_for_task(self, request_record, task_instance):
        if not request_record or not task_instance or not request_record.version_id:
            return self.env["workflow.category.version.meta.task.action"]
        return request_record.version_id._get_user_action_by_node_id(
            task_instance.node_id
        ).filtered(
            lambda action: action.authorization_mode == "business_actor"
            and action.authorization_scope == "task"
        )

    def _resolve_business_action_users(self, request_record, task_instance, meta_action):
        Users = self.env["res.users"].sudo()
        users = Users
        sources_by_user = defaultdict(set)

        def add_source(records, source):
            nonlocal users
            records = records.filtered(lambda user: user.active)
            users |= records
            for user in records:
                sources_by_user[user.id].add(source)

        if meta_action.business_actor_include_owner and request_record.request_owner_id:
            add_source(request_record.request_owner_id, "request_owner")
        if meta_action.business_actor_include_creator and request_record.create_uid:
            add_source(request_record.create_uid, "request_creator")
        if meta_action.business_actor_include_node_assignees:
            node_users = task_instance.assignee_ids.filtered(
                lambda row: row.can_act
                and row.status in ("new", "pending", "in_progress", "rework")
            ).mapped("assignee_user_id")
            add_source(node_users, "node_assignees")
        add_source(meta_action.business_actor_user_ids, "explicit_users")
        add_source(meta_action.business_actor_group_ids.mapped("user_ids"), "system_groups")
        add_source(
            meta_action.business_actor_approval_group_ids.mapped("user_ids"),
            "approval_groups",
        )

        user_domain = (meta_action.business_actor_user_domain or "").strip()
        domain_details = {}
        if user_domain:
            candidates = Users.search([("active", "=", True), ("share", "=", False)])
            domain_users, domain_details = self.env[
                "workflow.engine.assignment.domain.service"
            ].eval_routing_user_domain(
                candidates,
                user_domain,
                request_record=request_record,
                task_node_id=task_instance.node_id,
                return_details=True,
            )
            add_source(domain_users, "user_domain")

        users = users.filtered(lambda user: user.active)
        snapshot = {
            "meta_action_id": meta_action.id,
            "task_instance_id": task_instance.id,
            "node_id": task_instance.node_id,
            "iteration_no": task_instance.iteration_no,
            "configured_sources": {
                "request_owner": bool(meta_action.business_actor_include_owner),
                "request_creator": bool(meta_action.business_actor_include_creator),
                "node_assignees": bool(meta_action.business_actor_include_node_assignees),
                "explicit_user_ids": meta_action.business_actor_user_ids.ids,
                "system_group_ids": meta_action.business_actor_group_ids.ids,
                "approval_group_ids": meta_action.business_actor_approval_group_ids.ids,
                "user_domain": user_domain,
            },
            "domain_details": domain_details,
        }
        return users, sources_by_user, snapshot

    def _ensure_business_actor_visibility(self, request_record, task_instance, user):
        permission_service = self.env["workflow.engine.permission.service"]
        if permission_service.can_access_request(request_record, user=user, scope="read"):
            return self.env["workflow.request.visibility.scope"]
        Scope = self.env["workflow.request.visibility.scope"].sudo()
        scope = Scope.search(
            [
                ("request_id", "=", request_record.id),
                ("task_instance_id", "=", task_instance.id),
                ("scope", "=", "read"),
                ("allowed_user_id", "=", user.id),
                ("active", "=", True),
            ],
            limit=1,
        )
        if not scope:
            scope = Scope.create(
                {
                    "request_id": request_record.id,
                    "task_instance_id": task_instance.id,
                    "scope": "read",
                    "allowed_user_id": user.id,
                    "reason": _("Business action actor for task '%s'.")
                    % (task_instance.node_name or task_instance.node_id),
                }
            )
        return scope

    def _sync_business_action_assignments(self, request_record, task_instance):
        Assignment = self.env["workflow.request.action.assignment"].sudo()
        if not self._business_action_actor_enabled():
            return Assignment
        actions = self._business_actions_for_task(request_record, task_instance)
        if not actions:
            return Assignment

        # Serialize activation/reconciliation for this exact task so two workers
        # cannot race between assignment lookup and creation.
        self.env.cr.execute(
            "SELECT id FROM workflow_request_task_instance WHERE id = %s FOR UPDATE",
            (task_instance.id,),
        )

        existing_rows = Assignment.search(
            [
                ("task_instance_id", "=", task_instance.id),
                ("meta_action_id", "in", actions.ids),
            ]
        )
        existing_by_key = {
            (
                row.meta_action_id.id,
                row.actor_user_id.id,
                row.original_actor_user_id.id,
            ): row
            for row in existing_rows
        }
        create_values = []
        result = Assignment
        for action in actions:
            users, sources_by_user, action_snapshot = self._resolve_business_action_users(
                request_record,
                task_instance,
                action,
            )
            for user in users:
                key = (action.id, user.id, user.id)
                source_snapshot = dict(action_snapshot)
                source_snapshot["matched_sources"] = sorted(sources_by_user.get(user.id, set()))
                existing = existing_by_key.get(key)
                if existing:
                    if existing.status == "open" and existing.can_act:
                        existing.sudo().write({"source_snapshot": source_snapshot})
                    result |= existing
                    continue
                visibility_scope = self._ensure_business_actor_visibility(
                    request_record,
                    task_instance,
                    user,
                )
                create_values.append(
                    {
                        "request_id": request_record.id,
                        "task_instance_id": task_instance.id,
                        "meta_action_id": action.id,
                        "scope": "task",
                        "actor_user_id": user.id,
                        "original_actor_user_id": user.id,
                        "status": "open",
                        "can_act": True,
                        "source_snapshot": source_snapshot,
                        "visibility_scope_id": visibility_scope.id if visibility_scope else False,
                    }
                )
        if create_values:
            result |= Assignment.create(create_values)
        return result

    def _open_business_action_assignments(
        self,
        request_record,
        user=False,
        node_id=False,
        meta_action=False,
    ):
        Assignment = self.env["workflow.request.action.assignment"].sudo()
        if not self._business_action_actor_enabled() or not request_record:
            return Assignment
        user = user or self.env.user
        domain = [
            ("request_id", "=", request_record.id),
            ("actor_user_id", "=", user.id),
            ("status", "=", "open"),
            ("can_act", "=", True),
            ("task_instance_id.is_active", "=", True),
        ]
        if node_id:
            domain.append(("node_id", "=", node_id))
        if meta_action:
            domain.append(("meta_action_id", "=", meta_action.id))
        return Assignment.search(domain)

    def _close_business_action_assignments(
        self,
        request_record,
        task_instance=False,
        node_id=False,
        iteration_no=False,
        reason=False,
    ):
        Assignment = self.env["workflow.request.action.assignment"].sudo()
        if not request_record:
            return Assignment
        domain = [
            ("request_id", "=", request_record.id),
        ]
        if task_instance:
            domain.append(("task_instance_id", "=", task_instance.id))
        if node_id:
            domain.append(("node_id", "=", node_id))
        if iteration_no:
            domain.append(("iteration_no", "=", iteration_no))
        rows = Assignment.search(domain)
        scopes = rows.mapped("visibility_scope_id").filtered("active")
        rows.mark_closed(reason=reason or _("Closed when the workflow task ended."))
        if scopes:
            scopes.sudo().write({"active": False})
        return rows

    def _delegate_business_action_assignments(
        self,
        request_record,
        source_user,
        target_user,
        mode,
        node_id=False,
        iteration_no=False,
        delegated_by=False,
        comment=False,
    ):
        Assignment = self.env["workflow.request.action.assignment"].sudo()
        source_rows = self._open_business_action_assignments(
            request_record,
            user=source_user,
            node_id=node_id,
        )
        if iteration_no:
            source_rows = source_rows.filtered(
                lambda row: (row.iteration_no or 1) == iteration_no
            )
        if not source_rows:
            return {"source_ids": [], "target_ids": []}
        self.env.cr.execute(
            "SELECT id FROM workflow_request_action_assignment WHERE id = ANY(%s) FOR UPDATE",
            (source_rows.ids,),
        )

        target_rows = Assignment.search(
            [
                ("task_instance_id", "in", source_rows.mapped("task_instance_id").ids),
                ("meta_action_id", "in", source_rows.mapped("meta_action_id").ids),
                ("actor_user_id", "=", target_user.id),
                ("original_actor_user_id", "in", source_rows.mapped("original_actor_user_id").ids),
            ]
        )
        target_by_key = {
            (
                row.task_instance_id.id,
                row.meta_action_id.id,
                row.original_actor_user_id.id,
            ): row
            for row in target_rows
        }
        created_or_reopened = Assignment
        create_values = []
        delegated_at = fields.Datetime.now()
        for source in source_rows:
            key = (
                source.task_instance_id.id,
                source.meta_action_id.id,
                source.original_actor_user_id.id,
            )
            snapshot = dict(source.source_snapshot or {})
            snapshot["delegation"] = {
                "mode": mode,
                "source_assignment_id": source.id,
                "source_user_id": source_user.id,
                "target_user_id": target_user.id,
                "delegated_by_user_id": (delegated_by or self.env.user).id,
                "delegated_at": fields.Datetime.to_string(delegated_at),
                "comment": comment or "",
            }
            visibility_scope = self._ensure_business_actor_visibility(
                request_record,
                source.task_instance_id,
                target_user,
            )
            existing = target_by_key.get(key)
            values = {
                "delegated_from_user_id": source_user.id,
                "delegated_by_user_id": (delegated_by or self.env.user).id,
                "delegation_mode": mode,
                "status": "open",
                "can_act": True,
                "assigned_at": delegated_at,
                "acted_at": False,
                "closed_at": False,
                "close_reason": False,
                "source_snapshot": snapshot,
                "visibility_scope_id": visibility_scope.id if visibility_scope else False,
            }
            if existing:
                existing.sudo().write(values)
                created_or_reopened |= existing
            else:
                create_values.append(
                    {
                        **values,
                        "request_id": request_record.id,
                        "task_instance_id": source.task_instance_id.id,
                        "meta_action_id": source.meta_action_id.id,
                        "scope": "task",
                        "actor_user_id": target_user.id,
                        "original_actor_user_id": source.original_actor_user_id.id,
                    }
                )
        if create_values:
            created_or_reopened |= Assignment.create(create_values)
        if mode == "redirected":
            source_rows.mark_closed(
                status="redirected",
                reason=_("Redirected to %s.") % target_user.display_name,
            )
        return {"source_ids": source_rows.ids, "target_ids": created_or_reopened.ids}

    def _record_business_action(
        self,
        request_record,
        meta_action,
        actor_user=False,
        comment=False,
        execute_path=False,
        idempotency_key=False,
        challenge=False,
    ):
        actor_user = actor_user or self.env.user
        if (meta_action.authorization_mode or "approval_actor") != "business_actor":
            raise ValidationError(_("Only business actions can use business-action accounting."))
        self.env["workflow.engine.permission.service"].assert_can_execute_action(
            child_record=request_record,
            request_record=request_record,
            meta_action=meta_action,
            user=actor_user,
        )
        rows = self._open_business_action_assignments(
            request_record,
            user=actor_user,
            node_id=meta_action.source_id,
            meta_action=meta_action,
        )
        task_instance = rows[:1].task_instance_id
        if rows:
            values = {"acted_at": fields.Datetime.now()}
            if not execute_path:
                values.update({"status": "acted", "can_act": False})
            rows.sudo().write(values)
        payload = {
            "authorization_mode": "business_actor",
            "meta_action_id": meta_action.id,
            "meta_action_name": meta_action.name or "",
            "action_assignment_ids": rows.ids,
            "task_instance_id": task_instance.id if task_instance else False,
            "execute_path": bool(execute_path),
        }
        return self.env["workflow.engine.audit.service"].log_event(
            request_record=request_record,
            task_instance=task_instance,
            event_type="action",
            action_key=meta_action.name or meta_action.attr_label,
            from_node_id=meta_action.source_id,
            to_node_id=meta_action.target_id,
            actor_user=actor_user,
            comment=comment,
            payload=payload,
            idempotency_key=idempotency_key,
            challenge=challenge,
        )

    def _upsert_task_assignees(self, task_instance, users, delegation_map=False):
        delegation_map = delegation_map or []
        assignee_model = self.env["workflow.request.task.assignee"].sudo()
        mapping = {item.get("delegate_user_id"): item.get("original_user_id") for item in delegation_map}
        result_rows = assignee_model.browse()
        for user in users:
            existing = assignee_model.search(
                [
                    ("task_instance_id", "=", task_instance.id),
                    ("assignee_user_id", "=", user.id),
                ],
                limit=1,
            )
            values = {
                "task_instance_id": task_instance.id,
                "assignee_user_id": user.id,
                "original_user_id": mapping.get(user.id) or user.id,
                "status": "new",
                "can_act": True,
            }
            if existing:
                existing.write(
                    {
                        "original_user_id": values["original_user_id"],
                        "status": "new" if existing.status in ("closed", "skipped") else existing.status,
                        "can_act": True,
                    }
                )
                result_rows |= existing
            else:
                result_rows |= assignee_model.create(values)
        return result_rows

    def create_or_sync_task_instance_from_legacy(
        self,
        request_record,
        meta_task,
        previous_meta_task=False,
        iteration_no=False,
    ):
        if not request_record or not meta_task:
            return self.env["workflow.request.task.instance"]
        task_model = self.env["workflow.request.task.instance"].sudo()
        assignee_model = self.env["workflow.request.task.assignee"].sudo()
        audit_service = self.env["workflow.engine.audit.service"]

        iteration_no = iteration_no or request_record.current_iteration_no or 1
        existing = task_model.search(
            [
                ("request_id", "=", request_record.id),
                ("node_id", "=", meta_task.node_id),
                ("iteration_no", "=", iteration_no),
                ("status", "in", ["new", "pending", "in_progress", "blocked", "rework"]),
            ],
            order="id desc",
            limit=1,
        )
        task_instance = existing
        if not task_instance:
            task_instance = task_model.create(
                {
                    "request_id": request_record.id,
                    "node_id": meta_task.node_id,
                    "node_name": meta_task.name,
                    "node_type": meta_task.node_type,
                    "status": "pending",
                    "required": True,
                    "completion_mode": meta_task.completion_mode or "any",
                    "iteration_no": iteration_no,
                    "join_key": meta_task.join_key or False,
                    "gateway_node_id": meta_task.gateway_node_id or False,
                    "join_policy": meta_task.join_policy or "all_of",
                    "join_min_n": meta_task.join_min_n or 0,
                    "reject_policy": meta_task.parallel_reject_policy or "strict",
                    "started_at": fields.Datetime.now(),
                }
            )

        open_approvers = request_record.approver_ids.filtered(
            lambda a: a.current_meta_id.id == meta_task.id
            and (a.iteration_no or 1) == iteration_no
            and a.status in ("new", "pending", "waiting")
        )
        if open_approvers:
            final_users = open_approvers.mapped("user_id")
            delegation_map = []
            resolution = {
                "candidate_user_ids": final_users.ids,
                "final_user_ids": final_users.ids,
                "delegation_map": [],
                "fallback_policy": meta_task.fallback_policy or "block",
                "blocked": False,
                "warnings": [],
            }
        else:
            resolution = self.resolve_assignees(request_record, meta_task, task_node_id=meta_task.node_id)
            final_users = self.env["res.users"].browse(resolution["final_user_ids"])
            delegation_map = resolution["delegation_map"]

        assignees = self._upsert_task_assignees(task_instance, final_users, delegation_map=delegation_map)
        if assignees:
            task_instance.mark_status("pending")
        elif resolution.get("blocked"):
            task_instance.mark_status("blocked", reason=_("No assignee resolved by assignment policy."))

        assignment_payload = {
            "source": "legacy_sync",
            "meta_task_id": meta_task.id,
            "meta_task_name": meta_task.name,
            "previous_meta_task_id": previous_meta_task.id if previous_meta_task else False,
            "resolution": resolution,
            "assignee_user_ids": assignees.mapped("assignee_user_id").ids,
        }
        has_assignment_event = self.env["workflow.request.task.event"].sudo().search_count(
            [
                ("request_id", "=", request_record.id),
                ("task_instance_id", "=", task_instance.id),
                ("event_type", "=", "assignment"),
            ]
        )
        if not has_assignment_event:
            audit_service.log_event(
                request_record=request_record,
                task_instance=task_instance,
                event_type="assignment",
                from_node_id=previous_meta_task.node_id if previous_meta_task else False,
                to_node_id=meta_task.node_id,
                payload=assignment_payload,
            )
        self._sync_business_action_assignments(request_record, task_instance)
        return task_instance


class WorkflowEngineLegacyAdapterService(models.AbstractModel):
    _name = "workflow.engine.legacy.adapter.service"
    _description = "Workflow Engine Legacy Adapter Service"

    def _build_assignment_remark(self, current_meta_task, resolution, assignee_user):
        stage_name = current_meta_task.name or current_meta_task.node_id or _("Unknown Stage")
        mode = current_meta_task.assignment_mode or "mixed"
        fallback_policy = (
            resolution.get("fallback_policy")
            or current_meta_task.fallback_policy
            or "block"
        )

        delegation_map = resolution.get("delegation_map") or []
        delegated_from_id = False
        for item in delegation_map:
            if item.get("delegate_user_id") == assignee_user.id:
                delegated_from_id = item.get("original_user_id")
                break
        if delegated_from_id:
            original_user = self.env["res.users"].browse(delegated_from_id)
            return _(
                "Auto-added via delegation from '%(delegator)s' during stage '%(stage)s'."
            ) % {
                "delegator": original_user.name or _("Unknown User"),
                "stage": stage_name,
            }

        if resolution.get("candidate_user_ids"):
            return _(
                "Auto-added by assignment mode '%(mode)s' during stage '%(stage)s'."
            ) % {
                "mode": mode,
                "stage": stage_name,
            }

        return _(
            "Auto-added by fallback policy '%(policy)s' during stage '%(stage)s'."
        ) % {
            "policy": fallback_policy,
            "stage": stage_name,
        }

    @api.model
    def is_unassigned_stage_reason(self, reason):
        normalized = (reason or "").strip().lower()
        if not normalized:
            return False
        return (
            "no approvers were added at stage" in normalized
            and "no users matched assignment policy" in normalized
        )

    @api.model
    def build_unassigned_stage_reason(self, current_meta_task, resolution=False):
        stage_name = (
            current_meta_task.name
            if current_meta_task and current_meta_task.name
            else current_meta_task.node_id if current_meta_task else _("Unknown Stage")
        )
        base = _(
            "No approvers were added at stage %s — no users matched assignment policy."
        ) % (stage_name,)
        warnings = (resolution or {}).get("warnings") or []
        if warnings:
            return "%s %s" % (base, " ".join(warnings))
        return base

    @api.model
    def prepare_legacy_approver_rows(
        self,
        request_record,
        current_meta_task,
        previous_meta_task=False,
        iteration_no=False,
        existing_keys=False,
        eval_record=None,
    ):
        """Resolve approvers and build row dicts for the given stage.

        ``request_record`` must be the ``workflow.base.approval.request`` record
        so that ``request_id`` on approver rows is correct.

        ``eval_record`` is the child model record (e.g. ``x_it_change_request``)
        whose fields are used when evaluating ``link.domain`` / ``user_domain``
        expressions.  Child models carry custom fields (e.g. ``x_it_session_id``)
        that do not exist on the base request table.  When omitted, ``request_record``
        is used for evaluation — which silently fails for any domain that references
        child-model fields.
        """
        if not request_record or not current_meta_task:
            return {
                "approver_data_list": [],
                "matched_any": False,
                "resolution": {},
            }

        assignment_service = self.env["workflow.engine.assignment.service"]
        resolution = assignment_service.resolve_assignees(
            request_record=request_record,
            meta_task=current_meta_task,
            task_node_id=current_meta_task.node_id,
            eval_record=eval_record,
        )
        final_users = self.env["res.users"].browse(resolution.get("final_user_ids") or [])
        rows = []
        existing = set(existing_keys or set())
        previous_meta_id = previous_meta_task.id if previous_meta_task else False
        row_iteration = iteration_no or request_record.current_iteration_no or 1

        for user in final_users.sorted(key=lambda u: u.id):
            key = (
                user.id,
                current_meta_task.id,
                previous_meta_id,
                row_iteration,
            )
            if key in existing:
                continue
            existing.add(key)
            rows.append(
                {
                    "user_id": user.id,
                    "status": "new",
                    "required": True,
                    "sequence": 10,
                    "iteration_no": row_iteration,
                    "request_id": request_record.id,
                    "current_meta_id": current_meta_task.id,
                    "previous_meta_id": previous_meta_id,
                    "remark": self._build_assignment_remark(
                        current_meta_task=current_meta_task,
                        resolution=resolution,
                        assignee_user=user,
                    ),
                }
            )

        return {
            "approver_data_list": rows,
            "matched_any": bool(final_users),
            "resolution": resolution,
        }


class WorkflowEngineRuntimeService(models.AbstractModel):
    _name = "workflow.engine.runtime.service"
    _description = "Workflow Engine Runtime Service"

    def lock_request(self, request_record):
        if not request_record:
            return
        request_record.ensure_one()
        try:
            self.env.cr.execute(
                """
                SELECT id
                  FROM workflow_base_approval_request
                 WHERE id = %s
                 FOR UPDATE NOWAIT
                """,
                (request_record.id,),
            )
        except Exception as error:
            raise UserError(
                _(
                    "This request is being processed by another user. Please retry."
                )
            ) from error

    def _close_branch_approval_activities(self, request_record, approver_rows):
        if not request_record or not approver_rows:
            return self.env["mail.activity"]
        activity_type = self.env.ref(
            "workflow_engine.mail_activity_data_workflow_approval",
            raise_if_not_found=False,
        )
        if not activity_type:
            return self.env["mail.activity"]

        targets = []
        model_name = request_record.res_model_name or request_record._name
        if model_name == request_record._name:
            targets.append((request_record._name, request_record.id))
        else:
            try:
                child_model = self.env[model_name]
            except KeyError:
                child_model = False
            if child_model is not False and "x_approval_base_id" in child_model._fields:
                children = child_model.sudo().search(
                    [("x_approval_base_id", "=", request_record.id)]
                )
                targets.extend((child._name, child.id) for child in children)
        if not targets:
            return self.env["mail.activity"]

        expected_pairs = {
            (row.user_id.id, row.current_meta_id.name or "")
            for row in approver_rows
            if row.user_id and row.current_meta_id
        }
        if not expected_pairs:
            return self.env["mail.activity"]
        Activity = self.env["mail.activity"].sudo()
        matched = Activity
        for target_model, target_id in targets:
            candidates = Activity.search(
                [
                    ("res_model", "=", target_model),
                    ("res_id", "=", target_id),
                    ("activity_type_id", "=", activity_type.id),
                    ("user_id", "in", list(approver_rows.mapped("user_id").ids)),
                    ("date_done", "=", False),
                ]
            )
            matched |= candidates.filtered(
                lambda activity: (activity.user_id.id, activity.summary or "")
                in expected_pairs
            )
        if matched:
            matched.unlink()
        return matched

    def _close_runtime_branch_state(
        self,
        request_record,
        branch_node_id,
        reason=False,
        iteration_no=False,
        decision_if_blank=False,
        comment_if_blank=False,
    ):
        """Close one task branch without recording an approval decision."""
        request_record.ensure_one()
        active_iteration = iteration_no or request_record.current_iteration_no or 1
        Approver = self.env["workflow.approval.approver"]
        open_rows = request_record.approver_ids.filtered(
            lambda row: row.current_meta_node_id == branch_node_id
            and (row.iteration_no or 1) == active_iteration
            and row.status in ("new", "pending", "waiting")
        )
        self._close_branch_approval_activities(request_record, open_rows)
        if open_rows:
            if decision_if_blank:
                is_routed_audit = Approver._is_routed_audit_decision_value(
                    decision_if_blank
                )
                decided_rows = open_rows.filtered(
                    lambda row: Approver._has_decision_text(row.user_decision)
                )
                undecided_rows = open_rows - decided_rows
                if undecided_rows:
                    values = {
                        "status": "closed",
                        "user_decision": decision_if_blank,
                        "is_routed_audit": is_routed_audit,
                    }
                    if comment_if_blank:
                        values["comment"] = comment_if_blank
                    undecided_rows.sudo().write(values)
                if decided_rows:
                    decided_rows.sudo().write({"status": "closed"})
            else:
                open_rows.sudo().write({"status": "closed"})

        tasks = self.env["workflow.request.task.instance"].sudo().search(
            [
                ("request_id", "=", request_record.id),
                ("node_id", "=", branch_node_id),
                ("iteration_no", "=", active_iteration),
                ("status", "in", ["new", "pending", "in_progress", "blocked", "rework"]),
            ]
        )
        for task in tasks:
            task.assignee_ids.filtered(
                lambda row: row.status in ("new", "pending", "in_progress", "rework")
            ).sudo().write({"status": "closed"})
            task.mark_status(
                "closed",
                reason=reason or _("Closed by workflow branch cleanup."),
            )

        automations = self.env["workflow.request.automation.instance"].sudo().search(
            [
                ("request_id", "=", request_record.id),
                ("iteration_no", "=", active_iteration),
                ("status", "in", ["new", "scheduled", "running"]),
                "|",
                ("branch_node_id", "=", branch_node_id),
                ("node_id", "=", branch_node_id),
            ]
        )
        if automations:
            automations.mark_cancelled(
                reason or _("Cancelled by workflow branch cleanup.")
            )
        return {
            "approvers": open_rows,
            "task_instances": tasks,
            "automation_instances": automations,
        }

    def _decision_status_rules(self):
        """Ordered decision keyword rules -> task status.

        Override and append in inherited modules for custom decision labels.
        """
        return (
            ("rejected", ("reject", "refuse")),
            ("rework", ("rework",)),
            ("cancelled", ("cancel",)),
        )

    def _decision_to_status(self, decision):
        text = (decision or "").strip().lower()
        for status, keywords in self._decision_status_rules():
            if any(keyword in text for keyword in keywords):
                return status
        return "approved"

    def evaluate_join_policy(self, task_instance):
        task_instance.ensure_one()
        if not task_instance.join_key:
            return {"satisfied": True, "reason": "no_join_key"}
        siblings = self.env["workflow.request.task.instance"].sudo().search(
            [
                ("request_id", "=", task_instance.request_id.id),
                ("iteration_no", "=", task_instance.iteration_no),
                ("join_key", "=", task_instance.join_key),
                ("required", "=", True),
            ]
        )
        if not siblings:
            return {"satisfied": True, "reason": "no_required_siblings"}

        approved_count = len(siblings.filtered(lambda t: t.status == "approved"))
        rejected_count = len(siblings.filtered(lambda t: t.status == "rejected"))
        total_required = len(siblings)

        policy = task_instance.join_policy or "all_of"
        if task_instance.reject_policy == "strict" and rejected_count:
            return {
                "satisfied": False,
                "rejected": True,
                "reason": "strict_reject",
                "approved_count": approved_count,
                "total_required": total_required,
            }

        if policy == "any_of":
            satisfied = approved_count >= 1
        elif policy == "min_n":
            min_n = max(1, task_instance.join_min_n or 1)
            satisfied = approved_count >= min_n
        else:
            satisfied = approved_count >= total_required

        return {
            "satisfied": satisfied,
            "rejected": False,
            "reason": policy,
            "approved_count": approved_count,
            "total_required": total_required,
        }

    def _close_other_assignees_if_any_mode(self, task_instance, winner_assignee):
        if task_instance.completion_mode != "any":
            return
        task_instance.action_close_remaining_assignees(winner_assignee_id=winner_assignee.id if winner_assignee else False)

    def record_decision_from_legacy(
        self,
        request_record,
        meta_action,
        actor_user=False,
        on_behalf_user=False,
        comment=False,
        idempotency_key=False,
        challenge=False,
    ):
        if not request_record or not meta_action:
            return self.env["workflow.request.task.instance"]
        actor_user = actor_user or self.env.user
        assignment_service = self.env["workflow.engine.assignment.service"]
        audit_service = self.env["workflow.engine.audit.service"]
        task_model = self.env["workflow.request.task.instance"].sudo()
        assignee_model = self.env["workflow.request.task.assignee"].sudo()

        iteration_no = request_record.current_iteration_no or 1
        task_instance = task_model.search(
            [
                ("request_id", "=", request_record.id),
                ("node_id", "=", meta_action.source_id),
                ("iteration_no", "=", iteration_no),
                ("status", "in", ["new", "pending", "in_progress", "blocked", "rework"]),
            ],
            order="id desc",
            limit=1,
        )
        source_meta = request_record.version_id.meta_task_ids.filtered(
            lambda t: t.node_id == meta_action.source_id
        )[:1]
        if not task_instance and source_meta:
            task_instance = assignment_service.create_or_sync_task_instance_from_legacy(
                request_record=request_record,
                meta_task=source_meta,
                iteration_no=iteration_no,
            )
        if not task_instance:
            return task_instance

        effective_user = on_behalf_user or actor_user
        assignee = assignee_model.search(
            [
                ("task_instance_id", "=", task_instance.id),
                ("assignee_user_id", "=", effective_user.id),
            ],
            limit=1,
        )
        if not assignee:
            assignee = assignee_model.create(
                {
                    "task_instance_id": task_instance.id,
                    "assignee_user_id": effective_user.id,
                    "original_user_id": effective_user.id,
                    "status": "new",
                    "can_act": True,
                }
            )
        decision_status = self._decision_to_status(meta_action.name)
        assignee_values = {
            "status": decision_status,
            "decision": meta_action.name,
            "decision_at": fields.Datetime.now(),
            "comment": comment or False,
        }
        if on_behalf_user:
            assignee_values["delegated_from_user_id"] = on_behalf_user.id
        assignee.sudo().write(assignee_values)

        if decision_status == "approved":
            self._close_other_assignees_if_any_mode(task_instance, assignee)
            if task_instance.completion_mode == "all":
                remaining = task_instance.assignee_ids.filtered(
                    lambda a: a.status in ("new", "pending", "in_progress")
                )
                if not remaining:
                    task_instance.mark_status("approved")
            else:
                task_instance.mark_status("approved")
        elif decision_status == "rejected":
            task_instance.mark_status("rejected")
            if task_instance.reject_policy == "strict" and task_instance.join_key:
                siblings = task_model.search(
                    [
                        ("request_id", "=", request_record.id),
                        ("iteration_no", "=", task_instance.iteration_no),
                        ("join_key", "=", task_instance.join_key),
                        ("id", "!=", task_instance.id),
                        ("status", "in", ["new", "pending", "in_progress", "rework", "blocked"]),
                    ]
                )
                for sibling in siblings:
                    sibling.mark_status("cancelled", reason=_("Cancelled by strict parallel reject policy."))
        elif decision_status == "rework":
            task_instance.mark_status("rework")
        elif decision_status == "cancelled":
            task_instance.mark_status("cancelled")

        payload = {
            "source": "legacy_sync",
            "meta_action_id": meta_action.id,
            "meta_action_name": meta_action.name,
            "task_instance_id": task_instance.id,
            "assignee_id": assignee.id,
            "completion_mode": task_instance.completion_mode,
            "join_policy": task_instance.join_policy,
        }
        event = audit_service.log_event(
            request_record=request_record,
            task_instance=task_instance,
            task_assignee=assignee,
            event_type="decision",
            action_key=meta_action.name,
            decision=meta_action.name,
            from_node_id=meta_action.source_id,
            to_node_id=meta_action.target_id,
            actor_user=actor_user,
            on_behalf_of_user=on_behalf_user,
            comment=comment,
            payload=payload,
            idempotency_key=idempotency_key,
            challenge=challenge,
        )
        return event


class WorkflowEngineFieldRuleService(models.AbstractModel):
    _name = "workflow.engine.field.rule.service"
    _description = "Workflow Engine Field Rule Service"

    _WORKFLOW_NODE_POLICY_PREFIX = "__wf_node__:"
    _WORKFLOW_NODE_VISIBLE_TAGS = {"group"}
    _META_BUILTIN_DEFAULT_VISIBLE_FIELD_NAMES = {
        "id",
        "display_name",
        "create_uid",
        "create_date",
        "write_uid",
        "write_date",
        "__last_update",
        "required_fields",
        "readonly_fields",
        "invisible_fields",
        "visible_buttons",
        "current_node_id",
        "wf_current_node_id",
        "wf_action_key",
        "previous_activity_name",
        "current_activity_name",
        "next_activity_name",
        "next_action_label",
        "workflow_category_label",
        "workflow_version_label",
        "request_status",
        "pending_approver_summary",
        "latest_transition_summary",
        "active_branch_node_ids",
        "branch_mode",
        "branch_progress_summary",
        "branch_active_count",
        "wf_is_blocked",
        "wf_block_badge",
        "wf_block_reason",
    }

    _WF_MAX_DOMAIN_EXPR_LENGTH = 4096
    _WF_MAX_DOMAIN_DEPTH = 16
    _WF_MAX_DOMAIN_LEAFS = 120
    _WF_MAX_DOMAIN_ITEMS = 256
    _WF_MAX_DOMAIN_STRING_LENGTH = 512

    def _user_effective_groups(self, user):
        return self.env["workflow.engine.permission.service"]._user_effective_groups(user)

    def _user_effective_group_ids(self, user):
        return self.env["workflow.engine.permission.service"]._user_effective_group_ids(user)

    _WF_DOMAIN_OPERATORS = {
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

    @api.model
    @ormcache("target_model_name", "field_path")
    def _domain_field_path_exists(self, target_model_name, field_path):
        if not target_model_name or not field_path:
            return False
        try:
            current_model = self.env[target_model_name]
        except KeyError:
            return False
        segments = field_path.split(".")
        for index, segment in enumerate(segments):
            field = current_model._fields.get(segment)
            if not field:
                return False
            if index == len(segments) - 1:
                return True
            if field.type not in ("many2one", "one2many", "many2many") or not field.comodel_name:
                return False
            try:
                current_model = self.env[field.comodel_name]
            except KeyError:
                return False
        return False

    def _value_from_record(self, record, field_name):
        if not field_name or field_name not in record._fields:
            return None
        value = record[field_name]
        if hasattr(value, "id"):
            return value.id
        return value

    def _evaluate_simple_condition(self, record, condition, context):
        if not isinstance(condition, dict):
            return False

        if "all" in condition:
            return all(self._evaluate_simple_condition(record, c, context) for c in condition.get("all", []))
        if "any" in condition:
            return any(self._evaluate_simple_condition(record, c, context) for c in condition.get("any", []))
        if "not" in condition:
            return not self._evaluate_simple_condition(record, condition.get("not"), context)

        if "field" in condition:
            field_name = condition.get("field")
            operator = condition.get("op", "=")
            expected = condition.get("value")
            actual = self._value_from_record(record, field_name)
            if operator in ("=", "=="):
                return actual == expected
            if operator in ("!=", "<>"):
                return actual != expected
            if operator == ">":
                return actual is not None and expected is not None and actual > expected
            if operator == "<":
                return actual is not None and expected is not None and actual < expected
            if operator == ">=":
                return actual is not None and expected is not None and actual >= expected
            if operator == "<=":
                return actual is not None and expected is not None and actual <= expected
            if operator == "in":
                return actual in (expected or [])
            if operator == "not_in":
                return actual not in (expected or [])
            if operator == "contains":
                if actual is None:
                    return False
                return str(expected) in str(actual)
            return False

        if "user_id" in condition:
            return context.get("user_id") == condition.get("user_id")
        if "user_group_xmlid" in condition:
            xmlid = condition.get("user_group_xmlid")
            group = self.env.ref(xmlid, raise_if_not_found=False)
            return bool(group and context.get("user") and group in context["user"].group_ids)
        if "task_node_id" in condition:
            return condition.get("task_node_id") == context.get("task_node_id")
        if "action_key" in condition:
            return condition.get("action_key") == context.get("action_key")
        return False

    def _collect_rule_bindings(self, request_record, task_node_id=False, action_key=False):
        domain = [("active", "=", True), ("category_id", "=", request_record.category_id.id)]
        bindings = self.env["workflow.field.rule.binding"].sudo().search(domain, order="sequence, id")
        scoped = self.env["workflow.field.rule.binding"]
        for binding in bindings:
            if binding.scope == "category":
                scoped |= binding
            elif binding.scope == "task" and task_node_id and binding.task_node_id == task_node_id:
                scoped |= binding
            elif binding.scope == "action" and action_key and binding.action_key == action_key:
                scoped |= binding
        return scoped.sorted(key=lambda b: (b.sequence, b.id))

    @api.model
    def evaluate_field_states(self, request_record, task_node_id=False, action_key=False, user=False):
        user = user or self.env.user
        bindings = self._collect_rule_bindings(request_record, task_node_id=task_node_id, action_key=action_key)
        rule_sets = bindings.mapped("rule_set_id").filtered(lambda r: r.active)

        controlled_fields = set()
        states = {}
        matched_rules = []
        context = {
            "user_id": user.id,
            "user": user,
            "task_node_id": task_node_id,
            "action_key": action_key,
            "now": datetime.utcnow().isoformat(),
        }

        for rule_set in rule_sets.sorted(key=lambda r: (r.sequence, r.id)):
            for rule in rule_set.rule_ids.filtered(lambda r: r.active).sorted(key=lambda r: (r.sequence, r.id)):
                effects = rule.effect_json or {}
                for field_name in (effects.get("fields") or {}).keys():
                    controlled_fields.add(field_name)
                    states.setdefault(field_name, {"visible": False, "required": False, "readonly": True})

                if rule.task_node_id and task_node_id and rule.task_node_id != task_node_id:
                    continue
                if rule.action_key and action_key and rule.action_key != action_key:
                    continue

                condition = rule.condition_json or {}
                if condition and not self._evaluate_simple_condition(request_record, condition, context):
                    continue

                matched_rules.append(rule.id)
                field_effects = (effects.get("fields") or {})
                for field_name, effect in field_effects.items():
                    if field_name not in states:
                        states[field_name] = {"visible": False, "required": False, "readonly": True}
                    if "visible" in effect:
                        states[field_name]["visible"] = bool(effect.get("visible"))
                    if "readonly" in effect:
                        states[field_name]["readonly"] = bool(effect.get("readonly"))
                    if "required" in effect:
                        states[field_name]["required"] = bool(effect.get("required"))

                if rule.stop_on_match:
                    break

        # Merge policy: invisible wins, readonly wins, required only if visible.
        required_fields = []
        readonly_fields = []
        invisible_fields = []
        for field_name, state in states.items():
            if not state.get("visible", False):
                invisible_fields.append(field_name)
                state["required"] = False
                state["readonly"] = True
            if state.get("readonly"):
                readonly_fields.append(field_name)
            if state.get("required") and state.get("visible"):
                required_fields.append(field_name)

        return {
            "controlled_fields": sorted(controlled_fields),
            "states": states,
            "required_fields": sorted(set(required_fields)),
            "readonly_fields": sorted(set(readonly_fields)),
            "invisible_fields": sorted(set(invisible_fields)),
            "matched_rule_ids": matched_rules,
        }

    def _normalize_action_key(self, action_key=False):
        return (action_key or "").strip()

    def _workflow_node_policy_parts(self, policy_field_name):
        value = (policy_field_name or "").strip()
        if not value.startswith(self._WORKFLOW_NODE_POLICY_PREFIX):
            return False, False
        tail = value[len(self._WORKFLOW_NODE_POLICY_PREFIX):]
        if ":" not in tail:
            return False, False
        node_tag, node_name = tail.split(":", 1)
        node_tag = (node_tag or "").strip().lower()
        node_name = (node_name or "").strip()
        if not node_tag or not node_name:
            return False, False
        return node_tag, node_name

    def _workflow_node_state_key(self, node_tag, node_name):
        node_tag = (node_tag or "").strip().lower()
        node_name = (node_name or "").strip()
        if not node_tag or not node_name:
            return ""
        return f"{node_tag}:{node_name}"

    def _normalize_domain_text(self, value):
        if not value:
            return ""
        if isinstance(value, (list, tuple)):
            try:
                return json.dumps(value)
            except Exception:
                return ""
        if not isinstance(value, str):
            return ""
        return re.sub(r"[\u200B-\u200D\uFEFF]", "", value).strip()

    def _normalize_modifier_domain_text(self, value, keep_false_literal=True):
        normalized = self._normalize_domain_text(value)
        if not normalized:
            return ""
        if not keep_false_literal and normalized.lower() in {"false", "0", "none", "null"}:
            return ""
        return normalized

    def _normalize_runtime_value(self, value):
        if hasattr(value, "ids"):
            ids = [rid for rid in value.ids if isinstance(rid, int) and rid > 0]
            if len(ids) == 1:
                return ids[0]
            return ids
        if value is not None and value.__class__.__name__ == "NewId":
            origin = getattr(value, "origin", False)
            return origin if isinstance(origin, int) and origin > 0 else False
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, list):
            return [self._normalize_runtime_value(item) for item in value]
        if isinstance(value, dict):
            if "id" in value:
                return value.get("id")
            if "resId" in value:
                return value.get("resId")
            return value
        if isinstance(value, str):
            return value.strip()
        return value

    def _to_namespace(self, **kwargs):
        return SimpleNamespace(**kwargs)

    def _safe_int(self, value):
        try:
            return int(value)
        except Exception:
            return False

    def _runtime_eval_context(
        self,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        user=False,
        simulated_history=False,
        snapshot_values=None,
    ):
        user = (user or self.env.user).sudo()
        actual_user_id = int(self.env.context.get("workflow_actual_actor_user_id") or 0)
        actual_user = self.env["res.users"].sudo().browse(actual_user_id).exists() if actual_user_id else user
        delegated_from_user = user if actual_user and user.id != actual_user.id else self.env["res.users"]
        target_record = target_record.sudo()
        request_record = request_record.sudo()
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}

        employee = user.employee_id.sudo() if user.employee_id else self.env["hr.employee"]
        department = user.department_id or (employee.department_id if employee else self.env["hr.department"])
        company = request_record.company_id or user.company_id
        manager_user = request_record.manager_user_id
        request_owner = request_record.request_owner_id
        requester_employee = request_owner.employee_id.sudo() if request_owner and request_owner.employee_id else self.env["hr.employee"]

        # ── Extended request-owner context ────────────────────────────────────
        # Computed here so safe_symbols matches the runtime reference panel
        # symbols exposed in the studio domain dialog builder.
        request_creator = (
            request_record.create_uid
            if "create_uid" in request_record._fields
            else self.env["res.users"]
        )
        req_owner_dept = (
            requester_employee.department_id
            if requester_employee and requester_employee.department_id
            else self.env["hr.department"]
        )
        req_owner_mgr_user = (
            requester_employee.parent_id.user_id
            if requester_employee
            and requester_employee.parent_id
            and requester_employee.parent_id.user_id
            else self.env["res.users"]
        )
        req_owner_dept_mgr_user = (
            req_owner_dept.manager_id.user_id
            if req_owner_dept
            and req_owner_dept.manager_id
            and req_owner_dept.manager_id.user_id
            else self.env["res.users"]
        )
        req_owner_mgr_chain_ids = self.env["workflow.engine.assignment.domain.service"]._collect_manager_chain_user_ids(requester_employee)
        req_owner_team_code = getattr(requester_employee, "x_team_code", False) if requester_employee else False
        req_owner_line_code = getattr(requester_employee, "x_line_code", False) if requester_employee else False

        user_group_ids = self._user_effective_group_ids(user)
        actual_user_group_ids = self._user_effective_group_ids(actual_user) if actual_user else []
        delegated_from_user_group_ids = (
            self._user_effective_group_ids(delegated_from_user)
            if delegated_from_user
            else []
        )
        group_xmlids = self.env["ir.model.data"].sudo().search(
            [("model", "=", "res.groups"), ("res_id", "in", user_group_ids)]
        ).mapped("complete_name")
        actual_group_xmlids = self.env["ir.model.data"].sudo().search(
            [("model", "=", "res.groups"), ("res_id", "in", actual_user_group_ids)]
        ).mapped("complete_name") if actual_user else []
        actor_group_csv = f",{','.join(group_xmlids)}," if group_xmlids else ","
        actor_approval_groups = self.env["workflow.approval.group"].sudo().search(
            [("user_ids", "in", user.id)]
        )
        actor_approval_group_ids = actor_approval_groups.ids
        actor_approval_group_names = [
            (group.name or "").strip().lower()
            for group in actor_approval_groups
            if (group.name or "").strip()
        ]
        actor_approval_group_csv = (
            f",{','.join(str(group_id) for group_id in actor_approval_group_ids)},"
            if actor_approval_group_ids
            else ","
        )
        delegated_group_xmlids = self.env["ir.model.data"].sudo().search(
            [("model", "=", "res.groups"), ("res_id", "in", delegated_from_user_group_ids)]
        ).mapped("complete_name") if delegated_from_user else []
        delegated_approval_group_ids = self.env["workflow.approval.group"].sudo().search(
            [("user_ids", "in", delegated_from_user.id)]
        ).ids if delegated_from_user else []
        normalized_action_key = self._normalize_action_key(action_key).lower()
        normalized_task_node_id = (
            task_node_id
            or getattr(request_record, "current_node_id", False)
            or ""
        ).strip()

        current_meta_task = self.env["workflow.category.version.meta.task"]
        if request_record.version_id and normalized_task_node_id:
            current_meta_task = request_record.version_id.meta_task_ids.filtered(
                lambda t: t.node_id == normalized_task_node_id
            )[:1]
        elif request_record.version_id and request_record.current_node_id:
            current_meta_task = request_record.version_id.meta_task_ids.filtered(
                lambda t: t.node_id == request_record.current_node_id
            )[:1]

        if hasattr(request_record, "_workflow_active_node_ids_for_domains"):
            active_node_ids = request_record._workflow_active_node_ids_for_domains()
        else:
            active_node_ids = []
            current_node_id = getattr(request_record, "current_node_id", False)
            if current_node_id:
                active_node_ids.append(current_node_id)
            for node_id in (getattr(request_record, "active_branch_node_ids", None) or []):
                if node_id and node_id not in active_node_ids:
                    active_node_ids.append(node_id)

        now_dt = fields.Datetime.now()
        today_date = fields.Date.context_today(request_record)
        current_date = fields.Date.to_string(today_date)
        node_age_cache = {}

        def _wf_node_age_minutes(node_id):
            node_id = (node_id or "").strip()
            if not node_id:
                return 0
            if node_id not in node_age_cache:
                if hasattr(request_record, "_workflow_node_age_minutes"):
                    node_age_cache[node_id] = request_record._workflow_node_age_minutes(
                        node_id,
                        now=now_dt,
                    )
                else:
                    node_age_cache[node_id] = 0
            return node_age_cache[node_id]

        current_stage_age_minutes = _wf_node_age_minutes(normalized_task_node_id)
        if hasattr(request_record, "_workflow_format_duration_compact"):
            current_stage_age_display = request_record._workflow_format_duration_compact(
                current_stage_age_minutes
            )
        else:
            current_stage_age_display = str(current_stage_age_minutes)

        is_it_department = bool(department and "it" in (department.name or "").strip().lower())
        is_manager_of_requester = bool(
            manager_user
            and manager_user.id == user.id
            or (
                requester_employee
                and requester_employee.parent_id
                and requester_employee.parent_id.user_id.id == user.id
            )
        )
        actor_position_name = (
            employee.job_id.name.strip().lower()
            if employee and employee.job_id and employee.job_id.name
            else ""
        )
        actor_department_name = (
            department.name.strip().lower()
            if department and department.name
            else ""
        )
        actor_login = (user.login or "").strip().lower()
        actor_name = (user.name or "").strip().lower()

        approver_rows = getattr(request_record.sudo(), "approver_ids", self.env["workflow.approval.approver"])
        domain_service = self.env["workflow.engine.assignment.domain.service"]
        history = domain_service._normalize_simulated_history(simulated_history)
        all_approver_user_ids = list(
            dict.fromkeys(
                approver_rows.mapped("user_id").ids
                + (history.get("all_assigned_user_ids") or [])
                + (history.get("all_decided_user_ids") or [])
            )
        )
        decided_approver_user_ids = list(
            dict.fromkeys(
                approver_rows.filtered("counts_as_decided_user").mapped("user_id").ids
                + (history.get("all_decided_user_ids") or [])
            )
        )
        pending_approver_user_ids = approver_rows.filtered(
            lambda row: row.status in ("new", "pending", "waiting")
        ).mapped("user_id").ids
        pending_approver_user_ids = list(
            dict.fromkeys(pending_approver_user_ids + (history.get("all_pending_user_ids") or []))
        )
        def node_assigned_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="assigned",
                simulated_history=simulated_history,
            )

        def node_pending_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="pending",
                simulated_history=simulated_history,
            )

        def node_decided_approver_user_ids(node_id):
            return domain_service.node_approver_user_ids(
                request_record,
                node_id,
                user_type="decided",
                simulated_history=simulated_history,
            )

        runtime_values = {
            "uid": user.id,
            "user_id": user.id,
            "current_date": current_date,
            "today": current_date,
            "now": fields.Datetime.to_string(now_dt),
            "request_id": request_record.id,
            "request_owner_id": request_owner.id if request_owner else False,
            "request_owner_user_id": request_owner.id if request_owner else False,
            "manager_user_id": manager_user.id if manager_user else False,
            "request_creator_id": request_creator.id if request_creator else False,
            "request_creator_manager_user_id": manager_user.id if manager_user else False,
            "request_owner_manager_user_id": req_owner_mgr_user.id if req_owner_mgr_user else False,
            "request_owner_line_manager_user_id": req_owner_mgr_user.id if req_owner_mgr_user else False,
            "request_owner_department_manager_user_id": req_owner_dept_mgr_user.id if req_owner_dept_mgr_user else False,
            "request_owner_manager_chain_user_ids": req_owner_mgr_chain_ids,
            "all_approver_user_ids": all_approver_user_ids,
            "decided_approver_user_ids": decided_approver_user_ids,
            "has_decision_user_ids": decided_approver_user_ids,
            "pending_approver_user_ids": pending_approver_user_ids,
            "node_assigned_approver_user_ids": node_assigned_approver_user_ids,
            "node_pending_approver_user_ids": node_pending_approver_user_ids,
            "node_decided_approver_user_ids": node_decided_approver_user_ids,
            "request_owner_team_code": req_owner_team_code or False,
            "request_owner_line_code": req_owner_line_code or False,
            "wf_actor_uid": user.id,
            "wf_actor_name": actor_name,
            "wf_actor_login": actor_login,
            "wf_actor_department_name": actor_department_name,
            "wf_actor_position_name": actor_position_name,
            "wf_actor_group_ids": user_group_ids,
            "wf_actor_group_xmlids": actor_group_csv,
            "wf_actor_approval_group_ids": actor_approval_group_ids,
            "wf_actor_approval_group_names": actor_approval_group_names,
            "wf_actor_approval_group_csv": actor_approval_group_csv,
            "wf_actor_is_manager": is_manager_of_requester,
            "wf_actor_is_hod": bool(
                "hod" in actor_position_name
                or "head of department" in actor_position_name
            ),
            "wf_action_key": normalized_action_key,
            "action_key": normalized_action_key,
            "current_action_key": normalized_action_key,
            "wf_current_node_id": normalized_task_node_id,
            "current_node_id": normalized_task_node_id,
            "wf_active_node_ids": active_node_ids,
            "active_node_ids": active_node_ids,
            "wf_current_stage_age_minutes": current_stage_age_minutes,
            "current_stage_age_minutes": current_stage_age_minutes,
            "wf_current_stage_age_display": current_stage_age_display,
            "current_stage_age_display": current_stage_age_display,
            "wf_oldest_active_stage_age_minutes": max(
                [_wf_node_age_minutes(node_id) for node_id in active_node_ids] or [0]
            ),
            "wf_youngest_active_stage_age_minutes": min(
                [_wf_node_age_minutes(node_id) for node_id in active_node_ids] or [0]
            ),
            "current_meta_task_id": current_meta_task.id if current_meta_task else False,
            "current_meta_task": current_meta_task.id if current_meta_task else False,
            "is_it_department": is_it_department,
            "is_manager_of_requester": is_manager_of_requester,
            "__action_key__": normalized_action_key,
            "__current_node_id__": normalized_task_node_id,
            "__actor_uid__": user.id,
            "__actor_name__": actor_name,
            "__actor_login__": actor_login,
            "__actor_department__": actor_department_name,
            "__actor_position__": actor_position_name,
            "__actor_group_ids__": user_group_ids,
            "__actor_group_xmlids__": actor_group_csv,
            "__actor_approval_group_ids__": actor_approval_group_ids,
            "__actor_approval_group_names__": actor_approval_group_names,
            "__actor_is_manager__": is_manager_of_requester,
            "__actor_is_hod__": bool(
                "hod" in actor_position_name
                or "head of department" in actor_position_name
            ),
            "actual_user_id": actual_user.id if actual_user else False,
            "actual_user_login": actual_user.login if actual_user else False,
            "actual_user_name": actual_user.name if actual_user else False,
            "delegated_from_user_id": delegated_from_user.id if delegated_from_user else False,
            "request": request_record,
            "object": target_record,
        }
        if "x_approval_base_id" in getattr(target_record, "_fields", {}):
            runtime_values["x_approval_base_id"] = request_record

        def wf_domain_and(left, right):
            if left in (None, "", "False", "false"):
                left = False
            if right in (None, "", "False", "false"):
                right = False
            if isinstance(left, tuple):
                left = list(left)
            if isinstance(right, tuple):
                right = list(right)
            if left is False or right is False:
                return False
            if left is True:
                return right
            if right is True:
                return left
            if isinstance(left, list) and isinstance(right, list):
                return ["&", left, right]
            return False

        def wf_domain_or(left, right):
            if left in (None, "", "False", "false"):
                left = False
            if right in (None, "", "False", "false"):
                right = False
            if isinstance(left, tuple):
                left = list(left)
            if isinstance(right, tuple):
                right = list(right)
            if left is True or right is True:
                return True
            if left is False:
                return right
            if right is False:
                return left
            if isinstance(left, list) and isinstance(right, list):
                return ["|", left, right]
            return False

        # ── Actor helper functions ─────────────────────────────────────────────
        # Exposed in safe_symbols so Actor Condition Builder expressions work:
        #   [('id','!=',0)] if actor_is_hod() else [('id','=',0)]
        def _wf_norm(s):
            return (s or "").strip().lower()

        def actor_has_group(xmlid):
            if not xmlid:
                return False
            return bool(f",{xmlid}," in actor_group_csv)

        def actor_has_approval_group(group_ref):
            if group_ref in (None, False, ""):
                return False
            try:
                return int(group_ref) in actor_approval_group_ids
            except Exception:
                normalized = _wf_norm(group_ref)
                return normalized in actor_approval_group_names

        def actor_name_is(name):
            return _wf_norm(actor_name) == _wf_norm(name)

        def actor_in_department(name):
            return _wf_norm(actor_department_name) == _wf_norm(name)

        def actor_in_position(name):
            return _wf_norm(actor_position_name) == _wf_norm(name)

        def actor_is_request_manager():
            return bool(manager_user and manager_user.id == user.id)

        def actor_is_hod():
            pos = _wf_norm(actor_position_name)
            return "hod" in pos or "head of department" in pos

        def wf_has_active_node(node_id):
            node_id = (node_id or "").strip()
            return bool(node_id and node_id in active_node_ids)

        def wf_node_age_minutes(node_id):
            return _wf_node_age_minutes(node_id)

        def wf_oldest_active_node_age_minutes():
            return max([_wf_node_age_minutes(node_id) for node_id in active_node_ids] or [0])

        def wf_youngest_active_node_age_minutes():
            return min([_wf_node_age_minutes(node_id) for node_id in active_node_ids] or [0])

        safe_symbols = {}

        def wf_any(relation_path, line_domain):
            return self._match_related_domain_quantifier(
                target_record=target_record,
                request_record=request_record,
                relation_path=relation_path,
                line_domain=line_domain,
                eval_ctx={
                    "runtime_values": runtime_values,
                    "safe_symbols": safe_symbols,
                },
                quantifier="any",
                snapshot_values=snapshot_values,
            )

        def wf_all(relation_path, line_domain):
            return self._match_related_domain_quantifier(
                target_record=target_record,
                request_record=request_record,
                relation_path=relation_path,
                line_domain=line_domain,
                eval_ctx={
                    "runtime_values": runtime_values,
                    "safe_symbols": safe_symbols,
                },
                quantifier="all",
                snapshot_values=snapshot_values,
            )

        safe_symbols = {
            "uid": user.id,
            "current_date": current_date,
            "today": current_date,
            "now": fields.Datetime.to_string(now_dt),
            "context_today": lambda *args, **kwargs: today_date,
            "datetime": safe_eval_datetime,
            "time": py_datetime.time,
            "relativedelta": relativedelta,
            "user": self._to_namespace(
                id=user.id,
                login=user.login or "",
                name=user.name or "",
                company_id=company.id if company else False,
                department_id=department.id if department else False,
                position_name=employee.job_id.name if employee and employee.job_id else "",
                manager_id=manager_user.id if manager_user else False,
                group_ids=tuple(user_group_ids),
                group_xmlids=tuple(group_xmlids),
                approval_group_ids=tuple(actor_approval_group_ids),
            ),
            "current_user": self._to_namespace(
                id=user.id,
                login=user.login or "",
                name=user.name or "",
                company_id=company.id if company else False,
                department_id=department.id if department else False,
                manager_id=manager_user.id if manager_user else False,
                group_ids=tuple(user_group_ids),
                group_xmlids=tuple(group_xmlids),
                approval_group_ids=tuple(actor_approval_group_ids),
            ),
            "actual_user": self._to_namespace(
                id=actual_user.id if actual_user else False,
                login=actual_user.login if actual_user else "",
                name=actual_user.name if actual_user else "",
                company_id=actual_user.company_id.id if actual_user and actual_user.company_id else False,
                department_id=actual_user.department_id.id if actual_user and actual_user.department_id else False,
                manager_id=actual_user.employee_id.parent_id.user_id.id
                if actual_user and actual_user.employee_id and actual_user.employee_id.parent_id and actual_user.employee_id.parent_id.user_id
                else False,
                group_ids=tuple(actual_user_group_ids) if actual_user else tuple(),
                group_xmlids=tuple(actual_group_xmlids),
            ),
            "delegated_from_user": self._to_namespace(
                id=delegated_from_user.id if delegated_from_user else False,
                login=delegated_from_user.login if delegated_from_user else "",
                name=delegated_from_user.name if delegated_from_user else "",
                company_id=delegated_from_user.company_id.id if delegated_from_user and delegated_from_user.company_id else False,
                department_id=delegated_from_user.department_id.id if delegated_from_user and delegated_from_user.department_id else False,
                group_ids=tuple(delegated_from_user_group_ids) if delegated_from_user else tuple(),
                group_xmlids=tuple(delegated_group_xmlids),
                approval_group_ids=tuple(delegated_approval_group_ids),
            ),
            "employee": self._to_namespace(
                id=employee.id if employee else False,
                department_id=department.id if department else False,
                job_id=employee.job_id.id if employee and employee.job_id else False,
                manager_id=employee.parent_id.id if employee and employee.parent_id else False,
            ),
            "department": self._to_namespace(
                id=department.id if department else False,
                name=department.name if department else "",
            ),
            "company": self._to_namespace(
                id=company.id if company else False,
                name=company.name if company else "",
            ),
            "groups": tuple(group_xmlids),
            "group_xmlids": tuple(group_xmlids),
            "approval_groups": tuple(actor_approval_group_ids),
            "approval_group_ids": tuple(actor_approval_group_ids),
            "current_node_id": normalized_task_node_id,
            "current_action_key": normalized_action_key,
            "active_node_ids": tuple(active_node_ids),
            "current_meta_task_id": current_meta_task.id if current_meta_task else False,
            "is_it_department": is_it_department,
            "is_manager_of_requester": is_manager_of_requester,
            "request": request_record,
            "object": target_record,
            "wf_domain_and": wf_domain_and,
            "wf_domain_or": wf_domain_or,
            "actor_name_is": actor_name_is,
            "actor_in_department": actor_in_department,
            "actor_in_position": actor_in_position,
            "actor_has_group": actor_has_group,
            "actor_has_approval_group": actor_has_approval_group,
            "actor_is_request_manager": actor_is_request_manager,
            "actor_is_hod": actor_is_hod,
            "wf_has_active_node": wf_has_active_node,
            "wf_node_age_minutes": wf_node_age_minutes,
            "wf_oldest_active_node_age_minutes": wf_oldest_active_node_age_minutes,
            "wf_youngest_active_node_age_minutes": wf_youngest_active_node_age_minutes,
            "wf_any": wf_any,
            "wf_all": wf_all,
        }
        safe_symbols.update(runtime_values)
        return {
            "runtime_values": runtime_values,
            "safe_symbols": safe_symbols,
            "current_meta_task_id": current_meta_task.id if current_meta_task else False,
            "task_node_id": normalized_task_node_id,
            "action_key": normalized_action_key,
        }

    def _validate_domain_literal(self, value, depth=1):
        if depth > self._WF_MAX_DOMAIN_DEPTH:
            raise ValidationError(_("Workflow domain value nesting is too deep."))
        if isinstance(value, str):
            if len(value) > self._WF_MAX_DOMAIN_STRING_LENGTH:
                raise ValidationError(_("Workflow domain literal value is too long."))
            return
        if isinstance(value, (int, float, bool, py_datetime.date, py_datetime.datetime)) or value is None:
            return
        if isinstance(value, (list, tuple, set)):
            if len(value) > self._WF_MAX_DOMAIN_ITEMS:
                raise ValidationError(_("Workflow domain list literal has too many items."))
            for item in value:
                self._validate_domain_literal(item, depth=depth + 1)
            return
        if isinstance(value, dict):
            if len(value) > self._WF_MAX_DOMAIN_ITEMS:
                raise ValidationError(_("Workflow domain dictionary literal has too many keys."))
            for key, item in value.items():
                self._validate_domain_literal(key, depth=depth + 1)
                self._validate_domain_literal(item, depth=depth + 1)
            return
        raise ValidationError(_("Unsupported workflow domain literal type: %s", type(value).__name__))

    def _normalize_constant_workflow_domain(self, domain):
        """Support legacy constant domains used as config sentinels.

        Keep these exact one-leaf forms consistent across the engine:
        - ``[(0, '=', 1)]`` => always False
        - ``[(1, '=', 1)]`` => always True
        """
        if not isinstance(domain, (list, tuple)):
            return domain
        tokens = list(domain)
        if len(tokens) != 1:
            return domain
        leaf = tokens[0]
        if isinstance(leaf, tuple):
            leaf = list(leaf)
        if not isinstance(leaf, list) or len(leaf) < 3:
            return domain
        field_expr = leaf[0]
        operator = str(leaf[1] or "").strip().lower()
        expected = leaf[2]
        if operator != "=" or expected != 1:
            return domain
        if field_expr == 0:
            return False
        if field_expr == 1:
            return True
        return domain

    def _validate_evaluated_domain_structure(self, domain):
        domain = self._normalize_constant_workflow_domain(domain)
        if isinstance(domain, bool):
            return
        leaf_count = 0

        def _validate_leaf(leaf):
            nonlocal leaf_count
            if len(leaf) < 3:
                raise ValidationError(_("Workflow domain condition is incomplete: %s", leaf))
            field_expr = leaf[0]
            operator = str(leaf[1] or "").strip().lower()
            expected = leaf[2]
            if not isinstance(field_expr, str) or not field_expr.strip():
                raise ValidationError(_("Workflow domain field must be a non-empty string."))
            if operator not in self._WF_DOMAIN_OPERATORS:
                raise ValidationError(_("Unsupported workflow domain operator: %s", operator))
            self._validate_domain_literal(expected, depth=1)
            leaf_count += 1
            if leaf_count > self._WF_MAX_DOMAIN_LEAFS:
                raise ValidationError(_("Workflow domain has too many conditions."))

        def _walk(node, depth=1):
            if depth > self._WF_MAX_DOMAIN_DEPTH:
                raise ValidationError(_("Workflow domain nesting is too deep."))
            if isinstance(node, bool):
                return
            if not isinstance(node, (list, tuple)):
                raise ValidationError(_("Invalid workflow domain token type: %s", type(node).__name__))
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
                        raise ValidationError(_("Workflow domain logical operator is missing an operand."))
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
                        raise ValidationError(_("Workflow domain logical operator is missing an operand."))
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

    def _safe_eval_domain_expression(self, domain_expression, safe_symbols):
        if domain_expression in (None, False, "", "False", "false"):
            return False
        if domain_expression in (True, "True", "true"):
            return True
        if isinstance(domain_expression, (list, tuple)):
            domain_list = self._normalize_constant_workflow_domain(list(domain_expression))
            if isinstance(domain_list, bool):
                return domain_list
            self._validate_evaluated_domain_structure(domain_list)
            return domain_list
        if not isinstance(domain_expression, str):
            return False
        expression = self._normalize_domain_text(domain_expression)
        if not expression:
            return False
        if len(expression) > self._WF_MAX_DOMAIN_EXPR_LENGTH:
            raise ValidationError(_("Workflow domain expression is too large."))
        evaluated = safe_eval(expression, safe_symbols, mode="eval")
        if isinstance(evaluated, tuple):
            evaluated = list(evaluated)
        if isinstance(evaluated, bool):
            return evaluated
        if isinstance(evaluated, list):
            evaluated = self._normalize_constant_workflow_domain(evaluated)
            if isinstance(evaluated, bool):
                return evaluated
            self._validate_evaluated_domain_structure(evaluated)
            return evaluated
        raise ValidationError(_("Workflow domain expression must evaluate to a domain list or boolean."))

    def _parse_options_literal(self, options_literal):
        if not options_literal or not isinstance(options_literal, str):
            return {}
        options_literal = re.sub(r"[\u200B-\u200D\uFEFF]", "", options_literal).strip()
        if not options_literal:
            return {}

        def _literal_eval(expr):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                warnings.simplefilter("ignore", SyntaxWarning)
                return ast.literal_eval(expr)

        try:
            if options_literal.startswith("{"):
                try:
                    parsed = json.loads(options_literal)
                except Exception:
                    parsed = _literal_eval(options_literal)
            else:
                parsed = _literal_eval(options_literal)
        except Exception:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    warnings.simplefilter("ignore", SyntaxWarning)
                    parsed = safe_eval(options_literal, {}, mode="eval")
            except Exception:
                return {}
        return parsed if isinstance(parsed, dict) else {}

    def _extract_field_names_from_arch(self, arch):
        field_names = set()
        if not arch:
            return []
        try:
            if hasattr(arch, "xpath"):
                xml_root = arch
            elif isinstance(arch, bytes):
                xml_root = etree.fromstring(arch)
            elif isinstance(arch, str):
                xml_root = etree.fromstring(arch.encode("utf-8"))
            else:
                return []
        except Exception:
            return []

        try:
            field_nodes = xml_root.xpath("//*[local-name()='field'][@name]")
        except Exception:
            field_nodes = []
        if not field_nodes and hasattr(xml_root, "iter"):
            for node in xml_root.iter():
                try:
                    if etree.QName(node.tag).localname == "field" and node.get("name"):
                        field_nodes.append(node)
                except Exception:
                    continue

        for node in field_nodes:
            field_name = (node.get("name") or "").strip()
            if field_name:
                field_names.add(field_name)
        return sorted(field_names)

    @ormcache(
        "self.env.cr.dbname",
        "model_name",
        "view_id",
        "self.env.uid",
        "self.env.lang",
        "self.env.company.id",
    )
    def _cached_form_field_names(self, model_name, view_id):
        Model = self.env[model_name].sudo()
        view_id = self._safe_int(view_id) or False
        arch = False
        if view_id:
            view = self.env["ir.ui.view"].sudo().browse(view_id)
            if view.exists() and view.model == model_name:
                try:
                    arch = view.get_combined_arch()
                except Exception:
                    arch = view.arch_db
        if not arch:
            try:
                view_data = Model.get_view(view_id=view_id, view_type="form")
                arch = view_data.get("arch")
            except Exception:
                _logger.warning(
                    "_cached_form_field_names: get_view failed for model %s "
                    "view_id %s - skipping visible allowlist candidates",
                    model_name,
                    view_id,
                    exc_info=True,
                )
        return json.dumps(self._extract_field_names_from_arch(arch), sort_keys=True)

    def _get_visible_allowlist_candidate_fields(self, target_record, view_id=False):
        if not target_record:
            return set()
        try:
            view_field_names = set(
                json.loads(self._cached_form_field_names(target_record._name, view_id) or "[]")
            )
        except Exception:
            view_field_names = set()
        default_visible_field_names = self._get_default_visible_field_names(target_record)
        return {
            field_name
            for field_name in view_field_names
            if field_name in target_record._fields
            and field_name not in default_visible_field_names
        }

    @ormcache("self.env.cr.dbname", "model_name")
    def _configured_default_visible_field_names(self, model_name):
        if not model_name:
            return ()
        records = self.env["workflow.default.visible.field"].sudo().search(
            [
                ("active", "=", True),
                ("model", "=", model_name),
            ]
        )
        return tuple(sorted(set(records.mapped("field_name"))))

    def _get_default_visible_field_names(self, target_record):
        if not target_record:
            return set(self._META_BUILTIN_DEFAULT_VISIBLE_FIELD_NAMES)
        return set(self._META_BUILTIN_DEFAULT_VISIBLE_FIELD_NAMES) | set(
            self._configured_default_visible_field_names(target_record._name)
        )

    def _extract_workflow_domains_from_arch(self, arch):
        return {}

    @ormcache(
        "self.env.cr.dbname",
        "model_name",
        "view_id",
        "self.env.uid",
        "self.env.lang",
        "self.env.company.id",
    )
    def _cached_form_workflow_domains(self, model_name, view_id):
        return "{}"

    def _workflow_domain_policy_write_stamp(self, model_name, view_id=False, version_id=False):
        return ""

    def _workflow_meta_field_write_stamp(self, version_id=False):
        version_id = self._safe_int(version_id) or 0
        if not version_id:
            return ""
        rows = self.env["workflow.category.version.meta.field"].sudo().search(
            [("meta_id.version_id", "=", version_id)]
        )
        if not rows:
            return ""
        signatures = []
        for row in rows.sorted(lambda item: (item.meta_id.node_id or "", item.field_id.name or "", item.id)):
            action_keys = [
                (action.name or action.attr_label or "").strip().lower()
                for action in row.activity_action_ids
            ]
            signatures.append(
                "|".join(
                    [
                        str(row.meta_id.node_id or ""),
                        str(row.field_id.model or ""),
                        str(row.field_id.name or ""),
                        str(row.field_type or ""),
                        str(row.domain or ""),
                        ",".join(sorted(action_keys)),
                    ]
                )
            )
        payload = "||".join(signatures)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @ormcache(
        "self.env.cr.dbname",
        "model_name",
        "view_id",
        "version_id",
        "policy_stamp",
    )
    def _cached_workflow_policy_domains(self, model_name, view_id, version_id, policy_stamp):
        return "{}"

    def _workflow_domains_for_model(self, model_name, view_id=False, version_id=False):
        return {}

    def _empty_recordset_for_workflow_domain(self):
        return self.env["ir.model"].browse()

    def _resolve_workflow_record_path(self, record, path):
        path_parts = [part.strip() for part in (path or "").split(".") if part.strip()]
        current = record.sudo() if hasattr(record, "sudo") else record
        for part in path_parts:
            if not current or not hasattr(current, "_fields") or part not in current._fields:
                raise ValidationError(_("Unknown workflow relation path: %s") % (path or ""))
            current = current[part]
        return current.sudo() if hasattr(current, "sudo") else current

    def _workflow_relation_records_from_snapshot(self, base_record, relation_field, raw_value):
        related_model = self.env[relation_field.comodel_name].sudo()
        if not isinstance(raw_value, list):
            return related_model.browse()

        item_ids = []
        for item in raw_value:
            if isinstance(item, int):
                item_id = item
            elif isinstance(item, dict):
                item_id = item.get("id")
            else:
                item_id = False
            if isinstance(item_id, int) and not isinstance(item_id, bool):
                item_ids.append(item_id)
        item_ids = list(dict.fromkeys(item_ids))
        persisted_records = related_model.browse(item_ids).exists()
        if relation_field.type == "many2many":
            return persisted_records

        origins_by_id = {record.id: record for record in persisted_records}
        resolved_records = []

        converter = getattr(base_record, "_workflow_virtual_vals_from_snapshot_for_model", None)
        for item in raw_value:
            if isinstance(item, int) and not isinstance(item, bool):
                if origin := origins_by_id.get(item):
                    resolved_records.append(origin)
                continue
            if not isinstance(item, dict):
                continue

            item_id = item.get("id")
            origin = origins_by_id.get(item_id, related_model.browse())

            child_vals = (
                converter(related_model, item, depth=1)
                if callable(converter)
                else {}
            )
            if child_vals:
                resolved_records.append(related_model.new(child_vals, origin=origin or None))
            elif origin:
                resolved_records.append(origin)
        return related_model.union(*resolved_records)

    def _resolve_workflow_relation_path(
        self,
        target_record,
        request_record,
        relation_path,
        snapshot_values=None,
    ):
        path = (relation_path or "").strip()
        if not path:
            raise ValidationError(_("Missing workflow relation path."))

        base_record = target_record
        if path.startswith("request."):
            base_record = request_record
            path = path[len("request."):]
        elif path.startswith(("object.", "record.")):
            base_record = target_record
            path = path.split(".", 1)[1]
        else:
            root = path.split(".", 1)[0]
            if root not in getattr(target_record, "_fields", {}) and root in getattr(request_record, "_fields", {}):
                base_record = request_record

        root = path.split(".", 1)[0]
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        relation_field = getattr(base_record, "_fields", {}).get(root)
        if (
            root in snapshot_values
            and relation_field
            and relation_field.type in ("one2many", "many2many")
            and base_record._name == target_record._name
        ):
            value = self._workflow_relation_records_from_snapshot(
                base_record,
                relation_field,
                snapshot_values[root],
            )
            remainder = path.split(".", 1)[1] if "." in path else ""
            if remainder:
                value = self._resolve_workflow_record_path(value, remainder)
        else:
            value = self._resolve_workflow_record_path(base_record, path)
        if not hasattr(value, "filtered_domain"):
            raise ValidationError(_("Workflow relation path is not a record relation: %s") % relation_path)
        return value

    def _match_related_domain_quantifier(
        self,
        target_record,
        request_record,
        relation_path,
        line_domain,
        eval_ctx,
        quantifier="any",
        snapshot_values=None,
    ):
        related_records = self._resolve_workflow_relation_path(
            target_record,
            request_record,
            relation_path,
            snapshot_values=snapshot_values,
        ).exists()
        if not related_records:
            return False

        if line_domain in (True, "True", "true"):
            return True
        if line_domain in (None, False, "False", "false", ""):
            return False

        try:
            if isinstance(line_domain, str):
                line_domain = self._safe_eval_domain_expression(
                    line_domain,
                    (eval_ctx or {}).get("safe_symbols") or {},
                )
            elif isinstance(line_domain, tuple):
                line_domain = list(line_domain)
            elif isinstance(line_domain, list):
                self._validate_evaluated_domain_structure(line_domain)
            else:
                return False

            if isinstance(line_domain, bool):
                return bool(line_domain)

            matched = related_records.sudo().filtered_domain(line_domain or [])
        except Exception as error:
            _logger.warning(
                "Invalid workflow %s relation domain for %s on %s(%s): %s",
                quantifier,
                relation_path,
                target_record._name,
                target_record.id,
                error,
            )
            return False

        if quantifier == "all":
            return bool(matched) and len(matched) == len(related_records)
        return bool(matched)

    def _traverse_runtime_value(self, value, path_parts):
        current = value
        for part in path_parts:
            if current is None or current is False:
                return False
            if hasattr(current, "_fields"):
                if part == "id":
                    ids = current.ids
                    current = ids[0] if len(ids) == 1 else ids
                    continue
                if part == "ids":
                    current = current.ids
                    continue
                if part not in current._fields:
                    return False
                current = current[part]
                continue
            if isinstance(current, dict):
                current = current.get(part)
                continue
            if isinstance(current, (list, tuple)):
                if part in ("id", "ids"):
                    if len(current) == 2 and isinstance(current[0], int):
                        current = current[0]
                    else:
                        current = list(current)
                    continue
                return False
            if isinstance(current, int) and part == "id":
                continue
            if isinstance(current, int) and part == "ids":
                current = [current]
                continue
            if hasattr(current, part):
                current = getattr(current, part)
                continue
            return False
        return self._normalize_runtime_value(current)

    def _resolve_domain_operand(self, target_record, field_expr, runtime_values, snapshot_values=None):
        snapshot_values = snapshot_values or {}
        root, *rest = (field_expr or "").split(".")
        if not root:
            return False

        # Live form values must win over persisted/runtime aliases for the same
        # field so Studio button domains react correctly before the record is saved.
        if root in snapshot_values:
            return self._traverse_runtime_value(snapshot_values.get(root), rest)
        if field_expr in runtime_values:
            return runtime_values[field_expr]
        if rest and root in target_record._fields:
            return self._traverse_runtime_value(target_record[root], rest)
        if root in runtime_values:
            return self._traverse_runtime_value(runtime_values[root], rest)
        if root == "id":
            value = target_record.id
        elif root in target_record._fields:
            value = target_record[root]
        else:
            alias_map = {
                # Backward-compatible studio alias in existing customer data.
                "owner_user_id": "request_owner_id",
            }
            alias_field = alias_map.get(root)
            if alias_field and alias_field in target_record._fields:
                value = target_record[alias_field]
            elif alias_field and alias_field in snapshot_values:
                value = snapshot_values.get(alias_field)
            else:
                raise KeyError(field_expr)
        return self._traverse_runtime_value(value, rest)

    def _like_match(self, text_value, pattern, case_sensitive=True):
        text_value = "" if text_value in (None, False) else str(text_value)
        pattern = "" if pattern in (None, False) else str(pattern)
        escaped = re.escape(pattern)
        regex = (
            "^"
            + escaped
            .replace(r"\%", ".*")
            .replace("%", ".*")
            .replace(r"\_", ".")
            .replace("_", ".")
            + "$"
        )
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.match(regex, text_value, flags=flags))

    def _is_collection(self, value):
        return isinstance(value, (list, tuple, set))

    def _coerce_temporal_domain_value(self, value, field_type):
        if field_type not in ("date", "datetime") or value is None or value is False:
            return value
        if isinstance(value, (list, tuple, set)):
            return [self._coerce_temporal_domain_value(item, field_type) for item in value]
        if isinstance(value, str) and value == "":
            return value
        parsed = value
        if isinstance(value, str):
            try:
                parsed = date_utils.parse_date(value.strip(), self.env)
            except Exception:
                return value
        if field_type == "date":
            if isinstance(parsed, py_datetime.datetime):
                return parsed.date()
            if isinstance(parsed, py_datetime.date):
                return parsed
            return value
        if isinstance(parsed, py_datetime.datetime):
            return parsed.replace(tzinfo=None)
        if isinstance(parsed, py_datetime.date):
            return py_datetime.datetime.combine(parsed, py_datetime.time.min)
        return value

    def _evaluate_leaf_condition(self, target_record, leaf, runtime_values, snapshot_values=None):
        if not isinstance(leaf, (list, tuple)) or len(leaf) < 3:
            return False
        field_expr, operator, expected = leaf[0], str(leaf[1] or "").strip().lower(), leaf[2]
        if not isinstance(field_expr, str):
            return False
        root_field = field_expr.split(".", 1)[0]
        field_path_exists = self._domain_field_path_exists(target_record._name, field_expr)
        field_type = target_record._fields[root_field].type if root_field in target_record._fields else False
        runtime_override = field_expr in runtime_values or root_field in runtime_values
        if field_path_exists and not snapshot_values and not runtime_override:
            try:
                return bool(target_record.sudo().filtered_domain([tuple(leaf)]))
            except Exception:
                # Workflow runtime symbols and unsaved form snapshots are handled
                # by the custom evaluator below.
                pass
        actual = self._resolve_domain_operand(
            target_record,
            field_expr,
            runtime_values,
            snapshot_values=snapshot_values,
        )
        actual = self._normalize_runtime_value(actual)
        expected = self._normalize_runtime_value(expected)
        if field_type in ("date", "datetime"):
            actual = self._coerce_temporal_domain_value(actual, field_type)
            expected = self._coerce_temporal_domain_value(expected, field_type)

        if operator not in self._WF_DOMAIN_OPERATORS:
            if field_expr in target_record._fields and not snapshot_values:
                try:
                    return bool(target_record.sudo().filtered_domain([tuple(leaf)]))
                except Exception:
                    _logger.debug("Unsupported domain leaf operator %s on %s", operator, leaf)
            return False

        if operator in ("=", "=="):
            return actual == expected
        if operator in ("!=", "<>"):
            return actual != expected
        if operator == ">":
            return actual not in (None, False) and expected not in (None, False) and actual > expected
        if operator == ">=":
            return actual not in (None, False) and expected not in (None, False) and actual >= expected
        if operator == "<":
            return actual not in (None, False) and expected not in (None, False) and actual < expected
        if operator == "<=":
            return actual not in (None, False) and expected not in (None, False) and actual <= expected
        if operator in ("in", "not in"):
            candidates = expected if self._is_collection(expected) else [expected]
            if self._is_collection(actual):
                matched = any(item in candidates for item in actual)
            else:
                matched = actual in candidates
            return matched if operator == "in" else not matched
        if operator in ("contains", "not contains", "like", "not like", "=like", "not =like"):
            if operator in ("contains", "not contains", "like", "not like"):
                pattern = f"%{expected}%"
            else:
                pattern = expected
            matched = self._like_match(actual, pattern, case_sensitive=True)
            return matched if "not" not in operator else not matched
        if operator in ("icontains", "not icontains", "ilike", "not ilike", "=ilike", "not =ilike"):
            if operator in ("icontains", "not icontains", "ilike", "not ilike"):
                pattern = f"%{expected}%"
            else:
                pattern = expected
            matched = self._like_match(actual, pattern, case_sensitive=False)
            return matched if "not" not in operator else not matched
        return False

    def _evaluate_domain_node(self, target_record, node, runtime_values, snapshot_values=None):
        if isinstance(node, bool):
            return node
        if isinstance(node, (list, tuple)):
            if (
                len(node) >= 3
                and isinstance(node[0], str)
                and node[0] not in ("&", "|", "!")
            ):
                return self._evaluate_leaf_condition(
                    target_record,
                    node[:3],
                    runtime_values,
                    snapshot_values=snapshot_values,
                )
            if not node:
                return True
            return self._evaluate_domain_tokens(
                target_record,
                list(node),
                runtime_values,
                snapshot_values=snapshot_values,
            )
        return bool(node)

    def _evaluate_domain_next(self, target_record, tokens, runtime_values, snapshot_values=None):
        if not tokens:
            return True
        token = tokens.pop(0)
        if token == "&":
            left = self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
            right = self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
            return left and right
        if token == "|":
            left = self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
            right = self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
            return left or right
        if token == "!":
            return not self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
        return self._evaluate_domain_node(
            target_record,
            token,
            runtime_values,
            snapshot_values=snapshot_values,
        )

    def _evaluate_domain_tokens(self, target_record, tokens, runtime_values, snapshot_values=None):
        if not tokens:
            return True
        result = self._evaluate_domain_next(
            target_record,
            tokens,
            runtime_values,
            snapshot_values=snapshot_values,
        )
        while tokens:
            next_result = self._evaluate_domain_next(
                target_record,
                tokens,
                runtime_values,
                snapshot_values=snapshot_values,
            )
            result = result and next_result
        return bool(result)

    def _domain_match(self, target_record, domain, eval_ctx, snapshot_values=None):
        if domain in (True, "True", "true"):
            return True
        if domain in (False, "False", "false"):
            return False
        if domain in (None, [], ()):
            return True
        if isinstance(domain, tuple):
            domain = list(domain)
        domain = self._normalize_constant_workflow_domain(domain)
        if isinstance(domain, bool):
            return domain
        if not isinstance(domain, list):
            return bool(domain)
        return self._evaluate_domain_tokens(
            target_record,
            list(domain),
            eval_ctx["runtime_values"],
            snapshot_values=snapshot_values,
        )

    def match_domain_expression(
        self,
        request_record,
        domain_expression,
        target_record=False,
        task_node_id=False,
        action_key=False,
        user=False,
        snapshot_values=None,
        simulated_history=False,
        raise_on_error=False,
        default=True,
    ):
        """Evaluate workflow domain expression with runtime context.

        This is the shared evaluator for action visibility and server-side
        guard checks so both UI rendering and action execution use identical
        semantics (current actor + request data).
        """
        if domain_expression in (None, False, "", "[]"):
            return bool(default)
        if not request_record:
            return bool(default)

        request_record = request_record.sudo().exists()
        if not request_record:
            return bool(default)

        target_record = (target_record or request_record).sudo().exists()
        if not target_record:
            target_record = request_record

        task_node_id = self._resolve_runtime_field_task_node_id(
            request_record,
            task_node_id=task_node_id,
            user=user,
        )

        try:
            eval_ctx = self._runtime_eval_context(
                target_record=target_record,
                request_record=request_record,
                task_node_id=task_node_id,
                action_key=action_key,
                user=user,
                simulated_history=simulated_history,
                snapshot_values=snapshot_values,
            )
            evaluated_domain = self._safe_eval_domain_expression(
                domain_expression,
                eval_ctx["safe_symbols"],
            )
            return self._domain_match(
                target_record,
                evaluated_domain,
                eval_ctx,
                snapshot_values=snapshot_values or {},
            )
        except Exception as error:
            if raise_on_error:
                raise
            _logger.warning(
                "Invalid workflow domain expression '%s' for %s(%s): %s",
                domain_expression,
                target_record._name,
                target_record.id,
                error,
            )
            return False

    def _meta_field_rule_domain_matches(
        self,
        field_rule,
        target_record,
        eval_ctx,
        snapshot_values=None,
    ):
        domain_expression = self._normalize_modifier_domain_text(
            getattr(field_rule, "domain", False),
            keep_false_literal=True,
        )
        if not domain_expression or domain_expression == "[]":
            return True
        try:
            evaluated_domain = self._safe_eval_domain_expression(
                domain_expression,
                eval_ctx["safe_symbols"],
            )
            return self._domain_match(
                target_record,
                evaluated_domain,
                eval_ctx,
                snapshot_values=snapshot_values or {},
            )
        except Exception as error:
            field_name = field_rule.field_id.name if field_rule.field_id else ""
            _logger.debug(
                "Workflow meta field domain evaluation failed for %s.%s (%s): %s",
                target_record._name,
                field_name,
                domain_expression,
                error,
            )
            return False

    def _evaluate_meta_field_states(
        self,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        result = {}
        if not request_record.version_id:
            return result
        task_node_id = self._resolve_runtime_field_task_node_id(
            request_record,
            task_node_id=task_node_id,
            user=user,
        )
        if not task_node_id:
            return result
        meta_task = request_record.version_id.meta_task_ids.filtered(lambda t: t.node_id == task_node_id)[:1]
        if not meta_task:
            return result

        normalized_action_key = self._normalize_action_key(action_key).lower()
        field_rules = meta_task.field_ids
        eval_ctx = self._runtime_eval_context(
            target_record,
            request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            user=user,
        )
        static_eval_ctx = (
            self._runtime_eval_context(
                target_record,
                request_record,
                task_node_id=task_node_id,
                action_key=False,
                user=user,
            )
            if action_key
            else eval_ctx
        )
        visible_field_names = {
            field_rule.field_id.name
            for field_rule in field_rules
            if field_rule.field_type == "visible"
            and field_rule.field_id.name
            and field_rule.field_id.name in target_record._fields
            and self._meta_field_rule_domain_matches(
                field_rule,
                target_record,
                static_eval_ctx,
                snapshot_values=snapshot_values,
            )
        }
        candidate_names = self._get_visible_allowlist_candidate_fields(target_record, view_id=view_id)
        for field_name in candidate_names:
            result[field_name] = {
                "invisible": field_name not in visible_field_names,
                "readonly": False,
                "required": False,
            }

        for field_rule in field_rules:
            field_name = field_rule.field_id.name
            if not field_name or field_name not in target_record._fields:
                continue
            state = result.setdefault(
                field_name,
                {"invisible": False, "readonly": False, "required": False},
            )
            if field_rule.field_type == "visible":
                if not self._meta_field_rule_domain_matches(
                    field_rule,
                    target_record,
                    static_eval_ctx,
                    snapshot_values=snapshot_values,
                ):
                    continue
                state["invisible"] = False
            elif field_rule.field_type == "invisible":
                if not self._meta_field_rule_domain_matches(
                    field_rule,
                    target_record,
                    static_eval_ctx,
                    snapshot_values=snapshot_values,
                ):
                    continue
                state["invisible"] = True
            elif field_rule.field_type == "readonly":
                if not self._meta_field_rule_domain_matches(
                    field_rule,
                    target_record,
                    static_eval_ctx,
                    snapshot_values=snapshot_values,
                ):
                    continue
                state["readonly"] = True
            elif field_rule.field_type == "required":
                if field_rule.activity_action_ids:
                    action_keys = {
                        (a.name or a.attr_label or "").strip().lower()
                        for a in field_rule.activity_action_ids
                    }
                    if normalized_action_key not in action_keys:
                        continue
                if not self._meta_field_rule_domain_matches(
                    field_rule,
                    target_record,
                    eval_ctx,
                    snapshot_values=snapshot_values,
                ):
                    continue
                state["required"] = True
        return result

    def _evaluate_view_domain_states(
        self,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        return {
            "field_states": {},
            "node_states": {},
        }

    def _merge_state_maps(self, *maps):
        merged = {}
        for map_item in maps:
            for field_name, state in (map_item or {}).items():
                final_state = merged.setdefault(
                    field_name,
                    {"invisible": False, "readonly": False, "required": False},
                )
                final_state["invisible"] = final_state["invisible"] or bool(state.get("invisible"))
                final_state["readonly"] = final_state["readonly"] or bool(state.get("readonly"))
                final_state["required"] = final_state["required"] or bool(state.get("required"))

        for field_name, state in merged.items():
            if state["invisible"]:
                state["readonly"] = True
                state["required"] = False
            elif state["readonly"]:
                state["required"] = False
        return merged

    def _rule_states_to_map(self, rule_payload):
        map_payload = {}
        for field_name in rule_payload.get("required_fields") or []:
            map_payload.setdefault(
                field_name,
                {"invisible": False, "readonly": False, "required": False},
            )["required"] = True
        for field_name in rule_payload.get("readonly_fields") or []:
            map_payload.setdefault(
                field_name,
                {"invisible": False, "readonly": False, "required": False},
            )["readonly"] = True
        for field_name in rule_payload.get("invisible_fields") or []:
            map_payload.setdefault(
                field_name,
                {"invisible": False, "readonly": False, "required": False},
            )["invisible"] = True
        return map_payload

    def _resolve_runtime_field_task_node_id(self, request_record, task_node_id=False, user=False):
        normalized_node_id = (task_node_id or "").strip()
        if normalized_node_id:
            return normalized_node_id
        if not request_record:
            return ""

        resolver = getattr(request_record, "_workflow_get_actor_primary_node_id", None)
        if resolver:
            try:
                actor_node_id = (resolver(user=user) or "").strip()
                if actor_node_id:
                    return actor_node_id
            except Exception:
                _logger.debug(
                    "Could not resolve actor workflow node for %s(%s)",
                    getattr(request_record, "_name", ""),
                    getattr(request_record, "id", False),
                    exc_info=True,
                )

        return (getattr(request_record, "current_node_id", False) or "").strip()

    def _build_runtime_state_payload(
        self,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        user = user or self.env.user
        task_node_id = self._resolve_runtime_field_task_node_id(
            request_record,
            task_node_id=task_node_id,
            user=user,
        )
        action_key = self._normalize_action_key(action_key)

        # Runtime field render architecture:
        # Meta Field rows tied to the current workflow node are the single
        # source of truth for form field visibility/readonly/required state.
        #
        # Keep button/action/automation domain evaluation separate. View-level
        # wf_policy/wf_* domains and legacy rule bindings are intentionally not
        # merged here, so a field rule only affects the node where admins
        # configure it in Studio Meta Fields.
        meta_map = self._evaluate_meta_field_states(
            target_record,
            request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            view_id=view_id,
            user=user,
            snapshot_values=snapshot_values,
        )
        node_state_map = {}
        merged_map = self._merge_state_maps(meta_map)

        required_fields = sorted([name for name, state in merged_map.items() if state.get("required")])
        readonly_fields = sorted([name for name, state in merged_map.items() if state.get("readonly")])
        invisible_fields = sorted([name for name, state in merged_map.items() if state.get("invisible")])

        payload = {
            "field_state_map": merged_map,
            "node_state_map": node_state_map,
            "required_fields": required_fields,
            "readonly_fields": readonly_fields,
            "invisible_fields": invisible_fields,
            "meta": {
                "task_node_id": task_node_id,
                "action_key": action_key,
                "view_id": self._safe_int(view_id) or False,
                "request_id": request_record.id,
                "target_model": target_record._name,
                "target_id": target_record.id,
                "user_id": user.id,
            },
        }
        _logger.debug(
            "Workflow field states computed model=%s id=%s request=%s node=%s action=%s controlled=%s",
            target_record._name,
            target_record.id,
            request_record.id,
            task_node_id,
            action_key,
            sorted(merged_map.keys()),
        )
        return payload

    @ormcache(
        "self.env.cr.dbname",
        "target_model",
        "target_id",
        "request_id",
        "uid",
        "task_node_id",
        "action_key",
        "view_id",
        "write_stamp",
    )
    def _cached_runtime_state_payload_json(
        self,
        target_model,
        target_id,
        request_id,
        uid,
        task_node_id,
        action_key,
        view_id,
        write_stamp,
    ):
        user = self.env["res.users"].sudo().browse(uid)
        target_record = self.env[target_model].sudo().browse(target_id)
        request_record = self.env["workflow.base.approval.request"].sudo().browse(request_id)
        payload = self._build_runtime_state_payload(
            target_record=target_record,
            request_record=request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            view_id=view_id,
            user=user,
            snapshot_values=None,
        )
        return json.dumps(payload, sort_keys=True)

    def evaluate_runtime_field_state_map(
        self,
        target_record,
        request_record=False,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        target_record.ensure_one()
        request_record = request_record or (
            target_record.x_approval_base_id
            if "x_approval_base_id" in target_record._fields and target_record.x_approval_base_id
            else target_record
        )
        if not request_record:
            return {
                "field_state_map": {},
                "node_state_map": {},
                "required_fields": [],
                "readonly_fields": [],
                "invisible_fields": [],
            }

        action_key = self._normalize_action_key(action_key)
        view_id = self._safe_int(view_id) or 0
        user = user or self.env.user
        task_node_id = self._resolve_runtime_field_task_node_id(
            request_record,
            task_node_id=task_node_id,
            user=user,
        )

        def _stamp(record):
            if not record or "write_date" not in record._fields:
                return ""
            write_date = record.write_date
            if not write_date:
                return ""
            if isinstance(write_date, str):
                try:
                    write_date = fields.Datetime.from_string(write_date)
                except Exception:
                    return write_date
            try:
                return write_date.strftime("%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                return str(write_date)

        write_stamp = f"{_stamp(request_record)}|{_stamp(target_record)}"
        request_version_id = (
            request_record.version_id.id
            if hasattr(request_record, "_fields")
            and "version_id" in request_record._fields
            and request_record.version_id
            else False
        )
        meta_stamp = self._workflow_meta_field_write_stamp(request_version_id)
        write_stamp = f"{write_stamp}|meta:{meta_stamp}"

        if snapshot_values:
            payload = self._build_runtime_state_payload(
                target_record=target_record.sudo(),
                request_record=request_record.sudo(),
                task_node_id=task_node_id,
                action_key=action_key,
                view_id=view_id,
                user=user,
                snapshot_values=snapshot_values,
            )
        else:
            payload_json = self._cached_runtime_state_payload_json(
                target_record._name,
                target_record.id,
                request_record.id,
                user.id,
                task_node_id or "",
                action_key or "",
                view_id,
                write_stamp or "",
            )
            payload = json.loads(payload_json or "{}")
        return copy.deepcopy(payload)

    def _is_empty_value(self, record, field_name):
        if field_name not in record._fields:
            return True
        field = record._fields[field_name]
        value = record[field_name]
        if field.type in ("one2many", "many2many"):
            return not bool(value)
        if field.type == "many2one":
            return not bool(value.id if value else False)
        if field.type == "html":
            return not bool((value or "").strip())
        return value in (False, None, "", [])

    def _form_arch_root_for_visibility(self, model_name, view_id=False):
        model_name = (model_name or "").strip()
        if not model_name:
            return False

        Model = self.env[model_name].sudo()
        resolved_view_id = self._safe_int(view_id) or False
        arch = False
        if resolved_view_id:
            view = self.env["ir.ui.view"].sudo().browse(resolved_view_id)
            if view.exists() and view.model == model_name:
                try:
                    arch = view.get_combined_arch()
                except Exception:
                    arch = view.arch_db
            else:
                resolved_view_id = False
        if not arch:
            view_data = Model.get_view(view_id=resolved_view_id, view_type="form")
            arch = view_data.get("arch")

        try:
            if hasattr(arch, "xpath"):
                return arch
            if isinstance(arch, bytes):
                return etree.fromstring(arch)
            if isinstance(arch, str):
                return etree.fromstring(arch.encode("utf-8"))
        except Exception:
            _logger.debug(
                "Failed to parse form arch for visibility model=%s view_id=%s",
                model_name,
                resolved_view_id,
            )
        return False

    def _view_groups_match_user(self, groups_expression, user):
        expression = (groups_expression or "").strip()
        if not expression:
            return True
        user = (user or self.env.user).sudo()

        tokens = [token.strip() for token in expression.split(",") if token and token.strip()]
        if not tokens:
            return True
        include_xmlids = [token for token in tokens if not token.startswith("!")]
        exclude_xmlids = [token[1:].strip() for token in tokens if token.startswith("!") and token[1:].strip()]

        try:
            if any(user.has_group(xmlid) for xmlid in exclude_xmlids):
                return False
            if include_xmlids and not any(user.has_group(xmlid) for xmlid in include_xmlids):
                return False
        except Exception:
            return True
        return True

    def _extract_node_invisible_rules(self, node):
        rules = []
        invisible_expr = (node.get("invisible") or "").strip()
        if invisible_expr:
            rules.append(invisible_expr)
        column_invisible_expr = (node.get("column_invisible") or "").strip()
        if column_invisible_expr:
            rules.append(column_invisible_expr)

        attrs_literal = node.get("attrs")
        if attrs_literal:
            attrs = self._parse_options_literal(attrs_literal)
            if isinstance(attrs, dict) and "invisible" in attrs:
                rules.append(attrs.get("invisible"))

        modifiers_literal = node.get("modifiers")
        if modifiers_literal:
            modifiers = {}
            try:
                modifiers = json.loads(modifiers_literal)
            except Exception:
                modifiers = self._parse_options_literal(modifiers_literal)
            if isinstance(modifiers, dict) and "invisible" in modifiers:
                rules.append(modifiers.get("invisible"))
        return rules

    def _extract_node_required_rules(self, node):
        rules = []
        required_expr = (node.get("required") or "").strip()
        if required_expr:
            rules.append(required_expr)

        attrs_literal = node.get("attrs")
        if attrs_literal:
            attrs = self._parse_options_literal(attrs_literal)
            if isinstance(attrs, dict) and "required" in attrs:
                rules.append(attrs.get("required"))

        modifiers_literal = node.get("modifiers")
        if modifiers_literal:
            modifiers = {}
            try:
                modifiers = json.loads(modifiers_literal)
            except Exception:
                modifiers = self._parse_options_literal(modifiers_literal)
            if isinstance(modifiers, dict) and "required" in modifiers:
                rules.append(modifiers.get("required"))
        return rules

    def _build_view_eval_symbols(self, target_record, eval_ctx, snapshot_values=None):
        symbols = dict((eval_ctx or {}).get("safe_symbols") or {})
        symbols.setdefault("env", self.env)
        symbols.setdefault("context", dict(self.env.context))
        symbols.setdefault("active_id", target_record.id)
        symbols.setdefault("id", target_record.id)
        for field_name in target_record._fields:
            if field_name in symbols:
                continue
            try:
                symbols[field_name] = self._normalize_runtime_value(target_record[field_name])
            except Exception:
                symbols[field_name] = False
        if isinstance(snapshot_values, dict):
            for field_name, value in snapshot_values.items():
                if field_name not in target_record._fields:
                    continue
                symbols[field_name] = self._normalize_runtime_value(value)
        return symbols

    def _evaluate_view_rule(
        self,
        rule,
        target_record,
        eval_ctx,
        eval_symbols,
        snapshot_values=None,
    ):
        if rule in (None, False, "", "False", "false", "0", 0):
            return False
        if rule in (True, "True", "true", "1", 1):
            return True

        if isinstance(rule, tuple):
            rule = list(rule)
        if isinstance(rule, list):
            return self._domain_match(
                target_record,
                rule,
                eval_ctx,
                snapshot_values=snapshot_values,
            )
        if isinstance(rule, (int, float, bool)):
            return bool(rule)

        if not isinstance(rule, str):
            return bool(rule)

        expression = rule.strip()
        if not expression:
            return False
        try:
            evaluated = safe_eval(expression, eval_symbols, mode="eval")
            if isinstance(evaluated, tuple):
                evaluated = list(evaluated)
            if isinstance(evaluated, list):
                return self._domain_match(
                    target_record,
                    evaluated,
                    eval_ctx,
                    snapshot_values=snapshot_values,
                )
            return bool(evaluated)
        except Exception:
            try:
                evaluated_domain = self._safe_eval_domain_expression(
                    expression,
                    (eval_ctx or {}).get("safe_symbols") or {},
                )
                return self._domain_match(
                    target_record,
                    evaluated_domain,
                    eval_ctx,
                    snapshot_values=snapshot_values,
                )
            except Exception:
                _logger.debug(
                    "Unable to evaluate view modifier rule '%s' on %s(%s)",
                    expression,
                    target_record._name,
                    target_record.id,
                )
                return False

    def _evaluate_view_invisible_rule(
        self,
        rule,
        target_record,
        eval_ctx,
        eval_symbols,
        snapshot_values=None,
    ):
        return self._evaluate_view_rule(
            rule,
            target_record=target_record,
            eval_ctx=eval_ctx,
            eval_symbols=eval_symbols,
            snapshot_values=snapshot_values,
        )

    def _is_field_node_visible_in_form(
        self,
        node,
        target_record,
        eval_ctx,
        eval_symbols,
        user=False,
        snapshot_values=None,
    ):
        lineage = [node] + list(node.iterancestors())
        for current in lineage:
            if not self._view_groups_match_user(current.get("groups"), user=user):
                return False
            for invisible_rule in self._extract_node_invisible_rules(current):
                if self._evaluate_view_invisible_rule(
                    invisible_rule,
                    target_record=target_record,
                    eval_ctx=eval_ctx,
                    eval_symbols=eval_symbols,
                    snapshot_values=snapshot_values,
                ):
                    return False
        return True

    def _is_field_visible_in_form_arch(
        self,
        arch_root,
        field_name,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        user=False,
        snapshot_values=None,
    ):
        if arch_root is False or arch_root is None or not field_name:
            return True
        try:
            field_nodes = arch_root.xpath("//*[local-name()='field'][@name=$fname]", fname=field_name)
        except Exception:
            field_nodes = []
        if not field_nodes:
            return False

        eval_ctx = self._runtime_eval_context(
            target_record=target_record,
            request_record=request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            user=user,
        )
        eval_symbols = self._build_view_eval_symbols(
            target_record,
            eval_ctx,
            snapshot_values=snapshot_values,
        )
        for node in field_nodes:
            if self._is_field_node_visible_in_form(
                node,
                target_record=target_record,
                eval_ctx=eval_ctx,
                eval_symbols=eval_symbols,
                user=user,
                snapshot_values=snapshot_values,
            ):
                return True
        return False

    def _visible_required_fields_from_form_arch(
        self,
        arch_root,
        target_record,
        request_record,
        task_node_id=False,
        action_key=False,
        user=False,
        snapshot_values=None,
    ):
        if arch_root is False or arch_root is None:
            return []

        try:
            field_nodes = arch_root.xpath("//*[local-name()='field'][@name]")
        except Exception:
            field_nodes = []

        if not field_nodes:
            return []

        eval_ctx = self._runtime_eval_context(
            target_record=target_record,
            request_record=request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            user=user,
        )
        eval_symbols = self._build_view_eval_symbols(
            target_record,
            eval_ctx,
            snapshot_values=snapshot_values,
        )
        required_fields = []
        for node in field_nodes:
            field_name = (node.get("name") or "").strip()
            if (
                not field_name
                or field_name not in target_record._fields
                or field_name in required_fields
            ):
                continue
            if not self._is_field_node_visible_in_form(
                node,
                target_record=target_record,
                eval_ctx=eval_ctx,
                eval_symbols=eval_symbols,
                user=user,
                snapshot_values=snapshot_values,
            ):
                continue
            required_rules = self._extract_node_required_rules(node)
            if not required_rules:
                continue
            for required_rule in required_rules:
                if self._evaluate_view_rule(
                    required_rule,
                    target_record=target_record,
                    eval_ctx=eval_ctx,
                    eval_symbols=eval_symbols,
                    snapshot_values=snapshot_values,
                ):
                    required_fields.append(field_name)
                    break
        return required_fields

    def filter_required_fields_for_view(
        self,
        target_record,
        required_fields,
        request_record=False,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        target_record.ensure_one()
        request_record = request_record or target_record
        request_record.ensure_one()

        unique_required = []
        for field_name in required_fields or []:
            if (
                field_name
                and field_name in target_record._fields
                and field_name not in unique_required
            ):
                unique_required.append(field_name)
        resolved_view_id = self._safe_int(view_id) or 0
        if not unique_required or not resolved_view_id:
            return unique_required

        arch_root = self._form_arch_root_for_visibility(
            target_record._name,
            view_id=resolved_view_id,
        )
        if arch_root is False or arch_root is None:
            return unique_required

        visible_required = []
        hidden_required = []
        for field_name in unique_required:
            if self._is_field_visible_in_form_arch(
                arch_root=arch_root,
                field_name=field_name,
                target_record=target_record.sudo(),
                request_record=request_record.sudo(),
                task_node_id=task_node_id,
                action_key=action_key,
                user=user or self.env.user,
                snapshot_values=snapshot_values,
            ):
                visible_required.append(field_name)
            else:
                hidden_required.append(field_name)
        if hidden_required:
            _logger.debug(
                "Skip required validation for hidden/non-rendered fields model=%s id=%s view=%s fields=%s",
                target_record._name,
                target_record.id,
                resolved_view_id,
                ",".join(hidden_required),
            )
        return visible_required

    def resolve_effective_required_fields_for_view(
        self,
        target_record,
        required_fields,
        request_record=False,
        task_node_id=False,
        action_key=False,
        view_id=False,
        user=False,
        snapshot_values=None,
    ):
        target_record.ensure_one()
        request_record = request_record or target_record
        request_record.ensure_one()

        filtered_required = self.filter_required_fields_for_view(
            target_record=target_record,
            required_fields=required_fields,
            request_record=request_record,
            task_node_id=task_node_id,
            action_key=action_key,
            view_id=view_id,
            user=user,
            snapshot_values=snapshot_values,
        )

        resolved_view_id = self._safe_int(view_id) or 0
        if not resolved_view_id:
            return filtered_required

        arch_root = self._form_arch_root_for_visibility(
            target_record._name,
            view_id=resolved_view_id,
        )
        if arch_root is False or arch_root is None:
            return filtered_required

        effective_required = list(filtered_required)
        for field_name in self._visible_required_fields_from_form_arch(
            arch_root=arch_root,
            target_record=target_record.sudo(),
            request_record=request_record.sudo(),
            task_node_id=task_node_id,
            action_key=action_key,
            user=user or self.env.user,
            snapshot_values=snapshot_values,
        ):
            if field_name not in effective_required:
                effective_required.append(field_name)
        return effective_required

    def validate_action_required_fields(
        self,
        request_record,
        action_key=False,
        task_node_id=False,
        view_id=False,
    ):
        request_record.ensure_one()
        target_record = request_record
        base_request = (
            target_record.x_approval_base_id
            if "x_approval_base_id" in target_record._fields and target_record.x_approval_base_id
            else target_record
        )
        effective_view_id = self._safe_int(view_id or self.env.context.get("view_id")) or 0
        payload = self.evaluate_runtime_field_state_map(
            target_record=target_record,
            request_record=base_request,
            task_node_id=task_node_id or target_record.current_node_id,
            action_key=action_key,
            view_id=effective_view_id,
            user=self.env.user,
        )
        required_fields = self.resolve_effective_required_fields_for_view(
            target_record=target_record,
            required_fields=payload.get("required_fields") or [],
            request_record=base_request,
            task_node_id=task_node_id or target_record.current_node_id,
            action_key=action_key,
            view_id=effective_view_id,
            user=self.env.user,
        )
        missing = [
            fname
            for fname in required_fields
            if self._is_empty_value(target_record, fname)
        ]
        if not missing:
            return True
        field_labels = []
        for name in missing:
            field = target_record._fields.get(name)
            field_labels.append(field.string if field else name)
        raise ValidationError(
            _("Missing required fields for this action: %s", ", ".join(field_labels))
        )


class WorkflowEngineTwoFactorService(models.AbstractModel):
    _name = "workflow.engine.twofactor.service"
    _description = "Workflow Engine Two Factor Service"

    def _inject_actor_helpers(self, context, record):
        actor = self.env.user.sudo()
        request_record = record.sudo()

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

        def actor_name_is(name):
            return _norm(actor.name) == _norm(name)

        def actor_in_department(name):
            department = _actor_department()
            return bool(department and _norm(department.name) == _norm(name))

        def actor_in_position(name):
            return _norm(_actor_position_name()) == _norm(name)

        def actor_is_request_manager():
            manager = getattr(request_record, "manager_user_id", False)
            return bool(manager and manager.id == actor.id)

        def actor_is_hod():
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

        context.update(
            {
                "actor": actor,
                "actor_has_group": actor_has_group,
                "actor_name_is": actor_name_is,
                "actor_in_department": actor_in_department,
                "actor_in_position": actor_in_position,
                "actor_is_request_manager": actor_is_request_manager,
                "actor_is_hod": actor_is_hod,
            }
        )
        return context

    def _eval_condition_domain(self, record, domain_str):
        if not record:
            return None
        record.ensure_one()
        context = (
            record.get_safe_eval_context()
            if hasattr(record, "get_safe_eval_context")
            else {
                "object": record.sudo(),
                "request": record.sudo(),
                "env": self.env,
                "user": self.env.user.sudo(),
            }
        )
        context = self._inject_actor_helpers(context, record)
        domain = safe_eval(domain_str, context)
        if not domain:
            return True
        return bool(record.sudo().filtered_domain(domain).exists())

    def action_requires_twofactor(self, request_record, meta_action, target_record=False):
        if not request_record or not meta_action:
            return False
        if not meta_action.require_2fa:
            return False
        condition_domain = meta_action.twofa_condition_domain
        if condition_domain:
            candidates = []
            if target_record:
                candidates.append(target_record)
            if request_record:
                candidates.append(request_record)

            seen = set()
            for rec in candidates:
                if not rec or not rec.exists():
                    continue
                key = (rec._name, rec.id)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    return self._eval_condition_domain(rec, condition_domain)
                except Exception as exc:
                    _logger.debug(
                        "2FA domain eval failed on %s(%s): %s",
                        rec._name,
                        rec.id,
                        exc,
                    )
                    continue
            _logger.warning("Invalid 2FA condition domain on meta action %s", meta_action.id)
            return False
        return True

    def _normalize_twofactor_method(self, method):
        return "qr" if (method or "").strip() == "qr" else "email_otp"

    def _twofactor_challenge_issuers(self, challenge_model):
        """Return challenge issuer callables by method for extension."""
        return {
            "email_otp": challenge_model.issue_email_otp,
            "qr": challenge_model.issue_qr_challenge,
        }

    def _resolve_twofactor_challenge_issuer(self, challenge_model, method):
        normalized = self._normalize_twofactor_method(method)
        issuers = self._twofactor_challenge_issuers(challenge_model)
        return issuers.get(normalized) or issuers.get("email_otp")

    def _twofactor_verifiers(self, challenge):
        """Return verification callables by challenge method for extension."""
        return {
            "email_otp": challenge.verify_email_otp,
            "qr": challenge.verify_qr_token,
        }

    def _resolve_twofactor_verifier(self, challenge):
        verifiers = self._twofactor_verifiers(challenge)
        return verifiers.get(challenge.method)

    @api.model
    def issue_action_challenge(
        self,
        request_record,
        meta_action,
        action_key=False,
        task_instance=False,
        method=False,
        ttl_seconds=90,
        target_record=False,
    ):
        if not self.action_requires_twofactor(request_record, meta_action, target_record=target_record):
            return self.env["workflow.approval.action.challenge"]
        action_key = action_key or meta_action.name or meta_action.attr_label or ""
        method = self._normalize_twofactor_method(method or meta_action.twofa_method or "email_otp")
        challenge_model = self.env["workflow.approval.action.challenge"].sudo()
        params = {
            "request_record": request_record,
            "action_key": action_key,
            "user": self.env.user,
            "ttl_seconds": ttl_seconds,
            "task_instance": task_instance,
        }
        issuer = self._resolve_twofactor_challenge_issuer(challenge_model, method)
        challenge = issuer(**params) if issuer else self.env["workflow.approval.action.challenge"]
        if challenge:
            challenge.sudo().write({"meta_action_id": meta_action.id})
        return challenge

    def verify_action_challenge(self, challenge_id, otp_code):
        if not challenge_id:
            return False
        challenge = self.env["workflow.approval.action.challenge"].sudo().browse(challenge_id)
        if not challenge.exists():
            return False
        if challenge.user_id.id != self.env.user.id:
            return False
        verifier = self._resolve_twofactor_verifier(challenge)
        if verifier:
            return verifier(otp_code)
        return False
