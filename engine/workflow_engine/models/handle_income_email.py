from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class HandleIncomingEmail(models.Model):
    _name = 'handle.incoming.email'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Handle Incoming Email'

    name = fields.Char(string='Subject', required=True, tracking=True)
    sender_email = fields.Char(string='From', tracking=True)
    body = fields.Html(string='Message Body')
    state = fields.Selection([
        ('new', 'New'),
        ('active', 'Workflow Triggered'),
        ('done', 'Completed')
    ], default='new', tracking=True)

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """
        Overriding message_new to catch the email and create the record.
        msg_dict contains the parsed email data.
        """
        # Set default values from the email
        defaults = {
            'name': msg_dict.get('subject', 'No Subject'),
            'sender_email': msg_dict.get('from'),
            'body': msg_dict.get('body'),
        }
        
        # Merge with any other custom values provided by Odoo
        if custom_values:
            defaults.update(custom_values)

        # Create the ticket record
        record = super(HandleIncomingEmail, self).message_new(msg_dict, custom_values=defaults)

        # TRIGGER WORKFLOW
        record._action_trigger_workflow()

        return record

    def _action_trigger_workflow(self):
        """
        This is where your business logic lives.
        """
        for record in self:
            _logger.info(f"Triggering workflow for Ticket: {record.name}")
            
            # Example Logic: Change state and post a log
            record.state = 'active'
            record.message_post(body=_("Workflow automatically started from incoming email."))
            
            # You can call other methods here, e.g., create a task, send an API call, etc.