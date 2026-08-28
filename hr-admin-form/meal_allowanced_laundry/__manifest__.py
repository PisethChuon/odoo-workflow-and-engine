{
    'name': 'Meal Allowance & Laundry',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 100,
    'icon': 'meal_allowanced&laundry/static/description/icon.png',
    'summary': 'Manage and approve meal allowance and laundry expense requests',
    'description': '''
Meal Allowance & Laundry Management
====================================

A comprehensive solution for organizations to manage meal allowance and laundry expense requests.

This module allows you to:

- Process meal allowance and laundry expense applications from employees
- Collect essential expense information
- Track approval workflows
- Maintain records of approved expenses and their details
    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        # Models
        'models/schema/x_meal_allowance_level.xml',
        'models/schema/x_meal_allowance_title.xml',
        'models/schema/x_meal_allowance_apparel_type.xml',
        'models/schema/x_meal_allowance_staff_group.xml',
        'models/schema/x_meal_allowance_outlet.xml',
        'models/schema/x_meal_allowance_request.xml',

        # Security
        'security/ir.model.access.csv',

        # UI Elements
        'actions/title_act_window.xml',
        'actions/level_act_window.xml',
        'actions/apparel_type_act_window.xml',
        'actions/staff_group_act_window.xml',
        'actions/outlet_act_window.xml',
        'actions/act_window.xml',
        'automation/automation_rules.xml',
        'automation/server_actions.xml',
        'views/x_meal_allowance_title_views.xml',
        'views/x_meal_allowance_level_views.xml',
        'views/x_meal_allowance_apparel_type_views.xml',
        'views/x_meal_allowance_staff_group_views.xml',
        'views/x_meal_allowance_outlet_views.xml',
        'views/x_meal_allowance_request_views.xml',
        'menus/meal_allowance_laundry_menus.xml',

        # Workflows
        'workflows/meal_allowance_laundry_workflow.xml',

        # Reports
        'reports/report_meal_allowance_request_detail_template.xml',
        'reports/report_action.xml',
    ],
    'demo': [
        'data/demo/x_meal_allowance_outlet_demo.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
