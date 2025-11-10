import logging
import pprint
import collections

from odoo import http
from odoo.http import request

from odoo.addons.payment.controllers.post_processing import PaymentPostProcessing
from ..const import CALLBACK_URL, WEBHOOK_URL, PAYMENT_PROVIDER_NAME

_logger = logging.getLogger(__name__)


class FintectureController(http.Controller):

    @http.route(route=CALLBACK_URL, type='http', auth='public', methods=['GET'])
    def fintecture_callback(self, **data):
        """ Display payment status after user returns from Fintecture payment page.

        SECURITY: Callback URL is READ-ONLY and informational only.
        GET parameters are untrusted (user can modify them in browser).
        Only the cryptographically signed webhook can update transaction state.

        :param dict data: The callback data (UNTRUSTED - for display purposes only)
        :return: Redirect to payment status page
        """
        _logger.info('|FintectureController| Received callback from Fintecture (informational only)')
        _logger.info('|FintectureController| Callback data (UNTRUSTED): %s', data)

        # Retrieve the transaction based on the session_id included in the return url
        # This is safe - we're only looking up the transaction, not trusting callback data
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                PAYMENT_PROVIDER_NAME, data
            )
            _logger.info('|FintectureController| Found transaction: %s (current state: %s)',
                        tx_sudo.reference, tx_sudo.state)
        except Exception as e:
            _logger.error('|FintectureController| Failed to retrieve transaction: %s', str(e))
            # Redirect to payment status anyway - Odoo will show appropriate error
            return request.redirect('/payment/status')

        # Log callback parameters for debugging (but don't trust them)
        callback_status = data.get('status', 'unknown')
        callback_transfer_state = data.get('transfer_state', 'unknown')
        _logger.info('|FintectureController| Callback claims status=%s, transfer_state=%s (NOT TRUSTED)',
                    callback_status, callback_transfer_state)
        _logger.info('|FintectureController| Actual transaction state from database: %s', tx_sudo.state)

        # Check if webhook has processed the transaction yet
        if tx_sudo.state == 'draft':
            # Webhook hasn't processed yet - show processing message
            _logger.info('|FintectureController| Transaction still in draft state - webhook processing in progress')
            request.session['payment_processing_message'] = True
        elif tx_sudo.state == 'pending':
            _logger.info('|FintectureController| Transaction pending - awaiting payment confirmation')

        _logger.info('|FintectureController| Callback complete, redirecting user to /payment/status')
        _logger.info('|FintectureController| Webhook will update transaction state asynchronously')

        # Register transaction in session so /payment/status can find it
        # This is required for the status page to display the correct transaction
        PaymentPostProcessing.monitor_transaction(tx_sudo)
        _logger.info('|FintectureController| Transaction %s registered in session for monitoring', tx_sudo.reference)

        # Redirect the user to the standard Odoo payment status page
        # The page will display current transaction state from database
        return request.redirect('/payment/status')

    @http.route(route=WEBHOOK_URL, methods=['POST'], type='http', auth='public', csrf=False)
    def fintecture_webhook(self, **kwargs):
        """ Process all events sent by Fintecture to the webhook.

        SECURITY: Webhook is the ONLY TRUSTED source for payment state updates.
        All webhook data is cryptographically signed and verified before processing.
        This endpoint is responsible for all critical operations:
        - Updating transaction state
        - Creating payment records
        - Reconciling invoices
        - Confirming orders

        :return: An empty string to acknowledge the notification with an HTTP 200 response
        :rtype: str
        """
        _logger.info('|FintectureController| Received a webhook request and now it will be processed...')

        form_data = collections.OrderedDict(request.httprequest.form)
        _logger.debug("|FintectureController| received form data: \n%s", pprint.pformat(form_data))

        try:
            state = kwargs.get('state', '')
            if not isinstance(state, str):
                _logger.warning(
                    '|FintectureController| Webhook handler receives an invalid state ({})...'.format(state))
                return ''

            # Validate state parameter format (company_id/connection_id)
            if not self._parse_state_param(state):
                _logger.warning('|FintectureController| Invalid state parameter format')
                return ''

            event = self._verify_webhook_signature(form_data)
            if event is not False:
                session_id = event.get('session_id', 'unknown')
                status = event.get('status', '')
                transfer_state = event.get('transfer_state', '')

                if event['status'] in ['payment_created', 'payment_partial'] and event['transfer_state'] in [
                    'completed', 'received', 'insufficient', 'overpaid']:
                    _logger.info("|FintectureController| Processing webhook for session=%s (status=%s, transfer_state=%s)",
                               session_id, status, transfer_state)

                    # Handle the notification data to update transaction status
                    tx_sudo = request.env['payment.transaction'].sudo()._handle_notification_data(
                        PAYMENT_PROVIDER_NAME, form_data
                    )

                    # ================================================================
                    # CRITICAL: Post-process transaction immediately
                    # Webhooks don't have user sessions, so we can't use monitor_transaction()
                    # Instead, we directly trigger post-processing to create account.payment records
                    # ================================================================
                    if tx_sudo:
                        _logger.info("|FintectureController| Post-processing transaction %s (state: %s) from webhook",
                                   tx_sudo.reference, tx_sudo.state)

                        # ================================================================
                        # IMPORTANT: Check for additional payment FIRST (before idempotency check)
                        #
                        # Partial payments can be detected using multiple indicators:
                        # 1. transaction_id: Unique ID for each transfer (may not be present for manual transfers)
                        # 2. received_amount: Total amount received across all payments
                        # 3. last_transaction_amount: Amount of this specific payment
                        #
                        # This check must happen regardless of sale order state
                        # ================================================================

                        # Get existing payments for this transaction
                        existing_payments = request.env['account.payment'].sudo().search([
                            ('payment_transaction_id', '=', tx_sudo.id),
                            ('state', 'in', ['posted', 'in_process', 'paid']),
                        ])
                        existing_payments_count = len(existing_payments)
                        total_existing_amount = sum(existing_payments.mapped('amount'))

                        _logger.debug("|FintectureController| Existing payments: %s, total amount: %s",
                                     existing_payments_count, total_existing_amount)

                        # Detect additional payment using multiple strategies
                        is_additional_payment = False
                        additional_payment_amount = 0
                        detection_method = None

                        if tx_sudo.state == 'done' and existing_payments_count > 0:
                            # Strategy 1: Check transaction_id (for PIS/instant transfers)
                            fintecture_transaction_id = form_data.get('transaction_id', None)
                            if fintecture_transaction_id:
                                is_additional_payment = True
                                detection_method = 'transaction_id'
                                _logger.debug("|FintectureController| Additional payment detected via transaction_id: %s",
                                            fintecture_transaction_id)

                            # Strategy 2: Compare received_amount vs existing payments (for manual transfers)
                            received_amount_str = form_data.get('received_amount', None)
                            if received_amount_str:
                                try:
                                    received_amount = float(received_amount_str)
                                    # If received_amount > sum of existing payments, there's a new payment
                                    if received_amount > total_existing_amount + 0.01:  # 0.01 tolerance for float comparison
                                        is_additional_payment = True
                                        additional_payment_amount = received_amount - total_existing_amount
                                        detection_method = 'received_amount'
                                        _logger.debug("|FintectureController| Additional payment detected via received_amount: "
                                                    "total=%s, existing=%s, new=%s",
                                                    received_amount, total_existing_amount, additional_payment_amount)
                                except (ValueError, TypeError) as e:
                                    _logger.warning("|FintectureController| Invalid received_amount: %s", received_amount_str)

                            # Strategy 3: Use last_transaction_amount as fallback
                            if not is_additional_payment:
                                last_transaction_amount_str = form_data.get('last_transaction_amount', None)
                                if last_transaction_amount_str:
                                    try:
                                        last_transaction_amount = float(last_transaction_amount_str)
                                        # If we have a last_transaction_amount and it's different from any existing payment
                                        # and total would be different, it's likely a new payment
                                        if not any(abs(p.amount - last_transaction_amount) < 0.01 for p in existing_payments):
                                            is_additional_payment = True
                                            additional_payment_amount = last_transaction_amount
                                            detection_method = 'last_transaction_amount'
                                            _logger.debug("|FintectureController| Additional payment detected via last_transaction_amount: %s",
                                                        last_transaction_amount)
                                    except (ValueError, TypeError) as e:
                                        _logger.warning("|FintectureController| Invalid last_transaction_amount: %s",
                                                      last_transaction_amount_str)

                        if is_additional_payment:
                            _logger.info("|FintectureController| Additional payment detected for %s (method: %s, amount: %s)",
                                       tx_sudo.reference, detection_method, additional_payment_amount)
                            try:
                                self._handle_additional_payment(tx_sudo, form_data)
                            except Exception as e:
                                _logger.error("|FintectureController| Error handling additional payment: %s", str(e))
                                _logger.exception("|FintectureController| Full error:")
                            # Return early - additional payment handled
                            return ''

                        # Check if transaction needs post-processing (idempotency check)
                        # Look for associated sale order to check if already confirmed
                        sale_order = request.env['sale.order'].sudo().search([
                            ('transaction_ids', 'in', tx_sudo.id)
                        ], limit=1)

                        if tx_sudo.state == 'done' and sale_order and sale_order.state in ['sale', 'done']:
                            _logger.info("|FintectureController| Transaction %s already post-processed (sale order %s in state %s)",
                                       tx_sudo.reference, sale_order.name, sale_order.state)
                            # Regular duplicate webhook - just try reconciliation
                            try:
                                self._reconcile_payment_with_invoice(tx_sudo)
                            except Exception as e:
                                _logger.warning("|FintectureController| Reconciliation attempt failed: %s", str(e))
                        else:
                            # Use a savepoint to isolate transaction errors
                            # This allows us to rollback just this operation if it fails (e.g., duplicate keys)
                            # without aborting the entire HTTP request transaction
                            try:
                                with request.env.cr.savepoint():
                                    # Directly trigger post-processing (creates account.payment and reconciles)
                                    tx_sudo._post_process()
                                    _logger.info("|FintectureController| Successfully post-processed transaction %s", tx_sudo.reference)

                                    # After post-processing, reconcile payment with invoice if needed
                                    self._reconcile_payment_with_invoice(tx_sudo)

                            except Exception as e:
                                # Savepoint automatically rolled back the failed operation
                                # Transaction is now clean and we can safely continue
                                error_msg = str(e)

                                # Check if this is a concurrent processing error (expected when multiple webhooks arrive)
                                is_concurrent_error = (
                                    'duplicate key value violates unique constraint' in error_msg or
                                    'could not serialize access due to concurrent update' in error_msg
                                )

                                if is_concurrent_error:
                                    # This is normal - Fintecture sends multiple webhooks simultaneously
                                    # The parallel request already completed successfully, nothing more to do
                                    _logger.info("|FintectureController| Concurrent webhook detected for transaction %s, already processed by parallel request",
                                                  tx_sudo.reference)
                                else:
                                    # This is an unexpected error that needs investigation
                                    _logger.error("|FintectureController| Unexpected error during post-processing of transaction %s: %s",
                                                tx_sudo.reference, error_msg)
                                    _logger.exception("|FintectureController| Full post-processing error:")
                                    # Don't raise - return 200 to prevent webhook retries
                                    # The error is logged and can be investigated
                    else:
                        _logger.warning("|FintectureController| No transaction returned from _handle_notification_data")
                else:
                    _logger.info("|FintectureController| Received webhook of payment with session={0}) has the "
                                 " status='{1}' and transfer_state={2}".format(
                        event.get('session_id'),
                        event.get('status'),
                        event.get('transfer_state')
                    ))
            else:
                _logger.error("|FintectureController| Invalid received webhook content. Canceling processing...")
        except Exception as e:
            _logger.error("""
                |FintectureController| An error occur when manage feedback data 
                received from webhook notification...
            """)
            _logger.error('|FintectureController| ERROR: %s' % str(e))

        return ''

    @staticmethod
    def _handle_additional_payment(tx_sudo, notification_data):
        """Handle additional partial payment for an already-paid transaction.

        When a user makes multiple payments for one order, Fintecture sends multiple webhooks.
        This method creates additional payment records.

        Payment amount is determined using multiple strategies:
        1. last_transaction_amount: Amount of this specific payment (preferred)
        2. Calculate from received_amount - existing payments (for manual transfers)
        3. transaction_amount: Fallback field

        :param tx_sudo: The payment transaction recordset
        :param notification_data: The webhook data containing amounts
        """
        from odoo import fields

        # Determine payment amount using multiple strategies
        payment_amount = 0

        # Get existing payments total
        existing_payments = request.env['account.payment'].sudo().search([
            ('payment_transaction_id', '=', tx_sudo.id),
            ('state', 'in', ['posted', 'in_process', 'paid']),
        ])
        total_existing_amount = sum(existing_payments.mapped('amount'))

        # Strategy 1: Use last_transaction_amount (most accurate for partial payments)
        if notification_data.get('last_transaction_amount'):
            try:
                payment_amount = float(notification_data.get('last_transaction_amount'))
                _logger.debug('|FintectureController| Using last_transaction_amount: %s', payment_amount)
            except (ValueError, TypeError):
                pass

        # Strategy 2: Calculate from received_amount (total) - existing payments
        if payment_amount <= 0 and notification_data.get('received_amount'):
            try:
                received_amount = float(notification_data.get('received_amount'))
                payment_amount = received_amount - total_existing_amount
                _logger.debug('|FintectureController| Calculated from received_amount: %s - %s = %s',
                            received_amount, total_existing_amount, payment_amount)
            except (ValueError, TypeError):
                pass

        # Strategy 3: Use transaction_amount as fallback
        if payment_amount <= 0 and notification_data.get('transaction_amount'):
            try:
                payment_amount = float(notification_data.get('transaction_amount'))
                _logger.debug('|FintectureController| Using transaction_amount: %s', payment_amount)
            except (ValueError, TypeError):
                pass

        if payment_amount <= 0:
            _logger.warning('|FintectureController| Invalid payment amount: %s', payment_amount)
            return

        _logger.info('|FintectureController| Creating additional payment of %s EUR for %s (existing: %s EUR)',
                   payment_amount, tx_sudo.reference, total_existing_amount)

        # Count existing payments
        existing_payments_count = request.env['account.payment'].sudo().search_count([
            ('payment_transaction_id', '=', tx_sudo.id),
            ('state', 'in', ['posted', 'in_process', 'paid']),
        ])

        # Get invoice linked to this transaction (if exists)
        # For eCommerce orders, invoice might not exist yet - we'll create standalone payment
        invoices = request.env['account.move'].sudo().search([('transaction_ids', 'in', [tx_sudo.id])])

        if invoices:
            invoice = invoices[0]
            _logger.debug('|FintectureController| Invoice %s found, will reconcile immediately', invoice.name)
            partner_id = invoice.partner_id.id
            currency_id = invoice.currency_id.id
        else:
            # No invoice yet (eCommerce scenario) - use transaction's partner and currency
            _logger.debug('|FintectureController| No invoice - creating standalone payment for later reconciliation')
            partner_id = tx_sudo.partner_id.id
            currency_id = tx_sudo.currency_id.id
            invoice = None

        # Get journal and payment method
        journal = tx_sudo.provider_id.journal_id if tx_sudo.provider_id.journal_id else request.env['account.journal'].sudo().search([('type', '=', 'bank')], limit=1)

        # Get Fintecture payment method line for this journal
        payment_method_line = request.env['account.payment.method.line'].sudo().search([
            ('journal_id', '=', journal.id),
            ('payment_method_id.code', '=', PAYMENT_PROVIDER_NAME),
        ], limit=1)

        if not payment_method_line:
            _logger.error('|FintectureController| No Fintecture payment method line found for journal %s', journal.name if journal else 'None')
            return

        # Create payment
        payment_vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner_id,
            'amount': payment_amount,
            'currency_id': currency_id,
            'date': fields.Date.context_today(request.env['payment.transaction']),
            'payment_reference': f'{tx_sudo.reference} - Payment #{existing_payments_count + 1}',
            'journal_id': journal.id,
            'payment_method_line_id': payment_method_line.id if payment_method_line else False,
            'payment_transaction_id': tx_sudo.id,
        }

        new_payment = request.env['account.payment'].sudo().create(payment_vals)
        new_payment.action_post()
        _logger.info('|FintectureController| Created additional payment %s (%s EUR)',
                     new_payment.name, new_payment.amount)

        # Reconcile with invoice (if invoice exists)
        if invoice:
            new_payment.invalidate_recordset()
            invoice.invalidate_recordset()

            payment_move = new_payment.move_id
            if not payment_move:
                _logger.error('|FintectureController| Payment has no move_id after action_post()')
                return

            # Get receivable lines
            invoice_lines = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )
            payment_lines = payment_move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )

            lines_to_reconcile = invoice_lines + payment_lines

            if len(lines_to_reconcile) >= 2:
                lines_to_reconcile.reconcile()

                # Refresh and update payment state
                invoice.invalidate_recordset()
                new_payment.invalidate_recordset()

                new_payment.invalidate_recordset(['is_reconciled', 'is_matched'])
                invoice.invalidate_recordset(['payment_state'])

                # Force recompute by accessing the fields
                _ = new_payment.is_reconciled
                _ = invoice.payment_state

                # Update payment state based on reconciliation
                # A payment should be marked 'paid' when:
                # 1. It's currently in 'in_process' state
                # 2. AND one of these conditions:
                #    a) The payment is fully reconciled (is_reconciled=True)
                #    b) The invoice is fully paid (payment_state='paid')
                #
                # This handles both partial payments (where invoice isn't fully paid yet)
                # and final payments (where invoice becomes fully paid)
                if new_payment.state == 'in_process':
                    if new_payment.is_reconciled or invoice.payment_state == 'paid':
                        new_payment.write({'state': 'paid'})
                        _logger.info('|FintectureController| Payment %s state updated to paid (is_reconciled=%s, invoice payment_state=%s)',
                                   new_payment.name, new_payment.is_reconciled, invoice.payment_state)

                _logger.info('|FintectureController| Reconciled payment %s with invoice %s',
                           new_payment.name, invoice.name)

        # Check if order should be confirmed based on webhook data
        # Fintecture sends status=payment_created when full payment is received
        # received_amount gives the TOTAL amount received across all partial payments
        webhook_status = notification_data.get('status')
        received_amount = float(notification_data.get('received_amount', 0))

        # Find sale order linked to this transaction
        sale_order = request.env['sale.order'].sudo().search([
            ('transaction_ids', 'in', tx_sudo.id)
        ], limit=1)

        if sale_order and sale_order.state in ['draft', 'sent']:
            # Confirm order if status=payment_created (full payment received)
            # OR if received_amount covers the order amount
            should_confirm = (
                webhook_status == 'payment_created' or
                received_amount >= tx_sudo.amount
            )

            if should_confirm:
                try:
                    sale_order.action_confirm()
                    _logger.info('|FintectureController| Sale order %s confirmed (full payment received: %s EUR)',
                                 sale_order.name, received_amount)
                except Exception as e:
                    _logger.warning('|FintectureController| Failed to confirm sale order %s: %s', sale_order.name, str(e))

    @staticmethod
    def _reconcile_payment_with_invoice(tx_sudo):
        """Reconcile payment created by _post_process() with the invoice.

        :param tx_sudo: The payment transaction recordset
        """
        # Find the payment created by _post_process()
        payments = request.env['account.payment'].sudo().search([
            ('payment_transaction_id', '=', tx_sudo.id),
            ('state', 'in', ['posted', 'in_process']),
        ])

        if not payments:
            _logger.debug('|FintectureController| No payment found for %s', tx_sudo.reference)
            return

        for payment in payments:
            # Get invoice linked to this transaction
            invoices = request.env['account.move'].sudo().search([('transaction_ids', 'in', tx_sudo.id)])
            if not invoices:
                _logger.debug('|FintectureController| No invoice for payment %s (eCommerce order)', payment.name)
                continue

            invoice = invoices[0]

            # Check if already reconciled
            if invoice.payment_state == 'paid' and payment.is_matched:
                _logger.debug('|FintectureController| Payment %s already matched with paid invoice', payment.name)
                if payment.state == 'in_process':
                    payment.write({'state': 'paid'})
                continue

            # Reconcile payment with invoice
            payment.invalidate_recordset()
            invoice.invalidate_recordset()

            payment_move = payment.move_id
            if not payment_move:
                _logger.warning('|FintectureController| Payment %s has no move_id', payment.name)
                continue

            # Get receivable lines from both invoice and payment
            invoice_lines = invoice.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )
            payment_lines = payment_move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
            )

            lines_to_reconcile = invoice_lines + payment_lines

            if len(lines_to_reconcile) >= 2:
                try:
                    lines_to_reconcile.reconcile()

                    # Refresh records after reconciliation
                    invoice.invalidate_recordset()
                    payment.invalidate_recordset()

                    # Trigger payment state update
                    payment.invalidate_recordset(['is_reconciled', 'is_matched'])
                    invoice.invalidate_recordset(['payment_state'])

                    # Force recompute by accessing the fields
                    _ = payment.is_reconciled
                    _ = invoice.payment_state

                    # Update payment state based on reconciliation
                    # A payment should be marked 'paid' when:
                    # 1. It's currently in 'in_process' state
                    # 2. AND one of these conditions:
                    #    a) The payment is fully reconciled (is_reconciled=True)
                    #    b) The invoice is fully paid (payment_state='paid')
                    if payment.state == 'in_process':
                        if payment.is_reconciled or invoice.payment_state == 'paid':
                            payment.write({'state': 'paid'})
                            _logger.debug('|FintectureController| Payment %s state updated to paid (is_reconciled=%s, invoice payment_state=%s)',
                                       payment.name, payment.is_reconciled, invoice.payment_state)

                    _logger.debug('|FintectureController| Reconciled %s with %s (invoice payment_state: %s)',
                               payment.name, invoice.name, invoice.payment_state)
                except Exception as e:
                    _logger.warning('|FintectureController| Error reconciling %s: %s', payment.name, str(e))
            else:
                _logger.debug('|FintectureController| Not enough lines to reconcile for %s (found %s)',
                             payment.name, len(lines_to_reconcile))

    @staticmethod
    def _parse_state_param(state):
        """Parse state parameter from Fintecture callback.

        Format: company_id/connection_id

        :param str state: The state parameter from Fintecture callback
        :return: Dict with parsed state components or False if invalid
        :rtype: dict or bool
        """
        state_params = state.split('/')
        if not state_params or len(state_params) < 2:
            _logger.warning('|FintectureController| State param parser receives an invalid state ({})...'.format(state))
            return False

        _logger.debug('|FintectureController| _parse_state_param(): state: ({})...'.format(state))
        _logger.debug('|FintectureController| _parse_state_param(): state_params: ({})...'.format(state_params))

        company_id = state_params[0]
        connection_id = state_params[1]

        _logger.debug('|FintectureController| _parse_state_param(): company_id: ({})...'.format(company_id))
        _logger.debug('|FintectureController| _parse_state_param(): connection_id: ({})...'.format(connection_id))

        return {
            'company_id': company_id,
            'connection_id': connection_id,
        }

    @staticmethod
    def _verify_webhook_signature(form_data):
        _logger.info('|FintectureController| Verifying webhook signature...')

        tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
            PAYMENT_PROVIDER_NAME, form_data
        )

        if not tx_sudo:
            _logger.error("|FintectureController| Invalid received form data which is unrelated to a payment provider")
            return False

        payload = request.httprequest.form
        received_digest = request.httprequest.headers.get("Digest", None)
        received_signature = request.httprequest.headers.get("Signature", None)
        received_request_id = request.httprequest.headers.get("X-Request-ID", None)

        _logger.debug("|FintectureController| payload: {}".format(payload))
        _logger.debug("|FintectureController| received_digest: {}".format(received_digest))
        _logger.debug("|FintectureController| received_signature: {}".format(received_signature))
        _logger.debug("|FintectureController| received_request_id: {}".format(received_request_id))

        # SECURITY: Verify signature using Fintecture SDK (checks signature against private key)
        # This prevents anyone from sending fake payment confirmations
        event = tx_sudo.provider_id.fintecture_webhook_signature(
            payload, received_digest, received_signature, received_request_id
        )

        _logger.debug("|FintectureController| validation result of webhook signature: {}".format(event))

        return event
