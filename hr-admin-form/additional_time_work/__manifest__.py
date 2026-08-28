{
    'name': 'Additional Time Work',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 130,
    'icon': 'additional_time_work/static/description/icon.png',
    'summary': 'Manage and approve additional time work requests',
    'description': '''
Additional Time Work Management
===============================

Scaffold for additional time work request flow and approval lifecycle.

This module currently includes only structural placeholders.
    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        'models/schema/x_additional_time_work.xml',

        'security/ir.model.access.csv',

        'actions/act_window.xml',
        'actions/work_on_category_actions.xml',
        'automation/automation_rules.xml',
        'automation/server_actions.xml',
        'views/work_on_category_views.xml',
        'views/x_additional_time_work_views.xml',
        'menus/additional_time_work_menus.xml',

        'workflows/additional_time_work_workflow.xml',

        # Reports
        'reports/report_action.xml',
        'reports/report_additional_time_work_detail_template.xml',
    ],
    'demo': [
        'data/demo/additional_time_work_demo.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}
