# karma/services/ledger.py
from decimal import Decimal
from django.db import transaction
from django.db import models
from karma.models import KarmaTransaction

def balance(user):
	"""
	Returns the sum of all karma deltas for the user.
	"""
	return KarmaTransaction.objects.filter(user=user).aggregate(total=models.Sum('delta'))['total'] or Decimal('0')


def earn(user, delta, reason, ref=None):
	"""
	Writes a positive karma transaction for the user.
	"""
	with transaction.atomic():
		return KarmaTransaction.objects.create(
			user=user,
			delta=Decimal(delta),
			reason=reason,
		)


def spend(user, delta, reason, ref=None):
	"""
	Checks balance, raises ValueError if insufficient, writes negative transaction.
	"""
	with transaction.atomic():
		current = balance(user)
		if current < Decimal(delta):
			raise ValueError("Insufficient karma balance")
		return KarmaTransaction.objects.create(
			user=user,
			delta=-Decimal(delta),
			reason=reason,
		)
