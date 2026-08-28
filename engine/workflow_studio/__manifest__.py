# -*- coding: utf-8 -*-
{
    'name': "Workflow Studio",
    'summary': "Create and customize your Workflow",
    'description': """
Workflow - Customize Workflow Approval
==============================================
This addon allows the user to customize most element of the approval workflow, workflow from, meta data flow digram, in a
simple and graphical way. It has two main features:

* create a new workflow
* customize an existing workflow and design form

Note: Only the admin user is allowed to make those customizations.
""",
    'category': 'Workflow',
    'sequence': 75,
    'version': '1.4',
    'depends': [
        'base_automation',
        'base_import_module',
        'mail',
        'web',
        'html_editor',
        'sms',
        'workflow_engine',
    ],
    'data': [
        'views/assets.xml',
        'views/actions.xml',
        'views/ir_actions_report_xml.xml',
        'views/ir_model_data.xml',
        'views/base_automation_views.xml',
        'views/studio_approval_views.xml',
        'views/reset_view_arch_wizard.xml',
        'views/studio_export_wizard_views.xml',
        'views/studio_export_model_views.xml',
        'views/workflow_meta_field_picker_views.xml',
        'wizard/workflow_studio_import_zip_wizard_views.xml',
        'wizard/workflow_studio_quick_start_wizard_views.xml',
        'views/workflow_approval_category_views.xml',
        'views/workflow_menu_overrides.xml',
        'data/mail_templates.xml',
        'data/web_tour_tour.xml',
        'wizard/base_module_uninstall_view.xml',
        'security/ir.model.access.csv',
        'security/studio_security.xml',
    ],
    'application': True,
    'author': 'Puthiphorn',
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            'workflow_studio/static/src/systray_item/**/*.js',
            'workflow_studio/static/src/studio_service.js',
            'workflow_studio/static/src/utils.js',

            'workflow_studio/static/src/client_action/studio_action_loader.js',
            'workflow_studio/static/src/client_action/app_creator/app_creator_shortcut.js',
            'workflow_studio/static/src/client_action/components/**/*.js',
            'workflow_studio/static/src/client_action/components/**/*.xml',
            'workflow_studio/static/src/export/**/*.js',
            'workflow_studio/static/src/home_menu/**/*.js',
            'workflow_studio/static/src/views/**/*.js',
            'workflow_studio/static/src/js/**/*.js',
            ('remove', 'workflow_studio/static/src/views/kanban_report/**/*'),
            'workflow_studio/static/src/approval/**/*',
            'workflow_studio/static/src/**/*.xml',
            'workflow_studio/static/src/client_action/report_editor/qweb_table_plugin.scss',
        ],
        'workflow_studio.studio_assets': [
            ('include', 'web.assets_backend_lazy'),
            ('include', 'workflow_studio.studio_assets_minimal'),
        ],
        'workflow_studio.studio_assets_minimal': [
            'workflow_studio/static/src/client_action/**/*.js',
            'workflow_studio/static/src/views/kanban_report/**/*.js',
            ('remove', 'workflow_studio/static/src/client_action/studio_action_loader.js'),
            ('remove', 'workflow_studio/static/src/client_action/app_creator/app_creator_shortcut.js'),
            ('remove', 'workflow_studio/static/src/client_action/view_editor/editors/graph/**/*'),
            ('remove', 'workflow_studio/static/src/client_action/view_editor/editors/kanban/**/*'),
            ('remove', 'workflow_studio/static/src/client_action/view_editor/editors/list/**/*'),
            ('remove', 'workflow_studio/static/src/client_action/view_editor/editors/pivot/**/*'),
            ('remove', 'workflow_studio/static/src/client_action/view_editor/editors/search/**/*'),

            ('include', 'web._assets_helpers'),
            'workflow_studio/static/src/scss/bootstrap_overridden.scss',
            'web/static/src/scss/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            'workflow_studio/static/src/client_action/variables.scss',
            'workflow_studio/static/src/client_action/mixins.scss',
            'workflow_studio/static/src/client_action/**/*.scss',
            ("remove", "workflow_studio/static/src/client_action/report_editor/report_iframe.scss"),
            'workflow_studio/static/src/views/kanban_report/**/*.scss',
        ],
        "workflow_studio.studio_assets_dark": [
            'workflow_studio/static/src/client_action/variables.dark.scss',
            ('include', 'web.assets_backend_lazy_dark'),
            ('include', 'workflow_studio.studio_assets_minimal'),
        ],
        'web.assets_tests': [
            'workflow_studio/static/tests/tours/**/*',
        ],
        'workflow_studio.report_assets': [
            ('include', 'web._assets_helpers'),
            'web/static/src/scss/pre_variables.scss',
            'web/static/lib/bootstrap/scss/_variables.scss',
            'web/static/lib/bootstrap/scss/_variables-dark.scss',
            'web/static/lib/bootstrap/scss/_maps.scss',
            "web/static/src/webclient/actions/reports/report.scss",
            'workflow_studio/static/src/client_action/report_editor/report_iframe.scss',
            'workflow_studio/static/src/client_action/report_editor/qweb_table_plugin.scss',
        ],
        'web.qunit_suite_tests': [
            'workflow_studio/static/tests/legacy/disable_patch.js',
        ],
        'web.assets_unit_tests': [
            ('include', 'workflow_studio.studio_assets_minimal'),
            'workflow_studio/static/tests/**/*',
            ('remove', 'workflow_studio/static/tests/legacy/**/*'),
            ('remove', 'workflow_studio/static/tests/tours/**/*'),
        ],
    }
}
