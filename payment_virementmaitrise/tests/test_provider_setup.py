from odoo.tests import tagged

from .common import FintectureCommon
from ..const import MODULE_NAME, PAYMENT_PROVIDER_NAME


@tagged('post_install', '-at_install')
class FintectureProviderSetupTest(FintectureCommon):

    def test_provider_is_linked_to_its_module(self):
        provider = self.env.ref(f'{MODULE_NAME}.payment_provider_{PAYMENT_PROVIDER_NAME}')
        self.assertEqual(provider.module_id, self.env.ref(f'base.module_{MODULE_NAME}'))
