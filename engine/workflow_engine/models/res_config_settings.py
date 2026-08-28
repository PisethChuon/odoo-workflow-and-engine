from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    workflow_business_action_actor_enabled = fields.Boolean(
        string="Business Action Actors",
        config_parameter="workflow_engine.business_action_actor_enabled",
        default=False,
        help=(
            "Enable exact stage-bound business action assignments. Existing approval actions "
            "are unaffected."
        ),
    )

    workflow_default_owner_notification_template_id = fields.Many2one(
        "mail.template",
        string="Default Owner Update Email Template",
        help="Fallback template used for built-in owner update emails when a workflow version does not define a category-specific template.",
    )

    @api.constrains("workflow_default_owner_notification_template_id")
    def _check_workflow_default_owner_notification_template_id(self):
        for rec in self:
            template = rec.workflow_default_owner_notification_template_id
            if (
                template
                and template.model_id
                and template.model_id.model != "workflow.base.approval.request"
            ):
                raise ValidationError(
                    _("The default owner update email template must belong to the Approval Base Request model.")
                )

    @api.model
    def get_values(self):
        values = super().get_values()
        template_id = self.env["ir.config_parameter"].sudo().get_param(
            "workflow_engine.default_owner_notification_template_id"
        )
        try:
            template_id = int(template_id or 0)
        except (TypeError, ValueError):
            template_id = 0
        if not template_id:
            try:
                template_id = self.env.ref("workflow_engine.email_template_workflow_email_notify").id
            except ValueError:
                template_id = False
        values.update(
            workflow_default_owner_notification_template_id=template_id or False
        )
        return values

    def set_values(self):
        super().set_values()
        self.ensure_one()
        template_id = self.workflow_default_owner_notification_template_id.id or ""
        self.env["ir.config_parameter"].sudo().set_param(
            "workflow_engine.default_owner_notification_template_id",
            template_id,
        )
