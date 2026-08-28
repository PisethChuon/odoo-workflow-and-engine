# -*- coding: utf-8 -*-
import logging
from urllib.parse import urlencode

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

ACTIONABLE_STATUSES = ("new", "pending")
PUSH_CTX_SKIP = "workflow_skip_push_notify"
WORKFLOW_NOTIFICATION_ACTOR_USER_ID_CTX = "workflow_notification_actor_user_id"
WORKFLOW_NOTIFICATION_TAG_XMLID = "notification_app.notification_post_tag_workflow"
WORKFLOW_APPROVAL_PARAM_MODULE = "workflow_approval"
DEFAULT_WORKFLOW_MINI_APP_CODE = "noc"
WORKFLOW_PUSH_ENABLED_PARAM = "workflow_notification.push_enabled"
NOTIFICATION_SUPPRESS_CONTEXT_KEYS = (
    PUSH_CTX_SKIP,
    "no_notification",
    "workflow_suppress_notifications",
    "workflow_skip_notifications",
    "workflow_silent_migration",
    "workflow_migration_mode",
)


class WorkflowApprovalApprover(models.Model):
    _inherit = "workflow.approval.approver"

    push_notified_at = fields.Datetime(readonly=True, copy=False, index=True)

    # ------------------------------------------------------------
    # ORM hooks
    # ------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if records._workflow_push_notifications_suppressed():
            return records
        # send only for actionable statuses
        try:
            records.filtered(lambda r: r.status in ACTIONABLE_STATUSES)._workflow_push_notify()
        except Exception:
            _logger.exception("Workflow push notify failed on create (non-blocking).")
        return records

    def write(self, vals):
        # Prevent recursion when we mark push_notified_at
        if self.env.context.get(PUSH_CTX_SKIP):
            return super().write(vals)

        tracked_assignment_fields = {"status", "user_id", "current_meta_id", "request_id"}
        if not (tracked_assignment_fields & set(vals.keys())):
            return super().write(vals)

        old_values_by_id = {
            r.id: {
                "status": r.status,
                "user_id": r.user_id.id,
                "current_meta_id": r.current_meta_id.id,
                "request_id": r.request_id.id,
            }
            for r in self
        }
        res = super().write(vals)

        if self._workflow_push_notifications_suppressed():
            return res

        to_notify = self.env[self._name]
        if "status" in vals and vals.get("status") in ACTIONABLE_STATUSES:
            # Freshly actionable rows must notify even when the engine reuses an
            # older approver row on resubmit / loopback paths.
            to_notify |= self.filtered(
                lambda r: old_values_by_id.get(r.id, {}).get("status") not in ACTIONABLE_STATUSES
                and r.status in ACTIONABLE_STATUSES
            )

        if {"user_id", "current_meta_id", "request_id"} & set(vals.keys()):
            # Admin corrections or engine-side row reuse can reassign an already
            # actionable row without recreating it; treat that as a new assignment.
            to_notify |= self.filtered(
                lambda r: r.status in ACTIONABLE_STATUSES
                and (
                    old_values_by_id.get(r.id, {}).get("user_id") != r.user_id.id
                    or old_values_by_id.get(r.id, {}).get("current_meta_id") != r.current_meta_id.id
                    or old_values_by_id.get(r.id, {}).get("request_id") != r.request_id.id
                )
            )

        if to_notify:
            try:
                reset_rows = to_notify.filtered("push_notified_at")
                if reset_rows:
                    reset_rows.with_context(**{PUSH_CTX_SKIP: True}).sudo().write({
                        "push_notified_at": False,
                    })
                to_notify._workflow_push_notify()
            except Exception:
                _logger.exception("Workflow push notify failed on approver update (non-blocking).")

        return res

    # ------------------------------------------------------------
    # Push notification core
    # ------------------------------------------------------------
    def _workflow_push_notify(self):
        """
        Non-blocking push notify via notification.post -> notification.live.post pipeline.

        The workflow operation only queues push delivery and creates a best-effort
        local inbox row. Firebase delivery runs later in the notification cron.

        Guards:
        - send only once per approver record (push_notified_at)
        - send only if user is active
        - send only if status actionable
        - never raise to callers
        """
        if self._workflow_push_notifications_suppressed():
            return
        if "notification.account" not in self.env or "notification.post" not in self.env:
            _logger.info(
                "Push notification models not found; skipping workflow push notifications."
            )
            return

        grouped_notifications = {}
        for approver in self.sudo():
            # hard guards
            if approver.push_notified_at:
                continue
            if approver.status not in ACTIONABLE_STATUSES:
                continue
            if not approver.user_id or not approver.user_id.active:
                continue
            if not approver._workflow_actor_push_notification_enabled_for_row():
                continue
            if not approver.user_id.sudo().wf_approval_push_enabled:
                continue

            try:
                account = approver._workflow_get_push_account()
                if not account:
                    continue

                title, body = approver._workflow_build_message()
                group_key = approver._workflow_notification_group_key(
                    account,
                    title,
                    body,
                )
                if group_key in grouped_notifications:
                    grouped_notifications[group_key]["approvers"] |= approver
                else:
                    grouped_notifications[group_key] = {
                        "account": account,
                        "title": title,
                        "body": body,
                        "approvers": approver,
                    }

            except Exception:
                _logger.exception(
                    "Workflow push grouping failed (non-blocking). approver_id=%s user_id=%s",
                    approver.id,
                    approver.user_id.id if approver.user_id else None,
                )

        for notification_data in grouped_notifications.values():
            approvers = notification_data["approvers"]
            eligible_users = approvers.mapped("user_id").sudo().exists().filtered("active")
            if not eligible_users:
                continue

            representative = approvers.sorted("id")[:1]
            target_users = representative._workflow_filter_notification_target_users(
                eligible_users
            )
            if not target_users:
                approvers.with_context(**{PUSH_CTX_SKIP: True}).sudo().write({
                    "push_notified_at": fields.Datetime.now()
                })
                continue

            try:
                if len(approvers) == 1:
                    payload = representative._workflow_build_payload(
                        notification_data["title"],
                        notification_data["body"],
                    )
                else:
                    payload = representative._workflow_build_payload(
                        notification_data["title"],
                        notification_data["body"],
                        approver_id=0,
                    )
                deeplink = payload.get("deeplink") or ""

                representative._workflow_post_via_notification_channel(
                    notification_data["account"],
                    notification_data["title"],
                    notification_data["body"],
                    deeplink,
                    payload,
                    target_users=target_users,
                )

                # Mark as notified without triggering write() hook again
                approvers.with_context(**{PUSH_CTX_SKIP: True}).sudo().write({
                    "push_notified_at": fields.Datetime.now()
                })

            except Exception:
                _logger.exception(
                    "Workflow push failed (non-blocking). approver_ids=%s user_ids=%s",
                    approvers.ids,
                    target_users.ids,
                )

    def _workflow_push_notifications_suppressed(self):
        context = self.env.context or {}
        return any(context.get(key) for key in NOTIFICATION_SUPPRESS_CONTEXT_KEYS) or not self._workflow_push_notifications_enabled()

    def _workflow_push_notifications_enabled(self):
        raw_value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(WORKFLOW_PUSH_ENABLED_PARAM, "0")
        )
        return str(raw_value or "").strip() == "1"

    def _workflow_actor_push_notification_enabled_for_row(self):
        self.ensure_one()
        meta_task = self.current_meta_id.sudo()
        if not meta_task or meta_task.push_notification_to_actor:
            return True
        return bool(self.delegation_mode or self.delegated_from_user_id)

    def _workflow_post_via_notification_channel(
        self, account, title, body, deeplink, payload_data, target_users=None
    ):
        """Queue notification delivery without blocking the workflow transaction."""
        self.ensure_one()
        env = self.sudo().env
        target_users = (target_users or self.user_id).sudo().exists()
        if not target_users:
            return

        request_id = self.request_id.id if self.request_id and hasattr(self.request_id, "id") else 0
        user_domain = self._workflow_build_target_user_domain(target_users)
        workflow_tag = env.ref(WORKFLOW_NOTIFICATION_TAG_XMLID, raise_if_not_found=False)

        post_vals = {
            "message": body,
            # push_notification_message is a stored computed field (readonly=False);
            # setting it explicitly avoids a timing edge where _compute_message_by_channel
            # hasn't run yet when _check_has_push_notification_message constraint fires.
            "push_notification_message": body,
            "push_notification_title": title,
            "push_notification_target_url": deeplink or False,
            "user_domain": user_domain,
            "open_type": "deeplink" if deeplink else "default",
            "param_request_id": str(request_id),
            "param_module": WORKFLOW_APPROVAL_PARAM_MODULE,
            "post_method": "now",
            "state": "posting",
            "published_date": fields.Datetime.now(),
            "account_ids": [(6, 0, [account.id])],
        }
        if workflow_tag:
            post_vals["tag_ids"] = [(6, 0, [workflow_tag.id])]

        post = env["notification.post"].sudo().create(post_vals)

        live_post = env["notification.live.post"].sudo().create({
            "post_id": post.id,
            "account_id": account.id,
            "state": "ready",
        })

        live_post.mapped("message")
        self._workflow_upsert_inline_inbox(live_post, users=target_users)
        self._workflow_trigger_push_cron()

    def _workflow_upsert_inline_inbox(self, live_post, users=None):
        """Best-effort local inbox rows; external push delivery stays async."""
        self.ensure_one()
        users = (users or self.user_id).sudo().exists()
        if not users:
            return
        try:
            post = live_post.post_id
            icon_url = (
                "/notification_push_channel/notification_post/%s/push_notification_image" % post.id
                if post.push_notification_image
                else "/notification_app/static/description/icon.png"
            )
            target_url = live_post._build_target_link(live_post, post)
            data_payload = live_post._build_firebase_payload(post, target_url, icon_url)
            self._workflow_seed_target_audience(live_post, users)
            live_post._safe_upsert_push_inbox_for_users(users, data_payload, target_url)
        except Exception:
            _logger.exception(
                "Failed to create inline workflow notification inbox row; queued push remains ready."
            )

    def _workflow_trigger_push_cron(self):
        cron = self.env.ref("notification_app.ir_cron_post_scheduled", raise_if_not_found=False)
        if not cron:
            return
        try:
            cron.sudo()._trigger(at=fields.Datetime.now())
        except Exception:
            _logger.exception("Failed to trigger workflow push notification cron; queued post remains ready.")

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _workflow_get_push_account(self):
        """
        Picks ONE account to prevent sending to wrong app tokens.

        Robust to different schemas:
        - active or is_active
        - optional company_id
        """
        self.ensure_one()
        notification_account = self.env["notification.account"].sudo()
        notification_push_account_code = self.env['ir.config_parameter'].sudo().get_param(
            "notification.push_account", 'super_app'
        )

        domain = [
            ("code", "=", notification_push_account_code),
            ("firebase_enable_push_notifications", "=", True),
            ("active", "=", True),
        ]

        if "company_id" in notification_account._fields:
            if self.company_id:
                domain = ["&"] + domain + [("company_id", "in", [self.company_id.id, False])]
            else:
                # allow global only
                domain = ["&"] + domain + [("company_id", "=", False)]

        return notification_account.search(domain, limit=1)

    def _workflow_notification_group_key(self, account, title, body):
        self.ensure_one()
        shared_payload = self._workflow_build_payload(title, body, approver_id=0)
        return (
            account.id,
            self.request_id.id if self.request_id else 0,
            self.current_meta_id.id if self.current_meta_id else 0,
            self.status or "",
            tuple(sorted(shared_payload.items())),
        )

    def _workflow_filter_notification_target_users(self, users):
        self.ensure_one()
        users = users.sudo().exists()
        actor_user_id = self._workflow_notification_actor_user_id()
        if not actor_user_id:
            return users
        return users.filtered(lambda user: user.id != actor_user_id)

    def _workflow_notification_actor_user_id(self):
        self.ensure_one()
        actor_user_id = self.env.context.get(WORKFLOW_NOTIFICATION_ACTOR_USER_ID_CTX)
        try:
            return int(actor_user_id or 0)
        except Exception:
            return 0

    def _workflow_build_target_user_domain(self, users):
        self.ensure_one()
        users = users.sudo().exists().sorted("id")
        if not users:
            return repr([("id", "=", 0)])

        if "emp_code" in users._fields:
            emp_codes = []
            for user in users:
                emp_code = str(user.emp_code or "").strip()
                if not emp_code:
                    emp_codes = []
                    break
                emp_codes.append(emp_code)
            if emp_codes and len(set(emp_codes)) == len(users):
                return repr([("emp_code", "in", emp_codes)])

        return repr([("id", "in", users.ids)])

    def _workflow_seed_target_audience(self, live_post, users):
        """Make the post audience visible before cron delivery starts."""
        self.ensure_one()
        users = users.sudo().exists()
        if not users:
            return

        push_capable_user_ids = live_post._get_push_capable_user_ids(
            live_post.account_id,
            users,
        )
        push_users = users.filtered(lambda user: user.id in push_capable_user_ids)
        inbox_only_users = users - push_users

        if push_users:
            live_post._log_recipients_for_users(push_users, state="queued")
        if inbox_only_users:
            live_post._log_recipients_for_users(
                inbox_only_users,
                state="skipped",
                extra_vals={
                    "error": _(
                        "No active push device was found when the workflow notification was queued."
                    ),
                },
            )

    def _workflow_build_message(self):
        self.ensure_one()
        task_name = self.current_meta_id.name if self.current_meta_id else _("Approval")
        req_name = self._workflow_request_display_name()
        creator, owner = self._workflow_request_identity_users()
        creator_name = self._workflow_identity_display_name(creator)
        owner_name = self._workflow_identity_display_name(owner)

        title = _("Workflow action required")
        if creator_name and owner_name and creator.id != owner.id:
            body = _(
                "%(request)s needs your action at %(step)s. Requested by %(creator)s for %(owner)s.",
                request=req_name,
                step=task_name,
                creator=creator_name,
                owner=owner_name,
            )
        elif creator_name or owner_name:
            body = _(
                "%(request)s needs your action at %(step)s. Requested by %(requester)s.",
                request=req_name,
                step=task_name,
                requester=creator_name or owner_name,
            )
        else:
            body = _(
                "%(request)s needs your action at %(step)s. Tap to review.",
                request=req_name,
                step=task_name,
            )
        return title, body

    def _workflow_get_target_record(self):
        """Resolve the concrete document record for a workflow approver row."""
        self.ensure_one()

        # Backward compatibility for old engine schema (model + Many2oneReference id).
        legacy_model = self.model if "model" in self._fields else False
        if legacy_model and legacy_model in self.env:
            legacy_res_id = self.request_id
            if hasattr(legacy_res_id, "id"):
                legacy_res_id = legacy_res_id.id
            try:
                legacy_res_id = int(legacy_res_id or 0)
            except Exception:
                legacy_res_id = 0
            if legacy_res_id:
                legacy_rec = self.env[legacy_model].browse(legacy_res_id)
                if legacy_rec.exists():
                    return legacy_rec

        request = self.request_id if "request_id" in self._fields else False
        if not request or not hasattr(request, "_name"):
            return self.env["workflow.base.approval.request"]

        delegate_getter = getattr(request, "_get_transition_delegate_record", None)
        if delegate_getter:
            try:
                target = delegate_getter()
                if target and target.exists():
                    return target
            except Exception:
                _logger.debug(
                    "Failed to resolve delegate record for workflow request %s",
                    request.id,
                    exc_info=True,
                )

        model_name = getattr(request, "res_model_name", False)
        if model_name and model_name in self.env:
            model = self.env[model_name]
            if "x_approval_base_id" in model._fields:
                child = model.search([("x_approval_base_id", "=", request.id)], limit=1)
                if child:
                    return child

        return request

    def _workflow_request_display_name(self):
        self.ensure_one()
        target = self._workflow_get_target_record()
        if target and target.exists():
            return target.display_name or _("Request")
        request = self.request_id
        if request and hasattr(request, "display_name"):
            return request.display_name
        return _("Request")

    def _workflow_requester_display_name(self):
        self.ensure_one()
        creator, owner = self._workflow_request_identity_users()
        return self._workflow_identity_display_name(creator or owner)

    def _workflow_request_identity_users(self):
        self.ensure_one()
        request = self.request_id if "request_id" in self._fields else False
        target = self._workflow_get_target_record()
        creator = self.env["res.users"]
        owner = self.env["res.users"]
        for record in (target, request):
            if not record or not hasattr(record, "_fields"):
                continue
            if not creator and "create_uid" in record._fields and record.create_uid:
                creator = record.create_uid
            if not owner:
                for field_name in ("request_owner_id", "owner_user_id"):
                    candidate = record[field_name] if field_name in record._fields else False
                    if candidate:
                        owner = candidate
                        break
        return creator, owner

    @api.model
    def _workflow_identity_display_name(self, user):
        if not user:
            return ""
        return user.display_name or user.name or ""

    def _workflow_build_payload(self, title, body, approver_id=None):
        self.ensure_one()
        target = self._workflow_get_target_record()

        model = ""
        res_id = 0
        if target and target.exists():
            model = target._name
            res_id = target.id

        request_id = self.request_id.id if self.request_id and hasattr(self.request_id, "id") else 0
        action_url = self._workflow_build_odoo_action_path(
            request_id, model=model, res_id=res_id
        )
        approver_id = self.id if approver_id is None else approver_id
        deeplink = self._workflow_build_myportal_deeplink(
            action_url,
            request_id=request_id,
            approver_id=approver_id,
            model=model,
            res_id=res_id,
        )

        # Keep payload values as strings to avoid FCM data issues
        return {
            "title": str(title or ""),
            "body": str(body or ""),
            "type": WORKFLOW_APPROVAL_PARAM_MODULE,

            "approver_id": str(approver_id or 0),
            "status": str(self.status or ""),
            "current_node_id": str(self.current_meta_node_id or ""),
            "task_name": str((self.current_meta_id.name or "") if self.current_meta_id else ""),

            "param_request_id": str(request_id),
            "param_model": str(model),
            "param_res_id": str(res_id),
            "deeplink": str(deeplink),
            "action_url": str(action_url),
        }

    def _workflow_build_odoo_action_path(self, request_id, model="", res_id=0):
        self.ensure_one()
        if model and res_id:
            return "/odoo/approval-request-report/m-%s/%s" % (model, res_id)

        action = self.env.ref(
            "workflow_engine.my_approval_requests_to_review_action_window",
            raise_if_not_found=False,
        )
        if action and request_id:
            return "/odoo/action-%s/%s" % (action.id, request_id)
        if action:
            return "/odoo/action-%s" % action.id
        return "/odoo/my-approvals-to-review"

    def _workflow_build_myportal_deeplink(
        self, action_path, request_id=0, approver_id=0, model="", res_id=0
    ):
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        template = (params.get_param("workflow_notification.myportal_deeplink_template") or "").strip()
        values = {
            "action_path": action_path or "",
            "request_id": request_id or 0,
            "approver_id": approver_id or 0,
            "model": model or "",
            "res_id": res_id or 0,
            "param_module": WORKFLOW_APPROVAL_PARAM_MODULE,
        }
        if template:
            try:
                return template.format(**values)
            except Exception:
                _logger.exception(
                    "Invalid workflow_notification.myportal_deeplink_template; using default."
                )

        app_code = (
            params.get_param(
                "workflow_notification.myportal_app_code",
                DEFAULT_WORKFLOW_MINI_APP_CODE,
            )
            or DEFAULT_WORKFLOW_MINI_APP_CODE
        ).strip()
        query = {
            "app": app_code,
            "path": action_path or "/odoo/my-approvals-to-review",
            "session": "1",
            "request_id": str(request_id or 0),
            "approver_id": str(approver_id or 0),
            "module": WORKFLOW_APPROVAL_PARAM_MODULE,
        }
        if model:
            query["model"] = model
        if res_id:
            query["res_id"] = str(res_id)
        return "app://myportal/mini?%s" % urlencode(query, safe="/")
