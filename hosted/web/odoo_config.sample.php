<?php
// Copy this to odoo_config.php on the host and fill in the real values.
// odoo_config.php holds the read-only Odoo API key and is intentionally
// NOT committed to git. live.php includes it to pull today's orders.
return [
  'ODOO_URL'     => 'https://YOUR-COMPANY.odoo.com',
  'ODOO_DB'      => 'your_db',
  'ODOO_LOGIN'   => 'you@example.com',
  'ODOO_API_KEY' => 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
];
