"""Tasks services module. Verification, health checks, configuration, rewards."""
# Core operations
from .core import (
    verify_task_with_details,
    soft_delete_task,
    settle_or_create_obligation,
    on_task_unhidden,
)

# Health checks
from .health import (
    run_health_check,
    can_run_manual_health_check,
)

# Configuration validation
from .validate import (
    get_task_configuration_failure,
)

# GitHub utilities
from .github import (
    get_user_github_repo_choices,
    get_user_github_repo_choices_cached,
)

__all__ = [
    'verify_task_with_details',
    'soft_delete_task',
    'settle_or_create_obligation',
    'on_task_unhidden',
    'run_health_check',
    'can_run_manual_health_check',
    'get_task_configuration_failure',
    'get_user_github_repo_choices',
    'get_user_github_repo_choices_cached',
]
