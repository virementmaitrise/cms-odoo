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
        'payment_unsuccessful',
        # transfer state
        'rejected',
    ),
    'error': (
        # session status
        'payment_error',
        # transfer state
    )
}

# Events which are handled by the webhook
WEBHOOK_HANDLED_EVENTS = [
    'checkout.session.completed',
]

CALLBACK_URL = f'/payment/{PAYMENT_PROVIDER_NAME}/callback'
WEBHOOK_URL = f'/payment/{PAYMENT_PROVIDER_NAME}/webhook'