# setup/asgi.py
"""
ASGI config for project KarmaRace.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os
import logging
import warnings
import traceback

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'setup.settings')


def _warn_with_traceback(message, category, filename, lineno, file=None, source=None):
    if issubclass(category, Warning) and 'synchronous' in str(message):
        logging.getLogger('py.warnings').warning(
            'Caught sync warning: %s\n%s',
            message,
            ''.join(traceback.format_stack()),
        )


warnings.showwarning = _warn_with_traceback

logging.getLogger('py.warnings').warning('asgi.py warning hook installed (pid=%d)', os.getpid())

application = get_asgi_application()