# -*- coding: utf-8 -*-
{
    "name": "Emergency Incident",
    "version": "1.0.0",
    "category": "Workflow",
    "author": "CHUON PISETH",
    "website": "",
    "sequence": 130,
    "icon": "emergency_incident/static/description/icon.png",
    "summary": "Manage and track emergency incident reports and resolution workflow",
    "description": """
Emergency Incident Management
===============================
Scaffold for emergency incident reporting and approval lifecycle.
This module currently includes only structural placeholders.
    """,
    "depends": [
        "workflow_engine",
        "hr",
    ],
    "data": [
        "models/schema/emergency_incident_information_type.xml",
        "models/schema/emergency_incident_color_code.xml",
        "models/schema/emergency_incident_property.xml",
        "models/schema/emergency_incident_shift.xml",
        "models/schema/emergency_incident_location.xml",
        "models/schema/emergency_incident_call.xml",
        "models/schema/emergency_incident_information.xml",

        "automation/emergency_incident_automation.xml",

        "data/emergency_incident_type_data.xml",

        "security/ir.model.access.csv",

        "views/emergency_incident_information_type_view.xml",
        "views/emergency_incident_shift_view.xml",
        "views/emergency_incident_location_view.xml",
        "views/emergency_incident_call_view.xml",
        "views/emergency_incident_information_view.xml",
        "views/emergency_incident_color_code_view.xml",
        "views/emergency_incident_property_view.xml",

        'actions/act_window.xml',

        'menus/emergency_incident_menu.xml',

        'workflows/emergency_incident_workflow.xml',
        
        "reports/emergency_incident_report.xml",
        "reports/emergency_incident_report_template.xml",

    ],
    "demo": [
        # 'demo/emergency_incident_demo.xml',
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
    "post_init_hook": "post_init_action",
    "uninstall_hook": "uninstall_action",
}
