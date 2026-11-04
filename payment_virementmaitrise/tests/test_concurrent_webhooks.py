from types import SimpleNamespace
from unittest.mock import patch

from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo.tests import tagged

from .common import FintectureCommon
from ..const import PAYMENT_PROVIDER_NAME
from ..controllers import main
from ..controllers.main import FintectureController


@tagged('post_install', '-at_install')
class FintectureConcurrentWebhooksTest(FintectureCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enable_post_process_patcher = False
        # account_payment's install hook skips providers whose module is installed in the same run.
        if 'account.payment.method' in cls.env:
            cls.env['payment.provider']._setup_payment_method(PAYMENT_PROVIDER_NAME)
            cls.provider.journal_id.inbound_payment_method_line_ids.filtered(
                lambda line: line.code == PAYMENT_PROVIDER_NAME
            ).payment_provider_id = cls.provider

    def setUp(self):
        super().setUp()
        # The webhook's done branch reads account.payment and sale.order; the module only depends on payment.
        if 'sale.order' not in self.env:
            self.skipTest("sale is not installed")
        self.tx = self._create_transaction('redirect', provider_reference='session-concurrent')
        self.form = {
            'session_id': 'session-concurrent',
            'status': 'payment_created',
            'transfer_state': 'completed',
            'received_amount': str(self.tx.amount),
            'last_transaction_amount': str(self.tx.amount),
            'state': '1/connection',
        }

    def _send_webhook(self):
        fake_request = SimpleNamespace(env=self.env, httprequest=SimpleNamespace(form=self.form, headers={}))
        with patch.object(main, 'request', fake_request), \
                patch.object(FintectureController, '_verify_webhook_signature', return_value=dict(self.form)):
            return FintectureController().fintecture_webhook(state=self.form['state'])

    def _payment_count(self):
        return self.env['account.payment'].search_count([('payment_transaction_id', '=', self.tx.id)])

    def test_serialization_failure_is_raised_for_request_retry(self):
        error = SerializationFailure('could not serialize access due to concurrent update')
        with patch.object(type(self.tx), '_post_process', side_effect=error):
            with self.assertRaises(SerializationFailure):
                self._send_webhook()

    def test_serialization_failure_on_duplicate_webhook_is_raised(self):
        self._send_webhook()
        self.assertTrue(self.tx.is_post_processed)

        error = SerializationFailure('could not serialize access due to concurrent update')
        with patch.object(FintectureController, '_reconcile_payment_with_invoice', side_effect=error):
            with self.assertRaises(SerializationFailure):
                self._send_webhook()

    def test_duplicate_key_is_swallowed(self):
        error = UniqueViolation('duplicate key value violates unique constraint "account_payment_pkey"')
        with patch.object(type(self.tx), '_post_process', side_effect=error):
            self.assertEqual(self._send_webhook().status_code, 200)

    def test_replayed_success_webhook_creates_no_second_payment(self):
        self._send_webhook()
        self.assertEqual(self.tx.state, 'done')
        self.assertTrue(self.tx.is_post_processed)
        self.assertEqual(self._payment_count(), 1)

        with patch.object(type(self.tx), '_post_process') as post_process:
            self._send_webhook()
        post_process.assert_not_called()
        self.assertEqual(self._payment_count(), 1)
