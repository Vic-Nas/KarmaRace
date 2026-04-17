"""Central formulas for configurable scoring/penalty logic.

These are code-level formulas by design (not DB config objects).
Edit values/functions here to tune behavior.
"""

BASE_BREACH_PENALTY = 10
BREACH_PENALTY_GROWTH = 1.5
MAX_BREACH_PENALTY = 200


def breach_penalty(breach_count: int) -> int:
    """Return escalating penalty based on prior breach count."""
    if breach_count < 0:
        breach_count = 0
    penalty = int(BASE_BREACH_PENALTY * (BREACH_PENALTY_GROWTH ** breach_count))
    return min(penalty, MAX_BREACH_PENALTY)
