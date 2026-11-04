from odoo.tests import tagged

from ..const import DISPLAY_NAME
from .common import FintectureCommon


@tagged('post_install', '-at_install')
class FintectureWhiteLabelTest(FintectureCommon):

    def test_error_state_message_is_payer_friendly(self):
        tx = self._create_transaction('redirect')
        tx._process_notification_data({'status': 'payment_unsuccessful'})

        self.assertEqual(tx.state, 'error')
        self.assertEqual(tx.state_message, "The bank did not confirm the payment.")
        self.assertNotIn(DISPLAY_NAME, tx.state_message)
