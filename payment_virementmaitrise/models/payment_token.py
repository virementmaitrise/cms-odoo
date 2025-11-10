# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    # ============================================================================
    # TOKENIZATION FIELDS - Currently disabled (support_tokenization=False)
    # Keep for potential future extension
    # ============================================================================
    fintecture_type = fields.Char(
        string="Fintecture Type",
        readonly=True,
    )
    fintecture_provider = fields.Char(
        string="Fintecture Bank Provider",
        readonly=True,
    )

    # one of SEPA, INSTANT_SEPA, SWIFT or FPS
    fintecture_payment_method = fields.Char(
        string="Fintecture Payment Method",
        readonly=True
    )
