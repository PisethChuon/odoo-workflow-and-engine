from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import NODE_TYPE


class ForceTransitionWizard(models.TransientModel):
    _name = "workflow.force.transition.wizard"
    _description = "Force Jump to BPMN Node"

    # store the child model name
    model = fields.Char('Related Document Model', required=True)

    # store the integer id of the child model record
    request_id = fields.Many2oneReference('Related Document Id', model_field='model')

    # name of the request
    request_name = fields.Char('Request Name', compute="_compute_request_name")

    target_node = fields.Many2one(
        "workflow.bpmn.temp.node",
        string="Select Target Node",
        required=True,
        ondelete="cascade"
    )
    category_id = fields.Many2one('workflow.approval.category', string="Workflow Category", compute="_compute_category_id", store=True)
    
    re_assign_approvals = fields.Boolean(
        string="Re-assign Approvals",
        default=True,
        help="If checked, approvals will be reassigned according to the new node's configuration."
    )
    comment = fields.Text(string="Comment")

    @api.depends('request_id', 'model')
    def _compute_category_id(self):
        for rec in self:
            if rec.model and rec.request_id:
                target_rec = self.env[rec.model].browse(rec.request_id)
                # Check if the target model actually has a category_id field
                rec.category_id = target_rec.category_id if 'category_id' in target_rec._fields else False
            else:
                rec.category_id = False

    def _get_force_target_meta_tasks(self, version, request=False):
        """Return deterministic force-jump candidates for the selected version."""
        start_types = {
            NODE_TYPE["START_EVENT"],
            NODE_TYPE["START_EVENT_WITH_MESSAGE"],
            NODE_TYPE["START_EVENT_WITH_TIMER"],
            NODE_TYPE["START_EVENT_WITH_SIGNAL"],
            NODE_TYPE["START_EVENT_WITH_CONDITIONAL"],
        }
        current_node_id = request.current_node_id if request and "current_node_id" in request._fields else False
        candidates = version.meta_task_ids.filtered(
            lambda task: bool(task.node_id) and task.node_type not in start_types
        )
        if current_node_id:
            candidates = candidates.filtered(lambda task: task.node_id != current_node_id)
        return candidates.sorted(key=lambda task: (task.sequence or 10, task.id))

    def _rebuild_temp_target_nodes(self, request):
        TempNode = self.env["workflow.bpmn.temp.node"]
        Wizard = self.env["workflow.force.transition.wizard"]
        user_id = self.env.uid
        
        version = request.version_id or request.category_id.active_version_id
        if not version:
            stale_nodes = user_nodes.filtered(lambda node: node.id not in referenced_node_ids)
            if stale_nodes:
                stale_nodes.unlink()
            return TempNode.browse()
        
        user_nodes = TempNode.search([
            ("create_uid", "=", user_id), 
            ("category_id", "=", version.category_id.id)
            ])
        referenced_node_ids = set(
            Wizard.search(
                [
                    ("create_uid", "=", user_id),
                    ("target_node", "!=", False),
                ]
            ).mapped("target_node").ids
        )
        if not request:
            stale_nodes = user_nodes.filtered(lambda node: node.id not in referenced_node_ids)
            if stale_nodes:
                stale_nodes.unlink()
            return TempNode.browse()

        by_code = {node.code: node for node in user_nodes if node.code}
        candidate_nodes = TempNode.browse()
        keep_ids = set()
        for meta_task in self._get_force_target_meta_tasks(version, request=request):
            code = meta_task.node_id
            node = by_code.get(code)
            vals = {
                "code": code,
                "name": meta_task.name or code,
                "node_type": meta_task.node_type,
                "category_id": version.category_id.id,
            }
            if node:
                node.write(vals)
            else:
                node = TempNode.create(vals)
            keep_ids.add(node.id)
            candidate_nodes |= node

        stale_nodes = user_nodes.filtered(
            lambda node: node.id not in keep_ids and node.id not in referenced_node_ids
        )
        if stale_nodes:
            stale_nodes.unlink()

        return candidate_nodes.sorted(key=lambda node: (node.name or "", node.id))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        context = self.env.context
        default_model = context.get("default_model")
        active_model = context.get("active_model")
        model_name = res.get("model") or default_model or active_model or "workflow.base.approval.request"
        if (
            model_name == "workflow.base.approval.request"
            and active_model
            and active_model in self.env
            and active_model != "workflow.base.approval.request"
        ):
            # Child forms may still pass default_model=workflow.base.approval.request.
            # Prefer active_model to keep request resolution accurate.
            model_name = active_model
        request_ref = res.get("request_id") or context.get("default_request_id") or context.get("active_id")
        if model_name and request_ref:
            res["model"] = model_name
            res["request_id"] = request_ref
            wizard_preview = self.new(
                {
                    "model": model_name,
                    "request_id": request_ref,
                }
            )
            request = wizard_preview._resolve_request_record()
            if request:
                res["request_name"] = request.display_name or ""
            nodes = wizard_preview._rebuild_temp_target_nodes(request)
            first = nodes[:1]
            if first:
                res["target_node"] = first.id
        return res

    @api.depends('request_id')
    def _compute_request_name(self):
        for record in self:
            request = record._resolve_request_record()
            record.request_name = request.display_name if request else ""

    def _get_reference_res_id(self):
        self.ensure_one()
        ref = self.request_id
        if not ref:
            return False
        if hasattr(ref, "id"):
            return ref.id
        try:
            return int(ref)
        except Exception:
            return False

    def _resolve_request_record(self):
        self.ensure_one()
        model_name = self.model or "workflow.base.approval.request"
        res_id = self._get_reference_res_id()
        if not res_id:
            active_model = self.env.context.get("active_model")
            active_id = self.env.context.get("active_id")
            if active_model and active_id and active_model in self.env:
                active_rec = self.env[active_model].browse(active_id).exists()
                if active_rec:
                    if active_model == "workflow.base.approval.request":
                        target = active_rec._get_transition_delegate_record()
                        return target if target else active_rec
                    return active_rec
            return self.env["workflow.base.approval.request"]

        if model_name in self.env:
            model = self.env[model_name]
            direct = model.browse(res_id).exists()
            if direct:
                if model_name == "workflow.base.approval.request":
                    target = direct._get_transition_delegate_record()
                    return target if target else direct
                return direct

            # Backward-compatibility:
            # some callers pass base request id while model_name points to child model.
            link_field = model._fields.get("x_approval_base_id")
            # Only run SQL domains on stored link fields. Base request keeps this
            # compatibility field non-stored, which cannot be converted to SQL.
            if link_field and getattr(link_field, "store", False):
                child = model.sudo().search([("x_approval_base_id", "=", res_id)], limit=1)
                if child:
                    return model.browse(child.id)

        # Child-form fallback: when default_model was set to base request but id belongs
        # to the child model, use active_model/active_id from context.
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model and active_id and active_model in self.env:
            active_rec = self.env[active_model].browse(active_id).exists()
            if active_rec:
                if active_model == "workflow.base.approval.request":
                    target = active_rec._get_transition_delegate_record()
                    return target if target else active_rec
                return active_rec

        base_request = self.env["workflow.base.approval.request"].browse(res_id).exists()
        if not base_request:
            return self.env["workflow.base.approval.request"]
        target = base_request._get_transition_delegate_record()
        return target if target else base_request

    # def _get_target_nodes(self):
    #     """Dynamic method to compute selection options based on request_id."""
    #     if not self.request_id:
    #         return []
    #     engine = BpmnEngine(self.request_id.version_id.bpmn_xml)
    #     nodes = [(n.attrib["id"], n.attrib.get("name", "No Label")) 
    #             for n in engine.tree.findall(".//*[@id]")]
    #     return nodes
    
    @api.onchange("request_id")
    def _onchange_request_id(self):
        request = self._resolve_request_record()
        self.request_name = request.display_name if request else ""
        nodes = self._rebuild_temp_target_nodes(request)
        self.target_node = nodes[:1]

    def action_confirm_force(self):
        self.ensure_one()
        if not self.target_node:
            raise UserError(_("Please select a target node."))
        comment = (self.comment or "").strip()
        if not comment:
            raise ValidationError(_("This action requires a comment."))
        request = self._resolve_request_record()
        if not request:
            raise ValidationError(_("Invalid request selected."))
        if not hasattr(type(request), "action_force_transition"):
            raise UserError(_("This request model does not support force transition."))
        result = request.action_force_transition(
            self.target_node,
            self.re_assign_approvals,
            audit_comment=comment,
        )

        # Most force transitions go through _run_engine(), which can legitimately
        # return None for non-terminal nodes. Always close the wizard in that case.
        if not result:
            return {"type": "ir.actions.act_window_close"}

        # Keep notifications while ensuring the modal can close afterwards.
        if (
            isinstance(result, dict)
            and result.get("type") == "ir.actions.client"
            and result.get("tag") == "display_notification"
        ):
            params = dict(result.get("params") or {})
            params.setdefault("next", {"type": "ir.actions.act_window_close"})
            result["params"] = params
            return result

        return result
