# karma/services/cost.py
import math
from decimal import Decimal

def compute_cost(base, total_received):
	"""
	Compute the karma cost using a logarithmic formula.
	Args:
		base (Decimal): The base cost.
		total_received (int or Decimal): Total number of times received.
	Returns:
		Decimal: The computed cost.
	"""
	if total_received <= 0:
		return Decimal(base)
	return Decimal(base) * Decimal(math.log(total_received + 1, 2))
