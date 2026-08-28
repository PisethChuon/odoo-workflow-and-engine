{
    'name': 'Item Repair',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 110,
    'icon': 'item_repair/static/description/icon.png',
    'summary': 'Streamlined item repair request and approval workflow',
    'description': '''
Efficiently manage item repairs from submission to completion. This module enables users to:

• Submit repair requests with detailed item and issue information
• Route requests through approval workflows for management review
• Automatically assign follow-up activities to relevant personnel based on repair type
• Track repair status throughout the entire process

Simplify organization's item repair management with automated task assignment and clear visibility into all repair requests.

    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        'models/schema/x_item_request_type.xml',
        'models/schema/x_item_repair_request.xml',
        'models/schema/x_item_request.xml',
        'models/schema/x_item_repair_vendor.xml',
        'models/schema/x_item_repair_request_fields.xml',

        # Security
        'security/ir.model.access.csv',

        # Actions
        'actions/act_window.xml',

        # Views
        'views/x_item_repair_request_views.xml',
        'views/item_request_type_views.xml',

        # Menus
        'menus/item_repair_menus.xml',

        # Workflows
        'workflows/item_repair_workflow.xml',

        # Reports
        'reports/report_item_repair_template.xml',
        'reports/report_action.xml',

    ],
    'demo': [
        'demo/item_request_type_demo.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}