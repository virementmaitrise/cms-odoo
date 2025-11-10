/** @odoo-module **/

import paymentForm from '@payment/js/payment_form';

// List of provider codes handled by this module (includes all tenants)
// This module handles: fintecture, virementmaitrise, and any future tenants
const HANDLED_PROVIDER_CODES = ['fintecture', 'virementmaitrise'];

/**
 * Check if the given provider code is handled by this payment module
 * @param {string} providerCode - The provider code to check
 * @returns {boolean} - True if this module handles the provider
 */
function isHandledProvider(providerCode) {
    return HANDLED_PROVIDER_CODES.includes(providerCode);
}

/**
 * Payment form extension for Fintecture/white-label providers
 *
 * This provider uses the standard redirect flow, so no custom JavaScript is needed.
 * The base payment form handles:
 * - Transaction creation via RPC
 * - Extracting redirect_form_html from processing values
 * - Submitting the form to redirect to payment gateway
 *
 * This file only exists to:
 * - Register the provider codes as handled by this module
 * - Provide debugging logs if needed
 * - Allow future customization if needed
 */
paymentForm.include({

    /**
     * Optional: Log payment flow for debugging
     *
     * @override method from payment.payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider
     * @param {number} paymentOptionId - The id of the payment option handling the transaction
     * @param {string} paymentMethodCode - The code of the selected payment method, if any
     * @param {string} flow - The online payment flow of the transaction
     * @return {void}
     */
    async _initiatePaymentFlow(providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (isHandledProvider(providerCode)) {
            console.log('|Payment| Processing payment for provider:', providerCode);
            console.log('|Payment| Flow:', flow);
        }

        // Let the base implementation handle everything
        return this._super(...arguments);
    },

});
