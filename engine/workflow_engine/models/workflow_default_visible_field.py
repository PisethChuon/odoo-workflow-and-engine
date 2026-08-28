# -*- coding: utf-8 -*-

from odoo import api, fields, models


class WorkflowDefaultVisibleField(models.Model):
    _name = "workflow.default.visible.field"
    _description = "Workflow Default Visible Field"
    _rec_name = "field_id"
    _order = "model, field_name"

    _PREDEFINED_DEFAULT_VISIBLE_FIELDS = {
        "workflow.base.approval.request": (
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
            "request_owner_id",
            "create_uid",
            # Decision/comment stays visible unless a stage explicitly hides it.
            "comment",
        ),
    }

    active = fields.Boolean(default=True)
    is_predefined = fields.Boolean(
        string="Predefined",
        default=False,
        readonly=True,
        help="Created by Workflow as a default visible field. Built-in workflow fields remain protected in code.",
    )
    field_id = fields.Many2one(
        "ir.model.fields",
        string="Field",
        required=True,
        ondelete="cascade",
        index=True,
    )
    model_id = fields.Many2one(
        related="field_id.model_id",
        store=True,
        readonly=True,
    )
    model = fields.Char(
        related="field_id.model",
        store=True,
        readonly=True,
        index=True,
    )
    field_name = fields.Char(
        related="field_id.name",
        string="Technical Name",
        store=True,
        readonly=True,
        index=True,
    )
    field_description = fields.Char(
        related="field_id.field_description",
        string="Label",
        readonly=True,
    )
    ttype = fields.Selection(
        related="field_id.ttype",
        string="Type",
        store=True,
        readonly=True,
    )

    _field_id_unique = models.Constraint(
        "UNIQUE(field_id)",
        "This field is already configured as default visible.",
    )

    @api.model
    def ensure_predefined_default_visible_fields(self):
        Field = self.env["ir.model.fields"].sudo()
        DefaultVisible = self.sudo().with_context(active_test=False)
        for model_name, field_names in self._PREDEFINED_DEFAULT_VISIBLE_FIELDS.items():
            fields_by_name = {
                field.name: field
                for field in Field.search(
                    [
                        ("model", "=", model_name),
                        ("name", "in", list(field_names)),
                    ]
                )
            }
            for field_name in field_names:
                field = fields_by_name.get(field_name)
                if not field:
                    continue
                existing = DefaultVisible.search([("field_id", "=", field.id)], limit=1)
                if existing:
                    if not existing.is_predefined:
                        existing.write({"is_predefined": True})
                    continue
                DefaultVisible.create(
                    {
                        "field_id": field.id,
                        "is_predefined": True,
                    }
                )
        return True

    def _clear_workflow_default_visible_field_cache(self):
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._clear_workflow_default_visible_field_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {"active", "field_id"} & set(vals):
            self._clear_workflow_default_visible_field_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self._clear_workflow_default_visible_field_cache()
        return result
