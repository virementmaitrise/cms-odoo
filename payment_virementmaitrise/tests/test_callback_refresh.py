from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, tagged

from .. import sdk_adapter
from ..const import CALLBACK_URL
from .common import FintectureCommon


@tagged('post_install', '-at_install')
class FintectureCallbackRefreshTest(FintectureCommon, HttpCase):

    def _callback(self, tx, api_session=None, api_error=None):
        """Hit the callback route for tx with the SDK mocked; return the mocked Payment.retrieve."""
        sdk = MagicMock()
        sdk.PIS.oauth.return_value = {'access_token': 'token', 'expires_in': 3600}
        sdk.Payment.retrieve.return_value = api_session
        sdk.Payment.retrieve.side_effect = api_error
        with patch.object(sdk_adapter, '_sdk_module', sdk):
            response = self.url_open(f'{CALLBACK_URL}?session_id={tx.provider_reference}', allow_redirects=False)
        self.assertTrue(response.headers.get('Location', '').endswith('/payment/status'))
        tx.invalidate_recordset()
        return sdk.Payment.retrieve

    @staticmethod
    def _api_session(status, transfer_state, received_amount=None):
        attributes = {'transfer_state': transfer_state}
        if received_amount is not None:
            attributes['received_amount'] = received_amount
        return {'meta': {'status': status}, 'data': {'attributes': attributes}}

    def test_cancelled_tx_paid_after_retry_is_done(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-paid')

        retrieve = self._callback(tx, self._api_session('payment_created', 'completed'))

        self.assertEqual(tx.state, 'done')
        retrieve.assert_called_once_with('session-paid')

    def test_api_failure_keeps_state_and_redirects(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-api-down')

        self._callback(tx, api_error=Exception('API down'))

        self.assertEqual(tx.state, 'cancel')

    def test_draft_tx_does_not_call_api(self):
        tx = self._create_transaction('redirect', provider_reference='session-draft')

        retrieve = self._callback(tx, self._api_session('payment_created', 'completed'))

        retrieve.assert_not_called()
        self.assertEqual(tx.state, 'draft')

    def test_still_failed_session_stays_cancelled(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-failed')

        self._callback(tx, self._api_session('sca_required', 'rejected'))

        self.assertEqual(tx.state, 'cancel')

    def test_cancelled_tx_with_transfer_in_progress_is_pending(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-processing')

        self._callback(tx, self._api_session('payment_created', 'processing'))

        self.assertEqual(tx.state, 'pending')

    def test_errored_tx_paid_after_retry_is_done(self):
        tx = self._create_transaction('redirect', state='error', provider_reference='session-error-paid')

        self._callback(tx, self._api_session('payment_created', 'completed'))

        self.assertEqual(tx.state, 'done')

    def test_partial_payment_after_retry_books_received_amount(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-partial')
        partial = round(tx.amount / 2, 2)

        self._callback(tx, self._api_session('payment_partial', 'completed', str(partial)))

        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.amount, partial)

    def test_zero_received_amount_keeps_order_amount(self):
        tx = self._create_transaction('redirect', state='cancel', provider_reference='session-zero')
        amount = tx.amount

        self._callback(tx, self._api_session('payment_created', 'completed', '0.00'))

        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.amount, amount)

    def test_processing_webhook_does_not_reopen_cancelled_tx(self):
        tx = self._create_transaction('redirect', state='cancel')

        tx._process_notification_data({'status': 'payment_created', 'transfer_state': 'processing'})

        self.assertEqual(tx.state, 'cancel')
