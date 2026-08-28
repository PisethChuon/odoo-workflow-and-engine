{
    'name': 'Purchase Request',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 110,
    'icon': 'purchase_request/static/description/icon.png',
    'summary': 'Manage purchase requests with approval routing and status tracking',
    'description': '''
Streamline purchase request handling from submission to approval. This module enables users to:

• Create purchase requests with the required item and request details
• Route requests through the configured approval workflow
• Automatically generate follow-up activities for the responsible personnel
• Track request progress and status throughout the process

Improve purchasing coordination with a clear request history, structured approvals, and better visibility into each request.

    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        'models/schema/x_purchase_request_type.xml',
        'models/schema/x_purchase_request.xml',
        'models/schema/x_purchase_request_vendor.xml',
        'models/schema/x_purchase_request_fields.xml',

        # Security
        'security/ir.model.access.csv',

        # Actions
        'actions/purchase_request_actions.xml',
        'actions/purchase_request_type_actions.xml',
        'actions/purchase_item_actions.xml',

        # Views
        'views/x_purchase_request_views.xml',
        'views/purchase_request_type_views.xml',
        'views/purchase_item_views.xml',

        # Menus
        'menus/purchase_request_menus.xml',

        # Workflows
        'workflows/purchase_request_workflow.xml',

        # Reports
        'reports/purchase_request_report_template.xml',
        'reports/purchase_request_report_action.xml',

    ],
    'demo': [
        'data/demo/purchase_request_type_demo.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}