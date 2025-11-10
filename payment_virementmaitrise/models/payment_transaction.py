import logging
import pprint
import uuid
import qrcode
import base64
import json

from io import BytesIO
from datetime import date

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.payment import utils as payment_utils
from .. import utils as fintecture_utils
from ..const import INTENT_STATUS_MAPPING, PAYMENT_PROVIDER_NAME

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    fintecture_payment_intent = fields.Char(
        string="Fintecture Payment Intent ID",
        readonly=True
    )
    fintecture_url = fields.Char(
        string="Fintecture URL"
    )

    # ============================================================================
    # VIBAN FIELDS - Currently disabled, keep for future use
    # These fields extract IBAN details from fintecture_virtual_beneficiary
    # ============================================================================
    # fintecture_virtual_beneficiary = fields.Text(
    #     string="Fintecture Virtual Beneficiary"
    # )
    # fintecture_iban_holder = fields.Char(
    #     string="Fintecture IBAN holder",
    #     compute="_compute_fintecture_iban"
    # )
    # fintecture_iban_account = fields.Char(
    #     string="Fintecture IBAN account",
    #     compute="_compute_fintecture_iban"
    # )
    # fintecture_iban_swift_bic = fields.Char(
    #     string="Fintecture IBAN SWIFT/BIC",
    #     compute="_compute_fintecture_iban"
    # )
    # fintecture_iban_bank_name = fields.Char(
    #     string="Fintecture IBAN bank name",
    #     compute="_compute_fintecture_iban"
    # )
    # fintecture_iban_bank_address = fields.Char(
    #     string="Fintecture IBAN bank address",
    #     compute="_compute_fintecture_iban"
    # )

    # ============================================================================
    # VIBAN COMPUTE METHOD - Currently disabled, keep for future use
    # ============================================================================
    # def _compute_fintecture_iban(self):
    #     """Compute IBAN fields from virtual beneficiary data."""
    #     for trx in self:
    #         if not trx.fintecture_virtual_beneficiary:
    #             trx.fintecture_iban_holder = ''
    #             trx.fintecture_iban_account = ''
    #             trx.fintecture_iban_swift_bic = ''
    #             trx.fintecture_iban_bank_name = ''
    #             trx.fintecture_iban_bank_address = ''
    #             continue
    #
    #         data = json.loads(trx.fintecture_virtual_beneficiary)
    #
    #         if not data or 'iban' not in data:
    #             trx.fintecture_iban_holder = ''
    #             trx.fintecture_iban_account = ''
    #             trx.fintecture_iban_swift_bic = ''
    #             trx.fintecture_iban_bank_name = ''
    #             trx.fintecture_iban_bank_address = ''
    #             continue
    #
    #         trx.fintecture_iban_holder = data['name']
    #         trx.fintecture_iban_account = data['iban']
    #         trx.fintecture_iban_swift_bic = data['swift_bic']
    #         trx.fintecture_iban_bank_name = data['bank_name']
    #
    #         addresses = []
    #         if 'street' in data and data['street'] != '':
    #             addresses.append(data['street'])
    #         if 'number' in data and data['number'] != '':
    #             addresses.append(data['number'])
    #         if 'zip' in data and data['zip'] != '':
    #             addresses.append(data['zip'])
    #         if 'city' in data and data['city'] != '':
    #             addresses.append(data['city'])
    #         if 'country' in data and data['country'] != '':
    #             addresses.append(data['country'])
    #         trx.fintecture_iban_bank_address = ",".join(addresses)

    def _get_specific_processing_values(self, processing_values):
        """ Override of payment to return Fintecture-specific processing values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction
        :return: The dict of provider-specific processing values
        :rtype: dict
        """
        _logger.info('|PaymentTransaction| Retrieving specific processing values...')

        res = super()._get_specific_processing_values(processing_values)

        if self.provider_code != PAYMENT_PROVIDER_NAME or self.operation != 'online_redirect':
            return res

        if self.fintecture_url and self.provider_reference:
            # Transaction already exists, generate redirect form from stored values
            redirect_form_html = f'''
                <form method="GET" action="{self.fintecture_url}">
                    <input type="hidden" name="session_id" value="{self.provider_reference}" />
                </form>
            '''
            return {
                'app_id': fintecture_utils.get_pis_app_id(self.provider_id),
                'session_id': self.provider_reference,
                'url': self.fintecture_url,
                'redirect_form_html': redirect_form_html,
            }

        try:
            _logger.info('|PaymentTransaction| Creating new payment request...')
            _logger.debug('|PaymentTransaction| provider_code: %s', self.provider_code)
            _logger.debug('|PaymentTransaction| operation: %s', self.operation)
            _logger.debug('|PaymentTransaction| company_id: %s', self.company_id.id)

            # State parameter format: company_id/unique_connection_id
            state = '{}/{}'.format(
                self.company_id.id,
                uuid.uuid4().hex
            )
            _logger.debug('|PaymentTransaction| state: %s', state)
            _logger.info('|PaymentTransaction| Calling _fintecture_create_request_pay...')

            req_pay_data = self._fintecture_create_request_pay(state)
            _logger.debug('|PaymentTransaction| req_pay_data: %s', pprint.pformat(req_pay_data))
            req_pay_data = req_pay_data['meta']
        except Exception as e:
            _logger.error('|PaymentTransaction| Error generating payment link: %s', str(e))
            _logger.exception('|PaymentTransaction| Full exception traceback:')
            raise UserError('An error occur when trying to generate the payment link. '
                            'Try again and if error persist contact your administrator for support about this.\n'
                            'Error details: %s' % str(e))

        # Generate redirect form HTML for Odoo 18
        redirect_form_html = f'''
            <form method="GET" action="{req_pay_data['url']}">
                <input type="hidden" name="session_id" value="{req_pay_data['session_id']}" />
            </form>
        '''

        return {
            'app_id': fintecture_utils.get_pis_app_id(self.provider_id),
            'session_id': req_pay_data['session_id'],
            'url': req_pay_data['url'],
            'redirect_form_html': redirect_form_html,
        }

    @api.model
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on Fintecture data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if inconsistent data were received
        :raise: ValidationError if the data match no transaction
        """
        _logger.info('|PaymentTransaction| Retrieving transaction from notification data...')
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        _logger.debug('|PaymentTransaction| tx: %r' % tx)

        if provider_code != PAYMENT_PROVIDER_NAME:
            return tx

        ir_logging_model = self.env['ir.logging']
        payment_transaction_model = self.env['payment.transaction'].sudo().with_user(SUPERUSER_ID)

        session_id = notification_data.get('session_id', False)
        _logger.debug('|PaymentTransaction| session_id: %s' % session_id)
        if not session_id:
            ir_logging_model.sudo().create({
                'name': 'fintecture.transaction.error',
                'type': 'server',
                'dbname': self.env.db,
                'level': 'DEBUG',
                'message': _("Received data without session_id parameter\nData: %s") % str(notification_data),
                'path': 'fintecture.model.payment_transaction._get_tx_from_notification_data',
                'func': '_get_tx_from_notification_data',
                'line': 188
            })
            raise ValidationError(
                "Fintecture: " + _("Received data has an invalid structure.")
            )

        found_trx = payment_transaction_model.search([
            ('provider_code', '=', PAYMENT_PROVIDER_NAME),
            ('provider_reference', '=', session_id),
        ], limit=1)
        _logger.debug('|PaymentTransaction| found_trx: %r' % found_trx)
        if not found_trx:
            raise ValidationError(
                "Fintecture: " + _("No transaction found matching reference '%s.'", session_id)
            )
        return found_trx

    def _process_notification_data(self, notification_data):
        """ Override of payment to process the transaction based on Fintecture data.

        SECURITY: This method should ONLY be called from the webhook endpoint, never from callback.
        The callback URL receives untrusted GET parameters that users can manipulate.
        Only webhook data has been cryptographically verified and can be trusted.

        Note: self.ensure_one()

        :param dict notification_data: The notification data sent by Fintecture via webhook.
                          Contains session_id, status, transfer_state, and other payment info.
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        _logger.info('|PaymentTransaction| Processing transaction with received notification data...')
        super()._process_notification_data(notification_data)
        if self.provider_code != PAYMENT_PROVIDER_NAME:
            return
        received_amount = notification_data.get('received_amount', False)

        # Handle transfer state and session status from webhook
        # Webhook provides both 'status' (session status) and 'transfer_state'
        if self.operation != 'online_redirect':
            raise ValidationError(
                "Fintecture: " + _("Invalid transaction operation.")
            )

        transfer_state = notification_data.get('transfer_state', None)
        session_status = notification_data.get('status', None)

        _logger.debug('|PaymentTransaction| transfer_state: %s', transfer_state)
        _logger.debug('|PaymentTransaction| session_status: %s', session_status)

        # Require at least one status indicator
        if not transfer_state and not session_status:
            raise ValidationError(
                "Fintecture: " + _("Received data is missing both transfer state and session status information.")
            )

        # Determine transaction state based on available information
        # Webhook provides both status indicators for comprehensive validation
        # Logic: Check each status separately and combine appropriately
        is_pending = (
            (transfer_state and transfer_state in INTENT_STATUS_MAPPING['pending']) or
            (session_status and session_status in INTENT_STATUS_MAPPING['pending'])
        )
        is_done = (
            (session_status and session_status in INTENT_STATUS_MAPPING['done']) and
            (transfer_state is None or transfer_state in INTENT_STATUS_MAPPING['done'])
        )
        is_cancelled = (
            (transfer_state and transfer_state in INTENT_STATUS_MAPPING['cancel']) or
            (session_status and session_status in INTENT_STATUS_MAPPING['cancel'])
        )
        is_draft = (
            (transfer_state and transfer_state in INTENT_STATUS_MAPPING['draft']) and
            (session_status is None or session_status in INTENT_STATUS_MAPPING['draft'])
        )

        if is_draft:
            _logger.info('|PaymentTransaction| Transaction (%r) is in draft state, no action taken' % self)
            pass
        elif is_pending:
            _logger.info('|PaymentTransaction| Setting current transaction (%r) as pending...' % self)
            self._set_pending()
        elif is_done:
            _logger.info('|PaymentTransaction| Setting current transaction (%r) as done...' % self)

            # Check if this is an additional payment (different Fintecture transaction_id)
            fintecture_transaction_id = notification_data.get('transaction_id', None)

            # Use transaction_amount if available (specific payment), otherwise received_amount (total), fallback to amount
            if notification_data.get('transaction_amount'):
                payment_amount = float(notification_data.get('transaction_amount'))
            elif received_amount:
                payment_amount = float(received_amount)
            else:
                payment_amount = float(notification_data.get('amount', self.amount))

            _logger.debug('|PaymentTransaction| Fintecture transaction_id: %s, payment_amount: %s (from transaction_amount/received_amount)',
                       fintecture_transaction_id, payment_amount)

            # If transaction is already done and we have a new transaction_id, create additional payment
            if self.state == 'done' and fintecture_transaction_id:
                _logger.debug('|PaymentTransaction| Transaction already done, checking if this is an additional payment')

                # Check if we already processed this transaction_id
                # Count existing payments (in_process or paid)
                # Note: In Odoo 18, payment states are 'draft', 'in_process', 'paid', 'cancel' - no 'posted'
                existing_payments_count = self.env['account.payment'].search_count([
                    ('payment_transaction_id', '=', self.id),
                    ('state', 'in', ['in_process', 'paid']),
                ])

                _logger.debug('|PaymentTransaction| Found %s existing posted payments for this transaction', existing_payments_count)

                # Get invoice linked to this transaction
                invoices = self.env['account.move'].search([('transaction_ids', 'in', self.id)])
                if invoices and payment_amount > 0:
                    invoice = invoices[0]
                    _logger.debug('|PaymentTransaction| Found invoice %s (id=%s), residual: %s',
                               invoice.name, invoice.id, invoice.amount_residual)

                    # Create a new payment for this additional transfer
                    # Get Fintecture payment method line
                    journal = self.provider_id.journal_id if self.provider_id.journal_id else self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
                    payment_method_line = self.env['account.payment.method.line'].search([
                        ('journal_id', '=', journal.id),
                        ('payment_method_id.code', '=', 'fintecture'),
                    ], limit=1)

                    _logger.debug('|PaymentTransaction| Using journal: %s, payment method line: %s', journal.name, payment_method_line.name if payment_method_line else 'None')

                    payment_vals = {
                        'payment_type': 'inbound',
                        'partner_type': 'customer',
                        'partner_id': invoice.partner_id.id,
                        'amount': payment_amount,
                        'currency_id': invoice.currency_id.id,
                        'date': fields.Date.context_today(self),
                        'payment_reference': f'{self.reference} - Payment #{existing_payments_count + 1}',
                        'journal_id': journal.id,
                        'payment_method_line_id': payment_method_line.id if payment_method_line else False,
                        'payment_transaction_id': self.id,
                        # Link payment to invoice - needed for auto state transition to 'paid'
                        'invoice_ids': [(4, invoice.id)],  # Many2many link
                    }

                    _logger.debug('|PaymentTransaction| Creating additional payment with values: %s', payment_vals)
                    new_payment = self.env['account.payment'].sudo().create(payment_vals)
                    _logger.debug('|PaymentTransaction| Created payment %s (id=%s)', new_payment, new_payment.id)

                    # Post the payment
                    new_payment.action_post()
                    _logger.debug('|PaymentTransaction| Posted additional payment %s', new_payment)

                    # Reconcile with the invoice
                    # In Odoo 18, payment.line_ids doesn't exist - use payment.move_id.line_ids
                    # Need to invalidate cache and reload after action_post()
                    new_payment.invalidate_recordset()
                    invoice.invalidate_recordset()

                    payment_move = new_payment.move_id
                    if not payment_move:
                        _logger.error('|PaymentTransaction| Payment has no move_id after action_post()')
                    else:
                        _logger.debug('|PaymentTransaction| Payment move: %s (id=%s)', payment_move.name, payment_move.id)

                        # Get receivable lines from both invoice and payment
                        invoice_lines = invoice.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )
                        payment_lines = payment_move.line_ids.filtered(
                            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                        )

                        _logger.debug('|PaymentTransaction| Invoice receivable lines: %s', invoice_lines.ids)
                        _logger.debug('|PaymentTransaction| Payment receivable lines: %s', payment_lines.ids)

                        lines_to_reconcile = invoice_lines + payment_lines

                        if len(lines_to_reconcile) >= 2:
                            _logger.debug('|PaymentTransaction| Reconciling %s lines', len(lines_to_reconcile))
                            lines_to_reconcile.reconcile()

                            # Refresh records after reconciliation
                            invoice.invalidate_recordset()
                            new_payment.invalidate_recordset()

                            _logger.debug('|PaymentTransaction| Reconciled payment with invoice, remaining: %s', invoice.amount_residual)

                            # Trigger payment state update
                            # Odoo auto-transitions payment to 'paid' when:
                            # - state == 'in_process'
                            # - invoice_ids are linked
                            # - all linked invoices have payment_state == 'paid'
                            # We need to trigger this check manually after reconciliation
                            new_payment.invalidate_recordset(['is_reconciled', 'is_matched'])
                            invoice.invalidate_recordset(['payment_state'])

                            # Force recompute by accessing the fields
                            _ = new_payment.is_reconciled
                            _ = invoice.payment_state

                            # If invoice is now fully paid, payment state should auto-transition
                            if new_payment.state == 'in_process' and invoice.payment_state == 'paid':
                                _logger.debug('|PaymentTransaction| Invoice fully paid, manually setting payment to paid')
                                new_payment.write({'state': 'paid'})

                            _logger.debug('|PaymentTransaction| Payment state after reconciliation: %s, is_reconciled: %s, invoice payment_state: %s',
                                       new_payment.state, new_payment.is_reconciled, invoice.payment_state)
                        else:
                            _logger.warning('|PaymentTransaction| Not enough lines to reconcile (need at least 2, found %s)', len(lines_to_reconcile))

                    # Update transaction total amount
                    total_amount = sum(self.env['account.payment'].search([
                        ('payment_transaction_id', '=', self.id),
                        ('state', 'in', ['in_process', 'paid']),
                    ]).mapped('amount'))
                    _logger.debug('|PaymentTransaction| Total payments for this transaction: %s', total_amount)
                else:
                    _logger.warning('|PaymentTransaction| No invoice found for transaction or invalid amount')
            else:
                # First payment - standard flow
                # NOTE: Tokenization is disabled for Fintecture (support_tokenization=False)
                # This branch will never execute but is kept for future extension
                if self.tokenize:
                    self._fintecture_tokenize_from_notification_data(notification_data)

                # Only call _set_done if not already done
                if self.state != 'done':
                    # Update transaction amount to match the actual payment received
                    # This is important when the first payment is partial (less than invoice amount)
                    if payment_amount != self.amount:
                        _logger.debug('|PaymentTransaction| Updating transaction amount from %s to %s before setting done',
                                   self.amount, payment_amount)
                        self.write({'amount': payment_amount})

                    _logger.debug('|PaymentTransaction| Transaction state is %s, setting to done', self.state)
                    self._set_done()
                    # NOTE: Payment reconciliation is handled in the webhook controller after _post_process()
                else:
                    _logger.debug('|PaymentTransaction| Transaction already in done state, skipping _set_done()')
            # Trigger post-processing for refund operations
            if self.operation == 'refund':
                self.env.ref('payment.cron_post_process_payment_tx')._trigger()
        elif is_cancelled:
            _logger.info('|PaymentTransaction| Canceling current transaction (%r)...' % self)
            self._set_canceled()
        else:  # classify unknown intent statuses as `error` tx state
            _logger.warning(
                '|PaymentTransaction| Unknown status - transfer_state: %s, session_status: %s',
                transfer_state, session_status
            )
            self._set_error(
                "Fintecture: " + _(
                    "Received data with invalid or unknown status (transfer_state=%s, session_status=%s)",
                    transfer_state, session_status
                )
            )

    def _fintecture_create_request_pay(self, state=None):
        _logger.info('|PaymentTransaction| Creating the URL for request to pay...')

        _logger.debug('|PaymentTransaction| _fintecture_create_request_pay(): state: {}'
                      .format(state))
        _logger.debug('|PaymentTransaction| Transaction details: id=%s, reference=%s, amount=%s, currency=%s',
                      self.id, self.reference, self.amount, self.currency_id.name)
        _logger.debug('|PaymentTransaction| Partner: id=%s, name=%s', self.partner_id.id, self.partner_id.name)
        _logger.debug('|PaymentTransaction| Provider: id=%s, code=%s', self.provider_id.id, self.provider_id.code)

        # look for connect invoice to this transaction
        am = self.env['account.move'].search([('transaction_ids', 'in', self.id)], limit=1)
        _logger.debug("|PaymentTransaction| _get_specific_processing_values(): am: %s", pprint.pformat(am))

        invoice_due_date = None
        invoice_expire_date = None
        if am:
            invoice_due_date = int((am.invoice_date_due - date.today()).total_seconds())
            # Ensure due_date is at least 1 second (Fintecture requirement: must be >= 1)
            if invoice_due_date < 1:
                invoice_due_date = 86400  # Default to 1 day if invoice is overdue
            invoice_expire_date = int(invoice_due_date + 86400)  # one day more

        _logger.debug('|PaymentTransaction| _fintecture_create_request_pay(): invoice_due_date: {}'
                      .format(invoice_due_date))
        _logger.debug('|PaymentTransaction| _fintecture_create_request_pay(): invoice_expire_date: {}'
                      .format(invoice_expire_date))

        try:
            lang = self.partner_lang.iso_code
            _logger.debug('|PaymentTransaction| Language from iso_code: %s', lang)
        except:
            try:
                lang = str(self.partner_lang).split('_')[0]
                _logger.debug('|PaymentTransaction| Language from split: %s', lang)
            except:
                lang = ''
                _logger.debug('|PaymentTransaction| Language defaulted to empty string')

        _logger.info('|PaymentTransaction| Calling provider.fintecture_pis_create_request_to_pay...')
        pay_data = self.provider_id.fintecture_pis_create_request_to_pay(
            lang_code=lang,
            partner_id=self.partner_id,
            amount=payment_utils.to_minor_currency_units(self.amount, self.currency_id) / 100,
            currency_id=self.currency_id,
            reference=self.reference,
            state=state,
            due_date=invoice_due_date,
            expire_date=invoice_expire_date,
        )

        _logger.info('|PaymentTransaction| Received pay_data from provider')
        _logger.debug('|PaymentTransaction| pay_data: %s', pprint.pformat(pay_data))

        self.provider_reference = pay_data['meta']['session_id']
        self.fintecture_payment_intent = pay_data['meta']['session_id']
        self.fintecture_url = pay_data['meta']['url']

        # ========================================================================
        # VIBAN STORAGE - Currently disabled, keep for future use
        # ========================================================================
        # if 'virtual_beneficiary' in pay_data:
        #     self.fintecture_virtual_beneficiary = json.dumps(pay_data['virtual_beneficiary'])

        _logger.info('|PaymentTransaction| Successfully created payment request with session_id: %s',
                     self.provider_reference)
        _logger.debug('|PaymentTransaction| pay_data details: %s', pprint.pformat(pay_data))
        return pay_data

    def fintecture_create_qr(self):
        self.ensure_one()
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=20,
            border=4,
        )
        qr.add_data(self.fintecture_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#000000", back_color="#FFFFFF")
        temp = BytesIO()
        img.save(temp, format="PNG")
        qr_img = base64.b64encode(temp.getvalue())
        return qr_img

    def _send_refund_request(self, amount_to_refund=None):
        """ Override of payment to send a refund request to Fintecture.

        Note: self.ensure_one()

        :param float amount_to_refund: The amount to refund.
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        refund_tx = super()._send_refund_request(amount_to_refund=amount_to_refund)
        if self.provider_code != PAYMENT_PROVIDER_NAME:
            return refund_tx

        # Make the refund request to Fintecture
        # Note: refund_tx.amount is negative (e.g., -54.0 for a 54 EUR refund)
        # We need to pass the absolute value to Fintecture API
        refund_amount = abs(refund_tx.amount)

        _logger.info(
            '|PaymentTransaction| Sending refund request for transaction %s (session_id: %s)',
            self.reference, self.provider_reference
        )
        _logger.info(
            '|PaymentTransaction| Refund amount: %s (from refund_tx.amount: %s)',
            refund_amount, refund_tx.amount
        )

        # Execute refund via Fintecture API
        refund_data = self.provider_id._fintecture_refund_payment(
            session_id=self.provider_reference,
            amount=refund_amount,
            reason=f"Refund {self.reference}"
        )

        # Update refund transaction with provider reference if available
        if refund_data and isinstance(refund_data, dict):
            refund_id = refund_data.get('id') or refund_data.get('meta', {}).get('session_id')
            if refund_id:
                refund_tx.provider_reference = refund_id
                _logger.info('|PaymentTransaction| Refund transaction provider reference: %s', refund_id)

        # Set the refund transaction as done
        # Fintecture processes refunds immediately
        refund_tx._set_done()

        _logger.info(
            '|PaymentTransaction| Refund request completed for transaction %s. Refund tx: %s',
            self.reference, refund_tx.reference
        )

        return refund_tx
