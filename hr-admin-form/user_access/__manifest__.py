{
    "name": "User Access",
    "version": "1.0.0",
    "category": "Workflow",
    "author": "CHUON PISETH",
    "sequence": 100,
    "summary": "Manage and approve user access requests",
    "description": '''
User Access Management
=======================

A comprehensive solution for organizations to manage and control user access to resources.

This module allows you to:

- Process user access requests from employees
- Manage access to resources (software, hardware, network, security)
- Track access approval workflows
- Maintain records of authorized access

The request form captures details such as employee information, resource type, 
and access requirements to ensure proper access control and security.
    ''',
    "depends": ["workflow_engine", "hr"],
    "data": [
        "models/schema/x_user_access_item.xml",
        "models/schema/x_user_access_item_type.xml",
        "models/schema/x_user_access.xml",
        "models/schema/x_user_access_line.xml",

        "security/ir.model.access.csv",

        "actions/act_window.xml",
        "views/x_user_access_line_views.xml",
        "views/x_user_access_views.xml",
        "menus/user_access_menus.xml",
        "workflows/user_access_workflow.xml",

        # Reports
        "reports/report_user_access_detail_template.xml",
        "reports/report_action.xml",
    ],
    "demo": [
        "data/demo/user_access_item_type_demo.xml",
        "data/demo/user_access_item_demo.xml",
    ],
    "installable": True,
    "application": True,
}
