# Fyxx — Executive Insights

Companion dashboard to **Fyxx Live Sales** (https://fyxx-sales.streamlit.app).
This one is the executive / strategic view — multi-year KPIs, historical
trends, channel mix, top customers, salesperson leaderboard — on a dark,
neon-accented canvas.

**100% read-only.** Pulls from Odoo via XMLRPC using `search_read` only.
Nothing in Odoo is created, modified or deleted.

## Run locally

```
pip install -r requirements.txt
streamlit run app.py
```

Credentials are read from `~/.odoo-creds.env`:

```
ODOO_URL=https://your-instance.odoo.com
ODOO_DB=your-db
ODOO_LOGIN=your-login
ODOO_API_KEY=your-api-key
DASHBOARD_PASSWORD=2525
```

## Deploy

Push to a GitHub repo, then deploy as a new app on
https://share.streamlit.io. Add the same five secrets in the Streamlit
Cloud "Secrets" panel.
