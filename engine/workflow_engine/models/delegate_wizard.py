# x_delegate_wizard.py
from odoo import api, fields, models, _
import logging
from markupsafe import Markup
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class DelegateWizard(models.TransientModel):
    _name = "delegate_wizard"
    _description = "Delegate Wizard"

    _inherit = ['mail.thread', 'mail.activity.mixin']

    delegate_type = fields.Selection(
        [("redirected", "Redirected"), ("shared", "Shared")], required=True
    )
    res_id = fields.Integer('Record ID')
    res_model = fields.Char('Model')

    request_id = fields.Many2one("workflow.base.approval.request", string="Base Request",
                                 compute="_compute_parent_request_id", store=True)
    source_approver_id = fields.Many2one(
        "workflow.approval.approver",
        string="Source Approver",
        domain="[('id', 'in', available_source_approver_ids)]",
    )
    available_source_approver_ids = fields.Many2many(
        "workflow.approval.approver",
        compute="_compute_source_approver_options",
        string="Available Source Approvers",
    )
    show_source_approver_selection = fields.Boolean(
        compute="_compute_source_approver_options",
        string="Show Source Approver Selection",
    )
    selected_user_id = fields.Many2one("res.users", string="Approver", domain=lambda self: [('id', '!=', self.env.uid),
                                                                                            ('id', 'in', self.env.ref(
                                                                                                'workflow_engine.group_workflow_approval_user').user_ids.ids),
                                                                                            ('wf_hide_from_workflow_picker', '=', False)])
    selected_user_ids = fields.Many2many(
        "res.users",
        string="Share With",
        domain=lambda self: [
            ('id', '!=', self.env.uid),
            ('id', 'in', self.env.ref(
                'workflow_engine.group_workflow_approval_user'
            ).user_ids.ids),
            ('wf_hide_from_workflow_picker', '=', False),
        ],
    )
    comment = fields.Text(string="Comment")
    selected_employee_id = fields.Many2one(string="Employee", readonly=True, related="selected_user_id.employee_id")
    department_id = fields.Many2one(string="Department", readonly=True, related="selected_employee_id.department_id")
    job_id = fields.Many2one(string="Job Position", readonly=True, related="selected_employee_id.job_id")
    work_email = fields.Char(string="Email", readonly=True, related="selected_employee_id.work_email")
    ext_phone = fields.Char(string="Extension", readonly=True, related="selected_employee_id.x_ext_phone")
    emp_code = fields.Char(string="Employee Id", readonly=True, related="selected_employee_id.x_emp_code")
    mobile_phone = fields.Char(string="Mobile Phone", readonly=True, related="selected_employee_id.mobile_phone")
    avatar = fields.Binary(string="Avatar", readonly=True, related="selected_employee_id.avatar_128")

    @api.onchange("delegate_type")
    def _onchange_delegate_type(self):
        for rec in self:
            if rec.delegate_type == "shared":
                rec.selected_user_id = False
            elif rec.delegate_type == "redirected":
                rec.selected_user_ids = [fields.Command.clear()]

    @api.depends("res_id", "res_model")
    def _compute_parent_request_id(self):
        for rec in self:
            if rec.res_model == "workflow.base.approval.request":
                rec.request_id = rec.res_id
            else:
                if rec.res_model:
                    child_obj = rec.env[rec.res_model].browse(rec.res_id)
                    if child_obj:
                        rec.request_id = child_obj.x_approval_base_id

    @api.depends("request_id")
    def _compute_source_approver_options(self):
        Approver = self.env["workflow.approval.approver"]
        for rec in self:
            available = Approver
            show_selector = False
            if rec.request_id:
                available = rec._delegation_source_rows(rec.request_id)
                has_override = rec.request_id._workflow_user_has_delegate_override(user=rec.env.user)
                show_selector = (
                    has_override
                    and len(available) > 1
                )
            rec.available_source_approver_ids = available
            rec.show_source_approver_selection = show_selector
            if rec.source_approver_id and rec.source_approver_id not in available:
                rec.source_approver_id = False
            if not show_selector and len(available) == 1:
                rec.source_approver_id = available[:1]

    def _get_audit_comment(self, audit_comment=False):
        self.ensure_one()
        comment = (audit_comment if audit_comment is not False else self.comment) or ""
        comment = comment.strip()
        if not comment:
            raise ValidationError(_("This action requires a comment."))
        return comment

    def _build_audit_message(self, detail, comment):
        return Markup("<p><b>%s</b> %s</p><p><b>%s</b> %s</p>") % (
            _("Delegation:"),
            html_escape(detail),
            _("Comment:"),
            html_escape(comment),
        )

    def _ensure_user_can_delegate(self, request):
        self.ensure_one()
        if not request.check_if_user_can_delegate(request, user=self.env.user):
            raise UserError(_("You are not allowed to delegate this workflow activity."))

    def _delegation_source_rows(self, request):
        self.ensure_one()
        request = request.sudo()
        current_meta_task = request.version_id.meta_task_ids.filtered(lambda m: m.node_id == request.current_node_id)[:1]
        if not current_meta_task:
            return self.env["workflow.approval.approver"]
        iteration_resolver = getattr(request, "_resolve_iteration_for_action", None)
        if callable(iteration_resolver):
            iteration_no = iteration_resolver(request.current_node_id)
        else:
            iteration_no = request.current_iteration_no or 1
        rows = request.approver_ids.filtered(
            lambda row: row.current_meta_id.id == current_meta_task.id
            and (row.iteration_no or 1) == iteration_no
            and row.status in ("new", "pending", "waiting")
        ).sorted(key=lambda row: (row.sequence, row.id))
        if request._workflow_user_has_delegate_override(user=self.env.user):
            return rows
        return rows.filtered(lambda row: row.user_id.id == self.env.user.id)

    def _resolve_source_approver(self, request, source_approver=False):
        self.ensure_one()
        source_rows = self._delegation_source_rows(request)
        if source_approver and source_approver in source_rows:
            return source_approver
        if len(source_rows) == 1:
            return source_rows[:1]
        if not source_rows:
            actor_node_id = request._workflow_get_actor_primary_node_id(user=self.env.user)
            business_rows = self.env[
                "workflow.engine.assignment.service"
            ]._open_business_action_assignments(
                request,
                user=self.env.user,
                node_id=actor_node_id,
            )
            if business_rows:
                return self.env["workflow.approval.approver"]
            raise UserError(_("No active source approver is available for delegation on this stage."))
        raise UserError(_("Please choose which current approver should be delegated."))

    def _delegate_business_only(self, request, delegate_type, selected_user, audit_comment):
        self.ensure_one()
        source_user = self.env.user
        if selected_user == source_user:
            raise UserError(_("Please choose a different user for delegation."))
        actor_node_id = request._workflow_get_actor_primary_node_id(user=source_user)
        source_rows = self.env[
            "workflow.engine.assignment.service"
        ]._open_business_action_assignments(
            request,
            user=source_user,
            node_id=actor_node_id,
        )
        if not source_rows:
            raise UserError(_("No active business action is available for delegation."))
        task_instance = source_rows[:1].task_instance_id
        iteration_no = task_instance.iteration_no or 1
        result = self.env[
            "workflow.engine.assignment.service"
        ]._delegate_business_action_assignments(
            request,
            source_user,
            selected_user,
            delegate_type,
            node_id=actor_node_id,
            iteration_no=iteration_no,
            delegated_by=self.env.user,
            comment=audit_comment,
        )
        if not result.get("source_ids"):
            raise UserError(_("No active business action is available for delegation."))
        delegate_label = dict(self._fields["delegate_type"].selection).get(
            delegate_type,
            delegate_type or _("Delegated"),
        )
        request._workflow_safe_message_post(
            body=self._build_audit_message(
                self._build_delegation_detail(
                    source_user,
                    selected_user,
                    delegate_type,
                    self.env.user.name or _("Unknown User"),
                ),
                audit_comment,
            ),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        self.env["workflow.engine.audit.service"].log_event(
            request_record=request,
            event_type="delegation",
            action_key=delegate_label,
            from_node_id=actor_node_id,
            actor_user=self.env.user,
            on_behalf_of_user=source_user,
            target_user=selected_user,
            comment=audit_comment,
            payload={
                "mode": delegate_type,
                "source_approver_id": False,
                "delegated_approver_id": False,
                "business_action_source_assignment_ids": result.get("source_ids") or [],
                "business_action_target_assignment_ids": result.get("target_ids") or [],
                "admin_override": False,
            },
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _build_delegation_detail(self, source_user, selected_user, delegate_type, actor_name):
        mode_label = dict(self._fields["delegate_type"].selection).get(delegate_type, delegate_type or _("Delegated"))
        if delegate_type == "shared":
            return _("%(source)s shared with %(target)s by %(actor)s") % {
                "source": source_user.name,
                "target": selected_user.name,
                "actor": actor_name,
            }
        return _("%(source)s redirected to %(target)s by %(actor)s") % {
            "source": source_user.name,
            "target": selected_user.name,
            "actor": actor_name,
        }

    def _next_delegation_event_orders(self, request, iteration_no):
        self.ensure_one()
        self.env.cr.execute(
            """
            SELECT COALESCE(MAX(event_order), 0)
              FROM workflow_approval_approver
             WHERE request_id = %s
               AND COALESCE(iteration_no, 1) = %s
            """,
            (request.id, iteration_no or 1),
        )
        current_max = self.env.cr.fetchone()[0] or 0
        return current_max + 1, current_max + 2

    def action_server_delegate(self):
        """Create (or reuse) a workflow.approval.approver for the chosen user."""
        self.ensure_one()
        if not self.request_id:
            raise UserError(_("No request selected."))
        if self.delegate_type == "shared":
            # Keep the single-user fallback for existing RPC integrations while
            # the wizard UI moves Share to the multi-user field.
            selected_users = self.selected_user_ids or self.selected_user_id
            if not selected_users:
                raise UserError(_("Please choose at least one user to share with."))
        else:
            if not self.selected_user_id:
                raise UserError(_("Please choose one approver to redirect to."))
            selected_users = self.selected_user_id
        request = self.request_id.sudo()
        self._ensure_user_can_delegate(request)
        audit_comment = self._get_audit_comment()
        for selected_user in selected_users:
            self.delegate(
                request,
                self.delegate_type,
                selected_user,
                source_approver=self.source_approver_id,
                is_create_activity=True,
                audit_comment=audit_comment,
            )
        return {"type": "ir.actions.client", "tag": "reload"}

    @api.model
    def delegate(self, request, delegate_type, selected_user, source_approver=False, is_create_activity=False, audit_comment=False):
        self.ensure_one()
        audit_comment = self._get_audit_comment(audit_comment=audit_comment)
        self._ensure_user_can_delegate(request)
        if selected_user.wf_hide_from_workflow_picker:
            raise UserError(_("This user is hidden from workflow selections and cannot be delegated to."))
        source_approver = self._resolve_source_approver(request, source_approver=source_approver)
        if not source_approver:
            return self._delegate_business_only(
                request,
                delegate_type,
                selected_user,
                audit_comment,
            )
        source_approver = source_approver.sudo()
        if selected_user.id == source_approver.user_id.id:
            raise UserError(_("Please choose a different user for delegation."))

        current_meta_task = source_approver.current_meta_id
        if not current_meta_task:
            raise UserError(_("Cannot delegate: missing current meta task in request."))

        previous_meta_task = source_approver.previous_meta_id or request.version_id.meta_task_ids.filtered(
            lambda m: m.node_id == request.previous_node_id
        )[:1]
        if not previous_meta_task:
            raise UserError(_("Cannot delegate: missing previous meta task in request."))
        active_iteration_no = source_approver.iteration_no or request.current_iteration_no or 1
        existing_target_row = request.approver_ids.filtered(
            lambda row: row.user_id.id == selected_user.id
            and row.current_meta_id.id == current_meta_task.id
            and (row.iteration_no or 1) == active_iteration_no
            and row.status in ("new", "pending", "waiting")
        )[:1]
        _logger.info("%s request %s to user %s as %s", delegate_type.capitalize(),
                     request.display_name, selected_user.name, delegate_type)
        actor_name = self.env.user.name or _("Unknown User")
        delegate_label = dict(self._fields["delegate_type"].selection).get(delegate_type, delegate_type or _("Unknown"))
        source_user = source_approver.user_id

        Approver = self.env["workflow.approval.approver"].sudo()
        audit_service = self.env["workflow.engine.audit.service"]
        delegated_at = fields.Datetime.now()
        audit_rows = self.env["workflow.approval.approver"]
        assignment_event_order, decision_event_order = self._next_delegation_event_orders(
            request,
            active_iteration_no,
        )

        if delegate_type == "redirected":
            audit_remark = _("Redirected to '%(target)s' by '%(actor)s'") % {
                "target": selected_user.name,
                "actor": actor_name,
            }
            if (source_approver.remark or "").strip():
                audit_remark = "%s\n%s" % ((source_approver.remark or "").strip(), audit_remark)
            source_approver.write({
                'status': 'closed',
                'user_decision': _("Redirected"),
                'comment': audit_comment,
                'remark': audit_remark,
                'delegation_mode': 'redirected',
                'delegated_from_user_id': source_user.id,
                'delegated_from_approver_id': source_approver.id,
                'delegated_to_user_id': selected_user.id,
                'delegated_by_user_id': self.env.user.id,
                'delegated_at': delegated_at,
                'activity_event_at': delegated_at,
                'event_order': decision_event_order,
            })
            audit_rows |= source_approver

        open_row_vals = [{
            "current_meta_id": current_meta_task.id,
            "previous_meta_id": previous_meta_task.id,
            "user_id": selected_user.id,
            "required": source_approver.required,
            "status": 'new',
            "sequence": source_approver.sequence or 10,
            "iteration_no": active_iteration_no,
            "request_id": request.id,
            "comment": audit_comment,
            "remark": _("Delegated by '%(actor)s' on behalf of '%(source)s' (%(mode)s)") % {
                "actor": actor_name,
                "source": source_user.name,
                "mode": delegate_label,
            },
            "delegation_mode": delegate_type,
            "delegated_from_user_id": source_user.id,
            "delegated_from_approver_id": source_approver.id,
            "delegated_to_user_id": selected_user.id,
            "delegated_by_user_id": self.env.user.id,
            "delegated_at": delegated_at,
            "activity_event_at": delegated_at,
            "event_order": assignment_event_order,
        }]
        approver = existing_target_row or Approver.create(open_row_vals)
        if not existing_target_row:
            _logger.info("Created approver %s for request %s", approver.id, request.display_name)
        audit_rows |= approver

        if delegate_type == "shared":
            shared_audit_row = Approver.create({
                "current_meta_id": current_meta_task.id,
                "previous_meta_id": previous_meta_task.id,
                "user_id": source_user.id,
                "required": False,
                "status": "closed",
                "user_decision": _("Shared"),
                "sequence": source_approver.sequence or 10,
                "iteration_no": active_iteration_no,
                "request_id": request.id,
                "comment": audit_comment,
                "remark": _("Shared with '%(target)s' by '%(actor)s'") % {
                    "target": selected_user.name,
                    "actor": actor_name,
                },
                "delegation_mode": "shared",
                "delegated_from_user_id": source_user.id,
                "delegated_from_approver_id": source_approver.id,
                "delegated_to_user_id": selected_user.id,
                "delegated_by_user_id": self.env.user.id,
                "delegated_at": delegated_at,
                "activity_event_at": delegated_at,
                "event_order": decision_event_order,
            })
            audit_rows |= shared_audit_row

        if is_create_activity:
            request._workflow_safe_message_post(
                body=self._build_audit_message(
                    self._build_delegation_detail(source_user, selected_user, delegate_type, actor_name),
                    audit_comment,
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_note'
            )
            if not existing_target_row:
                approver._create_activity()

        business_delegation = self.env[
            "workflow.engine.assignment.service"
        ]._delegate_business_action_assignments(
            request,
            source_user,
            selected_user,
            delegate_type,
            node_id=current_meta_task.node_id,
            iteration_no=active_iteration_no,
            delegated_by=self.env.user,
            comment=audit_comment,
        )

        audit_service.log_event(
            request_record=request,
            event_type="delegation",
            action_key=delegate_label,
            from_node_id=current_meta_task.node_id,
            actor_user=self.env.user,
            on_behalf_of_user=source_user,
            target_user=selected_user,
            comment=audit_comment,
            payload={
                "mode": delegate_type,
                "source_approver_id": source_approver.id,
                "delegated_approver_id": approver.id,
                "affected_approver_row_ids": audit_rows.ids,
                "business_action_source_assignment_ids": business_delegation.get("source_ids") or [],
                "business_action_target_assignment_ids": business_delegation.get("target_ids") or [],
                "admin_override": bool(
                    request._workflow_user_has_delegate_override(user=self.env.user)
                    and source_user.id != self.env.user.id
                ),
            },
        )

        # Refresh
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
