"""Centralized product constants for karma and webhook behavior."""

KARMA_REWARDS_BY_TASK_TYPE = {
    'GITHUB_STAR': 5,
    'GITHUB_FORK': 5,
    'PH_COMMENT': 5,
    'WEBHOOK': 10,
}

KARMA_LOW_THRESHOLD = 20

# Webhook tasks are intentionally excluded from reciprocity obligations.
WEBHOOK_OBLIGATIONS_ENABLED = False

# Stabilizes denominator for failure-rate display.
WEBHOOK_FAILURE_RATE_EPSILON = 1e-6
