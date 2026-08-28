# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


RULE_GROUP_UPDATES = (
    "workflow_engine.rule_workflow_base_for_visibility_scope_read",
    "workflow_engine.rule_workflow_base_for_follower_read",
    "workflow_engine.rule_workflow_category_by_default",
)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    reader_group = env.ref("workflow_engine.group_workflow_request_reader", raise_if_not_found=False)
    approval_group = env.ref("workflow_engine.group_workflow_approval_user", raise_if_not_found=False)
    if reader_group and approval_group:
        approval_group.write(
            {"implied_ids": [(6, 0, list(set((approval_group.implied_ids | reader_group).ids)))]}
        )

    if reader_group:
        for xmlid in RULE_GROUP_UPDATES:
            rule = env.ref(xmlid, raise_if_not_found=False)
            if rule:
                rule.write({"groups": [(6, 0, [reader_group.id])]})
