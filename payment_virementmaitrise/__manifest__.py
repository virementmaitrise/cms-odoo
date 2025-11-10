# -*- coding: utf-8 -*-

{
    'name': 'Virement Maitrisé',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Payment Providers',
    'summary': 'Payment Provider: Virement Maitrisé Implementation',
    'description': """Virement Maitrisé Payment Provider for Odoo 18 (powered by Fintecture)""",
    'website': 'http://doc.virementmaitrise.societegenerale.eu/',
    'author': 'Virement Maitrisé',
    'depends': [
        'payment'
    ],
    'data': [
        'views/payment_provider_views.xml',
        'views/payment_virementmaitrise_templates.xml',
        'views/payment_templates.xml',  # Only load the SDK on pages with a payment form.
        # NOTE: account_invoice_report.xml is loaded in post_init_hook (only if account module is installed)
        # This prevents errors when account module is not installed

        'data/payment_method_data.xml',  # Payment method definitions
        'data/payment_provider_data.xml',  # Depends on views/payment_virementmaitrise_templates.xml
    ],
    'application': True,
    'uninstall_hook': 'uninstall_hook',
    'post_init_hook': 'post_init_hook',
    'assets': {
        'web.assets_frontend': [
            'payment_virementmaitrise/static/src/js/payment_form.js',
        ],
    },
    "qweb": [],
    "installable": True,
    'application': True,
    "images": [
        "static/description/icon.png"
    ],
    "currency": "EUR",
    "price": 0.00,
    'license': 'LGPL-3',
    'python_requires': '>=3.10',
}