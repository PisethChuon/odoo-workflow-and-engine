# -*- coding: utf-8 -*-

from odoo import _, api, fields, models

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    wf_request_id = fields.Many2one(
        "workflow.base.approval.request",
        string="Workflow Request",
        readonly=True,
        index=True,
        copy=False,
    )
    wf_uploaded_activity_name = fields.Char(
        string="Uploaded At Activity",
        readonly=True,
        copy=False,
    )
    wf_uploaded_node_id = fields.Char(
        string="Uploaded At Node ID",
        readonly=True,
        copy=False,
    )
    
    wf_created_by_legacy = fields.Char(
        string="Legacy Created By",
        readonly=True,
        copy=False,
    )

    wf_created_date_legacy = fields.Datetime(
        string="Legacy Created Date",
        readonly=True,
        copy=False,
    )
    wf_id_legacy = fields.Integer(
        string="Legacy Workflow Request ID",
        readonly=True,
        copy=False,
    )

    is_admin = fields.Boolean(related="wf_request_id.is_admin", readonly=True)
    is_workflow_admin = fields.Boolean(related="wf_request_id.is_workflow_admin", readonly=True)
    is_creator = fields.Boolean(compute="_compute_is_creator", string="Is Creator", readonly=True)
    
    @api.depends_context('uid')
    @api.depends('create_uid', 'wf_request_id')
    def _compute_is_creator(self):
        for attachment in self:
            attachment.is_creator = attachment.create_uid == self.env.user and attachment.wf_request_id

    @api.model
    def _wf_resolve_base_request_from_target(self, res_model, res_id):
        Request = self.env["workflow.base.approval.request"].sudo()
        if not res_model or not res_id:
            return Request.browse()
        if res_model == Request._name:
            return Request.browse(res_id).exists()
        if res_model not in self.env:
            return Request.browse()

        target = self.env[res_model].sudo().browse(res_id).exists()
        if not target:
            return Request.browse()
        if "x_approval_base_id" in target._fields and target.x_approval_base_id:
            return target.x_approval_base_id.sudo().exists()
        return Request.browse()

    @api.model
    def _wf_prepare_upload_snapshot_vals(self, vals):
        if self.env.context.get('wf_skip_snapshot'):
            return {}
        
        request = self._wf_resolve_base_request_from_target(vals.get("res_model"), vals.get("res_id"))
        if not request:
            return {}
        return {
            "wf_request_id": request.id,
            "wf_uploaded_activity_name": request.current_activity_name or request.state or _("Unknown"),
            "wf_uploaded_node_id": request.current_node_id or False,
        }

    def _wf_collect_related_requests(self):
        """Collect workflow requests impacted by these attachments."""
        requests = self.env["workflow.base.approval.request"].browse()
        requests |= self.sudo().mapped("wf_request_id").exists()
        for attachment in self.sudo():
            requests |= self._wf_resolve_base_request_from_target(
                attachment.res_model,
                attachment.res_id,
            )
        return requests.exists()

    def _wf_invalidate_request_attachment_cache(self, requests):
        if not requests:
            return
        # Clear non-stored file list cache so form record.load() sees uploaded files immediately.
        requests.invalidate_recordset(["file_attachment_ids", "attachment_number"])

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for vals in vals_list:
            prepared_vals = dict(vals)
            if not prepared_vals.get("wf_request_id"):
                prepared_vals.update(self._wf_prepare_upload_snapshot_vals(prepared_vals))
            prepared_vals_list.append(prepared_vals)
        records = super().create(prepared_vals_list)
        records._wf_invalidate_request_attachment_cache(records._wf_collect_related_requests())
        return records

    def write(self, vals):
        requests_before = self._wf_collect_related_requests()
        result = super().write(vals)
        if "res_model" in vals or "res_id" in vals:
            for attachment in self:
                if attachment.wf_request_id:
                    continue
                snapshot_vals = attachment._wf_prepare_upload_snapshot_vals(
                    {"res_model": attachment.res_model, "res_id": attachment.res_id}
                )
                if snapshot_vals:
                    attachment.sudo().write(snapshot_vals)
        if {"res_model", "res_id", "wf_request_id", "datas", "raw", "name"} & set(vals.keys()):
            requests_after = self._wf_collect_related_requests()
            self._wf_invalidate_request_attachment_cache(requests_before | requests_after)
        return result

    def unlink(self):
        requests = self._wf_collect_related_requests()
        result = super().unlink()
        self._wf_invalidate_request_attachment_cache(requests)
        return result

    def action_wf_preview_file(self):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.id}?download=false',
            'target': 'new',
        }

    def action_wf_download_file(self):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.id}?download=true',
            'target': 'self',
        }

    @api.ondelete(at_uninstall=False)
    def _unlink_approved_approval_request(self):
        """
            Prevent attachment deletion for an approval request
            that is in the approved, refused or cancel state.
        """
        pass
        # Fixme:
        # approval_request_ids = [attachment.res_id for attachment in self if attachment.res_model == 'workflow.approval.request' and not attachment.res_field]
        # if not approval_request_ids:
        #     return
        # approval_requests = self.env['workflow.approval.request'].browse(approval_request_ids)
        # for approval_request in approval_requests:
        #     if approval_request.request_status in ['approved', 'refused', 'cancel']:
        #         raise UserError(_("You cannot unlink an attachment which is linked to a validated, refused or cancelled approval request."))
