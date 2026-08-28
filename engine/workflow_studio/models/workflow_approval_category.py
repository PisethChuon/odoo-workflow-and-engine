from odoo import _, models, api
from odoo.exceptions import AccessError, UserError


from ..utils.sequence_code import make_sequence_code, unique_sequence_code

class WorkflowApprovalCategory(models.Model):
    _inherit = "workflow.approval.category"

    @api.model_create_multi
    def create(self, vals_list):
        # Work on a copy to avoid side effects
        vals_list = [dict(vals) for vals in vals_list]

        for vals in vals_list:
            if not vals.get("automated_sequence"):
                continue

            # If sequence already set, don't recreate
            if vals.get("sequence_id"):
                continue

            # 1) Determine base label for code generation
            # Prefer explicit name, else fallback to res_model display name if available
            base_name = (vals.get("name") or "").strip()

            # If name not provided but res_model is, use ir.model name (display name)
            if not base_name and vals.get("res_model"):
                ir_model = self.env["ir.model"].sudo().browse(vals["res_model"])
                if ir_model.exists():
                    base_name = (ir_model.name or "").strip()

            # 2) Determine sequence_code
            # If user provided it, keep it (but normalize + ensure uniqueness)
            if vals.get("sequence_code"):
                base_code = (vals["sequence_code"] or "").strip().upper()
                base_code = (base_code[:4] or make_sequence_code(base_name))
            else:
                base_code = make_sequence_code(base_name)

            code = unique_sequence_code(
                self.env,
                base_code,
                model_name="workflow.approval.category",
                field_name="sequence_code",
            )
            vals["sequence_code"] = code

            # 3) Create ir.sequence
            seq = self.env["ir.sequence"].sudo().create({
                "name": _("Sequence %(code)s", code=code),
                "padding": 5,
                "prefix": code,
                "company_id": vals.get("company_id"),
            })
            vals["sequence_id"] = seq.id

        return super().create(vals_list)

    def _ensure_workflow_studio_admin(self):
        if not (
            self.env.user.has_group("workflow_engine.group_workflow_approval_admin")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Only Workflow Approval Admin users can design workflows."))

    def action_open_workflow_studio_entry(self):
        """Open Studio from category list header.

        - If a category with model exists: open Studio directly.
        - If none exists: open quick-start wizard to create model/category/version.
        """
        self._ensure_workflow_studio_admin()

        category = self.filtered("res_model")[:1]
        if not category and not self.env.context.get("workflow_studio_skip_global_lookup"):
            category = self.env["workflow.approval.category"].sudo().search(
                [("res_model", "!=", False)],
                order="id desc",
                limit=1,
            )
        if category:
            return category.action_activate_workflow_studio()

        return self.env.ref(
            "workflow_studio.action_workflow_studio_quick_start_wizard"
        ).sudo().read()[0]

    def action_activate_workflow_studio(self):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        if not self.res_model:
            raise UserError(_("Please set a target model before opening Workflow Studio."))

        context = dict(self.env.context)
        version_id = False
        candidate_version_ids = [context.get("workflow_version_id")]
        if context.get("active_model") == "workflow.approval.category.version":
            active_id = context.get("active_id")
            if not active_id:
                active_ids = context.get("active_ids") or []
                if isinstance(active_ids, (list, tuple)) and active_ids:
                    active_id = active_ids[0]
            candidate_version_ids.append(active_id)
        for candidate in candidate_version_ids:
            try:
                candidate = int(candidate or 0)
            except (TypeError, ValueError):
                candidate = 0
            if not candidate:
                continue
            version = self.env["workflow.approval.category.version"].sudo().browse(candidate)
            if version.exists() and version.category_id.id == self.id:
                version_id = version.id
                break
        if not version_id and self.active_version_id:
            version_id = self.active_version_id.id
        context.update(
            {
                "active_id": self.id,
                "active_ids": [self.id],
                "active_model": self._name,
                "workflow_category_id": self.id,
            }
        )
        if version_id:
            context["workflow_version_id"] = version_id

        return {
            "type": "ir.actions.client",
            "tag": "workflow_studio.open_workflow_studio",
            "target": "current",
            "params": {
                "model": self.res_model.model,
                "name": self.res_model.name or self.name,
                "context": context,
                "editor_tab": "bpmn",
            },
        }

    def action_open_bpmn_designer(self):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        if not self.active_version_id:
            raise UserError(_("Please create a workflow version before opening the BPMN designer."))

        context = dict(self.env.context)
        context.update(
            {
                "active_id": self.id,
                "active_model": self._name,
            }
        )

        return {
            "type": "ir.actions.client",
            "name": _("BPMN Designer"),
            "tag": "workflow_bpmn_view",
            "target": "current",
            "context": context,
        }

    def workflow_studio_create_initial_version(self, values=False):
        self.ensure_one()
        self._ensure_workflow_studio_admin()

        if not self.res_model:
            raise UserError(_("Please set a target model before creating a workflow version."))

        values = values or {}
        title = (values.get("title") or "").strip()
        sequence = max(self.version_ids.mapped("sequence") or [0]) + 10
        version_vals = {
            "category_id": self.id,
            "name": "New",
            "title": title,
            "sequence": sequence or 10,
            "is_active": False,
            "is_locked": False,
            "is_published": False,
            "deployed_at": False,
            "published_at": False,
        }
        version = self.env["workflow.approval.category.version"].sudo().create(version_vals)
        return {
            "version_id": version.id,
            "version_control": version._workflow_studio_build_version_control(self.sudo()),
        }
