from . import controllers
from . import models
from . import const

from odoo.addons.payment import setup_provider, reset_payment_provider
from odoo.tools import convert_file
import logging
import os

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Post-installation hook for payment provider module.
    Sets up the payment provider and loads invoice report view if account module exists.

    IMPORTANT: This only runs on NEW INSTALLS, not on upgrades.
    For upgrades, the view is loaded when you RESTART Odoo (checked at startup).
    If you upgrade without restarting, you need to restart Odoo to reload the view.
    """
    # Use constants from const.py
    setup_provider(env, const.PAYMENT_PROVIDER_NAME)

    # Load invoice report view if account module is installed
    _load_invoice_report_view(env)


def _load_invoice_report_view(env):
    """
    Helper function to load invoice report view.
    This is called from post_init_hook during installation.

    :param env: Odoo environment
    """
    # Check if account module is installed
    account_module = env['ir.module.module'].search([
        ('name', '=', 'account'),
        ('state', '=', 'installed')
    ], limit=1)

    if not account_module:
        _logger.debug("%s: Account module not installed, skipping invoice report view", const.MODULE_NAME)
        return

    _logger.info("%s: Account module detected, loading invoice report view", const.MODULE_NAME)

    try:
        module_path = os.path.dirname(os.path.abspath(__file__))
        view_file = os.path.join(module_path, 'views', 'account_invoice_report.xml')

        if os.path.exists(view_file):
            _logger.info("%s: Loading %s", const.MODULE_NAME, view_file)
            convert_file(env, const.MODULE_NAME, view_file, None,
                       mode='update', noupdate=False, kind='data')
            _logger.info("%s: Invoice report view loaded successfully", const.MODULE_NAME)
        else:
            _logger.warning("%s: Invoice report file not found at %s", const.MODULE_NAME, view_file)
    except Exception as e:
        _logger.warning("%s: Could not load invoice report view: %s", const.MODULE_NAME, str(e), exc_info=True)



def uninstall_hook(env):
    """Uninstallation hook for payment provider module."""
    reset_payment_provider(env, const.PAYMENT_PROVIDER_NAME)
