import logging

_logger = logging.getLogger(__name__)

from . import payment_provider
from . import payment_token
from . import payment_transaction
from . import res_company
from . import invoice_view_loader

# Conditionally import account_move only if it can be safely loaded
# The account_move.py file itself will check if account.move exists
try:
    from . import account_move
    _logger.debug("payment_fintecture: account_move integration loaded")
except Exception as e:
    _logger.debug("payment_fintecture: account_move not loaded: %s", type(e).__name__)
