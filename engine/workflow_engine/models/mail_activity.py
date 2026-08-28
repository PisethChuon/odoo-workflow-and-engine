# -*- coding: utf-8 -*-

from odoo import _, models
from odoo.addons.mail.tools.discuss import Store
from odoo.tools import is_html_empty


class MailActivity(models.Model):
    _inherit = "mail.activity"

    def action_notify(self):
        if not self.env.context.get("workflow_activity_no_email"):
            return super().action_notify()

        workflow_activity_type = self.env.ref(
            "workflow_engine.mail_activity_data_workflow_approval",
            raise_if_not_found=False,
        )
        if not workflow_activity_type:
            return super().action_notify()

        workflow_activities = self.filtered(
            lambda activity: activity.activity_type_id == workflow_activity_type
        )
        activities_to_notify = self - workflow_activities
        if activities_to_notify:
            super(MailActivity, activities_to_notify).action_notify()
        if not workflow_activities:
            return False

        classified = workflow_activities._classify_by_model()
        for model, activity_data in classified.items():
            records_sudo = self.env[model].sudo().browse(activity_data["record_ids"])
            activity_data["record_ids"] = records_sudo.exists().ids

        for activity in workflow_activities.filtered("res_model"):
            if activity.res_id not in classified[activity.res_model]["record_ids"]:
                continue

            if activity.user_id.lang:
                activity = activity.with_context(lang=activity.user_id.lang)

            model_description = activity.env["ir.model"]._get(activity.res_model).display_name
            body = activity.env["ir.qweb"]._render(
                "mail.message_activity_assigned",
                {
                    "activity": activity,
                    "model_description": model_description,
                    "is_html_empty": is_html_empty,
                },
                minimal_qcontext=True,
            )
            record = activity.env[activity.res_model].browse(activity.res_id)
            if not activity.user_id.partner_id or not hasattr(record, "_workflow_safe_message_notify_inbox_only"):
                continue

            record._workflow_safe_message_notify_inbox_only(
                partner_ids=activity.user_id.partner_id.ids,
                body=body,
                subject=_(
                    '"%(activity_name)s: %(summary)s" assigned to you',
                    activity_name=activity.res_name,
                    summary=activity.summary or activity.activity_type_id.name or "",
                ),
                force_record_name=activity.res_name,
            )
        return False

    def _to_store_defaults(self, store: Store):
        # Keep the core payload sent to OWL activity widgets.
        # If this method does not return the superclass defaults, fields such as
        # activity_type_id/create_uid/date_deadline/summary are missing in the UI.
        return super()._to_store_defaults(store)
        # fixme:
        # activity_type_approval_id = self.env.ref("workflow_engine.mt_workflow_approval_request_status")
        # for activity in self.filtered(
        #     lambda activity: activity["res_model"] == "workflow.approval.request"
        #     and activity.activity_type_id == activity_type_approval_id
        # ):
        #     request = self.env["workflow.approval.request"].browse(activity["res_id"])
        #     approver = request.approver_ids.filtered(
        #         lambda approver: activity.user_id == approver.user_id
        #     )
        #     store.add(activity, {"approver_id": approver.id, "approver_status": approver.status})
