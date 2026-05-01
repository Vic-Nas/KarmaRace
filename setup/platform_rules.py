"""Centralized product constants for karma and webhook behavior."""
import math

KARMA_REWARDS_BY_TASK_TYPE = {
    'GITHUB_STAR': 5,
    'GITHUB_FORK': 10,
    'WEBHOOK': 20,
}

KARMA_LOW_THRESHOLD = 20
KARMA_HIGH_THRESHOLD = 100

# Webhook obligations are now enabled — webhook <-> webhook reciprocity applies.
WEBHOOK_OBLIGATIONS_ENABLED = True

# Stabilizes denominator for failure-rate display.
WEBHOOK_FAILURE_RATE_EPSILON = 1e-6

# Webhook auto-unpublish policy based on all recorded webhook contacts.
WEBHOOK_BAD_CHECK_RATIO_THRESHOLD = 0.5
WEBHOOK_BAD_CHECK_MIN_CALLS = 5

# Owner-triggered health checks are rate limited per task.
WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS = 60

# GitHub task auto-unpublish policy based on consecutive health check failures.
GITHUB_HEALTH_HIDE_STREAK_THRESHOLD = 2


def karma_reward_for_task(owner_karma: int, task_type: str) -> int:
    """
    Reward = base * log-compressed fraction of owner karma.
    Active owners offer more, new owners stay affordable.
    Floor = base reward. Ceiling = 3x base.

    Approximate scale for WEBHOOK (base=20):
      0 karma   -> 20
      10 karma  -> 23
      50 karma  -> 27
      200 karma -> 33
      1000+     -> 60 (hard ceiling)
    """
    base = int(KARMA_REWARDS_BY_TASK_TYPE.get(task_type, 5))
    if owner_karma <= 0:
        return base
    # log2(karma+1) grows fast early, flattens at scale. /6 controls steepness.
    scale = 1.0 + min(2.0, math.log2(owner_karma + 1) / 6.0)
    return max(base, round(base * scale))
