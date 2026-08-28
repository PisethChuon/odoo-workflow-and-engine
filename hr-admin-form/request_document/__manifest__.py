{
    'name': 'Request Document',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 120,
    'icon': 'request_document/static/description/icon.png',
    'summary': 'Workflow Request Document',
    'description': '''
A Workflow Request Document is used to document and manage the workflow request process of items within an organization
======================================
This module manages workflow request documents, including submission, approval, and tracking of workflow request status.
According to the workflow request type configuration, a request creates next activities for the related personnel.
    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        'models/schema/x_request_document.xml',

        # Security
        'security/ir.model.access.csv',

        # Actions
        'actions/act_window.xml',
        'views/x_request_document_views.xml',

        # Workflows
        'workflows/request_document_workflow.xml',

        # Reports
        'reports/report_action.xml',
        'reports/report_request_document_template.xml',

    ],
    'demo': [

    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}