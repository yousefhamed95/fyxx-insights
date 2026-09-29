<?php
// Copy to auth_config.php ON THE HOST and set real passwords. The real file
// is .gitignored and must never be committed — this repository is public.
//
// Each login has a role (see role_filter.php):
//   admin - the full dashboard
//   ecom  - the e-commerce manager: E-com data only, enforced server-side
// Passwords must be digits only (the login box uses a number keypad).
if (basename(isset($_SERVER['SCRIPT_FILENAME']) ? $_SERVER['SCRIPT_FILENAME'] : '') === 'auth_config.php') {
    http_response_code(403);
    exit;
}
return array(
    'logins' => array(
        array('role' => 'admin', 'password' => 'CHANGE-ME'),
        array('role' => 'ecom',  'password' => 'CHANGE-ME-TOO'),
    ),
);
