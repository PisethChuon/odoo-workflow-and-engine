# -*- coding: utf-8 -*-
import unicodedata
import uuid
import re

import xml.etree.ElementTree as ET

from odoo import api, fields, models, _, Command
from odoo.exceptions import ValidationError
from odoo.addons.workflow_engine.models.ir_model import (
    WORKFLOW_CHILD_REQUEST_READER_RULE_DOMAIN,
)

OPTIONS_WL = [
    'use_mail',          # add mail_thread to record
    'use_active',        # allows to archive records (active field)
    'use_responsible',   # add user field
    'use_partner',       # adds partner and related phone and email fields
    'use_company',       # add company field and corresponding access rules
    'use_notes',         # html note field
    'use_date',          # date field
    'use_double_dates',  # date start and date begin
    'use_value',         # value and currency
    'use_image',         # image field
    'use_sequence',      # allows to order records (sequence field)
    'lines',             # create a default One2Many targeting a generated lines models
    'use_stages',        # add stages and stage model to record (kanban)
    'use_tags'           # add tags and tags model to record (kanban)
]

STUDIO_TRANSIENT_OPTION = "is_transient"
STUDIO_APPROVAL_OPTION = "has_approval"

STUDIO_CUSTOMIZATION_MODULES = {"workflow_studio_customization"}
STUDIO_APPROVAL_READER_RULE_DOMAIN = WORKFLOW_CHILD_REQUEST_READER_RULE_DOMAIN


def sanitize_for_xmlid(s):
    """ Transforms a string to a name suitable for use in an xmlid.
        Strips leading and trailing spaces, converts unicode chars to ascii,
        lowers all chars, replaces spaces with underscores and truncates the
        resulting string to 20 characters.

        :type s: str
        :rtype: str
    """
    uni = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')

    slug_str = re.sub(r'\W', ' ', uni).strip().lower()
    slug_str = re.sub(r'[-\s]+', '_', slug_str)
    slug_str = normalize_studio_identifier(slug_str)
    return slug_str[:20]


def normalize_studio_identifier(value):
    if not value:
        return value
    return value.replace('odoo_studio', 'workflow_studio').replace('web_studio', 'workflow_studio')


class Base(models.AbstractModel):
    _inherit = 'base'

    def create_studio_model_data(self, name):
        """ We want to keep track of created records with studio
            (ex: model, field, view, action, menu, etc.).
            An ir.model.data is created whenever a record of one of these models
            is created, tagged with studio.
        """
        IrModelData = self.env['ir.model.data']

        # Check if there is already an ir.model.data for the given resource
        data = IrModelData.search([
            ('model', '=', self._name), ('res_id', '=', self.id)
        ])
        if data:
            for imd in data.filtered(lambda rec: rec.module in STUDIO_CUSTOMIZATION_MODULES and rec.name):
                normalized_name = normalize_studio_identifier(imd.name)
                if normalized_name != imd.name:
                    duplicate = IrModelData.search_count([
                        ('module', '=', imd.module),
                        ('name', '=', normalized_name),
                        ('id', '!=', imd.id),
                    ])
                    if not duplicate:
                        imd.name = normalized_name
            data.write({})  # force a write to set the 'studio' and 'noupdate' flags to True
        else:
            module = self.env['ir.module.module'].get_studio_module()
            IrModelData.create({
                'name': '%s_%s' % (sanitize_for_xmlid(name or 'False'), uuid.uuid4()),
                'model': self._name,
                'res_id': self.id,
                'module': module.name,
            })

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        in_studio = self.env.context.get("workflow_studio")
        if in_studio and self.env.user.has_group("base.group_system"):
            return super(Base, self.sudo()).fields_get(allfields, attributes=attributes)
        return super().fields_get(allfields, attributes=attributes)


class IrModel(models.Model):
    _name = 'ir.model'
    _inherit = ['workflow.studio.mixin', 'ir.model']

    abstract = fields.Boolean(compute='_compute_abstract',
                              store=False,
                              help="Whether this model is abstract",
                              search='_search_abstract')

    def _compute_abstract(self):
        for record in self:
            model = self.env.get(record.model)
            record.abstract = model is not None and model._abstract

    def _search_abstract(self, operator, value):
        if operator != 'in':
            return NotImplemented
        abstract_models = [
            model._name
            for model in self.env.values()
            if model._abstract
        ]
        return [('model', 'in', abstract_models)]

    @api.model
    def studio_model_create(self, name, options=()):
        """ Allow quick creation of models through Studio.

        :param name: functional name of the model (_description attribute)
        :param options: list of options that can trigger automated behaviours,
                        in the form of 'use_<behaviour>' (e.g. 'use_tags')
        :return: the main model created as well as extra models needed for the
                 requested behaviours (e.g. tag or stage models) in the form of
                 a tuple (main_model, extra_models)
        :rtype: tuple
        """
        options = set(options)
        is_transient = STUDIO_TRANSIENT_OPTION in options
        has_approval = STUDIO_APPROVAL_OPTION in options
        if is_transient and has_approval:
            raise ValidationError(
                _("Transient models cannot use workflow approvals. Disable one of these options.")
            )
        use_mail = 'use_mail' in options

        model_values = {
            'name': name,
            'model': 'x_' + sanitize_for_xmlid(name),
            'is_mail_thread': use_mail,
            'is_mail_activity': use_mail,
            'transient': is_transient,
            'field_id': [
                # Command.create({
                #     'name': 'x_name',
                #     'ttype': 'char',
                #     'required': True,
                #     'field_description': _('Description'),
                #     'translate': 'standard',
                #     'tracking': use_mail,
                # })
            ]
        }

        # now let's check other options and accumulate potential extra models (tags, stages)
        # created during this process, they will need to get their own action and menu
        # (which will be done at the controller level)
        extra_models_keys = []
        extra_models_values = []

        options.discard('use_mail')
        for option in OPTIONS_WL:
            if option in options:
                method = f'_create_option_{option}'
                model_to_create = getattr(self, method)(model_values)
                if model_to_create:
                    extra_models_keys.append(option)
                    extra_models_values.append(model_to_create)

        all_models = self.create([model_values] + extra_models_values)
        main_model, *extra_models = all_models
        extra_models_dict = dict(zip(extra_models_keys, extra_models))

        all_models._setup_access_rights()
        if has_approval:
            main_model._workflow_studio_enable_approval_features()

        for option in OPTIONS_WL:
            if option in options:
                method = f'_post_create_option_{option}'
                getattr(main_model, method, lambda m: None)(extra_models_dict.get(option))

        self.env['ir.ui.view'].create_automatic_views(main_model.model)

        ListEditableView = self.env['ir.ui.view'].with_context(list_editable="bottom")
        for extra_model in extra_models:
            ListEditableView.create_automatic_views(extra_model.model)

        models_with_menu = self.browse(
            model.id
            for key, model in extra_models_dict.items()
            if key in ('use_stages', 'use_tags')
        )
        return (main_model, models_with_menu)

    def _workflow_studio_enable_approval_features(self):
        self.ensure_one()
        if "is_approval" in self._fields and not self.is_approval:
            self.sudo().write({"is_approval": True})

        self._workflow_studio_setup_approval_access_rights()
        self._workflow_studio_setup_approval_record_rules()
        self._workflow_studio_setup_approval_form_view()
        self._workflow_studio_setup_approval_action_window()
        self._workflow_studio_setup_approval_category()

    @api.model
    def workflow_studio_sync_all_approval_security(self):
        """
        Re-sync ACL and record-rule templates for all approval-enabled Studio models.
        Safe to run repeatedly (idempotent upsert behavior).
        """
        models = self.sudo().search([("is_approval", "=", True), ("transient", "=", False)])
        synced = self.browse()
        for model in models:
            model_name = model.model or ""
            if model_name.endswith(".mixin") or model_name in ("approval.child.mixin", "approval.base.mixin"):
                continue
            model._workflow_studio_setup_approval_access_rights()
            model._workflow_studio_setup_approval_record_rules()
            synced |= model
        return {
            "status": "ok",
            "synced_model_count": len(synced),
            "model_names": synced.mapped("model"),
        }

    def _workflow_studio_setup_approval_access_rights(self):
        self.ensure_one()
        if not self._workflow_is_child_request_model():
            return False
        Access = self.env["ir.model.access"].sudo()
        # Approval-enabled models must rely on workflow approval groups, not the
        # generic Studio internal-user ACL created by `_setup_access_rights`.
        base_group_user = self.env.ref("base.group_user", raise_if_not_found=False)
        if base_group_user:
            Access.search(
                [("model_id", "=", self.id), ("group_id", "=", base_group_user.id)]
            ).unlink()

        self._workflow_sync_child_request_reader_access_rights()
        groups = [
            ("workflow_engine.group_workflow_approval_user", (True, True, True, False)),
            ("workflow_engine.group_workflow_approval_admin", (True, True, True, True)),
        ]
        for xmlid, (perm_read, perm_write, perm_create, perm_unlink) in groups:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            existing = Access.search(
                [("model_id", "=", self.id), ("group_id", "=", group.id)],
                limit=1,
            )
            if existing:
                continue
            Access.create(
                {
                    "name": f"{self.name} {group.name}",
                    "model_id": self.id,
                    "group_id": group.id,
                    "perm_read": perm_read,
                    "perm_write": perm_write,
                    "perm_create": perm_create,
                    "perm_unlink": perm_unlink,
                }
            )
        return True

    def _workflow_studio_setup_approval_record_rules(self):
        self.ensure_one()
        if not self._workflow_is_child_request_model():
            return False
        Rule = self.env["ir.rule"].sudo()
        group_user = self.env.ref("workflow_engine.group_workflow_approval_user", raise_if_not_found=False)
        # group_manager = self.env.ref(
        #     "workflow_engine.group_workflow_approval_manager", raise_if_not_found=False
        # )
        group_admin = self.env.ref("workflow_engine.group_workflow_approval_admin", raise_if_not_found=False)
        group_system = self.env.ref("base.group_system", raise_if_not_found=False)

        self._workflow_sync_child_request_reader_record_rule()
        definitions = [
            {
                "name": f"{self.name}: Request Owner Rule",
                "domain_force": "['|', ('x_approval_base_id.create_uid', '=', user.id), ('x_approval_base_id.request_owner_id', '=', user.id)]",
                "groups": [group_user.id] if group_user else [],
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            },
            {
                "name": f"{self.name}: Approver Rule",
                "domain_force": "[('x_approval_base_id.approver_ids.user_id', 'in', [user.id])]",
                "groups": [
                    group_id
                    for group_id in [
                        group_user.id if group_user else False,
                        # group_manager.id if group_manager else False,
                    ]
                    if group_id
                ],
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": False,
            },
            {
                "name": f"{self.name}: Admin Rule",
                "domain_force": "[(1, '=', 1)]",
                "groups": [
                    group_id
                    for group_id in [group_admin.id if group_admin else False, group_system.id if group_system else False]
                    if group_id
                ],
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            },
        ]
        for definition in definitions:
            if not definition["groups"]:
                continue
            values = {
                "name": definition["name"],
                "model_id": self.id,
                "domain_force": definition["domain_force"],
                "groups": [(6, 0, definition["groups"])],
                "perm_read": definition["perm_read"],
                "perm_write": definition["perm_write"],
                "perm_create": definition["perm_create"],
                "perm_unlink": definition["perm_unlink"],
            }
            existing = Rule.search([("model_id", "=", self.id), ("name", "=", definition["name"])])
            if existing:
                existing.write(values)
            else:
                Rule.create(values)
        return True

    def _workflow_studio_setup_approval_form_view(self):
        self.ensure_one()
        View = self.env["ir.ui.view"].sudo()
        base_view = self.env.ref(
            "workflow_engine.approval_base_request_view_form",
            raise_if_not_found=False
        )
        if not base_view:
            return
        existing = View.search(
            [
                ("model", "=", self.model),
                ("inherit_id", "=", base_view.id),
                ("type", "=", "form"),
                ("mode", "=", "primary"),
            ],
            limit=1,
        )
        if existing:
            return

        FORM_ARCH = """
        <data>
          <group name="request_main" position="inside"></group>
        </data>
        """.strip()
        approval_view = View.create(
            {
                "name": f"{self.model}.workflow.approval.form.primary",
                "model": self.model,
                "type": "form",
                "inherit_id": base_view.id,
                "mode": "primary",
                "priority": 99,
                "arch_base": FORM_ARCH,
            }
        )
        action_model = self.env["ir.actions.act_window"].sudo()
        action = action_model.search([("res_model", "=", self.model)], limit=1)
        if action:
            view_mode = action.view_mode or ""
            if "form" not in view_mode.split(","):
                action.view_mode = (view_mode + ",form").strip(",")
            views = list(action.views or [])
            views = [v for v in views if v[1] != "form"]
            views.insert(0, (approval_view.id, "form"))
            action.views = views

    def _workflow_studio_setup_approval_action_window(self):
        self.ensure_one()
        Action = self.env["ir.actions.act_window"].sudo()
        existing = Action.search([("res_model", "=", self.model)], limit=1)
        if existing:
            return existing
        return self.sudo()._create_default_action(self.name)

    def _workflow_studio_setup_approval_category(self):
        self.ensure_one()
        Category = self.env["workflow.approval.category"].sudo()
        Version = self.env["workflow.approval.category.version"].sudo()

        category = Category.search([("res_model", "=", self.id)], limit=1)
        if not category:
            category = Category.create(
                {
                    "name": self.name,
                    'automated_sequence': True,
                    "res_model": self.id,
                }
            )
        elif not category.res_model:
            category.write({"res_model": self.id})

        if not category.version_ids:
            sequence = max(category.version_ids.mapped("sequence") or [0]) + 10
            Version.create(
                {
                    "category_id": category.id,
                    "name": "v1",
                    "title": self.name,
                    "sequence": sequence or 10,
                    "is_active": True,
                    "is_locked": False,
                    "is_published": False,
                }
            )

    @api.model
    def name_create(self, name):
        if self.env.context.get('workflow_studio'):
            (main_model, _) = self.studio_model_create(name)
            return main_model.id, main_model.display_name
        return super().name_create(name)

    def _create_option_lines(self, model_vals):
        """ Creates a new model (with sequence and description fields) and a
            one2many field pointing to that model.
        """
        # create the Line model
        line_model_values, field_values = self._values_lines(model_vals.get('model'))

        model_vals['field_id'].append(
            Command.create(field_values)
        )
        return line_model_values

    def _setup_one2many_lines(self, one2many_name=None):
        # create the Line model
        model_values, field_values = self._values_lines(self.model, one2many_name)
        line_model = self.create(model_values)
        line_model._setup_access_rights()
        self.env['ir.ui.view'].create_automatic_views(line_model.model)
        field_values['model_id'] = self.id
        return self.env['ir.model.fields'].create(field_values)

    def _values_lines(self, model_name, one2many_name=None):
        """ Creates a new model (with sequence and description fields) and a
            one2many field pointing to that model.
        """
        # create the Line model
        model_table = model_name.replace('.', '_')
        if not self._is_manual_name(model_table):
            model_table = 'x_' + model_table
        model_line_name = model_table[2:] + '_line'
        model_line_model = model_table + '_line_' + uuid.uuid4().hex[:5]
        relation_field_name = model_table + '_id'
        line_model_values = {
            'name': model_line_name,
            'model': model_line_model,
            'field_id': [
                Command.create({
                    'name': 'x_workflow_studio_sequence',
                    'ttype': 'integer',
                    'field_description': _('Sequence'),
                }),
                Command.create({
                    'name': 'x_name',
                    'ttype': 'char',
                    'required': True,
                    'field_description': _('Description'),
                    'translate': 'standard',
                }),
                Command.create({
                    'name': relation_field_name,
                    'ttype': 'many2one',
                    'relation': model_name,
                }),
            ],
        }
        field_values = {
            'name': one2many_name or model_table + '_line_ids_' + uuid.uuid4().hex[:5],
            'ttype': 'one2many',
            'relation': model_line_model,
            'relation_field': relation_field_name,
            'field_description': _('New Lines'),
        }
        return line_model_values, field_values

    def _create_option_use_active(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_active',  # can't use x_studio_active as not supported by ORM
                'ttype': 'boolean',
                'field_description': _('Active'),
                'tracking': model_vals.get('is_mail_thread'),
            })
        )

    def _post_create_option_use_active(self, _model):
        self.env['ir.default'].set(self.model, 'x_active', True)

    def _create_option_use_sequence(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_sequence',
                'ttype': 'integer',
                'field_description': _('Sequence'),
                'copied': True,
            })
        )
        model_vals['order'] = 'x_workflow_studio_sequence asc, id asc'

    def _post_create_option_use_sequence(self, _model):
        self.env['ir.default'].set(self.model, 'x_workflow_studio_sequence', 10)

    def _create_option_use_responsible(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_user_id',
                'ttype': 'many2one',
                'relation': 'res.users',
                'domain': "[('share', '=', False)]",
                'field_description': _('Responsible'),
                'copied': True,
                'tracking': model_vals.get('is_mail_thread'),
            })
        )

    def _create_option_use_partner(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_partner_id',
                'ttype': 'many2one',
                'relation': 'res.partner',
                'field_description': _('Contact'),
                'copied': True,
                'tracking': model_vals.get('is_mail_thread'),
            })
        )
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_partner_phone',
                'ttype': 'char',
                'related': 'x_workflow_studio_partner_id.phone',
                'field_description': _('Phone'),
            })
        )
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_partner_email',
                'ttype': 'char',
                'related': 'x_workflow_studio_partner_id.email',
                'field_description': _('Email'),
            })
        )

    def _create_option_use_company(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_company_id',
                'ttype': 'many2one',
                'relation': 'res.company',
                'field_description': _('Company'),
                'copied': True,
                'tracking': model_vals.get('is_mail_thread'),
            })
        )

    def _post_create_option_use_company(self, _model):
        # generate default for each company (note: also done when creating a new company)
        self.env['ir.rule'].create({
            'name': '%s - Multi-Company' % self.name,
            'model_id': self.id,
            'domain_force': "['|', ('x_workflow_studio_company_id', '=', False), ('x_workflow_studio_company_id', 'in', company_ids)]"
        })
        for company in self.env['res.company'].sudo().search([]):
            self.env['ir.default'].set(self.model, 'x_workflow_studio_company_id', company.id, company_id=company.id)

    def _create_option_use_notes(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_notes',
                'ttype': 'html',
                'field_description': _('Notes'),
                'copied': True,
            })
        )

    def _create_option_use_date(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_date',
                'ttype': 'date',
                'field_description': _('Date'),
                'copied': True,
            })
        )

    def _create_option_use_double_dates(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_date_stop',
                'ttype': 'datetime',
                'field_description': _('End Date'),
                'copied': True,
            })
        )
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_date_start',
                'ttype': 'datetime',
                'field_description': _('Start Date'),
                'copied': True,
            })
        )

    def _create_option_use_value(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_currency_id',
                'ttype': 'many2one',
                'relation': 'res.currency',
                'field_description': _('Currency'),
                'copied': True,
            })
        )
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_value',
                'ttype': 'monetary',
                'currency_field': 'x_workflow_studio_currency_id',
                'field_description': _('Value'),
                'copied': True,
                'tracking': model_vals.get('is_mail_thread'),
            })
        )

    def _post_create_option_use_value(self, _model):
        for company in self.env['res.company'].sudo().search([]):
            self.env['ir.default'].set(self.model, 'x_workflow_studio_currency_id', company.currency_id.id, company_id=company.id)

    def _create_option_use_image(self, model_vals):
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_image',
                'ttype': 'binary',
                'field_description': _('Image'),
                'copied': True,
            })
        )

    def _create_option_use_stages(self, model_vals):
        # 1. Create the stage model
        stage_model_vals = {
            'name': '%s Stages' % model_vals.get('name'),
            'model': '%s_stage' % model_vals.get('model'),
            'field_id': [
                Command.create({
                    'name': 'x_name',
                    'ttype': 'char',
                    'required': True,
                    'field_description': _('Stage Name'),
                    'translate': 'standard',
                    'copied': True,
                })
            ],
        }
        self._create_option_use_sequence(stage_model_vals)

        # 2. Link our model with the tag model
        model_vals['field_id'].extend([
            Command.create({
                'name': 'x_workflow_studio_stage_id',
                'ttype': 'many2one',
                'relation': stage_model_vals['model'],
                'on_delete': 'restrict',
                'required': True,
                'field_description': _('Stage'),
                'tracking': model_vals.get('is_mail_thread'),
                'copied': True,
                'group_expand': True,
            }),
            Command.create({
                'name': 'x_workflow_studio_priority',
                'ttype': 'boolean',
                'field_description': _('High Priority'),
                'copied': True,
            }),
            Command.create({
                'name': 'x_color',
                'ttype': 'integer',
                'field_description': _('Color'),
            }),
            Command.create({
                'name': 'x_workflow_studio_kanban_state',
                'ttype': 'selection',
                'selection_ids': [
                    Command.create({'value': 'normal', 'name': _('In Progress'), 'sequence': 10}),
                    Command.create({'value': 'done', 'name': _('Ready'), 'sequence': 20}),
                    Command.create({'value': 'blocked', 'name': _('Blocked'), 'sequence': 30}),
                ],
                'field_description': _('Kanban State'),
                'copied': True,
            }),
        ])
        model_vals['order'] = 'id asc'
        return stage_model_vals

    def _post_create_option_use_stages(self, stage_model):
        # create stage 'New','In Progress','Done' and set 'New' as default
        stages = self.env[stage_model.model].create([
            {'x_name': _('New')},
            {'x_name': _('In Progress')},
            {'x_name': _('Done')}
        ])
        self.env['ir.default'].set(self.model, 'x_workflow_studio_stage_id', stages[0].id)

    def _create_option_use_tags(self, model_vals):
        # 1. Create the tag model
        tag_model_vals = {
            'name': '%s Tags' % model_vals.get('name'),
            'model': '%s_tag' % model_vals.get('model'),
            'field_id': [
                Command.create({
                    'name': 'x_name',
                    'ttype': 'char',
                    'required': True,
                    'field_description': _('Name'),
                    'copied': True,
                }),
                Command.create({
                    'name': 'x_color',
                    'ttype': 'integer',
                    'field_description': _('Color'),
                    'copied': True,
                }),
            ],
        }
        # 2. Link our model with the tag model
        model_vals['field_id'].append(
            Command.create({
                'name': 'x_workflow_studio_tag_ids',
                'ttype': 'many2many',
                'relation': tag_model_vals['model'],
                'field_description': _('Tags'),
                'relation_table': '%s_tag_rel' % model_vals.get('model'),
                'column1': '%s_id' % model_vals.get('model'),
                'column2': 'x_tag_id',
                'copied': True,
            })
        )
        return tag_model_vals

    def _setup_access_rights(self):
        for model in self:
            # Give all access to the created model to Employees by default, except deletion. All access to System
            # Note: a better solution may be to create groups at the app creation but the model is created
            # before the app and for other models we need to have info about the app.
            self.env['ir.model.access'].create({
                'name': model.name + ' group_system',
                'model_id': model.id,
                'group_id': self.env.ref('base.group_system').id,
                'perm_read': True,
                'perm_write': True,
                'perm_create': True,
                'perm_unlink': True,
            })
            self.env['ir.model.access'].create({
                'name': model.name + ' group_user',
                'model_id': model.id,
                'group_id': self.env.ref('base.group_user').id,
                'perm_read': True,
                'perm_write': True,
                'perm_create': True,
                'perm_unlink': False,
            })
        return True

    def _get_default_view(self, view_type, view_id=False, create=True):
        """Get the default view for a given model.

        By default, create a view if one does not exist.
        """
        self.ensure_one()
        View = self.env['ir.ui.view']
        # If we have no view_id to inherit from, it's because we are adding
        # fields to the default view of a new model. We will materialize the
        # default view as a true view so we can keep using our xpath mechanism.
        if view_id:
            view = View.browse(view_id)
        elif create:
            arch = self.env[self.model].get_view(view_id, view_type)['arch']
            # set sample data when activating a pivot/graph view through studio
            if view_type in ['graph', 'pivot']:
                sample_view_arch = ET.fromstring(arch)
                sample_view_arch.set('sample', '1')
                arch = ET.tostring(sample_view_arch, encoding='unicode')
            view = View.create({
                'type': view_type,
                'model': self.model,
                'arch': arch,
                'name': self.env._("Default %(view_type)s view for %(model)s", view_type=view_type, model=self),
            })
        else:
            view = View.browse(View.default_view(self.model, view_type))
        return view

    def _create_default_action(self, name):
        """Create an ir.act_window record set up with the available view types set up."""
        self.ensure_one()
        if self.transient:
            form_view = self.env['ir.ui.view'].search(
                [('model', '=', self.model), ('type', '=', 'form')],
                limit=1,
            )
            action_vals = {
                'name': name,
                'res_model': self.model,
                'view_mode': 'form',
                'target': 'new',
                'help': _("""
                    <p class="o_view_nocontent_smiling_face">
                        This wizard was created by Workflow Studio.
                    </p>
                """),
            }
            if form_view:
                action_vals['views'] = [(form_view.id, 'form')]
            return self.env['ir.actions.act_window'].create(action_vals)

        model_views = self.env['ir.ui.view'].search_read([('model', '=', self.model), ('type', '!=', 'search')],
                                                         fields=['type'])
        available_view_types = set(map(lambda v: v['type'], model_views))
        # in actions, kanban should be first, then list, etc.
        # this is arbitrary, but we need consistency!
        VIEWS_ORDER = {'kanban': 0, 'list': 1, 'form': 2, 'calendar': 3, 'gantt': 4, 'map': 5,
                       'pivot': 6, 'graph': 7, 'qweb': 8, 'activity': 9}
        sorted_view_types = list(sorted(available_view_types, key=lambda vt: VIEWS_ORDER.get(vt, 10)))
        view_mode = ','.join(sorted_view_types) if sorted_view_types else 'list,form'
        action = self.env['ir.actions.act_window'].create({
            'name': name,
            'res_model': self.model,
            'view_mode': view_mode,
            'help': _("""
                <p class="o_view_nocontent_smiling_face">
                    This is your new action.
                </p>
                <p>By default, it contains a list and a form view and possibly
                    other view types depending on the options you chose for your model.
                </p>
                <p>
                    You can start customizing these screens by clicking on the Studio icon on the
                    top right corner (you can also customize this help message there).
                </p>
            """),
        })
        return action

    @api.model
    def studio_model_infos(self, model_name):
        irModel = self._get(model_name)
        res = irModel.read(["id", "name", "state", "is_mail_thread", "is_mail_activity", "model"])[0]
        domain = []
        if model_name == "account.move":
            domain = [["move_type", "!=", "entry"]]
        res["record_ids"] = self.env[model_name].search(domain, limit=10).ids
        res["domain"] = domain
        return res


class IrModelFields(models.Model):
    _name = 'ir.model.fields'
    _inherit = ['workflow.studio.mixin', 'ir.model.fields']

    @property
    def _rec_names_search(self):
        if self.env.context.get('workflow_studio'):
            return ['name', 'field_description', 'model', 'model_id.name']
        return ['field_description']

    @api.depends('field_description', 'model_id')
    @api.depends_context('workflow_studio')
    def _compute_display_name(self):
        in_studio = self.env.context.get("workflow_studio")
        if not in_studio:
            return super()._compute_display_name()
        for field in self:
            field.display_name = f"{field.field_description} ({field.model_id.name})"

    @api.constrains('name')
    def _check_name(self):
        super()._check_name()
        for field in self:
            if '__' in field.name:
                raise ValidationError(_("Custom field names cannot contain double underscores."))

    @api.model
    def _get_next_relation(self, model_name, comodel_name):
        """Prevent using the same m2m relation table when adding the same field.

        If the same m2m field was already added on the model, the user is in fact
        trying to add another relation - not the same one. We need to create another
        relation table.
        """
        result = super()._custom_many2many_names(model_name, comodel_name)[0]
        # check if there's already a m2m field from model_name to comodel_name;
        # if yes, check the relation table and add a sequence to it - we want to
        # be able to mirror these fields on the other side in the same order
        base = result
        attempt = 0
        existing_m2m = self.search([
            ('model', '=', model_name),
            ('relation', '=', comodel_name),
            ('relation_table', '=', result)
        ])
        while existing_m2m:
            attempt += 1
            result = '%s_%s' % (base, attempt)
            existing_m2m = self.search([
                ('model', '=', model_name),
                ('relation', '=', comodel_name),
                ('relation_table', '=', result)
            ])
        return result


class IrModelAccess(models.Model):
    _name = 'ir.model.access'
    _inherit = ['workflow.studio.mixin', 'ir.model.access']
