# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


RULE_XMLID = "rule_workflow_base_for_create_audience"
RULE_DOMAIN = """
                ['|',
                    ('category_id.create_access_mode', '!=', 'restricted'),
                    '&',
                        ('category_id.create_access_mode', '=', 'restricted'),
                        '|','|',
                            ('category_id.create_allowed_user_ids', 'in', [user.id]),
                            ('category_id.create_allowed_group_ids', 'in', user.all_group_ids.ids),
                            '&',
                                ('category_id.create_allowed_department_ids', '!=', False),
                                ('category_id.create_allowed_department_ids', 'in', [user.department_id.id or 0])
                ]
"""


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    model = env.ref(
        "workflow_engine.model_workflow_base_approval_request",
        raise_if_not_found=False,
    )
    group = env.ref(
        "workflow_engine.group_workflow_approval_user",
        raise_if_not_found=False,
    )
    if not model or not group:
        return

    data = env["ir.model.data"].sudo().search(
        [
            ("module", "=", "workflow_engine"),
            ("name", "=", RULE_XMLID),
            ("model", "=", "ir.rule"),
        ],
        limit=1,
    )
    rule = env["ir.rule"].sudo().browse(data.res_id).exists() if data else env["ir.rule"]
    if not rule:
        rule = env["ir.rule"].sudo().search(
            [
                ("model_id", "=", model.id),
                ("name", "=", "WF: Request Create Audience Rule"),
            ],
            limit=1,
        )

    values = {
        "name": "WF: Request Create Audience Rule",
        "model_id": model.id,
        "domain_force": RULE_DOMAIN,
        "groups": [(6, 0, [group.id])],
        "perm_read": False,
        "perm_write": False,
        "perm_create": True,
        "perm_unlink": False,
        "active": True,
    }
    if rule:
        rule.write(values)
    else:
        rule = env["ir.rule"].sudo().create(values)

    if not data:
        env["ir.model.data"].sudo().create(
            {
                "module": "workflow_engine",
                "name": RULE_XMLID,
                "model": "ir.rule",
                "res_id": rule.id,
                "noupdate": True,
            }
        )
