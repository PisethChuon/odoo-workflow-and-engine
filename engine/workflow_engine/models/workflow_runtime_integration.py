# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class ApprovalChildMixinRuntimeIntegration(models.AbstractModel):
    _inherit = "approval.child.mixin"

    def _run_engine(self, form_data=None, meta_action_id=None, re_assign_approvals=True):
        runtime_service = self.env["workflow.engine.runtime.service"]
        for rec in self:
            base_request = rec._resolve_base_request_record()
            if base_request:
                runtime_service.lock_request(base_request)
        return super()._run_engine(
            form_data=form_data,
            meta_action_id=meta_action_id,
            re_assign_approvals=re_assign_approvals,
        )

    def action_do_transition(self, button, show_dialog=True):
        self.ensure_one()
        if not button:
            return super().action_do_transition(button, show_dialog=show_dialog)

        meta_action = self.env["workflow.category.version.meta.task.action"].sudo().browse(
            button.get("meta_action_id")
        )
        if not meta_action.exists():
            return super().action_do_transition(button, show_dialog=show_dialog)

        base_request = self._resolve_base_request_record()
        permission_service = self.env["workflow.engine.permission.service"]
        permission = permission_service.assert_can_execute_action(
            child_record=self,
            request_record=base_request,
            meta_action=meta_action,
            user=self.env.user,
        )
        context = dict(self.env.context)
        context.update(
            self._workflow_build_action_execution_context(
                permission=permission,
                actor_user=self.env.user,
                task_node_id=meta_action.source_id,
            )
        )
        return super(
            ApprovalChildMixinRuntimeIntegration,
            self.with_context(context),
        ).action_do_transition(button, show_dialog=show_dialog)

    def _assign_dynamic_approvers_from_meta(
        self,
        meta_action,
        current_node,
        next_node,
        is_need_to_send_mail,
    ):
        result = super()._assign_dynamic_approvers_from_meta(
            meta_action,
            current_node,
            next_node,
            is_need_to_send_mail,
        )
        assignment_service = self.env["workflow.engine.assignment.service"]
        for rec in self:
            try:
                base_request = rec._resolve_base_request_record()
                if not base_request or not base_request.version_id:
                    continue
                current_meta_task = rec._resolve_meta_task_for_node(
                    next_node.attrib.get("id"),
                    next_node.attrib.get("name"),
                )
                previous_meta_task = rec._resolve_meta_task_for_node(
                    current_node.attrib.get("id"),
                    current_node.attrib.get("name"),
                )
                if not current_meta_task:
                    continue

                open_iteration_values = base_request.approver_ids.filtered(
                    lambda a: a.current_meta_id.id == current_meta_task.id
                    and a.status in ("new", "pending", "waiting")
                ).mapped("iteration_no")
                iteration_no = max(open_iteration_values) if open_iteration_values else (base_request.current_iteration_no or 1)
                assignment_service.create_or_sync_task_instance_from_legacy(
                    request_record=base_request,
                    meta_task=current_meta_task,
                    previous_meta_task=previous_meta_task,
                    iteration_no=iteration_no,
                )
            except Exception:
                _logger.exception("Failed runtime assignment sync for request %s", rec.id)
        return result

    def _approve(self, meta_action):
        delegate_for_user_id = self.env.context.get("workflow_delegate_for_user_id")
        manual_delegated_approver_id = self.env.context.get("workflow_manual_delegated_approver_id")
        if delegate_for_user_id and not manual_delegated_approver_id:
            result = self._approve_as_delegate(meta_action, delegate_for_user_id)
        else:
            result = super()._approve(meta_action)

        runtime_service = self.env["workflow.engine.runtime.service"]
        challenge = self.env["workflow.approval.action.challenge"].browse(
            self.env.context.get("workflow_challenge_id")
        )
        on_behalf_user = self.env["res.users"].browse(delegate_for_user_id) if delegate_for_user_id else self.env["res.users"]
        for rec in self:
            base_request = rec._resolve_base_request_record()
            runtime_service.record_decision_from_legacy(
                request_record=base_request,
                meta_action=meta_action,
                actor_user=self.env.user,
                on_behalf_user=on_behalf_user if on_behalf_user else False,
                comment=rec.comment or False,
                idempotency_key=self.env.context.get("workflow_idempotency_key"),
                challenge=challenge if challenge else False,
            )
        return result

    def _workflow_process_actor_action(self, meta_action, execute_path=False):
        if (meta_action.authorization_mode or "approval_actor") != "business_actor":
            return super()._workflow_process_actor_action(
                meta_action,
                execute_path=execute_path,
            )

        assignment_service = self.env["workflow.engine.assignment.service"]
        challenge = self.env["workflow.approval.action.challenge"].browse(
            self.env.context.get("workflow_challenge_id")
        )
        result = self.env["workflow.request.task.event"]
        for rec in self:
            base_request = rec._resolve_base_request_record()
            actor_user = rec._workflow_resolve_notification_actor_user()
            self.env["workflow.engine.permission.service"].assert_can_execute_action(
                child_record=rec,
                request_record=base_request,
                meta_action=meta_action,
                user=actor_user,
            )
            result |= assignment_service._record_business_action(
                request_record=base_request,
                meta_action=meta_action,
                actor_user=actor_user,
                comment=rec.comment or False,
                execute_path=execute_path,
                idempotency_key=self.env.context.get("workflow_idempotency_key"),
                challenge=challenge if challenge else False,
            )
            if not execute_path:
                iteration_no = rec._resolve_iteration_for_action(meta_action.source_id)
                rec._workflow_close_runtime_branch(
                    meta_action.source_id,
                    reason=_("Closed by business action '%s'.")
                    % (meta_action.name or meta_action.attr_label or ""),
                    iteration_no=iteration_no,
                )
        return result

    def _approve_as_delegate(self, meta_action, delegate_for_user_id):
        delegate_for = self.env["res.users"].browse(delegate_for_user_id)
        if not delegate_for:
            raise AccessError(_("Invalid delegation target."))
        for request in self:
            # Keep domain/invisible guard from base flow.
            if meta_action.invisible_domain:
                if not request.check_domain(meta_action.invisible_domain, default=False):
                    raise AccessError(_("This request can no longer be updated."))

            active_iteration_no = request._resolve_iteration_for_action(meta_action.source_id)
            source_meta_task = request._resolve_meta_task_for_node(
                meta_action.source_id,
                meta_action.source_name,
            )
            approver_rec = request.approver_ids.filtered(
                lambda a: a.user_id.id == delegate_for.id
                and a.current_meta_id == meta_action.meta_task_id
                and (a.iteration_no or 1) == active_iteration_no
                and a.status in ("new", "pending", "waiting")
            )[:1]
            if not approver_rec:
                raise AccessError(
                    _(
                        "Delegation is no longer valid for this action. The original assignee has no open task."
                    )
                )

            request._workflow_assign_submission_folio_if_needed(source_meta_task)
            decision_status = request._resolve_approver_status_from_action(meta_action.name)
            approver_rec.write(
                {
                    "status": decision_status,
                    "user_decision": meta_action.name,
                    "comment": request.comment or "",
                    "updated_date": fields.Datetime.now(),
                }
            )
            request._cleanup_fields_after_approve(request)
            request.sudo()._update_next_approvers("pending", approver_rec, only_next_approver=True)
            request.sudo()._get_user_approval_activities(user=delegate_for).action_feedback()
        return True
