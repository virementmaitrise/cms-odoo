from collections import namedtuple

PAYMENT_PROVIDER_NAME = 'virementmaitrise'
MODULE_NAME = 'payment_virementmaitrise'
DISPLAY_NAME = 'Virement Maitrisé'
SDK_IMPORT_NAME = 'virementmaitrise'  # SDK package name for dynamic import

# The codes of the payment methods to activate when Virement Maitrisé is activated.
DEFAULT_PAYMENT_METHOD_CODES = {
    # Only bank transfer payment method
    'virementmaitrise_bank_transfer',
}

PMT = namedtuple('PaymentMethodType', ['name', 'countries', 'currencies', 'recurrence'])
PAYMENT_METHOD_TYPES = [
    # Only bank transfer payment method
    PMT('virementmaitrise_bank_transfer', [], ['eur'], 'punctual'),
]
# Mapping of transaction states to Virement Maitrisé Payment state and status.
INTENT_STATUS_MAPPING = {
    'draft': (
        # session status
        # transfer state
    ),
    'pending': (
        # session status
        'payment_pending',
        'order_created',
        # transfer state
        'processing',
        'pending',
        'authorized',
        'accepted',
    ),
    'done': (
        # session status
        'payment_created',
        'payment_partial',
        'insufficient',
        # transfer state
        'completed',
        'received',
        'sent',
        'overpaid',
    ),
    'cancel': (
        # session status
        'sca_required',
        'provider_required',
        'payment_cancelled',
        'payment_expired',
        # transfer state
        'rejected',
        'returned',
    ),
    'error': (
        # session status
        'payment_error',
        'payment_unsuccessful',
        # transfer state
    )
}

# Events that must be subscribed on the Fintecture webhook configuration for this module to
# receive the full payment lifecycle covered by INTENT_STATUS_MAPPING above. Fintecture event
# names follow the "payment_session.<category>.<value>" format - "checkout.session.completed"
# (the previous value here) is not a real Fintecture event name.
WEBHOOK_HANDLED_EVENTS = [
    'payment_session.status.payment_created',
    'payment_session.status.payment_pending',
    'payment_session.status.payment_unsuccessful',
    'payment_session.status.payment_cancelled',
    'payment_session.status.payment_expired',
    'payment_session.status.payment_partial',
    'payment_session.status.order_created',
    'payment_session.transfer_states.pending',
    'payment_session.transfer_states.processing',
    'payment_session.transfer_states.completed',
    'payment_session.transfer_states.sent',
    'payment_session.transfer_states.received',
    'payment_session.transfer_states.insufficient',
    'payment_session.transfer_states.overpaid',
    'payment_session.transfer_states.returned',
    'payment_session.transfer_states.rejected',
]

CALLBACK_URL = f'/payment/{PAYMENT_PROVIDER_NAME}/callback'
WEBHOOK_URL = f'/payment/{PAYMENT_PROVIDER_NAME}/webhook'