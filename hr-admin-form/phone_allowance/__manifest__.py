{
    'name': 'Phone allowance',
    'version': '1.0',
    'summary': 'Manage phone allowance requests with dynamic item lines and approval workflows.',
    'author': 'CHHIN VANCHHAI',
    'category': 'Workflow',
    'depends': ['workflow_engine'],
    'data': [
        "models/phone_allowance.xml",
        "models/phone_allowance_item_line.xml",
        "models/phone_allowance_line_rel.xml",
        "models/inherit_update_wazard.xml",
        
        # data
        "data/ir_actions_act_window.xml",
        "data/data.xml",
        "data/mail_template_data.xml",
        "data/automation_rule.xml",
        # views
        "views/phone_allowance_item_line.xml", 
        "views/inherit_update_wazard.xml",
        "views/ir_ui_view.xml",
         
        # menu
        "data/ir_ui_menu.xml",
        
        # report
        "reports/report.xml",
        
        # security
        'security/groups.xml',
        'security/record_rule.xml',
    ],
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            # 'it_request/static/src/js/confirm_selection.js',
        ],
    },
}
