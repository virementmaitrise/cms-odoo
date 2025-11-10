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
