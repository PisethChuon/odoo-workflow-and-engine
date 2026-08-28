{
    'name': 'Honestly Award',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 130,
    'icon': 'honestly_award/static/description/icon.png',
    'summary': 'Honestly Award Request workflow',
    'description': '''
    The Honesty Award recognizes employees who lead with transparency and hold themselves to the highest ethical standards.
    ''',

    'depends': ['workflow_engine', 'hr'],
    'data': [
        # Models (schema)
        'models/schema/x_honestly_award.xml',
        'models/schema/x_item.xml',
        'models/schema/x_location.xml',
        'models/schema/x_honestly_award_detail.xml',
        'models/schema/x_honestly_award_relations.xml',
        'models/schema/x_honestly_award_computed_fields.xml',
        'models/schema/x_honestly_award_related_fields.xml',

        # Security
        'security/ir_model_access.xml',
        'security/ir.model.access.csv',

        # Actions
        'actions/honestly_award_actions.xml',

        # Views
        'views/x_item_views.xml',
        'views/x_location_views.xml',
        'views/x_honestly_award_views.xml',

        # Menus
        'menus/honestly_award_menus.xml',

        # Workflows
        'workflows/honestly_award_workflow.xml',

        # Reports
        'reports/honestly_award_report_template.xml',
        'reports/honestly_award_report_action.xml',
    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'
}