"""Centralized product constants for karma and webhook behavior."""

KARMA_REWARDS_BY_TASK_TYPE = {
    'GITHUB_STAR': 5,
    'GITHUB_FORK': 5,
    'WEBHOOK': 10,
}

KARMA_LOW_THRESHOLD = 20
KARMA_HIGH_THRESHOLD = 100

# Webhook tasks are intentionally excluded from reciprocity obligations.
WEBHOOK_OBLIGATIONS_ENABLED = False

# Stabilizes denominator for failure-rate display.
WEBHOOK_FAILURE_RATE_EPSILON = 1e-6

# Webhook auto-unpublish policy based on all recorded webhook contacts.
WEBHOOK_BAD_CHECK_RATIO_THRESHOLD = 0.5
WEBHOOK_BAD_CHECK_MIN_CALLS = 5

# Owner-triggered health checks are rate limited per task.
WEBHOOK_HEALTH_CHECK_RATE_LIMIT_SECONDS = 60
