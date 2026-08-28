
import logging
import re
from datetime import timezone
from pprint import pformat
from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE, ACTION_TYPE
from markupsafe import Markup, escape
from odoo.tools import html2plaintext
from odoo.tools.mail import generate_tracking_message_id

_logger = logging.getLogger(__name__)

class ApprovalBaseMixin(models.AbstractModel):
    """
    This is approval base mixin which will be used to provide common methods for approval request and approval approver.
    """
    _name = 'approval.base.mixin'
    _description = 'Approval Base Mixin'

    @api.model
    def _workflow_can_force_created_uid(self):
        admin_user = self.env.ref("base.user_admin", raise_if_not_found=False)
        return bool(
            self.env.su
            or (admin_user and self.env.user == admin_user)
            or self.env.user._is_admin()
            or self.env.user._is_system()
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group("workflow_engine.group_workflow_technical_admin")
        )

    @api.model
    def _workflow_resolve_force_created_user(self):
        force_created_uid = self.env.context.get("force_created_uid")
        if not force_created_uid or not self._workflow_can_force_created_uid():
            return self.env["res.users"]
        try:
            force_created_uid = int(force_created_uid)
        except (TypeError, ValueError):
            return self.env["res.users"]
        if not force_created_uid:
            return self.env["res.users"]
        return self.env["res.users"].sudo().with_context(active_test=False).browse(force_created_uid).exists()

    def _workflow_force_created_uid_on_records(self):
        records = self.exists()
        if not records:
            return records
        forced_user = self._workflow_resolve_force_created_user()
        if not forced_user:
            return records

        records._workflow_sql_force_create_uid(forced_user)
        base_requests = getattr(records, "x_approval_base_id", self.env["workflow.base.approval.request"])
        base_requests = base_requests.exists() if base_requests else base_requests
        if base_requests and base_requests._name != records._name:
            base_requests._workflow_sql_force_create_uid(forced_user)
        return records

    def _workflow_sql_force_create_uid(self, forced_user):
        records = self.exists()
        if not records:
            return
        self.env.cr.execute(
            f'UPDATE "{records._table}" SET create_uid = %s WHERE id = ANY(%s)',
            [forced_user.id, records.ids],
        )
        records.invalidate_recordset(["create_uid"])
        records.modified(["create_uid"])

    wf_actor_uid = fields.Integer(
        string="WF Actor UID",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_name = fields.Char(
        string="WF Actor Name",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_login = fields.Char(
        string="WF Actor Login",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_department_name = fields.Char(
        string="WF Actor Department",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_position_name = fields.Char(
        string="WF Actor Position",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_group_xmlids = fields.Text(
        string="WF Actor Groups",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
        help="Comma-delimited group xmlids for runtime domain checks.",
    )
    wf_actor_is_manager = fields.Boolean(
        string="WF Actor Is Manager",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_actor_is_hod = fields.Boolean(
        string="WF Actor Is HOD",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_action_key = fields.Char(
        string="WF Action Key",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_current_node_id = fields.Char(
        string="WF Current Node",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )
    wf_active_node_ids = fields.Json(
        string="WF Active Nodes",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
        help="Current workflow node plus active parallel branch node ids.",
    )
    wf_current_stage_age_minutes = fields.Integer(
        string="WF Current Stage Age (Min)",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
        help="Live age in minutes for the actor/current workflow stage.",
    )
    wf_current_stage_age_display = fields.Char(
        string="WF Current Stage Age",
        compute="_compute_workflow_actor_runtime_fields",
        store=False,
        readonly=True,
    )

    def _workflow_can_manage_archive_state(self):
        """Allow archive/reactivate safety operations for technical admins."""
        if self.env.context.get("workflow_force_hard_delete"):
            return False
        if self.env.su:
            return False
        user = self.env.user
        return bool(
            user
            and not user.has_group("base.group_system")
            and user.has_group("workflow_engine.group_workflow_technical_admin")
        )

    def _workflow_should_archive_on_unlink(self):
        """Archive instead of deleting only for workflow technical admins."""
        return self._workflow_can_manage_archive_state()

    def _workflow_archive_on_unlink(self):
        """Soft-delete workflow requests by archiving the delegated record."""
        if "active" not in self._fields:
            return False
        self.with_context(active_test=False).sudo().write({"active": False})
        return True

    def action_archive(self):
        if self and self._workflow_can_manage_archive_state() and "active" in self._fields:
            cleanup = getattr(self, "_workflow_cleanup_force_transition_wizards_for_unlink", False)
            if cleanup:
                cleanup()
            self.with_context(active_test=False).sudo().write({"active": False})
            return True
        return super().action_archive()

    def action_unarchive(self):
        if self and self._workflow_can_manage_archive_state() and "active" in self._fields:
            self.with_context(active_test=False).sudo().write({"active": True})
            return True
        return super().action_unarchive()

    _WF_RUNTIME_TRACKING_FIELDS = {
        "state",
        "request_status",
        "current_node_id",
        "previous_node_id",
        "next_node_id",
        "active_branch_node_ids",
        "branch_gateway_node_id",
        "branch_join_node_id",
        "branch_mode",
        "current_activity_name",
        "previous_activity_name",
        "next_activity_name",
        "current_iteration_no",
        "next_is_end_event",
        "wf_is_blocked",
        "wf_block_reason",
        "approver_ids",
    }

    def _workflow_notifications_suppressed(self):
        """Return True when workflow execution must avoid user-facing alerts.

        Migration/import scripts can still drive the workflow engine normally
        while suppressing emails, push notifications, activities, SMS, and
        chatter notifications by passing ``no_email_send=True`` in context.
        The additional aliases make the intent explicit for future RPC/import
        callers without changing the public behavior of normal workflow usage.
        """
        context = self.env.context or {}
        return any(
            context.get(flag)
            for flag in (
                "no_notification",
                "no_email_send",
                "workflow_no_email_send",
                "workflow_suppress_notifications",
                "workflow_skip_notifications",
                "workflow_silent_migration",
                "workflow_migration_mode",
            )
        )

    def _workflow_cleanup_force_transition_wizards_for_unlink(self):
        """Remove transient force-transition popups that reference these records.

        ``workflow.force.transition.wizard.request_id`` is a Many2oneReference,
        so Odoo treats it as a dependency during unlink but cannot apply a real
        database cascade. Transient popup rows must never prevent deleting real
        workflow requests or child request records.
        """
        record_ids = [record_id for record_id in self.ids if isinstance(record_id, int) and record_id > 0]
        if not record_ids or "workflow.force.transition.wizard" not in self.env:
            return

        reference_ids = set(record_ids)
        if self._name != "workflow.base.approval.request" and "x_approval_base_id" in self._fields:
            base_ids = [
                record_id
                for record_id in self.sudo().mapped("x_approval_base_id").ids
                if isinstance(record_id, int) and record_id > 0
            ]
            reference_ids.update(base_ids)

        self.env["workflow.force.transition.wizard"].sudo().search(
            [("request_id", "in", list(reference_ids))]
        ).unlink()

    @api.depends_context('uid')
    def _compute_workflow_actor_runtime_fields(self):
        actor = self.env.user.sudo()
        employee = actor.employee_id
        department = actor.department_id or (employee.department_id if employee else False)
        position_name = (employee.job_id.name or "") if employee and employee.job_id else ""
        position_lower = (position_name or "").strip().lower()
        action_key = (
            self.env.context.get("wf_action_key")
            or self.env.context.get("workflow_action_key")
            or self.env.context.get("action_key")
            or ""
        )

        user_groups = getattr(actor, "group_ids", False) or getattr(actor, "groups_id", False)
        group_xmlids = []
        if user_groups:
            group_xmlids = self.env["ir.model.data"].sudo().search([
                ("model", "=", "res.groups"),
                ("res_id", "in", user_groups.ids),
            ]).mapped("complete_name")
        group_csv = f",{','.join(group_xmlids)}," if group_xmlids else ","

        for rec in self:
            manager = getattr(rec, "manager_user_id", False)
            is_manager = bool(manager and manager.id == actor.id)
            is_hod = bool(
                "hod" in position_lower
                or "head of department" in position_lower
            )
            actor_name_parts = [
                (actor.name or "").strip().lower(),
                (actor.login or "").strip().lower(),
            ]
            actor_name_match = " ".join([part for part in actor_name_parts if part]).strip()
            rec.wf_actor_uid = actor.id
            rec.wf_actor_name = actor_name_match
            rec.wf_actor_login = (actor.login or "").strip().lower()
            rec.wf_actor_department_name = (department.name or "").strip().lower() if department else ""
            rec.wf_actor_position_name = (position_name or "").strip().lower()
            rec.wf_actor_group_xmlids = group_csv
            rec.wf_actor_is_manager = is_manager
            rec.wf_actor_is_hod = is_hod
            rec.wf_action_key = action_key
            actor_node_id = rec._workflow_get_actor_primary_node_id(user=actor)
            stage_age_minutes = rec._workflow_node_age_minutes(actor_node_id)
            rec.wf_current_node_id = actor_node_id or ""
            rec.wf_active_node_ids = rec._workflow_active_node_ids_for_domains()
            rec.wf_current_stage_age_minutes = stage_age_minutes
            rec.wf_current_stage_age_display = rec._workflow_format_duration_compact(stage_age_minutes)

    def _workflow_safe_message_post(self, **kwargs):
        """Post to chatter when available, otherwise skip without breaking workflow."""
        if self._workflow_notifications_suppressed():
            return False
        kwargs = dict(kwargs or {})
        if hasattr(self, "message_post"):
            try:
                return self.message_post(**kwargs)
            except Exception as exc:
                _logger.warning(
                    "Failed to post chatter message on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
        sudo_record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(sudo_record, "message_post"):
            try:
                return sudo_record.message_post(**self._workflow_message_author_kwargs(kwargs))
            except Exception as exc:
                _logger.warning(
                    "Failed to post chatter message with elevated rights on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
                return False
        _logger.info("Skipping chatter post on model without message_post: %s", self._name)
        return False

    def _workflow_safe_message_notify(
        self,
        body,
        subject=False,
        partner_ids=None,
        target_record=False,
        model_description=False,
        force_record_name=False,
    ):
        """Send notification when available; fallback to message_post; otherwise skip."""
        if self._workflow_notifications_suppressed():
            return False
        partner_ids = partner_ids or []
        if not partner_ids:
            return False
        notify_record = target_record
        notify_self = self
        notify_kwargs = {
            "body": body,
            "subject": subject,
            "partner_ids": partner_ids,
        }
        if notify_record and hasattr(notify_record, "sudo"):
            notify_record = notify_record.sudo().exists()
        if notify_record and getattr(notify_record, "_name", False) and getattr(notify_record, "id", False):
            notify_self = self.env["mail.thread"]
            notify_kwargs.update(
                {
                    "model": notify_record._name,
                    "res_id": notify_record.id,
                    "model_description": model_description
                    or self.workflow_email_document_label(target_record=notify_record),
                    "force_record_name": force_record_name
                    or self.workflow_email_record_name(target_record=notify_record),
                }
            )
        if hasattr(notify_self, "message_notify"):
            try:
                return notify_self.message_notify(**notify_kwargs)
            except Exception as exc:
                _logger.warning(
                    "Failed to notify on %s(%s), fallback to message_post: %s",
                    notify_record._name if notify_record else self._name,
                    [notify_record.id] if notify_record else self.ids,
                    exc,
                )
        sudo_record = notify_self.sudo() if hasattr(notify_self, "sudo") else notify_self
        if hasattr(sudo_record, "message_notify"):
            try:
                return sudo_record.message_notify(**notify_kwargs)
            except Exception as exc:
                _logger.warning(
                    "Failed to notify with elevated rights on %s(%s), fallback to message_post: %s",
                    notify_record._name if notify_record else self._name,
                    [notify_record.id] if notify_record else self.ids,
                    exc,
                )
        fallback_record = (
            notify_record
            if notify_record and hasattr(notify_record, "_workflow_safe_message_post")
            else self
        )
        return fallback_record._workflow_safe_message_post(
            body=body,
            subject=subject,
            partner_ids=partner_ids,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

    def _workflow_safe_message_notify_inbox_only(
        self,
        body,
        subject=False,
        partner_ids=None,
        force_record_name=False,
    ):
        """Create inbox/web-push notifications without generating email copies."""
        if self._workflow_notifications_suppressed():
            return False
        partner_ids = [pid for pid in (partner_ids or []) if isinstance(pid, int)]
        if not partner_ids or not hasattr(self, "_message_create"):
            return False

        self.ensure_one()
        author_kwargs = self._workflow_message_author_kwargs({})
        author_id, email_from = self._message_compute_author(
            author_kwargs.get("author_id"),
            False,
        )
        msg_values = {
            "author_id": author_id,
            "email_from": email_from,
            "model": self._name,
            "res_id": self.id,
            "body": escape(body),
            "is_internal": True,
            "message_type": "user_notification",
            "subject": subject,
            "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id("mail.mt_note"),
            "message_id": generate_tracking_message_id("message-notify"),
            "partner_ids": partner_ids,
            "email_add_signature": True,
        }
        if "record_alias_domain_id" not in msg_values:
            msg_values["record_alias_domain_id"] = self._mail_get_alias_domains(
                default_company=self.env.company
            )[self.id].id
        if "record_company_id" not in msg_values:
            msg_values["record_company_id"] = self._mail_get_companies(
                default=self.env.company
            )[self.id].id
        if "reply_to" not in msg_values:
            msg_values["reply_to"] = self._notify_get_reply_to(
                default=email_from,
                author_id=author_id,
            )[self.id]

        new_message = self._message_create([msg_values])
        recipients_data = self._notify_get_recipients(
            new_message,
            msg_vals=msg_values,
            notify_author_mention=True,
        )
        recipient_partner_ids = set(partner_ids)
        recipients_data = [
            {**recipient, "notif": "inbox"}
            for recipient in recipients_data
            if recipient.get("id") in recipient_partner_ids
        ]
        if not recipients_data:
            return new_message

        notify_record = self._fallback_lang()
        notify_record._notify_thread_by_inbox(
            new_message,
            recipients_data,
            msg_vals=msg_values,
        )
        notify_record._notify_thread_by_web_push(
            new_message,
            recipients_data,
            msg_vals=msg_values,
            force_record_name=force_record_name,
        )
        return new_message

    def _workflow_safe_message_subscribe(self, partner_ids):
        if self._workflow_notifications_suppressed():
            return False
        partner_ids = partner_ids or []
        if not partner_ids:
            return False
        if hasattr(self, "message_subscribe"):
            try:
                return self.message_subscribe(partner_ids=partner_ids)
            except Exception as exc:
                _logger.debug(
                    "Retrying follower subscribe with elevated rights on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
        sudo_record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(sudo_record, "message_subscribe"):
            try:
                return sudo_record.message_subscribe(partner_ids=partner_ids)
            except Exception as exc:
                _logger.warning(
                    "Failed to subscribe followers with elevated rights on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
                return False
        _logger.info("Skipping follower subscribe on model without message_subscribe: %s", self._name)
        return False

    def _workflow_safe_message_unsubscribe(self, partner_ids):
        if self._workflow_notifications_suppressed():
            return False
        partner_ids = partner_ids or []
        if not partner_ids:
            return False
        if hasattr(self, "message_unsubscribe"):
            try:
                return self.message_unsubscribe(partner_ids=partner_ids)
            except Exception as exc:
                _logger.warning(
                    "Failed to unsubscribe followers on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
        sudo_record = self.sudo() if hasattr(self, "sudo") else self
        if hasattr(sudo_record, "message_unsubscribe"):
            try:
                return sudo_record.message_unsubscribe(partner_ids=partner_ids)
            except Exception as exc:
                _logger.warning(
                    "Failed to unsubscribe followers with elevated rights on %s(%s): %s",
                    self._name,
                    self.ids,
                    exc,
                )
                return False
        _logger.info("Skipping follower unsubscribe on model without message_unsubscribe: %s", self._name)
        return False

    def _workflow_message_author_kwargs(self, kwargs=None):
        values = dict(kwargs or {})
        if values.get("author_id"):
            return values
        actor = self._workflow_resolve_notification_actor_user()
        if actor and actor.partner_id:
            values["author_id"] = actor.partner_id.id
        return values

    def _workflow_resolve_notification_actor_user(self):
        user_id = self.env.context.get("workflow_notification_actor_user_id")
        try:
            user_id = int(user_id or 0)
        except (TypeError, ValueError):
            user_id = 0
        if user_id:
            user = self.env["res.users"].sudo().browse(user_id).exists()
            if user:
                return user
        return self.env.user.sudo()

    def _workflow_selection_label(self, field_name, value):
        field = self._fields.get(field_name)
        if not field or not getattr(field, "selection", False):
            return value or ""
        selection = field.selection
        if callable(selection):
            selection = selection(self.env)
        return dict(selection or []).get(value, value or "")

    def _workflow_log_notification_warning(self, message, request_record=False, exc=False):
        request_record = request_record or self._workflow_resolve_request_record()
        if exc:
            _logger.warning("%s: %s", message, exc)
        else:
            _logger.warning("%s", message)
        warning_body = message
        if exc:
            warning_body = _("%(message)s Details: %(details)s") % {
                "message": message,
                "details": str(exc),
            }
        request_record._workflow_safe_message_post(
            body=_("Notification warning: %s") % warning_body,
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        return False

    def _workflow_default_owner_notification_template(self):
        template_id = self.env["ir.config_parameter"].sudo().get_param(
            "workflow_engine.default_owner_notification_template_id"
        )
        try:
            template_id = int(template_id or 0)
        except (TypeError, ValueError):
            template_id = 0
        if template_id:
            template = self.env["mail.template"].sudo().browse(template_id).exists()
            if template and template.model_id and template.model_id.model == "workflow.base.approval.request":
                return template
        try:
            return self.env.ref("workflow_engine.email_template_workflow_email_notify").sudo()
        except ValueError:
            return self.env["mail.template"]

    def _workflow_owner_update_notification_users(self, current_meta_task=False):
        request_record = self._workflow_resolve_request_record()
        users = self.env["res.users"]
        meta_task = self._workflow_resolve_owner_update_meta_task(
            current_meta_task=current_meta_task
        )
        notify_owner = True
        notify_creator = True
        if meta_task:
            if "notify_request_owner_email" in meta_task._fields:
                notify_owner = bool(meta_task.notify_request_owner_email)
            if "notify_request_creator_email" in meta_task._fields:
                notify_creator = bool(meta_task.notify_request_creator_email)
        if notify_owner:
            owner = request_record.request_owner_id
            if owner and owner.exists() and owner.partner_id:
                users |= owner
        if notify_creator:
            creator = request_record.create_uid
            if creator and creator.exists() and creator.partner_id:
                users |= creator
        return users

    def _workflow_owner_update_notification_partners(self, current_meta_task=False):
        users = self._workflow_owner_update_notification_users(
            current_meta_task=current_meta_task
        )
        partner_ids = list(dict.fromkeys(users.mapped("partner_id").ids))
        return self.env["res.partner"].sudo().browse(partner_ids).exists()

    def _workflow_owner_update_notification_partner_ids(self, current_meta_task=False):
        return self._workflow_owner_update_notification_partners(
            current_meta_task=current_meta_task
        ).ids

    def _workflow_owner_update_greeting_name(self, partner_ids=None):
        partner_ids = list(dict.fromkeys(partner_ids or []))
        if len(partner_ids) != 1:
            return False
        partner = self.env["res.partner"].sudo().browse(partner_ids[0]).exists()
        if not partner:
            return False
        return partner.name or False

    def _workflow_resolve_owner_update_meta_task(self, current_meta_task=False):
        meta_task = current_meta_task[:1] if current_meta_task else self.env["workflow.category.version.meta.task"]
        if meta_task:
            return meta_task

        request_record = self._workflow_resolve_request_record()
        if (
            not request_record
            or not request_record.exists()
            or not getattr(request_record, "current_node_id", False)
            or not hasattr(request_record, "_resolve_meta_task_for_node")
        ):
            return self.env["workflow.category.version.meta.task"]
        try:
            return request_record._resolve_meta_task_for_node(
                request_record.current_node_id,
                getattr(request_record, "current_activity_name", False),
            )[:1]
        except Exception:
            return self.env["workflow.category.version.meta.task"]

    def _workflow_owner_update_is_submission_meta_task(self, meta_task, request_record=False):
        meta_task = meta_task[:1]
        if not meta_task:
            return False

        request_record = request_record or self._workflow_resolve_request_record()
        for candidate in (request_record, self):
            if candidate and hasattr(candidate, "_is_submission_meta_task"):
                try:
                    return candidate._is_submission_meta_task(meta_task)
                except Exception:
                    continue

        node_id = meta_task.node_id or ""
        version = (
            getattr(request_record, "version_id", False)
            or getattr(self, "version_id", False)
            or getattr(meta_task, "version_id", False)
        )
        if version and getattr(version, "bpmn_xml", False) and node_id:
            try:
                engine = BpmnEngine(version.bpmn_xml)
                submission_node = engine.get_submission_task()
                if submission_node is not None and node_id == submission_node.attrib.get("id"):
                    return True
            except Exception:
                pass

        name = (meta_task.name or "").lower()
        return "submit" in name or "submission" in name

    def _workflow_should_send_owner_update_notification(self, current_meta_task=False):
        request_record = self._workflow_resolve_request_record()
        if self.env.context.get("workflow_skip_owner_notify"):
            return False
        if self._workflow_notifications_suppressed():
            return False
        if not request_record or not request_record.exists():
            return False
        meta_task = self._workflow_resolve_owner_update_meta_task(
            current_meta_task=current_meta_task
        )
        if self._workflow_owner_update_is_submission_meta_task(
            meta_task,
            request_record=request_record,
        ):
            return False
        recipients = self._workflow_owner_update_notification_users(
            current_meta_task=current_meta_task
        )
        return bool(recipients)

    def _workflow_resolve_owner_update_template_and_record(self):
        request_record = self._workflow_resolve_request_record()
        version = getattr(request_record, "version_id", False) or getattr(self, "version_id", False)
        version_template = (
            version.request_owner_notification_template_id.sudo()
            if version and "request_owner_notification_template_id" in version._fields
            else self.env["mail.template"]
        )
        if version_template:
            if version_template.model_id and version_template.model_id.model == self._name:
                return version_template, self, request_record
            if version_template.model_id and version_template.model_id.model == request_record._name:
                return version_template, request_record, request_record
            if hasattr(request_record, "_get_transition_delegate_record"):
                try:
                    delegate_record = request_record._get_transition_delegate_record()
                except Exception:
                    delegate_record = self.env[request_record.res_model_name] if getattr(request_record, "res_model_name", False) else self
                if delegate_record and delegate_record._name == version_template.model_id.model:
                    return version_template, delegate_record, request_record

        default_template = self._workflow_default_owner_notification_template()
        if default_template:
            return default_template, request_record, request_record
        return self.env["mail.template"], request_record, request_record

    def _workflow_render_template_subject_body(
        self,
        template,
        render_record,
        partner_ids=None,
        stage_label=False,
    ):
        render_record = render_record.sudo().exists()
        if not template or not render_record:
            return False, False
        refresh_fields = [
            field_name
            for field_name in (
                "state",
                "request_status",
                "current_activity_name",
                "next_activity_name",
                "next_is_end_event",
                "approver_ids",
            )
            if field_name in render_record._fields
        ]
        if refresh_fields and hasattr(render_record, "flush_recordset"):
            try:
                render_record.flush_recordset(refresh_fields)
            except Exception:
                pass
        if refresh_fields and hasattr(render_record, "invalidate_recordset"):
            try:
                render_record.invalidate_recordset(refresh_fields)
            except Exception:
                pass
        actor = self._workflow_resolve_notification_actor_user()
        render_template = template.sudo().with_context(
            workflow_actor_name=actor.name or "",
            workflow_actor_user_id=actor.id or False,
            workflow_request_owner_name=render_record.request_owner_id.name if "request_owner_id" in render_record._fields and render_record.request_owner_id else "",
            workflow_request_creator_name=render_record.create_uid.name if "create_uid" in render_record._fields and render_record.create_uid else "",
            workflow_owner_update_greeting_name=self._workflow_owner_update_greeting_name(
                partner_ids=partner_ids
            ) or "",
            # Owner updates already know the target node. Prefer that runtime
            # stage label during render so emails do not lag on transitions.
            workflow_owner_update_stage_label=(stage_label or "").strip(),
        )
        subject = render_template._render_field("subject", render_record.ids).get(render_record.id) or False
        body = render_template._render_field("body_html", render_record.ids).get(render_record.id) or False
        return subject, Markup(body or "") if body else False

    def _workflow_owner_update_template_looks_generic(self, subject, body):
        subject_text = (subject or "").strip()
        body_text = re.sub(r"<[^>]+>", " ", str(body or ""))
        body_text = re.sub(r"\s+", " ", body_text).strip()
        generic_subject = subject_text.startswith("Email Notification (Ref:")
        generic_body = body_text in {"", "Email Notify"}
        return generic_body or (generic_subject and body_text in {"", "Email Notify"})

    def _workflow_build_owner_update_notification_fallback(
        self,
        request_record=False,
        target_record=False,
        partner_ids=None,
        stage_label=False,
    ):
        request_record = request_record or self._workflow_resolve_request_record()
        request_record = request_record._workflow_refresh_email_tracking_snapshot()
        target_record = target_record or request_record._workflow_resolve_notification_target_record()
        actor = self._workflow_resolve_notification_actor_user()
        document_label = request_record.workflow_email_document_label(target_record=target_record)
        request_code = request_record.workflow_email_reference_code(target_record=target_record)
        subject = request_record.workflow_email_owner_update_subject(target_record=target_record)
        greeting_name = self._workflow_owner_update_greeting_name(partner_ids=partner_ids)
        effective_stage_label = (stage_label or "").strip() or request_record.workflow_email_current_stage_label(
            target_record=target_record
        )
        greeting_html = (
            Markup("Dear <strong>{name}</strong>,").format(name=escape(greeting_name))
            if greeting_name
            else escape(_("Good day,"))
        )
        body = Markup(
            """
            <div>
                <p>{greeting}</p>
                <p>Here is the latest update on your <strong>{document}</strong> request.</p>
                <p>
                    <strong>Reference:</strong> {reference}<br/>
                    <strong>Updated By:</strong> {actor}<br/>
                    <strong>Current Stage:</strong> {stage}
                </p>
                <p>Please use the request link above to review the latest details.</p>
            </div>
            """
        ).format(
            greeting=greeting_html,
            document=escape(document_label),
            reference=escape(request_code),
            actor=escape(actor.name or request_record.create_uid.name or _("Workflow User")),
            stage=escape(effective_stage_label),
        )
        return subject, body

    def _workflow_owner_update_stage_label(
        self,
        current_meta_task=False,
        request_record=False,
        target_record=False,
    ):
        self.ensure_one()
        meta_task = current_meta_task
        if meta_task and hasattr(meta_task, "exists"):
            meta_task = meta_task.sudo().exists()
        explicit_stage_label = ((meta_task.name if meta_task else "") or "").strip()
        if explicit_stage_label:
            return explicit_stage_label
        request_record = request_record or self._workflow_resolve_request_record()
        if request_record and hasattr(request_record, "_workflow_refresh_email_tracking_snapshot"):
            request_record = request_record._workflow_refresh_email_tracking_snapshot()
        if request_record:
            return request_record.workflow_email_current_stage_label(target_record=target_record)
        return _("Unknown")

    def _workflow_send_owner_update_notification(self, current_meta_task=False):
        if not self._workflow_should_send_owner_update_notification(
            current_meta_task=current_meta_task
        ):
            return False
        partner_ids = self._workflow_owner_update_notification_partner_ids(
            current_meta_task=current_meta_task
        )
        if not partner_ids:
            return False

        template, render_record, request_record = self._workflow_resolve_owner_update_template_and_record()
        request_record = request_record._workflow_refresh_email_tracking_snapshot()
        if render_record and hasattr(render_record, "_workflow_refresh_email_tracking_snapshot"):
            render_record = render_record._workflow_refresh_email_tracking_snapshot()
        notify_record = request_record._workflow_resolve_notification_target_record()
        stage_label = self._workflow_owner_update_stage_label(
            current_meta_task=current_meta_task,
            request_record=request_record,
            target_record=notify_record,
        )
        subject, body = self._workflow_build_owner_update_notification_fallback(
            request_record=request_record,
            target_record=notify_record,
            partner_ids=partner_ids,
            stage_label=stage_label,
        )
        if template and render_record:
            try:
                rendered_subject, rendered_body = self._workflow_render_template_subject_body(
                    template,
                    render_record,
                    partner_ids=partner_ids,
                    stage_label=stage_label,
                )
                if not self._workflow_owner_update_template_looks_generic(
                    rendered_subject,
                    rendered_body,
                ):
                    subject = rendered_subject or subject
                    body = rendered_body or body
            except Exception as exc:
                self._workflow_log_notification_warning(
                    _("Could not render the owner update notification template."),
                    request_record=request_record,
                    exc=exc,
                )
        return request_record._workflow_safe_message_notify(
            body=body,
            subject=subject,
            partner_ids=partner_ids,
            target_record=notify_record,
            model_description=request_record.workflow_email_document_label(
                target_record=notify_record
            ),
            force_record_name=request_record.workflow_email_record_name(
                target_record=notify_record
            ),
        )

    def _workflow_safe_send_mail_template(
        self,
        template,
        render_record,
        email_values=None,
        warning_label=False,
        request_record=False,
    ):
        request_record = request_record or self._workflow_resolve_request_record()
        render_record = render_record.sudo().exists() if render_record else render_record
        if not template or not render_record:
            return False
        if request_record and hasattr(request_record, "_workflow_notifications_suppressed"):
            if request_record._workflow_notifications_suppressed():
                return False
        elif self._workflow_notifications_suppressed():
            return False
        try:
            return template.sudo().send_mail(
                render_record.id,
                force_send=False,
                email_values=email_values,
            )
        except Exception as exc:
            label = warning_label or _("workflow notification")
            self._workflow_log_notification_warning(
                _("Could not send %(label)s email.") % {"label": label},
                request_record=request_record,
                exc=exc,
            )
            return False

    # def create(self, vals_list):
    #     #if self._name != "workflow.base.approval.request":
    #     created_requests = super().create(vals_list)
    #     if created_requests:
    #         created_requests.write({
    #             'name': created_requests.category_id.sequence_id.next_by_id()
    #         })
    #     for request in created_requests:
    #         request._run_engine()
    #     return created_requests

    def _workflow_actor_eval_helpers(self):
        self.ensure_one()
        actual_actor = self._workflow_resolve_actual_actor_user()
        actor = self._workflow_resolve_effective_actor_user(user=actual_actor)
        delegated_from_user = actor if actor.id != actual_actor.id else self.env["res.users"]
        request_record = self.sudo()

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

        def wf_has_active_node(node_id):
            return request_record._workflow_has_active_node(node_id)

        def wf_node_age_minutes(node_id):
            return request_record._workflow_node_age_minutes(node_id)

        def wf_oldest_active_node_age_minutes():
            return request_record._workflow_oldest_active_node_age_minutes()

        def wf_youngest_active_node_age_minutes():
            return request_record._workflow_youngest_active_node_age_minutes()

        return {
            "actor": actor,
            "actual_user": actual_actor,
            "delegated_from_user": delegated_from_user,
            "actor_has_group": actor_has_group,
            "actor_name_is": actor_name_is,
            "actor_in_department": actor_in_department,
            "actor_in_position": actor_in_position,
            "actor_is_request_manager": actor_is_request_manager,
            "actor_is_hod": actor_is_hod,
            "wf_has_active_node": wf_has_active_node,
            "wf_node_age_minutes": wf_node_age_minutes,
            "wf_oldest_active_node_age_minutes": wf_oldest_active_node_age_minutes,
            "wf_youngest_active_node_age_minutes": wf_youngest_active_node_age_minutes,
        }
    
    def get_safe_eval_context(self, extra_fields=None):
        """
        Build a safe eval context with dynamic extraction of all res.users-related fields.
        """
        self.ensure_one()

        # Default: auto-collect all fields that are Many2one to res.users
        if extra_fields is None:
            extra_fields = [
                fname for fname, field in self.sudo()._fields.items()
                if isinstance(field, fields.Many2one) and field.comodel_name == 'res.users'
            ]

        context = {
            'object': self.sudo(),
            'request': self.sudo(),
            'env': self.env,
            'user': self._workflow_resolve_effective_actor_user(),
            'actual_user': self._workflow_resolve_actual_actor_user(),
        }
        delegated_from_user = self._workflow_resolve_delegated_from_user()
        if delegated_from_user:
            context["delegated_from_user"] = delegated_from_user

        for field in extra_fields:
            value = getattr(self, field, None)
            context[field] = value.id if hasattr(value, 'id') else value

        active_node_ids = self._workflow_active_node_ids_for_domains()
        actor_node_id = self._workflow_get_actor_primary_node_id(user=self._workflow_resolve_actual_actor_user())
        current_stage_age = self._workflow_node_age_minutes(actor_node_id)
        context.update({
            "wf_active_node_ids": active_node_ids,
            "active_node_ids": active_node_ids,
            "wf_current_node_id": actor_node_id or "",
            "current_node_id": actor_node_id or "",
            "wf_current_stage_age_minutes": current_stage_age,
            "current_stage_age_minutes": current_stage_age,
            "wf_current_stage_age_display": self._workflow_format_duration_compact(current_stage_age),
            "current_stage_age_display": self._workflow_format_duration_compact(current_stage_age),
        })
        context.update(self._workflow_actor_eval_helpers())

        return context

    def _workflow_open_actor_approver_rows(self, user=False, task_node_id=False):
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        user = (user or self.env.user).sudo()
        approver_rows = getattr(request_record, "approver_ids", self.env["workflow.approval.approver"])
        rows = approver_rows.filtered(
            lambda row: row.user_id.id == user.id
            and row.status in ("new", "pending", "waiting")
            and (not task_node_id or row.current_meta_node_id == task_node_id)
        )
        current_iteration = getattr(request_record, "current_iteration_no", 0) or 0
        if current_iteration:
            iteration_rows = rows.filtered(lambda row: (row.iteration_no or 1) == current_iteration)
            if iteration_rows:
                rows = iteration_rows
        return rows.sorted(key=lambda row: (row.sequence, row.id))

    def _workflow_resolve_actual_actor_user(self, user=False):
        user_id = int(self.env.context.get("workflow_actual_actor_user_id") or 0)
        if user_id:
            actual_user = self.env["res.users"].sudo().browse(user_id).exists()
            if actual_user:
                return actual_user
        return (user or self.env.user).sudo()

    def _workflow_resolve_delegated_from_user(self, user=False, task_node_id=False):
        delegated_user_id = int(
            self.env.context.get("workflow_effective_actor_user_id")
            or self.env.context.get("workflow_delegate_for_user_id")
            or self.env.context.get("workflow_delegated_from_user_id")
            or 0
        )
        actual_actor = self._workflow_resolve_actual_actor_user(user=user)
        if delegated_user_id and delegated_user_id != actual_actor.id:
            delegated_user = self.env["res.users"].sudo().browse(delegated_user_id).exists()
            if delegated_user:
                return delegated_user

        open_rows = self._workflow_open_actor_approver_rows(user=actual_actor, task_node_id=task_node_id)
        delegated_row = open_rows.filtered(
            lambda row: row.delegated_from_user_id
            and row.delegation_mode in ("shared", "redirected")
        )[:1]
        return delegated_row.delegated_from_user_id.sudo() if delegated_row and delegated_row.delegated_from_user_id else self.env["res.users"]

    def _workflow_resolve_effective_actor_user(self, user=False, task_node_id=False):
        actual_actor = self._workflow_resolve_actual_actor_user(user=user)
        delegated_from_user = self._workflow_resolve_delegated_from_user(
            user=actual_actor,
            task_node_id=task_node_id,
        )
        return delegated_from_user or actual_actor

    def _workflow_build_action_execution_context(self, permission=False, actor_user=False, task_node_id=False):
        self.ensure_one()
        actor_user = self._workflow_resolve_actual_actor_user(user=actor_user)
        context = {
            "workflow_actual_actor_user_id": actor_user.id,
        }

        permission = permission or {}
        effective_user_id = int(
            permission.get("on_behalf_user_id")
            or self.env.context.get("workflow_effective_actor_user_id")
            or self.env.context.get("workflow_delegate_for_user_id")
            or 0
        )
        if not effective_user_id:
            delegated_from_user = self._workflow_resolve_delegated_from_user(
                user=actor_user,
                task_node_id=task_node_id,
            )
            effective_user_id = delegated_from_user.id if delegated_from_user else 0

        if effective_user_id and effective_user_id != actor_user.id:
            context.update({
                "workflow_effective_actor_user_id": effective_user_id,
                "workflow_delegate_for_user_id": effective_user_id,
                "workflow_delegated_from_user_id": effective_user_id,
            })

        manual_row_id = int(permission.get("manual_delegated_approver_id") or 0)
        source_approver_id = int(permission.get("source_approver_id") or 0)
        if not manual_row_id:
            open_rows = self._workflow_open_actor_approver_rows(user=actor_user, task_node_id=task_node_id)
            manual_row = open_rows.filtered(
                lambda row: row.delegated_from_user_id
                and row.delegation_mode in ("shared", "redirected")
                and (not effective_user_id or row.delegated_from_user_id.id == effective_user_id)
            )[:1]
            manual_row_id = manual_row.id if manual_row else 0
            source_approver_id = source_approver_id or (manual_row.delegated_from_approver_id.id if manual_row and manual_row.delegated_from_approver_id else 0)

        if manual_row_id:
            context["workflow_manual_delegated_approver_id"] = manual_row_id
        if source_approver_id:
            context["workflow_delegate_source_approver_id"] = source_approver_id
        return context

    def _workflow_resolve_request_record(self):
        self.ensure_one()
        if self._name == "workflow.base.approval.request":
            return self
        if "x_approval_base_id" in self._fields and self.x_approval_base_id:
            return self.x_approval_base_id
        return self

    def _workflow_resolve_notification_target_record(self):
        self.ensure_one()
        if self._name != "workflow.base.approval.request":
            return self
        delegate_getter = getattr(self, "_get_transition_delegate_record", False)
        if delegate_getter:
            try:
                target = delegate_getter()
            except Exception:
                target = False
            if target and hasattr(target, "exists"):
                target = target.exists()
            if target and getattr(target, "_name", False) and getattr(target, "id", False):
                return target
        return self

    def _workflow_refresh_email_tracking_snapshot(self):
        self.ensure_one()
        record = self.sudo().exists()
        if not record:
            return self
        refresh_fields = [
            field_name
            for field_name in (
                "state",
                "request_status",
                "current_activity_name",
                "next_activity_name",
                "next_is_end_event",
                "approver_ids",
            )
            if field_name in record._fields
        ]
        if refresh_fields and hasattr(record, "flush_recordset"):
            try:
                record.flush_recordset(refresh_fields)
            except Exception:
                pass
        if refresh_fields and hasattr(record, "invalidate_recordset"):
            try:
                record.invalidate_recordset(refresh_fields)
            except Exception:
                pass
        return record

    def _workflow_notification_target_label(self, target_record=False):
        self.ensure_one()
        target = target_record or self._workflow_resolve_notification_target_record()
        if target and hasattr(target, "exists"):
            target = target.exists()
        if not target:
            return _("Workflow Request")
        if getattr(target, "_name", "") == "workflow.base.approval.request":
            return getattr(target.category_id, "name", False) or _("Workflow Request")
        try:
            model_info = self.env["ir.model"].sudo()._get(target._name)
        except Exception:
            model_info = False
        return (
            (model_info.display_name or model_info.name)
            if model_info
            else (getattr(target, "_description", False) or _("Workflow Request"))
        )

    def workflow_email_document_label(self, target_record=False):
        self.ensure_one()
        return self._workflow_notification_target_label(target_record=target_record)

    def workflow_email_reference_code(self, target_record=False):
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        target = target_record or self._workflow_resolve_notification_target_record()
        for record in (target, request_record):
            if not record:
                continue
            code = getattr(record, "name", False) or getattr(record, "display_name", False)
            if code:
                return code
        return _("Draft")

    def workflow_email_record_name(self, target_record=False):
        self.ensure_one()
        target = target_record or self._workflow_resolve_notification_target_record()
        if target and hasattr(target, "exists"):
            target = target.exists()
        if target:
            return (
                getattr(target, "display_name", False)
                or getattr(target, "name", False)
                or self.workflow_email_reference_code(target_record=target)
            )
        return self.workflow_email_reference_code()

    def workflow_email_current_stage_label(self, target_record=False):
        self.ensure_one()
        override_stage_label = (self.env.context.get("workflow_owner_update_stage_label") or "").strip()
        if override_stage_label:
            return override_stage_label
        request_record = self._workflow_resolve_request_record()._workflow_refresh_email_tracking_snapshot()
        state_label = request_record._workflow_selection_label("state", request_record.state)
        current_stage = (request_record.current_activity_name or "").strip()
        if request_record.state in {
            "done",
            "completed",
            "cancelled",
            "auto_cancelled",
            "refused",
            "auto_approved",
        }:
            return state_label or current_stage or _("Completed")
        if current_stage:
            return current_stage
        if request_record.next_is_end_event and request_record.next_activity_name:
            return request_record.next_activity_name
        return state_label or request_record.workflow_email_status_label(target_record=target_record)

    def workflow_email_status_label(self, target_record=False):
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()._workflow_refresh_email_tracking_snapshot()
        status_value = request_record.request_status
        terminal_status_getter = getattr(request_record, "_workflow_terminal_state_to_request_status", False)
        if callable(terminal_status_getter):
            terminal_status = terminal_status_getter(request_record.state)
            if terminal_status:
                status_value = terminal_status
        elif request_record.state == "done":
            status_value = "done"
        status_label = request_record._workflow_selection_label("request_status", status_value)
        if status_label:
            return status_label
        return request_record._workflow_selection_label("state", request_record.state) or _("Unknown")

    def workflow_email_action_button_label(self, target_record=False):
        self.ensure_one()
        return _("View %s", self.workflow_email_document_label(target_record=target_record))

    def workflow_email_owner_update_subject(self, target_record=False):
        self.ensure_one()
        return _("Update on your %(document)s - %(reference)s") % {
            "document": self.workflow_email_document_label(target_record=target_record),
            "reference": self.workflow_email_reference_code(target_record=target_record),
        }

    def _workflow_elevated_action_record(self):
        """Return the same record in workflow-authorized elevated mode.

        This helper is only for engine-owned execution after the actor has
        already passed the workflow permission gate.
        """
        self.ensure_one()
        return self.sudo().with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
        )

    def _workflow_is_child_request_model(self):
        return self._name != "workflow.base.approval.request" and "x_approval_base_id" in self._fields

    def _workflow_done_action_requests(self):
        """Resolve base workflow requests for the public `action_set_done` helper."""
        request_model = self.env["workflow.base.approval.request"]
        requests = request_model.browse()
        for record in self:
            if record._name == "workflow.base.approval.request":
                requests |= record
                continue
            if "x_approval_base_id" in record._fields and record.x_approval_base_id:
                requests |= record.x_approval_base_id
        return requests.exists()

    def action_set_done(self):
        """Mark waiting workflow requests as informationally done.

        This is intended for workflow on-behalf admins and automations that need
        to suppress user-facing waiting/pending indicators while keeping the
        workflow record open for later administrative action.
        """
        requests = self._workflow_done_action_requests()
        if not requests:
            raise UserError(_("Set Done is only available on workflow requests."))

        denied_requests = self.env["workflow.base.approval.request"].browse()
        if not self.env.su:
            denied_requests = requests.filtered(
                lambda req: not req._workflow_user_is_on_behalf_admin(user=self.env.user)
            )
        if denied_requests:
            raise AccessError(
                _("Only workflow on-behalf admins can set requests to Done.")
            )

        eligible_requests = requests.filtered(lambda req: req.state in ("waiting", "done"))
        changed_requests = eligible_requests.filtered(lambda req: req.state != "done")
        if changed_requests:
            changed_requests.sudo().write({"state": "done"})

        if not self.env.context.get("workflow_silent_done_action"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Set Done"),
                    "message": _(
                        "Processed %(request_count)s request(s). Marked %(done_count)s request(s) as Done."
                    )
                    % {
                        "request_count": len(requests),
                        "done_count": len(changed_requests),
                    },
                    "type": "success" if changed_requests or eligible_requests else "warning",
                    "sticky": False,
                    "next": {"type": "ir.actions.client", "tag": "reload"},
                },
            }
        return True

    def _check_access(self, operation):
        if not self._workflow_is_child_request_model() or self.env.su or operation == "create":
            return super()._check_access(operation)

        translate = self.env._
        if self.env.context.get("workflow_history_mode"):
            if operation != "read":
                return self, lambda: AccessError(
                    translate("Workflow history is read-only.")
                )
            allowed_ids = set(self._workflow_history_effective_allowed_record_ids())
            denied = self.filtered(lambda record: record.id not in allowed_ids)
            if denied:
                return denied, lambda: AccessError(
                    translate("You are not allowed to access one or more workflow history records.")
                )
            return None

        Access = self.env["ir.model.access"]
        if not Access.check(self._name, operation, raise_exception=False):
            return self, lambda: AccessError(
                translate("You are not allowed to %(operation)s records of model %(model)s.")
                % {"operation": operation, "model": self._name}
            )

        service = self.env["workflow.engine.permission.service"]
        scope = "edit" if operation in ("write", "unlink") else "read"
        denied = self.browse()
        if scope == "read":
            base_requests = self.sudo().mapped("x_approval_base_id").exists()
            allowed_request_ids = service.allowed_request_ids(
                base_requests,
                user=self.env.user,
                scope=scope,
            )
            denied = self.filtered(
                lambda record: not record.sudo().x_approval_base_id
                or record.sudo().x_approval_base_id.id not in allowed_request_ids
            )
        else:
            for record in self:
                request_record = record.sudo().x_approval_base_id
                if not request_record or not service.can_access_request(
                    request_record,
                    user=self.env.user,
                    scope=scope,
                ):
                    denied |= record
        if denied:
            return denied, lambda: AccessError(
                _("You are not allowed to access one or more workflow requests.")
            )
        return None

    def check_access_rule(self, operation):
        if self._workflow_is_child_request_model():
            self.check_access(operation)
            return None
        return super().check_access_rule(operation)

    @api.model
    def _workflow_is_dryrun_mode(self):
        return bool(
            self.env.context.get("wf_dryrun_mode")
            and self.env.context.get("wf_dryrun_wizard_id")
        )

    @api.model
    def _workflow_get_dryrun_wizard(self):
        wizard_id = self.env.context.get("wf_dryrun_wizard_id")
        if not wizard_id:
            return self.env["workflow.dryrun.wizard"]
        return self.env["workflow.dryrun.wizard"].sudo().browse(wizard_id).exists()

    @api.model
    def _workflow_get_dryrun_actor_user(self):
        wizard = self._workflow_get_dryrun_wizard()
        if wizard and wizard.simulated_user_id:
            return wizard.simulated_user_id.sudo()
        dryrun_user_id = self.env.context.get("wf_dryrun_simulated_user_id")
        if dryrun_user_id:
            return self.env["res.users"].sudo().browse(dryrun_user_id)
        return self.env.user.sudo()

    @api.model
    def _workflow_build_dryrun_request_virtual_record(self, snapshot_values=False):
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        wizard = self._workflow_get_dryrun_wizard()
        stub_values = {}
        if wizard:
            stub_values = dict(wizard._build_request_stub_values() or {})
        elif isinstance(self.env.context.get("wf_dryrun_request_stub"), dict):
            stub_values = dict(self.env.context.get("wf_dryrun_request_stub") or {})
        request_model = self.env["workflow.base.approval.request"]
        virtual_snapshot_vals = request_model._workflow_virtual_vals_from_snapshot(snapshot_values)
        stub_values.update(virtual_snapshot_vals)
        if wizard and wizard.category_id:
            stub_values["category_id"] = wizard.category_id.id
            stub_values["request_owner_id"] = wizard.simulated_user_id.id
            if wizard.simulated_user_id:
                if "create_uid" in request_model._fields and not stub_values.get("create_uid"):
                    stub_values["create_uid"] = wizard.simulated_user_id.id
                if "write_uid" in request_model._fields and not stub_values.get("write_uid"):
                    stub_values["write_uid"] = wizard.simulated_user_id.id
        if "company_id" not in stub_values and wizard and wizard.category_id.company_id:
            stub_values["company_id"] = wizard.category_id.company_id.id
        return request_model.new(stub_values)

    def _workflow_get_open_approval_actor_node_ids(self, user=False):
        """
        Return ordered node ids where the actor currently has open approver rows.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        user = user or self.env.user
        approver_rows = getattr(request_record.sudo(), "approver_ids", self.env["workflow.approval.approver"])
        if not approver_rows:
            return []

        current_iteration = getattr(request_record, "current_iteration_no", 0) or 0
        rows = approver_rows.filtered(
            lambda a: a.user_id.id == user.id and a.status in ("new", "pending", "waiting")
        )
        if current_iteration:
            rows = rows.filtered(lambda a: (a.iteration_no or 1) == current_iteration) or rows

        # Guard against stale open rows from previous activities:
        # when runtime has an explicit current node (and optional active branch
        # nodes), prefer those nodes for action resolution so UI buttons stay
        # aligned with the effective stage.
        active_nodes = set()
        current_node_id = getattr(request_record, "current_node_id", False)
        if current_node_id:
            active_nodes.add(current_node_id)
        branch_nodes = set((getattr(request_record, "active_branch_node_ids", None) or []))
        active_nodes |= branch_nodes
        if active_nodes:
            active_rows = rows.filtered(lambda a: a.current_meta_node_id in active_nodes)
            if active_rows:
                rows = active_rows
            else:
                # Ignore stale open rows that point to unrelated historical nodes.
                # Returning an empty node list here allows the caller to fall back to
                # request.current_node_id for deterministic button rendering.
                rows = rows.filtered(lambda a: not a.current_meta_node_id)

        preferred_nodes = set((getattr(request_record, "active_branch_node_ids", None) or []))
        if current_node_id:
            preferred_nodes.add(current_node_id)
        ordered = []
        for row in rows.sorted(
            key=lambda r: (
                0 if preferred_nodes and r.current_meta_node_id in preferred_nodes else 1,
                r.sequence or 0,
                r.create_date or fields.Datetime.now(),
                r.id,
            )
        ):
            node_id = row.current_meta_node_id
            if node_id and node_id not in ordered:
                ordered.append(node_id)
        return ordered

    def _workflow_get_open_actor_node_ids(self, user=False):
        """Return active nodes where the user holds approval or business action rights."""
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        user = user or self.env.user
        ordered = list(request_record._workflow_get_open_approval_actor_node_ids(user=user))
        assignment_service = self.env["workflow.engine.assignment.service"]
        business_rows = assignment_service._open_business_action_assignments(
            request_record,
            user=user,
        )
        active_nodes = set(request_record._workflow_active_actor_node_ids())
        business_node_ids = []
        for row in business_rows.sorted(
            key=lambda assignment: (
                assignment.task_instance_id.iteration_no or 1,
                assignment.task_instance_id.id,
                assignment.id,
            )
        ):
            node_id = row.node_id
            if node_id and (not active_nodes or node_id in active_nodes) and node_id not in business_node_ids:
                business_node_ids.append(node_id)
        for node_id in business_node_ids:
            if node_id not in ordered:
                ordered.append(node_id)
        return ordered

    def _workflow_get_actor_primary_node_id(self, user=False):
        """
        Resolve the effective workflow node for actor-specific UI/rule evaluation.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        open_nodes = request_record._workflow_get_open_actor_node_ids(user=user)
        if open_nodes:
            return open_nodes[0]
        current_node_id = getattr(request_record, "current_node_id", False)
        if current_node_id:
            return current_node_id
        return request_record._workflow_get_initial_actor_node_id()

    def _workflow_get_initial_actor_node_id(self):
        """Return the first user-action node while a request has not entered BPMN yet."""
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        state = getattr(request_record, "state", False)
        if request_record.id and state not in ("draft", "new"):
            return False

        version = getattr(request_record, "version_id", False)
        if not version or not version.meta_task_ids:
            return False

        version = version.sudo()
        meta_tasks = version.meta_task_ids
        user_node_types = {
            NODE_TYPE["USER_TASK"],
            NODE_TYPE["MANUAL_TASK"],
            NODE_TYPE["TASK"],
        }

        def _meta_for_node(node_id):
            if not node_id:
                return self.env["workflow.category.version.meta.task"]
            return meta_tasks.filtered(lambda task: task.node_id == node_id)[:1]

        if version.bpmn_xml:
            try:
                engine = BpmnEngine(version.bpmn_xml)
                submission_node = engine.get_submission_task()
                submission_node_id = (
                    submission_node.attrib.get("id") if submission_node is not None else False
                )
                if _meta_for_node(submission_node_id):
                    return submission_node_id

                start_node = engine.get_start_event()
                seen = set()

                def _first_user_node(element):
                    if element is None:
                        return False
                    node_id = element.attrib.get("id")
                    if not node_id or node_id in seen:
                        return False
                    seen.add(node_id)
                    element_type = engine.get_element_type(element)
                    if element_type in user_node_types and _meta_for_node(node_id):
                        return node_id
                    for next_element in engine.get_next_elements(
                        element,
                        form_data=None,
                        evaluate_conditions=False,
                    ):
                        found_node_id = _first_user_node(next_element)
                        if found_node_id:
                            return found_node_id
                    return False

                initial_node_id = _first_user_node(start_node)
                if initial_node_id:
                    return initial_node_id
            except Exception:
                _logger.debug(
                    "Could not resolve initial workflow actor node for request %s",
                    request_record.id,
                    exc_info=True,
                )

        submission_tasks = meta_tasks.filtered(
            lambda task: task.node_type in user_node_types
            and (
                "submit" in (task.name or "").strip().lower()
                or "submission" in (task.name or "").strip().lower()
            )
        )
        if submission_tasks:
            return submission_tasks.sorted(key=lambda task: (task.sequence or 0, task.id))[0].node_id

        user_tasks = meta_tasks.filtered(lambda task: task.node_type in user_node_types)
        if user_tasks:
            return user_tasks.sorted(key=lambda task: (task.sequence or 0, task.id))[0].node_id

        return False

    def _workflow_active_actor_node_ids(self):
        """Return active actor-stage node ids that may expose decision actions."""
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        nodes = []
        current_node_id = getattr(request_record, "current_node_id", False)
        if current_node_id:
            nodes.append(current_node_id)
        for node_id in (getattr(request_record, "active_branch_node_ids", None) or []):
            if node_id and node_id not in nodes:
                nodes.append(node_id)
        return nodes

    def _workflow_active_node_ids_for_domains(self):
        """Return active workflow node ids for domain/runtime evaluation."""
        self.ensure_one()
        return self._workflow_resolve_request_record()._workflow_active_actor_node_ids()

    def _workflow_has_active_node(self, node_id):
        self.ensure_one()
        node_id = (node_id or "").strip()
        return bool(node_id and node_id in self._workflow_active_node_ids_for_domains())

    @api.model
    def _workflow_to_utc_datetime(self, value):
        if not value:
            return None
        dt = fields.Datetime.to_datetime(value)
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @api.model
    def _workflow_format_duration_compact(self, total_minutes):
        minutes = max(int(total_minutes or 0), 0)
        days = minutes // 1440
        hours = (minutes % 1440) // 60
        rem_minutes = minutes % 60
        if days:
            return _("%(days)sd %(hours)sh") % {"days": days, "hours": hours}
        if hours:
            return _("%(hours)sh %(minutes)sm") % {"hours": hours, "minutes": rem_minutes}
        return _("%sm") % rem_minutes

    def _workflow_stage_entered_at(self, node_id):
        """Resolve when the current active node was entered.

        Uses open approver rows first because they are created at stage entry and
        are already scoped by workflow iteration. Fallbacks keep draft/system
        stages usable without inventing new persistent state.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record().sudo()
        node_id = (node_id or "").strip()
        if not node_id or node_id not in request_record._workflow_active_node_ids_for_domains():
            return None

        current_iteration = getattr(request_record, "current_iteration_no", 0) or 1
        approver_rows = getattr(
            request_record,
            "approver_ids",
            self.env["workflow.approval.approver"],
        ).sudo()
        rows = approver_rows.filtered(
            lambda row: row.current_meta_node_id == node_id
            and (row.iteration_no or 1) == current_iteration
            and row.status in ("new", "pending", "waiting", "view")
        )
        if not rows:
            rows = approver_rows.filtered(
                lambda row: row.current_meta_node_id == node_id
                and (row.iteration_no or 1) == current_iteration
            )
        entered_values = [
            self._workflow_to_utc_datetime(row.create_date)
            for row in rows
            if row.create_date
        ]
        if entered_values:
            return min(entered_values)
        return self._workflow_to_utc_datetime(
            getattr(request_record, "write_date", False)
            or getattr(request_record, "create_date", False)
        )

    def _workflow_node_age_minutes(self, node_id, now=False):
        self.ensure_one()
        entered_at = self._workflow_stage_entered_at(node_id)
        if not entered_at:
            return 0
        now_dt = self._workflow_to_utc_datetime(now or fields.Datetime.now()) or entered_at
        minutes = max(int((now_dt - entered_at).total_seconds() // 60), 0)
        if now_dt > entered_at and minutes == 0:
            return 1
        return minutes

    def _workflow_oldest_active_node_age_minutes(self, now=False):
        self.ensure_one()
        ages = [
            self._workflow_node_age_minutes(node_id, now=now)
            for node_id in self._workflow_active_node_ids_for_domains()
        ]
        return max(ages or [0])

    def _workflow_youngest_active_node_age_minutes(self, now=False):
        self.ensure_one()
        ages = [
            self._workflow_node_age_minutes(node_id, now=now)
            for node_id in self._workflow_active_node_ids_for_domains()
        ]
        return min(ages or [0])

    def _workflow_user_is_on_behalf_admin(self, user=False):
        """Return True when user may execute assigned-stage actions on behalf.

        This is intentionally narrower than read/access policy. Category
        allowed users/groups can read or participate, but only these admin
        principals get task-owner override.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        user = user or self.env.user
        if not user:
            return False
        if (
            user.has_group("base.group_system")
            or user.has_group("workflow_engine.group_workflow_technical_admin")
        ):
            return True

        category = getattr(request_record.sudo(), "category_id", False)
        if not category:
            return False
        admin_queue_user = getattr(category, "admin_queue_user_id", False)
        if admin_queue_user and admin_queue_user.id == user.id:
            return True
        try:
            admin_groups = getattr(category, "admin_group_ids", False)
        except Exception:
            # During rolling deploys the Python field can be loaded before the
            # m2m relation table is created by `-u workflow_engine`.
            admin_groups = False
        if admin_groups:
            return bool(user.sudo().group_ids & admin_groups.sudo())
        return False

    def _workflow_get_action_label(self, action):
        self.ensure_one()
        if not action:
            return ""
        return (
            (getattr(action, "attr_label", False) or "").strip()
            or (getattr(action, "action_button_label", False) or "").strip()
            or (getattr(action, "name", False) or "").strip()
        )

    def _is_submit_decision_label(self, decision_label):
        """Return True for actions that represent a submission decision."""
        return "submit" in ((decision_label or "").strip().lower())

    def _get_latest_submission_actor_from_history(self, submission_node_id):
        """Resolve the most recent submit actor on the submission node.

        Important:
        - Rework/approve/reject audit rows that target Submission must not be
          treated as submit actors.
        """
        self.ensure_one()
        empty_users = self.env["res.users"]
        if not submission_node_id:
            return empty_users

        request_record = self._workflow_resolve_request_record()
        approver_rows = getattr(
            request_record,
            "approver_ids",
            self.env["workflow.approval.approver"].browse(),
        )
        if not approver_rows:
            return empty_users

        submission_rows = approver_rows.filtered(
            lambda a: a.current_meta_node_id == submission_node_id
            and bool((a.user_decision or "").strip())
            and request_record._is_submit_decision_label(a.user_decision)
        ).sorted(
            key=lambda a: (
                a.iteration_no or 0,
                a.create_date or fields.Datetime.now(),
                a.id,
            ),
            reverse=True,
        )
        return submission_rows[:1].user_id

    def workflow_get_runtime_field_state_map(
        self,
        action_key=False,
        task_node_id=False,
        meta_action_id=False,
        view_id=False,
        snapshot_values=False,
        **kwargs,
    ):
        """
        Public RPC entrypoint for wf_form:
        server-evaluate runtime field states and return normalized booleans per field.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        permission_service = self.env["workflow.engine.permission.service"]
        if (
            request_record._name == "workflow.base.approval.request"
            and not self.env.su
            and not permission_service.can_access_request(request_record, user=self.env.user, scope="read")
        ):
            raise AccessError(_("You are not allowed to read this workflow request."))

        if meta_action_id:
            meta_action = self.env["workflow.category.version.meta.task.action"].sudo().browse(meta_action_id)
            if meta_action.exists():
                action_key = action_key or meta_action.name or meta_action.attr_label
                task_node_id = task_node_id or meta_action.source_id

        field_rule_service = self.env["workflow.engine.field.rule.service"]
        payload = field_rule_service.evaluate_runtime_field_state_map(
            target_record=self,
            request_record=request_record,
            task_node_id=task_node_id or request_record._workflow_get_actor_primary_node_id(user=self.env.user),
            action_key=action_key,
            view_id=view_id,
            user=self.env.user,
            snapshot_values=snapshot_values if isinstance(snapshot_values, dict) else None,
        )
        self._workflow_force_payload_readonly_for_non_actor(
            payload,
            target_record=self,
            request_record=request_record,
        )
        return payload

    def _workflow_force_payload_readonly_for_non_actor(self, payload, target_record=False, request_record=False):
        """Make runtime RPC payload readonly when actor has no open activity.

        Studio field rules can make individual fields readonly. This guard is
        broader: users without the current activity should not be able to edit
        any loaded workflow form field, even when they are workflow admins.
        """
        if not isinstance(payload, dict):
            return
        request_record = request_record or self._workflow_resolve_request_record()
        target_record = target_record or self
        if not request_record.id and getattr(request_record, "state", False) in ("draft", "new"):
            return
        if not request_record or request_record.check_if_user_has_permission(request_record):
            return
        field_names = set(getattr(target_record, "_fields", {}) or {})
        # Also cover shared/base request fields when the RPC target is a child
        # model. Unknown names are harmless; the client applies only active ones.
        field_names |= set(getattr(request_record, "_fields", {}) or {})
        if not field_names:
            return
        field_state_map = payload.setdefault("field_state_map", {})
        for field_name in field_names:
            state = field_state_map.setdefault(
                field_name,
                {"invisible": False, "readonly": False, "required": False},
            )
            state["readonly"] = True
            state["required"] = False
        payload["readonly_fields"] = sorted(set(payload.get("readonly_fields") or []) | field_names)
        payload["required_fields"] = [
            name for name in (payload.get("required_fields") or [])
            if name not in field_names
        ]

    def _workflow_meta_field_has_condition_domain(self, meta_field):
        domain = (getattr(meta_field, "domain", False) or "").strip()
        return bool(domain and domain not in ("[]", "[ ]", "False", "false", "0"))

    def _workflow_button_required_field_payload(
        self,
        action,
        meta_task,
        target_record=False,
        task_node_id=False,
        snapshot_values=False,
        user=False,
    ):
        """Return action-required fields after evaluating conditional domains.

        Button payloads are used by the web client for pre-save validation. They
        must reflect the same meta-field domains as the server action guard, but
        only pay the runtime-evaluation cost for buttons that actually have
        conditional required rules.
        """
        self.ensure_one()
        all_require_fields = []
        action_required_fields = []
        conditional_required_fields = []
        seen_all = set()
        seen_action = set()

        if not meta_task:
            return {
                "required_fields": [],
                "all_require_fields": [],
                "has_conditional_required_fields": False,
                "conditional_required_fields": [],
            }

        for meta_field in meta_task.field_ids.filtered(lambda row: row.field_type == "required"):
            field_name = meta_field.field_id.name
            if not field_name:
                continue
            if field_name not in seen_all:
                all_require_fields.append(field_name)
                seen_all.add(field_name)

            if meta_field.activity_action_ids and action not in meta_field.activity_action_ids:
                continue
            if field_name not in seen_action:
                action_required_fields.append(field_name)
                seen_action.add(field_name)
            if self._workflow_meta_field_has_condition_domain(meta_field):
                conditional_required_fields.append(field_name)

        if not conditional_required_fields:
            return {
                "required_fields": action_required_fields,
                "all_require_fields": all_require_fields,
                "has_conditional_required_fields": False,
                "conditional_required_fields": [],
            }

        target_record = target_record or self._workflow_runtime_delegate_record()
        request_record = (
            target_record._workflow_resolve_request_record()
            if hasattr(target_record, "_workflow_resolve_request_record")
            else self._workflow_resolve_request_record()
        )
        field_rule_service = self.env["workflow.engine.field.rule.service"].sudo()
        payload = field_rule_service.evaluate_runtime_field_state_map(
            target_record=target_record.sudo(),
            request_record=request_record.sudo(),
            task_node_id=task_node_id or action.source_id or meta_task.node_id,
            action_key=action.name or action.attr_label,
            user=user or self.env.user,
            snapshot_values=snapshot_values if isinstance(snapshot_values, dict) else None,
        )
        runtime_required = set(payload.get("required_fields") or [])
        return {
            "required_fields": [
                field_name
                for field_name in action_required_fields
                if field_name in runtime_required
            ],
            "all_require_fields": all_require_fields,
            "has_conditional_required_fields": True,
            "conditional_required_fields": sorted(set(conditional_required_fields)),
        }

    def _workflow_runtime_delegate_record(self):
        """Return the concrete workflow form when a base request has one."""
        self.ensure_one()
        delegate_getter = getattr(self, "_get_transition_delegate_record", None)
        if callable(delegate_getter):
            delegate = delegate_getter()
            if delegate and delegate._name != self._name:
                return delegate
        return self

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
        """Return reachable user/call tasks before executing side effects.

        Base requests can be the RPC/test target, but concrete Studio request
        records own the business fields. Delegate when possible so conditions
        and assignment domains are evaluated against the same form record as
        real runtime routing.
        """
        self.ensure_one()
        delegate = self._workflow_runtime_delegate_record()
        if delegate._name != self._name and callable(getattr(delegate, "_workflow_collect_execute_path_targets", None)):
            return delegate._workflow_collect_execute_path_targets(
                engine=engine,
                start_node=start_node,
                source_node=source_node,
                form_data=form_data,
                max_hops=max_hops,
            )

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
                    # Router services are pass-through during execute-path precheck.
                    pass
            for next_node in self._workflow_get_next_elements(engine, current, form_data=form_data):
                queue.append((next_node, current))
        return activations

    def _workflow_precheck_execute_path_assignments(self, engine, activations):
        self.ensure_one()
        delegate = self._workflow_runtime_delegate_record()
        if delegate._name != self._name and callable(getattr(delegate, "_workflow_precheck_execute_path_assignments", None)):
            return delegate._workflow_precheck_execute_path_assignments(engine, activations)
        precheck = getattr(self, "_precheck_next_stage_assignment", None)
        if not callable(precheck):
            return None
        for activation_node, previous_node in activations:
            blocked_action = precheck(
                engine=engine,
                current_node=previous_node,
                next_node=activation_node,
            )
            if blocked_action:
                return blocked_action
        return None

    @api.model
    def _workflow_virtual_vals_from_snapshot(self, snapshot_values):
        return self._workflow_virtual_vals_from_snapshot_for_model(
            self,
            snapshot_values,
        )

    @api.model
    def _workflow_virtual_vals_from_snapshot_for_model(self, target_model, snapshot_values, depth=0):
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        if depth > 3:
            return {}
        vals = {}
        for field_name, raw_value in snapshot_values.items():
            field = target_model._fields.get(field_name)
            if not field:
                continue
            if field.type == "many2one":
                if isinstance(raw_value, dict):
                    vals[field_name] = raw_value.get("id") or False
                elif isinstance(raw_value, (list, tuple)):
                    vals[field_name] = raw_value[0] if raw_value else False
                else:
                    vals[field_name] = raw_value or False
                continue
            if field.type == "many2many":
                ids = []
                if isinstance(raw_value, list):
                    for item in raw_value:
                        if isinstance(item, dict) and item.get("id"):
                            ids.append(item["id"])
                        elif isinstance(item, int):
                            ids.append(item)
                vals[field_name] = [Command.set(list(dict.fromkeys(ids)))]
                continue
            if field.type == "one2many":
                commands = []
                if isinstance(raw_value, list):
                    child_model = self.env[field.comodel_name]
                    for item in raw_value:
                        if isinstance(item, dict):
                            item_id = item.get("id") or False
                            child_vals = self._workflow_virtual_vals_from_snapshot_for_model(
                                child_model,
                                item,
                                depth=depth + 1,
                            )
                            if item_id and child_vals:
                                commands.append(Command.update(item_id, child_vals))
                            elif item_id:
                                commands.append(Command.link(item_id))
                            elif child_vals:
                                commands.append(Command.create(child_vals))
                vals[field_name] = commands
                continue
            vals[field_name] = raw_value
        return vals

    @api.model
    def workflow_get_runtime_field_state_map_virtual(
        self,
        action_key=False,
        task_node_id=False,
        meta_action_id=False,
        view_id=False,
        snapshot_values=False,
        **kwargs,
    ):
        """
        Runtime map for unsaved/new forms (no resId yet).
        Evaluates policies against a virtual in-memory record built from snapshot values.
        """
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        actor_user = self._workflow_get_dryrun_actor_user() if self._workflow_is_dryrun_mode() else self.env.user
        virtual_vals = self._workflow_virtual_vals_from_snapshot(snapshot_values)
        target_record = self.new(virtual_vals)
        request_record = target_record._workflow_resolve_request_record()
        if self._workflow_is_dryrun_mode() and request_record._name != "workflow.base.approval.request":
            request_record = self._workflow_build_dryrun_request_virtual_record(snapshot_values=snapshot_values)

        permission_service = self.env["workflow.engine.permission.service"]
        if (
            request_record
            and request_record._name == "workflow.base.approval.request"
            and request_record.id
            and not self.env.su
            and not permission_service.can_access_request(request_record, user=self.env.user, scope="read")
        ):
            raise AccessError(_("You are not allowed to read this workflow request."))

        if meta_action_id:
            meta_action = self.env["workflow.category.version.meta.task.action"].sudo().browse(meta_action_id)
            if meta_action.exists():
                action_key = action_key or meta_action.name or meta_action.attr_label
                task_node_id = task_node_id or meta_action.source_id

        action_key = (
            action_key
            or snapshot_values.get("wf_action_key")
            or snapshot_values.get("workflow_action_key")
            or snapshot_values.get("action_key")
            or False
        )
        task_node_id = (
            task_node_id
            or snapshot_values.get("current_node_id")
            or snapshot_values.get("wf_current_node_id")
            or (
                request_record._workflow_get_actor_primary_node_id(user=self.env.user)
                if request_record and "current_node_id" in request_record._fields
                else False
            )
        )
        action_context = {}
        effective_actor_user = actor_user
        if not self._workflow_is_dryrun_mode() and request_record:
            action_context = request_record._workflow_build_action_execution_context(
                actor_user=actor_user,
                task_node_id=task_node_id,
            )
            if action_context:
                target_record = target_record.with_context(action_context)
                request_record = request_record.with_context(action_context)
                effective_actor_user = request_record._workflow_resolve_effective_actor_user(
                    user=actor_user,
                    task_node_id=task_node_id,
                )

        field_rule_service = self.env["workflow.engine.field.rule.service"]
        payload = field_rule_service.evaluate_runtime_field_state_map(
            target_record=target_record,
            request_record=request_record or target_record,
            task_node_id=task_node_id,
            action_key=action_key,
            view_id=view_id,
            user=effective_actor_user,
            snapshot_values=snapshot_values,
        )
        if not self._workflow_is_dryrun_mode():
            target_record._workflow_force_payload_readonly_for_non_actor(
                payload,
                target_record=target_record,
                request_record=request_record or target_record,
            )
        return payload

    def workflow_get_visible_buttons_snapshot(
        self,
        snapshot_values=False,
        task_node_id=False,
        **kwargs,
    ):
        """
        RPC: Re-evaluate visible action buttons using live (unsaved) snapshot_values.

        Called by the frontend on every onChange cycle so button visibility reacts to
        unsaved field changes without requiring a save.  All five business-logic cases
        are supported via the standard invisible_domain expression engine:

          1. Live form field value  — [('x_section', '=', 'hotel')]
          2. Child/base model field — [('x_amount', '>', 200)]
          3. User group             — actor_has_group('some.xml.id')
          4. Manager relationship   — is_manager_of_requester
          5. Amount / numeric threshold — [('x_amount', '>', 200)] via snapshot

        Returns a list of button dicts in the same shape as _compute_visible_buttons.
        """
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        if self._workflow_is_dryrun_mode() and request_record._name != "workflow.base.approval.request":
            request_record = self._workflow_build_dryrun_request_virtual_record(
                snapshot_values=snapshot_values,
            )
        if not request_record or (request_record.id and not request_record.exists()):
            return []

        if request_record._is_terminal_workflow_state(request_record.state):
            return []

        actor_user = self._workflow_get_dryrun_actor_user() if self._workflow_is_dryrun_mode() else self.env.user
        actor_node_id = task_node_id or request_record._workflow_get_actor_primary_node_id(
            user=actor_user
        )
        action_context = {}
        effective_actor_user = actor_user
        if not self._workflow_is_dryrun_mode():
            action_context = request_record._workflow_build_action_execution_context(
                actor_user=actor_user,
                task_node_id=actor_node_id,
            )
            if action_context:
                request_record = request_record.with_context(action_context)
                effective_actor_user = request_record._workflow_resolve_effective_actor_user(
                    user=actor_user,
                    task_node_id=actor_node_id,
                )

        # Normal approval buttons are for the current actionable actor only.
        # Workflow Admins still have admin tools such as Force Transition; they
        # must not inherit stale task-owner buttons after their activity is done.
        if not request_record._workflow_can_execute_actor_node(
            actor_node_id,
            user=actor_user,
        ):
            return []
        version = getattr(request_record, "version_id", False)
        if not version:
            return []

        user_actions = version._get_user_action_by_node_id(actor_node_id)
        if not user_actions:
            return []
        user_actions = self.env["workflow.engine.permission.service"].filter_authorized_actions(
            request_record,
            user_actions,
            user=actor_user,
        )
        if not user_actions:
            return []

        # Prefer child-model record so invisible_domain can reference child-model
        # fields (e.g. x_it_session_id, x_amount, x_section).
        visibility_target = request_record
        if hasattr(request_record, "_get_transition_delegate_record"):
            try:
                delegate = request_record._get_transition_delegate_record()
                if delegate and delegate.exists():
                    visibility_target = delegate
            except Exception:
                pass
        if action_context:
            visibility_target = visibility_target.with_context(action_context)

        snapshot = snapshot_values if isinstance(snapshot_values, dict) else {}

        match_actions = request_record.get_match_user_actions(
            user_actions,
            target_record=visibility_target,
            task_node_id=actor_node_id,
            snapshot_values=snapshot,
            user=effective_actor_user,
        )

        meta_task = version.meta_task_ids.filtered(lambda m: m.node_id == actor_node_id)[:1]
        transition_block_reason = ""
        try:
            transition_block_reason = request_record._get_transition_access_block_reason()
        except Exception:
            pass

        permission_block_reason = ""
        if not request_record._workflow_can_execute_actor_node(actor_node_id, user=actor_user):
            permission_block_reason = _("You are not an active approver for this stage.")

        buttons = []
        for action in match_actions:
            label = request_record._workflow_get_action_label(action)
            if not label:
                continue
            required_payload = request_record._workflow_button_required_field_payload(
                action,
                meta_task,
                target_record=visibility_target,
                task_node_id=actor_node_id,
                snapshot_values=snapshot,
                user=effective_actor_user,
            )
            disabled_reason = transition_block_reason or permission_block_reason
            buttons.append({
                "label": label,
                "css_class": action.attr_class or "",
                "icon_class": action.icon_class or "",
                "action_button_label": action.action_button_label or "",
                "action_key": action.name or action.attr_label or "",
                "required_fields": required_payload["required_fields"],
                "meta_action_id": action.id,
                "meta_node_id": action.node_id,
                "source_node_id": actor_node_id or action.source_id,
                "target_node_id": action.target_id,
                "all_require_fields": required_payload["all_require_fields"],
                "has_conditional_required_fields": required_payload["has_conditional_required_fields"],
                "conditional_required_fields": required_payload["conditional_required_fields"],
                "disabled": bool(disabled_reason),
                "disabled_reason": disabled_reason or "",
            })
        return buttons

    def _workflow_get_actor_ui_snapshot_payload(self, request_record=False, visible_buttons=False):
        self.ensure_one()
        request_record = request_record or self._workflow_resolve_request_record()
        request_record = request_record or self
        actor_user = self._workflow_get_dryrun_actor_user() if self._workflow_is_dryrun_mode() else self.env.user
        buttons = visible_buttons if isinstance(visible_buttons, list) else []
        can_delegate = False
        has_permission = False
        if request_record and (not request_record.id or request_record.exists()):
            if not request_record._is_terminal_workflow_state(getattr(request_record, "state", False)):
                has_permission = bool(request_record.check_if_user_has_permission(request_record))
            can_delegate = bool(request_record.check_if_user_can_delegate(request_record, user=actor_user))
        return {
            "visible_buttons": buttons,
            "is_user_has_permission": has_permission,
            "is_user_can_delegate": can_delegate,
        }

    def workflow_get_actor_ui_snapshot(
        self,
        snapshot_values=False,
        task_node_id=False,
        **kwargs,
    ):
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        if self._workflow_is_dryrun_mode() and request_record._name != "workflow.base.approval.request":
            request_record = self._workflow_build_dryrun_request_virtual_record(
                snapshot_values=snapshot_values,
            )
        if not request_record or (request_record.id and not request_record.exists()):
            return self._workflow_get_actor_ui_snapshot_payload(visible_buttons=[])
        buttons = self.workflow_get_visible_buttons_snapshot(
            snapshot_values=snapshot_values,
            task_node_id=task_node_id,
            **kwargs,
        )
        return self._workflow_get_actor_ui_snapshot_payload(
            request_record=request_record,
            visible_buttons=buttons,
        )

    @api.model
    def workflow_get_actor_ui_snapshot_virtual(
        self,
        snapshot_values=False,
        task_node_id=False,
        **kwargs,
    ):
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        virtual_vals = self._workflow_virtual_vals_from_snapshot(snapshot_values)
        target_record = self.new(virtual_vals)
        request_record = target_record._workflow_resolve_request_record()
        if self._workflow_is_dryrun_mode() and request_record._name != "workflow.base.approval.request":
            request_record = self._workflow_build_dryrun_request_virtual_record(
                snapshot_values=snapshot_values,
            )
        buttons = target_record.workflow_get_visible_buttons_snapshot_virtual(
            snapshot_values=snapshot_values,
            task_node_id=task_node_id,
            **kwargs,
        )
        return target_record._workflow_get_actor_ui_snapshot_payload(
            request_record=request_record,
            visible_buttons=buttons,
        )

    @api.model
    def workflow_get_visible_buttons_snapshot_virtual(
        self,
        snapshot_values=False,
        task_node_id=False,
        **kwargs,
    ):
        """Return action buttons for a new unsaved workflow form."""
        snapshot_values = snapshot_values if isinstance(snapshot_values, dict) else {}
        target_record = self.new(self._workflow_virtual_vals_from_snapshot(snapshot_values))
        return target_record.workflow_get_visible_buttons_snapshot(
            snapshot_values=snapshot_values,
            task_node_id=task_node_id,
            **kwargs,
        )

    @api.model
    def workflow_run_dryrun_virtual(self, wizard_id, snapshot_values, view_id=False):
        wizard = self.env["workflow.dryrun.wizard"].sudo().browse(wizard_id).exists()
        if not wizard:
            raise UserError(_("Dry-run session not found. Please reopen the wizard."))
        if wizard.category_id.res_model_name and wizard.category_id.res_model_name != self._name:
            raise UserError(
                _("Dry-run session model mismatch: expected %s, got %s.")
                % (wizard.category_id.res_model_name, self._name)
            )
        return wizard.action_run_dryrun_from_snapshot(
            snapshot_values if isinstance(snapshot_values, dict) else {}
        )

    def _workflow_is_policy_bypass_user(self):
        user = self.env.user
        return bool(
            self.env.su
            or user.has_group("base.group_system")
            or user.has_group("workflow_engine.group_workflow_approval_admin")
        )

    def _workflow_allow_runtime_tracking_write(self):
        return bool(
            self._workflow_is_policy_bypass_user()
            or self.env.context.get("workflow_allow_runtime_tracking_write")
        )

    def _workflow_strip_runtime_tracking_fields(self, vals):
        """
        Runtime tracking fields are engine-owned and should not be persisted from
        ordinary form writes. This protects duplicate/edit flows where the client
        may resend stale technical values such as active_branch_node_ids.
        """
        if not vals or self._workflow_allow_runtime_tracking_write():
            return vals
        stripped = {
            key: value for key, value in vals.items()
            if key not in self._WF_RUNTIME_TRACKING_FIELDS
        }
        if len(stripped) != len(vals):
            dropped = sorted(set(vals) - set(stripped))
            _logger.debug(
                "Ignoring workflow runtime tracking fields on user write for %s: %s",
                self._name,
                ", ".join(dropped),
            )
        return stripped

    def _workflow_field_empty_after_write(self, field_name, vals):
        self.ensure_one()
        if field_name not in self._fields:
            return True
        field = self._fields[field_name]
        value = vals.get(field_name, self[field_name])

        if field.type in ("one2many", "many2many"):
            if field_name in vals:
                commands = value or []
                if not commands:
                    return True
                if isinstance(commands, list):
                    clear_only = True
                    for command in commands:
                        if not isinstance(command, (list, tuple)) or not command:
                            clear_only = False
                            break
                        command_type = command[0]
                        if command_type == 6:
                            return not bool(command[2] if len(command) > 2 else [])
                        if command_type == 5:
                            continue
                        if command_type in (0, 1, 4):
                            clear_only = False
                            break
                        clear_only = False
                    if clear_only:
                        return True
                return not bool(commands)
            return not bool(value)

        if field.type == "many2one":
            if isinstance(value, dict):
                value = value.get("id")
            if isinstance(value, (list, tuple)) and value:
                value = value[0]
            return not bool(value)

        if field.type == "html":
            if value in (False, None):
                return True
            plain_text = re.sub(r"<[^>]+>", "", str(value or "")).strip()
            return not bool(plain_text)

        return value in (False, None, "", [])

    def _workflow_enforce_runtime_field_policy(self, vals):
        """
        Zero-trust server enforcement for wf_form rules.
        Readonly, required, and invisible are enforced server-side.
        """
        if not vals or self._workflow_is_policy_bypass_user():
            return
        if self.env.context.get("workflow_skip_field_policy"):
            return
        field_rule_service = self.env["workflow.engine.field.rule.service"]
        snapshot_values = vals if isinstance(vals, dict) else None

        action_key = (
            self.env.context.get("workflow_action_key")
            or self.env.context.get("wf_action_key")
            or self.env.context.get("action_key")
            or False
        )
        task_node_id = (
            self.env.context.get("workflow_task_node_id")
            or self.env.context.get("task_node_id")
            or False
        )
        meta_action_id = self.env.context.get("meta_action_id") or False
        params = self.env.context.get("params") or {}
        view_id = (
            self.env.context.get("view_id")
            or params.get("view_id")
            or params.get("form_view_id")
            or False
        )

        for record in self:
            payload = record.workflow_get_runtime_field_state_map(
                action_key=action_key,
                task_node_id=task_node_id,
                meta_action_id=meta_action_id,
                view_id=view_id,
                snapshot_values=snapshot_values,
            )
            field_state_map = payload.get("field_state_map") or {}
            readonly_written = [
                field_name
                for field_name, state in field_state_map.items()
                if state.get("readonly") and field_name in vals
            ]
            if readonly_written:
                labels = [
                    record._fields[field_name].string
                    if field_name in record._fields
                    else field_name
                    for field_name in readonly_written
                ]
                raise ValidationError(
                    _("These fields are readonly in the current workflow context: %s")
                    % ", ".join(labels)
                )

            invisible_written = [
                field_name
                for field_name, state in field_state_map.items()
                if state.get("invisible") and field_name in vals
            ]
            if invisible_written:
                labels = [
                    record._fields[field_name].string
                    if field_name in record._fields
                    else field_name
                    for field_name in invisible_written
                ]
                raise ValidationError(
                    _("These fields are hidden in the current workflow context and cannot be updated: %s")
                    % ", ".join(labels)
                )

            request_record = record._workflow_resolve_request_record()
            required_fields = field_rule_service.resolve_effective_required_fields_for_view(
                target_record=record,
                required_fields=payload.get("required_fields") or [],
                request_record=request_record,
                task_node_id=task_node_id or request_record.current_node_id,
                action_key=action_key,
                view_id=view_id,
                user=self.env.user,
                snapshot_values=snapshot_values,
            )
            missing_required = [
                field_name
                for field_name in required_fields
                if self._workflow_field_empty_after_write(field_name, vals)
            ]
            if missing_required:
                labels = [
                    record._fields[field_name].string
                    if field_name in record._fields
                    else field_name
                    for field_name in missing_required
                ]
                raise ValidationError(
                    _("Missing required fields for this workflow step: %s")
                    % ", ".join(labels)
                )

    def _workflow_enforce_edit_scope(self, vals):
        """
        Guard business writes so only active-stage actors (or admins) can edit.
        """
        if not vals or self._workflow_is_policy_bypass_user():
            return
        if self.env.context.get("workflow_skip_edit_scope"):
            return

        # Keep chatter/activity technical updates working for non-actors.
        business_keys = [
            key for key in vals.keys()
            if not (key.startswith("message_") or key.startswith("activity_"))
        ]
        if not business_keys:
            return

        permission_service = self.env["workflow.engine.permission.service"]
        for record in self:
            request_record = record._workflow_resolve_request_record()
            if not request_record or request_record._name != "workflow.base.approval.request" or not request_record.id:
                continue
            if not permission_service.can_access_request(request_record, user=self.env.user, scope="edit"):
                raise UserError(
                    _(
                        "You can edit this form only when you are an active approver for the current stage, "
                        "or a Workflow Admin."
                    )
                )

    def _workflow_format_access_error_message(self, error):
        """Convert low-level AccessError into an actionable user message."""
        message = (getattr(error, "name", None) or str(error) or "").strip()
        lines = [line.strip() for line in message.splitlines() if line.strip()]
        access_line = next((line for line in lines if "doesn't have" in line), "")
        model_line = next((line for line in lines if line.startswith("- ")), "")
        detail = " ".join(part for part in (access_line, model_line) if part).strip()
        if detail:
            return _(
                "You do not have permission to update one or more related records. "
                "Please contact Workflow Admin. Details: %s"
            ) % detail
        return _(
            "You do not have permission to update one or more related records. "
            "Please contact Workflow Admin."
        )

    def _workflow_compact_log_value(self, value, *, max_depth=3, max_items=8, max_chars=240):
        if max_depth <= 0:
            return "<%s>" % type(value).__name__
        if isinstance(value, dict):
            items = list(value.items())
            compact = {
                str(key): self._workflow_compact_log_value(
                    item,
                    max_depth=max_depth - 1,
                    max_items=max_items,
                    max_chars=max_chars,
                )
                for key, item in items[:max_items]
            }
            if len(items) > max_items:
                compact["__truncated__"] = "%s more item(s)" % (len(items) - max_items)
            return compact
        if isinstance(value, (list, tuple)):
            compact = [
                self._workflow_compact_log_value(
                    item,
                    max_depth=max_depth - 1,
                    max_items=max_items,
                    max_chars=max_chars,
                )
                for item in value[:max_items]
            ]
            if len(value) > max_items:
                compact.append("... (%s more item(s))" % (len(value) - max_items))
            return compact if isinstance(value, list) else tuple(compact)
        if isinstance(value, bytes):
            return "<bytes %s>" % len(value)
        if isinstance(value, str):
            if len(value) > max_chars:
                return "%s... (%s chars more)" % (value[:max_chars], len(value) - max_chars)
            return value
        if hasattr(value, "_name") and hasattr(value, "ids"):
            ids = list(value.ids[:max_items])
            if len(value.ids) > max_items:
                ids.append("...")
            return "%s%s" % (value._name, ids)
        try:
            text = repr(value)
        except Exception:
            return "<%s>" % type(value).__name__
        if len(text) > max_chars:
            return "%s... (%s chars more)" % (text[:max_chars], len(text) - max_chars)
        return text

    def _workflow_resolve_base_request_for_log(self, record):
        if not record:
            return self.env["workflow.base.approval.request"]
        record = record.sudo()
        if record._name == "workflow.base.approval.request":
            return record
        for field_name in ("x_approval_base_id", "request_id"):
            linked = getattr(record, field_name, False)
            if linked and getattr(linked, "_name", "") == "workflow.base.approval.request":
                return linked.sudo()
        resolver = getattr(record, "_resolve_base_request_record", False)
        if resolver:
            try:
                base_request = resolver()
            except Exception:
                base_request = False
            if base_request and getattr(base_request, "_name", "") == "workflow.base.approval.request":
                return base_request.sudo()
        return self.env["workflow.base.approval.request"]

    def _workflow_build_access_error_log_payload(self, vals, error):
        actor_user = self.env.user
        context_keys = (
            "active_model",
            "active_id",
            "active_ids",
            "default_res_model",
            "default_res_id",
            "meta_action_id",
            "view_id",
            "workflow_action_key",
            "workflow_task_node_id",
            "workflow_challenge_id",
            "workflow_idempotency_key",
            "workflow_skip_edit_scope",
            "workflow_skip_field_policy",
            "workflow_allow_runtime_tracking_write",
            "wf_skip_block_sync",
        )
        context_snapshot = {
            key: self._workflow_compact_log_value(self.env.context.get(key))
            for key in context_keys
            if key in self.env.context
        }
        records = []
        for record in self[:5].sudo():
            snapshot = {
                "record_id": record.id,
                "display_name": self._workflow_compact_log_value(record.display_name),
            }
            if "create_uid" in record._fields and record.create_uid:
                snapshot["record_create_uid"] = record.create_uid.id
                snapshot["record_create_user"] = record.create_uid.login or record.create_uid.name
            if "request_owner_id" in record._fields and record.request_owner_id:
                snapshot["request_owner_id"] = record.request_owner_id.id
                snapshot["request_owner_user"] = (
                    record.request_owner_id.login or record.request_owner_id.name
                )

            base_request = self._workflow_resolve_base_request_for_log(record)
            if base_request:
                current_iteration = base_request.current_iteration_no or 1
                actor_rows = base_request.approver_ids.sudo().filtered(
                    lambda row: row.user_id.id == actor_user.id
                    and (row.iteration_no or 1) == current_iteration
                    and row.current_meta_node_id == (base_request.current_node_id or False)
                )
                snapshot.update({
                    "base_request_id": base_request.id,
                    "base_request_create_uid": base_request.create_uid.id if base_request.create_uid else False,
                    "base_request_create_user": (
                        base_request.create_uid.login or base_request.create_uid.name
                    ) if base_request.create_uid else False,
                    "base_request_owner_id": (
                        base_request.request_owner_id.id
                        if "request_owner_id" in base_request._fields and base_request.request_owner_id
                        else False
                    ),
                    "base_request_owner_user": (
                        base_request.request_owner_id.login or base_request.request_owner_id.name
                    ) if "request_owner_id" in base_request._fields and base_request.request_owner_id else False,
                    "current_node_id": base_request.current_node_id,
                    "current_activity_name": base_request.current_activity_name,
                    "request_status": base_request.request_status,
                    "current_iteration_no": current_iteration,
                    "actor_rows": [
                        {
                            "approver_id": row.id,
                            "status": row.status,
                            "required": row.required,
                            "decision": row.user_decision,
                            "current_meta_id": row.current_meta_id.id,
                            "current_meta_name": row.current_meta_id.name,
                            "iteration_no": row.iteration_no,
                        }
                        for row in actor_rows[:5]
                    ],
                })
            records.append(snapshot)

        payload = {
            "model": self._name,
            "record_ids": list(self.ids[:20]),
            "record_count": len(self),
            "actor_uid": actor_user.id,
            "actor_login": actor_user.login,
            "actor_name": actor_user.name,
            "write_vals": self._workflow_compact_log_value(vals),
            "context": context_snapshot,
            "records": records,
            "original_error": {
                "type": type(error).__name__,
                "message": getattr(error, "name", None) or str(error),
            },
        }
        if len(self) > 5:
            payload["records_truncated"] = "%s more record(s)" % (len(self) - 5)
        return payload

    def write(self, vals):
        vals = self._workflow_strip_runtime_tracking_fields(vals)
        if not vals:
            return True
        self._workflow_enforce_edit_scope(vals)
        self._workflow_enforce_runtime_field_policy(vals)
        try:
            result = super().write(vals)
        except AccessError as error:
            try:
                payload = self._workflow_build_access_error_log_payload(vals, error)
                _logger.exception(
                    "Workflow access error diagnostic:\n%s",
                    pformat(payload, width=120, sort_dicts=False),
                )
            except Exception:
                _logger.exception(
                    "Workflow access error diagnostic logging failed for %s on records %s",
                    self._name,
                    list(self.ids[:20]),
                )
            raise UserError(self._workflow_format_access_error_message(error))
        self.env.registry.clear_cache()
        return result

    def _workflow_match_domain_expression(
        self,
        domain_expression,
        default=True,
        target_record=False,
        task_node_id=False,
        action_key=False,
        snapshot_values=None,
        user=False,
        raise_on_error=False,
    ):
        self.ensure_one()
        request_record = self._workflow_resolve_request_record()
        target_record = target_record or self
        return self.env["workflow.engine.field.rule.service"].match_domain_expression(
            request_record=request_record,
            domain_expression=domain_expression,
            target_record=target_record,
            task_node_id=task_node_id or getattr(request_record, "current_node_id", False) or "",
            action_key=action_key,
            user=user or self._workflow_resolve_effective_actor_user(task_node_id=task_node_id),
            snapshot_values=snapshot_values or {},
            raise_on_error=raise_on_error,
            default=default,
        )

    def check_domain(
        self,
        domain_str,
        default=True,
        target_record=False,
        task_node_id=False,
        action_key=False,
        snapshot_values=None,
        user=False,
        raise_on_error=False,
    ):
        """
        Evaluate a workflow domain against request/runtime context.
        """
        self.ensure_one()
        if action_key in (False, None, ""):
            action_key = (
                self.env.context.get("workflow_action_key")
                or self.env.context.get("wf_action_key")
                or self.env.context.get("action_key")
                or ""
            )
        return self._workflow_match_domain_expression(
            domain_expression=domain_str,
            default=default,
            target_record=target_record or self,
            task_node_id=task_node_id,
            action_key=action_key,
            snapshot_values=snapshot_values,
            user=user or self._workflow_resolve_effective_actor_user(task_node_id=task_node_id),
            raise_on_error=raise_on_error,
        )

    def _workflow_conditional_event_warning(self, node, message, *, condition_domain=False, error=False):
        self.ensure_one()
        node_id = node.attrib.get("id") if node is not None else False
        node_name = (node.attrib.get("name") if node is not None else False) or node_id
        body = message % {
            "node": node_name,
            "domain": condition_domain or "",
            "error": str(error or ""),
        }
        _logger.warning(
            "Workflow conditional event warning: request=%s node=%s domain=%s error=%s message=%s",
            self.id,
            node_id,
            condition_domain or "",
            error or "",
            body,
        )
        self._workflow_safe_message_post(
            body=body,
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )

    def _workflow_conditional_event_targets_from_flows(self, engine, flows):
        selected_nodes = []
        seen = set()
        for seq in flows:
            target = engine.get_element_by_id(seq.get("target"))
            target_id = target.attrib.get("id") if target is not None else False
            if target is None or not target_id or target_id in seen:
                continue
            seen.add(target_id)
            selected_nodes.append(target)
        return selected_nodes

    def _workflow_conditional_event_default_flows(self, node, outgoing):
        default_flow_id = node.attrib.get("default") if node is not None else False
        if not default_flow_id:
            return []
        return [seq for seq in outgoing if seq.get("id") == default_flow_id]

    def _workflow_get_conditional_event_next_elements(self, engine, node, condition_domain=False):
        self.ensure_one()
        outgoing = list(engine.sequence_flows.get(node.attrib.get("id"), []) or [])
        if not outgoing:
            return []

        default_flows = self._workflow_conditional_event_default_flows(node, outgoing)
        condition_domain = (condition_domain or "").strip()
        if not condition_domain:
            if default_flows:
                return self._workflow_conditional_event_targets_from_flows(engine, default_flows)
            self._workflow_conditional_event_warning(
                node,
                _(
                    "Conditional Event '%(node)s' has no condition domain and no BPMN default outgoing path. "
                    "Workflow execution stopped at this node."
                ),
            )
            return []

        try:
            condition_matched = self.check_domain(
                condition_domain,
                default=False,
                raise_on_error=True,
            )
        except Exception as error:
            if default_flows:
                self._workflow_conditional_event_warning(
                    node,
                    _(
                        "Conditional Event '%(node)s' has an invalid condition domain. "
                        "The workflow used its BPMN default outgoing path. Domain: %(domain)s. Error: %(error)s"
                    ),
                    condition_domain=condition_domain,
                    error=error,
                )
                return self._workflow_conditional_event_targets_from_flows(engine, default_flows)
            self._workflow_conditional_event_warning(
                node,
                _(
                    "Conditional Event '%(node)s' has an invalid condition domain and no BPMN default outgoing path. "
                    "Workflow execution stopped at this node. Domain: %(domain)s. Error: %(error)s"
                ),
                condition_domain=condition_domain,
                error=error,
            )
            return []

        if condition_matched:
            default_flow_id = node.attrib.get("default")
            selected_flows = [seq for seq in outgoing if seq.get("id") != default_flow_id] or outgoing
        else:
            selected_flows = default_flows
            if not selected_flows:
                self._workflow_conditional_event_warning(
                    node,
                    _(
                        "Conditional Event '%(node)s' evaluated to false but has no BPMN default outgoing path. "
                        "Workflow execution stopped at this node."
                    ),
                    condition_domain=condition_domain,
                )
                return []

        return self._workflow_conditional_event_targets_from_flows(engine, selected_flows)

    def _workflow_should_open_confirmation_dialog(self, meta_action, show_dialog=True):
        """
        Resolve whether this action should open the optional confirmation prompt.
        """
        self.ensure_one()
        if not show_dialog or not meta_action:
            return False
        if self.env.context.get("workflow_skip_config_confirm"):
            return False
        if not meta_action.show_confirm_dialog:
            return False
        return True

    def _workflow_action_execution_guard_matches(self, meta_action):
        self.ensure_one()
        guard_domain = (meta_action.domain or "").strip() if meta_action else ""
        if not guard_domain or guard_domain in ("[]", "[ ]"):
            return True
        return self.check_domain(guard_domain, default=False)

    def _workflow_find_meta_action_for_transition(self, target_node_id, source_node_id=False):
        self.ensure_one()
        MetaAction = self.env["workflow.category.version.meta.task.action"].sudo()
        if not self.version_id or not target_node_id:
            return MetaAction

        base_domain = [
            ("version_id", "=", self.version_id.id),
            ("target_id", "=", target_node_id),
        ]
        if source_node_id:
            exact = MetaAction.search(
                base_domain + [("source_id", "=", source_node_id)],
                order="id desc",
                limit=1,
            )
            if exact:
                return exact

        return MetaAction.search(base_domain, order="id desc", limit=1)

    def _workflow_validate_action_execution_guard(self, meta_action):
        self.ensure_one()
        if not self._workflow_action_execution_guard_matches(meta_action):
            custom_message = html2plaintext(meta_action.validation_message or "").strip()
            raise UserError(
                custom_message
                or _("Action blocked because the Runtime Domain Guard did not match.")
            )
        return True

    def _workflow_action_execution_guard_failure_action(self, meta_action, show_dialog=True):
        """Return an informational modal for an opt-in guard failure, or raise.

        This helper never authorizes execution. Non-UI callers and the final
        engine path continue to use the hard server-side validation above.
        """
        self.ensure_one()
        if self._workflow_action_execution_guard_matches(meta_action):
            return False
        if not (show_dialog and meta_action.show_validation_dialog):
            self._workflow_validate_action_execution_guard(meta_action)

        view = self.env.ref("workflow_engine.view_workflow_validation_dialog_form")
        message = meta_action.validation_message or Markup("<p>%s</p>") % escape(
            _("Action blocked because the Runtime Domain Guard did not match.")
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "workflow.confirm.wizard",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "target": "new",
            "name": _("Validation Message"),
            "context": {
                "default_confirm_message": message,
                "dialog_size": "medium",
            },
        }

    def _workflow_action_requirement_domain_matches(self, domain):
        self.ensure_one()
        domain = (domain or "").strip()
        if not domain or domain in ("[]", "[ ]"):
            return True
        return self.check_domain(domain, default=False)

    def _workflow_action_shows_reason(self, meta_action):
        return bool(meta_action and meta_action.require_reason)

    def _workflow_action_requires_reason(self, meta_action):
        self.ensure_one()
        if not self._workflow_action_shows_reason(meta_action):
            return False
        return self._workflow_action_requirement_domain_matches(meta_action.require_reason_domain)

    def _workflow_action_shows_comment(self, meta_action):
        return bool(meta_action and meta_action.comment_required)

    def _workflow_action_requires_comment(self, meta_action):
        self.ensure_one()
        if not self._workflow_action_shows_comment(meta_action):
            return False
        comment_domain = getattr(meta_action, "comment_required_domain", False)
        if comment_domain in (None, False, "", "False", "false"):
            return False
        return self._workflow_action_requirement_domain_matches(comment_domain)

    def _workflow_action_shows_attachment(self, meta_action):
        return bool(meta_action and meta_action.require_attachment)

    def _workflow_action_requires_attachment(self, meta_action):
        self.ensure_one()
        if not self._workflow_action_shows_attachment(meta_action):
            return False
        return self._workflow_action_requirement_domain_matches(
            getattr(meta_action, "require_attachment_domain", False)
        )

    def _workflow_requires_action_input_dialog(self, meta_action, show_dialog=True):
        """Return True when the action wizard must collect audit/input data."""
        self.ensure_one()
        if not show_dialog or not meta_action:
            return False
        return bool(
            self._workflow_action_shows_reason(meta_action)
            or self._workflow_action_shows_comment(meta_action)
            or self._workflow_action_shows_attachment(meta_action)
        )

    def _workflow_should_open_action_wizard(self, meta_action, show_dialog=True):
        """Return True when any workflow action wizard is required."""
        self.ensure_one()
        if self._workflow_requires_action_input_dialog(meta_action, show_dialog=show_dialog):
            return True
        if self._workflow_should_open_confirmation_dialog(meta_action, show_dialog=show_dialog):
            return True
        return False

    @api.model
    def get_all_by_parent(self, id=None, res_model_name= None):
        """
        Return all approval requests, optionally filtered by parent_id.
        Each record is converted to a dict via read(), no manual mapping.
        """
        if not id:
            return []

        BaseRequest = self.env["workflow.base.approval.request"].sudo().with_context(active_test=False)
        base_record = BaseRequest.browse(id).exists()

        if not base_record and res_model_name and res_model_name in self.env:
            delegate_model = self.env[res_model_name].sudo().with_context(active_test=False)
            delegate_record = delegate_model.browse(id).exists()
            if not delegate_record and "x_approval_base_id" in delegate_model._fields:
                delegate_record = delegate_model.search(
                    [("x_approval_base_id", "=", id)],
                    limit=1,
                )
            if delegate_record and "x_approval_base_id" in delegate_record._fields:
                base_record = delegate_record.x_approval_base_id.sudo().with_context(active_test=False).exists()

        if not base_record:
            return []

        sub_records = BaseRequest.search([
            ("parent_id", "=", base_record.id)
        ])

        return [r.read()[0] for r in sub_records]
    
    def close_approver(
        self,
        previous_meta_task,
        iteration_no=None,
        include_current_user=False,
        decision_if_blank=False,
        comment_if_blank=False,
    ):
        if not previous_meta_task:
            return
        open_statuses = {'new', 'pending', 'waiting'}
        previous_node_id = getattr(previous_meta_task, "node_id", False)
        previous_approver_ids = self.approver_ids.filtered(
            lambda a: a.status in open_statuses
            and (
                a.current_meta_id.id == previous_meta_task.id
                or (previous_node_id and a.current_meta_node_id == previous_node_id)
            )
            and (iteration_no is None or (a.iteration_no or 1) == iteration_no)
        )
        if not include_current_user:
            previous_approver_ids = previous_approver_ids.filtered(
                lambda a: a.user_id.id != self.env.user.id
            )
        if not previous_approver_ids:
            return
        if decision_if_blank:
            Approver = self.env["workflow.approval.approver"]
            is_routed_audit = Approver._is_routed_audit_decision_value(decision_if_blank)
            rows_with_decision = previous_approver_ids.filtered(lambda a: Approver._has_decision_text(a.user_decision))
            rows_without_decision = previous_approver_ids - rows_with_decision
            if rows_without_decision:
                routed_values = {
                    'status': 'closed',
                    'user_decision': decision_if_blank,
                    'is_routed_audit': is_routed_audit,
                }
                if comment_if_blank:
                    routed_values['comment'] = comment_if_blank
                rows_without_decision.write(routed_values)
            if rows_with_decision:
                rows_with_decision.write({'status': 'closed'})
            return
        previous_approver_ids.write({'status': 'closed'})
    
    def ensure_can_approve(self, meta_action):
        if any(approval.approver_sequence and approval.user_status == 'waiting' for approval in self):
            raise ValidationError(_('You cannot approve before the previous approver.'))

        request_record = self._workflow_resolve_request_record()
        if not request_record._workflow_can_execute_approval_actor_node(
            meta_action.source_id,
            user=self.env.user,
        ):
            raise ValidationError(_('This action is no longer assigned to you.'))
        
        # check if still allow workflow admin edit?
        # already handle it in backend domain
        # if meta_action.invisible_domain:
        #     if not self.check_domain(
        #         meta_action.invisible_domain,
        #         default=False,
        #         target_record=self,
        #         task_node_id=meta_action.source_id,
        #         action_key=meta_action.name or meta_action.attr_label or "",
        #     ):
        #         raise ValidationError(_('This request can no longer be updatable.'))
        
    def cancel_activities(self):
        mail_activity_type = self.env.ref('workflow_engine.mail_activity_data_workflow_approval')
        if not mail_activity_type:
            return

        def _persisted_id(record):
            rec_id = getattr(record, "id", False)
            return rec_id if isinstance(rec_id, int) and rec_id > 0 else False

        targets = set()
        for rec in self:
            rec_id = _persisted_id(rec)
            if rec_id:
                targets.add((rec._name, rec_id))

            base_request = rec
            if rec._name != 'workflow.base.approval.request':
                base_request = getattr(rec, 'x_approval_base_id', False)
            if not base_request:
                continue

            base_request_id = _persisted_id(base_request)
            if not base_request_id:
                continue

            targets.add(('workflow.base.approval.request', base_request_id))
            child_model_name = getattr(base_request, 'res_model_name', False)
            if not child_model_name or child_model_name == 'workflow.base.approval.request':
                continue

            child_model = self.env[child_model_name]
            link_field = child_model._fields.get('x_approval_base_id')
            if not link_field or not getattr(link_field, 'store', False):
                continue

            child_records = child_model.sudo().search([
                ('x_approval_base_id', '=', base_request_id),
            ])
            for child in child_records:
                targets.add((child._name, child.id))

        Activity = self.env['mail.activity'].sudo()
        for model_name, res_id in targets:
            if not isinstance(res_id, int) or res_id <= 0:
                continue
            Activity.search([
                ('activity_type_id', '=', mail_activity_type.id),
                ('res_model', '=', model_name),
                ('res_id', '=', res_id),
                ('date_done', '=', False),
            ]).unlink()

    def is_login_an_approver_in_current_activity(self, request, user=False):
        login = user or self.env.user
        open_nodes = request._workflow_get_open_approval_actor_node_ids(user=login)
        if not open_nodes:
            return False
        # `_workflow_get_open_actor_node_ids` already resolves active open rows
        # against runtime-active nodes. Keep current node included even when
        # parallel branch nodes are present.
        current_node_id = getattr(request, "current_node_id", False)
        branch_nodes = set((getattr(request, "active_branch_node_ids", None) or []))
        active_nodes = set(branch_nodes)
        if current_node_id:
            active_nodes.add(current_node_id)
        if not active_nodes:
            return bool(open_nodes)
        return bool(set(open_nodes) & active_nodes)

    def _workflow_can_execute_approval_actor_node(self, node_id=False, user=False):
        """Return True when user can execute an approval action on the node."""
        self.ensure_one()
        request = self._workflow_resolve_request_record()
        user = user or self.env.user
        if not request or request._is_terminal_workflow_state(request.state):
            return False
        if "active" in request._fields and not request.active:
            return False

        is_unsaved_bootstrap = not request.id and getattr(request, "state", False) in ("draft", "new")
        open_nodes = request._workflow_get_open_approval_actor_node_ids(user=user)
        if node_id:
            if node_id in open_nodes:
                return True
            no_rows_yet = not bool(getattr(request, "approver_ids", False))
            owns_request = user in (request.request_owner_id, request.create_uid, request.owner_user_id)
            if (
                no_rows_yet
                and (owns_request or is_unsaved_bootstrap)
                and node_id == request._workflow_get_initial_actor_node_id()
            ):
                return True
            return (
                request._workflow_user_is_on_behalf_admin(user=user)
                and node_id in request._workflow_active_actor_node_ids()
            )
        if open_nodes:
            return True
        if request._workflow_user_is_on_behalf_admin(user=user):
            return bool(request._workflow_active_actor_node_ids())

        # Before the first assignment exists, allow the owner/creator to submit
        # the request from the current node. Once approver rows exist, execution
        # is controlled exclusively by the open actor rows above.
        no_rows_yet = not bool(getattr(request, "approver_ids", False))
        owns_request = user in (request.request_owner_id, request.create_uid, request.owner_user_id)
        return bool(no_rows_yet and (owns_request or is_unsaved_bootstrap))

    def _workflow_can_execute_actor_node(self, node_id=False, user=False):
        """Return True for an approval actor or an exact business action actor."""
        self.ensure_one()
        request = self._workflow_resolve_request_record()
        user = user or self.env.user
        if request._workflow_can_execute_approval_actor_node(node_id=node_id, user=user):
            return True
        if not request or request._is_terminal_workflow_state(request.state):
            return False
        if "active" in request._fields and not request.active:
            return False
        rows = self.env["workflow.engine.assignment.service"]._open_business_action_assignments(
            request,
            user=user,
            node_id=node_id,
        )
        return bool(rows)
    
    def check_if_user_has_permission(self, request):
        """
        To check if the login is allowed to see the action buttons or not.
        """
        user = self.env.user
        if not request.id and getattr(request, "state", False) in ("draft", "new"):
            # A virtual draft has no persisted create_uid yet. The current user is
            # still the form creator and must be allowed to submit directly even
            # after selecting another request_owner_id.
            if not request.create_uid and not request.owner_user_id:
                return True
            if user in (request.create_uid, request.owner_user_id):
                return True
            bootstrap_owner = request.request_owner_id or request.create_uid or request.owner_user_id
            return not bootstrap_owner or bootstrap_owner == user
        if self.is_login_an_approver_in_current_activity(request):
            return True
        if request._workflow_user_is_on_behalf_admin(user=self.env.user):
            return bool(request._workflow_active_actor_node_ids())
        permission_service = self.env["workflow.engine.permission.service"]
        if permission_service.can_access_request(request.sudo(), user=user, scope="edit"):
            return True
        if request.approver_ids:
            return False
        return bool(user in (request.request_owner_id, request.create_uid, request.owner_user_id))

    def _workflow_user_has_delegate_override(self, user=False):
        self.ensure_one()
        user = user or self.env.user
        return bool(
            user
            and (
                user.has_group("workflow_engine.group_workflow_technical_admin")
                or user.has_group("workflow_engine.group_workflow_technical_support")
            )
        )

    def check_if_user_can_delegate(self, request, user=False):
        """Return True when user may delegate the current workflow activity."""
        user = user or self.env.user
        if not request or not user:
            return False

        if getattr(request, "state", False) == "done":
            return request._workflow_user_is_on_behalf_admin(user=user)

        if getattr(request, "state", False) in (
            "draft",
            "new",
            "completed",
            "auto_approved",
            "cancelled",
            "auto_cancelled",
            "refused",
        ):
            return False

        if request._workflow_user_has_delegate_override(user=user):
            return True

        if request.is_login_an_approver_in_current_activity(request, user=user):
            return True
        return bool(
            self.env["workflow.engine.assignment.service"]._open_business_action_assignments(
                request,
                user=user,
            )
        )
    
    def get_match_user_actions(
        self,
        all_actions,
        target_record=False,
        task_node_id=False,
        snapshot_values=None,
        user=False,
    ):
        """ 
        get match user actions of particular task.

        @return a list of match actions
        """
        self.ensure_one()
        target_record = target_record or self

        # start with actions that has empty domain
        match_actions = all_actions.filtered_domain(['|',('invisible_domain', '=', False),('invisible_domain', '=', '[]')])
        
        # then work on actions that has filled domain
        domain_actions = all_actions.filtered_domain([('invisible_domain', '!=', False), ('invisible_domain', '!=', '[]')])

        for act in domain_actions:
            is_visible = self.check_domain(
                act.invisible_domain,
                default=False,
                target_record=target_record,
                task_node_id=task_node_id or act.source_id,
                action_key=act.name or act.attr_label or "",
                snapshot_values=snapshot_values,
                user=user or self.env.user,
            )
            if is_visible:
                match_actions = match_actions + act

        return match_actions
    
    def get_access_action_url(self):
        self.ensure_one()
        target = self._workflow_resolve_notification_target_record()
        if not target or not getattr(target, "id", False):
            target = self
        return target._notify_get_action_link('view', model=target._name, res_id=target.id)

    def _resolve_meta_task_for_node(self, node_id, node_name=None, prefer_submission=None):
        """
        Resolve a single canonical meta task for a BPMN node in current version.

        This shared helper avoids random legacy picks when duplicate meta rows
        exist for the same node_id.
        """
        self.ensure_one()
        MetaTask = self.env['workflow.category.version.meta.task']
        version = getattr(self, 'version_id', False)
        if not version or not node_id:
            return MetaTask.browse()

        candidates = version.meta_task_ids.filtered(lambda m: m.node_id == node_id)
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
                try:
                    engine = BpmnEngine(version.bpmn_xml)
                    submission_node = engine.get_submission_task()
                    submission_node_id = submission_node.attrib.get('id') if submission_node is not None else False
                except Exception:
                    submission_node_id = False
                if submission_node_id:
                    submission_candidates = candidates.filtered(lambda m: m.node_id == submission_node_id)
                else:
                    submission_candidates = candidates.filtered(
                        lambda m: "submit" in (m.name or "").lower() or "submission" in (m.name or "").lower()
                    )
                if submission_candidates:
                    candidates = submission_candidates

        if prefer_submission in (True, False):
            submission_node_id = False
            try:
                engine = BpmnEngine(version.bpmn_xml)
                submission_node = engine.get_submission_task()
                submission_node_id = submission_node.attrib.get('id') if submission_node is not None else False
            except Exception:
                _logger.debug("Could not resolve submission node while selecting meta task", exc_info=True)

            def _is_submission_task(meta):
                if submission_node_id and meta.node_id == submission_node_id:
                    return True
                label = (meta.name or "").lower()
                return "submit" in label or "submission" in label

            if prefer_submission:
                subset = candidates.filtered(_is_submission_task)
                if subset:
                    candidates = subset
            else:
                subset = candidates.filtered(lambda m: not _is_submission_task(m))
                if subset:
                    candidates = subset

        return candidates.sorted(key=lambda m: m.id, reverse=True)[:1]

    def action_open_base_request(self):
        self.ensure_one()
        return {
            'name': 'Base Request',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'workflow.base.approval.request',
            'res_id': self.id,
            'target': 'current',
        }
