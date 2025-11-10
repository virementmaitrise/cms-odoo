from odoo import models, api

from ..const import PAYMENT_PROVIDER_NAME


class FintectureCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super(FintectureCompany, self).create(vals_list)
        for company in companies:
            company.fintecture_create_provider()
        return companies

    def fintecture_create_provider(self):
        rule = self.env.ref('payment.payment_provider_company_rule')
        rule.write({'active': False})
        try:
            provider = self.env.ref('payment_fintecture.payment_provider_fintecture')
        except ValueError:
            # External ID not found, provider record doesn't exist yet
            rule.write({'active': True})
            return False
        if not provider:
            rule.write({'active': True})
            return False
        for company in self:
            search_provider = self.env['payment.provider'].with_company(company).search([
                ('code', '=', PAYMENT_PROVIDER_NAME),
                ('company_id', '=', company.id)
            ], limit=1)
            if not search_provider:
                provider.sudo().copy({
                    'company_id': company.id
                })
        rule.write({'active': True})
