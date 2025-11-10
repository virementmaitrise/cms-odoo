# -*- coding: utf-8 -*-
import logging
import os
from odoo import models
from odoo.tools import convert_file
from .. import const

_logger = logging.getLogger(__name__)


class InvoiceViewLoader(models.AbstractModel):
    """
    This model uses _register_hook() to load the invoice report view on every Odoo restart.
    _register_hook() is called exactly once when the registry is being loaded.
    """
    _name = 'payment.invoice.view.loader'
    _description = 'Invoice View Loader for Payment Provider'

    def _register_hook(self):
        """
        Hook that runs once when the registry is loaded (on every Odoo restart).
        This is the perfect place to conditionally load views.
        """
        super()._register_hook()

        # Check if account module is installed
        account_module = self.env['ir.module.module'].sudo().search([
            ('name', '=', 'account'),
            ('state', '=', 'installed')
        ], limit=1)

        if not account_module:
            _logger.debug("%s: Account module not installed, skipping invoice view", const.MODULE_NAME)
            return

        # Check if view already exists
        view = self.env['ir.ui.view'].sudo().search([
            ('key', '=', f'{const.MODULE_NAME}.account_invoice_document_inherit')
        ], limit=1)

        if view:
            _logger.debug("%s: Invoice report view already exists", const.MODULE_NAME)
            return

        # Load the view
        _logger.info("%s: Loading invoice report view via _register_hook", const.MODULE_NAME)
        try:
            module_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            view_file = os.path.join(module_path, 'views', 'account_invoice_report.xml')

            if os.path.exists(view_file):
                convert_file(self.env, const.MODULE_NAME, view_file, None,
                           mode='update', noupdate=False, kind='data')
                _logger.info("%s: Invoice report view loaded successfully", const.MODULE_NAME)
                self.env.cr.commit()
            else:
                _logger.warning("%s: Invoice report file not found at %s", const.MODULE_NAME, view_file)
        except Exception as e:
            _logger.warning("%s: Could not load invoice report view: %s", const.MODULE_NAME, str(e), exc_info=True)
