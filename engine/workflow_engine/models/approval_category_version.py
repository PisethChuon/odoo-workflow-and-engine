# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.workflow_engine.utils.bpmn_engine_parser import BpmnEngine, NODE_TYPE, ACTION_TYPE


class WorkflowApprovalCategoryVersion(models.Model):
    _name = 'workflow.approval.category.version'
    _description = 'Workflow Approval Category Version'
    _order = 'sequence desc, id desc'
    _check_company_auto = True

    def _default_bpmn(self):
        return '''<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                      xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                      xmlns:custom="http://example.com/schema/custom"
                      id="Definition"
                      targetNamespace="http://bpmn.io/schema/bpmn">
      <bpmn:process id="ApprovalProcess" isExecutable="true">
        <bpmn:startEvent id="StartEvent" name="Start"/>
        <bpmn:endEvent id="EndEvent" name="End"/>
        <bpmn:sequenceFlow id="flow1" sourceRef="StartEvent" targetRef="EndEvent"/>
      </bpmn:process>
    </bpmn:definitions>'''

    name = fields.Char(string='Version Name', required=True, help='Name of the version (e.g., v1, v2, Draft, Final)', copy=False, 
                       default=lambda s: s.env._('New'))
    category_id = fields.Many2one('workflow.approval.category', string='Category', required=True, ondelete='cascade')
    res_model_id = fields.Many2one(related='category_id.res_model', store=True)
    res_model_name = fields.Char(related='category_id.res_model_name', store=True)
    sequence = fields.Integer(default=10, help='Used for ordering versions', copy=False)
    is_active = fields.Boolean(string='Active Version', default=False, copy=False)
    is_locked = fields.Boolean(string='Locked', default=False, help='Prevent further edits to BPMN XML once locked.', copy=False)
    request_owner_notification_template_id = fields.Many2one(
        'mail.template',
        string='Owner Update Email Template',
        copy=False,
        help='Optional category-specific template for built-in owner update emails. Leave empty to use the workflow default template.',
    )
    change_log = fields.Text(string='Change Log', help='Summary of changes made in this version.', copy=False)
    bpmn_xml = fields.Text(string='BPMN XML', required=True, default=lambda self: self._default_bpmn())
    title = fields.Char(string='Title', help='Title displayed on forms related to this workflow.')
    is_child_approval = fields.Boolean(string='Child Approval', default=False, help='Indicates if this workflow is a child approval process.', copy=False)

    # stage_ids = fields.One2many('workflow.category.stage', 'category_id', string="Stages")
    meta_task_ids = fields.One2many('workflow.category.version.meta.task', 'version_id', string='Meta Task')

    company_id = fields.Many2one(
        'res.company', string='Company', index=True, required=True,
        default=lambda self: self.env.company)
    
    
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends('name', 'title')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.title}" if rec.title else rec.name

    @api.constrains('is_active', 'category_id')
    def _check_unique_active_version(self):
        for rec in self:
            if rec.is_active:
                active_count = self.search_count([
                    ('category_id', '=', rec.category_id.id),
                    ('is_active', '=', True),
                    ('id', '!=', rec.id)
                ])
                if active_count:
                    raise ValidationError(_('Only one active version is allowed per approval category.'))

    @api.constrains("request_owner_notification_template_id", "res_model_id")
    def _check_request_owner_notification_template_id(self):
        for rec in self:
            template = rec.request_owner_notification_template_id
            if (
                template
                and template.model_id
                and rec.res_model_id
                and template.model_id != rec.res_model_id
            ):
                raise ValidationError(
                    _("Owner update email templates must belong to the workflow category model.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            # Auto-generate version name if not given or set to 'New'
            if vals.get('name', 'New') == 'New' and vals.get('category_id'):
                existing_versions = self.search_count([('category_id', '=', vals['category_id'])])
                vals['name'] = f"v{existing_versions + 1}"

            # Deactivate other versions if this one is set to active
            if vals.get('is_active') and vals.get('category_id'):
                self._deactivate_previous_versions(vals['category_id'])

            # Create record (defer save until loop ends)
            record = super(WorkflowApprovalCategoryVersion, self).create([vals])
            records += record

            # Update the active_version_id on the category if needed
            if vals.get('is_active'):
                record.category_id.active_version_id = record

            if 'bpmn_xml' in vals:
                # MALINKA
                #
                # record was created from vals, so they must be identitical
                # that is why no need to compare here
                # if vals.get('bpmn_xml', False) != record.bpmn_xml:
                record.sync_meta_from_bpmn(vals['bpmn_xml'])

        return records

    def write(self, vals):
        if 'is_active' in vals and vals['is_active']:
            for version in self:
                version._deactivate_previous_versions(version.category_id.id)
        if (
            'is_locked' in vals
            and vals['is_locked']
            and not self.env.context.get('allow_version_lock_write')
        ):
            raise ValidationError(_("You cannot lock the version from here. Use the Lock Version button."))

        if 'bpmn_xml' in vals:
            # If BPMN XML is updated, extract and store metadata again
            for record in self:
                if vals.get('bpmn_xml', False) != record.bpmn_xml:
                    self.sync_meta_from_bpmn(vals['bpmn_xml'])

        return super().write(vals)

    def _get_user_action_by_node_id(self, node_id):
        action_ids = self.meta_task_ids.mapped('meta_action_ids')
        # return a.filtered(
        #     lambda a: a.source_id == node_id and a.flow_type in ['userAction']
        # )        
        return action_ids.filtered(
            lambda a: a.source_id == node_id
            and (
                BpmnEngine.is_user_action(a.source_node_type, a.flow_type)
                or (
                    not a.flow_type
                    and a.source_node_type in (
                        NODE_TYPE["USER_TASK"],
                        NODE_TYPE["MANUAL_TASK"],
                        NODE_TYPE["TASK"],
                    )
                )
            )
        )

    def _store_metadata(self, metadata):
        task_model = self.env['workflow.category.version.meta.task']
        # Store tasks
        self.meta_task_ids.unlink()
        for task_data in metadata['tasks']:
            task_data['version_id'] = self.id
            task_data['attr_label'] = task_data.get('attr_label') or task_data.get('name', '')
            task_model.create(task_data)

        # Store sequence flows
        # self.meta_flow_ids.unlink()
        # for flow_data in metadata['sequence_flows']:
        #     flow_data['version_id'] = self.id
        #     flow_data['attr_label'] = flow_data.get('attr_label') or flow_data.get('name', '')
        #     flow_model.create(flow_data)

    def sync_meta_from_bpmn(self, bpmn_xml):
        self.ensure_one()
        engine = BpmnEngine(bpmn_xml)
        new_meta_tasks, new_meta_actions = engine.get_meta_tasks_and_actions()

        exiting_tasks = self.env['workflow.category.version.meta.task']
        exiting_actions = self.env['workflow.category.version.meta.task.action']

        # -------------------------
        # Sync Tasks
        # -------------------------
        existing_tasks = {t.node_id: t for t in exiting_tasks.search([('version_id', '=', self.id), ('category_id', '=', self.category_id.id)])}
        #existing_tasks = {t.node_id: t for t in exiting_tasks.search([('version_id', '=', self.id)])}
        new_task_ids = set(task['node_id'] for task in new_meta_tasks)

        # 1. Delete tasks that are removed
        for node_id, rec in existing_tasks.items():
            if node_id not in new_task_ids:
                rec.unlink()

        # 2. Update or create
        for task in new_meta_tasks:
            if task['node_id'] in existing_tasks:
                existing_task = existing_tasks[task['node_id']]
                existing_tasks[task['node_id']].write({
                    'name': task['name'],
                    'description': task['description'],
                    'node_type': task['node_type'],
                    'attr_class': task['attr_class'],
                    'attr_label': task.get('attr_label') or task.get('name', ''),
                    'element': task['element'],
                    # These domains are Studio-side metadata, not BPMN-owned fields.
                    # Preserve the saved values when the BPMN parser does not provide them.
                    'approval_group_domain': (
                        existing_task.approval_group_domain
                        or task['approval_group_domain']
                    ),
                    'notification_recipient_domain': (
                        existing_task.notification_recipient_domain
                        or task['notification_recipient_domain']
                    ),
                })
            else:
                exiting_tasks.create({
                    'version_id': self.id,
                    **{k: task[k] for k in [
                        'node_id', 'name', 'description', 'node_type', 'attr_class',
                        'attr_label', 'element', 'approval_group_domain', 'notification_recipient_domain'
                    ]}
                })

        # Rebuild map after potential changes
        meta_task_map = {t.node_id: t for t in exiting_tasks.search([('version_id', '=', self.id)])}

        # -------------------------
        # Sync Actions
        # -------------------------
        existing_actions = {(a.source_id, a.target_id): a for a in  exiting_actions.search([('version_id', '=', self.id)])}
        new_action_keys = set((a['source_id'], a['target_id']) for a in new_meta_actions)

        # 1. Delete removed flows
        for key, rec in existing_actions.items():
            if key not in new_action_keys:
                rec.unlink()

        # 2. Update or create actions
        for action in new_meta_actions:
            key = (action['source_id'], action['target_id'])
            existing_action = existing_actions.get(key)
            action_label = action.get('attr_label') or action.get('name', '')
            technical_name = (
                existing_action.name
                if existing_action and existing_action.name
                else action_label
            )
            values = {
                'name': technical_name,
                'node_id': action['node_id'],
                'source_id': action['source_id'],
                'source_name': action['source_name'],
                'source_node_type': action['source_node_type'],
                'target_id': action['target_id'],
                'target_name': action['target_name'],
                'target_node_type': action['target_node_type'],
                'attr_label': action_label,
                'attr_class': action['attr_class'],
                'invisible_domain': (
                    existing_action.invisible_domain if existing_action else ''
                ) or action['invisible_domain'],
                'flow_type': action['flow_type'],
            }
            parsed_domain = action.get('domain', '')
            if existing_action:
                values['domain'] = existing_action.domain or parsed_domain or ''
            else:
                values['domain'] = parsed_domain or ''

            if existing_action:
                existing_action.write(values)
            else:
                exiting_actions.create({
                    **values,
                    'version_id': self.id,
                    'meta_task_id': meta_task_map.get(action['source_id'], False).id
                })

    def action_sync_bpmn_metadata(self):
        """Public sync action used by runtime tests and server actions."""
        for version in self:
            version.sync_meta_from_bpmn(version.bpmn_xml or version._default_bpmn())
        return True

    @api.model
    def workflow_studio_validate_domain_expression(
        self,
        res_model_name,
        domain_expression,
        validation_scope=False,
        request_model_name=False,
    ):
        """
        Runtime-safe domain validator.

        Studio extends this method with designer access checks and richer UI
        hints, but engine constraints also need validation before Studio is
        loaded during module tests and standalone engine installs.
        """
        model_name = (res_model_name or "").strip()
        if not model_name:
            return {"valid": False, "error": _("Missing target model.")}

        normalized_scope = (validation_scope or "").strip()
        base_scope = {
            "assignment_users_routing": "assignment_users",
            "request_scope_routing": "request_scope",
        }.get(normalized_scope, normalized_scope)
        is_routing_scope = normalized_scope in {"assignment_users_routing", "request_scope_routing"}
        domain_service = self.env["workflow.engine.assignment.domain.service"].sudo()
        expression = (
            domain_service._normalize_routing_domain_text(domain_expression)
            if is_routing_scope
            else (domain_expression or "").strip() or "[]"
        )
        try:
            Model = self.env[model_name].sudo()
        except KeyError:
            return {"valid": False, "error": _("Unknown target model: %s", model_name)}

        sample_record = Model.search([], limit=1) or Model.new({})
        request_sample_record = sample_record
        request_model = (request_model_name or "").strip()
        if request_model:
            try:
                RequestModel = self.env[request_model].sudo()
            except KeyError:
                return {"valid": False, "error": _("Unknown request model: %s", request_model)}
            request_sample_record = RequestModel.search([], limit=1) or RequestModel.new({})

        service = self.env["workflow.engine.field.rule.service"].sudo()
        if is_routing_scope:
            classification = domain_service._classify_routing_domain_literal(expression)
            state = classification.get("domain_state") or "active_valid"
            if state in {"ignored_blank", "ignored_empty", "always_true", "always_false"}:
                warning = ""
                if state == "ignored_blank":
                    warning = _(
                        "Blank routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
                    )
                elif state == "ignored_empty":
                    warning = _(
                        "Empty [] routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
                    )
                return {
                    "valid": True,
                    "error": "",
                    "warning": warning,
                    "ignored": state.startswith("ignored"),
                    "domain_state": state,
                }
        try:
            eval_ctx = service._runtime_eval_context(
                target_record=sample_record,
                request_record=request_sample_record,
                user=self.env.user,
            )
            domain = service._safe_eval_domain_expression(
                expression,
                eval_ctx.get("safe_symbols") or {},
            )
            if isinstance(domain, bool):
                return {
                    "valid": True,
                    "error": "",
                    "warning": "",
                    "ignored": False,
                    "domain_state": "active_valid",
                }
            if domain is False:
                domain = []
            domain = domain_service._expand_domain_symbol_values(
                list(domain or []),
                eval_ctx.get("safe_symbols") or {},
            )
            if base_scope not in {"field_modifiers", "request_scope"}:
                Model.search(domain or [], limit=1)
        except Exception as exc:
            if is_routing_scope:
                return {
                    "valid": True,
                    "error": "",
                    "warning": str(exc)
                    or _(
                        "Invalid routing domains are ignored. Use [(1, '=', 1)] for always true or [(0, '=', 1)] for always false."
                    ),
                    "ignored": True,
                    "domain_state": "ignored_invalid",
                }
            return {"valid": False, "error": str(exc)}

        return {
            "valid": True,
            "error": "",
            "warning": "",
            "ignored": False,
            "domain_state": "active_valid",
        }

    def _deactivate_previous_versions(self, category_id):
        self.search([('category_id', '=', category_id), ('is_active', '=', True)]).write({'is_active': False})

    def action_set_active(self):
        for version in self:
            # version._deactivate_previous_versions(version.category_id.id)
            # version.is_active = True
            # version.category_id.active_version_id = version.id
            version._deactivate_previous_versions(version.category_id.id)
            version.is_active = True
            version.category_id.active_version_id = version.id

    def action_lock_version(self):
        for version in self:
            if not version.bpmn_xml:
                raise ValidationError(_('BPMN XML must be filled in before locking.'))
            version.with_context(allow_version_lock_write=True).write({'is_locked': True})

    def action_open_version_form(self):
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'workflow.approval.category.version',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


    @api.model
    def get_called_workflows(self, workflow_id):
        """
        Return all called workflows (childs) as JSON-safe list.
        Used by BPMN viewer via RPC call.
        """
        if not workflow_id:
            return []

        WorkflowMap = self.env["workflow.category.version.meta.task.workflow.map"].sudo()
        mappings = WorkflowMap.search([("workflow_id", "=", workflow_id)])

        sub_workflows = self.env["workflow.approval.category.version"].sudo().search([
            ("id", "in", mappings.mapped("called_workflow_id").ids)
        ])

        return [
            {
                "id": wf.id,
                "name": wf.display_name,
                "version": wf.name,
                "category_id": wf.category_id.id if wf.category_id else False,
                "bpmn_xml": wf.bpmn_xml,
            }
            for wf in sub_workflows
        ]
