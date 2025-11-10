# Virement Maitrisé Payment Provider for Odoo

Payment provider for instant bank transfers via Virement Maitrisé.

## Requirements

- Odoo 18.0+
- Python 3.10+

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Deploy Module

Copy the `payment_virementmaitrise/` directory to your `odoo/addons/` path.

### 3. Restart Odoo

```bash
sudo systemctl restart odoo
```

### 4. Activate Module

1. Go to **Apps** (enable Developer Mode if needed)
2. Click **Update Apps List**
3. Search for "Virement Maitrisé"
4. Click **Install**

## Configuration

Navigate to: **Accounting > Configuration > Payment Providers > Virement Maitrisé**

Required credentials:
- **Application ID** (App ID)
- **Application Secret** (App Secret)
- **Private Key** (PEM file content)

Get credentials from your developer console: https://console.virementmaitrise.societegenerale.eu
Don't forget to set your webhook URL in the developer console too.

## Support

- Website: http://doc.virementmaitrise.societegenerale.eu/
- Support: support@virementmaitrise.societegenerale.eu
