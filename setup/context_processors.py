# setup/context_processors.py
from django.conf import settings


def ads(request):
    client = getattr(settings, 'ADSENSE_CLIENT_ID', '')
    raw_slots = getattr(settings, 'ADSENSE_SLOTS', [])
    # Normalize: could be list already or comma-split string
    if isinstance(raw_slots, str):
        raw_slots = [s.strip() for s in raw_slots.split(',')]
    slots = [s for s in raw_slots if s]  # filter empties

    return {
        'adsense_client': client,
        'adsense_slots': slots,  # up to 6; template pads with '' beyond len
    }
