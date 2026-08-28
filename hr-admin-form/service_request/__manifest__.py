{
    'name': 'Service Request',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 100,
    'icon': 'service_request/static/description/icon.png',
    'summary': 'Manage and process service requests',
    'description': '''
Service Request Management
===========================

A comprehensive solution for organizations to manage and process service requests.

This module allows you to:

- Submit and track service requests
- Manage request approvals and workflows
- Assign requests to service teams
- Monitor request status and progress
- Generate service request reports

    ''',
    'depends': ['workflow_engine'],
    'data': [
        # Models
        'models/schema/x_service_request.xml',
        'models/schema/x_service_request_relations.xml',

        # Security
        'security/ir.model.access.csv',

        # Actions
        'actions/act_window.xml',

        # Automation
        'automation/automation_rules.xml',
        'automation/server_actions.xml',

        # Views
        'views/x_service_request_views.xml',

        # Menus
        'menus/service_request_menus.xml',

        # Workflows
        'workflows/service_request_workflow.xml',

        # Reports
        'reports/report_service_request_detail_template.xml',
        'reports/report_action.xml',

    ],
    'demo': [
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
