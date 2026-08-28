from odoo import _, api, fields, models
from odoo.exceptions import UserError
from collections.abc import Mapping

WORKFLOW_CHILD_REQUEST_READER_RULE_DOMAIN = (
    "['|', '|', '|', '|', '|', "
    "'|', '|', '|', ('x_approval_base_id.category_id.zero_trust_enforced', '=', False), "
    "('x_approval_base_id.category_id.allowed_user_ids', 'in', [user.id]), "
    "('x_approval_base_id.category_id.allowed_group_ids', 'in', user.all_group_ids.ids), "
    "'&', ('x_approval_base_id.category_id.allowed_department_ids', '!=', False), "
    "('x_approval_base_id.category_id.allowed_department_ids', 'in', [user.department_id.id or 0]), "
    "'&', ('x_approval_base_id.category_id.allow_requester_read', '=', True), "
    "'|', ('x_approval_base_id.create_uid', '=', user.id), "
    "('x_approval_base_id.request_owner_id', '=', user.id), "
    "'&', ('x_approval_base_id.category_id.allow_manager_access', '=', True), "
    "('x_approval_base_id.manager_user_id', '=', user.id), "
    "('x_approval_base_id.visibility_scope_user_ids', 'in', [user.id]), "
    "('x_approval_base_id.visibility_scope_group_ids', 'in', user.all_group_ids.ids), "
    "('x_approval_base_id.message_partner_ids.user_ids', '=', user.id)]"
)


class ApprovalMixinModel(models.Model):
    _inherit = 'ir.model'
    _order = 'is_mail_thread DESC, name ASC'

    is_approval = fields.Boolean(
        string="Has Approval", default=False,
    )

    def write(self, vals):
        if self and ('is_approval' in vals):
            if any(rec.state != 'manual' for rec in self):
                raise UserError(_('Only custom models can be modified.'))
            if 'is_approval' in vals and any(rec.is_approval > vals['is_approval'] for rec in self):
                raise UserError(_('Field "Approval" cannot be changed to "False".'))
            res = super(ApprovalMixinModel, self).write(vals)
            self.env.flush_all()
            # setup models; this reloads custom models in registry
            model_names = self.mapped('model')
            self.pool._setup_models__(self.env.cr, model_names)
            # update database schema of models
            models = self.pool.descendants(self.mapped('model'), '_inherits')
            self.pool.init_models(self.env.cr, models, dict(self.env.context, update_custom_fields=True))
        else:
            res = super(ApprovalMixinModel, self).write(vals)
        return res

    def _reflect_model_params(self, model):
        vals = super(ApprovalMixinModel, self)._reflect_model_params(model)
        vals['is_approval'] = isinstance(model, self.pool['approval.child.mixin'])
        return vals

    @api.model
    def _instanciate_attrs(self, model_data):
        attrs = super()._instanciate_attrs(model_data)
        if model_data.get('is_approval') and (attrs.get("_name") 
                                              not in ("approval.base.mixin", "approval.child.mixin", 
                                                      "workflow.base.approval.request")):
            # 1) Ensure classical inheritance includes your mixin
            parent_inherit = attrs.get('_inherit') or []
            if isinstance(parent_inherit, str):
                parent_inherit = [parent_inherit]
            elif isinstance(parent_inherit, tuple):
                parent_inherit = list(parent_inherit)
            elif not isinstance(parent_inherit, list):
                parent_inherit = list(parent_inherit) if parent_inherit else []

            # approval models must provide mail.thread APIs for chatter/discuss routes
            required_inherits = [
                'approval.child.mixin',
                'mail.thread',
                'mail.activity.mixin',
            ]
            for inherit_model in required_inherits:
                if inherit_model not in parent_inherit:
                    parent_inherit.append(inherit_model)
            attrs['_inherit'] = parent_inherit

            # 2) Ensure _inherits is a dict and add delegation to base request
            existing = attrs.get('_inherits') or {}
            if isinstance(existing, Mapping):
                new_inherits = dict(existing)  # copy
            elif isinstance(existing, (list, tuple)):
                # extremely defensive: convert legacy list of tuples -> dict
                new_inherits = dict(existing)
            elif not existing:
                new_inherits = {}
            else:
                # fallback: do not keep invalid content
                new_inherits = {}

            # Your FK field name on x_medical_request:
            fk_field = 'x_approval_base_id'
            new_inherits['workflow.base.approval.request'] = fk_field
            attrs['_inherits'] = new_inherits
        return attrs

    def _get_definitions(self, model_names):
        model_definitions = super()._get_definitions(model_names)
        for model_name, model_definition in model_definitions.items():
            if isinstance(self.env[model_name], self.env.registry['approval.mixin']):
                model_definition["has_approvals"] = True
        return model_definitions

    def _get_model_definitions(self, model_names_to_fetch):
        model_definitions = super()._get_model_definitions(model_names_to_fetch)
        for model_name, model_definition in model_definitions.items():
            if isinstance(self.env[model_name], self.env.registry['approval.mixin']):
                model_definition["has_approvals"] = True
        return model_definitions

    def _workflow_is_child_request_model(self):
        self.ensure_one()
        model_name = (self.model or "").strip()
        if not model_name or model_name == "workflow.base.approval.request":
            return False
        if self.is_approval:
            return True
        model = self.env.get(model_name)
        if not model or getattr(model, "_abstract", False) or getattr(model, "_transient", False):
            return False
        link_field = model._fields.get("x_approval_base_id")
        if not link_field:
            return False
        if getattr(link_field, "type", None) != "many2one":
            return False
        return getattr(link_field, "comodel_name", None) == "workflow.base.approval.request"

    def _workflow_sync_child_request_reader_access_rights(self):
        self.ensure_one()
        if not self._workflow_is_child_request_model():
            return False
        group = self.env.ref("workflow_engine.group_workflow_request_reader", raise_if_not_found=False)
        if not group:
            return False
        access_model = self.env["ir.model.access"].sudo()
        values = {
            "name": f"{self.name} {group.name}",
            "model_id": self.id,
            "group_id": group.id,
            "perm_read": True,
            "perm_write": False,
            "perm_create": False,
            "perm_unlink": False,
        }
        existing = access_model.search(
            [("model_id", "=", self.id), ("group_id", "=", group.id)]
        )
        if existing:
            existing.write(values)
        else:
            access_model.create(values)
        return True

    def _workflow_sync_child_request_reader_record_rule(self):
        self.ensure_one()
        if not self._workflow_is_child_request_model():
            return False
        group = self.env.ref("workflow_engine.group_workflow_request_reader", raise_if_not_found=False)
        if not group:
            return False
        rule_model = self.env["ir.rule"].sudo()
        rule_name = f"{self.name}: Request Reader Rule"
        values = {
            "name": rule_name,
            "model_id": self.id,
            "domain_force": WORKFLOW_CHILD_REQUEST_READER_RULE_DOMAIN,
            "groups": [(6, 0, [group.id])],
            "perm_read": True,
            "perm_write": False,
            "perm_create": False,
            "perm_unlink": False,
        }
        existing = rule_model.search(
            [
                ("model_id", "=", self.id),
                ("groups", "in", [group.id]),
                ("domain_force", "=", WORKFLOW_CHILD_REQUEST_READER_RULE_DOMAIN),
            ]
        )
        if not existing:
            existing = rule_model.search(
                [
                    ("model_id", "=", self.id),
                    ("name", "=", rule_name),
                    ("groups", "in", [group.id]),
                ]
            )
        if existing:
            existing.write(values)
        else:
            rule_model.create(values)
        return True

    def _workflow_sync_child_request_reader_security(self):
        synced = self.browse()
        for model in self:
            synced_access = model._workflow_sync_child_request_reader_access_rights()
            synced_rule = model._workflow_sync_child_request_reader_record_rule()
            if synced_access or synced_rule:
                synced |= model
        return synced

    @api.model
    def workflow_sync_all_child_request_reader_security(self, model_names=None):
        model_names = [name for name in (model_names or []) if name]
        if model_names:
            models_to_sync = self.sudo().search([("model", "in", list(set(model_names)))])
        else:
            models_to_sync = self.env["workflow.approval.category"].sudo().mapped("res_model")
        synced = models_to_sync._workflow_sync_child_request_reader_security()
        return {
            "status": "ok",
            "synced_model_count": len(synced),
            "model_names": synced.mapped("model"),
        }
