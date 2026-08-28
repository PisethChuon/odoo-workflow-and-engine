# -*- coding: utf-8 -*-
{
    "name": "Workflow Push Notifications",
    "version": "19.0.1.0.2",
    "category": "Tools",
    "summary": "Send push notifications to approvers when workflow requests are assigned",
    "license": "LGPL-3",
    'author': 'Programming Team',
    "depends": [
        "workflow_engine",
        "notification_push_channel",
    ],
    "data": [
        "data/ir_config_parameter.xml",
    ],
    "installable": True,
    "application": False,
}
