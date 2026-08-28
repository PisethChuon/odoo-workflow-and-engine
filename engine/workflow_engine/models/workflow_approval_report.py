# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.addons.workflow_engine.utils.util import EmployeeType
from odoo.fields import Domain

class WorkflowApprovalReport(models.Model):
    _name = "workflow.approval.report"
    _auto = False
    _description = "Report for workflow approval"

    name = fields.Char(string="Approval Subject")
    category_id = fields.Many2one('workflow.approval.category', string='Approval Category')
    res_model_name = fields.Char(related='version_id.res_model_name')
    version_id = fields.Many2one('workflow.approval.category.version', string='Active Version')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'To Submit'),
        ('waiting', 'Waiting for Next Approval'),
        ('completed', 'Completed'),
        ('cancel', 'Cancelled'),
        ('auto_cancelled', 'Auto Cancelled'),
        ('refused', 'Refused'),
    ], string='Workflow Stage', default='draft')
    
    current_node_id = fields.Char("Current BPMN Node ID")
    previous_node_id = fields.Char("Previous BPMN Node ID")
    next_node_id = fields.Char("Next BPMN Node ID")
    current_activity_name = fields.Char("Activity Name")
    previous_activity_name = fields.Char("Previous Activity")
    next_activity_name = fields.Char("Next Activity")
    category_image = fields.Binary(related='category_id.image')
    approver_ids = fields.One2many('workflow.approval.approver', 'request_id', string="Approvers", bypass_search_access=True)
    
    to_approve_user_ids = fields.One2many('workflow.approval.approver', 'request_id', string="Approvers Reviewer",
                check_company=True, domain=lambda self: [('status','=','new')])

    to_approve_res_user_ids = fields.One2many('res.users', compute='_compute_approve_res_user_ids', store=False)

    company_id = fields.Many2one(string='Company', related='category_id.company_id')
    request_owner_id = fields.Many2one('res.users', string="Request Owner",
                                       check_company=True, domain="[('company_ids', 'in', company_id)]",
                                       default=lambda self: self.env.user)
    request_owner_emp_code = fields.Char(string="Emp Code", store=True)
    request_owner_ext_phone = fields.Char(string="Ext Phone", store=True)

    creator_emp_code = fields.Char(string="Creator Emp Code")
    approval_minimum = fields.Integer(related="category_id.approval_minimum")
    
    create_date = fields.Datetime()
    create_uid = fields.Many2one("res.users")

    request_owner_emp_type = fields.Selection(EmployeeType.selection())
    

    def init(self):
        """ Create or replace the SQL view used by this model. """
        self.env.cr.execute(f"DROP VIEW IF EXISTS {self._table}")
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    id,
                    name,
                    category_id,
                    '' as res_model_name,
                    version_id,
                    state,
                    current_node_id,
                    previous_node_id,
                    next_node_id,
                    current_activity_name,
                    previous_activity_name,
                    next_activity_name,
                    '' as category_image,
                    '' as approver_ids,
                    company_id,
                    request_owner_id,
                    '' as request_owner_emp_code,
                    '' as request_owner_ext_phone,
                    creator_emp_code,
                    1 as approval_minimum,
                    '' as request_owner_emp_type,
                    create_date,
                    create_uid
                FROM workflow_base_approval_request
            )
        """)


    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        merged = {'length': 0, 'records': []}
        for cat in self.env["workflow.approval.category"].search([]):
            model_name = cat.res_model_name
            if not model_name or not self.env.registry.get(model_name):
                continue
            results = self.env[model_name].web_search_read( domain, specification, offset, limit, order, count_limit)
            merged['records'].extend(results.get('records', []))
            merged['length'] += results.get('length', 0)
        return merged

    @api.model
    @api.readonly
    def web_read_group(
            self,
            domain,
            groupby,
            aggregates=(),
            limit=None,
            offset=0,
            order=None,
            *,
            auto_unfold=False,
            opening_info=None,
            unfold_read_specification=None,
            unfold_read_default_limit=80,
            groupby_read_specification=None,
    ):
        """
        Merge grouped results across all workflow categories' res_model_name models.

        Notes:
        - We merge only group dictionaries (`groups`) and sum numeric aggregate values.
        - `__extra_domain` is kept from the first encountered group; cross-model domains
          are not safely mergeable (different models).
        - `length` is summed across models (total group count).
        """

        merged = {"groups": [], "length": 0}
        group_map = {}  # key -> merged group dict

        # Ensure Odoo-style Domain (Odoo 19 uses Domain class internally)
        domain = Domain(domain)

        # Important: always include '__count' so merging works consistently
        aggregates = list(aggregates or ())
        if "__count" not in aggregates:
            aggregates.append("__count")

        categories = self.env["workflow.approval.category"].search([])
        for cat in categories:
            model_name = cat.res_model_name
            if not model_name or not self.env.registry.get(model_name):
                continue

            # Call the real model web_read_group with the Odoo 19 signature
            res = self.env[model_name].web_read_group(
                domain,
                groupby,
                aggregates=aggregates,
                limit=limit,
                offset=offset,
                order=order,
                auto_unfold=auto_unfold,
                opening_info=opening_info,
                unfold_read_specification=unfold_read_specification,
                unfold_read_default_limit=unfold_read_default_limit,
                groupby_read_specification=groupby_read_specification,
            )

            merged["length"] += int(res.get("length", 0) or 0)

            for g in res.get("groups", []):
                # Build a stable key from groupby specs (exact keys are groupby strings, e.g. "state", "date:month")
                key = tuple(g.get(spec) for spec in groupby)

                if key not in group_map:
                    group_map[key] = g.copy()
                    continue

                target = group_map[key]

                # Sum only numeric aggregate values
                for agg in aggregates:
                    if agg in g and isinstance(g[agg], (int, float)):
                        target[agg] = (target.get(agg) or 0) + g[agg]

                # If some models return extra numeric aggregates not listed explicitly, you can also merge them:
                # (optional but often useful)
                for k, v in g.items():
                    if k.startswith("__"):
                        continue
                    if isinstance(v, (int, float)) and isinstance(target.get(k), (int, float)):
                        target[k] += v

                # Keep '__extra_domain' from the first group; cross-model merging is unsafe.

        merged["groups"] = list(group_map.values())
        return merged
       

    @api.depends('approver_ids')
    def _compute_approve_res_user_ids(self):
        for rec in self:
            rec.to_approve_res_user_ids = rec.to_approve_user_ids.user_id.filtered(lambda u: u)
            
