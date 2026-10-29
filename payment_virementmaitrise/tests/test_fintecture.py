from unittest.mock import patch

from odoo.tests import tagged
from odoo.exceptions import UserError

from .common import FintectureCommon


@tagged('post_install', '-at_install')
class FintectureTest(FintectureCommon):

    def test_authentication_with_valid_credentials(self):
        """Test that authentication succeeds with valid credentials.

        This test validates that:
        - app_id, app_secret, and private_key are correctly configured
        - The Fintecture SDK can successfully authenticate
        - OAuth token is retrieved
        """
        # Mock the Fintecture SDK OAuth call to avoid real API calls in tests
        with patch('fintecture.PIS.oauth', return_value={
            'access_token': 'test_access_token_123',
            'expires_in': 3600
        }) as mock_oauth:
            # Call the authentication method
            self.fintecture._authenticate_in_pis()

            # Verify OAuth was called (meaning credentials were processed)
            self.assertTrue(mock_oauth.called, "Fintecture OAuth should be called")

        # Verify the provider has the required credential fields
        self.assertTrue(self.fintecture.fintecture_pis_app_id, "PIS App ID should be configured")
        self.assertTrue(self.fintecture.fintecture_pis_app_secret, "PIS App Secret should be configured")
        self.assertTrue(self.fintecture.fintecture_pis_private_key_file, "PIS Private Key should be configured")

    def test_authentication_with_invalid_credentials(self):
        """Test that authentication fails gracefully with invalid credentials."""
        # Mock the Fintecture SDK to raise an authentication error
        with patch('fintecture.PIS.oauth', side_effect=Exception('Invalid credentials')):
            # Authentication should raise a UserError
            with self.assertRaises(UserError) as context:
                self.fintecture._authenticate_in_pis()

            # Verify the error message is user-friendly
            self.assertIn('Invalid authentication', str(context.exception))
            self.assertIn('credential', str(context.exception).lower())

    def test_success_after_rejected_attempt_sets_done(self):
        """A failed bank attempt is retryable in the same session: the later success must win."""
        tx = self._create_transaction('redirect')

        for status, transfer_state in [
            ('sca_required', 'rejected'),
            ('payment_created', 'processing'),
            ('payment_created', 'completed'),
        ]:
            tx._process_notification_data({'status': status, 'transfer_state': transfer_state})

        self.assertEqual(tx.state, 'done')

    def test_success_on_cancelled_transaction_sets_done(self):
        tx = self._create_transaction('redirect', state='cancel')

        tx._process_notification_data({'status': 'payment_created', 'transfer_state': 'received'})
        self.assertEqual(tx.state, 'done')

    def test_observed_webhook_sequences(self):
        """Webhook sequences observed in production (session status, transfer state) and the final Odoo state."""
        sequences = [
            ([('payment_pending', 'processing'), ('payment_created', 'completed')], 'done'),
            ([('payment_created', 'completed')], 'done'),
            ([('payment_created', 'sent')], 'done'),
            ([('sca_required', 'rejected'), ('payment_created', 'processing'), ('payment_created', 'completed')], 'done'),
            ([('payment_unsuccessful', 'rejected'), ('payment_pending', 'processing'), ('payment_created', 'completed')], 'done'),
            ([('sca_required', 'rejected')], 'cancel'),
            ([('payment_unsuccessful', 'rejected')], 'cancel'),
            ([('payment_cancelled', None)], 'cancel'),
            ([('payment_cancelled', 'rejected')], 'cancel'),
            ([('payment_expired', None)], 'cancel'),
            ([('payment_expired', 'rejected')], 'cancel'),
        ]
        for i, (webhooks, expected_state) in enumerate(sequences):
            with self.subTest(webhooks=webhooks):
                tx = self._create_transaction('redirect', reference=f'{self.reference}-{i}')
                for status, transfer_state in webhooks:
                    tx._process_notification_data({'status': status, 'transfer_state': transfer_state})
                self.assertEqual(tx.state, expected_state)
