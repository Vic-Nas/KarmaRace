# setup/settings_services.py
"""Third-party service configurations."""
import os
import environ

env = environ.Env()
environ.Env.read_env('.env')

# Ads
ADSENSE_CLIENT_ID = env('ADSENSE_CLIENT_ID')
ADSENSE_SLOTS     = env('ADSENSE_SLOTS').split(',')

# Stripe
STRIPE_SECRET_KEY     = env('STRIPE_SECRET_KEY')
STRIPE_PRICE_ID       = env('STRIPE_PRICE_ID')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET')

# SendPulse
SENDPULSE_API_ID     = os.environ.get('SENDPULSE_API_ID')
SENDPULSE_API_SECRET = os.environ.get('SENDPULSE_API_SECRET')

# GitHub (server credential for GitHub API calls)
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REACH = env.bool('REACH', default=False)
DAILY_REACH = env.int('DAILY_REACH', default=50)
MONTHLY_REACH = env.int('MONTHLY_REACH', default=12000)

# Procrastinate (background jobs — uses the same Postgres DATABASE_URL)
PROCRASTINATE_CONNECTORS = {
	'default': {
		'CONNECTOR': 'procrastinate.contrib.django.DjangoSyncConnector',
	}
}
