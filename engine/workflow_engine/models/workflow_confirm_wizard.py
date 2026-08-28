from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import base64
import io
import logging

try:
    import qrcode
except ImportError:  # pragma: no cover - dependency should exist, but fail gracefully
    qrcode = None

_logger = logging.getLogger(__name__)

class WorkflowConfirmWizard(models.TransientModel):
    _name = 'workflow.confirm.wizard'
    _description = 'Workflow Confirm / Reject Wizard'

    decision = fields.Selection([
        ('proceed', 'Proceed'),
        ('reject', 'Reject with reason'),
    ], string='Decision', required=True, default='proceed')

    reason = fields.Text(string='Reason')
    comment = fields.Text(string='Comment')
    # optional: the model and record id we act on (filled from context)
    res_model = fields.Char(string='Model', readonly=True)
    res_id = fields.Integer(string='Record ID', readonly=True)
    is_reject_action = fields.Boolean(
        string="Is Reject Action",
        compute="_compute_is_reject_action",
        store=False  # Wizard is transient, no need to store
    )
    confirm_message = fields.Html(store=False, readonly=True,)
    is_have_confirm_message = fields.Boolean(compute="_compute_is_have_confirm_message", store=False, readonly=True,)
    require_2fa = fields.Boolean(compute="_compute_require_2fa", store=False)
    show_reason_flag = fields.Boolean(compute="_compute_reason_flags", store=False)
    require_reason_flag = fields.Boolean(compute="_compute_reason_flags", store=False)
    show_comment_flag = fields.Boolean(compute="_compute_comment_flags", store=False)
    require_comment_flag = fields.Boolean(compute="_compute_comment_flags", store=False)
    show_attachment_flag = fields.Boolean(compute="_compute_require_attachment", store=False)
    challenge_id = fields.Many2one(
        "workflow.approval.action.challenge",
        string="2FA Challenge",
        readonly=True,
    )
    challenge_expires_at = fields.Datetime(related="challenge_id.expires_at", readonly=True)
    challenge_method = fields.Selection(related="challenge_id.method", store=False, readonly=True)
    challenge_state = fields.Selection(related="challenge_id.state", store=False, readonly=True)
    challenge_token = fields.Char(related="challenge_id.token", store=False, readonly=True)
    otp_code = fields.Char(string="OTP Code")
    qr_image = fields.Binary(
        string="QR Image",
        compute="_compute_qr_image",
        help="Rendered QR for mobile scan. Falls back to token display when rendering is not available.",
    )
    require_attachment_flag = fields.Boolean(compute="_compute_require_attachment", store=False)
    required_attachment_count = fields.Integer(compute="_compute_require_attachment", store=False)
    attachment_ids = fields.Many2many(
        'ir.attachment', 
        string='Attachments'
    )
    
    @api.depends_context("action_type")
    def _compute_is_reject_action(self):
        reject_values = ['reject', 'Reject', 'rejected', 'Rejected']
        for rec in self:
            action_type = self.env.context.get('action_type')
            rec.is_reject_action = action_type in reject_values
            
    # @api.depends_context('confirm_message')
    # def _compute_confirm_message(self):
    #     for rec in self:
    #         rec.confirm_message = rec.env.context.get('confirm_message') or False
       
    @api.depends_context('confirm_message')     
    def _compute_is_have_confirm_message(self):
        for rec in self:
            rec.is_have_confirm_message = bool(rec.env.context.get('confirm_message'))

    @api.depends_context("show_reason", "require_reason")
    def _compute_reason_flags(self):
        for rec in self:
            rec.show_reason_flag = bool(rec.env.context.get("show_reason") or rec.env.context.get("require_reason"))
            rec.require_reason_flag = bool(rec.env.context.get("require_reason"))

    @api.depends_context("show_comment", "require_comment")
    def _compute_comment_flags(self):
        for rec in self:
            rec.show_comment_flag = bool(rec.env.context.get("show_comment") or rec.env.context.get("require_comment"))
            rec.require_comment_flag = bool(rec.env.context.get("require_comment"))

    @api.depends_context("show_attachment", "require_attachment", "required_attachment_count")
    def _compute_require_attachment(self):
        for rec in self:
            rec.show_attachment_flag = bool(rec.env.context.get("show_attachment") or rec.env.context.get("require_attachment"))
            rec.require_attachment_flag = bool(rec.env.context.get("require_attachment"))
            rec.required_attachment_count = max(1, int(rec.env.context.get("required_attachment_count") or 1))

    @api.depends_context("meta_action_id", "default_res_model", "default_res_id")
    def _compute_require_2fa(self):
        twofa_service = self.env["workflow.engine.twofactor.service"]
        for rec in self:
            rec.require_2fa = False
            meta_action_id = rec.env.context.get("meta_action_id")
            if not meta_action_id:
                continue
            meta_action = rec.env["workflow.category.version.meta.task.action"].sudo().browse(meta_action_id)
            if not meta_action.exists():
                continue
            res_model = rec.env.context.get("default_res_model")
            res_id = rec.env.context.get("default_res_id")
            if not res_model or not res_id:
                continue
            target = rec.env[res_model].browse(res_id)
            request_record = target
            if target and "x_approval_base_id" in target._fields and target.x_approval_base_id:
                request_record = target.x_approval_base_id
            if request_record:
                rec.require_2fa = twofa_service.action_requires_twofactor(
                    request_record=request_record,
                    meta_action=meta_action,
                    target_record=target,
                )

    def _compute_qr_image(self):
        """Generate a lightweight PNG for QR challenges (server-side to avoid extra JS deps)."""
        for rec in self:
            rec.qr_image = False
            if not (qrcode and rec.challenge_id and rec.challenge_id.method == "qr" and rec.challenge_id.token):
                continue
            try:
                img = qrcode.make(rec.challenge_id.token)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                rec.qr_image = base64.b64encode(buffer.getvalue())
            except Exception as exc:  # pragma: no cover
                _logger.warning("Failed to render QR image: %s", exc)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        meta_action_id = self.env.context.get("meta_action_id")
        res_model = self.env.context.get("default_res_model")
        res_id = self.env.context.get("default_res_id")
        if not meta_action_id or not res_model or not res_id:
            return values

        meta_action = self.env["workflow.category.version.meta.task.action"].sudo().browse(meta_action_id)
        if not meta_action.exists():
            return values

        target = self.env[res_model].browse(res_id)
        request_record = target
        if target and "x_approval_base_id" in target._fields and target.x_approval_base_id:
            request_record = target.x_approval_base_id
        if not request_record:
            return values

        twofa_service = self.env["workflow.engine.twofactor.service"]
        if not twofa_service.action_requires_twofactor(request_record, meta_action):
            return values

        challenge = twofa_service.issue_action_challenge(
            request_record=request_record,
            meta_action=meta_action,
            action_key=meta_action.name or meta_action.attr_label,
            target_record=target,
        )
        if challenge:
            values["challenge_id"] = challenge.id
        return values
            

    def _get_target_record(self):
        """Return the active record (browse) we act on."""
        if not self.res_model or not self.res_id:
            raise UserError(_("Missing target record in wizard context."))
        return self.env[self.res_model].browse(self.res_id)

    def _validate_action_input(self, meta_action, record=False):
        self.ensure_one()
        requires_reason = (
            record._workflow_action_requires_reason(meta_action)
            if record and hasattr(record, "_workflow_action_requires_reason")
            else bool(meta_action.require_reason)
        )
        if requires_reason and not (self.reason or "").strip():
            raise ValidationError(_("This action requires a reason."))
        requires_comment = (
            record._workflow_action_requires_comment(meta_action)
            if record and hasattr(record, "_workflow_action_requires_comment")
            else bool(meta_action.comment_required)
        )
        if requires_comment and not (self.comment or "").strip():
            raise ValidationError(_("This action requires a comment."))
        requires_attachment = (
            record._workflow_action_requires_attachment(meta_action)
            if record and hasattr(record, "_workflow_action_requires_attachment")
            else bool(meta_action.require_attachment)
        )
        if requires_attachment:
            required_count = max(1, int(meta_action.required_attachment_count or 1))
            if len(self.attachment_ids) < required_count:
                raise ValidationError(
                    _("This action requires at least %(count)s attachment(s).") % {
                        "count": required_count,
                    }
                )

    def _persist_action_input(self, record, meta_action, reason=False):
        self.ensure_one()
        reason = ((reason if reason is not False else self.reason) or "").strip()
        comment = (self.comment or "").strip()
        workflow_write_record = record.sudo().with_context(
            workflow_skip_edit_scope=True,
            workflow_skip_field_policy=True,
        )
        if reason:
            action_type = self.env.context.get('action_type')
            model_fields = record._fields
            values = {}
            if action_type in ['reject', 'Reject', 'rejected', 'Rejected'] and 'x_reject_reason' in model_fields:
                values['x_reject_reason'] = reason
            if action_type in ['approve', 'Approve', 'Approved', 'Approved'] and 'x_approve_reason' in model_fields:
                values['x_approve_reason'] = reason
            if values:
                workflow_write_record.write(values)

        comment_value = comment or reason
        if comment_value:
            base_request = False
            if "x_approval_base_id" in record._fields and record.x_approval_base_id:
                base_request = record.x_approval_base_id
            elif record._name == "workflow.base.approval.request":
                base_request = record
            if base_request and "comment" in base_request._fields:
                base_request.sudo().with_context(
                    workflow_skip_edit_scope=True,
                    workflow_skip_field_policy=True,
                ).write({'comment': comment_value})

        for attachment in self.attachment_ids:
            attachment.sudo().write({
                'res_model': record._name,
                'res_id': record.id,
            })

    def _workflow_close_after_action(self, result=None):
        """Close the modal without opening a duplicate breadcrumb entry.

        The parent form button already registers an onClose reload callback, so
        returning act_window_close refreshes the current record without pushing a
        new form action for the same request.
        """
        close_action = {"type": "ir.actions.act_window_close"}
        if (
            isinstance(result, dict)
            and result.get("type") == "ir.actions.client"
            and result.get("tag") == "display_notification"
        ):
            result = dict(result)
            params = dict(result.get("params") or {})
            params.setdefault("next", close_action)
            result["params"] = params
            return result
        return close_action

    def action_confirm(self):
        """Called when user clicks Confirm in modal."""
        self.ensure_one()
        record = self._get_target_record()
        meta_action_id = self.env.context.get('meta_action_id')
        action_payload = {
            "meta_action_id": meta_action_id,
            "action_key": self.env.context.get("workflow_action_key") or self.env.context.get("action_type"),
            "source_node_id": self.env.context.get("workflow_task_node_id") or record.current_node_id,
        }
        if hasattr(record, "_workflow_resolve_meta_action_from_payload"):
            meta_action = record._workflow_resolve_meta_action_from_payload(action_payload)
        else:
            meta_action = self.env['workflow.category.version.meta.task.action'].sudo().browse(meta_action_id)
            if not meta_action.exists():
                raise UserError(_("Invalid workflow action payload. Please refresh and try again."))
        meta_action_id = meta_action.id
        request_record = record
        if record and "x_approval_base_id" in record._fields and record.x_approval_base_id:
            request_record = record.x_approval_base_id
        permission_service = self.env["workflow.engine.permission.service"]
        permission = permission_service.assert_can_execute_action(
            child_record=record,
            request_record=request_record,
            meta_action=meta_action,
            user=self.env.user,
        )
        action_context = {}
        if hasattr(record, "_workflow_build_action_execution_context"):
            action_context = record._workflow_build_action_execution_context(
                permission=permission,
                actor_user=self.env.user,
                task_node_id=meta_action.source_id,
            )
        record = record.with_context(action_context)
        request_record = request_record.with_context(action_context)
        if hasattr(record, "_workflow_validate_action_execution_guard"):
            record._workflow_validate_action_execution_guard(meta_action)
        workflow_record = record._workflow_elevated_action_record()
        workflow_request_record = request_record._workflow_elevated_action_record()
        if hasattr(workflow_request_record, "_workflow_can_execute_actor_node") and not workflow_request_record._workflow_can_execute_actor_node(
            meta_action.source_id,
            user=self.env.user,
        ):
            raise UserError(_("This action is no longer assigned to you."))

        field_rule_service = self.env["workflow.engine.field.rule.service"]
        action_key = meta_action.name or meta_action.attr_label
        try:
            field_rule_service.validate_action_required_fields(
                request_record=workflow_record,
                action_key=action_key,
                task_node_id=meta_action.source_id,
                view_id=self.env.context.get("view_id"),
            )
        except ValidationError:
            raise

        self._validate_action_input(meta_action, record=workflow_record)
        self._persist_action_input(workflow_record, meta_action)

        twofa_service = self.env["workflow.engine.twofactor.service"]
        challenge = self.challenge_id
        if twofa_service.action_requires_twofactor(workflow_request_record, meta_action, target_record=workflow_record):
            if not challenge:
                challenge = twofa_service.issue_action_challenge(
                    request_record=workflow_request_record,
                    meta_action=meta_action,
                    action_key=meta_action.name or meta_action.attr_label,
                    target_record=workflow_record,
                )
            if not challenge:
                raise ValidationError(_("2FA challenge could not be created."))
            # return client action to open 2FA dialog; do not execute engine yet
            return {
                "type": "ir.actions.client",
                "tag": "workflow_engine_twofa_dialog",
                "target": "new",
                "params": {
                    "challenge_id": challenge.id,
                    "meta_action_id": meta_action.id,
                    "res_model": record._name,
                    "res_id": record.id,
                    "view_id": self.env.context.get("view_id") or False,
                },
            }

        idempotency_key = self.env.context.get("workflow_idempotency_key") or (
            f"wiz:{self.id}:{record._name}:{record.id}:action:{meta_action_id}:user:{self.env.user.id}"
        )
            
        result = workflow_record.with_context(
            workflow_challenge_id=challenge.id if challenge else False,
            workflow_idempotency_key=idempotency_key,
            view_id=self.env.context.get("view_id") or False,
            meta_action_id=meta_action_id,
            workflow_action_key=action_key,
            workflow_task_node_id=meta_action.source_id or False,
            workflow_notification_actor_user_id=self.env.user.id,
        )._run_engine(
            form_data=workflow_record._get_form_data(),
            meta_action_id=meta_action_id
        )
        return self._workflow_close_after_action(result)

    def action_cancel(self):
        """Close without doing anything."""
        return {'type': 'ir.actions.act_window_close'}
