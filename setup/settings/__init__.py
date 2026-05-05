# setup/settings/__init__.py
# DJANGO_SETTINGS_MODULE = 'setup.settings' keeps working unchanged.
from .base import *
from .oauth import *
from .services import *

# djstripe needs STRIPE_* from services and AUTH_USER_MODEL from base.
DJSTRIPE_API_KEY = STRIPE_SECRET_KEY
DJSTRIPE_WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET
DJSTRIPE_SUBSCRIBER_MODEL = AUTH_USER_MODEL
DJSTRIPE_FOREIGN_KEY_TO_FIELD = 'id'
