"""Migration shim (plan revision 5): the HTTP solution adapter lives in
`harness.adapters.solution_http`. Removed in slice 8."""

from harness.adapters.solution_http import (
    HEALTH_TIMEOUT_S,
    SOLUTION_URL,
    TURN_TIMEOUT_S,
)
from harness.adapters.solution_http import HttpSolution as Solution
from harness.domain.observations import ChatResult

__all__ = [
    "HEALTH_TIMEOUT_S",
    "SOLUTION_URL",
    "TURN_TIMEOUT_S",
    "ChatResult",
    "Solution",
]
