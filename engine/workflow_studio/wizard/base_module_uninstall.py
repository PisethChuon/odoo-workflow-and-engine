# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

STUDIO_CUSTOMIZATION_MODULES = ["workflow_studio_customization"]


class BaseModuleUninstall(models.TransientModel):
    _inherit = "base.module.uninstall"

    is_workflow_studio = fields.Boolean(compute='_compute_is_workflow_studio')
    custom_views = fields.Integer(compute='_compute_custom_views')
    custom_reports = fields.Integer(compute='_compute_custom_reports')
    custom_models = fields.Integer(compute='_compute_custom_models')
    custom_fields = fields.Integer(compute='_compute_custom_fields')

    @api.depends('impacted_module_ids')
    def _compute_is_workflow_studio(self):
        for wizard in self:
            wizard.is_workflow_studio = 'workflow_studio' in wizard.impacted_module_ids.mapped('name')

    @api.depends('impacted_module_ids')
    def _compute_custom_views(self):
        for wizard in self:
            view_ids = self.env['ir.model.data'].search([
                ('module', 'in', STUDIO_CUSTOMIZATION_MODULES),
                ('model', '=', 'ir.ui.view'),
            ]).mapped('res_id')
            wizard.custom_views = self.env['ir.ui.view'].search_count([
                ('id', 'in', view_ids),
                ('type', '!=', 'qweb'),
            ])

    @api.depends('impacted_module_ids')
    def _compute_custom_reports(self):
        for wizard in self:
            wizard.custom_reports = self.env['ir.model.data'].search_count([
                ('module', 'in', STUDIO_CUSTOMIZATION_MODULES),
                ('model', '=', 'ir.actions.report'),
            ])

    def _get_models(self):
        # Overridden to include customizations made with studio
        res = super()._get_models()
        if self.is_workflow_studio:
            res |= self.env['ir.model'].search([
                ('transient', '=', False),
                ('state', '=', 'manual')
            ])
        return res

    @api.depends('model_ids')
    def _compute_custom_models(self):
        for wizard in self:
            wizard.custom_models = len(wizard.model_ids.filtered(lambda x: x.state == 'manual'))

    @api.depends('impacted_module_ids')
    def _compute_custom_fields(self):
        for wizard in self:
            wizard.custom_fields = self.env['ir.model.fields'].search_count([
                ('state', '=', 'manual'),
            ])

    def _purge_orphan_studio_customization_xmlids(self):
        """Remove Workflow Studio XMLIDs pointing to deleted records.

        These dangling references can trigger MissingError during module uninstall.
        """
        IrModelData = self.env['ir.model.data'].sudo().with_context(active_test=False)
        module_data = IrModelData.search([
            ('module', 'in', STUDIO_CUSTOMIZATION_MODULES),
            ('res_id', '!=', False),
        ])
        if not module_data:
            return 0

        to_unlink = IrModelData.browse()
        grouped = {}
        for data in module_data:
            grouped.setdefault(data.model, []).append((data.id, data.res_id))

        for model_name, rows in grouped.items():
            if not model_name or model_name not in self.env:
                to_unlink |= IrModelData.browse([row[0] for row in rows])
                continue

            res_ids = [res_id for _, res_id in rows]
            existing_ids = set(
                self.env[model_name]
                .sudo()
                .with_context(active_test=False)
                .browse(res_ids)
                .exists()
                .ids
            )
            missing_imd_ids = [
                imd_id
                for imd_id, res_id in rows
                if res_id not in existing_ids
            ]
            if missing_imd_ids:
                to_unlink |= IrModelData.browse(missing_imd_ids)

        if not to_unlink:
            return 0

        count = len(to_unlink)
        _logger.info(
            "Deleting %s orphan Workflow Studio ir.model.data record(s) before module uninstall",
            count,
        )
        to_unlink.unlink()
        return count

    def action_uninstall(self):
        for wizard in self:
            modules_to_remove = set(wizard._get_modules().mapped('name'))
            if 'workflow_studio' in modules_to_remove:
                wizard._purge_orphan_studio_customization_xmlids()
        return super().action_uninstall()
