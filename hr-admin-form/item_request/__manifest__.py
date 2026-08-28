{
    'name': 'Item Request',
    'version': '1.0',
    'summary': 'Manage item requests with dynamic item lines and approval workflows.',
    'author': 'CHHIN VANCHHAI',
    'category': 'Workflow',
    'depends': ['workflow_engine'],
    'data': [
        # 'views/assets.xml',
        # models
        "models/item_request.xml",
        "models/config_item_line.xml",
        "models/config_sub_item_line.xml",
        "models/config_rel.xml",
        

        "models/item_request_item_line.xml",
        "models/item_request_line_rel.xml",
        "models/inherit_update_wazard.xml",
        
        # data
        "data/ir_actions_act_window.xml",
        "data/item_request_data.xml",
        "data/mail_template_data.xml",
        "data/automation_rule.xml",
          
        # view
        "views/config_item_line.xml",
        "views/config_sub_item_line.xml",
        "views/item_req_item_line.xml", 
        "views/inherit_update_wazard.xml",
        "views/ir_ui_view.xml",
         
        # menu
        "data/ir_ui_menu.xml",
        
        # report
        "reports/report_template.xml",
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
