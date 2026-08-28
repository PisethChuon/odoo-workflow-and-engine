{
    'name': 'Car Park Permit',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 100,
    'icon': 'car_park_permit/static/description/icon.png',
    'summary': 'Manage and approve car parking permit requests',
    'description': '''
Car Park Permit Management
===========================

A comprehensive solution for organizations to manage and control vehicle parking access on their premises.

This module allows you to:

- Process parking permit applications from employees and visitors
- Collect essential driver and vehicle information
- Issue physical or digital parking permits
- Track permit approval workflows
- Maintain records of authorized vehicles and their parking privileges

The permit form captures details such as driver information, vehicle make, model, color, 
and registration number to ensure proper identification and access control.
    ''',
    'depends': ['workflow_engine'],
    'data': [
        'models/schema/x_car_model.xml',
        'models/schema/x_car_color.xml',
        'models/schema/x_car_park_request.xml',

        'security/ir.model.access.csv',

        'actions/act_window.xml',
        'automation/automation_rules.xml',
        'automation/server_actions.xml',
        'views/x_car_park_request_views.xml',
        'menus/car_park_permit_menus.xml',

        'workflows/car_park_permit_workflow.xml',

        # Reports
        'reports/report_car_park_request_detail_template.xml',
        'reports/report_action.xml',

    ],
    'demo': [
        'data/demo/car_model_demo.xml',
        'data/demo/car_color_demo.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}
