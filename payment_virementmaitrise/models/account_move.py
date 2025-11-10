import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)

# This file provides account.move extensions for invoice QR code features
# It will only define the model if the 'account' module is installed

try:
    from ..const import PAYMENT_PROVIDER_NAME
except ImportError:
    _logger.warning("payment_fintecture.const not found, account_move integration disabled")
    PAYMENT_PROVIDER_NAME = 'fintecture'


# Check if account.move model exists before trying to inherit from it
# This prevents "Model 'account.move' does not exist in registry" errors
try:
    # Try to get a reference to the parent model to ensure it exists
    # This will raise an error if account module is not installed
    from odoo.modules.registry import Registry
    import threading

    db_name = getattr(threading.current_thread(), 'dbname', None)
    _account_available = False

    if db_name:
        try:
            registry = Registry(db_name)
            _account_available = 'account.move' in registry
        except Exception:
            _account_available = False

    if not _account_available:
        _logger.debug("account.move model not available, skipping AccountMove extension")
        # Don't define the class at all
        raise ImportError("account.move not in registry")

    # Only define the class if account.move exists
    class AccountMove(models.Model):
        _inherit = 'account.move'

        fintecture_is_enabled = fields.Boolean(
            string="Fintecture enabled",
            compute="_compute_fintecture_payment_data"
        )
        fintecture_payment_link = fields.Char(
            string="Fintecture payment link",
            compute="_compute_fintecture_payment_data"
        )
        fintecture_payment_qr = fields.Binary(
            string="Fintecture QR",
            compute="_compute_fintecture_payment_data"
        )
        fintecture_invoice_link_qr = fields.Boolean(
            string="Include link/QR in invoices",
            compute="_compute_fintecture_config"
        )

        def _get_fintecture_provider(self):
            """Get the Fintecture payment provider for current company."""
            return self.env['payment.provider'].sudo().search([
                ('code', '=', PAYMENT_PROVIDER_NAME),
                ('company_id', '=', self.env.company.id)
            ], limit=1)

        def _compute_fintecture_config(self):
            """Get provider configuration."""
            provider = self._get_fintecture_provider()
            for move in self:
                if provider:
                    move.fintecture_invoice_link_qr = provider.fintecture_invoice_link_qr
                else:
                    move.fintecture_invoice_link_qr = False

        def _post(self, soft=True):
            """Override _post to reconcile payments when invoice is posted."""
            # Call parent to post the invoice
            posted = super()._post(soft=soft)

            # After posting, try to reconcile any existing payments from eCommerce orders
            for move in posted:
                if move.move_type == 'out_invoice' and move.payment_state != 'paid':
                    self._reconcile_existing_payment(move)

            return posted

        def _reconcile_existing_payment(self, invoice):
            """Reconcile existing payment from sale order with newly created invoice.

            This handles the case where:
            1. eCommerce order paid → Payment created (in_process state)
            2. Invoice created later manually
            3. Need to link payment to invoice
            """
            # Find sale order linked to this invoice
            sale_orders = self.env['sale.order'].sudo().search([
                ('invoice_ids', 'in', [invoice.id])
            ])

            if not sale_orders:
                return

            # Find payment transactions from the sale order
            transactions = sale_orders.transaction_ids.filtered(
                lambda t: t.state == 'done' and t.provider_code == PAYMENT_PROVIDER_NAME
            )

            if not transactions:
                return

            for tx in transactions:
                # Find ALL payments created for this transaction (not just one)
                # This is important for partial payments where multiple payments exist per transaction
                payments = self.env['account.payment'].sudo().search([
                    ('payment_transaction_id', '=', tx.id),
                    ('state', 'in', ['posted', 'in_process']),
                ])

                if not payments:
                    continue

                _logger.info('|AccountMove| Found %s existing payment(s) for invoice %s, attempting reconciliation',
                           len(payments), invoice.name)

                # Reconcile each payment with the invoice
                for payment in payments:
                    if not payment.move_id:
                        _logger.debug('|AccountMove| Payment %s has no move_id, skipping', payment.name)
                        continue

                    # Get receivable lines from both invoice and payment
                    invoice_lines = invoice.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                    )
                    payment_lines = payment.move_id.line_ids.filtered(
                        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                    )

                    lines_to_reconcile = invoice_lines + payment_lines

                    if len(lines_to_reconcile) >= 2:
                        try:
                            lines_to_reconcile.reconcile()

                            # After reconciliation, update payment state
                            payment.invalidate_recordset(['is_reconciled', 'is_matched'])
                            invoice.invalidate_recordset(['payment_state'])

                            # Force recompute by accessing the fields
                            is_reconciled = payment.is_reconciled
                            is_matched = payment.is_matched

                            # If payment is now fully reconciled, transition to 'paid'
                            if payment.state == 'in_process' and (is_reconciled or is_matched):
                                payment.write({'state': 'paid'})
                                _logger.info('|AccountMove| Reconciled payment %s with invoice %s (state: paid)',
                                           payment.name, invoice.name)
                            else:
                                _logger.debug('|AccountMove| Reconciled payment %s (state: %s)', payment.name, payment.state)

                        except Exception as e:
                            _logger.warning('|AccountMove| Error reconciling payment %s: %s', payment.name, str(e))
                    else:
                        _logger.debug('|AccountMove| Not enough lines for %s (found %s, need 2)',
                                    payment.name, len(lines_to_reconcile))

        def _compute_fintecture_payment_data(self):
            """Compute Fintecture payment link and QR code for invoices."""
            _logger.info('|AccountMove| Computing Fintecture payment data for %s invoices', len(self))

            provider = self._get_fintecture_provider()

            for move in self:
                # Reset values
                move.fintecture_is_enabled = False
                move.fintecture_payment_link = False
                move.fintecture_payment_qr = False

                # Check if provider is enabled
                if not provider or provider.state == 'disabled':
                    _logger.debug('|AccountMove| Fintecture provider disabled for invoice %s', move.name)
                    continue

                # Check if invoice is in valid state
                if move.state == 'draft':
                    _logger.debug('|AccountMove| Invoice %s is in draft state, skipping', move.name)
                    continue

                move.fintecture_is_enabled = True

                # Look for existing transaction
                trx = move.transaction_ids.filtered(
                    lambda x: x.provider_id and x.provider_id.code == PAYMENT_PROVIDER_NAME
                )

                if not trx:
                    _logger.debug('|AccountMove| No existing transaction for invoice %s, creating one', move.name)

                    # Get the default payment method for this provider
                    payment_method = self.env['payment.method'].sudo().search([
                        ('code', '=', f'{PAYMENT_PROVIDER_NAME}_bank_transfer'),
                    ], limit=1)

                    if not payment_method:
                        _logger.error('|AccountMove| No payment method found for provider %s', PAYMENT_PROVIDER_NAME)
                        continue

                    # Create transaction
                    trx = self.env['payment.transaction'].sudo().create({
                        'provider_id': provider.id,
                        'payment_method_id': payment_method.id,
                        'reference': move.name,
                        'amount': move.amount_residual,
                        'currency_id': move.currency_id.id,
                        'partner_id': move.partner_id.id,
                        'operation': 'online_redirect',
                    })
                    move.transaction_ids = [(4, trx.id)]
                else:
                    trx = trx[0]
                    _logger.debug('|AccountMove| Found existing transaction %s for invoice %s', trx.id, move.name)

                # Get processing values (this creates the Fintecture URL)
                try:
                    trx._get_processing_values()
                    move.fintecture_payment_link = trx.fintecture_url

                    _logger.info('|AccountMove| Generating QR code for invoice %s (URL: %s)', move.name, trx.fintecture_url)

                    if trx.fintecture_url:
                        move.fintecture_payment_qr = trx.fintecture_create_qr()
                        _logger.info('|AccountMove| QR code generated successfully for invoice %s', move.name)
                    else:
                        _logger.warning('|AccountMove| No Fintecture URL for invoice %s', move.name)

                except Exception as e:
                    _logger.error('|AccountMove| Error generating payment data for invoice %s: %s', move.name, str(e))
                    _logger.exception('|AccountMove| Full exception:')

except ImportError:
    # account.move not available - this is expected when account module is not installed
    _logger.debug("account.move model not available, AccountMove extension not loaded")
