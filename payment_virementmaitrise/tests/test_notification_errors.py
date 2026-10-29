from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import FintectureCommon


@tagged('post_install', '-at_install')
class FintectureNotificationErrorsTest(FintectureCommon):

    def test_error_statuses_set_transaction_in_error(self):
        for i, status in enumerate(['payment_unsuccessful', 'payment_error']):
            with self.subTest(status=status):
                tx = self._create_transaction('redirect', reference=f'{self.reference}-{i}')
                tx._process_notification_data({'status': status})
                self.assertEqual(tx.state, 'error')

    def test_notification_without_status_raises_validation_error(self):
        tx = self._create_transaction('redirect')

        with self.assertRaises(ValidationError):
            tx._process_notification_data({})
