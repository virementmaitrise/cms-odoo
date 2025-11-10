import base64
import logging
import unicodedata

from werkzeug.urls import url_join

from odoo import _, api, fields, models, release
from odoo.exceptions import ValidationError, UserError

# Dynamically import from the current module's parent package
from .. import const
from ..const import CALLBACK_URL, PAYMENT_PROVIDER_NAME, MODULE_NAME, DISPLAY_NAME
from ..sdk_adapter import fintecture

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[
            (PAYMENT_PROVIDER_NAME, DISPLAY_NAME)
        ],
        ondelete={
            PAYMENT_PROVIDER_NAME: 'set default'
        }
    )
    fintecture_pis_app_id = fields.Char(
        string="PIS Application ID",
        help=f"The key solely used to identify application with {DISPLAY_NAME}",
        copy=False,
        required_if_provider=PAYMENT_PROVIDER_NAME
    )
    fintecture_pis_app_secret = fields.Char(
        string="PIS Application Secret",
        required_if_provider=PAYMENT_PROVIDER_NAME,
        copy=False,
        groups='base.group_system'
    )
    fintecture_pis_private_key_file = fields.Binary(
        string="PIS Private Key File",
        required_if_provider=PAYMENT_PROVIDER_NAME,
        copy=False,
        help=f"The private key content is saved in an external file recovered from your {DISPLAY_NAME} developer account. "
             f"This signing secret must be set to authenticate the messages sent from {DISPLAY_NAME} to Odoo.",
        groups='base.group_system'
    )
    fintecture_pis_private_key_filename = fields.Char(
        copy=False,
        string="PIS Private Key Filename"
    )
    fintecture_webhook_url = fields.Char(
        string="Webhook URL",
        compute='_compute_fintecture_webhook_url',
        help=f"Configure this webhook URL in your {DISPLAY_NAME} developer console to receive payment notifications"
    )

    # ============================================================================
    # VIBAN FIELDS - Currently disabled, keep for future use
    # ============================================================================
    # fintecture_sale_viban = fields.Boolean(
    #     string="Include virtual IBAN in quotes",
    #     default=True
    # )
    # fintecture_invoice_viban = fields.Boolean(
    #     string="Include virtual IBAN in invoices",
    #     default=True
    # )
    # fintecture_sale_link_qr = fields.Boolean(
    #     string="Include link/QR in quotes",
    #     default=False
    # )
    fintecture_invoice_link_qr = fields.Boolean(
        string="Include link/QR in invoices",
        default=False
    )
    # fintecture_viban_unique_key = fields.Selection(
    #     string="Unique key for virtual IBAN",
    #     selection=[
    #         ('invoice', 'Invoice'),
    #         ('project', 'Project'),
    #         ('journal', 'Journal'),
    #         ('customer', 'Customer'),
    #     ],
    #     default='customer',
    #     required=True
    # )

    @api.depends('code')
    def _compute_view_configuration_fields(self):
        """
        This method extends the native method in Odoo to add configuration about fintecture provider to say Odoo which
        fields we want to show/hide
        :return:
        """
        super()._compute_view_configuration_fields()
        self.filtered(lambda prov: prov.code == PAYMENT_PROVIDER_NAME).write({
            'show_payment_icon_ids': False,
            'show_pre_msg': False,
            'show_done_msg': False,
            'show_cancel_msg': False,
        })

    @api.depends('code')
    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == PAYMENT_PROVIDER_NAME).update({
            'support_refund': 'partial',
            'support_tokenization': False,
        })

    def _compute_fintecture_webhook_url(self):
        """ Compute the webhook URL for this provider """
        for provider in self:
            # Check if this provider uses our payment method by checking if the webhook method exists
            if hasattr(provider, '_get_fintecture_webhook_url') and provider.code in ['fintecture', 'virementmaitrise']:
                provider.fintecture_webhook_url = provider._get_fintecture_webhook_url()
            else:
                provider.fintecture_webhook_url = False

    # === CONSTRAINT METHODS ===#

    @api.constrains('state', 'fintecture_pis_app_id', 'fintecture_pis_app_secret')
    def _check_state_of_connected_account_is_never_test(self):
        """ Check that the provider of a connected account can never been set to 'test'.

        This constraint is defined in the present module to allow the export of the translation
        string of the `ValidationError` should it be raised by modules that would fully implement
        Fintecture Connect.

        Additionally, the field `state` is used as a trigger for this constraint to allow those
        modules to indirectly trigger it when writing on custom fields. Indeed, by always writing on
        `state` together with writing on those custom fields, the constraint would be triggered.

        :return: None
        """
        for provider in self:
            if provider.state == 'test' and provider._fintecture_has_connected_account():
                raise ValidationError(_(
                    "You cannot set the provider to Test Mode while it is linked with your Fintecture "
                    "account."
                ))

    def _fintecture_has_connected_account(self):
        """ Return whether the provider is linked to a connected Fintecture account.

        Note: This method serves as a hook for modules that would fully implement Fintecture Connect.
        Note: self.ensure_one()

        :return: Whether the provider is linked to a connected Fintecture account
        :rtype: bool
        """
        self.ensure_one()
        return False

    # ============================================================================
    # VIBAN CONSTRAINT - Currently disabled, keep for future use
    # ============================================================================
    # @api.constrains('fintecture_viban_unique_key')
    # def _check_can_use_unique_key(self):
    #     """
    #     This constraint checks when user choose a unique_key if this key may be used.
    #     If not, alert user and provide a link to install specific module.
    #     :return: Void
    #     """
    #     for provider in self:
    #         if provider.fintecture_viban_unique_key == 'project' and 'project.project' not in self.env:
    #             base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
    #             url = "{}/web#id={}&model=ir.module.module&view_type=form".format(
    #                 base_url, str(self.env.ref('base.module_project').id)
    #             )
    #             raise ValidationError(_(
    #                 "You cannot set project as unique key because you need install the project module. <a href='{}'>Install</a>".format(
    #                     url
    #                 )
    #             ))

    # === ACTION METHODS === #

    def fintecture_pis_create_request_to_pay(self, lang_code, partner_id, amount, currency_id, reference, state,
                                             due_date=None, expire_date=None):
        _logger.info('|PaymentProvider| Creating the URL for request to pay...')
        _logger.debug('|PaymentProvider| Input parameters: lang_code=%s, partner_id=%s, amount=%s, currency=%s, reference=%s',
                      lang_code, partner_id.id if partner_id else None, amount, currency_id.name if currency_id else None, reference)
        _logger.debug('|PaymentProvider| Provider state: %s', self.state)
        _logger.debug('|PaymentProvider| PIS App ID: %s', self.fintecture_pis_app_id)
        _logger.debug('|PaymentProvider| partner_id: %s', partner_id)

        try:
            _logger.info('|PaymentProvider| Authenticating with Fintecture PIS...')
            self._authenticate_in_pis()
            _logger.info('|PaymentProvider| Authentication successful')
        except Exception as e:
            _logger.error('|PaymentProvider| Authentication failed: %s', str(e))
            _logger.exception('|PaymentProvider| Full authentication error:')
            raise

        if due_date is not None and expire_date is not None and due_date >= expire_date:
            raise ValueError('Due date parameter must be lower than expiry date parameter')

        # add or subtract two more hours for expire date
        if due_date is None:
            if expire_date is not None:
                due_date = expire_date - 7200
            else:
                due_date = 86400 # 1 day

        if expire_date is None:
            if due_date is not None:
                expire_date = due_date + 7200
            else:
                expire_date = 93600

        base_url = self.get_base_url()
        # Fintecture requires HTTPS for redirect_uri
        # For local development, you need to use ngrok or similar tunneling service
        if base_url.startswith('http://localhost') :
            _logger.warning('|PaymentProvider| Using localhost without HTTPS. Fintecture requires HTTPS.')
            _logger.warning('|PaymentProvider| Please use ngrok or configure a proper domain with HTTPS.')
            # Try to force HTTPS (this will only work if you have a reverse proxy/tunnel)
            base_url = base_url.replace('http://localhost', 'https://localhost.coco')
        if base_url.startswith('http:') :
            base_url = base_url.replace('http:', 'https:')
            _logger.warning('|PaymentProvider| HTTP replaced by HTTPS.')
        redirect_url = f'{url_join(base_url, CALLBACK_URL)}'

        # ============================================================================
        # VIBAN UNIQUE KEY - Currently disabled, keep for future use
        # ============================================================================
        # unique_key = self.env.context.get('unique_key', False)
        # if not unique_key:
        #     unique_key = "customer.{}".format(str(partner_id.id))
        # unique_email_key = "{}.{}@odoo.fintecture.com".format(unique_key, str(self.fintecture_pis_app_id))

        meta = {
            'psu_name': normalize_accents(partner_id.name),
            'due_date': due_date,
            'expire': expire_date,
            # ========================================================================
            # VIBAN RECONCILIATION - Currently disabled, keep for future use
            # When VIBAN support is added, uncomment one of these reconciliation options:
            # ========================================================================
            # Option 1: Reconciliation by payer
            # "reconciliation": {
            #     "level": "payer",
            #     "match_amount": True
            # }
            # Option 2: Reconciliation by unique key
            # "reconciliation": {
            #     "level": "key",
            #     "match_amount": True,
            #     'key': "{}.{}@odoo.fintecture.com".format(
            #         unique_key,
            #         str(self.fintecture_pis_app_id)
            #     ),
            # }
        }
        if partner_id.email:
            meta['psu_email'] = partner_id.email
        if partner_id.mobile:
            meta['psu_phone'] = partner_id.mobile
        if partner_id.country_id:
            meta['psu_address'] = {
                'country': partner_id.country_id.code
            }
            if partner_id.street:
                meta['psu_address']['street'] = normalize_accents(partner_id.street)
            if partner_id.zip:
                meta['psu_address']['zip'] = partner_id.zip
            if partner_id.city:
                meta['psu_address']['city'] = partner_id.city

        data = {
            'type': 'request-to-pay',
                'attributes': {
                'amount': str(amount),
                'currency': str(currency_id.name).upper(),
                'communication': "Reference {}".format(reference)
            }
        }

        _logger.debug('|PaymentProvider| used redirect_uri: {0}'.format(redirect_url))
        _logger.debug('|PaymentProvider| used state: {0}'.format(state))
        _logger.debug('|PaymentProvider| used language: {0}'.format(lang_code))
        _logger.debug('|PaymentProvider| used meta: {0}'.format(meta))
        _logger.debug('|PaymentProvider| used data: {0}'.format(data))

        try:
            _logger.info('|PaymentProvider| Calling fintecture.PIS.request_to_pay...')
            pay_response = fintecture.PIS.request_to_pay(
                redirect_uri=redirect_url,
                state=state,
                # ====================================================================
                # VIBAN API PARAMETER - Currently disabled, keep for future use
                # Uncomment when VIBAN support is enabled:
                # with_virtualbeneficiary=True,
                # ====================================================================
                meta=meta,
                data=data,
                language=lang_code,
            )
            _logger.info('|PaymentProvider| fintecture.PIS.request_to_pay successful')
            _logger.debug('|PaymentProvider| received request to pay result: {0}'.format(pay_response))

            return pay_response
        except Exception as e:
            _logger.error('|PaymentProvider| fintecture.PIS.request_to_pay failed: %s', str(e))
            _logger.exception('|PaymentProvider| Full PIS.request_to_pay error:')
            raise

    def _fintecture_refund_payment(self, session_id, amount, reason=None):
        """ Send a refund request to Fintecture for a payment session.

        :param str session_id: The Fintecture session ID (payment intent) to refund
        :param float amount: The amount to refund (positive value)
        :param str reason: Optional reason for the refund
        :return: Refund response data from Fintecture API
        :rtype: dict
        :raise: UserError if the refund fails
        """
        self.ensure_one()

        # Convert amount to string (Fintecture API requires string format)
        amount_str = str(amount)

        self._authenticate_in_pis()

        try:
            # Retrieve the payment session
            _logger.debug('|PaymentProvider| Retrieving payment session from Fintecture...')
            session = fintecture.Payment.retrieve(session_id)
            if not session:
                raise UserError(_('Payment session %s not found.', session_id))

            _logger.debug('|PaymentProvider| Payment session retrieved successfully')
            _logger.debug('|PaymentProvider| Session data: %s', session)

            # Prepare refund data
            refund_data = {
                'attributes': {
                    "amount": amount_str,  # Must be string
                    "communication": reason if reason else f"Refund for {session_id}"
                }
            }
            _logger.info('|PaymentProvider| Refund data to send: %s', refund_data)

            # Execute the refund
            refund_response = session.refund(data=refund_data)

            _logger.info('|PaymentProvider| Refund successful for session %s', session_id)
            _logger.debug('|PaymentProvider| Refund response: %s', refund_response)

            return refund_response

        except Exception as e:
            _logger.error('|PaymentProvider| === REFUND REQUEST FAILED ===')
            _logger.error('|PaymentProvider| Session ID: %s', session_id)
            _logger.error('|PaymentProvider| Error message: %s', str(e))
            _logger.error('|PaymentProvider| Error type: %s', type(e).__name__)
            _logger.exception('|PaymentProvider| Full refund error traceback:')

            # Extract detailed error message from Fintecture API error
            error_message = str(e)
            if hasattr(e, 'json_body') and e.json_body:
                # Fintecture SDK error with JSON body
                errors = e.json_body.get('errors', [])
                if errors and isinstance(errors, list) and len(errors) > 0:
                    first_error = errors[0]
                    if isinstance(first_error, dict):
                        # Use the detailed message from the API
                        error_message = first_error.get('message', str(e))

            raise UserError(_(
                'Refund failed for Fintecture payment.\n\n'
                'Session: %s\n'
                'Error: %s', session_id, error_message
            ))

    def fintecture_webhook_signature(self, payload, digest, signature, request_id):
        _logger.info('|PaymentProvider| Retrieve webhook content and validate signature...')

        self._prepare_fintecture_environment()

        if not fintecture.private_key:
            _logger.error("|PaymentProvider| ignored webhook validation due to undefined private key")
            return False

        try:
            event = fintecture.Webhook.construct_event(
                payload, digest, signature, request_id
            )
        except ValueError as e:
            _logger.error("|PaymentProvider| Error while decoding event. Bad payload!")
            _logger.error("|PaymentProvider| ERROR: %r\n" % e)
            return False
        except fintecture.error.SignatureVerificationError as e:
            _logger.error("|PaymentProvider| Invalid signature!")
            _logger.error("|PaymentProvider| ERROR: %r\n" % e)
            return False

        return event

    def get_fintecture_provider(self):
        return self.env[self._name].sudo().search([
            ('code', '=', PAYMENT_PROVIDER_NAME),
            ('company_id', '=', self.env.company.id)
        ], limit=1)

    def _get_fintecture_webhook_url(self):
        """ Generate webhook URL based on the provider's code """
        # Use the provider's actual code instead of PAYMENT_PROVIDER_NAME to support multiple tenants
        webhook_path = f'/payment/{self.code}/webhook'
        return url_join(self.get_base_url(), webhook_path)

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != PAYMENT_PROVIDER_NAME:
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === BUSINESS METHODS - FINTECTURE ENVIRONMENT === #

    def _prepare_fintecture_environment(self):
        _logger.info('|PaymentProvider| Preparing Fintecture environment...')

        if self.state == 'test':
            fintecture.env = fintecture.environments.ENVIRONMENT_SANDBOX
        elif self.state == 'enabled':
            fintecture.env = fintecture.environments.ENVIRONMENT_PRODUCTION
        else:
            fintecture.env = fintecture.environments.ENVIRONMENT_TEST

        fintecture.app_id = self.fintecture_pis_app_id
        fintecture.app_secret = self.fintecture_pis_app_secret
        if self.fintecture_pis_private_key_file and len(self.fintecture_pis_private_key_file) > 0:
            try:
                fintecture.private_key = base64.b64decode(self.fintecture_pis_private_key_file).decode('utf-8')
            except Exception as e:
                _logger.error('|PaymentProvider| Error decoding private key certificate: %s', str(e))

        # Set custom app info to identify Odoo plugin in User-Agent
        module = self.env['ir.module.module'].sudo().search([
            ('name', '=', MODULE_NAME),
            ('state', '=', 'installed')
        ], limit=1)
        plugin_version = module.latest_version if module else 'unknown'

        fintecture.set_app_info(
            f'Odoo-{MODULE_NAME}',
            version=f'{release.version}/{plugin_version}'
        )

    def _authenticate_in_pis(self):
        _logger.info('|PaymentProvider| Authenticating with Fintecture PIS application...')

        self._prepare_fintecture_environment()

        try:
            oauth_response = fintecture.PIS.oauth()

            access_token = oauth_response['access_token']
            expires_in = oauth_response['expires_in']

            _logger.debug('|PaymentProvider| _retrieve_pis_access_token(): access_token: {0}'.format(access_token))
            _logger.debug('|PaymentProvider| _retrieve_pis_access_token(): expires_in: {0}'.format(expires_in))

            fintecture.access_token = access_token

        except Exception as e:
            _logger.error('|PaymentProvider| An error occur when trying to authenticate through oAuth...')
            _logger.error('|PaymentProvider| ERROR {0}'.format(str(e)))
            raise UserError(_('Invalid authentication. Check your credential in payment provider configuration page.'))


def normalize_accents(text):
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
