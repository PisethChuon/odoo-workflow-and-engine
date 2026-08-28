# x_delegate_wizard.py
import logging
import pytz
from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class Util(models.TransientModel):
    """
    This model is used to provide utility functions for the script inside action server, 
    and it can import libraries and use them to implement the utility functions, 
    then the script inside action server can call these utility functions to get the result.
    """
    _name = "workflow.util"
    _description = "Workflow utility model"

    @api.model
    def get_now(self):
        """Get current datetime in user's timezone"""
        return datetime.now(pytz.timezone(self.env.user.tz or 'UTC'))

