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

# Resend
RESEND_API_KEY        = os.environ.get('RESEND_API_KEY')
RESEND_FROM_EMAIL     = os.environ.get('RESEND_FROM_EMAIL')
RESEND_WEBHOOK_SECRET = os.environ.get('RESEND_WEBHOOK_SECRET', '')

# GitHub (server credential for GitHub API calls)
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
REACH = env.bool('REACH', default=False)
DAILY_REACH = env.int('DAILY_REACH', default=100)

# Procrastinate (background jobs — uses the same Postgres DATABASE_URL)
PROCRASTINATE_CONNECTORS = {
	'default': {
		'CONNECTOR': 'procrastinate.contrib.django.DjangoSyncConnector',
	}
}
