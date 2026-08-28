{
    'name': 'Home Leave Ticket',
    'version': '1.0.0',
    'category': 'Workflow',
    'author': 'CHUON PISETH',
    'sequence': 120,
    'icon': 'home_leave_ticket/static/description/icon.png',
    'summary': 'This is Home Leave Ticket workflow',
    'description': '''
A Home Leave Ticket is used to document and manage the process of employees requesting leave to go home. 
It collects details about the leave request, including the reason for leave, duration, and tracks the approval status.

This module manages home leave ticket requests, including submission, approval, and tracking of leave status.
According to the leave type configuration, a request creates next activities for the related personnel.

    ''',
    'depends': ['workflow_engine', 'hr'],
    'data': [
        # Models
        "models/schema/x_home_leave_ticket.xml",
        "models/schema/x_home_leave_ticket_time_range.xml",
        "models/schema/x_home_leave_ticket_travel_detail.xml",
        "models/schema/x_home_leave_ticket_fields.xml",

        # Security
        "security/ir.model.access.csv",

        # Data
        "data/x_home_leave_ticket_type_data.xml",
        "data/x_home_leave_ticket_time_range_data.xml",
        "data/defaults.xml",

        # UI and Navigation
        "actions/home_leave_ticket_actions.xml",
        "views/home_leave_ticket_views.xml",
        "views/home_leave_ticket_type_views.xml",
        "menus/home_leave_ticket_menus.xml",

        # Workflow
        "workflows/home_leave_ticket_workflow.xml",

        # Reports
        "reports/home_leave_ticket_report_template.xml",
        "reports/home_leave_ticket_report_action.xml",

    ],
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_action',
    'uninstall_hook': 'uninstall_action'

}