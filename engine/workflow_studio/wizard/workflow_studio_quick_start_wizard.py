# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


class WorkflowStudioQuickStartWizard(models.TransientModel):
    _name = "workflow.studio.quick.start.wizard"
    _description = "Workflow Studio Quick Start Wizard"

    model_source = fields.Selection(
        selection=[
            ("create_new", "Create New Model"),
            ("use_existing", "Use Existing Model (has_approve=true)"),
        ],
        string="Model Source",
        required=True,
        default="create_new",
    )
    model_name = fields.Char(string="Model Name")
    existing_model_id = fields.Many2one(
        "ir.model",
        string="Existing Model",
        domain=[("is_approval", "=", True), ("transient", "=", False)],
    )
    category_name = fields.Char(string="Category Name")
    has_approval = fields.Boolean(
        string="Has Approval",
        default=True,
        readonly=True,
    )

    def _ensure_workflow_studio_admin(self):
        if not (
            self.env.user.has_group("workflow_engine.group_workflow_approval_admin")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Only Workflow Approval Admin users can design workflows."))

    def action_create_and_open_studio(self):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        if self.model_source == "use_existing":
            model = self.existing_model_id.sudo()
            if not model:
                raise UserError(_("Please select an existing model."))
            if not model.is_approval or model.transient:
                raise UserError(
                    _("Selected model must be approval-enabled (has_approve=true) and non-transient.")
                )
            model_name = (model.name or model.model or "").strip()
        else:
            model_name = (self.model_name or "").strip()
            if not model_name:
                raise UserError(_("Please provide a model name."))
            options = ["has_approval"]
            model, _extra_models = self.env["ir.model"].sudo().studio_model_create(
                model_name,
                options=options,
            )

        category_name = (self.category_name or "").strip() or model_name

        category = self.env["workflow.approval.category"].sudo().search(
            [("res_model", "=", model.id)],
            limit=1,
        )
        if not category:
            category = self.env["workflow.approval.category"].sudo().create(
                {
                    "name": category_name or model.name,
                    "automated_sequence": True,
                    "res_model": model.id,
                }
            )

        version_data = category.workflow_studio_create_initial_version(
            {"title": category_name}
        )
        return category.with_context(
            workflow_version_id=version_data["version_id"]
        ).action_activate_workflow_studio()
