# -*- coding: utf-8 -*-

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    activity_type = env.ref(
        "workflow_engine.mail_activity_data_workflow_approval",
        raise_if_not_found=False,
    )
    if not activity_type:
        return

    if activity_type.res_model:
        activity_type.write({"res_model": False})
